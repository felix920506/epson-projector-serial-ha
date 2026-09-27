"""Polling coordinator for the Epson projector serial bridge."""

from __future__ import annotations

import asyncio
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
    POWER_CODE_NAMES,
    POWER_ON_CODES,
    TRANSITION_POLL_INTERVAL,
    TRANSITION_TARGETS,
    TRANSITION_TIMEOUT,
    TRANSITIONAL_POWER_CODES,
)
from .protocol import EpsonError, EpsonRefusedError, EpsonSerialBridge

_LOGGER = logging.getLogger(__name__)

type EpsonConfigEntry = ConfigEntry[EpsonProjectorCoordinator]


class EpsonBusyError(EpsonError):
    """The projector stayed in warm-up or cool-down for too long.

    This lives here rather than in protocol.py because it is a policy decision
    about how long to wait, not something the wire protocol reports. It
    subclasses EpsonError so callers keep a single except clause.
    """


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
        self.pending_command: bool | None = None
        self._failures = 0
        self._command_lock = asyncio.Lock()
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

    @property
    def power_status(self) -> str | None:
        """Human-readable name for the current power code."""
        if self.power_code is None:
            return None
        return POWER_CODE_NAMES.get(self.power_code)

    async def async_set_power(self, power_on: bool) -> None:
        """Set the projector's power, waiting out any transition first.

        The projector rejects PWR ON/OFF while it is warming up or cooling
        down. Rather than failing the call -- and with it whatever automation
        made it -- wait for the transition to finish and then send the command.

        Calls are serialised, so a second command queues behind the first
        instead of racing it.
        """
        async with self._command_lock:
            self.pending_command = power_on
            self.async_update_listeners()
            try:
                await self._async_apply_power(power_on)
            finally:
                self.pending_command = None
                self.async_update_listeners()

    async def _async_apply_power(self, power_on: bool) -> None:
        """Read the projector, wait out any transition, then command it."""
        deadline = dt_util.utcnow() + TRANSITION_TIMEOUT
        reads = 0
        read_failures = 0
        refusal: EpsonRefusedError | None = None

        while True:
            reads += 1
            try:
                code = await self.bridge.async_query_power()
            except EpsonError:
                read_failures += 1
                # The first read is what tells us whether the projector is
                # reachable at all, so fail fast on it rather than making an
                # automation wait out the whole timeout.
                if reads == 1 or read_failures >= MAX_CONSECUTIVE_FAILURES:
                    raise
                _LOGGER.debug(
                    "Read %s of %s failed while waiting out a transition",
                    read_failures,
                    self.bridge.target,
                )
                await self._async_wait_to_retry(deadline)
                continue

            read_failures = 0
            self.power_code = code

            if code in TRANSITIONAL_POWER_CODES:
                if TRANSITION_TARGETS[code] == power_on:
                    _LOGGER.debug(
                        "PWR=%s is already heading to %s; no command needed",
                        code,
                        "on" if power_on else "off",
                    )
                    break
                # A transition explains a refusal, and gives us something to
                # wait for, so an earlier one stops being final.
                refusal = None
                _LOGGER.debug(
                    "Waiting out PWR=%s before turning %s",
                    code,
                    "on" if power_on else "off",
                )
                await self._async_wait_to_retry(deadline)
                continue

            if (code in POWER_ON_CODES) == power_on:
                _LOGGER.debug(
                    "Projector is already %s (PWR=%s)",
                    "on" if power_on else "off",
                    code,
                )
                break

            if refusal is not None:
                # It refused, and this read says it is settled, so there is
                # nothing to wait for and no reason to expect a different
                # answer. Send the refusal on rather than asking again.
                raise refusal

            try:
                await self.bridge.async_set_power(power_on)
            except EpsonRefusedError as err:
                # The state we read says this should have been accepted, so the
                # projector knows something we do not -- most likely it entered
                # a transition between the read and the command. Read it again
                # rather than repeating a command it has already declined. The
                # pause matters: the serial port lags at the start of a
                # transition, so an immediate re-read can still show the old
                # state.
                _LOGGER.debug("Power command refused, re-reading state: %s", err)
                refusal = err
                await self._async_wait_to_retry(deadline)
                continue

            break

        self._failures = 0
        self._commanded_state = power_on
        self._grace_until = dt_util.utcnow() + COMMAND_GRACE_PERIOD
        self.async_set_updated_data(power_on)

    async def _async_wait_to_retry(self, deadline: datetime) -> None:
        """Pause before looking at the projector again, or give up."""
        if dt_util.utcnow() >= deadline:
            raise EpsonBusyError(
                f"{self.bridge.target} did not settle within "
                f"{TRANSITION_TIMEOUT.total_seconds():.0f}s"
            )
        await asyncio.sleep(TRANSITION_POLL_INTERVAL)

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
