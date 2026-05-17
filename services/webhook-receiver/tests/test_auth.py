import hmac
import hashlib
from webhook_receiver.auth import validate_hmac_signature


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature():
    body = b'{"test": 1}'
    secret = "mysecret"
    assert validate_hmac_signature(body, _sign(body, secret), secret) is True


def test_invalid_signature():
    body = b'{"test": 1}'
    assert validate_hmac_signature(body, _sign(body, "wrong"), "correct") is False


def test_missing_header():
    assert validate_hmac_signature(b"body", None, "secret") is False


def test_wrong_prefix():
    body = b"body"
    assert validate_hmac_signature(body, "md5=abc123", "secret") is False


def test_malformed_header():
    assert validate_hmac_signature(b"body", "notavalidheader", "secret") is False
