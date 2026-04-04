import httpx
import asyncio
import spotipy
import logging

from django.shortcuts import render, redirect
from django.contrib import messages
from asgiref.sync import sync_to_async
from urllib.parse import urlparse

from .auth import get_valid_spotify_token
from .models import RadioStation, ScrapedTrack
from .services import (
    get_spotify_token,
    fetch_spotify_match,
    extract_tracklist_from_url,
    save_scraped_tracks,
    fetch_user_playlists,
)

logger = logging.getLogger("scraper")


async def scrape_url_view(request):
    get_token_safe = sync_to_async(get_valid_spotify_token, thread_sensitive=True)
    spotify_token = await get_token_safe(request)

    # ==========================================
    # POST REQUEST HANDLING (Scraping)
    # ==========================================
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
            logger.warning(f"No config found for {domain}")
            messages.error(request, f"No config found for {domain}")
            return render(
                request, "scraper/index.html", {"spotify_token": spotify_token}
            )

        # 2. Scrape
        raw_data, show_name = await asyncio.to_thread(
            extract_tracklist_from_url, target_url, station
        )

        logger.info(
            f"Data successfully fetched for {target_url}. Found {len(raw_data)} tracks."
        )

        # 3. Parallel Spotify Search
        async with httpx.AsyncClient() as client:
            token = await get_spotify_token(client)
            tasks = [
                fetch_spotify_match(client, token, artist, title)
                for artist, title in raw_data
            ]
            match_results = await asyncio.gather(*tasks)

        # 4. Batch Save to DB
        final_results = await sync_to_async(save_scraped_tracks, thread_sensitive=True)(
            station, raw_data, match_results
        )

        # Save state to session so the GET fallthrough can pick it up
        request.session["last_track_ids"] = [track.id for track in final_results]
        request.session["last_show_name"] = show_name
        request.session["last_station_id"] = station.id

    # ==========================================
    # GET REQUEST HANDLING & POST FALLTHROUGH
    # ==========================================
    restored_results = []
    show_name = None
    station_id = None
    user_playlists = []

    # 1. Restore tracks from session (Handles both GET redirects and fresh POSTs)
    if "last_track_ids" in request.session:
        track_ids = request.session["last_track_ids"]
        show_name = request.session.get("last_show_name")
        station_id = request.session.get("last_station_id")

        def get_restored_tracks():
            tracks_dict = ScrapedTrack.objects.in_bulk(track_ids)
            return [tracks_dict[tid] for tid in track_ids if tid in tracks_dict]

        restored_results = await sync_to_async(
            get_restored_tracks, thread_sensitive=True
        )()

        # Clear session
        del request.session["last_track_ids"]
        if "last_show_name" in request.session:
            del request.session["last_show_name"]
        if "last_station_id" in request.session:
            del request.session["last_station_id"]

    # 2. Fetch User Playlists (Delegated to services.py)
    if restored_results and spotify_token:
        user_playlists = await fetch_user_playlists(spotify_token)

    context = {
        "spotify_token": spotify_token,
        "results": restored_results if restored_results else None,
        "show_name": show_name,
        "station_id": station_id,
        "user_playlists": user_playlists,
    }

    return render(request, "scraper/index.html", context)


def create_playlist_view(request):
    if request.method == "POST":
        spotify_token = request.session.get("spotify_token")

        if not spotify_token:
            messages.error(request, "You must connect to Spotify first.")
            return redirect("home")

        playlist_action = request.POST.get("playlist_action")
        playlist_name = request.POST.get("playlist_name")
        track_uris = request.POST.getlist("track_uris")

        if not track_uris:
            messages.warning(request, "No tracks were available to add.")
            return redirect("home")

        sp = spotipy.Spotify(auth=spotify_token)

        try:
            user_profile = sp.current_user()
            user_id = user_profile["id"]

            target_playlist_id = None
            display_name = ""

            if playlist_action == "new":
                playlist = sp.user_playlist_create(
                    user=user_id, name=playlist_name, public=False
                )
                target_playlist_id = playlist["id"]
                display_name = playlist_name
                action_text = "Playlist created successfully! Added"
            else:
                target_playlist_id = playlist_action
                try:
                    existing_playlist = sp.playlist(target_playlist_id, fields="name")
                    display_name = existing_playlist["name"]
                except spotipy.SpotifyException:
                    display_name = "your existing playlist"

                action_text = "Successfully added"

            for i in range(0, len(track_uris), 100):
                chunk = track_uris[i : i + 100]
                sp.playlist_add_items(target_playlist_id, chunk)

            messages.success(
                request, f"{action_text} {len(track_uris)} tracks to '{display_name}'."
            )

        except Exception as e:
            logger.error(f"Failed to handle playlist: {str(e)}")
            messages.error(request, f"Failed to process playlist: {str(e)}")

    return redirect("home")
