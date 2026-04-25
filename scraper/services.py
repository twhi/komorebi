import os
import json
import re
import requests
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
from ytmusicapi import YTMusic

openai_client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
ytmusic = YTMusic()


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


def calculate_match_score(target_query, yt_item):
    """Computes the fuzzy match score for a single YouTube Music result."""
    yt_artists = " ".join([artist["name"] for artist in yt_item.get("artists", [])])
    yt_str = f"{yt_artists} {yt_item['title']}".lower()

    return fuzz.token_set_ratio(target_query.lower(), yt_str)


async def ytmusic_search_worker(query):
    """Unauthenticated search via ytmusicapi."""
    try:
        loop = asyncio.get_event_loop()
        # Filter for 'songs' to get best quality matches
        results = await loop.run_in_executor(
            None, lambda: ytmusic.search(query, filter="songs", limit=5)
        )
        return results
    except Exception as e:
        logger.error(f"YTMusic search error: {e}")
        return []


async def clean_with_llm(artist, title):
    """The 'Brain' fallback: Uses GPT to clean messy radio strings."""
    prompt = f"Clean this radio track metadata for a YouTube Music search. Return ONLY a JSON object with 'artist' and 'track' keys. Raw text: {artist} - {title}"
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return f"{data.get('artist')} {data.get('track')}"
    except:
        return f"{artist} {title}"


async def fetch_ytmusic_match(artist, title):
    # --- PRE-FLIGHT SANITY CHECK ---
    if len(artist) + len(title) < 5 or "ID" in artist or "ID" in title:
        return None, 0, False

    # --- STAGE 1: FAST CLEAN & FUZZY MATCH ---
    clean_artist = fast_clean_string(artist)
    clean_title = fast_clean_string(title)

    search_query = (
        f"{clean_artist} {clean_title}" if clean_title else f"{artist} {title}"
    )

    results = await ytmusic_search_worker(search_query)
    best_id, best_score = None, 0

    if results:
        for item in results:
            score = calculate_match_score(search_query, item)
            if score > best_score:
                best_score, best_id = score, item["videoId"]

        if best_score >= 85:
            return best_id, best_score, False

    # --- STAGE 2: LLM FALLBACK ---
    should_try_llm = (not results) or (40 <= best_score < 85)

    if should_try_llm:
        llm_cleaned_query = await clean_with_llm(artist, title)

        if llm_cleaned_query.lower() == search_query.lower():
            return best_id, best_score, False

        llm_results = await ytmusic_search_worker(llm_cleaned_query)

        llm_best_id, llm_best_score = None, 0
        for item in llm_results:
            score = calculate_match_score(llm_cleaned_query, item)
            if score > llm_best_score:
                llm_best_score, llm_best_id = score, item["videoId"]

        if llm_best_score >= 80:
            return llm_best_id, llm_best_score, True

    return best_id, best_score, False


def extract_tracklist_from_url(target_url, station):
    """
    Synchronous function to handle the actual web scraping.
    Returns: (raw_data_list, show_name_string)
    """
    config = station.scraperconfig
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    soup = None

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

    show_name_el = soup.select_one(config.show_name_selector)
    show_name = (
        f"{station.name} - {show_name_el.get_text(separator=' ', strip=True)}"
        if show_name_el
        else station.name
    )

    if config.parsing_strategy == "JSON_MAPPING":
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

    elif config.parsing_strategy == "HTML_SELECTORS":
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
    final_results = []
    print(f"DEBUG: Saving {len(raw_data)} tracks for station {station}")
    for (artist, title), (yt_id, score, via_llm) in zip(raw_data, match_results):
        print(f"DEBUG: Processing {artist} - {title} | yt_id: {yt_id} | score: {score}")
        track, created = ScrapedTrack.objects.get_or_create(
            station=station, artist_raw=artist, title_raw=title
        )

        # Update if it's new, OR if the current ID is missing, OR if we have a better confidence score
        if created or not track.youtube_id or score > (track.match_confidence or 0):
            track.youtube_id = yt_id
            track.match_confidence = score
            track.matched_via_llm = via_llm
            track.save()
            print(f"DEBUG: Saved track {track.id} with youtube_id {track.youtube_id}")

        final_results.append(track)

    return final_results


def create_yt_playlist(access_token, title, description="Generated by Komorebi"):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = "https://www.googleapis.com/youtube/v3/playlists?part=snippet,status"
    body = {
        "snippet": {"title": title, "description": description},
        "status": {"privacyStatus": "private"},
    }
    resp = requests.post(url, headers=headers, json=body)
    if resp.status_code == 200:
        return resp.json()["id"]
    return None


def add_tracks_to_yt_playlist(access_token, playlist_id, video_ids):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    url = "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet"
    
    results = []
    for video_id in video_ids:
        body = {
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        }
        resp = requests.post(url, headers=headers, json=body)
        results.append(resp.status_code == 200)
    
    return results
