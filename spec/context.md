# HousePanel — Project Context

_Gate 1 artifact. Created: 2026-05-16. Owner: karl@wehden.com._

---

## Problem Statement

Home automation data — weather, family calendar events, security camera alerts, doorbell events, and local system/temperature alerts — is spread across multiple services with no unified, always-on physical display. Residents have no single ambient view of the household state and no reliable, high-priority physical interrupt for critical events (e.g., doorbell). HousePanel solves this by combining an Arduino Giga + Gigashield physical display panel with always-on backend aggregation services, presenting a consolidated daily view with prioritized alert escalation.

---

## Goals

- Provide an always-on physical display panel showing current weather, family calendar events, and a scrolling alert ticker without requiring any user interaction.
- Deliver doorbell events as a full-screen flash interrupt on the physical display within a latency budget that makes the interrupt perceptually immediate (target: <= 2 seconds from event to display change; exact SLA to be confirmed — see Open Questions).
- Aggregate camera motion narrative descriptions (pushed via webhook from an existing external service) and surface them in the scrolling alert ticker.
- Aggregate local temperature and system/network alerts (pushed from the sibling `ArduinoTempHumUbuntu` repo) and surface them in the scrolling alert ticker.
- Expose a webhook receiver endpoint on the K8s cluster (`laminarflow`) that accepts inbound pushes from the UniFi Protect camera narrative service and from `ArduinoTempHumUbuntu`.
- Poll Google Calendar for family calendar events and refresh the display on a schedule (polling interval TBD — see Open Questions).
- Poll a Google APIs weather endpoint and refresh the weather display on a schedule (polling interval TBD — see Open Questions).
- All backend aggregation and polling services must be deployable as Kubernetes workloads on `laminarflow`.
- The Arduino Giga must communicate with the K8s services without requiring modification to the upstream `ardconfig` dependency.

---

## Non-Goals / Out of Scope

- Kubernetes manifest authoring, Helm charts, or deployment pipeline configuration — deferred to design/tasks phases.
- Ring doorbell integration design — the integration approach is fully open (see Open Questions); no code or design decisions are committed here.
- Arduino firmware implementation details below the interface boundary (wire protocol, display rendering internals) — these are delegated to a future firmware design step.
- Modification of the upstream `ardconfig` repository (`https://github.com/kwehden/ardconfig`) — treat as a black-box dependency.
- General home automation platform features beyond the six data sources listed in Data Sources.
- Mobile or web UI — the physical panel is the sole display target.
- Historical data logging, analytics, or dashboards.
- Multi-panel or multi-room display support.
- User authentication or access control for the webhook receiver (security posture for internal-only K8s endpoints to be evaluated in security review gate).

---

## Users & Use-Cases

**Primary user:** Household residents (family members) who glance at the panel in passing.

| ID  | Use-Case | Trigger | Expected Outcome |
|-----|----------|---------|-----------------|
| UC1 | Ambient daily view | Panel is always on | Resident sees current weather, upcoming calendar events, and the scrolling ticker without interaction. |
| UC2 | Doorbell interrupt | Ring doorbell pressed | Display immediately switches to full-screen flash and doorbell alert; overrides all other display states; returns to daily view after acknowledgement or timeout. |
| UC3 | Camera motion alert | UniFi Protect external service pushes webhook | Narrative description of camera event appears in the scrolling ticker within a reasonable delay. |
| UC4 | System/temperature alert | `ArduinoTempHumUbuntu` pushes alert | Alert appears in the scrolling ticker; severity level to be defined in requirements phase. |
| UC5 | Calendar event reminder | Upcoming family event within a time window | Event is visible in the calendar section; no active interrupt unless requirements define one. |
| UC6 | Weather update | Scheduled poll cycle | Weather section refreshes with current conditions. |

---

## Constraints & Invariants

**Hardware**
- Target microcontroller: Arduino Giga + Gigashield. No other hardware targets are in scope.
- The Giga's network connectivity may be provided by `ardconfig` or may need to be established independently — this is unresolved (see Open Questions).

**Upstream dependency**
- `ardconfig` (`https://github.com/kwehden/ardconfig`) is an upstream dependency that handles base hardware access, Arduino software flow, and OTA updates. It must not be modified. All firmware work must stay within the interface it exposes.

**Infrastructure**
- All backend services (webhook receiver, event aggregator, calendar poller, weather poller, and any Ring integration backend if applicable) must deploy as Kubernetes workloads on the host `laminarflow`.
- No external cloud hosting for backend services — `laminarflow` is the sole deployment target.

**Data sources and credentials**
- Google Calendar and Google weather APIs require user-supplied API credentials. Credential management approach (K8s Secrets, external secrets operator, etc.) is deferred to design.
- The UniFi Protect camera narrative service is an existing external system; HousePanel only needs to receive its webhooks — no changes to that service are in scope.
- `ArduinoTempHumUbuntu` (`https://github.com/kwehden/ArduinoTempHumUbuntu`) is a sibling repo being extended to push alerts to HousePanel. Changes to that repo are out of scope for HousePanel itself, but HousePanel must define and expose a compatible inbound interface.

