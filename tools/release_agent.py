"""Deploy verified CI image artifacts for the current main commit, with rollback.

Run by a local systemd timer. GitHub jobs never receive cluster credentials.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen

REPO = "kwehden/HousePanel"
SERVICES = ("aggregator", "calendar-poller", "sysmon-poller", "transport-adapter",
            "weather-poller", "webhook-receiver")
PORTS = dict(zip(SERVICES, (8001, 8003, 8005, 8002, 8004, 8000)))


def command(*args: str, **kwargs) -> str:
    result = subprocess.run(args, check=True, capture_output=True, text=True, timeout=600, **kwargs)
    return result.stdout.strip()


def api(path: str):
    return json.loads(command("gh", "api", f"repos/{REPO}/{path}"))


def write_state(path: Path, record: dict) -> None:
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(record))
    os.replace(pending, path)


def select_run(head: str, runs: list[dict]) -> dict | None:
    for run in runs:
        if (run["head_sha"] == head and run["head_branch"] == "main" and
                run["event"] == "push" and run["status"] == "completed" and
                run["conclusion"] == "success" and run["repository"]["full_name"] == REPO):
            return run
    return None


def verify_artifacts(directory: Path, sha: str) -> dict[str, dict]:
    records = {}
    for service in SERVICES:
        record = json.loads((directory / f"{service}.json").read_text())
        if (record["sha"] != sha or record["service"] != service or
                record["archive"] != f"{service}.tar.gz" or
                not re.fullmatch(r"sha256:[0-9a-f]{64}", record["image_id"])):
            raise ValueError(f"Invalid release metadata for {service}")
        with (directory / record["archive"]).open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"Archive hash mismatch for {service}")
        records[service] = record
    return records


def deploy(records: dict, directory: Path, sha: str, context: str, registry: str) -> None:
    def kubectl(*args: str, **kwargs):
        return command("kubectl", "--context", context, "-n", "housepanel", *args, **kwargs)

    def resource(kind: str, name: str):
        return json.loads(kubectl("get", kind, f"housepanel-{name}", "-o", "json"))

    def health(service: str, path: str):
        ip = resource("service", service)["spec"]["clusterIP"]
        with urlopen(f"http://{ip}:{PORTS[service]}{path}", timeout=5) as response:
            return json.load(response)

    previous = {}
    for service in SERVICES:
        containers = resource("deployment", service)["spec"]["template"]["spec"]["containers"]
        previous[service] = next(c["image"] for c in containers if c["name"] == service)
    # Require a healthy baseline so a pre-existing outage is not blamed on a release.
    if not health("transport-adapter", "/internal/health")["giga_connected"]:
        raise RuntimeError("Panel is disconnected before release")
    if resource("deployment", "ring-integration")["spec"]["replicas"] != 0:
        raise RuntimeError("Retired Ring service is enabled")
    targets = {}
    for service, record in records.items():
        command("docker", "load", "--input", str(directory / record["archive"]))
        image = f"housepanel/{service}:{sha}"
        actual = command("docker", "image", "inspect", image, "--format", "{{.Id}}")
        if actual != record["image_id"]:
            raise RuntimeError(f"Loaded image mismatch for {service}")
        revision = command("docker", "image", "inspect", image, "--format",
                           '{{index .Config.Labels "org.opencontainers.image.revision"}}')
        if revision != sha:
            raise RuntimeError(f"Image revision mismatch for {service}")
        target = f"{registry}/housepanel/{service}:{sha}"
        command("docker", "tag", image, target)
        command("docker", "push", target)
        digests = json.loads(command("docker", "image", "inspect", target, "--format", "{{json .RepoDigests}}"))
        prefix = f"{registry}/housepanel/{service}@sha256:"
        targets[service] = next(d for d in digests if d.startswith(prefix))

    started = time.time()
    changed = []
    try:
        for service in SERVICES:
            changed.append(service)
            kubectl("set", "image", f"deployment/housepanel-{service}", f"{service}={targets[service]}")
            kubectl("rollout", "status", f"deployment/housepanel-{service}", "--timeout=180s")
        for service in ("calendar-poller", "weather-poller"):
            ip = resource("service", service)["spec"]["clusterIP"]
            with urlopen(Request(f"http://{ip}:{PORTS[service]}/internal/poll-now", data=b"", method="POST"), timeout=5):
                pass
        deadline = time.monotonic() + 300
        last_error = ""
        while time.monotonic() < deadline:
            try:
                for service in SERVICES:
                    if health(service, "/healthz")["status"] != "ok":
                        raise RuntimeError(f"Unhealthy {service}")
                    pod_list = json.loads(kubectl("get", "pods", "-l", f"app=housepanel-{service}", "-o", "json"))
                    current = [p for p in pod_list["items"] if not p["metadata"].get("deletionTimestamp")]
                    if not current or any(c["restartCount"] for p in current for c in p["status"].get("containerStatuses", [])):
                        raise RuntimeError(f"Restarted {service}")
                panel = health("transport-adapter", "/internal/health")
                if not panel["giga_connected"] or panel["normal_queue_depth"] > 20:
                    raise RuntimeError("Panel disconnected or delivery queue backed up")
                for service in ("calendar-poller", "sysmon-poller", "weather-poller"):
                    ip = resource("service", service)["spec"]["clusterIP"]
                    with urlopen(f"http://{ip}:{PORTS[service]}/metrics", timeout=5) as response:
                        metrics = response.read().decode()
                    timestamps = [float(line.split()[-1]) for line in metrics.splitlines()
                                  if line.startswith("housepanel_source_last_push_success_timestamp_seconds{")]
                    if not timestamps or timestamps[0] < started:
                        raise RuntimeError(f"No successful post-release delivery from {service}")
                break
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                last_error = str(exc)
                time.sleep(5)
        else:
            raise RuntimeError(f"Release verification timed out: {last_error}")
    except BaseException:
        failures = []
        for service in reversed(changed):
            try:
                kubectl("set", "image", f"deployment/housepanel-{service}", f"{service}={previous[service]}")
                kubectl("rollout", "status", f"deployment/housepanel-{service}", "--timeout=180s")
            except subprocess.SubprocessError:
                failures.append(service)
        if failures:
            raise RuntimeError(f"Rollback failed for: {failures}")
        raise
    print(json.dumps({"deployed": sha, "images": targets}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".local/state/housepanel-release")
    parser.add_argument("--context", default="localk8s-cfd")
    parser.add_argument("--registry", default="laminarflow:30500")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    def terminated(signum, frame):
        raise RuntimeError("Release interrupted by SIGTERM")

    signal.signal(signal.SIGTERM, terminated)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    with (args.state_dir / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        head = api("commits/main")["sha"]
        runs = api("actions/workflows/ci.yml/runs?branch=main&event=push&per_page=20")["workflow_runs"]
        run = select_run(head, runs)
        if run is None:
            print("Current main has no successful release CI run", flush=True)
            return
        marker = args.state_dir / "deployed.json"
        if marker.exists() and json.loads(marker.read_text())["sha"] == head:
            deployed = json.loads(marker.read_text())
            if not args.dry_run and not deployed.get("status_reported", False):
                command("gh", "api", "--method", "POST",
                    f"repos/{REPO}/deployments/{deployed['deployment_id']}/statuses", "--input", "-",
                    input=json.dumps({"state": "success", "description": "Rollouts and delivery verified",
                                      "log_url": run["html_url"]}))
                deployed["status_reported"] = True
                write_state(marker, deployed)
            return
        failed = args.state_dir / "failed.json"
        if failed.exists() and json.loads(failed.read_text())["sha"] == head:
            print("Current release is held after a failure; review failed.json before retrying", flush=True)
            return
        artifacts = api(f"actions/runs/{run['id']}/artifacts")["artifacts"]
        if not any(a["name"] == "housepanel-release" and not a["expired"] for a in artifacts):
            print("No tested release artifact for current main", flush=True)
            return
        jobs = api(f"actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
        required = {"Quality Gate", "quality", "release"} | {f"image / {s}" for s in SERVICES}
        passed = {j["name"] for j in jobs if j["conclusion"] == "success"}
        if not required <= passed:
            raise RuntimeError("Release run is missing required quality jobs")
        if args.dry_run:
            print(json.dumps({"eligible_sha": head, "run_id": run["id"]}), flush=True)
            return
        with tempfile.TemporaryDirectory(prefix="release-", dir=args.state_dir) as temporary:
            directory = Path(temporary)
            command("gh", "run", "download", str(run["id"]), "--repo", REPO,
                    "--name", "housepanel-release", "--dir", str(directory))
            records = verify_artifacts(directory, head)
            if api("commits/main")["sha"] != head:
                print("Main advanced during download; deferring release", flush=True)
                return
            deployment = json.loads(command("gh", "api", "--method", "POST",
                f"repos/{REPO}/deployments", "--input", "-", input=json.dumps({
                    "ref": head, "environment": "housepanel", "auto_merge": False,
                    "required_contexts": ["Quality Gate"], "description": "Verified CI image release"})))

            def status(state: str, description: str):
                command("gh", "api", "--method", "POST",
                    f"repos/{REPO}/deployments/{deployment['id']}/statuses", "--input", "-",
                    input=json.dumps({"state": state, "description": description,
                        "log_url": run["html_url"]}))

            status("in_progress", "Deploying tested images and checking delivery")
            try:
                deploy(records, directory, head, args.context, args.registry)
            except BaseException as exc:
                failed.write_text(json.dumps({"sha": head, "run_id": run["id"], "error": str(exc), "time": time.time()}))
                status("failure", "Release failed; inspect local journal and rollback result")
                raise
            deployed = {"sha": head, "run_id": run["id"], "time": time.time(),
                        "deployment_id": deployment["id"], "status_reported": False}
            write_state(marker, deployed)
            status("success", "Rollouts healthy, panel connected, all pollers delivered")
            deployed["status_reported"] = True
            write_state(marker, deployed)


if __name__ == "__main__":
    main()
