"""Tests that Home Assistant can find the integration's own brand images.

Since 2026.3 a custom integration serves brand images from a brand/ directory
next to its manifest, in preference to the CDN. Without it the UI shows an
"icon not available" placeholder.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from homeassistant.components.brands.const import ALLOWED_IMAGES
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.epson_projector_serial.const import DOMAIN

BRAND_DIR = Path("custom_components/epson_projector_serial/brand")
SHIPPED = ("icon.png", "icon@2x.png", "logo.png", "logo@2x.png")


async def test_home_assistant_sees_the_branding(hass: HomeAssistant) -> None:
    """has_branding is what gates serving local images, and it is a directory check."""
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.has_branding
    assert (Path(integration.file_path) / "brand").is_dir()


@pytest.mark.parametrize("name", SHIPPED)
def test_filenames_are_ones_home_assistant_will_serve(name: str) -> None:
    """A name outside this set is ignored, so a typo would fail silently."""
    assert name in ALLOWED_IMAGES
    assert (BRAND_DIR / name).is_file()


@pytest.mark.parametrize(("name", "side"), [("icon.png", 256), ("icon@2x.png", 512)])
def test_icons_are_square_and_the_required_size(name: str, side: int) -> None:
    """The brands spec requires a 1:1 aspect ratio at exactly these sizes."""
    with Image.open(BRAND_DIR / name) as im:
        assert im.size == (side, side)
        assert im.mode == "RGBA"


@pytest.mark.parametrize(
    ("name", "low", "high"), [("logo.png", 128, 256), ("logo@2x.png", 256, 512)]
)
def test_logo_short_side_is_within_spec(name: str, low: int, high: int) -> None:
    """The spec constrains a logo's shortest side, not its width."""
    with Image.open(BRAND_DIR / name) as im:
        assert low <= min(im.size) <= high
        assert im.mode == "RGBA"


@pytest.mark.parametrize("name", ("logo.png", "logo@2x.png"))
def test_logos_are_trimmed(name: str) -> None:
    """Empty space around the mark is meant to be cropped off."""
    with Image.open(BRAND_DIR / name) as im:
        assert im.getchannel("A").getbbox() == (0, 0, *im.size)


@pytest.mark.parametrize("name", SHIPPED)
def test_backgrounds_are_transparent(name: str) -> None:
    """Transparency is preferred, and these sit on light and dark themes."""
    with Image.open(BRAND_DIR / name) as im:
        assert im.getchannel("A").getextrema()[0] == 0
