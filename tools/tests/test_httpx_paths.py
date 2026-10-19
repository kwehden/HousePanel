"""Require explicit inventory/test updates for every outbound HTTPX path."""
import ast
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Each entry has a real-stream case in tools/httpx_contract.py, run in CI and
# again in the deployable image. Count individual methods, not just modules.
PATHS = {
    "services/aggregator/src/aggregator/dispatch_worker.py": 1,
    "services/aggregator/src/aggregator/routes.py": 1,
    "services/calendar-poller/src/calendar_poller/calendar_client.py": 1,
    "services/calendar-poller/src/calendar_poller/poller.py": 1,
    "services/ring-integration/src/ring_integration/main.py": 1,
    "services/sysmon-poller/src/sysmon_poller/main.py": 2,
    "services/transport-adapter/src/transport_adapter/state_refresh.py": 2,
    "services/weather-poller/src/weather_poller/adapters/google.py": 1,
    "services/weather-poller/src/weather_poller/adapters/openweathermap.py": 2,
    "services/weather-poller/src/weather_poller/adapters/wttr_in.py": 1,
    "services/weather-poller/src/weather_poller/poller.py": 1,
    "services/webhook-receiver/src/webhook_receiver/forwarder.py": 1,
    "tools/calendar_runtime_probe.py": 1,
}


def calls(source):
    tree = ast.parse(source)
    http_modules, constructors, safe = {"httpx"}, set(), {"request", "async_request"}
    methods = {"get", "post", "put", "patch", "delete", "head", "options", "request", "send", "stream"}
    direct = set()
    clients = {"client", "http_client", "scrape", "_client", "_http_client"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            http_modules.update(a.asname or a.name for a in node.names if a.name == "httpx")
        if isinstance(node, ast.ImportFrom) and node.module == "httpx":
            constructors.update(a.asname or a.name for a in node.names if a.name in ("Client", "AsyncClient"))
            direct.update(a.asname or a.name for a in node.names if a.name in methods)
        if isinstance(node, ast.ImportFrom) and node.module == "shared.http":
            safe.update(a.asname or a.name for a in node.names if a.name in ("request", "async_request"))
    def is_client(value):
        return isinstance(value, ast.Call) and (
            isinstance(value.func, ast.Name) and value.func.id in constructors or
            isinstance(value.func, ast.Attribute) and isinstance(value.func.value, ast.Name)
            and value.func.value.id in http_modules and value.func.attr in ("Client", "AsyncClient"))
    def client_annotation(value):
        return value is not None and any(
            isinstance(n, ast.Name) and n.id in constructors or
            isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id in http_modules and n.attr in ("Client", "AsyncClient")
            for n in ast.walk(value))
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and client_annotation(node.annotation):
            clients.add(node.arg)
        if isinstance(node, ast.AnnAssign) and client_annotation(node.annotation):
            clients.add(node.target.id if isinstance(node.target, ast.Name) else node.target.attr)
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign) and is_client(node.value):
            targets = node.targets
        if isinstance(node, (ast.With, ast.AsyncWith)):
            targets += [item.optional_vars for item in node.items if is_client(item.context_expr)]
        for target in targets:
            if isinstance(target, ast.Name):
                clients.add(target.id)
            if isinstance(target, ast.Attribute):
                clients.add(target.attr)
    changed = True
    while changed:
        previous = clients.copy()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in clients:
                clients.update(target.id for target in node.targets if isinstance(target, ast.Name))
        changed = previous != clients
    raw, owned = [], 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in direct:
            raw.append(node.lineno)
        if isinstance(f, ast.Name) and f.id in safe:
            owned += 1
        if isinstance(f, ast.Attribute) and f.attr in methods:
            receiver = f.value
            name = receiver.id if isinstance(receiver, ast.Name) else receiver.attr if isinstance(receiver, ast.Attribute) else None
            if name in clients or name in http_modules or is_client(receiver):
                raw.append(node.lineno)
        if isinstance(f, ast.Name) and f.id in constructors:
            continue
    return raw, owned


def test_httpx_inventory_has_no_unowned_or_unregistered_calls():
    found = Counter()
    files = list((ROOT / "services").glob("*/src/**/*.py")) + list((ROOT / "tools").glob("*.py"))
    for path in files:
        if path.name in {"image_smoke.py", "httpx_contract.py"}:
            continue
        source = path.read_text()
        if "httpx" not in source and "shared.http" not in source:
            continue
        raw, owned = calls(source)
        assert not raw, f"{path}: direct HTTPX call(s) at {raw}; use shared.http and add an ownership contract"
        if owned:
            found[str(path.relative_to(ROOT))] = owned
    assert found == Counter(PATHS), "Update the path inventory AND real-stream image contracts for new HTTPX paths"
    contract = ast.parse((ROOT / "tools/httpx_contract.py").read_text())
    cases = next(ast.literal_eval(node.value) for node in ast.walk(contract)
                 if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "cases" for t in node.targets))
    assert sum(map(len, cases.values())) == sum(PATHS.values())


@pytest.mark.parametrize("source", [
    "import httpx as h\nc = h.AsyncClient()\nc.get('http://x')",
    "from httpx import Client as C\nc = C()\nc.stream('GET', 'http://x')",
    "import httpx\nasync def poll(client: httpx.AsyncClient):\n await client.post('http://x')",
    "import httpx\nasync with httpx.AsyncClient() as arbitrary:\n await arbitrary.send(req)",
    "import httpx\nhttpx.get('http://x')",
    "import httpx as h\nasync def poll(arbitrary: h.AsyncClient | None):\n await arbitrary.get('http://x')",
    "from httpx import Client as C\ndef poll(arbitrary: C):\n alias = arbitrary\n alias.post('http://x')",
    "from httpx import get as fetch\nfetch('http://x')",
])
def test_guard_detects_eager_streamed_aliased_and_top_level_calls(source):
    assert calls(source)[0]
