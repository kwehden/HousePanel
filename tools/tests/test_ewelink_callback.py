"""Exercise the actual OAuth callback HTTP surface and one-use token exchange."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("ewelink_callback", ROOT / "services/ewelink-callback/main.py")
callback = importlib.util.module_from_spec(spec)
spec.loader.exec_module(callback)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(callback, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(callback, "CREDENTIALS_FILE", tmp_path / "credentials.json")
    return callback


def configure(app):
    app.CREDENTIALS_FILE.write_text(json.dumps({"app_id": "example-app", "app_secret": "private-app-secret"}))


@pytest.fixture
def server(app):
    http = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http.server_port}"
    http.shutdown()
    http.server_close()
    thread.join()


def test_setup_page_and_health_work_without_credentials(app, server):
    with urlopen(server + "/ewelink/callback") as response:
        assert response.status == 200
        assert b"Waiting for eWeLink application credentials" in response.read()
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Referrer-Policy"] == "no-referrer"
    with urlopen(server + "/healthz") as response:
        assert json.load(response) == {"status": "ok", "oauth_configured": False, "account_connected": False}


def test_authorization_link_does_not_expose_secret(app):
    configure(app)
    link = app.authorization_url()
    fields = parse_qs(urlsplit(link).query)
    assert fields["redirectUrl"] == [app.REDIRECT_URL]
    assert fields["authorization"] == [app.signature("private-app-secret", ("example-app_" + fields["seq"][0]).encode())]
    assert len(fields["state"][0]) >= 40
    assert "private-app-secret" not in link
    # Signature example from the official documentation.
    assert app.signature("abc", b"ABC_123") == "v1+mfNY2ukxswM8sZOTg99srZsVnUVv9DGXeav1096M="


def test_exchange_is_signed_and_persists_tokens_once(app, monkeypatch):
    configure(app)
    state = parse_qs(urlsplit(app.authorization_url()).query)["state"][0]
    tokens = {"accessToken": "private-access", "refreshToken": "private-refresh"}
    opened = MagicMock()
    opened.return_value.__enter__.return_value.read.return_value = json.dumps({"error": 0, "data": tokens}).encode()
    monkeypatch.setattr(app, "urlopen", opened)
    app.complete_authorization("private-code", state, "us")
    request = opened.call_args.args[0]
    assert request.full_url == "https://us-apia.coolkit.cc/v2/user/oauth/token"
    assert request.get_header("Authorization") == "Sign " + app.signature("private-app-secret", request.data)
    assert json.loads(request.data)["redirectUrl"] == app.REDIRECT_URL
    with app.database() as db:
        region, data = db.execute("SELECT region, tokens FROM account WHERE id=1").fetchone()
    assert region == "us"
    assert json.loads(data) == tokens
    with pytest.raises(ValueError, match="already used"):
        app.complete_authorization("private-code", state, "us")
    assert opened.call_count == 1


@pytest.mark.parametrize("region", ["https://attacker.invalid", "", "unknown"])
def test_regions_are_allowlisted(app, region, monkeypatch):
    configure(app)
    opened = MagicMock()
    monkeypatch.setattr(app, "urlopen", opened)
    with pytest.raises(ValueError):
        app.complete_authorization("code", "state", region)
    opened.assert_not_called()


def test_expired_state_cannot_exchange(app, monkeypatch):
    configure(app)
    state = parse_qs(urlsplit(app.authorization_url()).query)["state"][0]
    with app.database() as db:
        db.execute("UPDATE pending SET expires=?", (time.time() - 1,))
    opened = MagicMock()
    monkeypatch.setattr(app, "urlopen", opened)
    with pytest.raises(ValueError, match="expired"):
        app.complete_authorization("code", state, "us")
    opened.assert_not_called()


@pytest.mark.parametrize("query", ["code=private-code", "code=x&code=y&state=z&region=us", "&".join(f"a{i}=x" for i in range(21))])
def test_malformed_callbacks_do_not_log_or_reflect_codes(server, query, capsys):
    with pytest.raises(HTTPError) as failure:
        urlopen(server + "/ewelink/callback?" + query)
    assert failure.value.code == 400
    assert b"private-code" not in failure.value.read()
    captured = capsys.readouterr()
    assert "private-code" not in captured.out + captured.err


def test_provider_failure_is_redacted(app, server, monkeypatch, capsys):
    configure(app)
    state = parse_qs(urlsplit(app.authorization_url()).query)["state"][0]
    monkeypatch.setattr(app, "urlopen", MagicMock(side_effect=RuntimeError("private-provider-response")))
    with pytest.raises(HTTPError) as failure:
        urlopen(server + "/ewelink/callback?code=code&state=" + state + "&region=us")
    assert failure.value.code == 502
    assert b"private-provider-response" not in failure.value.read()
    captured = capsys.readouterr()
    assert "private-provider-response" not in captured.out + captured.err


def test_head_probe_cannot_consume_authorization(app, server, monkeypatch):
    complete = MagicMock()
    monkeypatch.setattr(app, "complete_authorization", complete)
    with urlopen(Request(server + "/ewelink/callback?code=x&state=y&region=us", method="HEAD")) as response:
        assert response.status == 200
    complete.assert_not_called()


def test_import_preserves_umask_and_shared_build_directory_permissions(tmp_path):
    subprocess.run([sys.executable, "-c", '''
import importlib.util, os, pathlib, sys
os.umask(0o022)
spec = importlib.util.spec_from_file_location("callback", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert os.umask(0o022) == 0o022, "Callback import changed the host process umask"
build = pathlib.Path(sys.argv[2]) / "build"
build.mkdir()
assert build.stat().st_mode & 0o777 == 0o755
''', str(ROOT / "services/ewelink-callback/main.py"), str(tmp_path)], check=True)


def test_database_permissions_do_not_depend_on_process_umask(app):
    previous = os.umask(0o022)
    try:
        with app.database():
            pass
        assert app.STATE_DIR.stat().st_mode & 0o777 == 0o700
        assert (app.STATE_DIR / "oauth.sqlite").stat().st_mode & 0o777 == 0o600
    finally:
        os.umask(previous)
