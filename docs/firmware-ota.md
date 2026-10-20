# GIGA Firmware Updates

Firmware 0.5.3 adds an authenticated, encrypted LAN updater for `primary`
(`housepanel`) and `panel-2` (`housepanel-2`). Routine firmware updates use Wi-Fi.
The current 0.5.1/0.5.2 sketches have no firmware receiver, so each board needs a
one-time bootstrap installation. USB remains the recovery path for a board that
cannot boot or join Wi-Fi.

## Release Boundary

Backend CD continues deploying tested service images automatically from `main`.
CI compiles both firmware identities with dummy credentials and tests the updater;
it neither flashes boards nor publishes credential-bearing firmware. Firmware is
an explicit operator step after review and successful exact-SHA main push CI.
Keep the PR open for the user's review before merging or flashing its firmware.

Build and flash one panel at a time. Confirm its authenticated new boot, expected
revision, backend connection, update delivery and memory samples before changing
the other. Never report a backend deployment as a completed firmware update.

## Dependencies and Private Keys

Use the pinned dependencies from `.github/workflows/ci.yml`, including core
`arduino:mbed_giga@4.5.0`, `Arduino_Portenta_OTA@1.2.1`, and ArduinoHttpClient
`0.6.1`. The host uploader requires Python 3.12+ and `cryptography`. Native tests
also require a C++ compiler and OpenSSL development headers (`libssl-dev`).

Generate independent keys once. Preserve them for future uploads and recovery:

```sh
python tools/panel_firmware.py keygen .secrets/panels/primary.key
python tools/panel_firmware.py keygen .secrets/panels/panel-2.key
```

Keys contain 32 random binary bytes and must remain mode `0600` or `0400`.
`keygen` refuses to overwrite a key. An absent, invalid or all-zero firmware key
disables the updater. Never copy one panel's key to the other or publish keys,
compiled binaries, ELF files or build directories. Firmware contains Wi-Fi
credentials and its panel-specific OTA key. Key rotation is not supported by the
normal upload command; preserve the existing key during routine updates.

## One-Time Bootstrap

First check each board's bootloader and QSPI layout. Arduino's supported setup
uses FAT partition 2 at 1 MiB through 6 MiB for OTA staging. The updater checks
this layout and bootloader capability, mounts once and fails closed on error.
It never formats storage, changes the partition table or replaces a bootloader.
The existing display and WebSocket loop continue if OTA initialization fails.

Arduino's [GIGA OTA setup guide](https://support.arduino.cc/hc/en-us/articles/12370721200540-Configure-GIGA-R1-WiFi-Portenta-H7-and-Portenta-Machine-Control-for-Over-The-Air-OTA-uploads)
describes QSPI preparation. Its `QSPIFormat` sketch erases data. Inspect and back
up the board's existing storage before considering it; formatting or a bootloader
change requires separate approval. Do not run those sketches automatically.

After the OTA PR is reviewed and merged, substitute its verified merge SHA:

```sh
SHA=<reviewed-merge-sha>
python tools/panel_firmware.py build --panel primary --revision "$SHA" \
  --key-file .secrets/panels/primary.key --output "build/firmware-$SHA/primary"
python tools/panel_firmware.py bootstrap --panel primary \
  --manifest "build/firmware-$SHA/primary/manifest.json" --serial <PRIMARY_USB_SERIAL>
```

Repeat for `panel-2` with its own key and output directory. Its previously
identified hardware serial is `003900303033511034323932`; re-enumerate before use.
The bootstrap command requires exactly one matching USB GIGA and hardware serial.
It refuses the UNO R4 and ambiguous devices, then verifies the upload of the exact
manifest-checked `.bin`. It does not compile or select another image at upload.

`build` extracts the specified committed sketch into a private temporary directory,
adds local `secrets.h` and that panel's OTA key, and applies the global LVGL and
WebSocket flags. It never changes the source credentials or passes keys in argv.
Outputs are private and cannot overwrite an earlier build. Keep the manifest,
SHA-256 and target hardware mapping as local release evidence.

## Wi-Fi Updates

Use each panel's current DHCP address or verified DNS name. DHCP hostname does
not imply mDNS support. TCP port 8266 must be reachable only on the trusted LAN;
do not expose it through a public ingress or router port forwarding.

