from django.db import models


class RadioStation(models.Model):
    name = models.CharField(max_length=200)
    base_url = models.URLField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class ScraperConfig(models.Model):

    # define fetchers and parsers
    class FetchMethod(models.TextChoices):
        STANDARD = "STANDARD", "Standard Requests"
        HEADLESS_BROWSER = "HEADLESS_BROWSER", "Headless Browser (Playwright)"

    class ParseStrategy(models.TextChoices):
        HTML_SELECTORS = "HTML_SELECTORS", "HTML CSS Selectors"
        JSON_MAPPING = "JSON_MAPPING", "Next.js JSON Mapping"

    scraper_type = models.CharField(
        max_length=20,
        choices=FetchMethod.choices,
        default=FetchMethod.STANDARD,
        help_text="How should we fetch the page?",
    )

    parsing_strategy = models.CharField(
        max_length=20,
        choices=ParseStrategy.choices,
        default=ParseStrategy.HTML_SELECTORS,
        help_text="How should we extract the data?",
    )

    station = models.OneToOneField(RadioStation, on_delete=models.CASCADE)

    # HTML Selectors
    show_name_selector = models.CharField(max_length=255)
    container_selector = models.CharField(max_length=255, blank=True)
    artist_selector = models.CharField(max_length=255, blank=True)
    track_title_selector = models.CharField(max_length=255, blank=True)

    # JSON Selectors
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

    def __str__(self):
        return f"Config for {self.station.name}"


class ScrapedTrack(models.Model):
    station = models.ForeignKey(RadioStation, on_delete=models.CASCADE)
    artist_raw = models.CharField(max_length=255)
    title_raw = models.CharField(max_length=255)
    scraped_at = models.DateTimeField(auto_now_add=True)

    youtube_id = models.CharField(max_length=255, blank=True, null=True)
    match_confidence = models.FloatField(null=True, blank=True)
    matched_via_llm = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.artist_raw} - {self.title_raw}"
