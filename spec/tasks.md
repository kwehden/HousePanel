# HousePanel — Task Plan

_Gate 4 artifact. Created: 2026-05-16. Owner: karl@wehden.com._
_Source of truth: `spec/context.md` (Gate 1), `spec/requirements.md` (Gate 2), `spec/design.md` (Gate 3)._

---

## Task Graph Overview

26 tasks organized into 11 groups. The critical path runs:

```
TASK-001 (scaffold)
  └─► TASK-003 (shared types)
        ├─► TASK-005 (webhook receiver impl)   ─► TASK-022 (K8s: webhook-receiver)
        ├─► TASK-007 (aggregator impl)         ─► TASK-023 (K8s: aggregator)
        ├─► TASK-009 (calendar poller impl)    ─► TASK-024 (K8s: pollers)
        ├─► TASK-010 (weather poller impl)     ─► TASK-024
        ├─► TASK-013 (Ring backend impl)       ─► TASK-025 (K8s: ring + transport)
        └─► TASK-016 (transport adapter impl)  ─► TASK-025

  TASK-002 (K8s namespace + RBAC) — prerequisite for all TASK-02x
  TASK-004 (camera webhook schema pub) — unblocks external dependency
  TASK-006 (HMAC secret setup) — prerequisite for TASK-005
  TASK-008 (Google ADC secret) — prerequisite for TASK-009, TASK-010
  TASK-011 (ATH webhook schema) — unblocks sibling repo; can run after TASK-003
  TASK-012 (Ring token — interactive) — prerequisite for TASK-013
  TASK-014 (Ring K8s secret) — prerequisite for TASK-025
  TASK-017 (Arduino dev env setup) — prerequisite for TASK-018 through TASK-021
  TASK-018 (WiFi + WebSocket firmware) — prerequisite for TASK-019 and TASK-020
  TASK-019 (command frame parser firmware) — prerequisite for TASK-020 and TASK-021
  TASK-020 (display render firmware)
  TASK-021 (OTA protocol firmware)
  TASK-026 (integration wiring + smoke test) — depends on all TASK-02x
```

Parallelizable groups after TASK-001 and TASK-002 are completed:
- TASK-003 through TASK-006 can start in parallel with TASK-002
- TASK-007 through TASK-011 can start after TASK-003
- TASK-012 can start independently at any point
- Firmware tasks (TASK-017 through TASK-021) are entirely independent of K8s tasks and can run in parallel with them

**External dependency note:** The `unifi-camera-summarizer` repo must implement against the camera webhook schema published in TASK-004. That implementation is NOT a HousePanel task and is not tracked here. HousePanel's only obligation is to publish the stable schema (TASK-004) before that team begins.

---

## Tasks

---

### TASK-001 — Repository Scaffolding

**Recommended Mode:** executor

**Objective:** Create the full directory skeleton and shared tooling configuration for all six services and the firmware, establishing consistent Python project hygiene before any implementation begins. All six backend services are Python 3.12.

**Requirements:** REQ-WHR-006, REQ-AGG-006, REQ-CAL-005, REQ-WTH-007, REQ-RNG-005, REQ-ART-005, REQ-PER-006

**Write Lease:**
```
^services/webhook-receiver/.*$
^services/aggregator/.*$
^services/calendar-poller/.*$
^services/weather-poller/.*$
^services/ring-integration/.*$
^services/transport-adapter/.*$
^firmware/.*$
^k8s/.*$
^\.gitignore$
^\.python-version$
```

**Change Budget:**
- max_files: 30
- max_new_symbols: 0 (scaffold only — no logic symbols)
- interface_policy: new_interface

**Steps:**

1. Create top-level directories:
   ```
   services/webhook-receiver/
   services/aggregator/
   services/calendar-poller/
   services/weather-poller/
   services/ring-integration/
   services/transport-adapter/
   firmware/housepanel-giga/
   k8s/
   ```

2. For each Python service (`webhook-receiver`, `aggregator`, `calendar-poller`, `weather-poller`, `transport-adapter`), create:
   - `pyproject.toml` declaring Python 3.12, project name, and the allowed dependencies from the design's simplicity budget. No extra dependencies.
   - `requirements.txt` pinning the same allowed dependencies.
   - `src/<service_slug>/` Python package with empty `__init__.py`.
   - `tests/` directory with empty `__init__.py`.
   - `Dockerfile` using `python:3.12-slim` base, copying `requirements.txt`, running `pip install`, copying `src/`, setting `CMD ["uvicorn", ...]` (uvicorn entrypoint placeholder — exact module path filled in per service).
   - `.dockerignore` excluding `__pycache__`, `*.pyc`, `.git`, `tests/`.

3. For `ring-integration` (Python, same pattern as other Python services):
   - `pyproject.toml` declaring Python 3.12 and `ring_doorbell[listen]` as the sole runtime dependency.
   - `requirements.txt` pinning `ring_doorbell[listen]`.
   - `src/ring_integration/` package with empty `__init__.py`.
   - `tests/` directory with empty `__init__.py`.
   - `Dockerfile` using `python:3.12-slim` base (same as all other services).
   - `.dockerignore` excluding `__pycache__`, `*.pyc`, `.git`, `tests/`.

4. For the firmware, create:
   - `firmware/housepanel-giga/housepanel-giga.ino` — empty Arduino sketch with just `setup()` and `loop()` stubs.
   - `firmware/housepanel-giga/config.h` — placeholder header with `SSID`, `WIFI_PASS`, `TRANSPORT_ADAPTER_HOST`, `TRANSPORT_ADAPTER_PORT`, `FIRMWARE_VERSION` constants, all set to empty strings or zero.

5. Create `k8s/` with a single `README.txt` noting it will hold Kubernetes manifests created in TASK-022 through TASK-025.

6. Create top-level `.gitignore` covering: `__pycache__/`, `*.pyc`, `*.egg-info/`, `.venv/`, `node_modules/`, `*.env`, `.task-lease.regex`, `.task-budget.json`.

7. Create top-level `.python-version` with content `3.12`.

**Verification:**
- `find services/ -name "pyproject.toml" | wc -l` must output `6`.
- `find services/ -name "Dockerfile" | wc -l` must output `6`.
- `find services/ firmware/ -name "__init__.py" | wc -l` must output at least `10` (src + tests packages per Python service).
- `cat firmware/housepanel-giga/housepanel-giga.ino` must contain `void setup()` and `void loop()`.
- `python3 --version` must report `3.12.x`.

**Dependencies:** None (first task)

**Risk:** Low — pure directory/file creation, no logic.

---

### TASK-002 — Kubernetes Namespace and RBAC

**Recommended Mode:** executor

**Objective:** Create the `housepanel` Kubernetes namespace on the `laminarflow` k3s cluster and establish per-service ServiceAccounts with `automountServiceAccountToken: false`.

**Requirements:** REQ-SEC-005, REQ-WHR-006, REQ-AGG-006, REQ-CAL-005, REQ-WTH-007, REQ-RNG-005, REQ-ART-005

**Write Lease:**
```
^k8s/namespace\.yaml$
^k8s/serviceaccounts\.yaml$
```

**Change Budget:**
- max_files: 2
- max_new_symbols: 0
- interface_policy: new_interface

**Steps:**

1. Create `k8s/namespace.yaml` defining a Namespace named `housepanel` with label `app.kubernetes.io/part-of: housepanel`. The manifest must not touch any other namespace.

2. Create `k8s/serviceaccounts.yaml` defining one ServiceAccount per service (six total) in the `housepanel` namespace, each with:
   - `automountServiceAccountToken: false`
   - Label `app.kubernetes.io/part-of: housepanel`
   - Names: `housepanel-webhook-receiver`, `housepanel-aggregator`, `housepanel-calendar-poller`, `housepanel-weather-poller`, `housepanel-ring-integration`, `housepanel-transport-adapter`

3. Apply the namespace manifest:
   ```
   kubectl apply -f k8s/namespace.yaml
   ```

4. Apply the service accounts manifest:
   ```
   kubectl apply -f k8s/serviceaccounts.yaml
   ```

**Verification:**
- `kubectl get namespace housepanel` must show `STATUS: Active`.
- `kubectl get serviceaccounts -n housepanel` must list all six ServiceAccount names.
- `kubectl get namespace --no-headers | grep -v housepanel | grep -c .` must return the same count as before this task (no other namespaces created or modified).
- Inspect an existing namespace (e.g., `kubectl get namespace ollama`) to confirm it is unchanged.

**Rollback:**
```
kubectl delete -f k8s/serviceaccounts.yaml
kubectl delete -f k8s/namespace.yaml
```
Warning: deleting the namespace will delete all resources within it. Only perform rollback if the namespace is empty of live workloads.

**Dependencies:** None (can run in parallel with TASK-001)

**Risk:** Low — namespace creation on a home cluster; the sole risk is accidentally targeting a wrong namespace, which is prevented by the explicit manifest content check in verification.

---

### TASK-003 — Shared Python Types and Structured Logging

**Recommended Mode:** executor

**Objective:** Define the `UnifiedEvent`, `WeatherConditions`, `CalendarEvent`, and structured logging helpers as importable Python modules shared across all five Python services.

**Requirements:** REQ-DAT-002, REQ-DAT-005, REQ-OBS-001

**Write Lease:**
```
^services/shared/.*$
```

**Change Budget:**
- max_files: 6
- max_new_symbols: 12 (dataclasses: UnifiedEvent, WeatherConditions, CalendarEvent, CalendarState, InternalEventRequest, CommandRequest; helpers: make_logger, log_event; enums: EventType, AlertType, AlertSeverity, WeatherProvider)
- interface_policy: new_interface

**Steps:**

1. Create `services/shared/` Python package:
   - `services/shared/__init__.py` (empty)
   - `services/shared/models.py` — defines all dataclasses and enums exactly as specified in the design's "Internal Event Bus Contract" and "Data Model" sections:
     - `EventType` enum: `ticker`, `doorbell_interrupt`, `weather_update`, `calendar_update`
     - `AlertType` enum: `temperature`, `humidity`, `system`, `network`
     - `AlertSeverity` enum: `info`, `warning`, `critical`
     - `WeatherProvider` enum: `google`, `openweathermap`
     - `@dataclass UnifiedEvent` with fields: `event_id: str`, `source: str`, `event_type: str`, `timestamp: datetime`, `priority: int`, `ttl_seconds: int`, `payload: dict`, `dedup_hash: str | None`
     - `@dataclass WeatherConditions` with fields: `provider: str`, `timestamp: datetime`, `temperature_c: float`, `conditions: str`, `humidity_pct: float | None`, `wind_speed_ms: float | None`, `icon_code: str | None`
     - `@dataclass CalendarEvent` with fields: `event_id: str`, `summary: str`, `start: str`, `end: str`, `all_day: bool`
     - `@dataclass CalendarState` with fields: `poll_timestamp: datetime`, `events: list[CalendarEvent]`
   - `services/shared/logging.py` — defines `make_logger(service_name: str) -> logging.Logger` that configures Python's stdlib `logging` to emit JSON-structured lines to stdout. Required fields per log line: `timestamp` (ISO8601), `level`, `service`, `event`, `message`. Uses `python-json-logger` or a manual JSON formatter — prefer stdlib; only add `python-json-logger` if stdlib `logging.Formatter` cannot produce the required JSON structure cleanly.
   - `services/shared/py.typed` — marker file for PEP 561 type checking support.

2. Add `services/shared/` to the `pyproject.toml` of each Python service as a path dependency so all five services can import from it without duplication.

3. Create `services/shared/tests/test_models.py`:
   - Instantiate each dataclass with valid data; assert field values round-trip correctly.
   - Assert `UnifiedEvent.event_type` is a string (not enum) since the design uses string literals in HTTP payloads; document this in a comment.

**Verification:**
- `cd services/shared && python3 -c "from shared.models import UnifiedEvent, WeatherConditions, CalendarEvent; print('ok')"` must print `ok`.
- `cd services/shared && python3 -m pytest tests/ -q` must pass all tests with zero failures.
- `python3 -c "from shared.logging import make_logger; import json; ..."` — write a test that calls `make_logger('test')`, logs a test line, and confirms the output is valid JSON with the required fields.
- Grep for any import of `logging` in a service file to confirm shared logger is being used, not ad-hoc formatters.

**Dependencies:** TASK-001

**Risk:** Low — pure data definitions with no external I/O; errors caught by the model tests.

---

### TASK-004 — Camera Webhook Schema Publication (External Dependency Unblock)

**Recommended Mode:** executor

**Objective:** Publish the stable `POST /v1/webhooks/camera` JSON schema as a machine-readable file so the `unifi-camera-summarizer` team can implement against it immediately, independent of HousePanel implementation progress.

**Requirements:** REQ-WHR-001, REQ-WHR-005, REQ-DAT-001, REQ-DAT-003, REQ-BCK-001

**Write Lease:**
```
^spec/schemas/camera-webhook-v1\.json$
^spec/schemas/README\.txt$
```

**Change Budget:**
- max_files: 2
- max_new_symbols: 0 (schema artifact, not code)
- interface_policy: new_interface

**Steps:**

1. Create `spec/schemas/` directory.

