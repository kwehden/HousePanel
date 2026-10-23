"""Exercise the firmware's real freshness decision using transported source times."""
from pathlib import Path
import subprocess

import pytest

from transport_adapter.stream_decompose import decompose_command

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def freshness_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp("filament-freshness") / "freshness"
    subprocess.run([
        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-x", "c++", "-",
        "-I", str(ROOT / "firmware/giga-filament"), "-o", str(binary),
    ], input='''#include "sensor_freshness.h"
#include <iostream>
int main() {
  uint64_t now, measured;
  bool clock;
  while (std::cin >> clock >> now >> measured)
    std::cout << sensor_is_fresh(clock, now, measured) << '\\n';
}
''', text=True, check=True)
    return binary


def decisions(binary, cases):
    data = "".join(f"{int(clock)} {now} {measured}\n" for clock, now, measured in cases)
    return [int(row) for row in subprocess.check_output([binary], input=data, text=True).splitlines()]


def test_reconnect_replays_expire_and_new_identical_reading_recovers(freshness_binary):
    payload = {"temp_c": 24.4, "humidity_pct": 34.8, "timestamp": "2026-10-23T05:00:00Z"}
    cases = []
    # HELLO replays the same cached payload every 90 seconds during an outage.
    for elapsed in (0, 90, 180, 270, 299, 300, 360, 600):
        (frame,) = decompose_command("SYSMON-UPDATE", payload)
        cases.append((True, 1792731600 + elapsed, frame["measured_at"]))
    # An unchanged value from an actual new measurement must recover normally.
    payload["timestamp"] = "2026-10-23T05:10:00Z"
    (frame,) = decompose_command("SYSMON-UPDATE", payload)
    cases.append((True, 1792732200, frame["measured_at"]))
    assert decisions(freshness_binary, cases) == [1, 1, 1, 1, 1, 0, 0, 0, 1]


def test_unknown_clock_missing_age_and_future_measurements_are_not_live(freshness_binary):
    assert decisions(freshness_binary, [
        (False, 1792731600, 1792731600),
        (True, 1792731600, 0),
        (True, 1792731600, 1792731601),
    ]) == [0, 0, 0]
