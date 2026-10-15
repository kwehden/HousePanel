# HousePanel

A home automation display panel built on an Arduino Giga R1 WiFi with Giga Display Shield. Shows live weather, upcoming calendar events, sensor readings, and camera notifications on an 800×480 touchscreen display. Backend services run on a k3s cluster.

Ring doorbell notifications are retired as of October 5, 2026. The Ring
deployment stays at zero replicas, its metrics target is disabled, and its
service account has no secret access. The aggregator returns HTTP 410 for
Ring sources and the retired `doorbell-interrupt` event type. Other camera
webhooks remain supported. Existing Ring secrets are preserved, but no active
service needs them.

## Hardware

- **Arduino Giga R1 WiFi** (STM32H747XI dual-core, MbedOS) with **Giga Display Shield** (800×480)
- Display library: Arduino_H7_Video + LVGL 9.x
- Connects to the cluster over WiFi via WebSocket

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  k3s cluster                        │
│                                                     │
│  weather-poller ──┐                                 │
│  calendar-poller ─┤                                 │
│  sysmon-poller ───┼──► aggregator ──► transport-     │
│  webhook-receiver ┘                   adapter      │
│                                         │           │
└─────────────────────────────────────────┼───────────┘
                                          │ WebSocket
                                    ┌─────▼──────┐
                                    │ Giga panel │
                                    └────────────┘
```

| Service | Description |
|---|---|
| `weather-poller` | Polls OpenWeatherMap; pushes current conditions |
| `calendar-poller` | Polls Google Calendar via service account |
| `sysmon-poller` | Polls Arduino temperature and humidity readings |
| `webhook-receiver` | Receives camera motion webhooks (UniFi Protect, etc.) |
| `aggregator` | Merges all sources; fans out to connected panels |
| `transport-adapter` | WebSocket bridge (NodePort 30802) to Giga firmware |

## Repository layout

```
firmware/
  housepanel-giga/       Arduino sketch (LVGL display, WiFi, WebSocket)
  DEVENV.md              Firmware build environment setup
services/
  aggregator/            FastAPI — fan-out hub
  transport-adapter/     FastAPI — WebSocket bridge
  weather-poller/        FastAPI — OWM polling
  calendar-poller/       FastAPI — Google Calendar polling
  ring-integration/      Retired Ring integration, retained for reference
  webhook-receiver/      FastAPI — inbound webhooks
  shared/                Shared Pydantic models and helpers
k8s/                     Kubernetes manifests (namespace, deployments, services)
spec/                    Architecture context, requirements, design docs
```

## Setup

### Firmware

1. Install the Arduino Giga board core and required libraries (see `firmware/DEVENV.md`).
2. Copy `firmware/housepanel-giga/secrets.h.example` → `firmware/housepanel-giga/secrets.h` and fill in:
   - WiFi SSID and password
   - IP/hostname of your k3s node running the transport-adapter NodePort
3. Compile and upload:
   ```sh
   arduino-cli compile --fqbn arduino:mbed_giga:giga firmware/housepanel-giga/
   arduino-cli upload --fqbn arduino:mbed_giga:giga --port <PORT> firmware/housepanel-giga/
   ```

### Backend services

#### Kubernetes secrets

Create the required secrets before applying manifests:

```sh
# Google service account key (for calendar-poller)
kubectl create secret generic google-service-account \
  --from-file=service-account.json=/path/to/your-service-account.json \
  -n housepanel

# OpenWeatherMap API key (for weather-poller)
kubectl create secret generic openweathermap-api-key \
  --from-literal=api-key=YOUR_OWM_API_KEY \
  -n housepanel

# Webhook HMAC secret (for webhook-receiver)
kubectl create secret generic webhook-secrets \
  --from-literal=hmac-secret=YOUR_WEBHOOK_HMAC_SECRET \
  -n housepanel
