import pytest
from threading import Event

from transport_adapter import state
from transport_adapter.main import app


@pytest.fixture(autouse=True)
def isolated_panels(monkeypatch):
    panels = {panel_id: state.Panel(panel_id) for panel_id in ("primary", "panel-2")}
    monkeypatch.setattr(state, "panels", panels)
    monkeypatch.setattr(state, "primary", panels["primary"])


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


@pytest.fixture
def websocket_lifecycle():
    """Observe actual ASGI completion before TestClient cancels its portal task."""
    finished = {path: Event() for path in ("/ws/panel", "/ws/panels/panel-2")}

    async def observed_app(scope, receive, send):
        try:
            await app(scope, receive, send)
        finally:
            if scope["type"] == "websocket":
                finished[scope["path"]].set()

    def disconnect(socket, path):
        socket.close()
        assert finished[path].wait(2), f"ASGI session did not finish for {path}"

    return observed_app, disconnect