**Priority invariant**
- Doorbell events are the highest-priority display interrupt and must preempt all other display states. This invariant must be preserved in any transport and firmware design.

**Greenfield project**
- All HousePanel files are greenfield. No existing HousePanel code, schema, or API surface exists to preserve.

---

## Success Metrics & Acceptance Criteria

| ID   | Criterion | Measurement |
|------|-----------|-------------|
| AC1  | Doorbell interrupt latency | Full-screen doorbell display appears within <= 2 seconds of the Ring event (exact transport latency budget to be allocated across Ring integration, K8s service, and Arduino transport in design phase). |
| AC2  | Webhook receiver availability | Camera and system alert webhook endpoint returns 2xx to valid payloads and does not drop events during normal K8s pod operation. |
| AC3  | Calendar freshness | Calendar section reflects events within one polling cycle of their addition or change in Google Calendar. |
| AC4  | Weather freshness | Weather section reflects current conditions within one polling cycle. |
| AC5  | Ticker correctness | Every webhook payload received by the backend appears in the scrolling ticker on the panel within a reasonable end-to-end delay (target to be defined in requirements). |
| AC6  | OTA update continuity | `ardconfig`-managed OTA updates can be applied without permanent loss of panel functionality. |
| AC7  | K8s deployability | All backend services can be applied to `laminarflow` and reach a healthy/running state using standard K8s primitives. |

---

## Risks & Edge Cases

| ID  | Risk / Edge Case | Severity | Notes |
|-----|-----------------|----------|-------|
| R1  | Ring doorbell integration is fully greenfield with no committed approach | High | Blocks doorbell UX design and latency SLA allocation. Must be resolved before design phase. |
| R2  | `ardconfig` transport abstraction may or may not cover network connectivity for the Giga | High | If `ardconfig` does not provide network, HousePanel firmware must establish it — changes scope. |
| R3  | Google APIs weather offering is unspecified; correct endpoint, quota limits, and response schema are unknown | Medium | Risk of needing to switch APIs or add an adapter layer. |
| R4  | Doorbell full-screen interrupt may arrive while the panel is mid-render or mid-OTA | Medium | Firmware must define a safe preemption point; OTA must not brick the panel if interrupted. |
| R5  | Webhook receiver has no defined authentication in this spec | Medium | Internal-only K8s exposure may be acceptable, but must be confirmed in security review. |
| R6  | `ArduinoTempHumUbuntu` webhook push interface is being designed in the sibling repo; contract may drift | Medium | HousePanel must define a stable inbound interface and version it, or coordinate with sibling repo owner. |
| R7  | K8s cluster `laminarflow` is a home server; availability and resource limits are undefined | Low-Medium | No HA guarantee; pod restart policies and crash recovery must be considered in design. |
| R8  | Scrolling ticker ordering and deduplication policy is undefined | Low | Multiple rapid camera events could flood the ticker; a queue/dedup strategy is needed in requirements. |
| R9  | Google Calendar polling interval may miss short-duration events | Low | Events shorter than the polling interval may never appear on the panel. |

---

## Observability / Telemetry Expectations

_These are baseline expectations for a home server deployment. Formal observability tooling selection is deferred to design._

- Each K8s backend service should emit structured logs (stdout/stderr) sufficient to diagnose missed events, failed API calls, and webhook receipt failures.
- Webhook receiver must log: inbound payload source, receipt timestamp, and whether the event was forwarded to the Arduino transport layer.
- Calendar and weather pollers must log: poll cycle timestamp, number of events fetched, and any API errors with response codes.
- Doorbell interrupt path must be traceable from Ring event receipt through to the display command sent to the Giga.
- No external metrics platform (Prometheus, Datadog, etc.) is required for the initial version; stdout logs are the minimum viable observability baseline.

---

## Rollout & Backward Compatibility

_This is a greenfield project with no existing production deployment. Standard backward compatibility concerns do not apply to the initial version._

- The `ardconfig` upstream dependency must not be forked or patched. If a new `ardconfig` version is released during development, the HousePanel firmware interface must remain compatible or the update must be explicitly gated.
- The webhook receiver's inbound payload schema (for camera events and `ArduinoTempHumUbuntu` alerts) must be versioned from the first release to allow future schema evolution without breaking callers.
- If the Ring integration approach changes during design, only the Ring-specific backend service should require changes; the aggregator and Arduino transport layer should treat Ring events as a normalized event type.

---

## Open Questions

