import httpx
import asyncio
import logging

from django.shortcuts import render, redirect
from django.contrib import messages
from asgiref.sync import sync_to_async
from urllib.parse import urlparse, parse_qs

from .auth import get_valid_ytmusic_token
from .models import RadioStation, ScrapedTrack
from .services import (
    fetch_ytmusic_match,
    extract_tracklist_from_url,
    save_scraped_tracks,
    create_yt_playlist,
    add_tracks_to_yt_playlist,
)

logger = logging.getLogger("scraper")


def kill_ytmusic_session(request):
    if "ytmusic_access_token" in request.session:
        del request.session["ytmusic_access_token"]
    if "ytmusic_refresh_token" in request.session:
        del request.session["ytmusic_refresh_token"]
    if "ytmusic_token_expires_at" in request.session:
        del request.session["ytmusic_token_expires_at"]
    request.session.flush()
    return redirect("home")


def auth_section_view(request):
    """Returns only the Connect/Connected button partial."""
    token = get_valid_ytmusic_token(request)
    return render(
        request, "scraper/partials/auth_section.html", {"ytmusic_token": token}
    )


async def scrape_url_view(request):
    get_token_safe = sync_to_async(get_valid_ytmusic_token, thread_sensitive=True)
    ytmusic_token = await get_token_safe(request)

    display_results = None
    show_name = None
    station_id = None

    if request.method == "POST":
        target_url = request.POST.get("target_url")
        parsed_url = urlparse(target_url)
        domain = parsed_url.netloc

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
                request, "scraper/index.html", {"ytmusic_token": ytmusic_token}
            )

        raw_data, show_name = await asyncio.to_thread(
            extract_tracklist_from_url, target_url, station
        )
        station_id = station.id

        logger.info(
            f"Data successfully fetched for {target_url}. Found {len(raw_data)} tracks."
        )

        # Parallel YouTube Music Search (unauthenticated)
        tasks = [
            fetch_ytmusic_match(artist, title)
            for artist, title in raw_data
        ]
        match_results = await asyncio.gather(*tasks)

        # Batch Save to DB
        display_results = await sync_to_async(
            save_scraped_tracks, thread_sensitive=True
        )(station, raw_data, match_results)

    context = {
        "ytmusic_token": ytmusic_token,
        "results": display_results,
        "show_name": show_name,
        "station_id": station_id,
    }

    if request.headers.get("HX-Request"):
        return render(request, "scraper/partials/results_card.html", context)

    return render(request, "scraper/index.html", context)


def save_to_playlist_view(request):
    if request.method == "POST":
        ytmusic_token = get_valid_ytmusic_token(request)

        if not ytmusic_token:
            messages.error(request, "You must connect to YouTube Music first.")
            return redirect("home")

        playlist_action = request.POST.get("playlist_action") # 'new' or 'existing'
        playlist_name = request.POST.get("playlist_name")
        playlist_url = request.POST.get("playlist_url")
        track_ids = request.POST.getlist("track_ids")

        if not track_ids:
            messages.warning(request, "No tracks were available to add.")
            return redirect("home")

        try:
            target_playlist_id = None
            
            if playlist_action == "new":
                target_playlist_id = create_yt_playlist(ytmusic_token, playlist_name)
                if not target_playlist_id:
                    raise Exception("Failed to create new playlist.")
                action_text = "Playlist created successfully! Added"
                display_name = playlist_name
            else:
                # Extract playlist ID from URL if necessary
                if "list=" in playlist_url:
                    parsed = urlparse(playlist_url)
                    target_playlist_id = parse_qs(parsed.query).get("list", [None])[0]
                else:
                    target_playlist_id = playlist_url # Assume it's the ID
                
                if not target_playlist_id:
                    raise Exception("Invalid Playlist URL or ID.")
                
                action_text = "Successfully added"
                display_name = "your existing playlist"

            results = add_tracks_to_yt_playlist(ytmusic_token, target_playlist_id, track_ids)
            success_count = sum(results)

            messages.success(
                request, f"{action_text} {success_count} tracks to '{display_name}'."
            )

        except Exception as e:
            logger.error(f"Failed to handle playlist: {str(e)}")
            messages.error(request, f"Failed to process playlist: {str(e)}")

    return redirect("home")
