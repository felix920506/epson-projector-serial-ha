"""Constants for the Epson Projector (serial bridge) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "epson_projector_serial"

DEFAULT_NAME: Final = "Epson Projector"
DEFAULT_PORT: Final = 8002
DEFAULT_SCAN_INTERVAL: Final = 5

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

# After a power command the serial port goes briefly unresponsive and the
# projector may still report its previous state. Trust the commanded state for
# this long rather than flipping the switch back and forth.
COMMAND_GRACE_PERIOD: Final = timedelta(seconds=20)

# How long to keep waiting for warm-up or cool-down to finish before giving up
# on a power command. Epson transitions take well under a minute; this is a
# backstop against a projector that never reports a settled state.
TRANSITION_TIMEOUT: Final = timedelta(seconds=180)

# How many times to re-send a refused power command. A refusal usually means
# the projector slipped into a transition between the read and the command, so
# one more try is worth it -- but if it keeps refusing from a settled state the
# refusal is real, and there is nothing to wait for.
MAX_COMMAND_REJECTIONS: Final = 2

# How often to re-read the power state while waiting out a transition. The
# bridge takes one connection at a time, so this stays well clear of a busy
# poll.
TRANSITION_POLL_INTERVAL: Final = 3.0

# Human-readable states the power_state sensor can report, for its enum
# device class. Codes outside this set leave the sensor unknown.
POWER_STATE_OPTIONS: Final = tuple(POWER_CODE_NAMES.values())
