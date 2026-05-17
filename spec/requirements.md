# HousePanel — Requirements

_Gate 2 artifact. Created: 2026-05-16. Owner: karl@wehden.com._
_Source of truth: `/spec/context.md` (Gate 1). All requirements derive exclusively from that document._

---

## Table of Contents

1. [Functional Requirements](#functional-requirements)
   - [DIS — Display / UX](#dis--display--ux)
   - [WHR — Webhook Receiver](#whr--webhook-receiver)
   - [AGG — Event Aggregator](#agg--event-aggregator)
   - [CAL — Calendar Poller](#cal--calendar-poller)
   - [WTH — Weather Poller](#wth--weather-poller)
   - [RNG — Ring Integration](#rng--ring-integration)
   - [ART — Arduino Transport](#art--arduino-transport)
2. [Data & Interface Contracts](#data--interface-contracts)
3. [Error Handling & Recovery](#error-handling--recovery)
4. [Performance & Scalability](#performance--scalability)
5. [Security & Privacy](#security--privacy)
6. [Observability](#observability)
7. [Backward Compatibility & Migration](#backward-compatibility--migration)
8. [Compliance / Policy Constraints](#compliance--policy-constraints)
9. [Validation Plan](#validation-plan)
10. [Traceability Matrix](#traceability-matrix)
11. [Deferred Requirements](#deferred-requirements)

---

## Functional Requirements

Requirements use EARS syntax. Forms used:
- **Ubiquitous:** `THE [system] SHALL [action]`
- **Event-driven:** `WHEN [trigger], THE [system] SHALL [response]`
- **State-driven:** `WHILE [state], THE [system] SHALL [action]`
- **Conditional:** `IF [condition], THE [system] SHALL [action]`
- **Optional/feature-gated:** `WHERE [feature is enabled], THE [system] SHALL [action]`

---

### DIS — Display / UX

**REQ-DIS-001**
THE display panel SHALL present an always-on daily view consisting of a weather section, a calendar section, and a scrolling ticker without requiring any resident interaction.

**REQ-DIS-002**
WHEN a doorbell event is received by the Arduino transport layer, THE display panel SHALL immediately switch to a full-screen doorbell flash interrupt state, preempting all other active display states including the daily view and any in-progress ticker scroll.

**REQ-DIS-003**
WHILE the doorbell interrupt state is active, THE display panel SHALL maintain the full-screen doorbell alert until the interrupt is dismissed or a timeout elapses. _(Timeout value and acknowledgement mechanism: TBD — OQ6)_

**REQ-DIS-004**
WHEN the doorbell interrupt timeout elapses or the interrupt is dismissed, THE display panel SHALL return to the daily view. _(Dismissal interaction and timeout duration: TBD — OQ6)_

**REQ-DIS-005**
THE weather section of the daily view SHALL display current weather conditions sourced from the most recent weather poll result.

**REQ-DIS-006**
THE calendar section of the daily view SHALL display upcoming family calendar events sourced from the most recent calendar poll result.

**REQ-DIS-007**
THE scrolling ticker SHALL display camera motion narrative descriptions and system/temperature alerts as a continuously scrolling text band.

**REQ-DIS-008**
IF an `ardconfig`-managed OTA update is applied to the Giga, THE display panel SHALL resume normal daily view operation after the update completes without permanent loss of functionality.

**REQ-DIS-009**
THE display panel SHALL treat the doorbell interrupt as the highest-priority display state; no other event type may override or delay a doorbell interrupt once triggered.

---

### WHR — Webhook Receiver

**REQ-WHR-001**
THE webhook receiver SHALL expose an HTTP endpoint on the `laminarflow` Kubernetes cluster that accepts inbound camera motion narrative events pushed by the UniFi Protect external service.

**REQ-WHR-002**
THE webhook receiver SHALL expose an HTTP endpoint on the `laminarflow` Kubernetes cluster that accepts inbound system and temperature alert events pushed by the `ArduinoTempHumUbuntu` service.

**REQ-WHR-003**
WHEN a valid payload is received on either endpoint, THE webhook receiver SHALL return an HTTP 2xx response to the caller.

**REQ-WHR-004**
WHEN a valid payload is received, THE webhook receiver SHALL forward the event to the event aggregator without dropping it during normal Kubernetes pod operation.

**REQ-WHR-005**
THE webhook receiver SHALL enforce a versioned inbound payload schema for both the camera event endpoint and the `ArduinoTempHumUbuntu` alert endpoint from the first release, so that future schema changes do not silently break callers. _(Specific schema for `ArduinoTempHumUbuntu` alerts: TBD — OQ8)_

**REQ-WHR-006**
THE webhook receiver SHALL deploy and run as a Kubernetes workload on `laminarflow`.

**REQ-WHR-007**
THE webhook receiver's authentication and authorization posture SHALL be evaluated and decided during the security review gate before design is finalized. _(Posture outcome: TBD — OQ9)_

---

### AGG — Event Aggregator

**REQ-AGG-001**
THE event aggregator SHALL normalize events received from all sources — webhook receiver (camera events, system/temperature alerts), Ring integration backend, calendar poller, and weather poller — into a single unified internal event type before routing.

**REQ-AGG-002**
WHEN a doorbell event is received from the Ring integration backend, THE event aggregator SHALL route it immediately as a highest-priority interrupt to the Arduino transport layer, ahead of any queued ticker events.

**REQ-AGG-003**
THE event aggregator SHALL maintain a ticker event queue for camera motion narrative and system/temperature alert events. _(Queue depth, deduplication rules, TTL per event type, and display order policy: TBD — OQ7)_

**REQ-AGG-004**
THE event aggregator SHALL route ticker events from the queue to the Arduino transport layer for display on the scrolling ticker.

**REQ-AGG-005**
THE event aggregator SHALL treat Ring doorbell events as a normalized event type so that changes to the Ring integration backend do not require changes to the aggregator or the Arduino transport layer.

**REQ-AGG-006**
THE event aggregator SHALL deploy and run as a Kubernetes workload on `laminarflow`.

---

### CAL — Calendar Poller

**REQ-CAL-001**
THE calendar poller SHALL poll the Google Calendar API on a recurring schedule and retrieve upcoming family calendar events. _(Polling interval: TBD — OQ5)_

**REQ-CAL-002**
WHEN a poll cycle completes, THE calendar poller SHALL push the retrieved event set to the event aggregator for delivery to the display panel's calendar section.

**REQ-CAL-003**
THE calendar section of the display panel SHALL reflect calendar additions or changes within one polling cycle of their appearance in Google Calendar. _(Polling interval determines maximum staleness — OQ5)_

**REQ-CAL-004**
THE calendar poller SHALL use user-supplied Google Calendar API credentials. Credential storage and injection is deferred to design.

**REQ-CAL-005**
THE calendar poller SHALL deploy and run as a Kubernetes workload on `laminarflow`.

---

### WTH — Weather Poller

**REQ-WTH-001**
THE weather poller SHALL poll the Google weather API as the primary data source and SHALL fall back to OpenWeatherMap if Google weather API access or quota is insufficient. _(OQ4 resolved)_

**REQ-WTH-002**
THE weather poller SHALL implement a swappable adapter interface between the weather data source and the rest of the system, so that switching between weather providers requires no changes to the event aggregator or the display layer.

**REQ-WTH-003**
THE weather poller SHALL poll the active weather source on a recurring schedule and retrieve current conditions. _(Polling interval: TBD — OQ5)_

**REQ-WTH-004**
WHEN a weather poll cycle completes, THE weather poller SHALL push the retrieved conditions to the event aggregator for delivery to the display panel's weather section.

**REQ-WTH-005**
THE weather section of the display panel SHALL reflect current conditions within one polling cycle of the most recent successful weather poll. _(Polling interval determines maximum staleness — OQ5)_

**REQ-WTH-006**
THE weather poller SHALL use user-supplied API credentials for whichever weather provider is active. Credential storage and injection is deferred to design.

**REQ-WTH-007**
THE weather poller SHALL deploy and run as a Kubernetes workload on `laminarflow`.

---

### RNG — Ring Integration

> **NOTE:** The Ring integration mechanism is fully greenfield. The requirements below define the observable behavior and interface contract. All implementation decisions are deferred. _(OQ1)_

**REQ-RNG-001**
THE Ring integration backend SHALL receive or detect Ring doorbell press events by a mechanism to be determined during design. _(Integration mechanism: TBD — OQ1)_

**REQ-RNG-002**
WHEN a Ring doorbell press event is detected, THE Ring integration backend SHALL normalize it into the HousePanel unified event format and forward it to the event aggregator as a highest-priority interrupt event.

**REQ-RNG-003**
THE end-to-end latency from the moment a Ring doorbell is pressed to the moment the full-screen doorbell interrupt appears on the display panel SHALL be no greater than 2 seconds under normal operating conditions.

**REQ-RNG-004**
IF the Ring integration approach changes during design or development, THE event aggregator and Arduino transport layer SHALL require no changes, as Ring events are normalized at the Ring integration backend boundary before entering the aggregator.

**REQ-RNG-005**
THE Ring integration backend SHALL deploy and run as a Kubernetes workload on `laminarflow` if a server-side component is required by the chosen integration mechanism.

---

### ART — Arduino Transport

> **NOTE:** The wire protocol and connectivity mechanism between the K8s cluster and the Arduino Giga are unresolved. Requirements are expressed as interface contracts only. _(OQ2, OQ3)_

**REQ-ART-001**
THE Arduino transport adapter SHALL translate normalized events from the event aggregator into commands delivered to the Arduino Giga + Gigashield display panel. _(Wire protocol and transport mechanism: TBD — OQ2, OQ3)_

**REQ-ART-002**
THE Arduino transport adapter SHALL preserve the priority ordering of events emitted by the aggregator: doorbell interrupt commands SHALL be delivered to the Giga before any pending ticker commands.

**REQ-ART-003**
THE Arduino transport adapter SHALL operate without requiring any modification to the upstream `ardconfig` repository. All firmware integration must remain within the interface that `ardconfig` exposes.

**REQ-ART-004**
WHILE an `ardconfig`-managed OTA update is in progress, THE Arduino transport adapter SHALL NOT send display commands that could corrupt the update process. After the update completes, the transport adapter SHALL resume normal event delivery.

**REQ-ART-005**
THE Arduino transport adapter SHALL deploy and run as a Kubernetes workload or as a sidecar to an existing K8s service on `laminarflow`. _(Exact deployment topology deferred to design)_

**REQ-ART-006**
THE Arduino transport adapter SHALL expose a defined interface toward the event aggregator, independent of the underlying wire protocol used to communicate with the Giga, so that transport mechanism changes do not require aggregator changes.

---

## Data & Interface Contracts

**REQ-DAT-001**
THE webhook receiver SHALL version its inbound payload schemas using an explicit version field or URL path component from the first release. Schema changes that would break existing callers SHALL be introduced as new schema versions.

**REQ-DAT-002**
THE unified internal event type used by the event aggregator SHALL carry at minimum: event source identifier, event type (ticker | doorbell-interrupt | weather-update | calendar-update), event timestamp, and a human-readable payload string suitable for display.

**REQ-DAT-003**
THE inbound webhook schema for camera narrative events (UniFi Protect source) SHALL be treated as a stable contract from first release. The schema MUST be documented as part of the webhook receiver service's published interface.

**REQ-DAT-004**
THE inbound webhook schema for `ArduinoTempHumUbuntu` alert events SHALL be treated as a stable contract from first release, versioned as specified in REQ-WHR-005. _(Specific schema fields: TBD — OQ8)_

**REQ-DAT-005**
THE weather poller adapter interface SHALL define a provider-agnostic data structure for current weather conditions (at minimum: temperature, conditions description, and timestamp) so that switching between Google weather API and OpenWeatherMap requires no changes beyond the adapter implementation.

**REQ-DAT-006**
THE Google Calendar API and weather API credentials SHALL be supplied to their respective pollers via the Kubernetes deployment environment. The specific credential injection mechanism is deferred to design.

---

## Error Handling & Recovery

**REQ-ERR-001**
IF the Google Calendar API returns an error during a poll cycle, THE calendar poller SHALL log the error with the HTTP response code and SHALL retain the most recently successful event set for display until the next successful poll.

**REQ-ERR-002**
IF the primary weather data source (Google weather API) is unavailable or returns an error, THE weather poller SHALL automatically retry using the OpenWeatherMap fallback adapter. IF both sources fail, the poller SHALL log the failure and retain the most recently successful weather result for display.

**REQ-ERR-003**
IF the webhook receiver encounters a payload that does not conform to the declared inbound schema version, THE webhook receiver SHALL return an HTTP 4xx response and SHALL log the rejection with the source, timestamp, and schema version mismatch detail. The malformed payload SHALL NOT be forwarded to the aggregator.

**REQ-ERR-004**
IF a Kubernetes pod hosting any backend service restarts, THE service SHALL resume normal operation on restart without data migration steps, treating in-flight state (e.g., ticker queue contents) as lossy across restarts.

**REQ-ERR-005**
IF the Arduino transport adapter loses connectivity to the Giga, THE adapter SHALL log the connectivity failure and SHALL queue or discard pending commands according to a policy defined at design time, with the constraint that a reconnection SHALL resume delivery of the current state (daily view, weather, calendar) before queued ticker events.

**REQ-ERR-006**
IF an `ardconfig` OTA update interrupts the Giga mid-operation, THE system SHALL NOT enter a permanently broken display state; the Giga SHALL return to a functional display after OTA completes.

---

## Performance & Scalability

**REQ-PER-001**
THE end-to-end doorbell interrupt latency — measured from the moment the Ring doorbell is pressed to the moment the full-screen interrupt appears on the panel — SHALL be no greater than 2 seconds under normal operating conditions. _(Latency budget allocation across Ring backend, aggregator, and transport: deferred to design — AC1)_

**REQ-PER-002**
WHEN a valid webhook payload is received by the webhook receiver, THE event SHALL appear in the scrolling ticker on the display panel within an end-to-end delay to be defined and agreed upon during design. _(Target delay: TBD — AC5)_

**REQ-PER-003**
THE calendar poller SHALL be designed such that its polling interval can be configured without code changes, to allow tuning against Google Calendar API quota limits. _(Interval value: TBD — OQ5)_

**REQ-PER-004**
THE weather poller SHALL be designed such that its polling interval can be configured without code changes, to allow tuning against weather API quota limits. _(Interval value: TBD — OQ5)_

**REQ-PER-005**
THE event aggregator ticker queue SHALL have a bounded maximum depth to prevent unbounded memory growth during high-event-rate periods. _(Queue depth value: TBD — OQ7)_

**REQ-PER-006**
THE system SHALL be designed to run on the `laminarflow` home Kubernetes cluster within the resource constraints of that cluster. No high-availability or horizontal scaling requirements are imposed for the initial version.

---

## Security & Privacy

**REQ-SEC-001**
THE webhook receiver's authentication and authorization posture SHALL be evaluated in a security review gate before the design phase is finalized. The security review SHALL consider at minimum: network topology (cluster-internal vs. externally reachable), shared-secret token validation, and mTLS. _(Posture decision: TBD — OQ9)_

**REQ-SEC-002**
THE system SHALL NOT log sensitive API credential values (Google Calendar API key, Google weather API key, OpenWeatherMap API key, or any Ring integration credentials) in any log output.

**REQ-SEC-003**
THE system SHALL NOT log personally identifiable information from calendar event payloads beyond what is necessary to diagnose a missed display event.

**REQ-SEC-004**
THE Google Calendar API, weather API, and any Ring integration credentials SHALL be injected into the relevant K8s services via the deployment environment and SHALL NOT be embedded in container images or source code.

**REQ-SEC-005**
THE system SHALL apply the principle of least privilege: each K8s service SHALL have access only to the credentials and cluster resources required for its own function.

---

## Observability

**REQ-OBS-001**
EACH K8s backend service (webhook receiver, event aggregator, calendar poller, weather poller, Ring integration backend, Arduino transport adapter) SHALL emit structured logs to stdout/stderr sufficient to diagnose missed events, failed API calls, and connectivity failures.

**REQ-OBS-002**
THE webhook receiver SHALL log for each inbound request: source identifier, receipt timestamp, schema version detected, and whether the event was accepted and forwarded or rejected with reason.

**REQ-OBS-003**
THE calendar poller SHALL log for each poll cycle: poll cycle timestamp, number of events fetched, and any API error with HTTP response code.

**REQ-OBS-004**
THE weather poller SHALL log for each poll cycle: poll cycle timestamp, active provider (Google weather API or OpenWeatherMap), and any API error with HTTP response code and whether fallback was triggered.

**REQ-OBS-005**
THE doorbell interrupt path SHALL be traceable through logs from Ring event receipt at the Ring integration backend through aggregator routing to the display command sent by the Arduino transport adapter.

**REQ-OBS-006**
THE system SHALL NOT require an external metrics platform (such as Prometheus or Datadog) for the initial version. Stdout structured logs are the minimum viable observability baseline.

---

## Backward Compatibility & Migration

**REQ-BCK-001**
THE inbound webhook payload schema for camera narrative events and for `ArduinoTempHumUbuntu` alerts SHALL be treated as a stable external contract from the first release. Breaking schema changes SHALL be introduced only as new versioned schema variants; existing callers SHALL continue to work on the prior version.

**REQ-BCK-002**
THE `ardconfig` upstream dependency SHALL NOT be forked or patched. IF a new version of `ardconfig` is released during HousePanel development, the HousePanel firmware interface SHALL remain compatible with the new version or the update SHALL be explicitly gated and reviewed.

**REQ-BCK-003**
THE event aggregator and Arduino transport layer SHALL remain unchanged when the Ring integration backend's implementation approach changes, provided Ring events continue to be delivered as normalized unified events at the aggregator interface boundary.

**REQ-BCK-004**
THE weather poller's swappable adapter interface SHALL ensure that switching from the Google weather API to OpenWeatherMap (or any future provider) requires no changes to the event aggregator, display layer, or any service other than the adapter implementation itself.

---

## Compliance / Policy Constraints

**REQ-CPL-001**
THE system SHALL comply with the terms of service of any third-party API it consumes (Google Calendar API, Google weather API, OpenWeatherMap, Ring API if applicable), including rate limits, quota restrictions, and acceptable use policies.

**REQ-CPL-002**
THE system SHALL NOT store raw Google Calendar event data or weather data persistently beyond what is held in-memory for the current display cycle, unless a future requirement explicitly approves persistent storage.

---

## Validation Plan

Each requirement is validated by one or more of the following methods: manual inspection (INS), functional test (FT), integration test (IT), acceptance test (AT), or security review (SR).

| Requirement   | Validation Method | Test Description |
|---------------|-------------------|-----------------|
| REQ-DIS-001   | AT                | Power on panel; confirm weather, calendar, and ticker are all visible without interaction (UC1). |
| REQ-DIS-002   | AT, IT            | Trigger simulated doorbell event; confirm display immediately transitions to full-screen flash regardless of current display state (UC2). |
| REQ-DIS-003   | AT                | Trigger doorbell interrupt; confirm interrupt state persists until timeout/dismiss. _(Timeout value TBD — OQ6)_ |
| REQ-DIS-004   | AT                | After doorbell interrupt resolves, confirm return to daily view (UC2). |
| REQ-DIS-005   | AT                | Confirm weather section shows conditions from the last successful poll (UC6). |
| REQ-DIS-006   | AT                | Confirm calendar section shows events from the last successful poll (UC5). |
| REQ-DIS-007   | AT                | Inject test camera and system alert events; confirm ticker scrolls with their content (UC3, UC4). |
| REQ-DIS-008   | AT                | Trigger `ardconfig` OTA update; confirm panel resumes daily view after update completes (AC6). |
| REQ-DIS-009   | AT                | Inject ticker event and doorbell event simultaneously; confirm doorbell takes priority. |
| REQ-WHR-001   | IT, FT            | POST a test camera narrative payload to the endpoint; confirm 2xx response and event forwarded (UC3, AC2). |
| REQ-WHR-002   | IT, FT            | POST a test `ArduinoTempHumUbuntu` alert to the endpoint; confirm 2xx response and event forwarded (UC4, AC2). |
| REQ-WHR-003   | FT                | POST valid payloads; assert HTTP 2xx returned in both cases. |
| REQ-WHR-004   | IT                | Under normal pod operation, POST payloads and confirm none are dropped at the aggregator interface. |
| REQ-WHR-005   | INS, FT           | Inspect schema version field presence; POST payload with wrong version; confirm 4xx and rejection log. _(Schema TBD — OQ8)_ |
| REQ-WHR-006   | IT                | Deploy to `laminarflow`; confirm pod reaches Running state and endpoint is reachable (AC7). |
| REQ-WHR-007   | SR                | Security review gate evaluates auth posture before design sign-off. _(OQ9)_ |
| REQ-AGG-001   | IT                | Inject events of each type; confirm each is normalized and routed correctly. |
| REQ-AGG-002   | IT                | Inject doorbell and ticker events concurrently; confirm doorbell routed first. |
| REQ-AGG-003   | FT                | Inject events into ticker queue; confirm queue enforces bounds. _(Policy TBD — OQ7)_ |
| REQ-AGG-004   | IT                | Confirm ticker events flow from queue to transport adapter for display. |
| REQ-AGG-005   | INS               | Code review confirms aggregator has no Ring-specific code paths. |
| REQ-AGG-006   | IT                | Deploy to `laminarflow`; confirm pod reaches Running state (AC7). |
| REQ-CAL-001   | IT                | Confirm calendar poller executes poll cycles on schedule and retrieves events. |
| REQ-CAL-002   | IT                | Confirm retrieved events are pushed to aggregator after each poll cycle. |
| REQ-CAL-003   | AT                | Add calendar event; confirm it appears on panel within one poll cycle (AC3). |
| REQ-CAL-004   | INS               | Review deployment configuration; confirm credentials not in image or source. |
| REQ-CAL-005   | IT                | Deploy to `laminarflow`; confirm pod reaches Running state (AC7). |
| REQ-WTH-001   | FT                | Configure primary source to fail; confirm automatic fallback to OpenWeatherMap. |
| REQ-WTH-002   | INS               | Code review confirms adapter interface is the sole dependency boundary for weather provider. |
| REQ-WTH-003   | IT                | Confirm weather poller executes on schedule and fetches conditions. |
| REQ-WTH-004   | IT                | Confirm fetched conditions are pushed to aggregator after each poll cycle. |
| REQ-WTH-005   | AT                | Observe weather section; confirm it reflects current conditions within one poll cycle (AC4). |
| REQ-WTH-006   | INS               | Review deployment configuration; confirm credentials not in image or source. |
| REQ-WTH-007   | IT                | Deploy to `laminarflow`; confirm pod reaches Running state (AC7). |
| REQ-RNG-001   | AT                | Press Ring doorbell; confirm event is received and processed. _(Integration TBD — OQ1)_ |
| REQ-RNG-002   | IT                | Confirm Ring event is normalized and forwarded to aggregator as high-priority interrupt. |
| REQ-RNG-003   | AT                | Press Ring doorbell; measure elapsed time until full-screen interrupt appears on panel; assert <= 2 seconds (AC1). |
| REQ-RNG-004   | INS               | Code review confirms aggregator has no Ring-mechanism-specific code. |
| REQ-RNG-005   | IT                | Deploy Ring backend to `laminarflow`; confirm pod reaches Running state (AC7). |
| REQ-ART-001   | IT                | Inject aggregator events; confirm commands delivered to Giga. _(Protocol TBD — OQ2, OQ3)_ |
| REQ-ART-002   | IT                | Inject doorbell and ticker commands simultaneously; confirm doorbell delivered first. |
| REQ-ART-003   | INS               | Code review confirms no `ardconfig` source modifications. |
| REQ-ART-004   | AT                | Trigger OTA during event delivery; confirm update completes and delivery resumes. |
| REQ-ART-005   | IT                | Deploy adapter to `laminarflow`; confirm reaches Running state (AC7). |
| REQ-ART-006   | INS               | Code review confirms aggregator-facing interface is protocol-independent. |
| REQ-DAT-001   | INS, FT           | Confirm version field or path component present in both webhook endpoints from first deployment. |
| REQ-DAT-002   | INS               | Review unified event type definition for required fields. |
| REQ-DAT-003   | INS               | Confirm camera event schema is documented in webhook receiver service interface docs. |
| REQ-DAT-004   | INS               | Confirm ATH alert schema is documented and versioned. _(Schema TBD — OQ8)_ |
| REQ-DAT-005   | INS               | Review weather adapter interface; confirm provider-agnostic output structure. |
| REQ-DAT-006   | INS               | Confirm credentials are injected via K8s environment, not embedded in images. |
| REQ-ERR-001   | FT                | Simulate Google Calendar API failure; confirm log entry and stale data retained on display. |
| REQ-ERR-002   | FT                | Simulate Google weather API failure; confirm fallback to OpenWeatherMap; simulate both failures; confirm log and stale data retained. |
| REQ-ERR-003   | FT                | POST malformed payload to webhook receiver; confirm 4xx response and rejection log; confirm event not forwarded. |
| REQ-ERR-004   | IT                | Kill and restart a backend pod; confirm service resumes processing without manual intervention. |
| REQ-ERR-005   | FT                | Simulate Giga connectivity loss; confirm log entry; restore connection; confirm state resumes. |
| REQ-ERR-006   | AT                | Trigger OTA mid-operation; confirm Giga returns to functional display after OTA completes (AC6). |
| REQ-PER-001   | AT                | Measure doorbell press-to-display time over multiple trials; assert p99 <= 2 seconds (AC1). |
| REQ-PER-002   | IT                | Send webhook; measure time to ticker appearance on panel. _(Target TBD — AC5)_ |
| REQ-PER-003   | INS               | Confirm polling interval is externally configurable without code change. |
| REQ-PER-004   | INS               | Confirm polling interval is externally configurable without code change. |
| REQ-PER-005   | FT                | Flood aggregator with events; confirm queue stops growing after bounded depth. _(Depth TBD — OQ7)_ |
| REQ-PER-006   | IT                | Confirm all services run on `laminarflow` without exceeding cluster resource limits. |
| REQ-SEC-001   | SR                | Security review gate evaluates auth posture options before design. _(OQ9)_ |
| REQ-SEC-002   | INS, FT           | Review log output; confirm no credential strings appear in any log line. |
| REQ-SEC-003   | INS               | Review log output for calendar events; confirm no PII beyond diagnostic minimum. |
| REQ-SEC-004   | INS               | Inspect container images and source; confirm no hardcoded credentials. |
| REQ-SEC-005   | INS               | Review K8s RBAC and service account assignments. |
| REQ-OBS-001   | INS, IT           | Confirm each service emits structured log lines to stdout/stderr. |
| REQ-OBS-002   | FT                | Send webhook; confirm log contains source, timestamp, schema version, and forwarding result. |
| REQ-OBS-003   | FT                | Trigger poll cycle; confirm log contains timestamp, event count, and error (if any). |
| REQ-OBS-004   | FT                | Trigger poll cycle; confirm log contains timestamp, provider name, and error/fallback (if any). |
| REQ-OBS-005   | IT                | Press doorbell; collect logs from all services; confirm end-to-end trace is present. |
| REQ-OBS-006   | INS               | Confirm no external metrics agent is required to run the system. |
| REQ-BCK-001   | INS, FT           | Confirm schema version field is present; POST payload with old version to confirm continued acceptance. |
| REQ-BCK-002   | INS               | Confirm no `ardconfig` source files are modified; confirm `ardconfig` version is tracked. |
| REQ-BCK-003   | INS               | Code review confirms aggregator has no Ring-mechanism-specific dependencies. |
| REQ-BCK-004   | FT                | Switch weather adapter; confirm aggregator and display layer require no code changes. |
| REQ-CPL-001   | INS               | Review API usage against documented rate limits and ToS for each provider. |
| REQ-CPL-002   | INS               | Code review confirms no persistent storage write paths for calendar or weather data. |

---

## Traceability Matrix

| Requirement   | UC / AC / Constraint                        | Risk / OQ Reference     | Design Section (TBD at Gate 3) | Task IDs (TBD at Gate 4) |
|---------------|---------------------------------------------|-------------------------|-------------------------------|--------------------------|
| REQ-DIS-001   | UC1                                         | —                       | TBD                           | TBD                      |
| REQ-DIS-002   | UC2, Priority Invariant                     | R4                      | TBD                           | TBD                      |
| REQ-DIS-003   | UC2                                         | OQ6                     | TBD                           | TBD                      |
| REQ-DIS-004   | UC2                                         | OQ6                     | TBD                           | TBD                      |
| REQ-DIS-005   | UC1, UC6                                    | —                       | TBD                           | TBD                      |
| REQ-DIS-006   | UC1, UC5                                    | R9                      | TBD                           | TBD                      |
| REQ-DIS-007   | UC1, UC3, UC4                               | R8                      | TBD                           | TBD                      |
| REQ-DIS-008   | AC6, ardconfig constraint                   | R4                      | TBD                           | TBD                      |
| REQ-DIS-009   | UC2, Priority Invariant                     | R4                      | TBD                           | TBD                      |
| REQ-WHR-001   | UC3, Goal 3, AC2                            | —                       | TBD                           | TBD                      |
| REQ-WHR-002   | UC4, Goal 4, AC2                            | R6                      | TBD                           | TBD                      |
| REQ-WHR-003   | AC2                                         | —                       | TBD                           | TBD                      |
| REQ-WHR-004   | AC2, AC5                                    | —                       | TBD                           | TBD                      |
| REQ-WHR-005   | Rollout constraint, R6                      | OQ8                     | TBD                           | TBD                      |
| REQ-WHR-006   | Goal 8, AC7, Infrastructure constraint      | R7                      | TBD                           | TBD                      |
| REQ-WHR-007   | Non-goal (security posture deferred), R5    | OQ9                     | TBD                           | TBD                      |
| REQ-AGG-001   | Goal 3/4/5/6, UC3/UC4                       | —                       | TBD                           | TBD                      |
| REQ-AGG-002   | UC2, Priority Invariant, AC1                | R1                      | TBD                           | TBD                      |
| REQ-AGG-003   | UC3, UC4, AC5                               | OQ7, R8                 | TBD                           | TBD                      |
| REQ-AGG-004   | UC3, UC4, AC5                               | R8                      | TBD                           | TBD                      |
| REQ-AGG-005   | Rollout constraint                          | R1, OQ1                 | TBD                           | TBD                      |
| REQ-AGG-006   | Goal 8, AC7, Infrastructure constraint      | R7                      | TBD                           | TBD                      |
| REQ-CAL-001   | UC5, Goal 6, AC3                            | OQ5, R9                 | TBD                           | TBD                      |
| REQ-CAL-002   | UC5, AC3                                    | —                       | TBD                           | TBD                      |
| REQ-CAL-003   | AC3                                         | OQ5, R9                 | TBD                           | TBD                      |
| REQ-CAL-004   | Credential constraint                       | —                       | TBD                           | TBD                      |
| REQ-CAL-005   | Goal 8, AC7, Infrastructure constraint      | R7                      | TBD                           | TBD                      |
| REQ-WTH-001   | Goal 7, UC6, AC4                            | OQ4 (resolved), R3      | TBD                           | TBD                      |
| REQ-WTH-002   | R3, OQ4 (resolved)                          | —                       | TBD                           | TBD                      |
| REQ-WTH-003   | UC6, Goal 7, AC4                            | OQ5                     | TBD                           | TBD                      |
| REQ-WTH-004   | UC6, AC4                                    | —                       | TBD                           | TBD                      |
| REQ-WTH-005   | AC4                                         | OQ5                     | TBD                           | TBD                      |
| REQ-WTH-006   | Credential constraint                       | —                       | TBD                           | TBD                      |
| REQ-WTH-007   | Goal 8, AC7, Infrastructure constraint      | R7                      | TBD                           | TBD                      |
| REQ-RNG-001   | UC2, Goal 2                                 | OQ1, R1                 | TBD                           | TBD                      |
| REQ-RNG-002   | UC2, Priority Invariant, AC1                | OQ1, R1                 | TBD                           | TBD                      |
| REQ-RNG-003   | AC1, Goal 2                                 | OQ1, R1                 | TBD                           | TBD                      |
| REQ-RNG-004   | Rollout constraint                          | OQ1                     | TBD                           | TBD                      |
| REQ-RNG-005   | Goal 8, AC7, Infrastructure constraint      | OQ1, R7                 | TBD                           | TBD                      |
| REQ-ART-001   | Goal 9, UC1/UC2/UC3/UC4                     | OQ2, OQ3, R2            | TBD                           | TBD                      |
| REQ-ART-002   | UC2, Priority Invariant                     | OQ2, OQ3, R4            | TBD                           | TBD                      |
| REQ-ART-003   | ardconfig constraint, Goal 9                | OQ2, OQ3, R2            | TBD                           | TBD                      |
| REQ-ART-004   | AC6, ardconfig constraint                   | R4                      | TBD                           | TBD                      |
| REQ-ART-005   | Goal 8, AC7, Infrastructure constraint      | OQ2, OQ3, R7            | TBD                           | TBD                      |
| REQ-ART-006   | OQ2, OQ3, Rollout constraint                | R2                      | TBD                           | TBD                      |
| REQ-DAT-001   | Rollout constraint, AC2                     | OQ8                     | TBD                           | TBD                      |
| REQ-DAT-002   | All subsystems                              | —                       | TBD                           | TBD                      |
| REQ-DAT-003   | UC3, AC2, Rollout constraint                | —                       | TBD                           | TBD                      |
| REQ-DAT-004   | UC4, AC2, Rollout constraint                | OQ8, R6                 | TBD                           | TBD                      |
| REQ-DAT-005   | OQ4 (resolved), R3                          | —                       | TBD                           | TBD                      |
| REQ-DAT-006   | Credential constraint                       | —                       | TBD                           | TBD                      |
| REQ-ERR-001   | AC3, R9                                     | OQ5                     | TBD                           | TBD                      |
| REQ-ERR-002   | AC4, OQ4 (resolved), R3                     | —                       | TBD                           | TBD                      |
| REQ-ERR-003   | AC2                                         | OQ8                     | TBD                           | TBD                      |
| REQ-ERR-004   | AC2, AC7, R7                                | —                       | TBD                           | TBD                      |
| REQ-ERR-005   | UC1, AC5                                    | OQ2, OQ3                | TBD                           | TBD                      |
| REQ-ERR-006   | AC6                                         | R4                      | TBD                           | TBD                      |
| REQ-PER-001   | AC1, Goal 2                                 | OQ1, R1                 | TBD                           | TBD                      |
| REQ-PER-002   | AC5, UC3, UC4                               | R8                      | TBD                           | TBD                      |
| REQ-PER-003   | AC3, OQ5                                    | R9                      | TBD                           | TBD                      |
| REQ-PER-004   | AC4, OQ5                                    | —                       | TBD                           | TBD                      |
| REQ-PER-005   | AC5, R8                                     | OQ7                     | TBD                           | TBD                      |
| REQ-PER-006   | R7, Goal 8                                  | —                       | TBD                           | TBD                      |
| REQ-SEC-001   | Non-goal (auth deferred), R5                | OQ9                     | TBD                           | TBD                      |
| REQ-SEC-002   | Credential constraint                       | —                       | TBD                           | TBD                      |
| REQ-SEC-003   | Privacy (implied by calendar data)          | —                       | TBD                           | TBD                      |
| REQ-SEC-004   | Credential constraint                       | —                       | TBD                           | TBD                      |
| REQ-SEC-005   | Credential constraint                       | —                       | TBD                           | TBD                      |
| REQ-OBS-001   | Observability baseline                      | —                       | TBD                           | TBD                      |
| REQ-OBS-002   | Observability baseline, AC2                 | —                       | TBD                           | TBD                      |
| REQ-OBS-003   | Observability baseline, AC3                 | —                       | TBD                           | TBD                      |
| REQ-OBS-004   | Observability baseline, AC4                 | —                       | TBD                           | TBD                      |
| REQ-OBS-005   | Observability baseline, AC1                 | OQ1                     | TBD                           | TBD                      |
| REQ-OBS-006   | Observability baseline                      | —                       | TBD                           | TBD                      |
| REQ-BCK-001   | Rollout constraint                          | OQ8, R6                 | TBD                           | TBD                      |
| REQ-BCK-002   | ardconfig constraint                        | R2                      | TBD                           | TBD                      |
| REQ-BCK-003   | Rollout constraint                          | OQ1, R1                 | TBD                           | TBD                      |
| REQ-BCK-004   | OQ4 (resolved), Rollout constraint          | R3                      | TBD                           | TBD                      |
| REQ-CPL-001   | Credential / API constraint                 | R3                      | TBD                           | TBD                      |
| REQ-CPL-002   | Privacy, Non-goals (no logging/analytics)   | —                       | TBD                           | TBD                      |

---

## Deferred Requirements

The following requirement placeholders are deferred because their governing open questions are unresolved. They SHALL be converted to fully specified requirements when the corresponding OQ is resolved, before the relevant design section is finalized.

---

### DEFER-OQ1 — Ring Integration Mechanism

**Status:** Deferred. Blocks: REQ-RNG-001, REQ-RNG-002, REQ-RNG-003, REQ-PER-001, REQ-OBS-005, REQ-ART-001 (latency budget allocation), AC1.

**Placeholder requirement:**
WHEN a Ring doorbell button is pressed, THE Ring integration backend SHALL receive and normalize the event and forward it to the event aggregator. _(How the Ring integration backend receives the event — cloud polling, `ring-mqtt`, Home Assistant bridge, or other — is TBD pending OQ1 resolution.)_

**What must be decided:** The integration mechanism (cloud API polling, local MQTT bridge, Home Assistant adapter, or other). The decision determines latency characteristics and informs how the 2-second AC1 budget is allocated.

**Owner:** karl@wehden.com. Must be resolved before Ring integration backend design begins.

---

### DEFER-OQ2-OQ3 — Arduino Transport Wire Protocol and Network Connectivity

**Status:** Deferred. Blocks: REQ-ART-001, REQ-ART-006, REQ-ERR-005.

**Placeholder requirement:**
THE Arduino transport adapter SHALL deliver commands from the event aggregator to the Arduino Giga using a transport mechanism and protocol to be determined at design time, subject to the constraints that: (a) `ardconfig` must not be modified, and (b) doorbell interrupt commands must be delivered with higher priority than ticker commands.

**What must be decided:**
- OQ2: Whether the Giga communicates via HTTP polling, WebSocket push, MQTT, or an `ardconfig`-provided abstraction.
- OQ3: Whether `ardconfig` initializes Giga network connectivity or whether HousePanel firmware must establish it.

**Owner:** karl@wehden.com. Must be resolved by reviewing `ardconfig` source and README before Arduino transport design begins.

---

### DEFER-OQ5 — Calendar and Weather Polling Intervals

**Status:** Deferred. Affects: REQ-CAL-001, REQ-WTH-003, REQ-PER-003, REQ-PER-004.

**Placeholder requirement:**
THE calendar poller and weather poller SHALL execute at configurable polling intervals. _(The specific interval values for each poller are TBD pending OQ5 resolution, which requires evaluating Google API quota limits and acceptable display staleness.)_

**What must be decided:** Acceptable polling frequency for Google Calendar and Google weather / OpenWeatherMap given quota limits and the freshness requirements of AC3 and AC4.

**Owner:** karl@wehden.com. Can be resolved during design phase; does not block architectural design but must be set before implementation.

---

### DEFER-OQ6 — Doorbell Interrupt Timeout and Acknowledgement UX

**Status:** Deferred. Blocks: REQ-DIS-003, REQ-DIS-004.

**Placeholder requirement:**
WHEN a doorbell interrupt is active, THE display panel SHALL remain in the interrupt state until a timeout elapses or the interrupt is acknowledged. _(The timeout duration and whether manual acknowledgement is required are TBD pending OQ6 resolution.)_

**What must be decided:** Timeout duration (in seconds), and whether resident acknowledgement (button press, proximity sensor, or similar) can dismiss the interrupt early or whether timeout is the sole exit path.

**Owner:** karl@wehden.com. UX decision; must be resolved before firmware display logic is designed.

---

### DEFER-OQ7 — Ticker Event Queue Policy

**Status:** Deferred. Blocks: REQ-AGG-003, REQ-PER-005.

**Placeholder requirement:**
THE event aggregator SHALL maintain a bounded ticker event queue with defined policies for maximum depth, deduplication, TTL per event type, and display order. _(All policy values — depth, dedup rules, TTL, ordering — are TBD pending OQ7 resolution.)_

**What must be decided:** Maximum queue depth; whether duplicate events (same source + same content within a time window) are deduplicated; TTL values per event type (camera vs. system alert); queue ordering (FIFO, priority-weighted, or recency-weighted).

**Owner:** karl@wehden.com. Must be resolved during requirements finalization or early design phase; affects aggregator and firmware ticker behavior.

---

### DEFER-OQ8 — ArduinoTempHumUbuntu Inbound Webhook Schema

**Status:** Deferred. Blocks: REQ-WHR-002, REQ-WHR-005, REQ-DAT-004, REQ-BCK-001.

**Placeholder requirement:**
THE webhook receiver SHALL accept `ArduinoTempHumUbuntu` alert events via a versioned inbound schema to be defined jointly with the sibling repo owner. _(The specific HTTP method, URL path, payload field names, data types, and schema version mechanism are TBD pending OQ8 resolution.)_

**What must be decided:** The full payload schema for `ArduinoTempHumUbuntu` alerts — HTTP verb, endpoint path, required fields (temperature, humidity, severity, host identifier, timestamp), and schema version mechanism. HousePanel owns the inbound contract; the sibling repo must implement against it.

**Owner:** karl@wehden.com. Must be resolved and published before `ArduinoTempHumUbuntu` begins implementing push support.

---

### DEFER-OQ9 — Webhook Receiver Authentication Posture

**Status:** Deferred. Blocks: REQ-WHR-007, REQ-SEC-001.

**Placeholder requirement:**
THE webhook receiver's authentication and authorization posture SHALL be decided in a security review gate. _(Whether unauthenticated cluster-internal access, shared-secret token, or mTLS is required is TBD pending OQ9 resolution.)_

**What must be decided:** Network topology of the webhook receiver (cluster-internal only vs. externally reachable); whether a shared secret, API key header, or mTLS is required; and whether the UniFi Protect service and `ArduinoTempHumUbuntu` service can supply authentication credentials.

**Owner:** karl@wehden.com. Must be resolved in security review before webhook receiver design is finalized.

---

_End of HousePanel Requirements — Gate 2 artifact._