2. Create `spec/schemas/camera-webhook-v1.json` containing the complete JSON Schema (draft-07) for the `POST /v1/webhooks/camera` body, exactly matching the design document's definition:
   - Required fields: `schema_version` (const `"1"`), `source` (const `"unifi-protect"`), `timestamp` (ISO8601 string), `camera_name` (string), `narrative` (string)
   - Include a top-level `$schema`, `$id`, `title`, and `description`.
   - Include an `examples` array with one valid example payload.
   - Note in the schema's `description` field: "Breaking schema changes will be introduced as `/v2/` path variants. `/v1/` will remain supported until explicit deprecation."

3. Create `spec/schemas/README.txt` with:
   - The exact URL path where this endpoint is served: `POST /v1/webhooks/camera`
   - The required authentication header: `X-HousePanel-Signature: sha256=<hex>`
   - The expected response codes: 202, 400, 401, 422.
   - A note that this schema is owned by HousePanel and is stable from first release.

**Verification:**
- `python3 -c "import json, sys; json.load(open('spec/schemas/camera-webhook-v1.json'))"` must succeed (valid JSON).
- Validate the schema is valid JSON Schema draft-07 using `jsonschema` CLI or Python: `python3 -c "import jsonschema; jsonschema.Draft7Validator.check_schema(json.load(open('spec/schemas/camera-webhook-v1.json')))"`.
- Manually confirm that the example payload in the schema passes validation against the schema itself.

**Dependencies:** TASK-001 (for directory conventions, not strictly blocking schema creation)

**Risk:** Low — static file creation; schema content is fully specified in the design document.

---

### TASK-005 — Webhook Receiver Service Implementation

**Recommended Mode:** executor

**Objective:** Implement the FastAPI webhook receiver service with HMAC-SHA256 validation, Pydantic schema validation, and forwarding to the aggregator for both `/v1/webhooks/camera` and `/v1/webhooks/system-alert` endpoints.

**Requirements:** REQ-WHR-001, REQ-WHR-002, REQ-WHR-003, REQ-WHR-004, REQ-WHR-005, REQ-ERR-003, REQ-SEC-001, REQ-SEC-002, REQ-SEC-004, REQ-OBS-001, REQ-OBS-002, REQ-DAT-001, REQ-DAT-003

**Write Lease:**
```
^services/webhook-receiver/src/.*$
^services/webhook-receiver/tests/.*$
```

**Change Budget:**
- max_files: 10
- max_new_symbols: 15 (app, routers, validate_hmac_signature, CameraWebhookPayloadV1, SystemAlertWebhookPayloadV1, forward_to_aggregator, reject_malformed_payload, healthz handler, and their test counterparts)
- interface_policy: new_interface

**Steps:**

1. Implement `services/webhook-receiver/src/webhook_receiver/main.py`:
   - Create a FastAPI `app` instance.
   - Register `GET /healthz` returning `{"status": "ok"}`.
   - Include a router for `/v1/webhooks`.

2. Implement `services/webhook-receiver/src/webhook_receiver/schemas.py`:
   - Define Pydantic v2 models `CameraWebhookPayloadV1` and `SystemAlertWebhookPayloadV1` exactly matching the design's field definitions.
   - `SystemAlertWebhookPayloadV1` must include `alert_type` as a `Literal["temperature", "humidity", "system", "network"]` and `severity` as a `Literal["info", "warning", "critical"]`.
   - `message` field max length: 200 characters (use `Field(max_length=200)`).
   - `temperature_c` and `humidity_pct` are `float | None`.

3. Implement `services/webhook-receiver/src/webhook_receiver/auth.py`:
   - Function `validate_hmac_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool`.
   - Use `hmac.new(key=secret.encode(), msg=raw_body, digestmod=hashlib.sha256)`.
   - Compare with `hmac.compare_digest()` — not `==`.
   - Parse the header format `sha256=<hex>` before comparing.
   - Return `False` if header is `None` or malformed.
   - This function must never log the `secret` argument.

4. Implement `services/webhook-receiver/src/webhook_receiver/routes.py`:
   - `POST /v1/webhooks/camera`: Read raw body before Pydantic parsing (needed for HMAC), call `validate_hmac_signature` with `WEBHOOK_SECRET_UNIFI` env var, parse body into `CameraWebhookPayloadV1`, call `forward_to_aggregator`. Return 401 on HMAC failure, 400 on schema validation failure, 202 on success.
   - `POST /v1/webhooks/system-alert`: Same flow using `WEBHOOK_SECRET_ATH` env var and `SystemAlertWebhookPayloadV1`.
   - Log using the shared logger: `webhook_received` and `webhook_rejected` structured events as defined in the design.
   - Do not log `secret` values or raw body contents.

5. Implement `services/webhook-receiver/src/webhook_receiver/forwarder.py`:
   - `async def forward_to_aggregator(event_data: dict) -> None`.
   - HTTP POST to `AGGREGATOR_URL` (env var) at path `/internal/events` using `httpx.AsyncClient` with a 5-second timeout.
   - On HTTP error or timeout: log the failure with `level=ERROR`; do not raise (the webhook has already been accepted).

6. Implement tests in `services/webhook-receiver/tests/`:
   - `test_auth.py`: Test HMAC validation with valid signature, invalid signature, missing header, and wrong algorithm prefix.
   - `test_routes.py`: Use `httpx.AsyncClient` with the FastAPI `TestClient` to test: valid camera payload with correct HMAC (expect 202), valid system-alert payload with correct HMAC (expect 202), invalid HMAC (expect 401), malformed JSON (expect 422), wrong schema version (expect 400), missing required field (expect 400).
   - Mock `forward_to_aggregator` in route tests so no real HTTP calls are made.

**Verification:**
- `cd services/webhook-receiver && python3 -m pytest tests/ -v` must pass all tests with zero failures.
- Manually test with curl (after TASK-006 creates the secret): generate a valid HMAC-SHA256 signature for a test body and confirm 202; send with wrong signature and confirm 401; send malformed JSON and confirm 422.
- `grep -r "secret\|WEBHOOK_SECRET" services/webhook-receiver/src/ | grep -i "log\|print"` must return zero matches (no credential logging).

**Dependencies:** TASK-003 (shared types and logging), TASK-006 (HMAC secrets for manual testing — but unit tests can run without them)

**Risk:** Medium — HMAC validation is security-critical. The timing-safe comparison and raw-body capture (before Pydantic parsing) are implementation traps that must be explicitly verified.

---

### TASK-006 — HMAC Webhook Secrets (K8s Secrets)

**Recommended Mode:** executor

**Objective:** Create K8s Secrets for the two webhook HMAC shared secrets in the `housepanel` namespace.

**Requirements:** REQ-SEC-001, REQ-SEC-004, REQ-SEC-005

**Write Lease:**
```
^k8s/secrets-webhook\.yaml$
```

**Change Budget:**
- max_files: 1
- max_new_symbols: 0
- interface_policy: new_interface

**Steps:**

1. Generate two cryptographically random shared secrets (32 bytes each, hex-encoded):
   ```
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   Run this twice — one for `WEBHOOK_SECRET_UNIFI`, one for `WEBHOOK_SECRET_ATH`.

2. Create the K8s Secret using `kubectl create secret` (not a YAML file with plaintext values, to avoid committing secrets to source):
   ```
   kubectl create secret generic housepanel-webhook-secrets \
     --namespace housepanel \
     --from-literal=WEBHOOK_SECRET_UNIFI=<generated-value-1> \
     --from-literal=WEBHOOK_SECRET_ATH=<generated-value-2>
   ```

3. Create `k8s/secrets-webhook.yaml` as a **template only** (no real values). The file must contain:
   ```yaml
   # Template — do not commit real values.
   # Apply with: kubectl create secret generic housepanel-webhook-secrets ...
   # See Step 2 of TASK-006 in spec/tasks.md for the command.
   apiVersion: v1
   kind: Secret
   metadata:
     name: housepanel-webhook-secrets
     namespace: housepanel
   type: Opaque
   stringData:
     WEBHOOK_SECRET_UNIFI: "<REPLACE_WITH_GENERATED_VALUE>"
     WEBHOOK_SECRET_ATH: "<REPLACE_WITH_GENERATED_VALUE>"
   ```
   Add `k8s/secrets-webhook.yaml` to `.gitignore` if real values might ever appear there. The template approach avoids this risk.

4. Record the generated values in a local, git-ignored file (e.g., `.secrets/webhook-secrets.env`) for operational reference. Add `.secrets/` to `.gitignore`.

**Verification:**
- `kubectl get secret housepanel-webhook-secrets -n housepanel` must show the secret exists.
- `kubectl get secret housepanel-webhook-secrets -n housepanel -o jsonpath='{.data.WEBHOOK_SECRET_UNIFI}'` must return a non-empty base64 string.
- `grep -r "WEBHOOK_SECRET_UNIFI\|WEBHOOK_SECRET_ATH" k8s/ services/ | grep -v "\.yaml\|\.env\|template\|REPLACE"` must return zero matches (no plaintext secrets in source files).

**Rollback:**
```
kubectl delete secret housepanel-webhook-secrets -n housepanel
```

**Dependencies:** TASK-002 (namespace must exist)

**Risk:** Low — secret creation; main risk is committing real values to git. The template-only YAML approach prevents this.

---

### TASK-007 — Event Aggregator Service Implementation

**Recommended Mode:** executor

**Objective:** Implement the event aggregator with the FIFO ticker queue (deque maxlen=20, 60s TTL, SHA-256 dedup within 30s window), doorbell fast-path routing, last-good state cache, and the ticker drain background loop.

**Requirements:** REQ-AGG-001, REQ-AGG-002, REQ-AGG-003, REQ-AGG-004, REQ-AGG-005, REQ-ERR-004, REQ-PER-005, REQ-OBS-001, REQ-DAT-002

**Write Lease:**
```
^services/aggregator/src/.*$
^services/aggregator/tests/.*$
```

**Change Budget:**
- max_files: 12
- max_new_symbols: 20 (TickerQueue, DedupCache, AggregatorState, route_event, route_doorbell_interrupt, enqueue_ticker_event, ticker_drain_loop, dispatch_command_to_transport, get_state, normalize_event, healthz handler, internal_events handler, internal_state handler, internal_health handler, and their test counterparts)
- interface_policy: new_interface

**Steps:**

1. Implement `services/aggregator/src/aggregator/queue.py`:
   - `TickerQueue` class wrapping `collections.deque(maxlen=TICKER_QUEUE_MAX_DEPTH)` where `TICKER_QUEUE_MAX_DEPTH` defaults to `20` from env var `TICKER_QUEUE_MAX_DEPTH`.
   - Methods: `enqueue(event: UnifiedEvent) -> bool` (returns False if dropped for dedup/overflow), `dequeue_non_expired() -> UnifiedEvent | None`, `snapshot() -> list[UnifiedEvent]`.
   - TTL enforcement: `dequeue_non_expired()` skips events older than `TICKER_EVENT_TTL_SECONDS` (default `60`).
   - Overflow policy: `deque(maxlen=N)` drops the oldest element automatically; log `ticker_dropped_overflow` when this happens.

2. Implement `services/aggregator/src/aggregator/dedup.py`:
   - `DedupCache` class using a `dict[str, datetime]` mapping `dedup_hash` → expiry.
   - Method `is_duplicate(dedup_hash: str) -> bool` — returns True if hash exists and has not expired.
   - Method `record(dedup_hash: str) -> None` — records hash with expiry = now + `TICKER_DEDUP_WINDOW_SECONDS` (default `30`).
   - Evict expired entries lazily on each `is_duplicate` or `record` call.

3. Implement `services/aggregator/src/aggregator/state.py`:
   - `AggregatorState` dataclass: `last_weather: WeatherConditions | None`, `last_calendar: CalendarState | None`.
   - Update methods: `update_weather(w: WeatherConditions)`, `update_calendar(c: CalendarState)`.
   - `to_dict()` method that serializes state for the `/internal/state` response.

4. Implement `services/aggregator/src/aggregator/router.py`:
   - `async def route_event(event: InternalEventRequest, state: AggregatorState, queue: TickerQueue, dedup: DedupCache) -> None`
   - If `event_type == "doorbell-interrupt"`: immediately call `dispatch_command_to_transport` with `priority=99` before returning. Log `doorbell_routed`. Do NOT enqueue in the ticker queue.
   - If `event_type == "ticker"`: compute `dedup_hash = sha256(source + canonical_payload_str)`, check dedup, enqueue if not duplicate. Log `ticker_enqueued` or `ticker_dropped_dedup`.
   - If `event_type == "weather-update"`: update `state.last_weather`. The transport adapter push for weather/calendar is done by the drain loop after state update.
   - If `event_type == "calendar-update"`: update `state.last_calendar`. Same as above.
   - Design note: doorbell bypasses the queue entirely and is dispatched inline. This is the key priority invariant.

5. Implement `services/aggregator/src/aggregator/drain.py`:
   - `async def ticker_drain_loop(queue: TickerQueue, transport_url: str) -> None`
   - Runs as an `asyncio` background task.
   - Loop body: `await asyncio.sleep(TICKER_DRAIN_INTERVAL_SECONDS)` (default `1`), then `dequeue_non_expired()`, then if event available call `dispatch_command_to_transport` with TICKER-APPEND command.
   - Does not drain weather or calendar updates — those are pushed inline on receipt (see routes below).

6. Implement `services/aggregator/src/aggregator/transport_client.py`:
   - `async def dispatch_command_to_transport(cmd: str, priority: int, payload: dict, transport_url: str) -> None`
   - HTTP POST to `TRANSPORT_ADAPTER_URL/internal/commands` using `httpx.AsyncClient` with 5-second timeout.
   - On failure: log ERROR, do not raise.

7. Implement `services/aggregator/src/aggregator/routes.py`:
   - `POST /internal/events`: parse `InternalEventRequest`, call `route_event`. For weather and calendar updates, also immediately call `dispatch_command_to_transport` so the display updates without waiting for the drain loop (transport adapter queues it normally). Return 202.
   - `GET /internal/state`: return serialized `AggregatorState` plus `ticker_queue` snapshot.
   - `GET /internal/health`: return queue depth, last-event timestamps per source.
   - `GET /healthz`: return `{"status": "ok"}`.

8. Implement `services/aggregator/src/aggregator/main.py`:
   - Create FastAPI `app`, include routes, and on startup launch `ticker_drain_loop` as an `asyncio` background task using `asyncio.create_task`.

9. Implement tests in `services/aggregator/tests/`:
   - `test_queue.py`: Test enqueue, dequeue, TTL expiry, maxlen overflow drop, snapshot.
   - `test_dedup.py`: Test duplicate detection within window, expiry past window, eviction.
   - `test_router.py`: Test doorbell routes inline (mock transport client), ticker events enqueue, weather/calendar update state cache, dedup rejection.
   - `test_drain.py`: Test that the drain loop calls `dispatch_command_to_transport` for non-expired events and skips expired ones.

**Verification:**
- `cd services/aggregator && python3 -m pytest tests/ -v` must pass all tests with zero failures.
- Manually start the aggregator and post a doorbell event; check logs show `doorbell_routed` log entry.
- Manually post 25 ticker events; check logs show `ticker_dropped_overflow` for the oldest 5.
- Post the same ticker event twice within 30 seconds; check logs show `ticker_dropped_dedup` on the second post.
- `grep -r "ring\|Ring\|unifi\|UniFi" services/aggregator/src/` must return zero matches (aggregator must contain no source-specific code paths, per REQ-AGG-005).

**Dependencies:** TASK-003 (shared types and logging)

**Risk:** Medium — the asyncio concurrency model (single event loop, asyncio.Lock on shared deque) must be implemented correctly. The doorbell inline-dispatch-before-return is the key invariant; a bug here violates the 2-second SLA.

---

### TASK-008 — Google ADC Secret (K8s Secret)

**Recommended Mode:** executor

**Objective:** Mount the Google ADC credentials file into the `housepanel` namespace as a K8s Secret named `google-adc` so calendar and weather pollers can authenticate with Google APIs.

**Requirements:** REQ-CAL-004, REQ-WTH-006, REQ-DAT-006, REQ-SEC-004, REQ-SEC-005

**Write Lease:**
```
^k8s/secrets-google-adc\.yaml$
```

**Change Budget:**
- max_files: 1
- max_new_symbols: 0
- interface_policy: new_interface

**Steps:**

1. Verify the credentials file exists and is readable:
   ```
   test -f /home/kwehden/.config/gcloud/application_default_credentials.json && echo "exists"
   ```
   If the file is missing, stop and alert the user.

2. Create the K8s Secret from the file:
   ```
   kubectl create secret generic google-adc \
     --namespace housepanel \
     --from-file=application_default_credentials.json=/home/kwehden/.config/gcloud/application_default_credentials.json
   ```

3. Create `k8s/secrets-google-adc.yaml` as a template only (no real content):
   ```yaml
   # Template — do not commit real credentials.
   # Apply with: kubectl create secret generic google-adc --namespace housepanel \
   #   --from-file=application_default_credentials.json=/home/kwehden/.config/gcloud/application_default_credentials.json
   ```

4. Add the template to ensure `.gitignore` excludes any file matching `*credentials*` or `*adc*` in the `k8s/` directory if real content might be added.

**Verification:**
- `kubectl get secret google-adc -n housepanel` must show the secret exists.
- `kubectl get secret google-adc -n housepanel -o jsonpath='{.data.application_default_credentials\.json}' | base64 -d | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['type'])"` must print `authorized_user`.

