"""Payload values must survive decomposition.

Added after mutation testing: `p.get("temperature_c") or 0.0` could be changed
to `and 0.0` — silently zeroing every temperature on the panel — without a
single test failing. Nothing asserted the values, only the shapes.
"""
from __future__ import annotations

import pytest

from transport_adapter.stream_decompose import decompose_command


def _weather(**over) -> dict:
    base = {
        "temperature_c": 21.5,
        "conditions": "Partly cloudy",
        "today_high_c": 24.0,
        "today_low_c": 12.0,
    }
    base.update(over)
    return base


def test_weather_values_reach_the_wire():
    (msg,) = decompose_command("WEATHER-UPDATE", _weather())

    assert msg["cmd"] == "WEATHER"
    assert msg["t"] == 21.5
    assert msg["co"] == "Partly cloudy"
    assert msg["h"] == 24.0
    assert msg["l"] == 12.0


def test_absent_temperature_falls_back_to_zero():
    (msg,) = decompose_command("WEATHER-UPDATE", _weather(temperature_c=None))
    assert msg["t"] == 0.0


def test_absent_high_low_fall_back_to_current_temperature():
    """Better to repeat the current reading than render 0°C as today's high."""
    (msg,) = decompose_command(
        "WEATHER-UPDATE", _weather(today_high_c=None, today_low_c=None)
    )
    assert msg["h"] == 21.5
    assert msg["l"] == 21.5


def test_negative_temperature_is_preserved():
    """A falsy-adjacent value that must not be swallowed by an `or` default."""
    (msg,) = decompose_command("WEATHER-UPDATE", _weather(temperature_c=-4.5))
    assert msg["t"] == -4.5


def test_zero_temperature_survives_the_or_default():
    """0.0 is falsy, so `or 0.0` collapses it to the same value by luck.
    Pinned so a future default change cannot turn 0°C into something else."""
    (msg,) = decompose_command("WEATHER-UPDATE", _weather(temperature_c=0.0))
    assert msg["t"] == 0.0


def test_conditions_truncated_to_thirty_chars():
    (msg,) = decompose_command(
        "WEATHER-UPDATE", _weather(conditions="x" * 60)
    )
    assert msg["co"] == "x" * 30


def test_forecast_days_capped_at_four_with_values_intact():
    payload = _weather(forecast=[
        {"day_label": f"Day{i}", "high_c": 20.0 + i, "low_c": 10.0 + i,
         "conditions": f"cond{i}"}
        for i in range(6)
    ])
    msgs = decompose_command("WEATHER-UPDATE", payload)
    days = [m for m in msgs if m["cmd"] == "WEATHER_DAY"]

    assert len(days) == 4
    assert [d["i"] for d in days] == [0, 1, 2, 3]
    assert days[0]["h"] == 20.0
    assert days[3]["lo"] == 13.0
    assert days[0]["l"] == "Day"          # label truncated to 3 chars
    assert days[2]["c"] == "cond2"


def test_unknown_command_passes_through_untouched():
    out = decompose_command("OTA_PAUSE", {"reason": "flash"})
    assert out == [{"reason": "flash", "cmd": "OTA_PAUSE"}]


@pytest.mark.parametrize("cmd", ["WEATHER-UPDATE", "CALENDAR-UPDATE", "SYSMON-UPDATE"])
def test_every_message_carries_a_cmd(cmd):
    for msg in decompose_command(cmd, _weather()):
        assert msg.get("cmd"), f"{cmd} produced a message with no cmd"
