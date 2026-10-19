"""Export native Prometheus rules for promtool's per-panel alert tests."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def export_rules() -> None:
    source = yaml.safe_load((ROOT / "k8s/prometheusrule.yaml").read_text())
    target = ROOT / "build/panel-alerts.rules.yml"
    target.parent.mkdir(exist_ok=True)
    target.write_text(yaml.safe_dump(source["spec"]))


if __name__ == "__main__":
    export_rules()
