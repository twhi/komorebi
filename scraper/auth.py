import os
import time
import requests
import json
from django.shortcuts import redirect, render
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from ytmusicapi.auth.oauth import OAuthCredentials


def get_valid_ytmusic_token(request):
    """
    Checks if the session token is valid. If expired, uses the refresh_token
    to silently fetch a new one and updates the session.
    """
    token = request.session.get("ytmusic_access_token")
    refresh_token = request.session.get("ytmusic_refresh_token")
    expires_at = request.session.get("ytmusic_token_expires_at", 0)

    if not token:
        return None

    if time.time() > (expires_at - 60):
        if not refresh_token:
            return None

        client_id = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")

        response = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )

        if response.status_code == 200:
            data = response.json()
            request.session["ytmusic_access_token"] = data["access_token"]
            request.session["ytmusic_token_expires_at"] = int(time.time() + data.get("expires_in", 3600))
            if "refresh_token" in data:
                request.session["ytmusic_refresh_token"] = data["refresh_token"]
            return data["access_token"]
        else:
            request.session.pop("ytmusic_access_token", None)
            request.session.pop("ytmusic_refresh_token", None)
            return None

    return token


def ytmusic_login(request):
    """Starts the YouTube OAuth device flow using ytmusicapi credentials."""
    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        return JsonResponse({"error": "Missing YOUTUBE_CLIENT_ID or YOUTUBE_CLIENT_SECRET"}, status=500)

    try:
        session = requests.Session()
        creds = OAuthCredentials(client_id, client_secret, session)
        code_data = creds.get_code()
        
        request.session["ytmusic_device_code"] = code_data["device_code"]
        request.session.modified = True

        return JsonResponse({
            "user_code": code_data["user_code"],
            "verification_url": code_data["verification_url"],
            "interval": code_data.get("interval", 5)
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@csrf_exempt
@require_POST
def ytmusic_finish(request):
    """Exchanges the device code for tokens. CSRF exempt for convenience in this flow."""
    device_code = request.session.get("ytmusic_device_code")
    if not device_code:
        return JsonResponse({"error": "session_expired", "message": "No pending OAuth session found. Please restart the login."}, status=400)

    client_id = os.environ.get("YOUTUBE_CLIENT_ID")
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
    }

    try:
        response = requests.post("https://oauth2.googleapis.com/token", data=data)
        response_json = response.json()

        if "error" in response_json:
            if response_json["error"] == "authorization_pending":
                return JsonResponse({"error": "authorization_pending", "message": "Still waiting for authorization..."}, status=200)
            return JsonResponse(response_json, status=400)

        # Success
        request.session["ytmusic_access_token"] = response_json["access_token"]
        if "refresh_token" in response_json:
            request.session["ytmusic_refresh_token"] = response_json["refresh_token"]
        request.session["ytmusic_token_expires_at"] = int(time.time() + response_json.get("expires_in", 3600))
        
        if "ytmusic_device_code" in request.session:
            del request.session["ytmusic_device_code"]
        
        return JsonResponse({"success": True})
    except Exception as e:
        return JsonResponse({"error": "server_error", "message": str(e)}, status=500)
