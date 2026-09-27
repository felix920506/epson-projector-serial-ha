"""Switch platform for the Epson Projector (serial bridge) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EpsonConfigEntry, EpsonProjectorCoordinator
from .entity import EpsonProjectorEntity
from .protocol import EpsonError

# The bridge takes one connection at a time; never overlap service calls.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EpsonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the projector power switch."""
    async_add_entities([EpsonProjectorSwitch(entry.runtime_data, entry)])


class EpsonProjectorSwitch(EpsonProjectorEntity, SwitchEntity):
    """Power switch for a projector speaking ESC/VP21 over a serial bridge."""

    _attr_name = None
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_icon = "mdi:projector"

    def __init__(
        self, coordinator: EpsonProjectorCoordinator, entry: EpsonConfigEntry
    ) -> None:
        """Initialise the switch."""
        super().__init__(coordinator, entry, "power")

    @property
    def is_on(self) -> bool | None:
        """Return True when the projector is on or warming up."""
        return self.coordinator.data

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the raw ESC/VP21 state alongside plain on/off."""
        pending = self.coordinator.pending_command
        return {
            "power_code": self.coordinator.power_code,
            "power_status": self.coordinator.power_status,
            "pending_command": (
                None if pending is None else ("on" if pending else "off")
            ),
            "bridge": self._bridge_target,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the projector on."""
        await self._async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the projector off."""
        await self._async_set_power(False)

    async def _async_set_power(self, power_on: bool) -> None:
        """Send the power command, surfacing failures to the caller."""
        try:
            await self.coordinator.async_set_power(power_on)
        except EpsonError as err:
            raise HomeAssistantError(
                f"Failed to send power command to {self._bridge_target}: {err}"
            ) from err