**Rollback:**
```
kubectl delete secret google-adc -n housepanel
```

**Dependencies:** TASK-002 (namespace must exist)

**Risk:** Low — read-only operation on an existing file; secret stored in cluster only.

---

### TASK-009 — Calendar Poller Service Implementation

**Recommended Mode:** executor

**Objective:** Implement the APScheduler-based calendar poller that polls Google Calendar API every 5 minutes (configurable) and pushes `calendar-update` events to the aggregator, with error retention of the last successful result.

**Requirements:** REQ-CAL-001, REQ-CAL-002, REQ-CAL-003, REQ-CAL-004, REQ-ERR-001, REQ-PER-003, REQ-SEC-002, REQ-SEC-003, REQ-OBS-001, REQ-OBS-003, REQ-CPL-001, REQ-CPL-002

**Write Lease:**
```
^services/calendar-poller/src/.*$
^services/calendar-poller/tests/.*$
```

**Change Budget:**
- max_files: 8
- max_new_symbols: 10 (GoogleCalendarClient, poll_google_calendar, push_calendar_update, CalendarPollerState, healthz handler, schedule setup, and their test counterparts)
- interface_policy: new_interface

**Steps:**

1. Implement `services/calendar-poller/src/calendar_poller/calendar_client.py`:
   - `GoogleCalendarClient` class.
   - Constructor: authenticates using `google-auth` with ADC credentials. The `GOOGLE_APPLICATION_CREDENTIALS` env var must point to the mounted JSON file path. The `GOOGLE_CALENDAR_ID` env var specifies the target calendar.
   - Method `fetch_events(time_min: datetime, time_max: datetime) -> list[CalendarEvent]`.
   - Timeout: 10 seconds per API call.
   - On error: raise a typed exception `CalendarAPIError(http_status: int, message: str)`.
   - Must not log `GOOGLE_CALENDAR_ID` or any event `summary` text. Log only event count.

2. Implement `services/calendar-poller/src/calendar_poller/poller.py`:
   - `async def poll_google_calendar(client: GoogleCalendarClient, state: CalendarPollerState, aggregator_url: str) -> None`
   - Fetches events for the next 7 days from now.
   - On success: update `state.last_events`; call `push_calendar_update`.
   - On `CalendarAPIError`: log `poll_error` with `http_status_code` and error message; retain `state.last_events` (do not clear).
   - Log `poll_started` at the beginning; `poll_success` with `event_count` and `poll_duration_ms` on success.

3. Implement `services/calendar-poller/src/calendar_poller/pusher.py`:
   - `async def push_calendar_update(events: list[CalendarEvent], aggregator_url: str) -> None`
   - HTTP POST to `AGGREGATOR_URL/internal/events` with a `calendar-update` event.
   - Timeout: 5 seconds. On failure: log ERROR.

4. Implement `services/calendar-poller/src/calendar_poller/main.py`:
   - Configure APScheduler with an `AsyncIOScheduler`.
   - Schedule `poll_google_calendar` every `CALENDAR_POLL_INTERVAL_SECONDS` seconds (default `300`).
   - Add a FastAPI `GET /healthz` endpoint returning `{"status": "ok", "last_poll_timestamp": ..., "last_poll_event_count": ...}`.
   - Start the scheduler on FastAPI lifespan startup.

5. Implement tests in `services/calendar-poller/tests/`:
   - `test_poller.py`: Mock `GoogleCalendarClient` to return events; assert `push_calendar_update` is called with correct payload. Mock client to raise `CalendarAPIError`; assert `state.last_events` is retained and error is logged.
   - `test_calendar_client.py`: Unit test authentication configuration (mock `google.auth`); confirm timeout is set; confirm summary is not logged.

**Verification:**
- `cd services/calendar-poller && python3 -m pytest tests/ -v` must pass.
- Deploy to `laminarflow` (after TASK-022/TASK-024) and run `kubectl logs -n housepanel deployment/housepanel-calendar-poller --since=10m | grep poll_success` — should show poll cycles running.
- Confirm no log lines contain calendar event summary text: `kubectl logs ... | grep -v "poll_success\|poll_started\|poll_error" | grep -i "summary\|event_title"` must be empty.

**Dependencies:** TASK-003 (shared types), TASK-007 (aggregator endpoint must exist for integration), TASK-008 (Google ADC secret for deployment)

**Risk:** Medium — Google Calendar API authentication via ADC requires the mounted credentials file path and the `GOOGLE_APPLICATION_CREDENTIALS` env var to be set correctly. Token refresh is automatic via `google-auth` but must be confirmed in integration testing.

---

### TASK-010 — Weather Poller Service Implementation

**Recommended Mode:** executor

**Objective:** Implement the weather poller with a swappable `WeatherAdapter` protocol, Google Weather API primary adapter, OpenWeatherMap fallback adapter, and automatic fallback on primary failure.

**Requirements:** REQ-WTH-001, REQ-WTH-002, REQ-WTH-003, REQ-WTH-004, REQ-WTH-005, REQ-ERR-002, REQ-PER-004, REQ-SEC-002, REQ-OBS-001, REQ-OBS-004, REQ-DAT-005, REQ-BCK-004

**Write Lease:**
```
^services/weather-poller/src/.*$
^services/weather-poller/tests/.*$
```

**Change Budget:**
- max_files: 10
- max_new_symbols: 14 (WeatherAdapter Protocol, WeatherConditions, GoogleWeatherAdapter, OpenWeatherMapAdapter, resolve_active_adapter, poll_weather, push_weather_update, WeatherPollerState, fallback logic, healthz handler, and their test counterparts)
- interface_policy: new_interface

**Steps:**

1. Implement `services/weather-poller/src/weather_poller/adapter.py`:
   - Define `WeatherAdapter` as a Python `typing.Protocol`:
     ```python
     class WeatherAdapter(Protocol):
         provider_name: str
         def fetch_current(self) -> WeatherConditions: ...
     ```
   - Import `WeatherConditions` from `services/shared/models.py`.

2. Implement `services/weather-poller/src/weather_poller/adapters/google.py`:
   - `GoogleWeatherAdapter(WeatherAdapter)`:
     - `provider_name = "google-weather"`
     - `fetch_current()`: HTTP GET to `https://weather.googleapis.com/v1/weather` using `httpx` with `GOOGLE_WEATHER_API_KEY` and location. 10-second timeout.
     - Parse response into `WeatherConditions`. Map Google API fields to the canonical fields.
     - On HTTP error: raise `WeatherAPIError(provider="google-weather", http_status=..., message=...)`.

3. Implement `services/weather-poller/src/weather_poller/adapters/openweathermap.py`:
   - `OpenWeatherMapAdapter(WeatherAdapter)`:
     - `provider_name = "openweathermap"`
     - `fetch_current()`: HTTP GET to `https://api.openweathermap.org/data/2.5/weather` using `httpx` with `OPENWEATHERMAP_API_KEY` and `OPENWEATHERMAP_LOCATION`. 10-second timeout.
     - Parse response into `WeatherConditions`.
     - On HTTP error: raise `WeatherAPIError`.

4. Implement `services/weather-poller/src/weather_poller/poller.py`:
   - `async def poll_weather(primary: WeatherAdapter, fallback: WeatherAdapter, state: WeatherPollerState, aggregator_url: str) -> None`
   - Try primary. If `WeatherAPIError`: log `poll_error` for primary; log `fallback_triggered`; try fallback.
   - If fallback also raises `WeatherAPIError`: log `poll_error` for fallback; retain `state.last_weather`. Do not clear.
   - On any success: call `push_weather_update`.
   - Log `poll_started` with `provider` and `interval_seconds` at the beginning of each cycle.
   - The `WEATHER_PRIMARY_PROVIDER` env var (default `google`) determines which adapter is primary. If set to `openweathermap`, swap the order.

5. Implement `services/weather-poller/src/weather_poller/pusher.py` and `main.py` following the same pattern as the calendar poller. APScheduler, `WEATHER_POLL_INTERVAL_SECONDS` default `900`, healthz endpoint.

6. Implement tests in `services/weather-poller/tests/`:
   - `test_adapter_protocol.py`: Confirm both adapters satisfy the `WeatherAdapter` protocol using `isinstance(adapter, WeatherAdapter)` or structural check.
   - `test_poller.py`: Mock primary to succeed; assert push called. Mock primary to fail; assert fallback called and push called. Mock both to fail; assert state retained and error logged.
   - `test_adapters.py`: Mock `httpx` responses to test field mapping for both adapters.

**Verification:**
- `cd services/weather-poller && python3 -m pytest tests/ -v` must pass.
- Run `python3 -c "from weather_poller.adapters.google import GoogleWeatherAdapter; from weather_poller.adapter import WeatherAdapter; ..."` and confirm structural type check passes.
- Confirm `WEATHER_PRIMARY_PROVIDER=openweathermap` causes the OpenWeatherMap adapter to be tried first in test.

**Dependencies:** TASK-003 (shared types), TASK-007 (aggregator endpoint)

**Risk:** Medium — the Google Weather API (`https://weather.googleapis.com/v1/weather`) was announced in 2024; the exact response schema and quota tier require confirmation during implementation. If the endpoint is inaccessible, the executor must implement the fallback path and flag this for user review before closing the task.

---

### TASK-011 — ArduinoTempHumUbuntu Inbound Webhook Schema (HousePanel Side Only)

**Recommended Mode:** executor

**Objective:** Publish the stable `POST /v1/webhooks/system-alert` JSON schema as a machine-readable file so the `ArduinoTempHumUbuntu` sibling repo can implement the push side against a fixed contract.