```

#### ConfigMap

Edit `k8s/configmap.yaml` with your Google Calendar ID(s) before applying.

#### Apply manifests

```sh
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/serviceaccounts.yaml
kubectl apply -f k8s/
```

`kubectl apply -f k8s/` is safe to re-run: it applies workloads only. Secret
templates live in `k8s/templates/` as `.example` files and are deliberately
outside that path — they hold placeholder values, and applying them would
overwrite live credentials with `<REPLACE_WITH_...>` strings. Create secrets
with the `kubectl create secret` commands above, never by applying a template.

#### Container images

Images are pulled from a private registry. Build and push each active service
(exclude the retired `ring-integration`):

```sh
cd services/<service-name>
docker build -t <registry>/housepanel/<service-name>:0.1.0 .
docker push <registry>/housepanel/<service-name>:0.1.0
```

Update the image references in `k8s/*.yaml` to match your registry.

## Development

See `firmware/DEVENV.md` for the firmware build environment.

### CI and releases

Every PR and main push runs each service's pytest suite, uploads coverage,
checks Python errors with Ruff, and runs strict mypy for all active services
and shared code. All six
active services are built from the pinned Python base image. CI checks app
startup, health, metrics, shutdown, and the service tests against each packaged
image. Test tools live in a separate layer and do not replace application
dependencies in the release image.

The three pollers also run isolated HTTP memory probes for 3,000 polls. Calendar
exercises the real application lifespan, APScheduler, Uvicorn, metrics scrapes,
TLS, and synthetic service-account signing without forced garbage collection.
Its baseline starts after 12 polls, not 500 (42 hours at production cadence).
The other probes use 500 warm-up polls. RSS may grow at most 4 MiB total
and 1 MiB per 1,000 polls;
file descriptors, tasks, and threads must stay within small fixed allowances.
Calendar uses local TLS and synthetic service-account refreshes. Weather exercises
fallback. A daily CI run extends the probes to 10,000 polls. These thresholds
catch the reproduced sysmon leak, but cannot rule out every leak at normal
cadence or against real upstream payloads. Coverage floors were calibrated
against the existing tests: 95% for calendar/shared, 90% for sysmon/webhooks,
85% for aggregator/weather, 70% for transport, and 55% for retired Ring code.

`Quality Gate` requires every test, quality, and image job to pass. Main pushes
then publish a `housepanel-release` artifact containing the exact tested image
archives, their SHA-256 hashes, image IDs, and source commit. PR and scheduled
runs cannot trigger deployment.

The local `housepanel-release.timer` checks GitHub every five minutes. Its
agent accepts only successful push CI for the current main commit, verifies
artifact hashes and image revisions, pushes to the private registry, and uses
immutable registry digests for all six deployments. It waits for each rollout,
checks health and restarts, waits for the panel to reconnect, and requires all
pollers to deliver an update after the release started. Ring must stay disabled.
An unsuccessful rollout or verification restores the previous image references.
GitHub records deployment status. A failed commit is held for review, rather
than repeatedly redeployed. Secrets and live ConfigMaps are not rewritten.

The agent is installed locally from the reviewed `tools/release_agent.py`;
update that installed copy explicitly when changing the agent itself. It runs
with the user's existing GitHub, Docker, and kubectl access. GitHub-hosted PR
jobs have no cluster credentials and no access to a local runner.

```sh
systemctl --user status housepanel-release.timer
journalctl --user -u housepanel-release.service -n 50
python tools/release_agent.py --dry-run
```

State lives in `~/.local/state/housepanel-release`. Inspect `failed.json` and
the journal before removing that failure marker to retry a release. Stop the
timer with `systemctl --user stop housepanel-release.timer` to pause releases.
User services run after logout/reboot when linger is enabled. Firmware builds
and physical display checks remain manual.

The [release process](docs/releases.md) defines version tags, GitHub release
records, verification evidence, rollback, and the 24-hour memory comparison.
Main still deploys automatically; release tags record verified deployments.

Internal payload contracts reject malformed structured updates, non-finite
numbers, calendar lists over 500 events, weather forecasts over four days,
and payloads over 256 KiB. HTTP request streams are capped at 512 KiB before
JSON parsing. The transport fits compact UTF-8 JSON frames below 200 bytes,
also respecting the firmware's individual string-buffer byte limits.
HELLO refreshes share one owned polling task and drain it on shutdown.
Malformed weather payloads trigger fallback and failure accounting.
Calendar requests only the Google fields used by the panel and parses bounded
streamed bodies, avoiding retention of cached bodies in HTTPX response cycles.
After closing, calendar detaches HTTPX streams on both fetch and push paths so
completed responses and uploaded event bodies do not have to wait for cyclic GC.

`tools/calendar_allocation_probe.py` is an opt-in, Linux/glibc diagnostic for a
dedicated read-only canary. It forces delivery to a local discard endpoint and
exports Python heap, native used/free allocation, RSS, and resource counts.
Run separate traced and untraced arms; tracer snapshots themselves consume
memory, so use the untraced arm for RSS comparisons. GC and allocator trimming
are endpoint experiments only, never production memory-management policy.

Changes remain in PRs for user review before merging. Do not run more than
two Codex review rounds without consulting the user.

Each service has a standard Python layout with `pyproject.toml` and a test suite:

```sh
cd services/<service-name>
pip install -e ../shared -e .[dev]
pytest
```

### Poller memory and lifecycle

The sysmon, calendar, and weather pollers reuse HTTP clients across polls.
Each service owns at most one polling task, shared by scheduled and manual
refreshes. Requests arriving during a poll coalesce into that poll. Shutdown
waits for the outstanding poll before closing its HTTP clients, including
clients used by worker threads.

The October 5 investigation found sysmon RSS growing about 1.68 MiB/hour and
calendar RSS about 0.21 MiB/hour over the preceding six hours. Other services
were approximately flat. The recorded container exits did not identify OOM
kills. A probe using two persistent HTTP connections reproduced the sysmon
growth with a fresh client per poll; reusing the client eliminated that growth
in the same runtime. Unrestricted manual polling and missing client cleanup
were fixed as well.

Run the isolated HTTP probe with the sysmon dependencies installed:

```sh
python tools/memory_probe.py --cycles 3000 --sample-every 500
```

It uses loopback HTTP and synthetic readings, with no upstream credentials or
cluster writes. It reports RSS, open file descriptors, and pending tasks. It
also supports the previous sysmon image for comparison. In the Python 3.12
image, the old code grew from 66.3 MiB at 500 polls to 91.4 MiB at 3,000 polls,
and retained that memory after garbage collection. The patched code stayed
near 50.4 MiB. Both released their sockets and server tasks on shutdown. This
isolates client allocation churn as a source of memory retention; confirming
the production trend still requires several hours at the normal cadence.

Check the production trend in Prometheus after the services have run for
several hours:

```promql
max by (pod) (
  deriv(container_memory_rss{namespace="housepanel",container!="",container!="POD"}[6h])
) * 3600 / 1024 / 1024
```

#### Calendar follow-up profiling

After the first rollout, calendar's six-hour slope was still about 0.12
MiB/hour. Its later two-hour slope fell to 0.025 MiB/hour before the next
rollout. A positive RSS slope alone does not distinguish leaked objects from
allocator warm-up.

The follow-up found a lifecycle bug in the first fix: Google Auth's
`Request.__del__` closes even a caller-owned session. Creating a temporary
wrapper on every refresh therefore closed the supposedly reusable session.
Calendar 0.2.3 retains both the wrapper and session until shutdown. A regression
test using the real wrapper fails on 0.2.2 and passes with the correction.

`tools/calendar_memory_probe.py` exercises the real polling path against two
synthetic calendars (52 events), a local OAuth endpoint, and a local aggregator.
It uses one worker thread, matching production, and can expire HTTP connections
to model the normal five-minute interval without waiting between polls.
Run it in the calendar image with synthetic TLS:

```sh
mkdir -p build/calendar-profile
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -keyout build/calendar-profile/key.pem -out build/calendar-profile/cert.pem \
  -subj /CN=localhost -addext subjectAltName=IP:127.0.0.1
docker run --rm --network none --memory 512m \
  -v "$PWD/tools/calendar_memory_probe.py:/probe.py:ro" \
  -v "$PWD/build/calendar-profile:/tls:ro" \
  --entrypoint python laminarflow:30500/housepanel/calendar-poller:0.2.3 \
  /probe.py --cert /tls/cert.pem --key /tls/key.pem \
  --cycles 5000 --sample-every 1000 --expire-connections
```

With the correction, 5,000 polls and 416 token refreshes kept socket, thread,
and task counts constant. RSS fluctuated between 53.6 and 53.8 MiB after the
first 1,000 polls, ending only 64 KiB above that checkpoint. Closing clients
released the connections; diagnostic `malloc_trim` returned another 844 KiB.
Without token refreshes, the old release also plateaued over 5,000 polls.

Separate `--trace` runs attributed the small retained Python growth mainly to
timestamp formatting and HTTP helpers, not accumulating calendar events or
polling tasks. An auth-only run (`--mode auth --trace`) retained just 1.6 KiB
between refreshes 100 and 1,000 with the correction. Optional
`--native-output /path/profile.bin` requires Memray installed in the profiling
container. Native tracing found substantial allocation churn, but did not
establish an unbounded native leak. The probe includes its local servers and
profiler overhead in RSS; its absolute numbers are not production baselines.

These tests support allocator warm-up/retention as an explanation for the
remaining slow trend. They do not prove that the wrapper bug caused that trend,
or rule out leaks specific to real payloads, error paths, or long idle periods.
No profiler, forced garbage collection, or allocator trimming is enabled in
production. Check production slopes over multiple windows after rollout.

The October 10 calendar review added runtime checks for JSON field types,
typed HTTP parameters and endpoint responses, and a strict module-level mypy
configuration. After installing the calendar `dev` extras, run `python -m mypy`
from `services/calendar-poller`. Missing third-party stubs are ignored; the
untyped Google Auth refresh call has one specific suppression.

The review also corrected all-calendar HTTP failures being reported as a
successful empty result, and counted auth, network, and malformed-response
failures without replacing the last good state. Partial HTTP success retains
the existing behavior of publishing the calendars that succeeded.

Matched 1,000-poll TLS probes compared release 0.2.3 with the local corrections.
Between polls 100 and 1,000, post-GC traced Python growth was 36.5 KiB before and
12.6 KiB after. UTC-normalized ISO formatting replaces the previous `strftime`
calls, reducing retained allocations at those sites. Resource counts stayed
constant. Weak-reference tests additionally verify release of old events and
HTTP responses on success and failure paths. This does not establish the cause
of production RSS drift, and these October 10 changes are not yet deployed.

### Mutation testing

A green suite proves the tests ran, not that they assert anything.
`tools/mutate.py` breaks one line of source at a time and re-runs that
service's tests; if they still pass, nothing was checking that behaviour.

```sh
python tools/mutate.py                    # every service
python tools/mutate.py weather-poller --cap 40
```

It found ten real gaps on its first run, including a `stream_decompose` change
that zeroes every temperature on the panel with the whole suite green. Worth a
pass after adding tests to a service.

Not every survivor is a gap — some are *equivalent mutants* that cannot change
behaviour. Read each before writing a test for it. The tool edits files in
place and restores them, and refuses to start if the target sources have
uncommitted changes so an interrupted run stays recoverable.

## Security notes

- `firmware/housepanel-giga/secrets.h` is git-ignored and never committed.
- K8s secrets (`*credentials*.json`, service account keys) are git-ignored.
- Webhook HMAC validation uses constant-time comparison (`hmac.compare_digest`).
- Retired Ring credentials remain in the K8s Secret until explicitly removed.
