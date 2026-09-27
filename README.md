# Epson Projector (Serial Bridge) for Home Assistant

Control an Epson projector from Home Assistant over its RS-232 port, using the
ESC/VP21 protocol through a TCP-to-serial bridge (EByte, USR-TCP232, ser2net,
esphome `stream_server`, and similar).

This is for projectors reached over **serial**. If your projector has working
network control, the built-in [`epson`][core-epson] integration is the better
choice.

[core-epson]: https://www.home-assistant.io/integrations/epson/

## Features

- Power switch with on/off control and polling.
- **Power commands wait out warm-up and cool-down** instead of failing. The
  projector refuses `PWR ON`/`PWR OFF` mid-transition, which breaks
  automations; this queues the command until the projector can accept it.
- **Raw protocol state as its own entities** — warm-up and cool-down in their
  own right, as both a number and a readable name.
- Config flow — no YAML, set up from the UI.
- Adjustable polling interval (default 5 s), and a reconfigure step for when
  the bridge changes address.
- Handles the single-connection nature of serial bridges: commands are
  serialised and retried, and a busy bridge does not knock the entity offline.

## Entities

| Entity | Example | Notes |
| --- | --- | --- |
| `switch.<name>` | `on` | Plain on/off. Warm-up reads as on, cool-down as off, so it settles immediately after a command instead of bouncing. |
| `sensor.<name>_power_state` | `warming_up` | The full state: `standby`, `on`, `warming_up`, `cooling_down`, `standby_network_on`, `abnormal_standby`. An enum sensor, so it works in UI pickers and `state:` triggers. |
| `sensor.<name>_power_code` | `02` | The raw two-digit code from the projector's `PWR?` reply. |

The switch also carries `power_code`, `power_status`, `pending_command` and
`bridge` as attributes, so a template can read them without a second entity.

## Warm-up and cool-down

An Epson projector rejects `PWR ON` and `PWR OFF` while it is warming up or
cooling down. A naive integration reports that as a failure, so an automation
that turns the projector off and straight back on — or a second press of a
dashboard button — fails for no good reason.

Instead, a power command:

1. Reads the current state.
2. If the projector is mid-transition **towards the requested state**, returns
   immediately. `turn_on` during warm-up has nothing to do.
3. If it is mid-transition **away from it**, waits, re-reading every 3 s, until
   the projector settles, then sends the command.
4. If it is already in the requested state, sends nothing.
5. If the command is refused anyway, **reads the state again rather than
   repeating the command**. The projector can slip into a transition between
   the read and the command, and the second read reveals it. If the state is
   settled both times, the refusal is taken at its word and reported — a
   projector in `abnormal standby` fails immediately instead of being asked
   again.

Commands are serialised, so a second one queues behind the first rather than
racing it. `switch.turn_on` called during a cool-down therefore blocks until
the projector is actually on, which is usually what an automation wants; bear
in mind it can take the better part of a minute. While waiting, the switch's
`pending_command` attribute says which command is queued.

A projector that never leaves a transition fails the call after 3 minutes
rather than blocking forever.

## Requirements

- Home Assistant 2025.1 or newer.
- The projector's RS-232 port wired to a serial bridge, configured for
  **9600 baud, 8-N-1**.
- The bridge reachable from Home Assistant on a TCP port (commonly 8002).
- On most Epson models, **Standby Mode / Communication** must be enabled in the
  projector menu, or serial control stops responding once it powers down.

## Installation

### HACS (custom repository)

1. In Home Assistant, go to **HACS → ⋮ → Custom repositories**.
2. Add `https://github.com/felix920506/epson-projector-serial-ha` with the
   category **Integration**.
3. Find **Epson Projector (Serial Bridge)** in HACS, install it, and restart
   Home Assistant.

### Manual

Copy `custom_components/epson_projector_serial/` into your Home Assistant
`config/custom_components/` directory and restart.

## Setup

**Settings → Devices & services → Add integration → Epson Projector (Serial
Bridge)**, then enter:

| Field | Description |
| --- | --- |
| Host | IP address or hostname of the serial bridge |
| Port | TCP port the bridge listens on (default `8002`) |
| Name | Name for the device in Home Assistant |

Setup sends a `PWR?` query and fails fast if the projector does not answer, so
a successful setup means the wiring and baud rate are right.

The polling interval can be changed later under the integration's
**Configure** button. If the bridge moves to a different IP or port, use
**Reconfigure** on the device rather than deleting the entry — the entity and
its history are kept.

## How it works

Every command performs a full ESC/VP21 handshake, and the connection is closed
afterwards so the bridge's single connection slot is freed:

```
connect → send CR → wait for the ':' ready prompt → send command → read reply → close
```

A few details worth knowing:

- **Reaching the ready prompt is the proof of delivery.** `PWR ON` and `PWR OFF`
  often do not acknowledge within the read window because the projector is
  already busy transitioning, so a missing ack is treated as success.
- **A failed connection, a missing ready prompt or a truncated reply is
  retried** (3 attempts), because the bridge takes one connection at a time and
  may simply have been busy.
- **An explicit `ERR` is not retried.** A refusal is a considered answer, and
  it will still be true a fraction of a second later. It is passed up to the
  layer that knows what might have caused it, which re-reads the power state
  and decides — see [Warm-up and cool-down](#warm-up-and-cool-down).
- **Failed polls keep the last known state** for up to 3 consecutive attempts
  before the entity is marked unavailable. A bridge that is momentarily busy
  looks identical to one that is offline.
- **After a power command the state is held for 20 seconds** unless the
  projector confirms sooner. The serial port goes briefly unresponsive at the
  start of warm-up, and the projector can still report its old state for a
  moment after accepting the command.
- **Power commands wait for a transition to finish** rather than failing; see
  [Warm-up and cool-down](#warm-up-and-cool-down) above.

### Power codes

| `PWR=` | Meaning | Switch state |
| --- | --- | --- |
| `00` | Standby | off |
| `01` | On | on |
| `02` | Warming up | on |
| `03` | Cooling down | off |
| `04` | Standby, network on | off |
| `05` | Abnormal standby | off |

## Troubleshooting

**Setup fails with "could not reach the bridge"** — check that the host and
port are right and that nothing else is holding the bridge's single connection
(a terminal session, another HA instance, a `command_line` sensor).

**Setup fails with "did not return a valid PWR code"** — the bridge answered
but the projector did not. Check the baud rate (9600 8-N-1) and that the cable
is a null-modem/crossover type if your projector requires one.

**The switch goes unavailable at random** — something else is competing for
the bridge, or the polling interval is too aggressive for it. Raise the
interval under **Configure**.

For protocol-level detail, enable debug logging:

```yaml
logger:
  logs:
    custom_components.epson_projector_serial: debug
```

## Development

```bash
uv venv --python 3.14 .venv
uv pip install -r requirements-test.txt
.venv/bin/pytest
.venv/bin/ruff check .
```

Plain `pip` works too, but it spends a long time backtracking through Home
Assistant's dependency tree; `uv` resolves it in seconds. If a download times
out, raise `UV_HTTP_TIMEOUT` — Home Assistant depends on `uv` itself, and that
wheel is large.

The test suite runs the integration against a fake ESC/VP21 bridge that
refuses power commands mid-transition the way a real projector does, so the
socket handling, retries, queuing and state mapping are all covered without
hardware. It needs Python 3.14, which recent Home Assistant releases require.

Verified against Home Assistant 2026.9.3 (Python 3.14.7). The stated 2025.1
minimum reflects the Home Assistant APIs this integration uses, not a tested
floor.

## Tested with

- Epson EH-LS9000W via an EByte TCP-to-serial bridge.

Other Epson models using ESC/VP21 should work; reports welcome.

## Previous YAML configuration

`epson_ls9000w.yaml` in this repository is the original `command_line` switch
this integration replaces. It is kept for reference only — once the integration
is set up, remove it from `configuration.yaml`, since two pollers competing for
a single-connection bridge will cause both to fail intermittently.

## License

[MIT](LICENSE)
