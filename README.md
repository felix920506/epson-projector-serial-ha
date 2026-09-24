# Epson Projector (Serial Bridge) for Home Assistant

Control an Epson projector from Home Assistant over its RS-232 port, using the
ESC/VP21 protocol through a TCP-to-serial bridge (EByte, USR-TCP232, ser2net,
esphome `stream_server`, and similar).

This is for projectors reached over **serial**. If your projector has working
network control, the built-in [`epson`][core-epson] integration is the better
choice.

[core-epson]: https://www.home-assistant.io/integrations/epson/

## Features

- Power switch (`switch.<name>`) with on/off control and polling.
- Config flow — no YAML, set up from the UI.
- Adjustable polling interval (default 5 s), and a reconfigure step for when
  the bridge changes address.
- Handles the single-connection nature of serial bridges: commands are
  serialised and retried, and a busy bridge does not knock the entity offline.
- Warm-up (`PWR=02`) reports as **on** and cool-down (`PWR=03`) as **off**, so
  the switch settles immediately after a command instead of bouncing.
- Raw protocol state exposed as attributes: `power_code`, `power_status`.

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
  already busy transitioning, so a missing ack is treated as success. An
  explicit `ERR`, a failed connection, or a missing ready prompt triggers a
  retry (3 attempts).
- **Failed polls keep the last known state** for up to 3 consecutive attempts
  before the entity is marked unavailable. A bridge that is momentarily busy
  looks identical to one that is offline.
- **After a power command the state is held for 20 seconds** unless the
  projector confirms sooner. The serial port goes briefly unresponsive at the
  start of warm-up, and the projector can still report its old state for a
  moment after accepting the command.

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
pip install -r requirements-test.txt
pytest
```

The test suite runs the integration against a fake ESC/VP21 bridge, so the
socket handling, retries and state mapping are all covered without hardware.

## Tested with

- Epson EH-LS9000W via an EByte TCP-to-serial bridge.

Other Epson models using ESC/VP21 should work; reports welcome.

## Previous YAML configuration

`epson_ls9000w.yaml` in this repository is the original `command_line` switch
this integration replaces. It is kept for reference only — once the integration
is set up, remove it from `configuration.yaml`, since two pollers competing for
a single-connection bridge will cause both to fail intermittently.
