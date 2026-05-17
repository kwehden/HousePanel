# HousePanel

A home automation display panel built on an Arduino Giga R1 WiFi with Giga Display Shield. Shows live weather, upcoming calendar events, and doorbell/camera notifications on an 800×480 touchscreen display. Backend services run on a k3s cluster.

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
│  ring-integration ┼──► aggregator ──► transport-   │
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
| `ring-integration` | Receives Ring doorbell events via OAuth |
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
  ring-integration/      FastAPI — Ring doorbell
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

# Ring credentials (for ring-integration)
kubectl create secret generic ring-credentials \
  --from-literal=refresh-token=YOUR_RING_REFRESH_TOKEN \
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

#### Container images

Images are pulled from a private registry. Build and push each service:

```sh
cd services/<service-name>
docker build -t <registry>/housepanel/<service-name>:0.1.0 .
docker push <registry>/housepanel/<service-name>:0.1.0
```

Update the image references in `k8s/*.yaml` to match your registry.

## Development

See `firmware/DEVENV.md` for the firmware build environment.

Each service has a standard Python layout with `pyproject.toml` and a test suite:

```sh
cd services/<service-name>
pip install -e ../shared -e .[dev]
pytest
```

## Security notes

- `firmware/housepanel-giga/secrets.h` is git-ignored and never committed.
- K8s secrets (`*credentials*.json`, service account keys) are git-ignored.
- Webhook HMAC validation uses constant-time comparison (`hmac.compare_digest`).
- Ring refresh tokens are persisted exclusively in the K8s Secret and never logged.