**Requirements:** REQ-WHR-002, REQ-WHR-005, REQ-DAT-004, REQ-BCK-001

**Write Lease:**
```
^spec/schemas/system-alert-webhook-v1\.json$
```

**Change Budget:**
- max_files: 1
- max_new_symbols: 0 (schema artifact, not code)
- interface_policy: new_interface

**Steps:**

1. Create `spec/schemas/system-alert-webhook-v1.json` containing the complete JSON Schema (draft-07) for the `POST /v1/webhooks/system-alert` body, exactly matching the design document's field definitions:
   - Required fields: `schema_version` (const `"1"`), `source` (const `"arduino-temp-hum-ubuntu"`), `host_id` (string), `timestamp` (ISO8601), `alert_type` (enum: `temperature | humidity | system | network`), `severity` (enum: `info | warning | critical`), `message` (string, maxLength 200).
   - Optional fields: `temperature_c` (number or null), `humidity_pct` (number or null).
   - Include `$schema`, `$id`, `title`, `description`, and an `examples` array with one valid example.
   - Description must state: "HousePanel owns this contract. The `ArduinoTempHumUbuntu` repo implements against it. Breaking changes are introduced as `/v2/` path variants."

2. Update `spec/schemas/README.txt` to include the system-alert endpoint alongside the camera endpoint.

**Verification:**
- `python3 -c "import json; json.load(open('spec/schemas/system-alert-webhook-v1.json'))"` must succeed.
- Validate as JSON Schema draft-07 (same command as TASK-004).
- Cross-check that all field names and enum values in the JSON Schema exactly match the Pydantic model in `services/webhook-receiver/src/webhook_receiver/schemas.py` `SystemAlertWebhookPayloadV1`. Any mismatch is a contract violation.

**Dependencies:** TASK-003 (to confirm Pydantic model fields match schema), TASK-005 (schema must match the actual Pydantic model)

**Risk:** Low — static schema document; the main risk is a mismatch between this schema and the Pydantic model implemented in TASK-005, which the verification step catches.

---

### TASK-012 — Ring Refresh Token Acquisition (Interactive)

**Recommended Mode:** executor

**INTERACTIVE TASK — USER PRESENCE REQUIRED**

This task cannot be automated. It requires the user to supply Ring account credentials interactively. Do not proceed past step 1 without confirming user is present.

**Objective:** Obtain a Ring refresh token via `python-ring-doorbell`'s interactive 2FA auth flow and store it as a K8s Secret.

**Requirements:** REQ-RNG-001, REQ-SEC-004

**Write Lease:**
```
^services/ring-integration/scripts/get_token\.py$
^k8s/secrets-ring\.yaml$
```

**Change Budget:**
- max_files: 2
- max_new_symbols: 1 (the token script)
- interface_policy: new_interface

**Steps:**

1. Confirm user is present and ready to supply Ring credentials. Do not proceed if unattended.

2. Create `services/ring-integration/scripts/get_token.py`:
   - A standalone Python script using `ring_doorbell` to run the interactive auth flow.
   - Prompts for Ring email and password (via `getpass` — do not echo password).
   - Catches `Requires2FAError` and re-prompts for the OTP code.
   - Prints only the resulting refresh token to stdout (nothing else).
   - Example skeleton:
     ```python
     from ring_doorbell import Auth, Requires2FAError
     import getpass, asyncio

     async def main():
         email = input("Ring email: ")
         password = getpass.getpass("Ring password: ")
         auth = Auth("HousePanel/0.1", None, lambda token: None)
         try:
             await auth.async_fetch_token(email, password)
         except Requires2FAError:
             otp = input("2FA code: ")
             await auth.async_fetch_token(email, password, otp)
         print(auth.token["refresh_token"])

     asyncio.run(main())
     ```

3. Install the library in the service venv and run interactively:
   ```
   cd services/ring-integration && pip install "ring_doorbell[listen]"
   python scripts/get_token.py
   ```
   Follow prompts. The script outputs the refresh token to stdout. Copy the token.

4. Store the refresh token as a K8s Secret:
   ```
   kubectl create secret generic housepanel-ring-secrets \
     --namespace housepanel \
     --from-literal=RING_REFRESH_TOKEN=<token-from-step-4>
   ```

6. Create `k8s/secrets-ring.yaml` as a template (no real value):
   ```yaml
   # Template — do not commit real token.
   # Apply with: kubectl create secret generic housepanel-ring-secrets ...
   # See TASK-012 in spec/tasks.md for the procedure.
   apiVersion: v1
   kind: Secret
   metadata:
     name: housepanel-ring-secrets
     namespace: housepanel
   type: Opaque
   stringData:
     RING_REFRESH_TOKEN: "<REPLACE_WITH_TOKEN_FROM_RING_AUTH_FLOW>"
   ```

7. Delete or zero the local copy of the refresh token from the terminal session.

**Verification:**
- `kubectl get secret housepanel-ring-secrets -n housepanel` must exist.
- `kubectl get secret housepanel-ring-secrets -n housepanel -o jsonpath='{.data.RING_REFRESH_TOKEN}' | base64 -d | wc -c` must return a non-zero character count.
- In TASK-013 step 6, the Ring integration service startup will confirm the token is valid by connecting to Ring cloud successfully.

**Rollback:**
```
kubectl delete secret housepanel-ring-secrets -n housepanel
```

**Dependencies:** TASK-002 (namespace must exist). This task is independent of all implementation tasks and can run at any time the user is available.

**Risk:** High — requires live Ring account credentials; two-factor auth may complicate the flow. The refresh token has a long lifetime but will expire eventually and must be re-acquired when it does. The token script must not persist credentials anywhere other than the K8s Secret.

---

### TASK-013 — Ring Integration Backend Implementation

**Recommended Mode:** executor

**Objective:** Implement the `python-ring-doorbell` service that subscribes to Ring doorbell ding events, normalizes them into the HousePanel `UnifiedEvent` format, and forwards them to the aggregator as `doorbell-interrupt` events.

**Requirements:** REQ-RNG-001, REQ-RNG-002, REQ-RNG-004, REQ-RNG-005, REQ-ART-002, REQ-AGG-002, REQ-AGG-005, REQ-SEC-002, REQ-OBS-001, REQ-OBS-005

**Write Lease:**
```
^services/ring-integration/src/.*$
^services/ring-integration/tests/.*$
^services/ring-integration/pyproject\.toml$
^services/ring-integration/requirements\.txt$
```

**Change Budget:**
- max_files: 8
- max_new_symbols: 8 (init_ring_client, subscribe_to_doorbell_events, normalize_ring_event, forward_to_aggregator, persist_token, healthz FastAPI endpoint, and test equivalents)
- interface_policy: new_interface

**Steps:**

1. Implement `services/ring-integration/src/ring_integration/client.py`:
   - `async def init_ring_client(refresh_token: str, on_token_updated: Callable) -> tuple[Auth, Ring]`
     - Creates `Auth("HousePanel/0.1", token_dict, on_token_updated)` where `token_dict` is `{"refresh_token": refresh_token}`.
     - Calls `await ring.async_update_data()` to verify connectivity.
     - Must not log the refresh token value.
   - `async def subscribe_to_doorbell_events(ring: Ring, on_ding: Callable) -> None`
     - Iterates `ring.video_doorbells`; subscribes `on_ding` to each device's `on_ding` observable.
     - Logs `ring_subscribed` with device count.

2. Implement `services/ring-integration/src/ring_integration/token_manager.py`:
   - `def token_updated_callback(token: dict) -> None`
     - Receives the new token dict on every Ring auth refresh.
     - Writes `token["refresh_token"]` back to the `housepanel-ring-secrets` K8s Secret using the in-cluster K8s API (`kubernetes` client library).
     - Logs `ring_token_refreshed` (no token value in log). Never logs token value.
   - This is the critical token persistence mechanism — if omitted, the service locks itself out on restart.

3. Implement `services/ring-integration/src/ring_integration/normalizer.py`:
   - `def normalize_ring_event(device, ding_event) -> dict` — returns a dict matching `POST /internal/events`:
     ```json
     {
       "source": "ring",
       "event_type": "doorbell-interrupt",
       "timestamp": "<ISO8601>",
       "priority": 99,
       "payload": {
         "device_id": "<ring device id>",
         "device_name": "<ring device name>",
         "event_id": "<uuid>"
       }
     }
     ```

4. Implement `services/ring-integration/src/ring_integration/main.py` (FastAPI app):
   - Startup: read `RING_REFRESH_TOKEN`, `AGGREGATOR_URL`, `LOG_LEVEL` from env.
   - Call `init_ring_client` with `token_updated_callback`, then `subscribe_to_doorbell_events`.
   - On each ding: call `normalize_ring_event`, then HTTP POST to aggregator (`httpx` async client, 5s timeout). Log `event_forwarded` with `event_id`.
   - `GET /healthz` returns `{"status": "ok", "ring_connected": bool, "last_event_timestamp": str|None}`.

5. Implement `tests/`:
   - `test_normalizer.py`: Test `normalize_ring_event` with mock ding data; assert all output fields present and correctly typed.
   - `test_forwarder.py`: Mock `httpx.AsyncClient`; test successful forward; test failure logging without raise.

**Verification:**
- `cd services/ring-integration && python -m pytest tests/ -v` must pass.
- Deploy (TASK-025). `kubectl logs -n housepanel deployment/housepanel-ring-integration` must show `ring_subscribed`.
- Press Ring doorbell; within 5 seconds both `doorbell_event_received` (ring-integration log) and `doorbell_routed` (aggregator log) must appear.

**Dependencies:** TASK-003 (interface contract for event structure), TASK-007 (aggregator /internal/events endpoint), TASK-012 (Ring refresh token must be in K8s Secret before deployment)

**Risk:** High — depends on Ring cloud API availability and the refresh token's validity. `python-ring-doorbell` is an unofficial library; Ring may change their API at any time. The 2-second SLA depends on Ring cloud WebSocket latency, which is outside HousePanel control. Token persistence via K8s API write is a new failure mode: if the in-cluster K8s client lacks RBAC permission to patch the Secret, the service will lose its token on next restart — RBAC permissions must be verified in TASK-002.

---

### TASK-014 — Ring K8s Secret Verification

**Recommended Mode:** executor

**Objective:** Confirm the `housepanel-ring-secrets` Secret created in TASK-012 is correctly structured and will mount properly into the ring-integration deployment.

**Requirements:** REQ-SEC-004, REQ-SEC-005

**Write Lease:**
```
^k8s/secrets-ring\.yaml$
```

**Change Budget:**
- max_files: 1
- max_new_symbols: 0
- interface_policy: extend_only

**Steps:**

1. Verify secret exists and has the correct key:
   ```
   kubectl get secret housepanel-ring-secrets -n housepanel -o yaml | grep "RING_REFRESH_TOKEN"
   ```

2. Test that the secret can be mounted as an env var in a test pod:
   ```
   kubectl run ring-secret-test --image=busybox --rm -it --restart=Never \
     --namespace=housepanel \
     --env-from=secret:housepanel-ring-secrets \
     -- sh -c 'echo "token_len=${#RING_REFRESH_TOKEN}"'
   ```
   The output must show a non-zero token length.

3. Ensure the template `k8s/secrets-ring.yaml` has no real token values (grep confirms).

**Verification:**
- Step 2 test pod must exit cleanly and print a non-zero `token_len`.
- `grep -r "RING_REFRESH_TOKEN" k8s/ | grep -v "REPLACE_WITH"` must return zero matches.

**Dependencies:** TASK-012

**Risk:** Low — read-only verification task.

---

### TASK-015 — Arduino Dev Environment Setup

**Recommended Mode:** executor

**Objective:** Set up the Arduino development environment on the host machine using `ardconfig` so firmware can be compiled and uploaded to the Giga.

**Requirements:** REQ-ART-003, REQ-BCK-002

**Write Lease:**
```
^firmware/.*\.md$
```

**Change Budget:**
- max_files: 1
- max_new_symbols: 0
- interface_policy: new_interface

**Steps:**

1. Confirm `ardconfig` is available:
   ```
   which ardconfig-setup || ls /home/kwehden/projects/ardconfig/bin/ardconfig-setup
   ```
   If not found, follow the `ardconfig` README to install it at `https://github.com/kwehden/ardconfig`.

2. Run the board setup for the Giga:
   ```
   bin/ardconfig-setup --boards giga
   ```
   This installs `arduino-cli` and the `arduino:mbed_giga` core.

3. Verify the environment:
   ```
   bin/ardconfig-health
   ```
   The output must indicate the `giga` board profile is healthy and `arduino-cli` is found.

4. Confirm the FQBN is registered:
   ```
   arduino-cli board listall | grep "arduino:mbed_giga:giga"
   ```
   Must return a result.

5. Install the `ArduinoHttpClient` library (needed for WebSocket client):
   ```
   arduino-cli lib install "ArduinoHttpClient"
   ```

6. Create `firmware/DEVENV.md` (a short operational note, not a user-facing doc) capturing:
   - FQBN: `arduino:mbed_giga:giga`
   - Compile command: `arduino-cli compile --fqbn arduino:mbed_giga:giga firmware/housepanel-giga/`
   - Upload command: `arduino-cli upload --fqbn arduino:mbed_giga:giga --port <PORT> firmware/housepanel-giga/`
   - Note: ardconfig is a host-side tool only; it provides no firmware code.

