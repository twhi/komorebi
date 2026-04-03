import os
import httpx
import asyncio
import json
import re

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
    client_id = os.environ.get("SPOTIPY_CLIENT_ID")
    client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")

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
