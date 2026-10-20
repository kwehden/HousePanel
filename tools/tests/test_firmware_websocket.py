"""Run firmware send logic and the unmodified pinned ArduinoHttpClient on a fake NIC."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from transport_adapter.memory_telemetry import MemorySample

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from firmware_httpclient import sources


def decode_frames(wire):
    result = []
    while wire:
        assert wire[0] == 0x81 and wire[1] & 0x80  # FIN + text, client-masked.
        length = wire[1] & 127
        header = 2
        if length == 126:
            length = int.from_bytes(wire[2:4], "big")
            header = 4
        elif length == 127:
            length = int.from_bytes(wire[2:10], "big")
            header = 10
        mask = wire[header:header + 4]
        payload = wire[header + 4:header + 4 + length]
        assert len(mask) == 4 and len(payload) == length
        result.append(bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))
        wire = wire[header + 4 + length:]
    return result


@pytest.fixture(scope="module", params=["primary", "panel-2"])
def compiled_send_path(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("actual-websocket")
    upstream = sources(ROOT / "build/test-deps/ArduinoHttpClient-0.6.1.zip", directory / "upstream")
    sketch = directory / "sketch"
    sketch.mkdir()
    for name in ("ws_client.cpp", "ws_client.h", "memory_format.cpp", "memory_telemetry.h",
                 "command_parser.h", "config.h", "checked_wifi_client.h"):
        shutil.copyfile(ROOT / "firmware/housepanel-giga" / name, sketch / name)
    shutil.copyfile(ROOT / "firmware/housepanel-giga/secrets.h.example", sketch / "secrets.h")
    fixtures = ROOT / "tools/tests/firmware"
    panel_id = request.param
    hostname = "housepanel" if panel_id == "primary" else "housepanel-2"
    base = ["g++", "-std=c++17", "-g", "-fsanitize=undefined", "-fno-sanitize-recover=all",
            "-I", str(fixtures / "arduino"), "-I", str(sketch), "-I", str(upstream),
            f'-DHOUSEPANEL_PANEL_ID="{panel_id}"', f'-DHOUSEPANEL_HOSTNAME="{hostname}"']
    binary = directory / "send-path"
    subprocess.run(base + ["-DWS_TX_BUFFER_SIZE=768", str(sketch / "ws_client.cpp"),
                          str(sketch / "memory_format.cpp"), str(fixtures / "websocket_send_test.cpp"),
                          str(upstream / "WebSocketClient.cpp"), str(upstream / "HttpClient.cpp"),
                          str(upstream / "b64.cpp"), "-o", str(binary)], check=True)
    return base, sketch, binary, panel_id


def test_actual_websocket_send_path_round_trip(compiled_send_path):
    _, _, binary, panel_id = compiled_send_path
    rows = {}
    for line in subprocess.check_output([binary], text=True).splitlines():
        name, hex_wire = line.split(" ", 1)
        rows[name] = decode_frames(bytes.fromhex(hex_wire))
    hello = json.loads(rows["hello"][0])
    assert hello["cmd"] == "HELLO" and hello["panel_id"] == panel_id
    assert len(rows["normal"]) == len(rows["maximal"]) == 1
    normal = MemorySample.model_validate_json(rows["normal"][0])
    maximal = MemorySample.model_validate_json(rows["maximal"][0])
    assert len(rows["normal"][0]) > 128
    assert normal.heap_current == 1000
    assert maximal.heap_current == 2**32 - 1 and maximal.uptime_ms == 2**63 - 1
    assert len(rows["reconnected"]) == 2
    assert json.loads(rows["reconnected"][0])["cmd"] == "HELLO"
    MemorySample.model_validate_json(rows["reconnected"][1])
    assert len(rows["after_header_failures"]) == 2
    assert json.loads(rows["after_header_failures"][0])["cmd"] == "HELLO"
    MemorySample.model_validate_json(rows["after_header_failures"][1])
    assert rows["exact_capacity"] == [b"x" * 768]


def test_default_library_capacity_fails_compile_instead_of_silent_truncation(compiled_send_path, tmp_path):
    base, sketch, _, _ = compiled_send_path
    failed = subprocess.run(base + ["-c", str(sketch / "ws_client.cpp"), "-o", str(tmp_path / "bad.o")],
                            text=True, capture_output=True)
    assert failed.returncode != 0
    assert "Build all firmware/library sources with -DWS_TX_BUFFER_SIZE=768" in failed.stderr


def test_corrupt_cached_dependency_fails_closed(tmp_path):
    cache = tmp_path / "archive.zip"
    cache.write_bytes(b"not the pinned ArduinoHttpClient archive")
    with pytest.raises(ValueError, match="checksum"):
        sources(cache, tmp_path / "source")
    assert not (tmp_path / "source").exists()
