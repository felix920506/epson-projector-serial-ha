"""A fake ESC/VP21 projector behind a TCP-to-serial bridge."""

from __future__ import annotations

import asyncio


class FakeProjector:
    """Serve just enough ESC/VP21 to exercise the integration."""

    def __init__(self, power: str = "01") -> None:
        """Initialise the fake projector in the given power state."""
        self.power = power
        # "normal", "offline", "no_prompt", "err", "silent_ack" or "dribble".
        self.mode = "normal"
        self.commands: list[bytes] = []
        self._server: asyncio.Server | None = None
        self.port = 0

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
                await asyncio.sleep(5)
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
            elif command == b"PWR ON":
                self.power = "02"
                if self.mode != "silent_ack":
                    await self._send(writer, b":")
            elif command == b"PWR OFF":
                self.power = "03"
                if self.mode != "silent_ack":
                    await self._send(writer, b":")
            else:
                await self._send(writer, b"ERR\r:")
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()

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
