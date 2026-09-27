"""Tests for the config flow."""

from __future__ import annotations

from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .fake_projector import FakeProjector
from custom_components.epson_projector_serial.const import (
    CONF_TRANSITION_TIMEOUT,
    DEFAULT_TRANSITION_TIMEOUT,
    DOMAIN,
)


async def test_user_flow(hass: HomeAssistant, projector: FakeProjector) -> None:
    """A reachable projector creates an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "127.0.0.1", CONF_PORT: projector.port, CONF_NAME: "Beamer"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Beamer"
    assert result["data"][CONF_HOST] == "127.0.0.1"
    assert result["result"].unique_id == f"127.0.0.1:{projector.port}"


@pytest.mark.parametrize(
    ("mode", "error"),
    [
        ("offline", "cannot_connect"),
        ("no_prompt", "cannot_connect"),
        ("err", "invalid_response"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant, projector: FakeProjector, mode: str, error: str
) -> None:
    """A failing projector shows an error, and the form can be retried."""
    projector.mode = mode
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "127.0.0.1", CONF_PORT: projector.port, CONF_NAME: "Beamer"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    projector.mode = "normal"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "127.0.0.1", CONF_PORT: projector.port, CONF_NAME: "Beamer"},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_bridge_aborts(
    hass: HomeAssistant, projector: FakeProjector, config_entry: MockConfigEntry
) -> None:
    """The same bridge cannot be added twice."""
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "127.0.0.1", CONF_PORT: projector.port, CONF_NAME: "Beamer"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_updates_address(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Reconfiguring moves the entry to a new address, keeping the entry."""
    moved = FakeProjector()
    await moved.start()
    try:
        result = await setup_integration.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "127.0.0.1", CONF_PORT: moved.port, CONF_NAME: "Beamer"},
        )
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
        assert setup_integration.data[CONF_PORT] == moved.port
        assert setup_integration.unique_id == f"127.0.0.1:{moved.port}"
    finally:
        await moved.stop()


async def test_reconfigure_rejects_unreachable_address(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A bad address is refused and the entry is left alone."""
    result = await setup_integration.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "127.0.0.1", CONF_PORT: 1, CONF_NAME: "Beamer"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert setup_integration.data[CONF_PORT] == projector.port


async def test_options_flow_changes_interval(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The polling interval can be changed after setup."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 30, CONF_TRANSITION_TIMEOUT: DEFAULT_TRANSITION_TIMEOUT},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_integration.options[CONF_SCAN_INTERVAL] == 30
    coordinator = setup_integration.runtime_data
    assert coordinator.update_interval.total_seconds() == 30


async def test_options_flow_sets_transition_timeout(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The warm-up/cool-down timeout is configurable, for lamp projectors."""
    coordinator = setup_integration.runtime_data
    assert coordinator.transition_timeout == timedelta(
        seconds=DEFAULT_TRANSITION_TIMEOUT
    )

    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 10, CONF_TRANSITION_TIMEOUT: 300},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_integration.options == {
        CONF_SCAN_INTERVAL: 10,
        CONF_TRANSITION_TIMEOUT: 300,
    }
    # Applied to the reloaded coordinator, not just stored.
    reloaded = setup_integration.runtime_data
    assert reloaded.transition_timeout == timedelta(seconds=300)
    assert reloaded.update_interval == timedelta(seconds=10)
