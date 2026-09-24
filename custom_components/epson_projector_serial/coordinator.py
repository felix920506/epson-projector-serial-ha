"""Polling coordinator for the Epson projector serial bridge."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    COMMAND_GRACE_PERIOD,
    DOMAIN,
    MAX_CONSECUTIVE_FAILURES,
    POWER_ON_CODES,
)
from .protocol import EpsonError, EpsonSerialBridge

_LOGGER = logging.getLogger(__name__)

type EpsonConfigEntry = ConfigEntry[EpsonProjectorCoordinator]


class EpsonProjectorCoordinator(DataUpdateCoordinator[bool]):
    """Poll PWR? and hold the projector's power state."""

    config_entry: EpsonConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: EpsonConfigEntry,
        bridge: EpsonSerialBridge,
        scan_interval: int,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.bridge = bridge
        self.power_code: str | None = None
        self._failures = 0
        self._commanded_state: bool | None = None
        self._grace_until: datetime | None = None

    async def _async_update_data(self) -> bool:
        """Read the projector's power state."""
        try:
            code = await self.bridge.async_query_power()
        except EpsonError as err:
            self._failures += 1
            # A busy bridge looks exactly like an unreachable one, so keep the
            # last known state for a few polls instead of flipping the switch.
            if self.data is not None and self._failures < MAX_CONSECUTIVE_FAILURES:
                _LOGGER.debug(
                    "Poll %s/%s of %s failed, keeping last state: %s",
                    self._failures,
                    MAX_CONSECUTIVE_FAILURES,
                    self.bridge.target,
                    err,
                )
                return self.data
            raise UpdateFailed(f"Error polling {self.bridge.target}: {err}") from err

        self._failures = 0
        self.power_code = code
        is_on = code in POWER_ON_CODES

        if self._in_grace_period() and is_on != self._commanded_state:
            # Still transitioning: the port answers again before the projector
            # reports the new state.
            _LOGGER.debug(
                "Ignoring PWR=%s during grace period, holding commanded state %s",
                code,
                self._commanded_state,
            )
            return bool(self._commanded_state)

        self._clear_grace_period()
        return is_on

    async def async_set_power(self, power_on: bool) -> None:
        """Send a power command and assume it took effect."""
        await self.bridge.async_set_power(power_on)
        self._failures = 0
        self._commanded_state = power_on
        self._grace_until = dt_util.utcnow() + COMMAND_GRACE_PERIOD
        self.async_set_updated_data(power_on)

    def _in_grace_period(self) -> bool:
        """Return True while a recent power command is still being trusted."""
        if self._grace_until is None:
            return False
        if dt_util.utcnow() >= self._grace_until:
            self._clear_grace_period()
            return False
        return True

    def _clear_grace_period(self) -> None:
        """Stop trusting the commanded state."""
        self._grace_until = None
        self._commanded_state = None
