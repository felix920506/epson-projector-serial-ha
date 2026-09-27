"""Polling coordinator for the Epson projector serial bridge."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    COMMAND_GRACE_PERIOD,
    DOMAIN,
    MAX_CONSECUTIVE_BUSY_POLLS,
    MAX_CONSECUTIVE_FAILURES,
    POWER_CODE_NAMES,
    POWER_ON_CODES,
    TRANSITION_POLL_INTERVAL,
    TRANSITION_TARGETS,
    TRANSITIONAL_POWER_CODES,
)
from .protocol import (
    EpsonConnectionError,
    EpsonError,
    EpsonSerialBridge,
    EpsonUnreachableError,
)

_LOGGER = logging.getLogger(__name__)

type EpsonConfigEntry = ConfigEntry[EpsonProjectorCoordinator]


class EpsonBusyError(EpsonError):
    """The projector stayed in warm-up or cool-down for too long.

    This lives here rather than in protocol.py because it is a policy decision
    about how long to wait, not something the wire protocol reports. It
    subclasses EpsonError so callers keep a single except clause.
    """


# Which translated message explains each failure. Looked up along the
# exception's MRO, so a subclass inherits its parent's message.
ERROR_TRANSLATION_KEYS: dict[type[EpsonError], str] = {
    EpsonBusyError: "projector_busy",
    EpsonUnreachableError: "cannot_connect",
    EpsonConnectionError: "cannot_connect",
}
DEFAULT_ERROR_TRANSLATION_KEY = "command_failed"


def _translation_key(err: EpsonError) -> str:
    """Return the translation key that best describes this failure."""
    for cls in type(err).__mro__:
        if cls in ERROR_TRANSLATION_KEYS:
            return ERROR_TRANSLATION_KEYS[cls]
    return DEFAULT_ERROR_TRANSLATION_KEY


class EpsonProjectorCoordinator(DataUpdateCoordinator[bool]):
    """Poll PWR? and hold the projector's power state."""

    config_entry: EpsonConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: EpsonConfigEntry,
        bridge: EpsonSerialBridge,
        scan_interval: int,
        transition_timeout: int,
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
        self.transition_timeout = timedelta(seconds=transition_timeout)
        self.power_code: str | None = None
        self.pending_command: bool | None = None
        self._failures = 0
        self._busy_polls = 0
        self._command_lock = asyncio.Lock()
        self._commanded_state: bool | None = None
        self._grace_until: datetime | None = None

    async def _async_update_data(self) -> bool:
        """Read the projector's power state."""
        try:
            code = await self.bridge.async_query_power()
        except EpsonUnreachableError as err:
            # No connection at all. Keep the last state briefly anyway, since
            # the bridge takes one connection at a time and may be occupied.
            self._failures += 1
            if self.data is not None and self._failures < MAX_CONSECUTIVE_FAILURES:
                _LOGGER.debug(
                    "Poll %s/%s could not connect to %s, keeping last state: %s",
                    self._failures,
                    MAX_CONSECUTIVE_FAILURES,
                    self.bridge.target,
                    err,
                )
                return self.data
            raise UpdateFailed(f"Cannot reach {self.bridge.target}: {err}") from err
        except EpsonError as err:
            # Reachable but not talking: a quiet serial port, a refused PWR?, a
            # truncated reply. The projector does all of this during a
            # transition, so tolerate it for much longer than a dead bridge --
            # otherwise the entities drop out partway through every warm-up.
            self._busy_polls += 1
            if self.data is not None and self._busy_polls < MAX_CONSECUTIVE_BUSY_POLLS:
                _LOGGER.debug(
                    "Poll %s/%s of %s got no usable answer, keeping last state: %s",
                    self._busy_polls,
                    MAX_CONSECUTIVE_BUSY_POLLS,
                    self.bridge.target,
                    err,
                )
                return self.data
            raise UpdateFailed(
                f"{self.bridge.target} is not answering usefully: {err}"
            ) from err

        self._failures = 0
        self._busy_polls = 0
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

        Failures are raised as HomeAssistantError with a translated message, so
        every caller gets something Home Assistant can report properly. Errors
        we do not anticipate are left alone: they are bugs, and swallowing the
        traceback would only hide them.
        """
        async with self._command_lock:
            self.pending_command = power_on
            self.async_update_listeners()
            try:
                await self._async_apply_power(power_on)
            except EpsonError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key=_translation_key(err),
                    translation_placeholders={
                        "bridge": self.bridge.target,
                        "error": str(err),
                    },
                ) from err
            finally:
                self.pending_command = None
                self.async_update_listeners()

    async def _async_apply_power(self, power_on: bool) -> None:
        """Wait until the projector will accept the command, then send it.

        Only an unreachable bridge fails fast. Everything else -- a refused
        query, a refused command, a transition in progress -- means the
        projector is there but not ready, so it is waited out. A projector that
        never becomes ready fails on the deadline, which is a backstop rather
        than an expected outcome.
        """
        deadline = dt_util.utcnow() + self.transition_timeout

        while True:
            try:
                code = await self.bridge.async_query_power()
            except EpsonUnreachableError:
                # Nothing to wait for: no connection to the bridge at all.
                raise
            except EpsonError as err:
                # Reachable, but it will not say what state it is in. It does
                # this while busy -- a transition refuses PWR? as well as
                # PWR ON/OFF -- so ask again shortly.
                _LOGGER.debug(
                    "%s would not report its state: %s", self.bridge.target, err
                )
                await self._async_wait_to_retry(deadline, str(err))
                continue

            self.power_code = code

            if code in TRANSITIONAL_POWER_CODES:
                if TRANSITION_TARGETS[code] == power_on:
                    _LOGGER.debug(
                        "PWR=%s is already heading to %s; no command needed",
                        code,
                        "on" if power_on else "off",
                    )
                    break
                _LOGGER.debug(
                    "Waiting out PWR=%s before turning %s",
                    code,
                    "on" if power_on else "off",
                )
                await self._async_wait_to_retry(deadline, f"PWR={code}")
                continue

            if (code in POWER_ON_CODES) == power_on:
                _LOGGER.debug(
                    "Projector is already %s (PWR=%s)",
                    "on" if power_on else "off",
                    code,
                )
                break

            try:
                await self.bridge.async_set_power(power_on)
            except EpsonUnreachableError:
                raise
            except EpsonError as err:
                # Refused. The state we read said this should be accepted, so
                # the projector knows something we do not -- it can slip into a
                # transition between the read and the command, and it refuses
                # commands for a moment either side of one. Wait and look
                # again rather than failing a caller who only asked for the
                # state the projector is going to reach anyway.
                _LOGGER.debug("Power command refused, will look again: %s", err)
                await self._async_wait_to_retry(deadline, str(err))
                continue

            break

        self._failures = 0
        self._busy_polls = 0
        self._commanded_state = power_on
        self._grace_until = dt_util.utcnow() + COMMAND_GRACE_PERIOD
        self.async_set_updated_data(power_on)

    async def _async_wait_to_retry(self, deadline: datetime, reason: str) -> None:
        """Pause before looking at the projector again, or give up."""
        if dt_util.utcnow() >= deadline:
            raise EpsonBusyError(
                f"{self.bridge.target} was still not ready to accept the "
                f"command after {self.transition_timeout.total_seconds():.0f}s "
                f"({reason})"
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
