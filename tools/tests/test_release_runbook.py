"""Execute the documented shell workflow with local GitHub/Git stand-ins."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
PIN, PUBLISH = re.findall(r"```sh\n(.*?)```", (ROOT / "docs/releases.md").read_text(), re.S)
SHA = "a" * 40
RECORD = {"sha": SHA, "run_id": 1, "deployment_id": 10, "status_reported": True, "time": 1}

STAND_IN = r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
name = Path(sys.argv[0]).name
with open(os.environ['COMMAND_LOG'], 'a') as stream:
    stream.write(json.dumps([name, *args]) + '\n')
record = json.loads(os.environ['PINNED_RECORD'])
if name == 'git':
    sys.exit(0)
if args[:2] == ['run', 'view']:
    assert args[2] == str(record['run_id'])
    field = args[args.index('--json') + 1]
    print(record['sha'] if field == 'headSha' else 'success')
elif args[0] == 'api':
    endpoint = next(arg for arg in args if arg.startswith('repos/'))
    assert f"/deployments/{record['deployment_id']}" in endpoint
    if '/statuses' in endpoint:
        assert '--paginate' in args
        for page in json.loads(os.environ['STATUS_PAGES']):
            print(json.dumps(page))
    else:
        print(record['sha'])
elif args[0] != 'release':
    raise AssertionError(args)
'''


@pytest.fixture
def workflow(tmp_path):
    home = tmp_path / "home"
    state = home / ".local/state/housepanel-release/deployed.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps(RECORD))
    commands = tmp_path / "bin"
    commands.mkdir()
    for name in ("gh", "git"):
        executable = commands / name
        executable.write_text(f"#!{sys.executable}\n" + STAND_IN)
        executable.chmod(0o755)
    env = {**os.environ, "HOME": str(home), "PATH": f"{commands}:{os.environ['PATH']}",
           "COMMAND_LOG": str(tmp_path / "commands.jsonl"), "PINNED_RECORD": json.dumps(RECORD),
           "STATUS_PAGES": json.dumps([[{"state": "success"}]]), "VERSION": "v0.1.0"}

    def run(script):
        return subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env,
                              capture_output=True, text=True)

    def evidence(sha=SHA):
        directory = tmp_path / "build/releases/v0.1.0"
        (directory / "baseline.json").write_text(json.dumps({"expected_commit": sha}))
        (directory / "release-notes.md").write_text(f"Reviewed evidence for {sha}\n")

    def calls():
        log = Path(env["COMMAND_LOG"])
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    return run, evidence, calls, state, env


def test_later_deployment_cannot_retarget_prepared_release(workflow):
    run, evidence, calls, state, _ = workflow
    assert run(PIN).returncode == 0
    evidence()
    state.write_text(json.dumps({**RECORD, "sha": "b" * 40, "run_id": 2, "deployment_id": 20}))
    result = run(PUBLISH)
    assert result.returncode == 0, result.stderr
    tag = next(call for call in calls() if call[:3] == ["git", "tag", "-a"])
    assert tag[4] == SHA
    assert any(call[:3] == ["gh", "release", "create"] for call in calls())


@pytest.mark.parametrize("pages,allowed", [
    ([[{"state": "success"}]], True),
    ([[{"state": "inactive"}], [{"state": "success"}]], True),
    ([[{"state": "inactive"}]], False),
    ([[{"state": "failure"}, {"state": "success"}]], False),
    ([[{"state": "error"}, {"state": "success"}]], False),
    ([[{"state": "in_progress"}, {"state": "success"}]], False),
    ([[{"state": "pending"}]], False),
    ([[]], False),
])
def test_deployment_status_history_gate(workflow, pages, allowed):
    run, evidence, calls, _, env = workflow
    assert run(PIN).returncode == 0
    evidence()
    env["STATUS_PAGES"] = json.dumps(pages)
    result = run(PUBLISH)
    assert (result.returncode == 0) is allowed, result.stderr
    assert any(call[:3] == ["git", "tag", "-a"] for call in calls()) is allowed


def test_mismatched_baseline_cannot_publish(workflow):
    run, evidence, calls, _, _ = workflow
    assert run(PIN).returncode == 0
    evidence(sha="b" * 40)
    assert run(PUBLISH).returncode != 0
    assert not calls()


def test_existing_record_cannot_be_overwritten(workflow):
    run, _, _, state, _ = workflow
    assert run(PIN).returncode == 0
    state.write_text(json.dumps({**RECORD, "sha": "b" * 40}))
    assert run(PIN).returncode != 0
    # Inspect the pinned record through the same workflow path.
    result = run('jq -er .sha build/releases/v0.1.0/deployment.json')
    assert result.returncode == 0
    assert result.stdout.strip() == SHA


def test_unreported_deployment_cannot_be_pinned(workflow):
    run, _, _, state, _ = workflow
    state.write_text(json.dumps({**RECORD, "status_reported": False}))
    assert run(PIN).returncode != 0


def test_shell_examples_parse():
    for script in (PIN, PUBLISH):
        subprocess.run(["bash", "-n"], input=script, text=True, check=True)
