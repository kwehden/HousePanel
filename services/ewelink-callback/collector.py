"""Read one outdoor sensor and publish its original report time to HousePanel."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import threading
import time
from urllib.request import Request, urlopen

import main as oauth


class ProviderError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Provider error {code}")


def request_json(request):
    with urlopen(request, timeout=15) as response:
        body = response.read(262145)
    if len(body) > 262144:
        raise ValueError("Response exceeds size limit")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


def provider(region, config, tokens, path, payload, *, signed=False):
    body = json.dumps(payload, separators=(",", ":")).encode()
    authorization = ("Sign " + oauth.signature(config["app_secret"], body) if signed
                     else "Bearer " + tokens["accessToken"])
    value = request_json(Request(oauth.API_HOSTS[region] + path, data=body, headers={
        "Content-Type": "application/json", "X-CK-Appid": config["app_id"],
        "Authorization": authorization,
    }))
    if value.get("error") != 0:
        raise ProviderError(value.get("error"))
    if not isinstance(value.get("data"), dict):
        raise ValueError("Expected provider data")
    return value["data"]


def read_device(device_id):
    config = oauth.credentials()
    with oauth.database() as db:
        account = db.execute("SELECT region,tokens FROM account WHERE id=1").fetchone()
    if config is None or account is None:
        raise ValueError("Account setup incomplete")
    region, stored = account
    tokens = json.loads(stored)
    payload = {"thingList": [{"itemType": 1, "id": device_id}]}
    try:
        data = provider(region, config, tokens, "/v2/device/thing", payload)
    except ProviderError as exc:
        if exc.code != 402:
            raise
        refreshed = provider(region, config, tokens, "/v2/user/refresh",
                             {"rt": tokens["refreshToken"]}, signed=True)
        if not all(isinstance(refreshed.get(k), str) and refreshed[k] for k in ("at", "rt")):
            raise ValueError("Invalid refreshed tokens")
        tokens = {"accessToken": refreshed["at"], "refreshToken": refreshed["rt"]}
        with oauth.database() as db:
            updated = db.execute("UPDATE account SET tokens=? WHERE id=1 AND region=? AND tokens=?",
                                 (json.dumps(tokens), region, stored)).rowcount
        if updated != 1:
            raise ValueError("Authorization changed during refresh; retry next poll")
        data = provider(region, config, tokens, "/v2/device/thing", payload)
    devices = [x.get("itemData", {}) for x in data.get("thingList", []) if x.get("itemType") == 1]
    matches = [x for x in devices if x.get("deviceid") == device_id]
    if len(matches) != 1:
        raise ValueError("Selected sensor missing or ambiguous")
    return matches[0]


def frame(device, now):
    """Use source report time. Polling cached values must never renew their age."""
    if device.get("productModel") != "SNZB-02WD" or device.get("extra", {}).get("uiid") != 7033:
        raise ValueError("Unexpected outdoor sensor model")
    if device.get("online") is not True:
        return {"available": False}
    params = device.get("params", {})
    temperature, humidity = float(params["temperature"]), float(params["humidity"])
    reported = params.get("trigTime")
    if not isinstance(reported, str) or len(reported) != 13 or not reported.isdecimal():
        raise ValueError("Missing sensor report timestamp")
    measured = int(reported) // 1000
    if not (math.isfinite(temperature) and -20 <= temperature <= 60 and
            math.isfinite(humidity) and 0 <= humidity <= 100 and 1577836800 <= measured <= now):
        raise ValueError("Invalid sensor measurement")
    if now - measured >= 3600:
        return {"available": False}
    return {"available": True, "t": round(temperature, 1), "h": round(humidity, 1), "measured_at": measured}


def publish(transport, payload):
    # OUTDOOR_TEMP is understood only by the simplified primary. Existing full
    # panels ignore unknown commands; the filament SYSMON stream is untouched.
    value = request_json(Request(transport.rstrip("/") + "/internal/commands",
        data=json.dumps({"cmd": "OUTDOOR_TEMP", "priority": 0, "payload": payload,
                         "event_id": "outdoor-" + str(time.time_ns())}).encode(),
        headers={"Content-Type": "application/json"}))
    if value.get("accepted") is not True:
        raise ValueError("Transport rejected reading")


def write_status(value):
    path = oauth.STATE_DIR / "outdoor-status.json"
    temporary = Path(str(path) + ".tmp")
    with os.fdopen(os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600), "w") as stream:
        stream.write(json.dumps(value) + "\n")
    temporary.replace(path)


def run():
    device_id = os.environ["EWELINK_DEVICE_ID"]
    transport = os.getenv("TRANSPORT_URL", "http://housepanel-transport-adapter:8002")
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    while not stopped.is_set():
        started = time.monotonic()
        observed = datetime.now(timezone.utc).isoformat()
        try:
            device = read_device(device_id)
            payload = frame(device, int(time.time()))
            publish(transport, payload)
            write_status({"ok": True, "device_id": device_id, "observed_at": observed, **payload})
            print("Outdoor poll published", flush=True)
        except Exception as exc:
            # Provider error bodies and HTTP exception URLs may contain secrets.
            write_status({"ok": False, "observed_at": observed, "error_type": type(exc).__name__})
            print("Outdoor poll failed: " + type(exc).__name__, flush=True)
        stopped.wait(max(1, 60 - (time.monotonic() - started)))


if __name__ == "__main__":
    os.umask(0o077)
    run()
