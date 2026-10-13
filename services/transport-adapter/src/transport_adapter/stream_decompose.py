from __future__ import annotations
import json
from typing import Any

JsonObject = dict[str, Any]
MAX_FRAME_BYTES = 200


def _utf8_prefix(value: str, max_bytes: int) -> str:
    return value.encode()[:max_bytes].decode(errors="ignore")


def encode_frame(frame: JsonObject) -> str:
    return json.dumps(frame, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def fit_frame(frame: JsonObject) -> JsonObject:
    result = dict(frame)
    while len(encode_frame(result).encode()) >= MAX_FRAME_BYTES:
        fields = [key for key, value in result.items() if key != "cmd" and isinstance(value, str) and value]
        if not fields:
            raise ValueError("Non-text frame exceeds the firmware byte budget")
        key = max(fields, key=lambda k: len(result[k].encode()))
        value = result[key]
        low, high = 0, len(value)
        while low < high:
            mid = (low + high + 1) // 2
            result[key] = value[:mid]
            if len(encode_frame(result).encode()) < MAX_FRAME_BYTES:
                low = mid
            else:
                high = mid - 1
        result[key] = value[:low]
    return result


def decompose_command(cmd: str, payload: JsonObject) -> list[JsonObject]:
    """
    Decompose a large WEATHER-UPDATE or CALENDAR-UPDATE into a stream of
    small messages (each < 200 bytes on the wire) suitable for the Giga's
    256-byte WiFiClient socket buffer.
    """
    if cmd == "WEATHER-UPDATE":
        frames = _weather_stream(payload)
    elif cmd == "CALENDAR-UPDATE":
        frames = _calendar_stream(payload)
    elif cmd == "SYSMON-UPDATE":
        frames = _sysmon_stream(payload)
    else:
        frames = [{**payload, "cmd": cmd}]
    return [fit_frame(frame) for frame in frames]


def _weather_stream(p: JsonObject) -> list[JsonObject]:
    temp = float(p.get("temperature_c") or 0.0)
    msgs = [
        {
            "cmd": "WEATHER",
            "t": temp,
            "co": _utf8_prefix(p.get("conditions") or "", 30),
            "h": float(p.get("today_high_c") or temp),
            "l": float(p.get("today_low_c") or temp),
        }
    ]
    for i, day in enumerate((p.get("forecast") or [])[:4]):
        msgs.append({
            "cmd": "WEATHER_DAY",
            "i": i,
            "l": _utf8_prefix(day.get("day_label") or "", 3),
            "h": float(day.get("high_c") or 0.0),
            "lo": float(day.get("low_c") or 0.0),
            "c": _utf8_prefix(day.get("conditions") or "", 24),
        })
    return msgs


def _sysmon_stream(p: JsonObject) -> list[JsonObject]:
    temp_c = float(p.get("temp_c") or 0.0)
    humidity_pct = float(p.get("humidity_pct") or 0.0)
    return [{"cmd": "SYSMON_TEMP", "t": round(temp_c, 1), "h": round(humidity_pct, 1)}]


def _calendar_stream(p: JsonObject) -> list[JsonObject]:
    # Cap events with the same summary at 5 so recurring work entries
    # (e.g. "Office" × 23) don't push unique family events off screen.
    MAX_SAME = 5
    counts: dict[str, int] = {}
    filtered: list[JsonObject] = []
    for ev in (p.get("events") or []):
        s = ev.get("summary") or ""
        if counts.get(s, 0) < MAX_SAME:
            filtered.append(ev)
            counts[s] = counts.get(s, 0) + 1

    msgs = []
    for i, event in enumerate(filtered[:8]):
        start = event.get("start") or ""
        all_day = bool(event.get("all_day"))
        if all_day:
            time_str = start[:10]
        else:
            t = start.find("T")
            time_str = start[t + 1 : t + 6] if t >= 0 else start[:10]
        msgs.append({
            "cmd": "CAL_EVENT",
            "i": i,
            "s": _utf8_prefix(event.get("summary") or "", 50),
            "t": _utf8_prefix(time_str, 16),
            "a": all_day,
        })
    return msgs
