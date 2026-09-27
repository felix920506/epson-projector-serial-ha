"""A fake ESC/VP21 projector behind a TCP-to-serial bridge."""

from __future__ import annotations

import asyncio

# Where a transitional code settles once the transition finishes.
SETTLES_TO = {"02": "01", "03": "00"}


class FakeProjector:
    """Serve just enough ESC/VP21 to exercise the integration."""

    def __init__(self, power: str = "01") -> None:
        """Initialise the fake projector in the given power state."""
        self.power = power
        # "normal", "offline", "no_prompt", "err", "silent_ack" or "dribble".
        self.mode = "normal"
        self.commands: list[bytes] = []
        # How many PWR? reads report a transitional code before it settles.
        # None holds the transition open indefinitely.
        self.transition_reads: int | None = 0
        # How many of the next power commands to refuse outright, whatever the
        # power state says.
        self.reject_commands = 0
        self._server: asyncio.Server | None = None
        self.port = 0

    @property
    def rejects_power_commands(self) -> bool:
        """Real projectors refuse PWR ON/OFF mid-transition."""
        return self.power in SETTLES_TO

    async def start(self) -> int:
        """Start listening on a free port and return it."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        """Stop listening."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle one ESC/VP21 session."""
        try:
            if self.mode == "offline":
                return
            if self.mode == "no_prompt":
                # Hold the connection open, silently, for longer than the
                # client waits for the ready prompt. Server.wait_closed waits
                # on handlers, so keep it tight.
                await asyncio.sleep(2)
                return

            await reader.read(64)  # the leading CR
            writer.write(b":")
            await writer.drain()

            line = b""
            while not line.endswith(b"\r"):
                char = await reader.read(1)
                if not char:
                    return
                line += char
            command = line.strip()
            self.commands.append(command)

            if self.mode == "err":
                await self._send(writer, b"ERR\r:")
            elif command == b"PWR?":
                await self._send(writer, b"PWR=" + self.power.encode() + b"\r:")
                self._advance_transition()
            elif command in (b"PWR ON", b"PWR OFF"):
                if self.reject_commands > 0:
                    self.reject_commands -= 1
                    await self._send(writer, b"ERR\r:")
                elif self.rejects_power_commands:
                    await self._send(writer, b"ERR\r:")
                else:
                    self.power = "02" if command == b"PWR ON" else "03"
                    if self.mode != "silent_ack":
                        await self._send(writer, b":")
            else:
                await self._send(writer, b"ERR\r:")
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

    def _advance_transition(self) -> None:
        """Count down a transition, settling it when the reads run out."""
        if self.power not in SETTLES_TO or self.transition_reads is None:
            return
        if self.transition_reads > 0:
            self.transition_reads -= 1
        if self.transition_reads == 0:
            self.power = SETTLES_TO[self.power]

    async def _send(self, writer: asyncio.StreamWriter, payload: bytes) -> None:
        """Write a reply, one byte at a time in "dribble" mode."""
        if self.mode == "dribble":
            for byte in payload:
                writer.write(bytes([byte]))
                await writer.drain()
                await asyncio.sleep(0.01)
            return
        writer.write(payload)
        await writer.drain()
