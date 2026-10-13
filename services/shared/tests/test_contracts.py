import pytest

from shared.contracts import validate_payload, MAX_PAYLOAD_BYTES


def test_calendar_has_typed_bounded_events():
    payload = validate_payload("calendar-update", {"events": [{"summary": "Appointment", "all_day": False}]})
    assert payload["events"][0]["summary"] == "Appointment"


@pytest.mark.parametrize("payload", [
    {"events": [42]}, {"events": [{"summary": 42}]},
    {"events": [{}] * 501}, {"events": [{"all_day": "false"}]},
    {"events": [{"summary": "x" * 1025}]},
])
def test_invalid_calendar_contract_is_rejected(payload):
    with pytest.raises(ValueError):
        validate_payload("calendar-update", payload)


@pytest.mark.parametrize("event,payload", [
    ("weather-update", {"temperature_c": float("nan")}),
    ("weather-update", {"forecast": [{}] * 5}),
    ("weather-update", {"conditions": []}),
    ("sysmon-update", {"temp_c": "not-a-number"}),
    ("ticker", {"narrative": "x" * MAX_PAYLOAD_BYTES}),
])
def test_invalid_or_oversized_payload_is_rejected(event, payload):
    with pytest.raises(ValueError):
        validate_payload(event, payload)


def test_generic_ticker_payload_within_byte_limit_is_preserved():
    payload = {"narrative": "A person arrived"}
    assert validate_payload("ticker", payload) is payload
