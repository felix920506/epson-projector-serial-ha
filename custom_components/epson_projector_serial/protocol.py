"""ESC/VP21 client for an Epson projector behind a TCP-to-serial bridge.

Every command performs the full ESC/VP21 handshake::

    connect -> send CR -> wait for the ':' ready prompt -> send command ->
    read the reply -> close

The bridge accepts a single connection at a time, so an attempt can fail
simply because something else is holding the port. Commands are therefore
serialised behind a lock and retried a few times before giving up.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 1.5
PROMPT_TIMEOUT = 1.5
QUERY_TIMEOUT = 1.0
ACK_TIMEOUT = 1.5
RETRY_DELAY = 0.4
# Power commands retry hard because a lost one is user-visible. Queries retry
# less, so a poll cannot outlast the polling interval by much; the coordinator
# tolerates a few failed polls anyway.
COMMAND_ATTEMPTS = 3
QUERY_ATTEMPTS = 2
READ_SIZE = 64

PROMPT = b":"
TERMINATOR = b"\r"
ERROR_REPLY = b"ERR"

POWER_QUERY = b"PWR?"
POWER_ON_COMMAND = b"PWR ON"
POWER_OFF_COMMAND = b"PWR OFF"
POWER_REPLY_RE = re.compile(rb"PWR=(\d{2})")

# Tells the read loop when a reply is complete. Bridges hand bytes over in
# small chunks, so "the prefix arrived" is not the same as "the reply arrived".
type ReplyMatcher = Callable[[bytes], bool]


def _prompt_received(buffer: bytes) -> bool:
    """Return True once the projector has sent its ready prompt."""
    return PROMPT in buffer


def _power_reply_received(buffer: bytes) -> bool:
    """Return True once a complete two-digit PWR code has arrived."""
    return POWER_REPLY_RE.search(buffer) is not None


class EpsonError(Exception):
    """Base error for the ESC/VP21 client."""


class EpsonConnectionError(EpsonError):
    """The bridge could not be reached or did not offer a ready prompt."""


class EpsonCommandError(EpsonError):
    """The projector gave an unusable reply: truncated, or never sent."""


class EpsonRefusedError(EpsonCommandError):
    """The projector answered ERR.

    A refusal is a considered answer, not a glitch, so it is not retried here:
    whatever the projector is objecting to will still be true a fraction of a
    second later. The caller knows why it might be refused -- a projector
    mid-transition will not accept power commands -- and can re-read the state
    and decide. Retrying blind just spends the projector's patience.
    """


class EpsonSerialBridge:
    """Talk ESC/VP21 to a projector reachable over a TCP-to-serial bridge."""

    def __init__(self, host: str, port: int) -> None:
        """Initialise the client."""
        self._host = host
        self._port = port
        self._lock = asyncio.Lock()

    @property
    def target(self) -> str:
        """Return the bridge address, for logging and error messages."""
        return f"{self._host}:{self._port}"

    async def async_query_power(self) -> str:
        """Return the two-digit PWR code reported by the projector."""
        reply = await self._async_execute(
            POWER_QUERY,
            matcher=_power_reply_received,
            read_timeout=QUERY_TIMEOUT,
            attempts=QUERY_ATTEMPTS,
        )
        match = POWER_REPLY_RE.search(reply)
        if match is None:  # pragma: no cover - the matcher guarantees this
            raise EpsonCommandError(f"No PWR code in reply {reply!r}")
        return match.group(1).decode("ascii")

    async def async_set_power(self, power_on: bool) -> None:
        """Switch the projector on or off."""
        command = POWER_ON_COMMAND if power_on else POWER_OFF_COMMAND
        # PWR ON/OFF frequently do not acknowledge inside the read window
        # because the projector is already busy transitioning, so a missing
        # ack is not treated as a failure. Reaching the ready prompt before
        # sending is what proves the command landed.
        await self._async_execute(
            command, matcher=None, read_timeout=ACK_TIMEOUT, attempts=COMMAND_ATTEMPTS
        )

    async def _async_execute(
        self,
        command: bytes,
        *,
        matcher: ReplyMatcher | None,
        read_timeout: float,
        attempts: int,
    ) -> bytes:
        """Run a command, retrying while the bridge is busy."""
        async with self._lock:
            last_error: EpsonError = EpsonCommandError(
                f"No attempt made for {command!r}"
            )
            for attempt in range(attempts):
                if attempt:
                    await asyncio.sleep(RETRY_DELAY)
                try:
                    return await self._async_attempt(command, matcher, read_timeout)
                except EpsonRefusedError:
                    raise
                except EpsonError as err:
                    last_error = err
                    _LOGGER.debug(
                        "Attempt %s/%s of %r on %s failed: %s",
                        attempt + 1,
                        attempts,
                        command,
                        self.target,
                        err,
                    )
            raise last_error

    async def _async_attempt(
        self, command: bytes, matcher: ReplyMatcher | None, read_timeout: float
    ) -> bytes:
        """Perform a single handshake and return whatever the reply was."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), CONNECT_TIMEOUT
            )
        except (OSError, TimeoutError) as err:
            raise EpsonConnectionError(
                f"Cannot connect to {self.target}: {err}"
            ) from err

        try:
            writer.write(TERMINATOR)
            await writer.drain()

            _, ready = await self._async_read(reader, _prompt_received, PROMPT_TIMEOUT)
            if not ready:
                raise EpsonConnectionError(
                    f"No ready prompt from {self.target} within {PROMPT_TIMEOUT}s"
                )

            writer.write(command + TERMINATOR)
            await writer.drain()

            reply, complete = await self._async_read(
                reader, matcher or _prompt_received, read_timeout
            )
        except OSError as err:
            raise EpsonConnectionError(
                f"Lost {self.target} mid-command: {err}"
            ) from err
        finally:
            await self._async_close(writer)

        if ERROR_REPLY in reply:
            raise EpsonRefusedError(f"Projector returned ERR to {command!r}")
        if matcher is not None and not complete:
            # A reply that never arrived, or arrived truncated. Only queries
            # insist on one; power commands pass matcher=None.
            raise EpsonCommandError(
                f"Incomplete reply to {command!r} within {read_timeout}s"
                f" (got {reply!r})"
            )
        return reply

    async def _async_read(
        self, reader: asyncio.StreamReader, matcher: ReplyMatcher, read_timeout: float
    ) -> tuple[bytes, bool]:
        """Read until the reply is complete, the peer closes, or time is up."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + read_timeout
        buffer = b""
        while not matcher(buffer):
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                chunk = await asyncio.wait_for(reader.read(READ_SIZE), remaining)
            except TimeoutError:
                break
            if not chunk:  # bridge hung up
                break
            buffer += chunk
        return buffer, matcher(buffer)

    async def _async_close(self, writer: asyncio.StreamWriter) -> None:
        """Close the connection so the single-connection bridge frees up."""
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), CONNECT_TIMEOUT)
        except (OSError, TimeoutError) as err:
            _LOGGER.debug("Error closing connection to %s: %s", self.target, err)
