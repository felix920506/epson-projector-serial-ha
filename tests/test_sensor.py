"""Tests for the raw power state sensors."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.sensor import ATTR_OPTIONS, SensorDeviceClass
from homeassistant.const import ATTR_DEVICE_CLASS, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .fake_projector import FakeProjector
from custom_components.epson_projector_serial.const import POWER_STATE_OPTIONS

STATE_SENSOR = "sensor.epson_projector_power_state"
CODE_SENSOR = "sensor.epson_projector_power_code"


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("00", "standby"),
        ("01", "on"),
        ("02", "warming_up"),
        ("03", "cooling_down"),
        ("04", "standby_network_on"),
        ("05", "abnormal_standby"),
    ],
)
async def test_sensors_report_code_and_name(
    hass: HomeAssistant,
    projector: FakeProjector,
    config_entry: MockConfigEntry,
    code: str,
    status: str,
) -> None:
    """Both the raw code and its readable name are exposed."""
    projector.power = code
    projector.transition_reads = None  # hold transitional codes still
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(CODE_SENSOR).state == code
    assert hass.states.get(STATE_SENSOR).state == status


async def test_power_state_sensor_is_an_enum(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The state sensor declares its options, so it works in UI pickers."""
    state = hass.states.get(STATE_SENSOR)
    # State attributes carry the StrEnum's value, not the member.
    assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.ENUM
    assert state.attributes[ATTR_OPTIONS] == list(POWER_STATE_OPTIONS)


async def test_unrecognised_code_reads_unknown(
    hass: HomeAssistant, projector: FakeProjector, config_entry: MockConfigEntry
) -> None:
    """A code outside the documented set is reported, but not named."""
    projector.power = "09"
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(CODE_SENSOR).state == "09"
    assert hass.states.get(STATE_SENSOR).state == STATE_UNKNOWN


async def test_sensors_distinguish_warm_up_from_on(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Warm-up is visible here even though the switch just says on."""
    projector.power = "02"
    projector.transition_reads = None
    await setup_integration.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("switch.epson_projector").state == "on"
    assert hass.states.get(STATE_SENSOR).state == "warming_up"
    assert hass.states.get(CODE_SENSOR).state == "02"
