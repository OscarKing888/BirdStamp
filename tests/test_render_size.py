from pathlib import Path

from PIL import Image

from birdstamp.models import NormalizedMetadata, RenderOptions
from birdstamp.render.banner import render_banner
from birdstamp.template_loader import load_template


def test_render_banner_height_matches_template() -> None:
    image = Image.new("RGB", (1200, 800), color="#FFFFFF")
    metadata = NormalizedMetadata(
        source=Path("sample.jpg"),
        stem="sample",
        bird="灰喜鹊",
        capture_text="2026-02-16 09:14",
        location="Beijing",
        camera="Sony ILCE-1M2",
        lens="FE 600mm F4 GM OSS",
        aperture=4.0,
        shutter_s=1 / 2000,
        iso=800,
        focal_mm=600,
    )
    template = load_template("default")
    options = RenderOptions(show_fields={"bird", "time", "location", "camera", "lens", "settings", "gps"})
    rendered = render_banner(image, metadata, template, options)
    assert rendered.size == (1200, 800 + template.banner_height)

