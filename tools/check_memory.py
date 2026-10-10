"""Fail a release when post-warmup memory or resource counts keep growing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def assess(samples: list[dict], warmup: int = 500) -> dict:
    samples = [s for s in samples if s.get("stage") not in
               ("closed", "after_malloc_trim", "before_gc")]
    samples = [s for s in samples if s.get("cycle", s.get("cycles", 0)) >= warmup]
    # The sysmon probe prints its shutdown sample at the same cycle number.
    unique = {}
    for sample in samples:
        unique.setdefault(sample.get("cycle", sample.get("cycles")), sample)
    samples = [unique[key] for key in sorted(unique)]
    if len(samples) < 4:
        raise ValueError("Need at least four post-warmup samples")
    first = samples[0]
    xs = [s.get("cycle", s.get("cycles")) for s in samples]
    ys = [s["rss_kib"] for s in samples]
    xmean, ymean = sum(xs) / len(xs), sum(ys) / len(ys)
    slope = sum((x-xmean)*(y-ymean) for x, y in zip(xs, ys)) / sum((x-xmean)**2 for x in xs)
    growth = max(ys) - ys[0]
    errors = []
    if growth > 4096:
        errors.append(f"RSS grew {growth / 1024:.2f} MiB (limit 4 MiB)")
    if slope * 1000 > 1024:
        errors.append(f"RSS slope {slope * 1000 / 1024:.2f} MiB/1000 polls (limit 1)")
    for key, allowance in (("fds", 2), ("tasks", 1), ("threads", 1)):
        if any(s[key] > first[key] + allowance for s in samples):
            errors.append(f"Growing {key}")
    if errors:
        raise ValueError("; ".join(errors))
    return {"growth_mib": round(growth / 1024, 3),
            "mib_per_1000_polls": round(slope * 1000 / 1024, 3), "samples": len(samples)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    samples = []
    for line in args.log.read_text().splitlines():
        if line.startswith("{"):
            sample = json.loads(line)
            if "rss_kib" in sample:
                samples.append(sample)
    print(json.dumps(assess(samples)))


if __name__ == "__main__":
    main()
