from __future__ import annotations
from shared.metrics import CONTENT_TYPE, Metric, render


def test_render_single_gauge():
    out = render([Metric("thing_total", "A thing.", "gauge", 3)])
    assert out == "# HELP thing_total A thing.\n# TYPE thing_total gauge\nthing_total 3\n"


def test_help_and_type_emitted_once_per_family():
    out = render([
        Metric("q_depth", "Depth.", "gauge", 1, {"queue": "a"}),
        Metric("q_depth", "Depth.", "gauge", 2, {"queue": "b"}),
    ])
    assert out.count("# HELP q_depth") == 1
    assert out.count("# TYPE q_depth") == 1
    assert 'q_depth{queue="a"} 1' in out
    assert 'q_depth{queue="b"} 2' in out


def test_labels_are_sorted_and_escaped():
    out = render([Metric("m", "M.", "gauge", 1, {"b": "2", "a": 'x"y'})])
    assert 'm{a="x\\"y",b="2"} 1' in out


def test_integral_floats_render_without_exponent():
    """Unix timestamps must not be rendered in scientific notation."""
    out = render([Metric("ts", "T.", "gauge", 1755273600.0)])
    assert "ts 1755273600\n" in out
    assert "e+" not in out


def test_fractional_value_preserved():
    out = render([Metric("ratio", "R.", "gauge", 0.5)])
    assert "ratio 0.5\n" in out


def test_content_type_is_the_prometheus_text_format():
    assert CONTENT_TYPE.startswith("text/plain")
    assert "version=0.0.4" in CONTENT_TYPE


# ---------------------------------------------------------------------------
# SourceMetrics
# ---------------------------------------------------------------------------

from shared.metrics import SourceMetrics  # noqa: E402


def _families(m: SourceMetrics) -> dict[str, list]:
    out: dict[str, list] = {}
    for metric in m.render():
        out.setdefault(metric.name, []).append(metric)
    return out


def test_counters_start_at_zero_and_are_always_present():
    """Counters must exist from the start so rate() has a baseline."""
    fam = _families(SourceMetrics("weather", poll_interval_seconds=900))
    values = {
        (m.labels["outcome"]): m.value
        for m in fam["housepanel_source_poll_total"]
    }
    assert values == {"success": 0, "failure": 0}


def test_timestamps_absent_until_first_success():
    """A zero timestamp would read as 1970 and fire staleness on cold start."""
    m = SourceMetrics("weather", poll_interval_seconds=900)
    assert "housepanel_source_last_poll_success_timestamp_seconds" not in _families(m)
    assert "housepanel_source_last_push_success_timestamp_seconds" not in _families(m)

    m.record_poll(True)
    assert "housepanel_source_last_poll_success_timestamp_seconds" in _families(m)
    # Push has still never succeeded — must stay absent.
    assert "housepanel_source_last_push_success_timestamp_seconds" not in _families(m)

    m.record_push(True)
    assert "housepanel_source_last_push_success_timestamp_seconds" in _families(m)


def test_failure_does_not_advance_the_timestamp():
    m = SourceMetrics("weather", poll_interval_seconds=900)
    m.record_poll(True)
    first = m.last_poll_success_wall
    m.record_poll(False)
    assert m.last_poll_success_wall == first
    assert m.poll_failure_total == 1


def test_poll_and_push_are_tracked_separately():
    """A source can fetch fine while failing to reach the aggregator."""
    m = SourceMetrics("weather", poll_interval_seconds=900)
    m.record_poll(True)
    m.record_push(False)

    fam = _families(m)
    assert "housepanel_source_last_poll_success_timestamp_seconds" in fam
    assert "housepanel_source_last_push_success_timestamp_seconds" not in fam
    push = {m.labels["outcome"]: m.value for m in fam["housepanel_source_push_total"]}
    assert push == {"success": 0, "failure": 1}


def test_interval_declared_opts_into_staleness_alerting():
    fam = _families(SourceMetrics("weather", poll_interval_seconds=900))
    assert fam["housepanel_source_poll_interval_seconds"][0].value == 900


def test_event_driven_source_declares_no_interval():
    """Silence from a doorbell is normal; no interval means no staleness rule."""
    fam = _families(SourceMetrics("ring"))
    assert "housepanel_source_poll_interval_seconds" not in fam


def test_service_label_on_every_metric():
    for metric in SourceMetrics("calendar", poll_interval_seconds=300).render():
        assert metric.labels.get("service") == "calendar"
