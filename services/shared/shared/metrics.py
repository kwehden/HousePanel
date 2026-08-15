"""Minimal Prometheus text-format rendering.

Deliberately dependency-free: the services expose a handful of gauges and
counters, which does not justify pulling prometheus_client into every image.
Output follows the 0.0.4 text exposition format.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# Wall-clock, so Prometheus can compare the timestamps against time().
_now = time.time

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


class SourceMetrics:
    """Poll and push outcomes for a service that feeds the aggregator.

    Two timestamps, deliberately: a source can fetch upstream data perfectly
    while failing to hand it to the aggregator, and the display only reflects
    what was pushed. Alerting on the poll timestamp alone would report health
    while the panel goes stale.

    Passing poll_interval_seconds opts the service into staleness alerting and
    tells the alert rule what "late" means for it. Event-driven sources leave
    it None: silence from a doorbell is normal, not a fault.
    """

    def __init__(self, service: str, poll_interval_seconds: float | None = None) -> None:
        self.service = service
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_success_total = 0
        self.poll_failure_total = 0
        self.push_success_total = 0
        self.push_failure_total = 0
        self.last_poll_success_wall: float | None = None
        self.last_push_success_wall: float | None = None

    def record_poll(self, ok: bool) -> None:
        if ok:
            self.poll_success_total += 1
            self.last_poll_success_wall = _now()
        else:
            self.poll_failure_total += 1

    def record_push(self, ok: bool) -> None:
        if ok:
            self.push_success_total += 1
            self.last_push_success_wall = _now()
        else:
            self.push_failure_total += 1

    def render(self) -> list[Metric]:
        svc = {"service": self.service}
        out = [
            Metric("housepanel_source_poll_total",
                   "Upstream fetches by outcome.", "counter",
                   self.poll_success_total, {**svc, "outcome": "success"}),
            Metric("housepanel_source_poll_total",
                   "Upstream fetches by outcome.", "counter",
                   self.poll_failure_total, {**svc, "outcome": "failure"}),
            Metric("housepanel_source_push_total",
                   "Pushes to the aggregator by outcome.", "counter",
                   self.push_success_total, {**svc, "outcome": "success"}),
            Metric("housepanel_source_push_total",
                   "Pushes to the aggregator by outcome.", "counter",
                   self.push_failure_total, {**svc, "outcome": "failure"}),
        ]
        # Timestamps stay absent until the first success: a zero would read as
        # 1970 and fire every staleness alert on a cold start.
        if self.last_poll_success_wall is not None:
            out.append(Metric(
                "housepanel_source_last_poll_success_timestamp_seconds",
                "Unix time of the last successful upstream fetch.", "gauge",
                self.last_poll_success_wall, svc))
        if self.last_push_success_wall is not None:
            out.append(Metric(
                "housepanel_source_last_push_success_timestamp_seconds",
                "Unix time of the last push accepted by the aggregator.", "gauge",
                self.last_push_success_wall, svc))
        if self.poll_interval_seconds is not None:
            out.append(Metric(
                "housepanel_source_poll_interval_seconds",
                "Configured poll interval; presence opts into staleness alerting.",
                "gauge", self.poll_interval_seconds, svc))
        return out
