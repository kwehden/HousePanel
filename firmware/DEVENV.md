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
- **Compile check, both identities, dummy credentials:** `python tools/ci_firmware.py`
- **Local release compile:** set `LV_CONF_PATH` for both C and C++ as shown below.
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
  --build-property "compiler.cpp.extra_flags=-DHOUSEPANEL_PANEL_ID=\"panel-2\" -DHOUSEPANEL_HOSTNAME=\"housepanel-2\" -DLV_CONF_PATH=\"$PWD/firmware/housepanel-giga/housepanel_lv_conf.h\"" \
  --build-property "compiler.c.extra_flags=-DLV_CONF_PATH=\"$PWD/firmware/housepanel-giga/housepanel_lv_conf.h\"" \
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

## Memory Telemetry (0.5.2)

Review and deploy the telemetry backend before flashing either panel. This PR
does not flash hardware. Both identities compile from the same sketch using
their existing distinct hostnames. CI compiles both with dummy credentials;
it never uploads or publishes firmware binaries. Build local release binaries
only after review because the local `secrets.h` is embedded in them.
`housepanel_lv_conf.h` starts from core 4.5.0's display configuration and enables
the fonts used by the existing UI. The build helper supplies `LV_CONF_PATH` to
both C and C++; no edits to installed Arduino libraries are required.

Each connected board sends one `MEMORY` JSON sample after HELLO and then every
60 seconds over its existing socket. The backend binds it to that socket's
fixed panel identity; the payload cannot select another panel. It keeps only
the latest validated sample and accepts at most one per five seconds. Unknown
fields, invalid types/ranges and out-of-order uptime within a boot are ignored.
Disconnects and replacement sessions clear their own sample. Legacy firmware
remains supported and reports `memory: null`, never fabricated zero usage.

The sampler uses fixed buffers (32 thread handles, 768-byte wire buffer), a
hardware-random 64-bit boot ID and 64-bit kernel uptime. Reconnects preserve
boot identity; hardware reboots change it. Entropy initialization or kernel
lock failure suppresses a sample. Compile-time checks require heap statistics,
RTOS stack watermarking and the LVGL built-in allocator. Core 4.5.0 enables
these. No GC, task creation or sampler-owned heap allocation is added. Sampling
does scan RTOS stack watermarks and walk the bounded LVGL pool once per minute;
runtime overhead still needs on-board verification. The existing WebSocket implementation may allocate
while sending, as it already does for HELLO.

Reported memory domains are separate and must not be summed as total free RAM:

- Mbed tracked heap: current/peak allocated bytes, reserved bytes, outstanding
  allocation count and cumulative allocation failures since boot. Reserved
  space is not a measurement of free board RAM.
- RTOS stacks: summed per-thread high-water usage and reserved stack space,
  thread count, and the smallest per-thread remaining high-water headroom.
  These are watermark measurements, not instantaneous stack depth. If more
  than 32 threads exist, `stack_complete` is false and partial stack totals
  are omitted from Prometheus; heap and LVGL values remain available.
- LVGL's separate display pool: current/peak usage, capacity and largest free
  block. A falling largest block can expose fragmentation even with stable
  total usage. Stack statistics cover the M7 RTOS threads only; M4 firmware,
  framebuffers/SDRAM and untracked static/external allocations are not measured.

For the pinned LVGL 9.5.0, `max_used` is a byte count; `used_pct` is its separate
percentage field. The fixture mirrors that layout and asserts a 40000-byte peak
independently of a 24-percent current usage field. Upstream definitions:
[lv_mem.h](https://github.com/lvgl/lvgl/blob/v9.5.0/src/stdlib/lv_mem.h#L32-L41)
and [allocator accounting](https://github.com/lvgl/lvgl/blob/v9.5.0/src/stdlib/builtin/lv_mem_core_builtin.c#L129-L138).

`/internal/health` exposes the last sample, boot ID and server receipt timestamp
under `panels.<id>.memory`. Prometheus exports gauges with only the existing
fixed `panel_id` label, including:

```promql
housepanel_panel_memory_heap_allocated_bytes
housepanel_panel_memory_heap_peak_bytes
housepanel_panel_memory_heap_allocation_failures
housepanel_panel_memory_stack_high_water_bytes
housepanel_panel_memory_stack_min_free_bytes
housepanel_panel_memory_gui_allocated_bytes
housepanel_panel_memory_gui_largest_free_bytes
time() - housepanel_panel_memory_last_sample_timestamp_seconds
housepanel_panel_memory_uptime_seconds
```

Treat samples older than 180 seconds as stale even if the socket is connected.
Check unchanged boot ID and uninterrupted uptime before calculating growth;
all values and watermarks can reset at board boot. Allocation failures are
exported as a since-boot gauge, so compare increments only within the same boot.
Only graph complete stack samples. An increasing high-water mark alone is not
proof of a leak. Compare current heap and GUI usage over repeated workloads.

Local regression commands (no hardware access):

```sh
pytest tools/tests/test_firmware_memory.py -q
pytest services/transport-adapter/tests -q --asyncio-mode=auto
python tools/ci_firmware.py
```

The native test executes the actual C++ collector/serializer with deterministic
RTOS/heap/GUI fixtures and validates its JSON against the backend schema. It
covers cadence across the 32-bit millisecond boundary, maximum numeric values,
buffer truncation, unavailable entropy, failed kernel locking and thread-buffer
overflow. These tests and cross-compilation do not establish on-device runtime
accuracy; verify both panels' boot IDs, sample freshness and memory values after
the separately approved flash.
