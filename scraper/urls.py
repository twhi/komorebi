from django.urls import path
from . import views

urlpatterns = [
    path("", views.scrape_url_view, name="home"),
    path("login/", views.spotify_login, name="spotify_login"),
    path("callback/", views.spotify_callback, name="spotify_callback"),
    path("create-playlist/", views.create_playlist_view, name="create_playlist"),
]