```sh
python tools/panel_firmware.py status --panel primary --host <PRIMARY_IP> \
  --key-file .secrets/panels/primary.key
python tools/panel_firmware.py upload --panel primary --host <PRIMARY_IP> \
  --key-file .secrets/panels/primary.key \
  --manifest "build/firmware-$SHA/primary/manifest.json"
```

Build the new reviewed SHA first using the same per-panel key. The uploader
requires the expected panel ID, hostname and embedded firmware identity. It
checks the local image hash and revision before contacting hardware. Firmware
checks the incoming identity again before arming the bootloader. Only M7 images
with valid GIGA application vectors are accepted, capped at 1,310,720 bytes to
preserve the upper 512 KiB of flash for M4.

Successful upload requires an authenticated response from a different board boot
reporting the expected revision and ready updater. A missing response is an
uncertain result, not permission to flash again blindly. Inspect the board and
Transport first. There is no automatic firmware rollback. Power loss during
bootloader programming may require USB recovery; update only one panel at a time.

## Protocol and Resource Limits

The updater uses a small binary TCP protocol, not HTTP. Status requests contain
`HPOTA1S\n` plus a fresh 32-byte host nonce. The response is one bounded JSON line
and its HMAC-SHA256 on a second line. The signed JSON echoes the host nonce so
previous status responses cannot satisfy new verification requests.

Uploads start with a 141-byte envelope: `HPOTA1U\n`, one panel byte (1 or 2),
four-byte big-endian plaintext length, 32-byte board challenge, plaintext SHA-256,
ciphertext SHA-256 and a 32-byte HMAC over the preceding 109 bytes. Authentication
and encryption keys are derived independently with HMAC-SHA256 from the private
panel key using the labels in `ota_protocol.cpp`. The image uses AES-256-CTR with
the first 16 challenge bytes as IV. The pinned Mbed core disables its CTR helper,
so the counter stream uses Mbed TLS's AES primitive; tests cross-check it against
Python cryptography on fragmented input.

The authenticated challenge expires after 60 seconds and is consumed before
opening a staging file. Replays fail, including attempts cancelled after storage
opens. The encrypted body is streamed into `UPDATE.PART`; neither plaintext
credentials nor keys cross the LAN. Both image hashes and the embedded target
identity must match before the file becomes `UPDATE.BIN` and Arduino's OTA library
arms the bootloader. A failed transfer closes and removes the partial file.

Receive state and the 1 KiB transfer buffer are fixed-size. One connection is
processed at a time, with a five-second inactivity limit and a 180-second total
limit. Each display loop processes at most one body chunk. Storage mounts once
per boot; failed initialization is not retried in a loop. This avoids repeated
allocations in the upstream library's `begin()` path. Socket and filesystem
libraries still own internal allocations; host tests do not establish a hardware
memory plateau or bound physical flash latency.
Accepted Mbed sockets are explicitly owned and deleted after close. This bypasses
core 4.5.0's WiFiClient accepted-socket path, which closes its non-owned socket
without deleting it, and avoids that wrapper's per-connection reader task.

## Acceptance and Memory Baselines

After each bootstrap or update, confirm both panel identities remain connected
with independent empty delivery queues and increasing frame counters. Require two
fresh `MEMORY` samples with the same telemetry boot ID and increasing uptime per
panel. Record firmware revision and binary SHA-256 alongside those samples.

Capture a common baseline only after both panels are stable. Compare current
heap/LVGL usage and complete stack watermarks after an uninterrupted 24 hours;
keep peak gauges separate. Preserve backend RSS/container identities too. A board
boot change or backend process replacement interrupts its interval and requires
a new baseline. Do not force allocator activity or restart production to collect
the comparison.

Regression commands:

```sh
pytest tools/tests/test_panel_firmware.py tools/tests/test_firmware_memory.py -q
pytest tools/tests/test_firmware_websocket.py -q
python tools/ci_firmware.py
```

Native tests execute the actual C++ receiver and socket/staging logic with real
AES/HMAC/SHA compatibility calls backed by OpenSSL. Network, entropy, bootloader
and QSPI hardware are simulated; staging uses temporary host files. Hardware
acceptance must still verify bootloader behavior, filesystem layout and latency.
