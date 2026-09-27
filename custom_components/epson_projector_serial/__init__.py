"""The Epson Projector (serial bridge) integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_TRANSITION_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TRANSITION_TIMEOUT,
)
from .coordinator import EpsonConfigEntry, EpsonProjectorCoordinator
from .protocol import EpsonSerialBridge

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: EpsonConfigEntry) -> bool:
    """Set up a projector from a config entry."""
    bridge = EpsonSerialBridge(entry.data[CONF_HOST], entry.data[CONF_PORT])
    coordinator = EpsonProjectorCoordinator(
        hass,
        entry,
        bridge,
        entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        entry.options.get(CONF_TRANSITION_TIMEOUT, DEFAULT_TRANSITION_TIMEOUT),
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EpsonConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: EpsonConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)
