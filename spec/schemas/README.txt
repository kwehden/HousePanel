HousePanel Webhook Schemas
==========================

camera-webhook-v1.json
----------------------
Endpoint:      POST /v1/webhooks/camera
Auth header:   X-HousePanel-Signature: sha256=<hex-digest>
               HMAC-SHA256 of the raw request body using the shared secret
               stored in K8s Secret housepanel/housepanel-webhook-secrets
               (key: CAMERA_WEBHOOK_SECRET).
Responses:
  202  Accepted — event queued for processing
  400  Bad Request — malformed JSON body
  401  Unauthorized — missing or invalid HMAC signature
  422  Unprocessable Entity — schema validation failure

Schema ownership: HousePanel. Stable from first release.
Breaking changes: introduced as /v2/ path variants only.
/v1/ remains supported until explicit deprecation notice.

Implementing services must:
1. POST to this endpoint with Content-Type: application/json
2. Include the X-HousePanel-Signature header on every request
3. Treat a 202 response as confirmation the event was accepted
4. Retry on 5xx responses; do not retry on 4xx responses

system-alert-webhook-v1.json
-----------------------------
Endpoint:      POST /v1/webhooks/system-alert
Auth header:   X-HousePanel-Signature: sha256=<hex-digest>
               HMAC-SHA256 of the raw request body using the shared secret
               stored in K8s Secret housepanel/housepanel-webhook-secrets
               (key: WEBHOOK_SECRET_ATH).
Responses:
  202  Accepted — event queued for processing
  400  Bad Request — malformed JSON body
  401  Unauthorized — missing or invalid HMAC signature
  422  Unprocessable Entity — schema validation failure

Schema ownership: HousePanel. ArduinoTempHumUbuntu implements against this.
Breaking changes: introduced as /v2/ path variants only.
/v1/ remains supported until explicit deprecation notice.

Implementing services must:
1. POST to this endpoint with Content-Type: application/json
2. Include the X-HousePanel-Signature header on every request
3. Treat a 202 response as confirmation the event was accepted
4. Retry on 5xx responses; do not retry on 4xx responses
