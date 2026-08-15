"""Provider selection and the wttr.in slot/status boundaries.

Added after mutation testing: both `primary_env == "wttr_in"` and
`== "openweathermap"` could be flipped to `!=` with the suite green, so
WEATHER_PRIMARY_PROVIDER could silently select the wrong provider. Likewise
the midday forecast slot and the HTTP error threshold were unasserted.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from weather_poller.adapters.wttr_in import WttrInAdapter, _midday_conditions
from weather_poller.main import _build_adapters


def _env(primary: str | None) -> dict:
    env = {
        "GOOGLE_WEATHER_API_KEY": "g", "GOOGLE_WEATHER_LOCATION": "0,0",
        "OPENWEATHERMAP_API_KEY": "o", "OPENWEATHERMAP_LOCATION": "London",
        "WTTR_LOCATION": "",
    }
    if primary is not None:
        env["WEATHER_PRIMARY_PROVIDER"] = primary
    return env


@pytest.mark.parametrize("primary,expected", [
    ("wttr_in", ("wttr_in", "openweathermap")),
    ("openweathermap", ("openweathermap", "google-weather")),
    ("google", ("google-weather", "openweathermap")),
    (None, ("google-weather", "openweathermap")),
])
def test_primary_provider_selection(primary, expected):
    with patch.dict("os.environ", _env(primary), clear=True):
        chosen = _build_adapters()

    assert (chosen[0].provider_name, chosen[1].provider_name) == expected


def test_provider_selection_is_case_insensitive():
    with patch.dict("os.environ", _env("WTTR_IN"), clear=True):
        primary, _ = _build_adapters()
    assert primary.provider_name == "wttr_in"


def test_unrecognised_provider_falls_back_to_google():
    """A typo in config must not leave the panel with no weather at all."""
    with patch.dict("os.environ", _env("nonsense"), clear=True):
        primary, fallback = _build_adapters()
    assert (primary.provider_name, fallback.provider_name) == (
        "google-weather", "openweathermap")


# ---------------------------------------------------------------------------
# wttr.in conditions slot
# ---------------------------------------------------------------------------

def _slot(time: str, desc: str) -> dict:
    return {"time": time, "weatherDesc": [{"value": desc}]}


def test_midday_slot_is_preferred():
    """Overnight conditions are a poor summary of the day."""
    hourly = [_slot("0", "Clear"), _slot("1200", "Sunny"), _slot("2100", "Fog")]
    assert _midday_conditions(hourly) == "sunny"


def test_falls_back_to_first_slot_when_midday_absent():
    assert _midday_conditions([_slot("0300", "Drizzle")]) == "drizzle"


def test_empty_hourly_is_unknown_not_a_crash():
    assert _midday_conditions([]) == "unknown"


# ---------------------------------------------------------------------------
# HTTP error threshold
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [300, 301, 404, 500, 503])
def test_non_2xx_raises_weather_api_error(status):
    """300 is the boundary: `>= 300` vs `> 300` decides whether a redirect is
    treated as a successful body."""
    from weather_poller.adapter import WeatherAPIError

    adapter = WttrInAdapter(location="")
    resp = MagicMock()
    resp.status_code = status
    resp.text = "nope"
    adapter._client = MagicMock()
    adapter._client.get = MagicMock(return_value=resp)

    with pytest.raises(WeatherAPIError) as exc:
        adapter.fetch_current()
    assert exc.value.http_status == status