**Verification:**
- `arduino-cli compile --fqbn arduino:mbed_giga:giga firmware/housepanel-giga/` must succeed (empty sketch from TASK-001 compiles cleanly).
- `arduino-cli lib list | grep ArduinoHttpClient` must return a result.

**Dependencies:** TASK-001 (firmware sketch stub must exist)

**Risk:** Low — setup-only task using documented tooling. Risk: board core download requires internet access to Arduino's package index.

---

### TASK-016 — Arduino Transport Adapter Implementation

**Recommended Mode:** executor

**Objective:** Implement the FastAPI + websockets transport adapter that maintains the persistent WebSocket connection to the Giga, receives commands from the aggregator via `POST /internal/commands`, and dispatches them with interrupt-first priority ordering using two asyncio queues.

**Requirements:** REQ-ART-001, REQ-ART-002, REQ-ART-003, REQ-ART-004, REQ-ART-005, REQ-ART-006, REQ-ERR-005, REQ-OBS-001

**Write Lease:**
```
^services/transport-adapter/src/.*$
^services/transport-adapter/tests/.*$
```

**Change Budget:**
- max_files: 12
- max_new_symbols: 18 (interrupt_queue, normal_queue, ota_paused_flag, giga_connected_flag, giga_websocket_handler, ws_write_loop, handle_hello_frame, handle_ota_frame, request_state_refresh, CommandRequest, CommandFrame, healthz handler, internal_commands handler, internal_health handler, and their test counterparts)
- interface_policy: new_interface

**Steps:**

1. Implement `services/transport-adapter/src/transport_adapter/queues.py`:
   - `interrupt_queue: asyncio.Queue` — bounded, maxsize=50 (doorbell interrupts are rare; overflow would indicate a bug).
   - `normal_queue: asyncio.Queue` — bounded, maxsize=50.

2. Implement `services/transport-adapter/src/transport_adapter/ws_handler.py`:
   - `giga_websocket_handler(websocket: WebSocket) -> None` — FastAPI WebSocket endpoint handler.
   - On connect: set `giga_connected = True`; log `giga_connected`.
   - Receive first frame; if `cmd == "HELLO"`: call `handle_hello_frame(frame)`.
   - Receive subsequent frames in a loop:
     - `OTA-START`: set `ota_paused = True`; log `ota_start_received`; send `OTA-PAUSE` frame.
     - `OTA-END`: set `ota_paused = False`; log `ota_end_received`; call `handle_post_ota_refresh()`.
   - On disconnect: set `giga_connected = False`; log `giga_disconnected`.

3. Implement `services/transport-adapter/src/transport_adapter/ws_write_loop.py`:
   - `async def ws_write_loop(websocket: WebSocket) -> None`
   - Loop: check `interrupt_queue` first (non-blocking `get_nowait()`). If empty, try `normal_queue` with `asyncio.wait_for(normal_queue.get(), timeout=0.05)`.
   - If `ota_paused` is True: still drain `interrupt_queue` (DOORBELL commands are sent during OTA); skip `normal_queue`.
   - On `WebSocketDisconnect` or `ConnectionClosed`: exit loop.
   - Log `command_sent` with `cmd`, `message_id`, `priority`.

4. Implement `services/transport-adapter/src/transport_adapter/state_refresh.py`:
   - `async def handle_hello_frame(frame: dict) -> None`
   - Call `GET AGGREGATOR_URL/internal/state` using `httpx` (5-second timeout).
   - On success: enqueue `WEATHER-UPDATE` and `CALENDAR-UPDATE` commands in `normal_queue`; then enqueue all unexpired ticker events.
   - Log `state_refreshed` with `triggered_by="hello"`.

5. Implement `services/transport-adapter/src/transport_adapter/routes.py`:
   - `POST /internal/commands`: parse `CommandRequest`; if `priority == 99` (doorbell): put on `interrupt_queue`; else put on `normal_queue`. If Giga not connected: still enqueue (queued for reconnect). Return 202. If both queues are full: return 503 (only for non-interrupt commands — interrupt queue must never be blocked).
   - `GET /internal/health`: return `{"status": "ok", "giga_connected": <bool>, "interrupt_queue_depth": <int>, "normal_queue_depth": <int>}`.
   - `GET /healthz`: return `{"status": "ok"}`.
   - `WS /ws/panel`: upgrade to WebSocket; call `giga_websocket_handler`.

6. Implement `services/transport-adapter/src/transport_adapter/main.py`:
   - Create FastAPI `app`; include routes; on startup launch `ws_write_loop` as background task (note: the write loop is attached to the active WebSocket, so it should be started per-connection, not globally — design the lifecycle carefully).

7. Implement tests in `services/transport-adapter/tests/`:
   - `test_command_routing.py`: Assert doorbell commands go to `interrupt_queue`; ticker commands go to `normal_queue`.
   - `test_write_loop.py`: Mock WebSocket; assert interrupt queue is drained before normal queue; assert OTA pause blocks normal queue but not interrupt queue.
   - `test_hello_frame.py`: Mock aggregator state endpoint; assert correct frames are enqueued after HELLO.
   - `test_ota_protocol.py`: Simulate OTA-START, assert OTA-PAUSE sent; simulate OTA-END, assert state refresh triggered.

**Verification:**
- `cd services/transport-adapter && python3 -m pytest tests/ -v` must pass.
- Integration test: run a Python WebSocket simulator client (`websockets` library):
  1. Connect to the transport adapter's `ws://localhost:8002/ws/panel`.
  2. Send `{"cmd": "HELLO", "firmware_version": "test", "post_ota": false}`.
  3. Confirm the simulator receives `WEATHER-UPDATE` and `CALENDAR-UPDATE` frames (if aggregator has state) or receives nothing (if aggregator has no state yet — acceptable).
  4. Post `{"cmd": "DOORBELL", "priority": 99, ...}` to `POST /internal/commands`.
  5. Confirm the simulator receives `{"cmd": "DOORBELL", ...}` frame.
- Confirm that if both doorbell and ticker commands are queued simultaneously, doorbell frame arrives at simulator first.

**Dependencies:** TASK-003 (shared types), TASK-007 (aggregator `/internal/state` endpoint for state refresh)

**Risk:** Medium — asyncio two-queue write loop has a subtle timing dependency. The OTA-pause path must correctly block the normal queue while still sending doorbell frames. The `interrupt_queue`-first drain logic must be verified under simulated concurrent conditions.

---

### TASK-017 — Firmware: WiFi Initialization and WebSocket Connection

**Recommended Mode:** executor

**Objective:** Implement the Arduino Giga firmware WiFi initialization using `WiFi.h` and establish a persistent WebSocket client connection to the transport adapter using `ArduinoHttpClient`.

**Requirements:** REQ-ART-001, REQ-ART-003, REQ-BCK-002, REQ-ERR-005

**Write Lease:**
```
^firmware/housepanel-giga/housepanel-giga\.ino$
^firmware/housepanel-giga/config\.h$
^firmware/housepanel-giga/wifi_manager\.h$
^firmware/housepanel-giga/wifi_manager\.cpp$
^firmware/housepanel-giga/ws_client\.h$
^firmware/housepanel-giga/ws_client\.cpp$
```

**Change Budget:**
- max_files: 6
- max_new_symbols: 8 (wifi_connect, wifi_status_ok, ws_connect, ws_connected, ws_send_hello, ws_loop, WifiManager, WsClient)
- interface_policy: new_interface

**Steps:**

1. Populate `firmware/housepanel-giga/config.h`:
   - `SSID` — home Wi-Fi SSID (constant, not from external config; this is a home-only device).
   - `WIFI_PASS` — Wi-Fi password.
   - `TRANSPORT_ADAPTER_HOST` — IP address of the k3s node (use the NodePort-accessible IP from the 192.168.1.x subnet, e.g., `"192.168.1.205"`).
   - `TRANSPORT_ADAPTER_WS_PORT` — NodePort port number (filled in after TASK-025 creates the manifest).
   - `TRANSPORT_ADAPTER_WS_PATH` — `"/ws/panel"`.
   - `FIRMWARE_VERSION` — `"1.0.0"`.

2. Implement `firmware/housepanel-giga/wifi_manager.h` and `.cpp`:
   - `void wifi_connect()` — calls `WiFi.begin(SSID, WIFI_PASS)`. Retries in a loop until `WiFi.status() == WL_CONNECTED`.
   - `bool wifi_status_ok()` — returns `WiFi.status() == WL_CONNECTED`.
   - Include `<WiFi.h>` from the `arduino:mbed_giga` core.

3. Implement `firmware/housepanel-giga/ws_client.h` and `.cpp`:
   - Uses `ArduinoHttpClient` library: `#include <ArduinoHttpClient.h>`.
   - `WiFiClient wifi_client;`
   - `WebSocketClient ws(wifi_client, TRANSPORT_ADAPTER_HOST, TRANSPORT_ADAPTER_WS_PORT);`
   - `bool ws_connect()` — calls `ws.begin(TRANSPORT_ADAPTER_WS_PATH)`. Returns `true` on success.
   - `bool ws_connected()` — returns `ws.connected()`.
   - `void ws_send_hello(bool post_ota)` — sends `{"cmd": "HELLO", "firmware_version": "FIRMWARE_VERSION", "post_ota": <bool>}` as a WebSocket text frame.
   - `void ws_loop()` — polls `ws.parseMessage()`; returns immediately if no message available.

4. Update `firmware/housepanel-giga/housepanel-giga.ino`:
   - `setup()`: call `wifi_connect()`, then `ws_connect()`, then `ws_send_hello(false)`.
   - `loop()`: if `!wifi_status_ok()`, call `wifi_connect()`; if `!ws_connected()`, call `ws_connect()` then `ws_send_hello(false)`; call `ws_loop()`.
   - Add a 100ms `delay()` at the bottom of `loop()` to prevent busy-spinning.

**Verification:**
- `arduino-cli compile --fqbn arduino:mbed_giga:giga firmware/housepanel-giga/` must succeed with zero compilation errors.
- Flash to the Giga:
  ```
  arduino-cli upload --fqbn arduino:mbed_giga:giga --port <PORT> firmware/housepanel-giga/
  ```
- Open serial monitor (`arduino-cli monitor --port <PORT>`): confirm no error output and the board is not stuck in a crash loop.
- Check transport adapter logs: `kubectl logs -n housepanel deployment/housepanel-transport-adapter | grep giga_connected` must show a new connection event. (Requires transport adapter deployed per TASK-025.)
- If transport adapter is not yet deployed: run transport adapter locally (`uvicorn transport_adapter.main:app --port 8002`) and confirm the Giga connects.

**Dependencies:** TASK-001 (sketch stub), TASK-015 (dev env), TASK-016 (transport adapter must be running for end-to-end test)

**Risk:** Medium — WiFi and WebSocket initialization code is hardware-dependent. The `ArduinoHttpClient` WebSocket API must be verified against the installed library version. If `ArduinoHttpClient` WebSocket proves incompatible with the Giga's MbedOS networking stack, fall back to `arduinoWebSockets` (Links2004) library as specified in the design.

---

### TASK-018 — Firmware: Command Frame Parser

**Recommended Mode:** executor

**Objective:** Implement JSON command frame parsing in the Giga firmware to decode `DOORBELL`, `TICKER-APPEND`, `WEATHER-UPDATE`, and `CALENDAR-UPDATE` frames received from the transport adapter.

**Requirements:** REQ-ART-001, REQ-ART-002, REQ-DIS-002, REQ-DIS-009

**Write Lease:**
```
^firmware/housepanel-giga/command_parser\.h$
^firmware/housepanel-giga/command_parser\.cpp$
^firmware/housepanel-giga/housepanel-giga\.ino$
```

**Change Budget:**
- max_files: 3
- max_new_symbols: 8 (CommandType enum, CommandFrame struct, parse_command_frame, command_type_from_string, and field accessors)
- interface_policy: extend_only

**Steps:**

1. Add `ArduinoJson` to the firmware dependencies:
   ```
   arduino-cli lib install "ArduinoJson"
   ```

2. Implement `firmware/housepanel-giga/command_parser.h` and `.cpp`:
   - `enum class CommandType { DOORBELL, TICKER_APPEND, WEATHER_UPDATE, CALENDAR_UPDATE, OTA_PAUSE, OTA_RESUME, UNKNOWN }`.
   - `struct CommandFrame { CommandType type; char message_id[37]; /* UUID4 string */`... field unions or separate structs per command type: `timeout_seconds` for DOORBELL; `text[256]` and `ttl_seconds` for TICKER_APPEND; `temperature_c`, `conditions[64]`, `humidity_pct`, `wind_speed_ms` for WEATHER_UPDATE; `events_json[2048]` for CALENDAR_UPDATE. `}`.
   - `CommandType command_type_from_string(const char* cmd)` — maps string to enum.
   - `bool parse_command_frame(const String& raw_json, CommandFrame& out)` — uses `ArduinoJson`'s `deserializeJson`; populates `out`. Returns `false` on parse failure.

3. Integrate into `ws_client.cpp` `ws_loop()`:
   - After `ws.parseMessage()` succeeds, call `parse_command_frame(ws.readString(), frame)`.
   - If `frame.type == CommandType::DOORBELL`: set a global `doorbell_pending = true` and store the frame.
   - Otherwise: enqueue the frame in a global `CommandQueue` (simple circular buffer of `CommandFrame`, capacity 10).

