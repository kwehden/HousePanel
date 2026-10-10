import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from check_memory import assess
import release_agent as agent


def samples(slope=0, **growth):
    return [{"cycle": cycle, "rss_kib": 50000 + slope * (cycle - 500),
             "fds": 10 + growth.get("fds", 0) * (cycle // 500 - 1),
             "threads": 2, "tasks": 2} for cycle in range(500, 3001, 500)]


def test_flat_memory_passes():
    assert assess(samples())["growth_mib"] == 0


def test_reproduced_sysmon_sized_leak_fails():
    with pytest.raises(ValueError, match="RSS"):
        assess(samples(slope=10))


def test_slow_continuing_growth_fails_slope_gate():
    with pytest.raises(ValueError, match="slope"):
        assess(samples(slope=1.1))


def test_socket_leak_fails_even_with_flat_rss():
    with pytest.raises(ValueError, match="fds"):
        assess(samples(fds=1))


def test_short_probe_cannot_pass():
    with pytest.raises(ValueError, match="four"):
        assess(samples()[:2])


def run_record(**overrides):
    record = {"head_sha": "a" * 40, "head_branch": "main", "event": "push",
              "status": "completed", "conclusion": "success",
              "repository": {"full_name": agent.REPO}}
    record.update(overrides)
    return record


@pytest.mark.parametrize("override", [
    {"event": "pull_request"}, {"event": "schedule"}, {"conclusion": "failure"},
    {"head_sha": "b" * 40}, {"head_branch": "feature"}, {"status": "in_progress"},
    {"repository": {"full_name": "someone/fork"}},
])
def test_untrusted_or_stale_run_cannot_deploy(override):
    assert agent.select_run("a" * 40, [run_record(**override)]) is None


def test_current_successful_main_run_is_selected():
    run = run_record()
    assert agent.select_run("a" * 40, [run]) is run


def artifact_set(directory):
    for service in agent.SERVICES:
        archive = directory / f"{service}.tar.gz"
        archive.write_bytes(b"synthetic archive")
        (directory / f"{service}.json").write_text(json.dumps({
            "sha": "a" * 40, "service": service, "archive": archive.name,
            "image_id": "sha256:" + "b" * 64,
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        }))


def test_archive_integrity_is_checked(tmp_path):
    artifact_set(tmp_path)
    assert len(agent.verify_artifacts(tmp_path, "a" * 40)) == 6
    (tmp_path / "calendar-poller.tar.gz").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        agent.verify_artifacts(tmp_path, "a" * 40)


def test_artifact_cannot_choose_an_arbitrary_path(tmp_path):
    artifact_set(tmp_path)
    path = tmp_path / "calendar-poller.json"
    record = json.loads(path.read_text())
    record["archive"] = "../../private-file"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="metadata"):
        agent.verify_artifacts(tmp_path, "a" * 40)


@pytest.mark.parametrize("error", [subprocess.CalledProcessError(1, "rollout"), KeyboardInterrupt()])
def test_rollout_failure_restores_all_changed_images(tmp_path, error):
    records = {s: {"archive": f"{s}.tar.gz", "image_id": "sha256:" + "b" * 64} for s in agent.SERVICES}
    changes = []
    failed = False

    def command(*args, **kwargs):
        nonlocal failed
        if args[0] == "docker":
            if "inspect" in args:
                if args[-1] == "{{.Id}}":
                    return "sha256:" + "b" * 64
                if "Labels" in args[-1]:
                    return "a" * 40
                target = args[3]
                return json.dumps([target.rsplit(":", 1)[0] + "@sha256:" + "c" * 64])
            return ""
        if "get" in args:
            name = args[args.index("get") + 2]
            if name.endswith("ring-integration"):
                return json.dumps({"spec": {"replicas": 0}})
            service = name.removeprefix("housepanel-")
            return json.dumps({"spec": {"template": {"spec": {"containers": [
                {"name": service, "image": "previous/" + service}]}}, "clusterIP": "127.0.0.1"}})
        if "set" in args:
            changes.append(args[-1])
        if "rollout" in args and "deployment/housepanel-calendar-poller" in args and not failed:
            failed = True
            raise error
        return ""

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"giga_connected": true}'

    with patch.object(agent, "command", side_effect=command), patch.object(agent, "urlopen", return_value=Response()):
        with pytest.raises(type(error)):
            agent.deploy(records, tmp_path, "a" * 40, "test", "registry:30500")
    assert changes[-2:] == ["calendar-poller=previous/calendar-poller", "aggregator=previous/aggregator"]
