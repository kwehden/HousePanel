# Simplified primary interface

This standalone sketch runs on the primary Arduino GIGA R1 with its 800×480
Display Shield. It shows Pacific local time as `HH:MM:SS`, the local date in
the upper-right corner as `YYYY-MM-DD`, and filament-box temperature in °C
and relative humidity. Labels and values use antialiased Lato glyphs.

The sketch connects to the existing transport adapter as `primary` at
`/ws/panels/primary`. It accepts `TIME` and `SYSMON_TEMP` messages and ignores
the other panel commands. The server supplies the Pacific UTC offset.
`SYSMON_TEMP.measured_at` carries the source measurement's Unix timestamp.
Sensor values become placeholders once that measurement is five minutes old,
even if reconnects replay it. A synchronized clock and a valid source timestamp
are required to mark a reading live; missing or future timestamps show placeholders.
Deploy the transport adapter change before flashing this firmware. Older full-panel
firmware ignores the additional timestamp field.
Wi-Fi and WebSocket connections retry automatically, including after a failed
handshake. USB diagnostics use nonblocking writes; direct power works without
a serial reader.

The secondary continues to use `firmware/housepanel-giga`. This sketch does
not implement the full panel's touch interface, weather, calendar, OTA receiver,
memory telemetry, or watchdog. Flash it over USB. The original primary crash
cause remains unresolved; this is the smaller interface accepted on hardware.

## Build

Install Arduino CLI and the pinned dependencies:

```sh
arduino-cli core update-index
arduino-cli core install arduino:mbed_giga@4.5.0
arduino-cli lib install 'ArduinoGraphics@1.1.5' 'ArduinoHttpClient@0.6.1' 'ArduinoJson@7.4.3'
cp firmware/giga-filament/secrets.h.example firmware/giga-filament/secrets.h
```

Fill in the ignored `secrets.h` with Wi-Fi credentials and the adapter address.
Then compile:

```sh
arduino-cli compile --fqbn arduino:mbed_giga:giga \
  --build-path "$PWD/build/giga-filament-release" firmware/giga-filament
```

Identify the primary by USB serial `004A002A3533510139363331` in
`arduino-cli board list --format json` before uploading. Select its reported
serial port or DFU address:

```sh
arduino-cli upload --fqbn arduino:mbed_giga:giga --port PRIMARY_PORT \
  --input-dir build/giga-filament-release
```

CI builds this sketch with dummy credentials as well as both full-panel identities.
CI does not flash a board. Existing OTA build tooling still targets the full-panel
sketch.

## Fonts

`smooth_font.h` contains generated 4-bit coverage glyphs stored in flash. A normal
firmware build uses this checked-in header and needs no font-generation packages.
The generator records the source font hashes; the font license is in
`FONT-LICENSE.txt`.

To regenerate on Ubuntu with `fonts-lato` installed:

```sh
python3 -m venv build/font-tools
build/font-tools/bin/pip install Pillow==13.0.0
build/font-tools/bin/python tools/generate_filament_fonts.py
```

The generator also writes an 800×480 preview to
`build/giga-filament/font-preview.png`.
