from __future__ import annotations

import base64
from typing import Callable

from shared.logging import make_logger, log_event

logger = make_logger("ring-integration")


def make_token_updated_callback(
    namespace: str = "housepanel",
    secret_name: str = "housepanel-ring-secrets",
) -> Callable[[dict], None]:
    """Return a callback that persists the refreshed Ring token to K8s on every auth refresh."""

    def token_updated(token: dict) -> None:
        refresh_token = token.get("refresh_token", "")
        if not refresh_token:
            return
        try:
            from kubernetes import client, config  # type: ignore[import]

            config.load_incluster_config()
            v1 = client.CoreV1Api()
            v1.patch_namespaced_secret(
                name=secret_name,
                namespace=namespace,
                body={
                    "data": {
                        "RING_REFRESH_TOKEN": base64.b64encode(
                            refresh_token.encode()
                        ).decode()
                    }
                },
            )
            log_event(logger, "ring_token_refreshed")
        except Exception as exc:  # noqa: BLE001
            # Log error class only — never the token value.
            log_event(
                logger,
                "ring_token_persist_failed",
                level="error",
                error_class=type(exc).__name__,
            )

    return token_updated
