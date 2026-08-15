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
