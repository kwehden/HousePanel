"""Execute the actual firmware collector/encoder against deterministic RTOS data."""
import json
from pathlib import Path
import subprocess
import sys

from transport_adapter.memory_telemetry import MemorySample

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ci_firmware


def test_native_collector_wire_contract_cadence_and_bounds(tmp_path):
    fixtures = ROOT / "tools/tests/firmware"
    for name in ("mbed.h", "platform/mbed_stats.h", "hal/trng_api.h", "cmsis_os2.h",
                 "Arduino_H7_Video.h", "lvgl.h"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#include "memory_runtime.h"\n')
    firmware = ROOT / "firmware/housepanel-giga"
    binary = tmp_path / "memory-test"
    subprocess.run([
        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
        "-I", str(tmp_path), "-I", str(fixtures), "-I", str(firmware),
        str(fixtures / "memory_test.cpp"), str(firmware / "memory_format.cpp"),
        str(firmware / "memory_telemetry.cpp"), "-o", str(binary),
    ], check=True)
    rows = [json.loads(line) for line in subprocess.check_output([binary], text=True).splitlines()]
    normal, truncated, empty, maximal = rows
    for row in (normal, truncated, maximal):
        MemorySample.model_validate(row)
    assert normal["heap_current"] == 1000
    assert normal["stack_high_water"] == 3 * (1024 - 256)
    assert normal["stack_min_free"] == 256
    assert normal["stack_complete"] is True
    assert normal["gui_used"] == 31072
    assert truncated["stack_complete"] is False and truncated["stack_count"] == 32
    assert empty["stack_count"] == 0 and empty["stack_min_free"] == 0
    assert empty["stack_complete"] is True  # Backend deliberately rejects no-thread samples.
    assert maximal["uptime_ms"] == 2**63 - 1
    assert maximal["heap_current"] == 2**32 - 1


def test_ci_compiles_both_identities_with_only_dummy_credentials(tmp_path, monkeypatch):
    sketch = tmp_path / "firmware/housepanel-giga"
    sketch.mkdir(parents=True)
    (sketch / "secrets.h").write_text("PRIVATE MUST NOT BE COPIED")
    (sketch / "secrets.h.example").write_text("DUMMY CREDENTIALS")
    calls = []

    def compile_only(command, *, check):
        assert command[:2] == ["arduino-cli", "compile"] and check
        copied = Path(command[-1])
        assert (copied / "secrets.h").read_text() == "DUMMY CREDENTIALS"
        calls.append(command)

    monkeypatch.setattr(ci_firmware, "ROOT", tmp_path)
    monkeypatch.setattr(ci_firmware.subprocess, "run", compile_only)
    ci_firmware.main()
    assert len(calls) == 2
    assert '-DHOUSEPANEL_PANEL_ID="primary" -DHOUSEPANEL_HOSTNAME="housepanel"' in calls[0][5]
    assert '-DHOUSEPANEL_PANEL_ID="panel-2" -DHOUSEPANEL_HOSTNAME="housepanel-2"' in calls[1][5]
    assert (sketch / "secrets.h").read_text() == "PRIVATE MUST NOT BE COPIED"
