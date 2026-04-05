from django.urls import path
from . import views
from . import auth

urlpatterns = [
    path("", views.scrape_url_view, name="home"),
    path("login/", auth.spotify_login, name="spotify_login"),
    path("callback/", auth.spotify_callback, name="spotify_callback"),
    path("create-playlist/", views.create_playlist_view, name="create_playlist"),
    path("kill-auth/", views.kill_spotify_session, name="kill_auth"),
    path("auth-section/", views.auth_section_view, name="auth_section"),
]
