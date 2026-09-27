"""Shared base for the projector's entities."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER
from .coordinator import EpsonConfigEntry, EpsonProjectorCoordinator


class EpsonProjectorEntity(CoordinatorEntity[EpsonProjectorCoordinator]):
    """An entity belonging to one projector behind a serial bridge."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EpsonProjectorCoordinator,
        entry: EpsonConfigEntry,
        key: str,
    ) -> None:
        """Initialise the entity."""
        super().__init__(coordinator)
        host = entry.data[CONF_HOST]
        # entry_id, not host:port: the bridge's address can change without the
        # entity being a different thing.
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data.get(CONF_NAME, DEFAULT_NAME),
            manufacturer=MANUFACTURER,
            model="ESC/VP21 projector",
            configuration_url=f"http://{host}",
        )
        self._bridge_target = f"{host}:{entry.data[CONF_PORT]}"
