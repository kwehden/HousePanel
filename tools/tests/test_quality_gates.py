import hashlib
import io
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from unittest.mock import patch
from urllib.parse import urlparse

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


def test_calendar_gate_does_not_hide_first_500_polls():
    early_growth = [{"cycle": cycle, "rss_kib": 50000 + (6000 if cycle >= 250 else 0),
                     "fds": 10, "tasks": 2, "threads": 2}
                    for cycle in [12, 250, 500, 750, 1000, 1250, 1500]]
    assert assess(early_growth)["growth_mib"] == 0
    with pytest.raises(ValueError, match="RSS"):
        assess(early_growth, warmup=12)


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
            "config_digest": "sha256:" + "b" * 64,
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


def test_success_status_failure_does_not_redeploy_verified_release(tmp_path):
    run = run_record(id=123, html_url="https://github.com/kwehden/HousePanel/actions/runs/123")
    status_attempts = 0

    def api(path):
        if path == "commits/main":
            return {"sha": "a" * 40}
        if "/runs?" in path:
            return {"workflow_runs": [run]}
        if path.endswith("/artifacts"):
            return {"artifacts": [{"name": "housepanel-release", "expired": False}]}
        return {"jobs": [{"name": name, "conclusion": "success"} for name in
            {"Quality Gate", "quality", "release"} | {f"image / {s}" for s in agent.SERVICES}]}

    def command(*args, **kwargs):
        nonlocal status_attempts
        if args[:3] == ("gh", "run", "download"):
            artifact_set(Path(args[-1]))
            return ""
        if args[4].endswith("/deployments"):
            return '{"id": 99}'
        state = json.loads(kwargs["input"])["state"]
        if state == "success":
            status_attempts += 1
            if status_attempts == 1:
                raise subprocess.CalledProcessError(1, args)
        return "{}"

    with patch.object(agent, "api", side_effect=api), \
         patch.object(agent, "command", side_effect=command), \
         patch.object(agent, "deploy") as deploy, \
         patch.object(agent.signal, "signal"), \
         patch.object(sys, "argv", ["release_agent.py", "--state-dir", str(tmp_path)]):
        with pytest.raises(subprocess.CalledProcessError):
            agent.main()
        marker = tmp_path / "deployed.json"
        assert json.loads(marker.read_text())["status_reported"] is False
        assert not (tmp_path / "failed.json").exists()
        agent.main()
        deploy.assert_called_once()
        assert json.loads(marker.read_text())["status_reported"] is True


def test_successful_release_refreshes_supported_routes_and_verifies_delivery(tmp_path):
    records = {s: {"archive": f"{s}.tar.gz", "config_digest": "sha256:" + "b" * 64} for s in agent.SERVICES}
    refreshed = []

    def command(*args, **kwargs):
        if args[0] == "docker":
            if "inspect" in args:
                if args[-1] == "{{.Id}}":
                    return "sha256:" + "b" * 64
                if "Labels" in args[-1]:
                    return "a" * 40
                return json.dumps([args[3].rsplit(":", 1)[0] + "@sha256:" + "c" * 64])
            return ""
        if "get" in args:
            kind = args[args.index("get") + 1]
            name = args[args.index("get") + 2]
            if kind == "pods":
                return json.dumps({"items": [{"metadata": {}, "status": {"containerStatuses": [{"restartCount": 0}]}}]})
            if name.endswith("ring-integration"):
                return json.dumps({"spec": {"replicas": 0}})
            service = name.removeprefix("housepanel-")
            return json.dumps({"spec": {"template": {"spec": {"containers": [
                {"name": service, "image": "previous/" + service}]}}, "clusterIP": "127.0.0.1"}})
        return ""

    def response(request, **kwargs):
        url = urlparse(request if isinstance(request, str) else request.full_url)
        if url.path == "/internal/poll-now":
            # Fixture matches the packaged calendar/weather API contracts.
            assert url.port in (8003, 8004)
            refreshed.append(url.port)
            return io.BytesIO(b'{"accepted": true}')
        if url.path == "/metrics":
            return io.BytesIO(f'housepanel_source_last_push_success_timestamp_seconds{{service="test"}} {time.time()+1}\n'.encode())
        return io.BytesIO(b'{"status":"ok","giga_connected":true,"normal_queue_depth":0}')

    with patch.object(agent, "command", side_effect=command), patch.object(agent, "urlopen", side_effect=response), \
         patch.object(agent, "verify_loaded_image"):
        agent.deploy(records, tmp_path, "a" * 40, "test", "registry:30500")
    assert refreshed == [8003, 8004]


@pytest.mark.parametrize("error", [subprocess.CalledProcessError(1, "rollout"), KeyboardInterrupt()])
def test_rollout_failure_restores_all_changed_images(tmp_path, error):
    records = {s: {"archive": f"{s}.tar.gz", "config_digest": "sha256:" + "b" * 64} for s in agent.SERVICES}
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

    with patch.object(agent, "command", side_effect=command), patch.object(agent, "urlopen", return_value=Response()), \
         patch.object(agent, "verify_loaded_image"):
        with pytest.raises(type(error)):
            agent.deploy(records, tmp_path, "a" * 40, "test", "registry:30500")
    assert changes[-2:] == ["calendar-poller=previous/calendar-poller", "aggregator=previous/aggregator"]


def image_fixture(tmp_path):
    image = "housepanel/test:" + "a" * 40
    config = {"architecture": "amd64", "os": "linux",
              "rootfs": {"type": "layers", "diff_ids": ["sha256:" + "c" * 64]},
              "config": {"Cmd": ["python", "app.py"], "Labels": {"org.opencontainers.image.revision": "a" * 40}}}
    payload = json.dumps(config).encode()
    digest = "sha256:" + hashlib.sha256(payload).hexdigest()
    archive = tmp_path / "test.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name, data in [("manifest.json", json.dumps([{"Config": "config.json", "RepoTags": [image]}]).encode()),
                           ("config.json", payload)]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            bundle.addfile(member, io.BytesIO(data))
    actual = {"Id": "sha256:" + "d" * 64, "Architecture": "amd64", "Os": "linux",
              "RootFS": {"Type": "layers", "Layers": config["rootfs"]["diff_ids"]},
              "Config": {**config["config"], "Entrypoint": None, "User": "", "AttachStdin": False}}
    return image, archive, digest, actual


def test_content_identity_survives_docker_backend_id_changes(tmp_path):
    image, archive, digest, actual = image_fixture(tmp_path)
    with patch.object(agent, "command", return_value=json.dumps(actual)):
        agent.verify_loaded_image(image, archive, digest, "a" * 40)


@pytest.mark.parametrize("field", ["layer", "command", "platform", "extra_setting"])
def test_loaded_content_mismatch_is_rejected(tmp_path, field):
    image, archive, digest, actual = image_fixture(tmp_path)
    if field == "layer":
        actual["RootFS"]["Layers"] = ["sha256:" + "e" * 64]
    elif field == "command":
        actual["Config"]["Cmd"] = ["other.py"]
    elif field == "platform":
        actual["Architecture"] = "arm64"
    else:
        actual["Config"]["User"] = "unrelated-user"
    with patch.object(agent, "command", return_value=json.dumps(actual)), pytest.raises(RuntimeError, match="content"):
        agent.verify_loaded_image(image, archive, digest, "a" * 40)


def test_incorrect_config_digest_is_rejected(tmp_path):
    image, archive, digest, actual = image_fixture(tmp_path)
    with pytest.raises(ValueError, match="digest"):
        agent.verify_loaded_image(image, archive, "sha256:" + "f" * 64, "a" * 40)
