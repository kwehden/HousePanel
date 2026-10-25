# Simplified primary interface

This standalone sketch runs on the primary Arduino GIGA R1 with its 800×480
Display Shield. It shows Pacific local time as `HH:MM:SS`, the local date in
the upper-right corner as `YYYY-MM-DD`, and two sensor columns. OUTDOOR is on
the left, FILAMENT on the right, with matching green headings. Each column stacks
temperature in °C above relative humidity. Labels and values use the existing
antialiased Lato glyphs and keep the open black background. Tap anywhere in the
sensor area to switch both temperatures between Celsius and Fahrenheit. Humidity
stays in percent. A press toggles once; release before tapping again. Units start
in Celsius after a reboot. Touches on the clock/date or footer do not toggle.

The primary shield's touch controller reports portrait coordinates (480x800).
The landscape mapping is `x = raw_y`, `y = 479 - raw_x`, matching the video
driver's rotated framebuffer. On primary serial `004A002A3533510139363331`,
corner taps on 2026-10-24 recorded raw `(455,95)` as top-left `(95,24)` and raw
`(24,733)` as bottom-right `(733,455)`. Both corner taps left Celsius selected;
subsequent sensor-area taps switched C/F successfully. Read the controller's
configured dimensions before reusing this mapping on another shield.

The sketch connects to the existing transport adapter as `primary` at
`/ws/panels/primary`. It accepts `TIME`, `SYSMON_TEMP`, and `OUTDOOR_TEMP` messages and ignores
the other panel commands. The server supplies the Pacific UTC offset.
`SYSMON_TEMP.measured_at` carries the source measurement's Unix timestamp.
Sensor values become placeholders once that measurement is five minutes old,
even if reconnects replay it. A synchronized clock and a valid source timestamp
are required to mark a reading live; missing or future timestamps show placeholders.
Outdoor has independent readings and report timestamps. Its source report must
be less than an hour old, and a delivery must have arrived within three minutes.
An explicit `OUTDOOR_TEMP` with `available: false` blanks only that column.
The [eWeLink collector guide](../../services/ewelink-callback/README.md) explains
the one-minute delivery interval and the battery sensor's source-age policy.
Deploy the transport adapter change before flashing this firmware. Older full-panel
firmware ignores the additional timestamp field.
Wi-Fi and WebSocket connections retry automatically, including after a failed
handshake. USB diagnostics use nonblocking writes; direct power works without
a serial reader.

The secondary continues to use `firmware/housepanel-giga`. The simplified sketch
uses the same authenticated, encrypted OTA receiver as the full interface. The
build tools stage that receiver's canonical sources alongside this sketch;
there is no independent copy to maintain. The full touch interface, weather, calendar,
memory telemetry, and watchdog remain outside this interface. The original
primary crash cause remains unresolved.

## Build

Install Arduino CLI and the pinned dependencies:

```sh
arduino-cli core update-index
arduino-cli core install arduino:mbed_giga@4.5.0
arduino-cli lib install 'ArduinoGraphics@1.1.5' 'ArduinoHttpClient@0.6.1' \
  'ArduinoJson@7.4.3' 'Arduino_Portenta_OTA@1.2.1' 'Arduino_GigaDisplayTouch@1.0.1'
cp firmware/housepanel-giga/secrets.h.example firmware/housepanel-giga/secrets.h
```

Fill in the ignored `firmware/housepanel-giga/secrets.h` with Wi-Fi credentials
and the adapter address. The private build tool uses this existing credential
location for both interfaces. Reuse the primary's existing private OTA key at
`.secrets/panels/primary.key`; do not generate another key if it already exists.
For a new installation only, create one with `tools/panel_firmware.py keygen`.

Build an exact committed revision with the existing Python environment containing
`cryptography`. Use the reviewed commit's full SHA in place of `REVIEWED_SHA`:

```sh
python tools/panel_firmware.py build --panel primary --interface simplified \
  --revision REVIEWED_SHA --key-file .secrets/panels/primary.key \
  --output build/primary-simplified-REVIEWED_SHA
```

Use this tool rather than compiling the sketch directly: it stages the shared
OTA sources and embeds the revision, identity, and private key. Firmware images
contain Wi-Fi credentials; keep the output and key local. The manifest records
the `simplified` interface. Routine OTA uploads reject interface changes and key
changes before sending the image.

## One-time USB installation

The previous simplified firmware has no OTA listener. Install the first
OTA-enabled build over USB, identifying the primary by serial
`004A002A3533510139363331`:

```sh
python tools/panel_firmware.py bootstrap --panel primary \
  --serial 004A002A3533510139363331 \
  --manifest build/primary-simplified-REVIEWED_SHA/manifest.json
```

This preserves the bootloader and QSPI contents. The receiver requires an
OTA-capable bootloader and the documented QSPI partition layout; it disables
updates if those checks fail. It never formats storage automatically.

## Updates over Wi-Fi

Use the primary's current IP or hostname in place of `PRIMARY_HOST`:

```sh
python tools/panel_firmware.py status --panel primary --host PRIMARY_HOST \
  --key-file .secrets/panels/primary.key
python tools/panel_firmware.py upload --panel primary --host PRIMARY_HOST \
  --key-file .secrets/panels/primary.key \
  --manifest build/primary-simplified-REVIEWED_SHA/manifest.json
```

Status must be authenticated and report `interface: simplified`, `ready: true`,
and the expected revision. After an upload, the tool requires a new authenticated
boot ID and the target revision before reporting success. USB is not required
for subsequent updates. See [the OTA protocol and recovery guide](../../docs/firmware-ota.md).

CI stages the same OTA sources and builds this sketch with dummy credentials
alongside both full-panel identities. It does not flash hardware or use real keys.

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
