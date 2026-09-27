"""Tests for waiting out warm-up and cool-down before a power command."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .fake_projector import FakeProjector
from custom_components.epson_projector_serial import coordinator as coordinator_module

SWITCH_ENTITY = "switch.epson_projector"


async def _turn(hass: HomeAssistant, on: bool) -> None:
    """Call the switch's turn_on or turn_off service and wait for it."""
    await hass.services.async_call(
        SWITCH_DOMAIN,
        SERVICE_TURN_ON if on else SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: SWITCH_ENTITY},
        blocking=True,
    )


async def test_turn_on_waits_out_cool_down(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Turning on while cooling down waits, then sends the command."""
    projector.power = "03"
    projector.transition_reads = 3
    projector.commands.clear()

    await _turn(hass, True)

    assert b"PWR ON" in projector.commands
    # The command was only sent once the projector had left cool-down.
    reads_before_command = projector.commands.index(b"PWR ON")
    assert reads_before_command >= 3
    assert hass.states.get(SWITCH_ENTITY).state == STATE_ON


async def test_turn_off_waits_out_warm_up(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Turning off while warming up waits, then sends the command."""
    projector.power = "02"
    projector.transition_reads = 2
    projector.commands.clear()

    await _turn(hass, False)

    assert b"PWR OFF" in projector.commands
    assert projector.commands.index(b"PWR OFF") >= 2
    assert hass.states.get(SWITCH_ENTITY).state == STATE_OFF


@pytest.mark.parametrize(
    ("code", "turn_on", "expected_state"),
    [
        ("02", True, STATE_ON),  # warming up, asked for on
        ("03", False, STATE_OFF),  # cooling down, asked for off
    ],
)
async def test_no_command_when_transition_already_heading_there(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    projector: FakeProjector,
    code: str,
    turn_on: bool,
    expected_state: str,
) -> None:
    """A transition already going the right way needs no command at all."""
    projector.power = code
    projector.transition_reads = None  # would hold forever if we waited
    projector.commands.clear()

    await _turn(hass, turn_on)

    assert b"PWR ON" not in projector.commands
    assert b"PWR OFF" not in projector.commands
    assert hass.states.get(SWITCH_ENTITY).state == expected_state


@pytest.mark.parametrize(
    ("code", "turn_on"),
    [("01", True), ("00", False)],
)
async def test_no_command_when_already_in_requested_state(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    projector: FakeProjector,
    code: str,
    turn_on: bool,
) -> None:
    """The projector is not commanded into a state it already holds."""
    projector.power = code
    projector.commands.clear()

    await _turn(hass, turn_on)

    assert b"PWR ON" not in projector.commands
    assert b"PWR OFF" not in projector.commands


async def test_refusal_reveals_a_transition_and_the_command_still_lands(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A refusal is answered by re-reading, not by asking again.

    This is the race the refusal path exists for: the projector begins warming
    up just after we read it as settled, so it declines the command. Reading it
    again reveals the transition, which is then waited out.
    """
    projector.power = "01"
    projector.reject_commands = 1
    projector.power_after_rejection = "02"  # it had already started warming
    projector.transition_reads = 2
    projector.commands.clear()

    await _turn(hass, False)

    # Declined once, then sent again only after the projector settled -- never
    # repeated at a projector that had just said no.
    assert projector.commands.count(b"PWR OFF") == 2
    assert hass.states.get(SWITCH_ENTITY).state == STATE_OFF


async def test_refusal_from_a_settled_projector_is_final(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A refusal with nothing transitioning is taken at its word.

    The state was read before the command and read again after the refusal. If
    it is settled both times there is nothing to wait for and no reason to
    expect a different answer, so the command is sent exactly once.
    """
    projector.power = "05"  # abnormal standby
    projector.transition_reads = None
    projector.reject_commands = 99
    projector.commands.clear()

    with pytest.raises(HomeAssistantError, match="ERR"):
        await _turn(hass, True)

    assert projector.commands.count(b"PWR ON") == 1


async def test_endless_transition_eventually_fails(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A projector stuck in a transition fails the call rather than hanging."""
    projector.power = "02"
    projector.transition_reads = None  # never settles

    with (
        patch.object(
            coordinator_module, "TRANSITION_TIMEOUT", timedelta(milliseconds=200)
        ),
        pytest.raises(HomeAssistantError, match="did not settle"),
    ):
        await _turn(hass, False)


async def test_unreachable_projector_fails_immediately(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """An unreachable bridge fails fast instead of waiting out the timeout."""
    projector.mode = "offline"

    with pytest.raises(HomeAssistantError):
        await _turn(hass, False)


async def test_queued_commands_run_one_at_a_time(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A second command queues behind the first and wins."""
    projector.power = "01"
    projector.transition_reads = 1
    projector.commands.clear()

    # Turn off, then straight back on. The second call has to wait out the
    # cool-down the first one starts.
    await _turn(hass, False)
    await _turn(hass, True)

    assert projector.commands.index(b"PWR OFF") < projector.commands.index(b"PWR ON")
    assert hass.states.get(SWITCH_ENTITY).state == STATE_ON


async def test_pending_command_is_exposed_while_waiting(
    hass: HomeAssistant, setup_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """The switch reports which command is queued while it waits."""
    assert hass.states.get(SWITCH_ENTITY).attributes["pending_command"] is None

    projector.power = "03"
    projector.transition_reads = 2
    seen: list[str | None] = []

    original = coordinator_module.EpsonProjectorCoordinator._async_wait_to_retry

    async def record(self, deadline):
        seen.append(hass.states.get(SWITCH_ENTITY).attributes["pending_command"])
        await original(self, deadline)

    with patch.object(
        coordinator_module.EpsonProjectorCoordinator,
        "_async_wait_to_retry",
        record,
    ):
        await _turn(hass, True)

    assert seen and all(value == "on" for value in seen)
    # Cleared once the command lands.
    assert hass.states.get(SWITCH_ENTITY).attributes["pending_command"] is None