| ID  | Question | Owner | Resolution Path |
|-----|----------|-------|----------------|
| OQ1 | **Ring integration method:** cloud polling API, `ring-mqtt` local bridge, Home Assistant integration, or other? | karl@wehden.com | Evaluate Ring API capabilities, local bridge feasibility, and latency impact before design phase. Blocks AC1. |
| OQ2 | **Arduino ↔ K8s transport:** HTTP polling from Giga, WebSocket push from K8s, MQTT, or does `ardconfig` abstract this entirely? | karl@wehden.com | Review `ardconfig` source/docs for network and transport capabilities. Blocks firmware interface design. |
| OQ3 | **Does `ardconfig` handle Giga network connectivity** (Wi-Fi or Ethernet init), or must HousePanel firmware establish it independently? | karl@wehden.com | Review `ardconfig` README and source. If not covered, adds firmware scope. |
| OQ4 | **Google APIs weather specifics:** which API product (Maps Weather, Google Weather API, or other), endpoint, response schema, and quota tier? | karl@wehden.com | **Decision:** Try Google weather API first; fall back to OpenWeatherMap if access or quota is limited. Poller must be designed with a swappable adapter so the source can change without affecting the aggregator. |
| OQ5 | **Calendar and weather polling intervals:** what refresh rate is acceptable for each? | karl@wehden.com | Decide based on Google API quota limits and acceptable display staleness. Informs poller design. |
| OQ6 | **Doorbell interrupt timeout / acknowledgement:** how long does the full-screen doorbell alert stay before reverting to daily view, and does it require a manual dismiss? | karl@wehden.com | UX decision; affects firmware and event lifecycle design. |
| OQ7 | **Ticker event queue policy:** maximum queue depth, deduplication rules, TTL per event type, display order (FIFO, priority-weighted)? | karl@wehden.com | Requirements phase decision; affects aggregator and firmware ticker logic. |
| OQ8 | **`ArduinoTempHumUbuntu` webhook contract:** what payload schema and HTTP method will the sibling repo push? Who owns the contract? | karl@wehden.com | Coordinate with sibling repo; HousePanel must publish a stable inbound schema or negotiate a shared one. |
| OQ9 | **Webhook receiver security posture:** is unauthenticated access acceptable given K8s-internal exposure, or is a shared secret / mTLS required? | karl@wehden.com | Confirm network topology (is the receiver cluster-internal only?) and decide auth posture in security review gate. |

---

## Minimal Change Intent

_All HousePanel components are greenfield. There is no existing codebase to minimally patch._

**New modules expected to be created (not pre-approved for scope expansion beyond these):**

| Module | Role |
|--------|------|
| Webhook receiver service | HTTP endpoint receiving camera narrative events and `ArduinoTempHumUbuntu` alerts; runs as K8s service on `laminarflow`. |
| Event aggregator | Normalizes events from all sources into a unified event type; manages the ticker queue; routes doorbell events as high-priority interrupts. |
| Google Calendar poller | Scheduled service polling Google Calendar API and pushing updates to the aggregator. |
| Weather poller | Scheduled service polling the Google weather API and pushing updates to the aggregator. |
| Ring integration backend | Greenfield; approach TBD (OQ1). Responsible for receiving or polling Ring doorbell events and forwarding them to the aggregator as high-priority events. |
| Arduino transport adapter | Thin layer translating aggregator events into the wire protocol understood by the Giga (format TBD pending OQ2 and OQ3); runs as part of the K8s service or as a sidecar. |

**Abstractions explicitly out of scope unless approved:**
- A general-purpose home automation event bus or plugin system — events are point-to-point from source to aggregator.
- A generic device abstraction layer — only the Arduino Giga + Gigashield is supported.
- A configuration UI or admin interface.

**API surface that must remain unchanged:**
- None exists yet. The inbound webhook schema for camera events and `ArduinoTempHumUbuntu` alerts, once defined, must be treated as a stable contract from first release (see Rollout).

---

## Glossary

| Term | Definition |
|------|-----------|
| Arduino Giga + Gigashield | The target microcontroller board and its expansion shield that drives the physical display panel. |
| ardconfig | Upstream dependency repo (`https://github.com/kwehden/ardconfig`) providing base hardware access, software flow, and OTA for the Giga. Treated as read-only in this project. |
| ArduinoTempHumUbuntu | Sibling repo (`https://github.com/kwehden/ArduinoTempHumUbuntu`) being extended to push temperature/system/network alerts to HousePanel via webhook. |
| laminarflow | Hostname of the always-on home Kubernetes cluster that hosts all HousePanel backend services. |
| Daily view | The default display state of the panel: weather section + calendar section + scrolling ticker, all always-on. |
| Doorbell interrupt | A full-screen flash display state triggered by a Ring doorbell event; highest-priority state that preempts all other display states. |
| Scrolling ticker | A "breaking news" style horizontally scrolling text band displaying camera motion narratives and system/temperature alerts. |
| Event aggregator | The backend service responsible for normalizing events from all sources and routing them to the correct display channel (ticker vs. interrupt). |
| Webhook receiver | The HTTP endpoint service that accepts inbound event pushes from the UniFi Protect camera narrative service and from `ArduinoTempHumUbuntu`. |
| UniFi Protect camera narrative service | An existing external service (not in HousePanel scope) that generates natural language descriptions of camera motion events and pushes them to HousePanel via webhook. |
| Ring doorbell | Physical doorbell device; integration approach is TBD (OQ1). |
| OTA | Over-the-air firmware update, managed by `ardconfig`. |
| K8s | Kubernetes, the container orchestration platform running on `laminarflow`. |
| Google APIs | Google's developer API platform; used as the source for both calendar (Google Calendar API) and weather (specific product TBD — OQ4). |
