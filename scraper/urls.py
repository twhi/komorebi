from django.urls import path
from . import views, auth

urlpatterns = [
    path("", views.scrape_url_view, name="home"),
    # YouTube Music Auth
    path("yt-login/", auth.ytmusic_login, name="ytmusic_login"),
    path("yt-finish/", auth.ytmusic_finish, name="ytmusic_finish"),
    path("kill-auth/", views.kill_ytmusic_session, name="kill_auth"),
    # Scraper HTMX partials
    path("auth-section/", views.auth_section_view, name="auth_section"),
    # Playlist actions
    path("save-to-playlist/", views.save_to_playlist_view, name="save_to_playlist"),
]
