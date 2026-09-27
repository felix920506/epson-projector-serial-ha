"""Sensors exposing the projector's raw ESC/VP21 power state."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import POWER_STATE_OPTIONS
from .coordinator import EpsonConfigEntry, EpsonProjectorCoordinator
from .entity import EpsonProjectorEntity

# Both sensors read from the coordinator; neither touches the bridge.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EpsonConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the power state sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EpsonPowerStateSensor(coordinator, entry),
            EpsonPowerCodeSensor(coordinator, entry),
        ]
    )


class EpsonPowerStateSensor(EpsonProjectorEntity, SensorEntity):
    """The projector's power state, named rather than numbered.

    This reports warm-up and cool-down in their own right, which the on/off
    switch cannot: to the switch, warming up is on and cooling down is off.
    """

    _attr_translation_key = "power_state"
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(
        self, coordinator: EpsonProjectorCoordinator, entry: EpsonConfigEntry
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, "power_state")
        self._attr_options = list(POWER_STATE_OPTIONS)

    @property
    def native_value(self) -> str | None:
        """Return the named power state, or None for an unrecognised code."""
        return self.coordinator.power_status


class EpsonPowerCodeSensor(EpsonProjectorEntity, SensorEntity):
    """The raw two-digit code from the projector's PWR? reply."""

    _attr_translation_key = "power_code"

    def __init__(
        self, coordinator: EpsonProjectorCoordinator, entry: EpsonConfigEntry
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator, entry, "power_code")

    @property
    def native_value(self) -> str | None:
        """Return the ESC/VP21 power code, e.g. "02" while warming up."""
        return self.coordinator.power_code
