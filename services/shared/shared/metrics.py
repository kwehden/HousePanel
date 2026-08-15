"""Minimal Prometheus text-format rendering.

Deliberately dependency-free: the services expose a handful of gauges and
counters, which does not justify pulling prometheus_client into every image.
Output follows the 0.0.4 text exposition format.
"""
from __future__ import annotations
from dataclasses import dataclass, field

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

_ESCAPES = str.maketrans({"\\": r"\\", "\n": r"\n", '"': r"\""})


@dataclass(frozen=True)
class Metric:
    name: str
    help: str
    type: str  # "gauge" or "counter"
    value: float
    labels: dict[str, str] = field(default_factory=dict)


def _render_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    pairs = ",".join(f'{k}="{str(v).translate(_ESCAPES)}"' for k, v in sorted(labels.items()))
    return "{" + pairs + "}"


def _render_value(value: float) -> str:
    if value != value:  # NaN
        return "NaN"
    if value == float("inf"):
        return "+Inf"
    if value == float("-inf"):
        return "-Inf"
    if isinstance(value, bool):
        return "1" if value else "0"
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def render(metrics: list[Metric]) -> str:
    """Render metrics, emitting one HELP/TYPE header per metric family."""
    out: list[str] = []
    seen: set[str] = set()
    for metric in metrics:
        if metric.name not in seen:
            seen.add(metric.name)
            out.append(f"# HELP {metric.name} {metric.help}")
            out.append(f"# TYPE {metric.name} {metric.type}")
        out.append(f"{metric.name}{_render_labels(metric.labels)} {_render_value(metric.value)}")
    return "\n".join(out) + "\n"
