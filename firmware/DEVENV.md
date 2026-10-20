# HousePanel Firmware Dev Environment

## Prerequisites
- ardconfig cloned and installed (see https://github.com/kwehden/ardconfig)
- Run `bin/ardconfig-setup --boards giga` from the ardconfig directory

## Board
- FQBN: `arduino:mbed_giga:giga`
- Core: `arduino:mbed_giga` (MbedOS, STM32H747XI dual-core)

## Libraries
- ArduinoHttpClient — WebSocket client
- ArduinoJson — JSON parsing

## Commands
- **Compile:** `arduino-cli compile --fqbn arduino:mbed_giga:giga firmware/housepanel-giga/`
- **Upload:** `arduino-cli upload --fqbn arduino:mbed_giga:giga --port <PORT> firmware/housepanel-giga/`
- **Monitor:** `arduino-cli monitor --port <PORT>`

## Notes
- ardconfig is a host-side tool only; it provides no firmware code.
- WiFi credentials and transport adapter host/port go in `firmware/housepanel-giga/secrets.h` (git-ignored).
  Copy `secrets.h.example` → `secrets.h` and fill in your values.

## Two Panels

The original panel can continue using `/ws/panel`, which maps to `primary`.
New firmware uses `/ws/panels/<panel_id>`. The backend accepts only `primary`
and `panel-2`; reconnects replace only the matching identity. Both panels share
the existing pollers and Aggregator, with independent bounded delivery queues.
Transport must remain single-replica and single-worker because its broadcast
state is in memory; adding replicas requires a shared broadcast bus.

The primary firmware defaults to hostname `housepanel`. Build the second panel
with a different DHCP hostname and backend identity:

```sh
arduino-cli compile --fqbn arduino:mbed_giga:giga \
  --output-dir build/panel-2-firmware \
  --build-property 'compiler.cpp.extra_flags=-DHOUSEPANEL_PANEL_ID="panel-2" -DHOUSEPANEL_HOSTNAME="housepanel-2"' \
  firmware/housepanel-giga/
arduino-cli board list
arduino-cli upload --fqbn arduino:mbed_giga:giga --port <SECOND_GIGA_PORT> \
  --input-dir build/panel-2-firmware
```

Confirm the USB serial number before uploading. Use the native port reported
by `board list` for the 1200-baud bootloader reset; a `/dev/serial/by-id` alias
may not trigger that reset. Do not upload to the UNO or the original panel.
The boards use their own hardware MAC addresses and DHCP leases, not cloned
static addresses. Hostname publication depends on the DHCP/DNS server; setting
the DHCP hostname does not provide an mDNS responder.

Deploy the reviewed dual-panel backend before expecting the second panel to
receive data. Old backends reject the new endpoint without replacing the
primary connection. Firmware retries at most once every five seconds.
`/internal/health` reports each panel separately, and metrics use fixed
`panel_id` labels. Named-panel disconnect/staleness alerts keep a healthy peer
from hiding a failed panel.
