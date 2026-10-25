"""Small eWeLink OAuth receiver. Authorization links are created by operator CLI."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import sqlite3
import sys
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

REDIRECT_URL = os.getenv("REDIRECT_URL", "http://standpunkt:8765/ewelink/callback")
STATE_DIR = Path(os.getenv("STATE_DIR", "/data"))
CREDENTIALS_FILE = Path(os.getenv("CREDENTIALS_FILE", "/credentials/credentials.json"))
API_HOSTS = {region: f"https://{region}-apia.coolkit.cc" for region in ("us", "eu", "as")}
API_HOSTS["cn"] = "https://cn-apia.coolkit.cn"
os.umask(0o077)


def credentials() -> dict[str, str] | None:
    try:
        value = json.loads(CREDENTIALS_FILE.read_text())
        if all(isinstance(value.get(k), str) and value[k] for k in ("app_id", "app_secret")):
            return value
    except (OSError, ValueError, AttributeError):
        pass
    return None


@contextmanager
def database():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(STATE_DIR / "oauth.sqlite", timeout=5)
    db.execute("CREATE TABLE IF NOT EXISTS pending (state_hash TEXT PRIMARY KEY, expires REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), region TEXT, tokens TEXT)")
    db.commit()
    try:
        with db:
            yield db
    finally:
        db.close()


def signature(secret: str, payload: bytes) -> str:
    return base64.b64encode(hmac.digest(secret.encode(), payload, "sha256")).decode()


def authorization_url() -> str:
    config = credentials()
    if config is None:
        raise ValueError("App credentials are not configured")
    state = secrets.token_urlsafe(32)
    with database() as db:
        db.execute("DELETE FROM pending WHERE expires < ?", (time.time(),))
        db.execute("INSERT INTO pending VALUES (?, ?)",
                   (hashlib.sha256(state.encode()).hexdigest(), time.time() + 900))
    seq = str(int(time.time() * 1000))
    return "https://c2ccdn.coolkit.cc/oauth/index.html?" + urlencode({
        "clientId": config["app_id"], "seq": seq,
        "authorization": signature(config["app_secret"], f'{config["app_id"]}_{seq}'.encode()),
        "redirectUrl": REDIRECT_URL, "grantType": "authorization_code",
        "state": state, "nonce": secrets.token_hex(4), "showQRCode": "false",
    })


def complete_authorization(code: str, state: str, region: str) -> None:
    config = credentials()
    if config is None:
        raise ValueError("App credentials are not configured")
    if region not in API_HOSTS or not code or len(code) > 1024 or not state or len(state) > 128:
        raise ValueError("Invalid authorization response")
    with database() as db:
        removed = db.execute("DELETE FROM pending WHERE state_hash=? AND expires>=?",
                             (hashlib.sha256(state.encode()).hexdigest(), time.time())).rowcount
    if removed != 1:
        raise ValueError("Authorization state is invalid, expired, or already used")
    payload = json.dumps({"code": code, "redirectUrl": REDIRECT_URL,
                          "grantType": "authorization_code"}, separators=(",", ":")).encode()
    request = Request(API_HOSTS[region] + "/v2/user/oauth/token", data=payload, headers={
        "Content-Type": "application/json", "X-CK-Appid": config["app_id"],
        "Authorization": "Sign " + signature(config["app_secret"], payload),
    })
    with urlopen(request, timeout=10) as response:
        body = response.read(65537)
    if len(body) > 65536:
        raise RuntimeError("Token response exceeded size limit")
    result = json.loads(body)
    data = result.get("data", {})
    if result.get("error") != 0 or not isinstance(data, dict) or not all(
        isinstance(data.get(k), str) and data[k] for k in ("accessToken", "refreshToken")
    ):
        raise RuntimeError("Provider did not return valid tokens")
    with database() as db:
        db.execute("INSERT OR REPLACE INTO account VALUES (1, ?, ?)", (region, json.dumps(data)))


class Handler(BaseHTTPRequestHandler):
    server_version = "HousePanelOAuth"

    def log_message(self, *_args):
        # Request targets contain authorization codes. Never log URLs or queries.
        pass

    def reply(self, status: int, body: str, content_type="text/html; charset=utf-8"):
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def do_HEAD(self):
        # HEAD probes never consume an OAuth response.
        path = urlsplit(self.path).path
        self.reply(200 if path in ("/", "/healthz", "/ewelink/callback") else 404, "")

    def do_GET(self):
        if len(self.path) > 8192:
            return self.reply(414, "Request too long")
        url = urlsplit(self.path)
        if url.path == "/healthz":
            try:
                with database() as db:
                    connected = db.execute("SELECT 1 FROM account WHERE id=1").fetchone() is not None
            except sqlite3.Error:
                return self.reply(503, '{"status":"storage_unavailable"}', "application/json")
            return self.reply(200, json.dumps({"status": "ok", "oauth_configured": credentials() is not None,
                                              "account_connected": connected}), "application/json")
        if url.path not in ("/", "/ewelink/callback"):
            return self.reply(404, "Not found")
        if not url.query:
            message = ("Ready for eWeLink account authorization." if credentials() else
                       "Callback service is running. Waiting for eWeLink application credentials.")
            return self.reply(200, "<!doctype html><html lang=en><meta charset=utf-8>"
                              "<title>HousePanel eWeLink</title><h1>HousePanel eWeLink</h1><p>" + message + "</p></html>")
        if url.path != "/ewelink/callback":
            return self.reply(404, "Not found")
        try:
            fields = parse_qs(url.query, keep_blank_values=True, max_num_fields=20)
        except ValueError:
            return self.reply(400, "Invalid OAuth callback.")
        if any(len(fields.get(k, [])) != 1 for k in ("code", "state", "region")):
            return self.reply(400, "Invalid OAuth callback. Start a new authorization from HousePanel.")
        if credentials() is None:
            return self.reply(503, "Application credentials are not configured yet.")
        try:
            complete_authorization(fields["code"][0], fields["state"][0], fields["region"][0])
        except ValueError:
            return self.reply(400, "Invalid or expired authorization. Start a new authorization from HousePanel.")
        except Exception:
            # Provider exceptions can include response bodies, URLs, or tokens.
            print("OAuth token exchange failed", flush=True)
            return self.reply(502, "Authorization could not be completed. Start a new authorization from HousePanel.")
        self.reply(200, "<!doctype html><html lang=en><meta charset=utf-8><title>HousePanel eWeLink</title>"
                       "<h1>Account connected</h1><p>Authorization completed. You may close this tab.</p></html>")


if __name__ == "__main__":
    if sys.argv[1:] == ["authorize"]:
        try:
            print(authorization_url())
        except ValueError as exc:
            sys.exit(str(exc))
    else:
        with database():
            pass
        print("eWeLink callback listening on port 8765", flush=True)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        with ThreadingHTTPServer((os.getenv("BIND_HOST", "0.0.0.0"), 8765), Handler) as server:
            server.serve_forever()