4. Update `housepanel-giga.ino`'s `loop()` to read from the `CommandQueue` and dispatch to display handlers (stubbed for now — display rendering is TASK-019).

**Verification:**
- `arduino-cli compile --fqbn arduino:mbed_giga:giga firmware/housepanel-giga/` must succeed with zero errors.
- Unit test the parser logic on the host (not on hardware) using a desktop Arduino-compatible test harness if available, or manually validate JSON parsing by running a serial loopback test: send a JSON frame over serial and confirm the correct `CommandType` is parsed.

**Dependencies:** TASK-017 (WiFi + WebSocket foundation), TASK-015 (dev env)

**Risk:** Low-Medium — `ArduinoJson` is a mature library. The main risk is memory: the Giga has 1MB SRAM; the `CommandFrame` struct must fit comfortably. The `events_json[2048]` field for calendar events is the largest; confirm it does not cause stack overflow in tests.

---

### TASK-019 — Firmware: Display Rendering Logic

**Recommended Mode:** executor

**Objective:** Implement display rendering handlers in the Giga firmware for all four display states: daily view (weather + calendar + ticker), doorbell full-screen interrupt, and state transitions, using the Gigashield display API.

**Requirements:** REQ-DIS-001, REQ-DIS-002, REQ-DIS-003, REQ-DIS-004, REQ-DIS-005, REQ-DIS-006, REQ-DIS-007, REQ-DIS-008, REQ-DIS-009

**Write Lease:**
```
^firmware/housepanel-giga/display\.h$
^firmware/housepanel-giga/display\.cpp$
^firmware/housepanel-giga/housepanel-giga\.ino$
```

**Change Budget:**
- max_files: 3
- max_new_symbols: 12 (DisplayState enum, render_daily_view, render_doorbell_interrupt, render_weather_section, render_calendar_section, ticker_append, ticker_advance, dismiss_doorbell, display_init, and state transition helpers)
- interface_policy: extend_only

**Steps:**

1. Display library stack is confirmed — no research needed:
   - **Hardware layer:** `Arduino_H7_Video` (drives the Gigashield ASX00039 display hardware on the STM32H7)
   - **UI abstraction layer:** `LVGL` (Light and Versatile Graphics Library) — use LVGL widgets and styles for all rendering
   - Arduino library deps to declare: `Arduino_H7_Video`, `lvgl`
   - LVGL `lv_init()` and display driver registration must happen in `display_init()` before any widget calls

2. Implement `firmware/housepanel-giga/display.h` and `.cpp`:
   - `void display_init()` — initializes `Arduino_H7_Video`, registers the LVGL display driver, calls `lv_init()`.
   - `enum class DisplayState { DAILY_VIEW, DOORBELL_INTERRUPT }`.
   - `void render_daily_view(const char* weather_text, const char* calendar_text)` — clears screen; renders weather section (top area), calendar section (middle area), ticker area (bottom).
   - `void render_doorbell_interrupt(int timeout_seconds)` — fills screen with a high-visibility color (e.g., red); renders doorbell message and countdown.
   - `void render_weather_section(float temp_c, const char* conditions)` — renders into the weather region.
   - `void render_calendar_section(const char* events_text)` — renders into the calendar region.
   - `void ticker_append(const char* text)` — adds text to the scrolling ticker buffer.
   - `void ticker_advance()` — advances the ticker scroll position; called periodically from `loop()`.
   - `void dismiss_doorbell()` — transitions display back to daily view.

3. Implement the doorbell interrupt priority invariant in `housepanel-giga.ino`:
   - After each `ws_loop()` call, check `doorbell_pending`.
   - If `doorbell_pending == true`: call `render_doorbell_interrupt(frame.timeout_seconds)`; set a timer for `DOORBELL_TIMEOUT_SECONDS`; clear `doorbell_pending`.
   - WHILE doorbell is displayed: still receive WebSocket frames (keep calling `ws_loop()`) and buffer any incoming commands. Do NOT render ticker or calendar updates until doorbell is dismissed.
   - On timeout: call `dismiss_doorbell()`.

4. In `loop()`: call `ticker_advance()` every loop iteration (with appropriate timing) regardless of display state — but only render ticker text when in DAILY_VIEW state.

**Verification:**
- `arduino-cli compile --fqbn arduino:mbed_giga:giga firmware/housepanel-giga/` must succeed.
- Flash to hardware. Manually trigger a doorbell event from the backend (post a doorbell command to `/internal/commands` on the transport adapter). Confirm the display switches to a full-screen red/alert view.
- Confirm the display returns to daily view after `DOORBELL_TIMEOUT_SECONDS` (30 seconds default).
- Confirm ticker text scrolls in the bottom band during daily view.

**Dependencies:** TASK-018 (command frame parser must be integrated first), TASK-015 (dev env)

**Risk:** Medium — display library stack confirmed (Arduino_H7_Video + LVGL). Requires physical Giga + Gigashield hardware for verification. The doorbell-during-daily-view preemption is the highest-risk correctness invariant in the firmware; test this path explicitly before marking complete.

---

### TASK-020 — Firmware: OTA Protocol Handling

**Recommended Mode:** executor

**Objective:** Implement the firmware side of the OTA pause protocol: detect `ardconfig`-initiated OTA by sending `OTA-START` on upload detection, receive `OTA-PAUSE` acknowledgement, and resume on `OTA-END` / reconnect with `post_ota: true`.

**Requirements:** REQ-DIS-008, REQ-ART-004, REQ-ERR-006

**Write Lease:**
```
^firmware/housepanel-giga/ota_protocol\.h$
^firmware/housepanel-giga/ota_protocol\.cpp$
^firmware/housepanel-giga/housepanel-giga\.ino$
```

**Change Budget:**
- max_files: 3
- max_new_symbols: 5 (ota_detect_start, ota_send_start_frame, ota_in_progress flag, ota_send_end_frame, post_ota_flag)
- interface_policy: extend_only

**Steps:**

1. Research how `ardconfig` initiates OTA on the Giga:
   - Per the design: ardconfig uses `arduino-cli upload` from the host side (USB or network). The firmware does not control OTA initiation.
   - The firmware can detect an incoming upload by monitoring a specific pin state or by detecting a serial port reset (typical for `arduino-cli upload` over USB). Review `arduino:mbed_giga` core documentation for upload detection hooks.
   - If no detection hook exists: implement `OTA-START` frame as a best-effort signal sent before Arduino core resets for upload (use `Serial.begin()` hook or `mbed::mbed_event_queue()` if available).

2. Implement `firmware/housepanel-giga/ota_protocol.h` and `.cpp`:
   - `bool ota_in_progress = false`
   - `bool post_ota_flag = false` — set to `true` after OTA completes; read by `setup()` to pass `post_ota: true` in the HELLO frame.
   - `void ota_detect_start()` — if upload detected: set `ota_in_progress = true`; send `{"cmd": "OTA-START"}` over WebSocket; wait for `OTA-PAUSE` acknowledgement.
   - `void ota_send_end_frame()` — if OTA completes cleanly: send `{"cmd": "OTA-END"}`; set `post_ota_flag = true`.
   - Note: in practice, the firmware reboots after OTA; the `post_ota_flag` must be stored in retained RAM or EEPROM to survive the reboot, OR the approach relies on the `post_ota: true` field in the HELLO frame that `setup()` sends on restart.

3. Update `housepanel-giga.ino` `setup()`:
   - Read `post_ota_flag` from retained storage; if set, call `ws_send_hello(true)`; clear the flag.

4. Update `loop()`:
   - Call `ota_detect_start()` if applicable.

**Verification:**
- `arduino-cli compile --fqbn arduino:mbed_giga:giga firmware/housepanel-giga/` must succeed.
- Trigger an `ardconfig` OTA update (upload a new build): confirm transport adapter logs show `ota_start_received`, then `ota_end_received` or a new HELLO with `post_ota: true`.
- Confirm the display returns to daily view after OTA.

**Dependencies:** TASK-019 (display rendering must be in place), TASK-015 (dev env)

**Risk:** High — OTA detection on the Giga is hardware-specific and may not have a clean firmware-side hook in the `arduino:mbed_giga` core. If no detection hook is available, the `OTA-START` frame may not be sendable before reset; in this case, the system must rely solely on the `post_ota: true` HELLO frame on reconnect (which the transport adapter already handles via the state refresh path). This is an acceptable degradation: the transport adapter will log a `giga_disconnected` event during OTA and resume on reconnect. Document the fallback behavior.

---

### TASK-021 — Firmware: Integration Smoke Test (Hardware)

**Recommended Mode:** test-engineer

**Objective:** Execute end-to-end hardware smoke tests against the fully flashed Giga firmware with all backend services deployed, verifying all display states and the doorbell SLA.

**Requirements:** REQ-DIS-001 through REQ-DIS-009, REQ-ART-001, REQ-ART-002, REQ-PER-001, REQ-OBS-005

**Write Lease:**
```
^firmware/housepanel-giga/housepanel-giga\.ino$
```

**Change Budget:**
- max_files: 1 (only if a firmware bug fix is needed)
- max_new_symbols: 0
- interface_policy: extend_only

**Steps:**

1. Confirm all backend services are running and healthy:
   ```
   kubectl get pods -n housepanel
   ```
   All pods must be in `Running` state.

2. Test UC1 (ambient daily view):
   - Power on the Giga. Observe the display.
   - Confirm weather section, calendar section, and ticker are visible within 30 seconds of boot.
   - Wait for at least one calendar poll cycle (5 minutes) and one weather poll cycle (15 minutes); confirm sections update.

3. Test UC2 (doorbell interrupt):
   - Press the Ring doorbell 10 times with at least 40-second intervals (to allow auto-dismiss between trials).
   - For each press: measure time from press to display change using log timestamps:
     ```
     kubectl logs -n housepanel deployment/housepanel-ring-integration --since=5s
     kubectl logs -n housepanel deployment/housepanel-aggregator --since=5s
     kubectl logs -n housepanel deployment/housepanel-transport-adapter --since=5s
     ```
   - Record the delta between `ring-integration` `doorbell_event_received` timestamp and `transport-adapter` `command_sent` timestamp.
   - Add the estimated render time (~100ms) for end-to-end estimate.
   - All 10 trials must be <= 2000ms.

4. Test UC3 (camera motion alert ticker):
   - POST a test camera payload to the webhook receiver with a valid HMAC signature:
     ```
     curl -X POST http://<laminarflow-node>:<nodeport>/v1/webhooks/camera \
       -H "X-HousePanel-Signature: sha256=<computed-hmac>" \
       -H "Content-Type: application/json" \
       -d '{"schema_version":"1","source":"unifi-protect","timestamp":"2026-05-16T10:00:00Z","camera_name":"Front Yard","narrative":"Person detected near front door"}'
     ```
   - Confirm the text appears in the ticker on the display within 5 seconds.

5. Test UC4 (system alert ticker):
   - POST a test system alert to `/v1/webhooks/system-alert` with valid HMAC.
   - Confirm text appears in ticker.

6. Test REQ-DIS-009 (doorbell priority):
   - Simultaneously (within the same second): POST 5 ticker events and trigger a doorbell event.
   - Confirm doorbell display appears immediately; ticker events appear only after doorbell dismisses.

7. Test OTA continuity (AC6):
   - While the Giga is displaying daily view with active ticker events, trigger an OTA: run `arduino-cli upload --fqbn arduino:mbed_giga:giga --port <PORT> firmware/housepanel-giga/` with the same firmware (no-op update).
   - Confirm Giga reconnects; display returns to daily view with current weather and calendar.

**Verification:**
- All 10 doorbell latency trials logged; p99 <= 2000ms.
- All use-case steps above produce the expected display behavior.
- No pod crashes during the test session: `kubectl get pods -n housepanel | grep -v Running` must return empty.

**Dependencies:** TASK-019, TASK-020 (firmware complete), TASK-022 through TASK-025 (all backend services deployed)

**Risk:** High — requires physical hardware (Giga + Gigashield) and Ring doorbell device. Latency SLA depends on Ring cloud, which is outside HousePanel control. If Ring cloud regularly exceeds 800ms, the SLA buffer is insufficient — document and escalate rather than over-optimize local infrastructure.

---

### TASK-022 — K8s Manifests: Webhook Receiver

**Recommended Mode:** executor

**Objective:** Create Kubernetes Deployment, Service (NodePort), and ConfigMap manifests for `housepanel-webhook-receiver` and apply them to the `housepanel` namespace.

**Requirements:** REQ-WHR-006, REQ-SEC-004, REQ-SEC-005, REQ-PER-006

**Write Lease:**
```
^k8s/webhook-receiver\.yaml$
```

**Change Budget:**
- max_files: 1
- max_new_symbols: 0
- interface_policy: new_interface

**Steps:**

1. Create `k8s/webhook-receiver.yaml` containing:
   - `Deployment` named `housepanel-webhook-receiver` in namespace `housepanel`:
     - `replicas: 1`
     - `serviceAccountName: housepanel-webhook-receiver` (with `automountServiceAccountToken: false`)
     - Container `housepanel/webhook-receiver:latest` on port 8000
     - `resources: requests: {cpu: 50m, memory: 64Mi}, limits: {cpu: 200m, memory: 128Mi}`
     - `envFrom.secretRef: housepanel-webhook-secrets` (provides `WEBHOOK_SECRET_UNIFI` and `WEBHOOK_SECRET_ATH`)
     - `env: AGGREGATOR_URL=http://housepanel-aggregator:8001`, `LOG_LEVEL=INFO`
     - Liveness and readiness probes: `httpGet /healthz` port 8000, `initialDelaySeconds: 5`, `periodSeconds: 10`
   - `Service` named `housepanel-webhook-receiver` type `NodePort` on port 8000, `nodePort: 30800` (confirm this port is not in use on `laminarflow`).

