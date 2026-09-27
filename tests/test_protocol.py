"""Tests for how the ESC/VP21 client classifies failures.

Everything above this layer keys off one distinction: a bridge that cannot be
connected to at all, versus a projector that takes the connection and then does
not talk. The first is the only failure worth giving up on, so the boundary is
pinned here rather than inferred from behaviour further up.
"""

from __future__ import annotations

import pytest

from .fake_projector import FakeProjector
from custom_components.epson_projector_serial.protocol import (
    EpsonNotReadyError,
    EpsonRefusedError,
    EpsonSerialBridge,
    EpsonUnreachableError,
)


def _bridge(projector: FakeProjector) -> EpsonSerialBridge:
    """Return a client pointed at the fake projector."""
    return EpsonSerialBridge("127.0.0.1", projector.port)


async def test_reads_the_power_code(projector: FakeProjector) -> None:
    """The happy path, so the failure cases mean something."""
    projector.power = "02"
    projector.transition_reads = None
    assert await _bridge(projector).async_query_power() == "02"


async def test_refused_connection_is_unreachable(projector: FakeProjector) -> None:
    """Nothing listening: the one failure with nothing to wait for."""
    await projector.pause()

    with pytest.raises(EpsonUnreachableError):
        await _bridge(projector).async_query_power()


async def test_dropped_connection_is_not_unreachable(
    projector: FakeProjector,
) -> None:
    """A bridge that accepts and hangs up is reachable, just not talking."""
    projector.silent_connections = 99

    with pytest.raises(EpsonNotReadyError) as caught:
        await _bridge(projector).async_query_power()

    assert not isinstance(caught.value, EpsonUnreachableError)


async def test_missing_ready_prompt_is_not_unreachable(
    projector: FakeProjector,
) -> None:
    """The reported failure: connected, but the ready prompt never arrives.

    Classifying this as unreachable is what made it fail automations, so assert
    the message and the type together.
    """
    projector.mode = "no_prompt"

    with pytest.raises(EpsonNotReadyError, match="No ready prompt") as caught:
        await _bridge(projector).async_query_power()

    assert not isinstance(caught.value, EpsonUnreachableError)


async def test_err_is_a_refusal_not_a_transport_failure(
    projector: FakeProjector,
) -> None:
    """ERR is an answer, so it is neither unreachable nor a lost connection."""
    projector.mode = "err"

    with pytest.raises(EpsonRefusedError) as caught:
        await _bridge(projector).async_query_power()

    assert not isinstance(caught.value, EpsonUnreachableError)


async def test_a_refusal_is_not_retried(projector: FakeProjector) -> None:
    """A considered answer is passed up, not asked again at this level."""
    projector.reject_queries = 99
    projector.commands.clear()

    with pytest.raises(EpsonRefusedError):
        await _bridge(projector).async_query_power()

    assert projector.commands.count(b"PWR?") == 1


async def test_a_quiet_port_is_retried(projector: FakeProjector) -> None:
    """A connection problem might just be a busy bridge, so it is retried."""
    projector.silent_connections = 1
    projector.power = "01"

    # The retry finds the projector answering again.
    assert await _bridge(projector).async_query_power() == "01"
