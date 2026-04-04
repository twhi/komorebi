import httpx
import asyncio
import requests
import spotipy
import json
import logging

from django.shortcuts import render, redirect
from django.contrib import messages

from asgiref.sync import sync_to_async
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from .auth import get_valid_spotify_token
from .utils import resolve_path
from .models import RadioStation, ScrapedTrack
from .services import get_spotify_token, fetch_spotify_match

logger = logging.getLogger("scraper")


async def scrape_url_view(request):

    get_token_safe = sync_to_async(get_valid_spotify_token, thread_sensitive=True)
    spotify_token = await get_token_safe(request)

    if request.method == "POST":
        target_url = request.POST.get("target_url")
        parsed_url = urlparse(target_url)
        domain = parsed_url.netloc

        # 1. Async DB Lookup for Station
        get_station = sync_to_async(
            lambda: RadioStation.objects.filter(
                base_url__icontains=domain, is_active=True
            ).first(),
            thread_sensitive=True,
        )
        station = await get_station()

        if not station:
            messages.error(request, f"No config found for {domain}")
            return render(request, "scraper/index.html")

        # 2. Scrape (Sync)
        # We run this in a thread so it doesn't block the async loop
        def do_scrape():
            config = station.scraperconfig
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

            response = requests.get(target_url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            show_name = f"{station.name} - {soup.select_one(config.show_name_selector).get_text(
                separator=" ", strip=True
            )}"

            try:

                # --- STRATEGY 1: JSON EXTRACTION ---
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
                                    extracted.append(
                                        (str(artist).strip(), str(title).strip())
                                    )
                            if extracted:
                                return extracted, show_name

                # --- STRATEGY 2: HTML FALLBACK ---
                elif config.scraper_type == "STANDARD":
                    containers = soup.select(config.container_selector)
                    return [
                        (
                            c.select_one(config.artist_selector).text.strip(),
                            c.select_one(config.track_title_selector).text.strip(),
                        )
                        for c in containers
                        if c.select_one(config.artist_selector)
                        and c.select_one(config.track_title_selector)
                    ], show_name

            except Exception as e:
                print(f"Scrape failed: {e}")

            return [], None

        raw_data, show_name = await asyncio.to_thread(do_scrape)

        # 3. Parallel Spotify Search
        async with httpx.AsyncClient() as client:
            token = await get_spotify_token(client)
            tasks = [
                fetch_spotify_match(client, token, artist, title)
                for artist, title in raw_data
            ]
            match_results = await asyncio.gather(*tasks)

        # 4. Batch Save and Fetch with Eager Loading
        final_results = []
        for (artist, title), (uri, score, via_llm) in zip(raw_data, match_results):

            def get_and_prepare_track(a=artist, t=title, u=uri, s=score, v=via_llm):
                # 1. Get the track, or create a blank one
                track, created = ScrapedTrack.objects.get_or_create(
                    station=station, artist_raw=a, title_raw=t
                )

                # 2. If it's new, OR if our new algorithm found a better score, update it!
                # (We use "or 0" just in case your old records have a null match_confidence)
                if created or s > (track.match_confidence or 0):
                    track.spotify_uri = u
                    track.match_confidence = s
                    track.matched_via_llm = v
                    track.save()

                return track

            track_obj = await sync_to_async(
                get_and_prepare_track, thread_sensitive=True
            )()
            final_results.append(track_obj)

        # CRITICAL: If we are passing the station ID to the template,
        # let's just pass it as a standalone variable to be safe.
        context = {
            "results": final_results,
            "station_id": station.id,
            "show_name": show_name,
            "spotify_token": spotify_token,
        }
        return render(request, "scraper/index.html", context)

    context = {"spotify_token": spotify_token}
    return render(request, "scraper/index.html", context)


def create_playlist_view(request):
    if request.method == "POST":
        spotify_token = request.session.get("spotify_token")

        if not spotify_token:
            messages.error(request, "You must connect to Spotify first.")
            return redirect("home")

        playlist_name = request.POST.get("playlist_name")
        track_uris = request.POST.getlist("track_uris")

        # Initialize Spotipy strictly with the logged-in user's token
        sp = spotipy.Spotify(auth=spotify_token)

        try:
            # 1. Identify the user
            user_profile = sp.current_user()
            user_id = user_profile["id"]

            # 2. Create the blank playlist
            playlist = sp.user_playlist_create(
                user=user_id, name=playlist_name, public=False
            )

            # 3. Add tracks in chunks of 100 to obey Spotify's API limits
            for i in range(0, len(track_uris), 100):
                chunk = track_uris[i : i + 100]
                sp.playlist_add_items(playlist["id"], chunk)

            messages.success(
                request,
                f"Playlist created successfully! Added {len(track_uris)} tracks to your Spotify library.",
            )

        except Exception as e:
            messages.error(request, f"Failed to create playlist: {str(e)}")

    return redirect("home")
