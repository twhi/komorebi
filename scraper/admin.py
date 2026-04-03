from django.contrib import admin
from .models import RadioStation, ScraperConfig, ScrapedTrack


class ScraperConfigInline(admin.StackedInline):
    model = ScraperConfig
    can_delete = False


@admin.register(RadioStation)
class RadioStationAdmin(admin.ModelAdmin):
    list_display = ("name", "base_url", "is_active")
    inlines = [ScraperConfigInline]


@admin.register(ScrapedTrack)
class ScrapedTrackAdmin(admin.ModelAdmin):
    list_display = (
        "artist_raw",
        "title_raw",
        "station",
        "scraped_at",
        "match_confidence",
    )
    list_filter = ("station", "matched_via_llm")
    search_fields = ("artist_raw", "title_raw")
