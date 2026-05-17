from __future__ import annotations
import hashlib
import hmac


def validate_hmac_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    if not signature_header:
        return False
    if not signature_header.startswith("sha256="):
        return False
    provided_hex = signature_header[len("sha256="):]
    expected = hmac.new(
        key=secret.encode(),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    try:
        return hmac.compare_digest(expected, provided_hex)
    except (TypeError, ValueError):
        return False