2. Apply the manifest:
   ```
   kubectl apply -f k8s/webhook-receiver.yaml
   ```

3. Confirm the pod reaches `Running` state:
   ```
   kubectl rollout status deployment/housepanel-webhook-receiver -n housepanel
   ```

**Verification:**
- `kubectl get pod -n housepanel -l app=housepanel-webhook-receiver` must show `STATUS: Running`.
- `curl http://192.168.1.205:30800/healthz` must return `{"status": "ok"}`.
- `kubectl logs -n housepanel deployment/housepanel-webhook-receiver` must show startup logs with no error lines.

**Rollback:**
```
kubectl rollout undo deployment/housepanel-webhook-receiver -n housepanel
```

**Dependencies:** TASK-001 (scaffold), TASK-002 (namespace + ServiceAccount), TASK-005 (image built), TASK-006 (HMAC Secret)

**Risk:** Low — stateless Deployment; NodePort assignment must not conflict with existing cluster services.

---

### TASK-023 — K8s Manifests: Event Aggregator

**Recommended Mode:** executor

**Objective:** Create Kubernetes Deployment and ClusterIP Service manifests for `housepanel-aggregator` and apply them.

**Requirements:** REQ-AGG-006, REQ-SEC-005, REQ-PER-006

**Write Lease:**
```
^k8s/aggregator\.yaml$
```

**Change Budget:**
- max_files: 1
- max_new_symbols: 0
- interface_policy: new_interface

**Steps:**

1. Create `k8s/aggregator.yaml`:
   - `Deployment` named `housepanel-aggregator` in namespace `housepanel`:
     - `replicas: 1`
     - `serviceAccountName: housepanel-aggregator`
     - Container `housepanel/aggregator:latest` on port 8001
     - `resources: requests: {cpu: 50m, memory: 64Mi}, limits: {cpu: 200m, memory: 128Mi}`
     - `env`: `TRANSPORT_ADAPTER_URL=http://housepanel-transport-adapter:8002`, `TICKER_QUEUE_MAX_DEPTH=20`, `TICKER_EVENT_TTL_SECONDS=60`, `TICKER_DEDUP_WINDOW_SECONDS=30`, `TICKER_DRAIN_INTERVAL_SECONDS=1`, `DOORBELL_TIMEOUT_SECONDS=30`, `LOG_LEVEL=INFO`
     - Liveness probe: `httpGet /healthz` port 8001; readiness probe: `httpGet /internal/health` port 8001.
   - `Service` named `housepanel-aggregator` type `ClusterIP` on port 8001.

2. Apply:
   ```
   kubectl apply -f k8s/aggregator.yaml
   ```

3. Confirm `Running`:
   ```
   kubectl rollout status deployment/housepanel-aggregator -n housepanel
   ```

**Verification:**
- `kubectl exec -n housepanel deployment/housepanel-aggregator -- curl -s http://localhost:8001/internal/health` must return a valid JSON health response.
- `kubectl exec -n housepanel deployment/housepanel-webhook-receiver -- curl -s http://housepanel-aggregator:8001/internal/health` must succeed (confirms ClusterIP DNS resolves).

**Rollback:**
```
kubectl rollout undo deployment/housepanel-aggregator -n housepanel
```

**Dependencies:** TASK-002 (namespace + ServiceAccount), TASK-007 (image built)

**Risk:** Low — stateless ClusterIP service.

---

### TASK-024 — K8s Manifests: Calendar Poller and Weather Poller

**Recommended Mode:** executor

**Objective:** Create Kubernetes Deployment manifests for `housepanel-calendar-poller` and `housepanel-weather-poller` (no Services — outbound only), apply them, and confirm they begin polling.

**Requirements:** REQ-CAL-005, REQ-WTH-007, REQ-DAT-006, REQ-SEC-004, REQ-SEC-005, REQ-PER-006

**Write Lease:**
```
^k8s/calendar-poller\.yaml$
^k8s/weather-poller\.yaml$
```

**Change Budget:**
- max_files: 2
- max_new_symbols: 0
- interface_policy: new_interface

**Steps:**

1. Create `k8s/calendar-poller.yaml`:
   - `Deployment` named `housepanel-calendar-poller` in namespace `housepanel`:
     - `replicas: 1`
     - `serviceAccountName: housepanel-calendar-poller`
     - Container `housepanel/calendar-poller:latest` on port 8003 (healthz only)
     - `resources: requests: {cpu: 25m, memory: 64Mi}`
     - `env`: `AGGREGATOR_URL=http://housepanel-aggregator:8001`, `CALENDAR_POLL_INTERVAL_SECONDS=300`, `GOOGLE_CALENDAR_ID=<set-from-configmap>`, `LOG_LEVEL=INFO`, `GOOGLE_APPLICATION_CREDENTIALS=/secrets/google-adc/application_default_credentials.json`
     - `volumeMounts`: mount `google-adc` secret at `/secrets/google-adc/` as a file.
     - `volumes`: `secret: google-adc`.
     - Readiness probe: `httpGet /healthz` port 8003.

2. Create `k8s/weather-poller.yaml`:
   - `Deployment` named `housepanel-weather-poller` in namespace `housepanel`:
     - `replicas: 1`
     - `serviceAccountName: housepanel-weather-poller`
     - Container `housepanel/weather-poller:latest` on port 8004 (healthz only)
     - `resources: requests: {cpu: 25m, memory: 64Mi}`
     - `env`: `AGGREGATOR_URL=http://housepanel-aggregator:8001`, `WEATHER_POLL_INTERVAL_SECONDS=900`, `WEATHER_PRIMARY_PROVIDER=google`, `GOOGLE_APPLICATION_CREDENTIALS=/secrets/google-adc/application_default_credentials.json`, `LOG_LEVEL=INFO`
     - `envFrom.secretRef`: a `housepanel-weather-secrets` Secret containing `GOOGLE_WEATHER_API_KEY`, `OPENWEATHERMAP_API_KEY`, `OPENWEATHERMAP_LOCATION`.
     - Volume mount for `google-adc` secret (same as calendar poller).

3. Create the weather secrets (before applying):
   ```
   kubectl create secret generic housepanel-weather-secrets \
     --namespace housepanel \
     --from-literal=GOOGLE_WEATHER_API_KEY=<key> \
     --from-literal=OPENWEATHERMAP_API_KEY=<key> \
     --from-literal=OPENWEATHERMAP_LOCATION=<location>
   ```

4. Create a ConfigMap for non-secret config values like `GOOGLE_CALENDAR_ID`:
   ```
   kubectl create configmap housepanel-config \
     --namespace housepanel \
     --from-literal=GOOGLE_CALENDAR_ID=<calendar-id>
   ```

5. Apply both manifests:
   ```
   kubectl apply -f k8s/calendar-poller.yaml
   kubectl apply -f k8s/weather-poller.yaml
   ```

**Verification:**
- Both pods reach `Running` state.
- Within 5 minutes: `kubectl logs -n housepanel deployment/housepanel-calendar-poller | grep poll_success` must show at least one entry.
- Within 15 minutes: `kubectl logs -n housepanel deployment/housepanel-weather-poller | grep poll_success` must show at least one entry.
- Confirm no credential values appear in logs: `kubectl logs ... | grep -iE "api_key|secret|password"` must return empty.

**Rollback:**
```
kubectl rollout undo deployment/housepanel-calendar-poller -n housepanel
kubectl rollout undo deployment/housepanel-weather-poller -n housepanel
```

**Dependencies:** TASK-002 (namespace), TASK-008 (Google ADC secret), TASK-009 (calendar poller image), TASK-010 (weather poller image), TASK-023 (aggregator must be running)

**Risk:** Medium — Google API credentials and the Google Weather API endpoint validity are confirmed here for the first time in a real environment. If the Google Weather API key is invalid or the endpoint is inaccessible, the fallback to OpenWeatherMap will activate and must be confirmed working.

---

### TASK-025 — K8s Manifests: Ring Integration and Transport Adapter

**Recommended Mode:** executor

**Objective:** Create Kubernetes Deployment and Service manifests for `housepanel-ring-integration` (no Service) and `housepanel-transport-adapter` (ClusterIP + NodePort for Giga WebSocket), and apply them.

**Requirements:** REQ-RNG-005, REQ-ART-005, REQ-SEC-005, REQ-PER-006

**Write Lease:**
```
^k8s/ring-integration\.yaml$
^k8s/transport-adapter\.yaml$
```

**Change Budget:**
- max_files: 2
- max_new_symbols: 0
- interface_policy: new_interface

**Steps:**

1. Create `k8s/ring-integration.yaml`:
   - `Deployment` named `housepanel-ring-integration` in namespace `housepanel`:
     - `replicas: 1`
     - `serviceAccountName: housepanel-ring-integration`
     - Container `housepanel/ring-integration:latest` on port 8005 (healthz only)
     - `resources: requests: {cpu: 100m, memory: 128Mi}`
     - `env`: `AGGREGATOR_URL=http://housepanel-aggregator:8001`, `LOG_LEVEL=info`
     - `envFrom.secretRef`: `housepanel-ring-secrets` (provides `RING_REFRESH_TOKEN`)
     - Readiness probe: `httpGet /healthz` port 8005, `initialDelaySeconds: 15` (Ring client auth takes a few seconds).

2. Create `k8s/transport-adapter.yaml`:
   - `Deployment` named `housepanel-transport-adapter` in namespace `housepanel`:
     - `replicas: 1`
     - `serviceAccountName: housepanel-transport-adapter`
     - Container `housepanel/transport-adapter:latest` on port 8002
     - `resources: requests: {cpu: 50m, memory: 64Mi}`
     - `env`: `AGGREGATOR_URL=http://housepanel-aggregator:8001`, `LOG_LEVEL=INFO`
     - Liveness probe: `httpGet /healthz` port 8002; readiness probe: `httpGet /internal/health` port 8002.
   - `Service` named `housepanel-transport-adapter` with two ports:
     - `ClusterIP` port 8002 (for aggregator to call `/internal/commands`)
     - `NodePort` port 8002, `nodePort: 30802` (for Giga WebSocket `ws://192.168.1.205:30802/ws/panel`)
   - Confirm `nodePort: 30802` is not in use on `laminarflow`.

3. Apply both manifests:
   ```
   kubectl apply -f k8s/ring-integration.yaml
   kubectl apply -f k8s/transport-adapter.yaml
   ```

4. Update `firmware/housepanel-giga/config.h` `TRANSPORT_ADAPTER_WS_PORT` to `30802`.

**Verification:**
- `kubectl rollout status deployment/housepanel-transport-adapter -n housepanel` must succeed.
- `curl http://192.168.1.205:30802/internal/health` must return `{"status": "ok", "giga_connected": false, ...}` (Giga not yet connected; false is correct at this point).
- `kubectl logs -n housepanel deployment/housepanel-ring-integration | grep ring_connected` must appear within 30 seconds (Ring subscription established).
- `kubectl get pods -n housepanel` — all pods `Running`.

**Rollback:**
```
kubectl rollout undo deployment/housepanel-ring-integration -n housepanel
kubectl rollout undo deployment/housepanel-transport-adapter -n housepanel
```

**Dependencies:** TASK-002 (namespace), TASK-013 (ring-integration image), TASK-014 (Ring secret verified), TASK-016 (transport-adapter image), TASK-023 (aggregator running — transport adapter calls it on HELLO)

**Risk:** Medium — the transport adapter NodePort must be on the correct k3s node IP. Confirm that `192.168.1.205` is accessible from the Giga's Wi-Fi network before finalizing the NodePort assignment.

---

### TASK-026 — Integration Wiring and End-to-End Smoke Test

**Recommended Mode:** test-engineer

**Objective:** Execute the full end-to-end integration smoke test sequence validating all backend service interactions without hardware (Giga simulator), then with hardware, covering all four event paths and the state refresh protocol.

**Requirements:** REQ-DIS-001 through REQ-DIS-009, REQ-WHR-001 through REQ-WHR-004, REQ-AGG-001 through REQ-AGG-004, REQ-CAL-002, REQ-WTH-004, REQ-RNG-002, REQ-ART-001, REQ-ART-002, REQ-ERR-005, REQ-OBS-005

**Write Lease:**
```
^tests/integration/.*$
^tests/simulator/.*$
```

**Change Budget:**
- max_files: 8
- max_new_symbols: 10 (GigaSimulator class, simulate_hello, simulate_ota_cycle, collect_frames, assert_doorbell_first, and test functions)
- interface_policy: new_interface

**Steps:**

1. Create `tests/simulator/giga_simulator.py`:
   - A Python WebSocket client using the `websockets` library that:
     - Connects to `ws://<TRANSPORT_ADAPTER_HOST>:<PORT>/ws/panel`
     - Sends a HELLO frame on connect
     - Collects all received command frames into a list with receipt timestamps
     - Exposes `frames: list[dict]` for assertion
     - Method `simulate_ota_cycle()`: sends OTA-START, waits 2 seconds, sends OTA-END; records frames received during each phase.

