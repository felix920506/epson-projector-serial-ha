"""Tests for the projector power switch."""

from __future__ import annotations

from datetime import timedelta

import pytest
from freezegun.api import FrozenDateTimeFactory
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.epson_projector_serial.const import DOMAIN

from .fake_projector import FakeProjector

ENTITY_ID = "switch.epson_projector"


async def _poll(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: int = 30):
    """Advance time far enough to trigger a poll and let it finish."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("code", "state", "status"),
    [
        ("00", STATE_OFF, "standby"),
        ("01", STATE_ON, "on"),
        ("02", STATE_ON, "warming_up"),
        ("03", STATE_OFF, "cooling_down"),
        ("04", STATE_OFF, "standby_network_on"),
        ("05", STATE_OFF, "abnormal_standby"),
    ],
)
async def test_power_codes_map_to_state(
    hass: HomeAssistant,
    projector: FakeProjector,
    config_entry: MockConfigEntry,
    code: str,
    state: str,
    status: str,
) -> None:
    """Each ESC/VP21 power code maps to the right switch state."""
    projector.power = code
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entity = hass.states.get(ENTITY_ID)
    assert entity is not None
    assert entity.state == state
    assert entity.attributes["power_code"] == code
    assert entity.attributes["power_status"] == status


async def test_turn_on_and_off(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    projector: FakeProjector,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Turning the switch sends the command and reflects it immediately."""
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    assert b"PWR OFF" in projector.commands
    assert hass.states.get(ENTITY_ID).state == STATE_OFF

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    assert b"PWR ON" in projector.commands
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    # Warming up still reads as on once the projector answers again.
    await _poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    assert hass.states.get(ENTITY_ID).attributes["power_code"] == "02"


async def test_missing_ack_is_not_a_failure(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A power command that is never acknowledged still counts as delivered."""
    projector.mode = "silent_ack"
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    assert b"PWR OFF" in projector.commands
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_stale_reading_held_during_grace_period(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    projector: FakeProjector,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A projector still reporting standby right after PWR ON does not flip back."""
    projector.power = "00"
    await _poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF

    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
    )
    projector.power = "00"  # not caught up yet
    await _poll(hass, freezer, seconds=5)
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    # Once the grace period lapses, the projector is believed again.
    await _poll(hass, freezer, seconds=60)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF


async def test_command_failure_is_reported(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A rejected command raises instead of silently doing nothing."""
    projector.mode = "err"
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY_ID}, blocking=True
        )


async def test_busy_bridge_keeps_state_then_goes_unavailable(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    projector: FakeProjector,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Short outages keep the last state; a sustained one marks it unavailable."""
    assert hass.states.get(ENTITY_ID).state == STATE_ON

    projector.mode = "offline"
    await _poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    await _poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_ON
    await _poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE

    projector.mode = "normal"
    await _poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_ON


async def test_setup_retries_when_projector_is_unreachable(
    hass: HomeAssistant, projector: FakeProjector, config_entry: MockConfigEntry
) -> None:
    """Setup fails cleanly, so Home Assistant retries later."""
    projector.mode = "offline"
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_dribbled_reply_is_read_in_full(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    projector: FakeProjector,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A reply arriving byte by byte is still parsed correctly."""
    projector.mode = "dribble"
    projector.power = "00"
    await _poll(hass, freezer)
    assert hass.states.get(ENTITY_ID).state == STATE_OFF
    assert hass.states.get(ENTITY_ID).attributes["power_code"] == "00"


async def test_unload(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The entry unloads cleanly."""
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
