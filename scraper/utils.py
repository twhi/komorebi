import re
import time
import requests
import os


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

        client_id = os.environ.get("SPOTIPY_CLIENT_ID")
        client_secret = os.environ.get("SPOTIPY_CLIENT_SECRET")

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


def resolve_path(data, path):
    """
    Safely navigates a dictionary/list using dot notation and indices.
    Example path: 'queries[1].state.data[0].name'
    """
    if not path:
        return None

    # Split by dots, but ignore dots inside brackets (if we ever get that complex)
    parts = re.split(r"\.(?![^\[]*\])", path)

    current = data
    for part in parts:
        try:
            # Check for array index: e.g., "queries[1]"
            match = re.match(r"(.+)\[(\d+)\]", part)
            if match:
                key, idx = match.groups()
                current = current.get(key)[int(idx)]
            else:
                current = current.get(part)
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            return None

    return current