2. Create `tests/integration/test_pipeline.py`:
   - `test_ticker_event_flow()`: POST a camera event to the webhook receiver; assert the Giga simulator receives a TICKER-APPEND frame within 5 seconds.
   - `test_doorbell_priority()`: POST 10 ticker events and 1 doorbell event simultaneously; assert the first frame received by the simulator is `cmd == "DOORBELL"`.
   - `test_state_refresh_on_hello()`: Ensure weather and calendar state exist in aggregator (by posting weather and calendar events); disconnect and reconnect the simulator; assert WEATHER-UPDATE and CALENDAR-UPDATE frames are received within 5 seconds.
   - `test_ota_pause_resumes_state()`: Run `simulate_ota_cycle()`; assert OTA-PAUSE frame received; assert that after OTA-END, WEATHER-UPDATE and CALENDAR-UPDATE frames are replayed.
   - `test_ticker_dedup()`: POST the same ticker payload twice within 30 seconds; assert only one TICKER-APPEND frame is received by the simulator.
   - `test_ticker_overflow()`: POST 25 ticker events; assert the simulator receives at most 20 TICKER-APPEND frames.

3. Create `tests/integration/test_webhook_auth.py`:
   - `test_invalid_hmac_rejected()`: POST with wrong HMAC; assert 401.
   - `test_valid_hmac_accepted()`: POST with correct HMAC; assert 202.
   - `test_missing_hmac_rejected()`: POST with no signature header; assert 401.
   - `test_schema_version_mismatch()`: POST with `schema_version: "99"`; assert 400.

4. Run the full integration test suite:
   ```
   python3 -m pytest tests/integration/ -v --timeout=30
   ```
   All tests must pass.

5. Run Stage 3 doorbell SLA validation (per design rollout plan):
   - Press Ring doorbell 10 times; collect log timestamps; compute p99.
   - Document results in a test output file (not a tracked spec file; use `/tmp/doorbell-sla-results.txt`).

**Verification:**
- `python3 -m pytest tests/integration/ -v --timeout=30` must show all tests passing.
- Doorbell SLA: p99 across 10 trials must be <= 2000ms as measured by log timestamps.
- `kubectl get pods -n housepanel | grep -v Running` must return empty (no crashed pods after test run).
- `kubectl logs -n housepanel deployment/housepanel-aggregator | grep ERROR` must return empty (no unexpected errors during test run).

**Dependencies:** All TASK-022 through TASK-025 (all services deployed and running), TASK-017 through TASK-020 (for hardware tests in step 5)

**Risk:** High — end-to-end tests require all services to be healthy simultaneously. Flaky network conditions on the home cluster can cause intermittent failures. Use `--timeout=30` per test to prevent hangs. The doorbell SLA test requires live Ring hardware and Ring cloud availability.

---

## Definition of Done Checklist

A task is complete when ALL of the following are true:

- [ ] All steps in the task are executed and no step has a known failure.
- [ ] All verification commands in the task pass (zero failing assertions, zero error exits).
- [ ] No pod in the `housepanel` namespace has a non-Running status after the task completes.
- [ ] No credentials, API keys, refresh tokens, or HMAC secrets appear in any committed file.
- [ ] Structured log output from the modified service is valid JSON (spot-check 5 log lines from `kubectl logs`).
- [ ] The task's write lease was respected: no files outside the declared `Write Lease` patterns were modified.
- [ ] Unit tests pass: `python3 -m pytest tests/ -v` with zero failures.
- [ ] If the task involves a K8s deployment: `kubectl rollout status deployment/<name> -n housepanel` returns successfully.
- [ ] REQ-SEC-002 verified: `kubectl logs -n housepanel deployment/<service> | grep -iE "api_key|secret|password|token" | grep -v "REPLACE_WITH"` returns empty for any service touched by the task.

---

## Execution Notes

### Tooling and Environment

- **kubectl context:** Confirm `kubectl config current-context` points to the `laminarflow` k3s cluster before executing any K8s task.
- **Python version:** All Python tasks require Python 3.12. Verify: `python3 --version`.
- **All services are Python 3.12.** No Node.js runtime is required.
- **arduino-cli:** Firmware tasks require `arduino-cli`. After running TASK-015, verify: `arduino-cli version`.
- **Docker/image builds:** The cluster runs a local `registry:2` on `laminarflow` (NodePort 30500, plain HTTP, anonymous).
  - Build pattern: `docker build -t laminarflow:30500/housepanel/<service>:<semver-tag> services/<service>/`
  - Push pattern: `docker push laminarflow:30500/housepanel/<service>:<semver-tag>`
  - Manifest image refs: `laminarflow:30500/housepanel/<service>:<semver-tag>` — always use pinned semver tags, never `latest` in manifests (tag-reuse with `IfNotPresent` policy requires clearing both bare and `docker.io/...` cached refs before a redeploy).
  - **Mirror prerequisite:** Every node that schedules a HousePanel pod must have `/etc/rancher/k3s/registries.yaml` configured. Run `sudo scripts/configure-registry-mirror.sh` (from the cluster repo) on each node before TASK-022. Without this, containerd refuses plain HTTP pulls.
  - Alternatively, bare image refs (`housepanel/<service>:<tag>`) also resolve correctly once the mirror rewrite is in place (`docker.io/*` → `laminarflow:30500/*`), but the explicit hostname form is preferred for new workloads.
- **HMAC test helper:** A helper script for generating HMAC signatures during manual testing should be created during TASK-005. Suggested: `scripts/hmac-sign.py <secret-env-var-name> <body-file>`.
- **ardconfig host tool:** `ardconfig` is a host-side dev tool only. Do not attempt to use it as a firmware library or import it in firmware code. It is invoked via `bin/ardconfig-setup` and `bin/ardconfig-health` on the development host.

### Checkpoints

| Checkpoint | After Task | Criteria |
|------------|-----------|----------|
| CP-1: Scaffold complete | TASK-001 | Directory structure matches design; all Dockerfiles compile clean base images |
| CP-2: Namespace ready | TASK-002 | `kubectl get namespace housepanel` returns Active; all 6 ServiceAccounts exist |
| CP-3: Schema published | TASK-004, TASK-011 | Both JSON schemas validate and match Pydantic models |
| CP-4: Secrets in cluster | TASK-006, TASK-008, TASK-012 | All three secrets (`housepanel-webhook-secrets`, `google-adc`, `housepanel-ring-secrets`) exist in `housepanel` namespace |
| CP-5: Backend unit tests green | TASK-005 through TASK-013, TASK-016 | All `pytest` runs pass locally before any K8s manifest is applied |
| CP-6: All services deployed | TASK-022 through TASK-025 | `kubectl get pods -n housepanel` shows 6 pods all in Running state |
| CP-7: No-hardware integration | TASK-026 steps 1-4 | All integration tests with Giga simulator pass |
| CP-8: Hardware integration | TASK-021, TASK-026 step 5 | All hardware smoke tests pass; doorbell p99 <= 2000ms |

### Inter-Service Startup Order

On the cluster, services depend on each other for health. Apply manifests in this order to avoid early crash loops:
1. `housepanel-aggregator` (has no outbound dependency at startup)
2. `housepanel-transport-adapter` (calls aggregator only on Giga connect, not at startup)
3. `housepanel-webhook-receiver` (calls aggregator for forwarding; can start before aggregator is ready since it retries)
4. `housepanel-calendar-poller` and `housepanel-weather-poller` (outbound only; resilient to aggregator not ready)
5. `housepanel-ring-integration` (outbound only; Ring subscription happens at startup, aggregator calls happen on events)

### Namespace Stewardship

All `kubectl` commands in task steps must include `--namespace housepanel` or `-n housepanel` explicitly. No task may reference or modify any other namespace. Before executing any `kubectl apply` or `kubectl delete`, confirm the manifest's `namespace:` field reads `housepanel`.

---

## Traceability

| REQ ID | Task IDs |
|--------|---------|
| REQ-DIS-001 | TASK-019, TASK-021, TASK-026 |
| REQ-DIS-002 | TASK-018, TASK-019, TASK-021, TASK-026 |
| REQ-DIS-003 | TASK-019, TASK-021 |
| REQ-DIS-004 | TASK-019, TASK-021 |
| REQ-DIS-005 | TASK-019, TASK-021 |
| REQ-DIS-006 | TASK-019, TASK-021 |
| REQ-DIS-007 | TASK-019, TASK-021, TASK-026 |
| REQ-DIS-008 | TASK-020, TASK-021 |
| REQ-DIS-009 | TASK-007, TASK-016, TASK-019, TASK-021, TASK-026 |
| REQ-WHR-001 | TASK-004, TASK-005, TASK-022, TASK-026 |
| REQ-WHR-002 | TASK-005, TASK-011, TASK-022, TASK-026 |
| REQ-WHR-003 | TASK-005, TASK-026 |
| REQ-WHR-004 | TASK-005, TASK-026 |
| REQ-WHR-005 | TASK-004, TASK-005, TASK-011 |
| REQ-WHR-006 | TASK-001, TASK-022 |
| REQ-WHR-007 | TASK-006 (security posture: HMAC implemented) |
| REQ-AGG-001 | TASK-003, TASK-007 |
| REQ-AGG-002 | TASK-007, TASK-026 |
| REQ-AGG-003 | TASK-007, TASK-026 |
| REQ-AGG-004 | TASK-007, TASK-016, TASK-026 |
| REQ-AGG-005 | TASK-007, TASK-013 |
| REQ-AGG-006 | TASK-001, TASK-023 |
| REQ-CAL-001 | TASK-009, TASK-024 |
| REQ-CAL-002 | TASK-009, TASK-026 |
| REQ-CAL-003 | TASK-009, TASK-021 |
| REQ-CAL-004 | TASK-008, TASK-024 |
| REQ-CAL-005 | TASK-001, TASK-024 |
| REQ-WTH-001 | TASK-010, TASK-024 |
| REQ-WTH-002 | TASK-010 |
| REQ-WTH-003 | TASK-010, TASK-024 |
| REQ-WTH-004 | TASK-010, TASK-026 |
| REQ-WTH-005 | TASK-010, TASK-021 |
| REQ-WTH-006 | TASK-008, TASK-024 |
| REQ-WTH-007 | TASK-001, TASK-024 |
| REQ-RNG-001 | TASK-012, TASK-013 |
| REQ-RNG-002 | TASK-013, TASK-026 |
| REQ-RNG-003 | TASK-013, TASK-021, TASK-026 |
| REQ-RNG-004 | TASK-007, TASK-013 |
| REQ-RNG-005 | TASK-001, TASK-025 |
| REQ-ART-001 | TASK-016, TASK-017, TASK-025, TASK-026 |
| REQ-ART-002 | TASK-016, TASK-026 |
| REQ-ART-003 | TASK-015, TASK-017 |
| REQ-ART-004 | TASK-016, TASK-020 |
| REQ-ART-005 | TASK-001, TASK-025 |
| REQ-ART-006 | TASK-016 |
| REQ-DAT-001 | TASK-004, TASK-005, TASK-011 |
| REQ-DAT-002 | TASK-003 |
| REQ-DAT-003 | TASK-004, TASK-005 |
| REQ-DAT-004 | TASK-011 |
| REQ-DAT-005 | TASK-010 |
| REQ-DAT-006 | TASK-008, TASK-024 |
| REQ-ERR-001 | TASK-009 |
| REQ-ERR-002 | TASK-010 |
| REQ-ERR-003 | TASK-005 |
| REQ-ERR-004 | TASK-007, TASK-009, TASK-010 |
| REQ-ERR-005 | TASK-016, TASK-017 |
| REQ-ERR-006 | TASK-020, TASK-021 |
| REQ-PER-001 | TASK-007, TASK-013, TASK-016, TASK-021, TASK-026 |
| REQ-PER-002 | TASK-007, TASK-016, TASK-026 |
| REQ-PER-003 | TASK-009, TASK-024 |
| REQ-PER-004 | TASK-010, TASK-024 |
| REQ-PER-005 | TASK-007 |
| REQ-PER-006 | TASK-022, TASK-023, TASK-024, TASK-025 |
| REQ-SEC-001 | TASK-005, TASK-006 |
| REQ-SEC-002 | TASK-005, TASK-007, TASK-009, TASK-010, TASK-013 |
| REQ-SEC-003 | TASK-009 |
| REQ-SEC-004 | TASK-006, TASK-008, TASK-012, TASK-022, TASK-023, TASK-024, TASK-025 |
| REQ-SEC-005 | TASK-002, TASK-022, TASK-023, TASK-024, TASK-025 |
| REQ-OBS-001 | TASK-003, TASK-005, TASK-007, TASK-009, TASK-010, TASK-013, TASK-016 |
| REQ-OBS-002 | TASK-005 |
| REQ-OBS-003 | TASK-009 |
| REQ-OBS-004 | TASK-010 |
| REQ-OBS-005 | TASK-007, TASK-013, TASK-016, TASK-021, TASK-026 |
| REQ-OBS-006 | TASK-003 (stdout only, no external metrics) |
| REQ-BCK-001 | TASK-004, TASK-005, TASK-011 |
| REQ-BCK-002 | TASK-015 |
| REQ-BCK-003 | TASK-007, TASK-013 |
| REQ-BCK-004 | TASK-010 |
| REQ-CPL-001 | TASK-009, TASK-010 |
| REQ-CPL-002 | TASK-007, TASK-009, TASK-010 |

---

_End of HousePanel Task Plan — Gate 4 artifact._
