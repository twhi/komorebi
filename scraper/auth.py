import os
import time
import requests

from django.shortcuts import redirect, render

from spotipy.oauth2 import SpotifyOAuth


def get_valid_spotify_token(request):
    """
    Checks if the session token is valid. If expired, uses the refresh_token
    to silently fetch a new one and updates the session.
    """
    token = request.session.get("spotify_token")
    refresh_token = request.session.get("spotify_refresh_token")
    expires_at = request.session.get("spotify_token_expires_at", 0)

    # If we have no token at all, return None
    if not token:
        return None

    # We add a 60-second buffer so we don't use a token that's about to die in 1 second
    if time.time() > (expires_at - 60):
        if not refresh_token:
            return None  # We can't refresh, user must log in again

        client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")

        # Ask Spotify for a new access token
        response = requests.post(
            "https://accounts.spotify.com/api/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=(client_id, client_secret),
        )

        if response.status_code == 200:
            data = response.json()
            # Update the session with the new token and new expiry time
            request.session["spotify_token"] = data["access_token"]
            request.session["spotify_token_expires_at"] = time.time() + data.get(
                "expires_in", 3600
            )

            # Spotify sometimes returns a NEW refresh token. If so, save it.
            if "refresh_token" in data:
                request.session["spotify_refresh_token"] = data["refresh_token"]

            return data["access_token"]
        else:
            # The refresh token was revoked or failed. Nuke the session.
            request.session.pop("spotify_token", None)
            request.session.pop("spotify_refresh_token", None)
            return None

    # If it's not expired, just return the current one
    return token


def get_spotify_oauth():
    """Helper function to generate the OAuth object with the correct permissions."""
    return SpotifyOAuth(
        client_id=os.environ.get("SPOTIFY_CLIENT_ID"),
        client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.environ.get(
            "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/callback"
        ),
        scope="playlist-modify-public playlist-modify-private",
    )


def spotify_login(request):
    """Bounces the user to the official Spotify login screen."""
    sp_oauth = get_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return redirect(auth_url)


def spotify_callback(request):
    """Catches the user after they log in and saves their token."""
    sp_oauth = get_spotify_oauth()
    code = request.GET.get("code")

    if code:
        token_info = sp_oauth.get_access_token(code)
        # Save this specific user's token directly into their browser session
        request.session["spotify_token"] = token_info["access_token"]
        request.session["spotify_refresh_token"] = token_info["refresh_token"]
        request.session["spotify_token_expires_at"] = time.time() + token_info.get(
            "expires_in", 3600
        )

    return render(request, "scraper/partials/spotify_popup_close.html")
