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
