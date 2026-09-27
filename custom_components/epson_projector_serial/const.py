"""Constants for the Epson Projector (serial bridge) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "epson_projector_serial"

DEFAULT_NAME: Final = "Epson Projector"
DEFAULT_PORT: Final = 8002
DEFAULT_SCAN_INTERVAL: Final = 5

# Seconds to keep waiting for the projector to become ready before giving up on
# a power command. Laser projectors transition in seconds; lamp models can take
# a couple of minutes to cool down, hence the generous default and the option.
DEFAULT_TRANSITION_TIMEOUT: Final = 180
MIN_TRANSITION_TIMEOUT: Final = 10
MAX_TRANSITION_TIMEOUT: Final = 900

CONF_TRANSITION_TIMEOUT: Final = "transition_timeout"

MANUFACTURER: Final = "Epson"

# ESC/VP21 PWR? reply codes.
POWER_STANDBY: Final = "00"
POWER_ON: Final = "01"
POWER_WARMING: Final = "02"
POWER_COOLING: Final = "03"
POWER_STANDBY_NETWORK: Final = "04"
POWER_ABNORMAL_STANDBY: Final = "05"

# Warm-up counts as "on" so the switch settles immediately after turn_on.
POWER_ON_CODES: Final = frozenset({POWER_ON, POWER_WARMING})

# The projector refuses PWR ON/OFF while it is in one of these states.
TRANSITIONAL_POWER_CODES: Final = frozenset({POWER_WARMING, POWER_COOLING})

# Where each transition is headed, as an "is on" boolean. A command asking for
# the state a transition is already heading towards needs no command at all.
TRANSITION_TARGETS: Final = {POWER_WARMING: True, POWER_COOLING: False}

POWER_CODE_NAMES: Final = {
    POWER_STANDBY: "standby",
    POWER_ON: "on",
    POWER_WARMING: "warming_up",
    POWER_COOLING: "cooling_down",
    POWER_STANDBY_NETWORK: "standby_network_on",
    POWER_ABNORMAL_STANDBY: "abnormal_standby",
}

# Polls that fail are tolerated this many times in a row before the entity is
# marked unavailable. The bridge accepts a single connection at a time, so an
# occasional refused connection is normal rather than a real outage.
MAX_CONSECUTIVE_FAILURES: Final = 3

# A projector that answers but refuses to report its power state is reachable,
# just busy -- it does this throughout warm-up and cool-down. Tolerate that for
# longer than an unreachable bridge, so the entities do not drop out mid
# transition, while a projector stuck refusing forever still surfaces.
MAX_CONSECUTIVE_REFUSALS: Final = 12

# After a power command the serial port goes briefly unresponsive and the
# projector may still report its previous state. Trust the commanded state for
# this long rather than flipping the switch back and forth.
COMMAND_GRACE_PERIOD: Final = timedelta(seconds=20)

# How often to re-read the power state while waiting out a transition. The
# bridge takes one connection at a time, so this stays well clear of a busy
# poll.
TRANSITION_POLL_INTERVAL: Final = 3.0

# Human-readable states the power_state sensor can report, for its enum
# device class. Codes outside this set leave the sensor unknown.
POWER_STATE_OPTIONS: Final = tuple(POWER_CODE_NAMES.values())
