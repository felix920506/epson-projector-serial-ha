"""Tests that failures reach Home Assistant as translated errors."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import translation

from .fake_projector import FakeProjector
from custom_components.epson_projector_serial import coordinator as coordinator_module
from custom_components.epson_projector_serial.const import DOMAIN

SWITCH_ENTITY = "switch.epson_projector"
# Read at import time: doing it inside an async test would block the loop.
EXCEPTION_STRINGS: dict[str, dict[str, str]] = json.loads(
    Path("custom_components/epson_projector_serial/strings.json").read_text()
)["exceptions"]


async def _turn_on(hass: HomeAssistant) -> None:
    """Ask the switch to turn on."""
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: SWITCH_ENTITY}, blocking=True
    )


async def test_unreachable_bridge_raises_translated_error(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A bridge that cannot be reached reports cannot_connect."""
    projector.mode = "offline"

    with pytest.raises(HomeAssistantError) as caught:
        await _turn_on(hass)

    assert caught.value.translation_domain == DOMAIN
    assert caught.value.translation_key == "cannot_connect"
    assert caught.value.translation_placeholders["bridge"] == (
        f"127.0.0.1:{projector.port}"
    )


async def test_projector_that_never_accepts_reports_busy(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A projector that keeps refusing reports projector_busy, not a refusal.

    A refusal on its own is not an error -- it is waited out -- so the only
    thing left to report is that it never became ready.
    """
    projector.power = "05"
    projector.transition_reads = None
    projector.reject_commands = 99

    with (
        patch.object(
            coordinator_module, "TRANSITION_TIMEOUT", timedelta(milliseconds=200)
        ),
        pytest.raises(HomeAssistantError) as caught,
    ):
        await _turn_on(hass)

    assert caught.value.translation_domain == DOMAIN
    assert caught.value.translation_key == "projector_busy"


async def test_stuck_transition_raises_translated_error(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A projector stuck mid-transition reports projector_busy."""
    projector.power = "03"
    projector.transition_reads = None

    with (
        patch.object(
            coordinator_module, "TRANSITION_TIMEOUT", timedelta(milliseconds=200)
        ),
        pytest.raises(HomeAssistantError) as caught,
    ):
        await _turn_on(hass)

    assert caught.value.translation_domain == DOMAIN
    assert caught.value.translation_key == "projector_busy"


def test_every_error_has_a_message() -> None:
    """Each translation key the code can raise has a message to show.

    Without this, a failure would surface as a bare key and nobody would know
    until it happened in front of a user.
    """
    declared = set(EXCEPTION_STRINGS)
    used = set(coordinator_module.ERROR_TRANSLATION_KEYS.values())
    used.add(coordinator_module.DEFAULT_ERROR_TRANSLATION_KEY)

    assert used <= declared, f"no message for {sorted(used - declared)}"
    assert declared <= used, f"unused message for {sorted(declared - used)}"


async def test_home_assistant_can_render_every_message(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Home Assistant finds and formats each message, placeholders and all.

    The static check above only proves the keys line up. This proves Home
    Assistant can actually resolve them, which is what a user sees.
    """
    translations = await translation.async_get_translations(
        hass, "en", "exceptions", [DOMAIN]
    )
    placeholders = {"bridge": "10.0.0.5:8002", "error": "something went wrong"}

    for key in EXCEPTION_STRINGS:
        localize_key = f"component.{DOMAIN}.exceptions.{key}.message"
        assert localize_key in translations, f"{key} is not discoverable"

        rendered = translations[localize_key].format(**placeholders)
        assert "{" not in rendered, f"{key} has an unfilled placeholder"
        assert placeholders["bridge"] in rendered
