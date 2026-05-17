"""Confirm that GoogleWeatherAdapter and OpenWeatherMapAdapter satisfy WeatherAdapter protocol."""
from weather_poller.adapter import WeatherAdapter
from weather_poller.adapters.google import GoogleWeatherAdapter
from weather_poller.adapters.openweathermap import OpenWeatherMapAdapter


def test_google_adapter_satisfies_protocol() -> None:
    adapter = GoogleWeatherAdapter(api_key="test-key", location="37.7749,-122.4194")
    assert isinstance(adapter, WeatherAdapter)


def test_owm_adapter_satisfies_protocol() -> None:
    adapter = OpenWeatherMapAdapter(api_key="test-key", location="San Francisco")
    assert isinstance(adapter, WeatherAdapter)


def test_google_adapter_has_provider_name() -> None:
    adapter = GoogleWeatherAdapter(api_key="key", location="0.0,0.0")
    assert adapter.provider_name == "google-weather"


def test_owm_adapter_has_provider_name() -> None:
    adapter = OpenWeatherMapAdapter(api_key="key", location="London")
    assert adapter.provider_name == "openweathermap"
