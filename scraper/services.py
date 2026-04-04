import os
import json
import re
import requests
import json
import logging
import httpx
import asyncio

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from .models import ScrapedTrack
from .utils import resolve_path

logger = logging.getLogger("scraper")

from thefuzz import fuzz
from openai import AsyncOpenAI

openai_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


def fast_clean_string(text):
    """
    Instantly strips common track junk using Regex so we don't waste LLM calls.
    Removes (feat. X), [Remix], (Original Mix), etc.
    """
    # Remove text inside parentheses or brackets
    text = re.sub(r"[\(\[].*?[\)\]]", "", text)
    # Remove common DJ noise
    text = re.sub(r"(?i)\b(ft|feat|featuring|remix|edit|dub|mix)\b.*", "", text)
    # Clean up multiple spaces and trim
    return re.sub(r"\s+", " ", text).strip()


def calculate_match_score(target_query, spotify_item):
    """Computes the fuzzy match score for a single Spotify result."""
    # We combine all artists listed on the Spotify track
    spot_artists = " ".join([artist["name"] for artist in spotify_item["artists"]])
    spot_str = f"{spot_artists} {spotify_item['name']}".lower()

    # Using token_set_ratio: if the target is a subset of the Spotify string
    # (or vice-versa), it scores much higher, ignoring extra features/words.
    return fuzz.token_set_ratio(target_query.lower(), spot_str)


async def spotify_search_worker(http_client, token, query):
    search_url = "https://api.spotify.com/v1/search"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"q": query, "type": "track", "limit": 5}

    try:
        resp = await http_client.get(
            search_url, headers=headers, params=params, timeout=5.0
        )
        return resp.json().get("tracks", {}).get("items", [])
    except Exception:
        return []


async def clean_with_llm(artist, title):
    """The 'Brain' fallback: Uses GPT to clean messy radio strings."""
    prompt = f"Clean this radio track metadata for a Spotify search. Return ONLY a JSON object with 'artist' and 'track' keys. Raw text: {artist} - {title}"
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        print(f"--- LLM CLEAN ---")
        print(f"RAW: {artist} - {title}")
        print(f"CLEANED: {data.get('artist')} {data.get('track')}")
        return f"{data.get('artist')} {data.get('track')}"
    except:
        return f"{artist} {title}"


async def get_spotify_token(client):
    """Fetch a temporary access token from Spotify."""
    auth_url = "https://accounts.spotify.com/api/token"
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")

    resp = await client.post(
        auth_url,
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
    )
    return resp.json().get("access_token")


async def fetch_spotify_match(http_client, token, artist, title):
    # --- PRE-FLIGHT SANITY CHECK ---
    if len(artist) + len(title) < 5 or "ID" in artist or "ID" in title:
        return None, 0, False

    # --- STAGE 1: FAST CLEAN & FUZZY MATCH ---
    clean_artist = fast_clean_string(artist)
    clean_title = fast_clean_string(title)

    # If the regex wiped out the title entirely (e.g., track was literally just "(Remix)"), fallback to raw
    search_query = (
        f"{clean_artist} {clean_title}" if clean_title else f"{artist} {title}"
    )

    results = await spotify_search_worker(http_client, token, search_query)
    best_uri, best_score = None, 0

    if results:
        for item in results:
            score = calculate_match_score(search_query, item)
            if score > best_score:
                if "pluto" in search_query.lower():
                    print("new best score", score)
                    w = 0
                best_score, best_uri = score, item["uri"]

        # We can safely raise the threshold to 85 because token_set_ratio is more forgiving
        if best_score >= 85:
            return best_uri, best_score, False

    # --- STAGE 2: LLM FALLBACK (The Decision Gate) ---
    should_try_llm = (not results) or (40 <= best_score < 85)

    if should_try_llm:
        llm_cleaned_query = await clean_with_llm(artist, title)

        if llm_cleaned_query.lower() == search_query.lower():
            return best_uri, best_score, False

        llm_results = await spotify_search_worker(http_client, token, llm_cleaned_query)

        llm_best_uri, llm_best_score = None, 0
        for item in llm_results:
            score = calculate_match_score(llm_cleaned_query, item)
            if score > llm_best_score:
                llm_best_score, llm_best_uri = score, item["uri"]

        if llm_best_score >= 80:
            return llm_best_uri, llm_best_score, True
    else:
        print("skipping llm stuff for", artist, title)

    return best_uri, best_score, False


def extract_tracklist_from_url(target_url, station):
    """
    Synchronous function to handle the actual web scraping.
    Returns: (raw_data_list, show_name_string)
    """
    config = station.scraperconfig
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    soup = None

    # 1. FETCH HTML
    if config.scraper_type == "HEADLESS_BROWSER":
        logger.info(f"Spinning up headless browser for {target_url}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            page = context.new_page()
            try:
                page.goto(target_url, wait_until="networkidle")
                soup = BeautifulSoup(page.content(), "html.parser")
            except Exception as e:
                logger.error(f"Playwright error: {e}")
            finally:
                browser.close()
                logger.info("Successful playwright session - terminating")
    else:
        response = requests.get(target_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

    if not soup:
        return [], None

    # 2. EXTRACT SHOW NAME
    show_name_el = soup.select_one(config.show_name_selector)
    show_name = (
        f"{station.name} - {show_name_el.get_text(separator=' ', strip=True)}"
        if show_name_el
        else station.name
    )

    # 3. EXTRACT TRACKS
    if config.scraper_type == "JSON_MAPPING":
        next_data_script = soup.find("script", id="__NEXT_DATA__")
        if next_data_script:
            full_json = json.loads(next_data_script.string)
            tracks_array = resolve_path(full_json, config.json_root_path)

            if isinstance(tracks_array, list):
                extracted = []
                for item in tracks_array:
                    artist = resolve_path(item, config.json_artist_path)
                    title = resolve_path(item, config.json_title_path)
                    if artist and title:
                        extracted.append((str(artist).strip(), str(title).strip()))
                return extracted, show_name

    else:
        containers = soup.select(config.container_selector)
        extracted = [
            (
                c.select_one(config.artist_selector).text.strip(),
                c.select_one(config.track_title_selector).text.strip(),
            )
            for c in containers
            if c.select_one(config.artist_selector)
            and c.select_one(config.track_title_selector)
        ]
        return extracted, show_name

    return [], show_name


def save_scraped_tracks(station, raw_data, match_results):
    """
    Synchronous function to handle batch saving to the database.
    By doing this in one sync function, we avoid hitting the async loop
    for every single track iteration.
    """
    final_results = []
    for (artist, title), (uri, score, via_llm) in zip(raw_data, match_results):
        track, created = ScrapedTrack.objects.get_or_create(
            station=station, artist_raw=artist, title_raw=title
        )

        if created or score > (track.match_confidence or 0):
            track.spotify_uri = uri
            track.match_confidence = score
            track.matched_via_llm = via_llm
            track.save()

        final_results.append(track)

    return final_results


async def fetch_user_playlists(spotify_token):
    """
    Asynchronous function to rapidly fetch all pages of a user's Spotify playlists.
    """
    headers = {"Authorization": f"Bearer {spotify_token}"}
    base_url = "https://api.spotify.com/v1"

    async with httpx.AsyncClient() as client:
        # Get user profile and first page of playlists concurrently
        user_task = client.get(f"{base_url}/me", headers=headers)
        first_page_task = client.get(
            f"{base_url}/me/playlists?limit=50&offset=0", headers=headers
        )

        user_res, first_page_res = await asyncio.gather(user_task, first_page_task)

        if user_res.status_code != 200 or first_page_res.status_code != 200:
            return []

        user_id = user_res.json()["id"]
        first_page_data = first_page_res.json()

        all_playlists = first_page_data.get("items", [])
        total_playlists = first_page_data.get("total", 0)

        # Fetch remaining pages concurrently
        if total_playlists > 50:
            offsets = range(50, total_playlists, 50)
            tasks = [
                client.get(
                    f"{base_url}/me/playlists?limit=50&offset={offset}", headers=headers
                )
                for offset in offsets
            ]
            responses = await asyncio.gather(*tasks)

            for res in responses:
                if res.status_code == 200:
                    all_playlists.extend(res.json().get("items", []))

        return [
            {"id": p["id"], "name": p["name"]}
            for p in all_playlists
            if p and (p["owner"]["id"] == user_id or p.get("collaborative"))
        ]
