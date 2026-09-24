"""Fixtures for the Epson Projector (serial bridge) tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.core import HomeAssistant

from .fake_projector import FakeProjector
from custom_components.epson_projector_serial.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load the integration from custom_components."""


@pytest.fixture
async def projector(socket_enabled: None) -> AsyncGenerator[FakeProjector]:
    """Run a fake projector for the duration of a test.

    socket_enabled lifts pytest-socket's block: the fake speaks over a real
    loopback socket so the client's own connection handling is under test.
    """
    fake = FakeProjector()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
def config_entry(projector: FakeProjector) -> MockConfigEntry:
    """Return a config entry pointed at the fake projector."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Epson Projector",
        unique_id=f"127.0.0.1:{projector.port}",
        data={
            CONF_HOST: "127.0.0.1",
            CONF_PORT: projector.port,
            CONF_NAME: "Epson Projector",
        },
    )


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> MockConfigEntry:
    """Set up the integration against the fake projector."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
