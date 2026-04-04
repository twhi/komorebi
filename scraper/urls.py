from django.urls import path
from . import views
from . import auth

urlpatterns = [
    path("", views.scrape_url_view, name="home"),
    path("login/", auth.spotify_login, name="spotify_login"),
    path("callback/", auth.spotify_callback, name="spotify_callback"),
    path("create-playlist/", views.create_playlist_view, name="create_playlist"),
    path("clear/", views.clear_results_view, name="clear_results"),
]
