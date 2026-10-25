"""Check sensor identity, source age, read-only requests, and token persistence."""
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("main", ROOT / "services/ewelink-callback/main.py")
oauth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oauth)
spec = importlib.util.spec_from_file_location("collector", ROOT / "services/ewelink-callback/collector.py")
collector = importlib.util.module_from_spec(spec)
sys.modules["main"] = oauth
spec.loader.exec_module(collector)
sys.modules.pop("main")
NOW = 1792897019


def device(**params):
    return {"deviceid": "sensor", "productModel": "SNZB-02WD", "extra": {"uiid": 7033}, "online": True,
            "params": {"temperature": "11.0", "humidity": "68.2", "trigTime": str(NOW * 1000), **params}}


def test_polling_does_not_refresh_sensor_measurement_time():
    first = collector.frame(device(), NOW)
    assert first == {"available": True, "t": 11., "h": 68.2, "measured_at": NOW}
    assert collector.frame(device(), NOW + 3599) == first
    assert collector.frame(device(), NOW + 3600) == {"available": False}


@pytest.mark.parametrize("params", [{"temperature": "NaN"}, {"humidity": "inf"}, {"humidity": "101"},
    {"temperature": "-21"}, {"temperature": "61"}, {"trigTime": ""}, {"trigTime": "bad"},
    {"trigTime": str((NOW + 1) * 1000)}])
def test_bad_readings_are_rejected(params):
    with pytest.raises(ValueError):
        collector.frame(device(**params), NOW)


def test_offline_device_never_publishes_cached_values():
    d = device(); d["online"] = False
    assert collector.frame(d, NOW) == {"available": False}


def test_different_model_does_not_become_outdoor_temperature():
    d = device(); d["extra"]["uiid"] = 7048
    with pytest.raises(ValueError):
        collector.frame(d, NOW)


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "STATE_DIR", tmp_path)
    monkeypatch.setattr(oauth, "credentials", lambda: {"app_id": "app", "app_secret": "private"})
    with oauth.database() as db:
        db.execute("INSERT INTO account VALUES (1,?,?)", ("us", json.dumps({"accessToken": "old", "refreshToken": "refresh"})))


def test_refresh_rotates_durable_tokens_then_retries_selected_read_only_device(account, monkeypatch):
    calls = []

    def request(req):
        calls.append(req)
        if len(calls) == 1:
            return {"error": 402}
        if len(calls) == 2:
            return {"error": 0, "data": {"at": "new", "rt": "new-refresh"}}
        return {"error": 0, "data": {"thingList": [{"itemType": 1, "itemData": device()}]}}

    monkeypatch.setattr(collector, "request_json", request)
    assert collector.read_device("sensor")["deviceid"] == "sensor"
    assert [r.full_url for r in calls] == ["https://us-apia.coolkit.cc/v2/device/thing",
        "https://us-apia.coolkit.cc/v2/user/refresh", "https://us-apia.coolkit.cc/v2/device/thing"]
    assert calls[1].get_header("Authorization") == "Sign " + oauth.signature("private", calls[1].data)
    assert calls[2].get_header("Authorization") == "Bearer new"
    assert json.loads(calls[2].data) == {"thingList": [{"itemType": 1, "id": "sensor"}]}
    with oauth.database() as db:
        stored = json.loads(db.execute("SELECT tokens FROM account").fetchone()[0])
    assert stored == {"accessToken": "new", "refreshToken": "new-refresh"}


def test_missing_device_fails_without_publishing(account, monkeypatch):
    monkeypatch.setattr(collector, "provider", lambda *_args: {"thingList": []})
    with pytest.raises(ValueError, match="missing"):
        collector.read_device("sensor")


def test_outdoor_delivery_uses_independent_command_and_source_time(monkeypatch):
    request = MagicMock(return_value={"accepted": True})
    monkeypatch.setattr(collector, "request_json", request)
    payload = collector.frame(device(), NOW)
    collector.publish("http://transport:8002", payload)
    req = request.call_args.args[0]
    body = json.loads(req.data)
    assert req.full_url == "http://transport:8002/internal/commands"
    assert body["cmd"] == "OUTDOOR_TEMP" and body["payload"] == payload
    assert "sensor" not in body["payload"]


def test_private_status_receipt_has_no_credentials(account):
    previous = os.umask(0o022)
    try:
        collector.write_status({"ok": True, **collector.frame(device(), NOW)})
    finally:
        os.umask(previous)
    path = oauth.STATE_DIR / "outdoor-status.json"
    assert path.stat().st_mode & 0o077 == 0
    assert "Token" not in path.read_text()
