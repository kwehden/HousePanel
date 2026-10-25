# eWeLink OAuth callback

The registered callback is `http://standpunkt:8765/ewelink/callback`.
`k8s/ewelink-callback.yaml` deploys one pod on standpunkt in the `housepanel`
namespace. It uses the host network to bind only `192.168.1.186:8765`, the
10G interface, since that port is outside the cluster's NodePort range.
Internal DNS for `standpunkt` must resolve to `192.168.1.186`. The receiver
does not listen on the other LAN interface. A ClusterIP Service also exposes
the receiver inside the cluster.

The pod runs as UID 10001 with health probes, a read-only root filesystem,
resource limits, and a persistent local-path volume. SQLite stores one-use
authorization state and the account's tokens in `/data/oauth.sqlite`, mode 0600.
The PVC is tied to standpunkt's local storage; it survives pod replacement but
does not provide recovery from loss of that node or its disk.

## Configure the application

The endpoint can run before credentials are available. Its landing page explains
that setup is pending; `/healthz` reports `oauth_configured` and `account_connected`
separately from service health.

Create a private JSON file with `app_id` and `app_secret` fields. Install only
that file as the `credentials.json` key of the `housepanel-ewelink-credentials`
Secret in namespace `housepanel`. The optional Secret mount lets Kubernetes
project the credentials without embedding them in the image or repository.

After the Secret is projected, generate an authorization link from the trusted
operator interface:

```sh
kubectl --context default -n housepanel exec deploy/housepanel-ewelink-callback -- \
  python /app/main.py authorize
```

Open the resulting link in a browser that can resolve and reach standpunkt.
The receiver validates and consumes the generated state, exchanges the short-lived
code immediately, and persists the returned tokens. It never logs request URLs,
authorization codes, tokens, or provider error bodies. There is no public
endpoint that starts authorization or exposes stored tokens.

## Outdoor sensor collection

The `outdoor-collector` sidecar reads only the selected SONOFF SNZB-02WD,
`Outdoor Temp Hum STZ` (`a4400440c8`, UIID 7033). It shares the existing private
token store and credentials mount with the callback. Expired access tokens are
refreshed with a signed `/v2/user/refresh` request. Rotated tokens are persisted
without overwriting a newer account authorization.

Once per minute, it calls the read-only specified-things endpoint and sends an
independent `OUTDOOR_TEMP` command to the existing transport adapter. The primary
understands this command; existing full-interface panels ignore it. The filament
`SYSMON_TEMP` feed and aggregator cache are unchanged. No actuator commands are
implemented. One-minute polling is about 43,200 device reads per 30 days, within
the documented free-app limit of 50,000 requests per month; other clients share
that quota.

`trigTime` is the source's millisecond report time. Polling the same reading
does not renew it. Offline devices, invalid readings, and reports at least an
hour old cannot display as live. The primary also blanks outdoor data after
three minutes without delivery from the collector. This one-hour source-age
policy accommodates battery-powered reporting without changing sensor settings.
Filament retains its five-minute freshness limit. The columns work independently.

After reconnect, outdoor data arrives on the next successful poll, normally
within one minute. It is not in the aggregator's HELLO snapshot. The private
`/data/outdoor-status.json` receipt records collector health and published values
without account credentials:

```sh
kubectl -n housepanel exec deploy/housepanel-ewelink-callback -c outdoor-collector -- \
  cat /data/outdoor-status.json
```

References: [specified-things API](https://github.com/CoolKit-Technologies/eWeLink-API/blob/main/en/APICenterV2.md#get-specified-things-list),
[OAuth and refresh](https://github.com/CoolKit-Technologies/eWeLink-API/blob/main/en/OAuth2.0.md#token-refresh).

## Build and deploy

Run from the repository root:

```sh
docker build -f services/ewelink-callback/Dockerfile -t laminarflow:30500/housepanel/ewelink-callback:VERSION .
docker push laminarflow:30500/housepanel/ewelink-callback:VERSION
```

Set the resulting immutable image digest in `k8s/ewelink-callback.yaml`, then:

```sh
kubectl --context default apply -f k8s/ewelink-callback.yaml
kubectl --context default -n housepanel rollout status deploy/housepanel-ewelink-callback
curl --noproxy '*' --fail http://standpunkt:8765/healthz
```

Tests use synthetic credentials and a fake provider:

```sh
python -m pytest tools/tests/test_ewelink_callback.py -q
```
