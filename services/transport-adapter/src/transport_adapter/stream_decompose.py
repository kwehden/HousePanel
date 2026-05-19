from __future__ import annotations


def decompose_command(cmd: str, payload: dict) -> list[dict]:
    """
    Decompose a large WEATHER-UPDATE or CALENDAR-UPDATE into a stream of
    small messages (each < 200 bytes on the wire) suitable for the Giga's
    256-byte WiFiClient socket buffer.
    """
    if cmd == "WEATHER-UPDATE":
        return _weather_stream(payload)
    if cmd == "CALENDAR-UPDATE":
        return _calendar_stream(payload)
    return [{**payload, "cmd": cmd}]


def _weather_stream(p: dict) -> list[dict]:
    temp = float(p.get("temperature_c") or 0.0)
    msgs = [
        {
            "cmd": "WEATHER",
            "t": temp,
            "co": (p.get("conditions") or "")[:30],
            "h": float(p.get("today_high_c") or temp),
            "l": float(p.get("today_low_c") or temp),
        }
    ]
    for i, day in enumerate((p.get("forecast") or [])[:4]):
        msgs.append({
            "cmd": "WEATHER_DAY",
            "i": i,
            "l": (day.get("day_label") or "")[:3],
            "h": float(day.get("high_c") or 0.0),
            "lo": float(day.get("low_c") or 0.0),
            "c": (day.get("conditions") or "")[:24],
        })
    return msgs


def _calendar_stream(p: dict) -> list[dict]:
    # Cap events with the same summary at 5 so recurring work entries
    # (e.g. "Office" × 23) don't push unique family events off screen.
    MAX_SAME = 5
    counts: dict[str, int] = {}
    filtered: list[dict] = []
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
            "s": (event.get("summary") or "")[:50],
            "t": time_str[:16],
            "a": all_day,
        })
    return msgs
