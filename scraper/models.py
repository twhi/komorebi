from django.db import models


class RadioStation(models.Model):
    name = models.CharField(max_length=200)
    base_url = models.URLField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class ScraperConfig(models.Model):
    station = models.OneToOneField(RadioStation, on_delete=models.CASCADE)

    show_name_selector = models.CharField(max_length=255)

    # HTML Fallback / Standard Selectors
    container_selector = models.CharField(max_length=255, blank=True)
    artist_selector = models.CharField(max_length=255, blank=True)
    track_title_selector = models.CharField(max_length=255, blank=True)

    # NEW: JSON Mapping (The "Next.js" Strategy)
    # This allows us to store "props.pageProps.dehydratedState.queries[1].state.data.data[1].data"
    json_root_path = models.CharField(
        max_length=500, blank=True, help_text="Path to the tracks array"
    )
    json_artist_path = models.CharField(
        max_length=255,
        blank=True,
        help_text="Relative path to artist name inside an item",
    )
    json_title_path = models.CharField(
        max_length=255,
        blank=True,
        help_text="Relative path to track title inside an item",
    )

    # Strategy Toggle
    use_json_data = models.BooleanField(
        default=False,
        help_text="If checked, look for __NEXT_DATA__ before falling back to HTML",
    )

    def __str__(self):
        return f"Config for {self.station.name}"


class ScrapedTrack(models.Model):
    station = models.ForeignKey(RadioStation, on_delete=models.CASCADE)
    artist_raw = models.CharField(max_length=255)
    title_raw = models.CharField(max_length=255)
    scraped_at = models.DateTimeField(auto_now_add=True)

    spotify_uri = models.CharField(max_length=255, blank=True, null=True)
    match_confidence = models.FloatField(null=True, blank=True)
    matched_via_llm = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.artist_raw} - {self.title_raw}"
