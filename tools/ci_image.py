"""Build and test the exact image that will be deployed; export a verified archive."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from check_memory import assess
from release_agent import archive_config

ROOT = Path(__file__).resolve().parent.parent
SERVICES = ("aggregator", "calendar-poller", "sysmon-poller", "transport-adapter",
            "weather-poller", "webhook-receiver")


def run(*args, **kwargs):
    return subprocess.run(args, check=True, cwd=ROOT, timeout=1200, **kwargs)


def build(service: str, sha: str, cycles: int) -> None:
    output = ROOT / "build" / "release" / service
    output.mkdir(parents=True, exist_ok=True)
    image = f"housepanel/{service}:{sha}"
    run("docker", "build", "--platform", "linux/amd64", "--label",
        f"org.opencontainers.image.revision={sha}", "-f", f"services/{service}/Dockerfile", "-t", image, ".")
    container = ("docker", "run", "--rm", "--network", "none", "--memory", "512m",
                 "-v", f"{ROOT / 'tools'}:/tools:ro", "-v", f"{ROOT / 'services' / service / 'tests'}:/tests:ro",
                 "--entrypoint", "python", image)
    run(*container, "/tools/image_smoke.py", service)
    test_image = image + "-test"
    run("docker", "build", "--build-arg", f"BASE_IMAGE={image}", "-f", "tools/Dockerfile.test", "-t", test_image, ".")
    run(*container[:-1], test_image, "-m", "pytest", "/tests", "-q", "--asyncio-mode=auto", "-p", "no:cacheprovider")
    probe = {"sysmon-poller": "memory_probe.py", "calendar-poller": "calendar_runtime_probe.py",
             "weather-poller": "weather_memory_probe.py"}.get(service)
    if probe:
        probe_args = ["--cycles", str(cycles)]
        if service == "calendar-poller":
            run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                "-keyout", str(output / "key.pem"), "-out", str(output / "cert.pem"),
                "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1",
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # Add the synthetic TLS files before the image argument.
            container = (*container[:-1], "-v", f"{output}:/tls:ro", container[-1])
            probe_args += ["--cert", "/tls/cert.pem", "--key", "/tls/key.pem", "--warmup", "12",
                           "--sample-every", "250"]
        log = output / "memory.jsonl"
        with log.open("w") as stream:
            run(*container, f"/tools/{probe}", *probe_args, stdout=stream)
        samples = [json.loads(line) for line in log.read_text().splitlines() if line.startswith("{")]
        print(json.dumps({"service": service, "memory": assess(samples, warmup=12 if service == "calendar-poller" else 500)}), flush=True)
    archive = output / f"{service}.tar.gz"
    # Save and compress without loading the image into Python memory.
    with archive.open("wb") as stream:
        saved = subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE)
        assert saved.stdout is not None
        zipped = subprocess.run(["gzip", "-c"], stdin=saved.stdout, stdout=stream, timeout=1200)
        saved.stdout.close()
        if saved.wait(timeout=60) or zipped.returncode:
            raise RuntimeError("Image export failed")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    image_id = run("docker", "image", "inspect", image, "--format", "{{.Id}}", capture_output=True, text=True).stdout.strip()
    config_digest, _ = archive_config(archive, image)
    (output / f"{service}.json").write_text(json.dumps({"service": service, "sha": sha,
        "archive": archive.name, "sha256": digest, "image_id": image_id, "config_digest": config_digest}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=SERVICES)
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--cycles", type=int, default=3000)
    args = parser.parse_args()
    if not args.sha or len(args.sha) != 40 or any(c not in "0123456789abcdef" for c in args.sha):
        parser.error("A full commit SHA is required")
    build(args.service, args.sha, args.cycles)
