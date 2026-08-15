#!/usr/bin/env python3
"""Mutation tester — find tests that pass against deliberately broken code.

A test suite going green proves the tests ran, not that they check anything.
This breaks one line of source at a time and re-runs that service's suite. If
the suite still passes, nothing was asserting that behaviour: a false negative.

    python tools/mutate.py                    # every service, 20 mutants each
    python tools/mutate.py weather-poller     # one service
    python tools/mutate.py aggregator --cap 40

Surviving mutants are printed with file, line and the change that went
unnoticed. Not every survivor is a real gap — some are *equivalent mutants*
that cannot change behaviour (see the `field(compare=False)` entries in
aggregator's dispatch_worker, where `seq` is unique so tuple comparison never
reaches the later fields). Read each one before writing a test for it.

Safety: this edits files in place and restores them. It refuses to start if the
target sources have uncommitted changes, so an interrupted run is always
recoverable with `git checkout -- services/<svc>/src`. Sources are verified
byte-identical on exit.
"""
from __future__ import annotations

import argparse
import io
import os
import pathlib
import re
import signal
import subprocess
import sys
import tokenize

REPO = pathlib.Path(__file__).resolve().parent.parent
SERVICES = REPO / "services"

# (pattern, replacement, label) — applied to a single line at a time.
MUTATIONS = [
    (r" == ",       " != ",     "== -> !="),
    (r" != ",       " == ",     "!= -> =="),
    (r" >= ",       " > ",      ">= -> >"),
    (r" <= ",       " < ",      "<= -> <"),
    (r"([^<>=!])> ", r"\1>= ",  "> -> >="),
    (r"([^<>=!])< ", r"\1<= ",  "< -> <="),
    (r"\bTrue\b",   "False",    "True -> False"),
    (r"\bFalse\b",  "True",     "False -> True"),
    (r" and ",      " or ",     "and -> or"),
    (r" or ",       " and ",    "or -> and"),
    (r"\bnot in\b", "in",       "not in -> in"),
    (r"\bis not\b", "is",       "is not -> is"),
]

# Definitions and imports are structure, not behaviour worth mutating.
SKIP_LINE = re.compile(
    r"^\s*(#|from |import |@|def |class |async def )|__name__|noqa"
)


def discover_services() -> list[str]:
    return sorted(
        p.name for p in SERVICES.iterdir()
        if (p / "tests").is_dir() and any((p / "tests").glob("test_*.py"))
    )


def source_files(service: str) -> list[pathlib.Path]:
    """Service sources, excluding tests. `shared` has no src/ layer."""
    root = SERVICES / service / "src"
    if not root.is_dir():
        root = SERVICES / service / service.replace("-", "_")
    return sorted(p for p in root.rglob("*.py") if "test" not in p.name)


def scan(src: str) -> tuple[set[int], dict[int, list[tuple[int, int]]]]:
    """Return (lines carrying code, per-line column spans to leave alone).

    Without this the tester mutates prose — docstring text, and the `or` in a
    trailing `# "gauge" or "counter"` — and reports survivors that mean
    nothing. String literals are masked too, so a mutation cannot rewrite the
    contents of a message the code emits.
    """
    live: set[int] = set()
    masked: dict[int, list[tuple[int, int]]] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            row = tok.start[0] - 1
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                if tok.start[0] == tok.end[0]:      # multi-line bodies yield no code lines
                    masked.setdefault(row, []).append((tok.start[1], tok.end[1]))
                continue
            if tok.type in (tokenize.NL, tokenize.NEWLINE,
                            tokenize.INDENT, tokenize.DEDENT):
                continue
            live.add(row)
    except tokenize.TokenError:
        pass
    return live, masked


def candidates(path: pathlib.Path):
    src = path.read_text()
    live, masked = scan(src)
    for i, line in enumerate(src.splitlines(keepends=True)):
        if i not in live or not line.strip() or SKIP_LINE.search(line):
            continue
        spans = masked.get(i, [])
        for pat, rep, label in MUTATIONS:
            for match in re.finditer(pat, line):
                if any(s <= match.start() < e for s, e in spans):
                    continue                        # inside a comment or string
                mutated = line[:match.start()] + match.expand(rep) + line[match.end():]
                if mutated != line:
                    yield path, i, mutated, label, line.strip()
                break


def run_tests(service: str) -> bool:
    """True if the suite passes.

    PYTHONDONTWRITEBYTECODE is not optional. Without it a mutant's .pyc can
    outlive the source restore and silently poison later runs — including runs
    after this tool exits, which looks like a spontaneously failing test file.
    """
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", str(SERVICES / service / "tests"),
         "-x", "-q", "--asyncio-mode=auto", "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=REPO, env=env,
    )
    return proc.returncode == 0


def dirty(paths: list[pathlib.Path]) -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", *[str(p) for p in paths]],
        capture_output=True, text=True, cwd=REPO,
    )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def mutate_service(service: str, cap: int) -> int:
    """Run the campaign for one service. Returns the number of survivors."""
    files = source_files(service)
    if not files:
        print(f"{service}: no sources found"); return 0

    changed = dirty(files)
    if changed:
        print(f"{service}: SKIPPED — uncommitted changes in sources:")
        for line in changed:
            print(f"    {line}")
        print("    commit or stash them so an interrupted run stays recoverable")
        return 0

    if not run_tests(service):
        print(f"{service}: SKIPPED — baseline suite already fails")
        return 0

    pool = [c for f in files for c in candidates(f)]
    if not pool:
        print(f"{service}: no mutable lines")
        return 0
    step = max(1, len(pool) // cap)
    picked = pool[::step][:cap]

    survivors, killed = [], 0
    for path, lineno, mutated, label, original in picked:
        backup = path.read_text()
        lines = backup.splitlines(keepends=True)
        lines[lineno] = mutated
        candidate = "".join(lines)
        try:
            compile(candidate, str(path), "exec")
        except SyntaxError:
            continue

        restore = lambda *_: (path.write_text(backup), sys.exit(1))
        previous = signal.signal(signal.SIGINT, restore)
        path.write_text(candidate)
        try:
            if run_tests(service):
                survivors.append((path, lineno + 1, label, original))
            else:
                killed += 1
        finally:
            path.write_text(backup)
            signal.signal(signal.SIGINT, previous)

    total = killed + len(survivors)
    score = (killed / total * 100) if total else 0.0
    print(f"\n=== {service}: {killed}/{total} mutants killed ({score:.0f}%)")
    for path, line, label, original in survivors:
        print(f"  SURVIVED {path.relative_to(REPO)}:{line}  [{label}]")
        print(f"           {original[:100]}")

    if leftover := dirty(files):
        print(f"  WARNING: {service} sources not restored cleanly:")
        for line in leftover:
            print(f"    {line}")
    return len(survivors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("services", nargs="*", help="default: every service with tests")
    parser.add_argument("--cap", type=int, default=20,
                        help="mutants sampled per service (default 20)")
    args = parser.parse_args()

    targets = args.services or discover_services()
    unknown = [s for s in targets if not (SERVICES / s / "tests").is_dir()]
    if unknown:
        parser.error(f"no test suite for: {', '.join(unknown)}")

    total = sum(mutate_service(s, args.cap) for s in targets)
    print(f"\n{total} surviving mutant(s) across {len(targets)} service(s).")
    print("Review each before writing tests — some are equivalent mutants.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
