import base64
import hashlib
import hmac

from apps.lineapp.client import verify_signature
from apps.lineapp.quota import QuotaStatus, planned_messages


def test_quota_remaining_and_exceed():
    q = QuotaStatus(limit=200, used=150, planned=60)
    assert q.remaining == 50
    assert q.remaining_after == -10
    assert q.would_exceed is True
    assert QuotaStatus(limit=200, used=150, planned=50).would_exceed is False


def test_quota_warn_threshold():
    assert QuotaStatus(limit=200, used=160).warn(0.8) is True
    assert QuotaStatus(limit=200, used=159).warn(0.8) is False
    assert QuotaStatus(limit=200, used=100, planned=60).warn(0.8) is True


def test_quota_unlimited_plan():
    q = QuotaStatus(limit=None, used=5000, planned=100)
    assert q.remaining is None
    assert q.would_exceed is False
    assert q.warn() is False
    assert q.to_dict()["percent"] == 0


def test_quota_used_never_negative_remaining():
    assert QuotaStatus(limit=200, used=250).remaining == 0
    assert QuotaStatus(limit=200, used=250).to_dict()["percent"] == 100


def test_planned_messages_is_sends_times_recipients():
    assert planned_messages(100, 2) == 200
    assert planned_messages(0, 3) == 0
    assert planned_messages(-5, 1) == 0


def _sign(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def test_verify_signature():
    body = b'{"events":[]}'
    sig = _sign("secret", body)
    assert verify_signature("secret", body, sig) is True
    assert verify_signature("secret", body + b" ", sig) is False
    assert verify_signature("other", body, sig) is False
    assert verify_signature("secret", body, None) is False
    assert verify_signature("", body, sig) is False
