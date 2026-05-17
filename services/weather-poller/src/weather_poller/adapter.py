from __future__ import annotations

import typing
from typing import Protocol, runtime_checkable

from shared.models import WeatherConditions


class WeatherAPIError(Exception):
    def __init__(self, provider: str, http_status: int, message: str) -> None:
        super().__init__(f"[{provider}] HTTP {http_status}: {message}")
        self.provider = provider
        self.http_status = http_status
        self.message = message


@runtime_checkable
class WeatherAdapter(Protocol):
    provider_name: str

    def fetch_current(self) -> WeatherConditions: ...
