import pytest

from transport_adapter import state


@pytest.fixture(autouse=True)
def isolated_panels(monkeypatch):
    panels = {panel_id: state.Panel(panel_id) for panel_id in ("primary", "panel-2")}
    monkeypatch.setattr(state, "panels", panels)
    monkeypatch.setattr(state, "primary", panels["primary"])


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )
