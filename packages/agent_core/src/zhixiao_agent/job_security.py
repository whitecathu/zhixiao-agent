"""Integrity protection for API-to-Worker Redis jobs."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import Mapping

SIGNATURE_FIELD = "job_signature"
ISSUED_AT_FIELD = "job_issued_at"
NONCE_FIELD = "job_nonce"


def canonical_job_payload(fields: Mapping[str, str]) -> bytes:
    payload = {
        str(key): str(value)
        for key, value in fields.items()
        if key != SIGNATURE_FIELD
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_job_fields(fields: Mapping[str, str], secret: str) -> str:
    if len(secret) < 24:
        raise ValueError("worker job signing secret must be at least 24 characters")
    return hmac.new(
        secret.encode("utf-8"),
        canonical_job_payload(fields),
        hashlib.sha256,
    ).hexdigest()


def verify_job_fields(
    fields: Mapping[str, str],
    secret: str,
    *,
    now: int | None = None,
    max_age_seconds: int = 3_600,
) -> bool:
    signature = fields.get(SIGNATURE_FIELD, "")
    issued_at = fields.get(ISSUED_AT_FIELD, "")
    nonce = fields.get(NONCE_FIELD, "")
    if not signature or not issued_at or len(nonce) < 16:
        return False
    try:
        issued = int(issued_at)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if issued > current + 60 or current - issued > max_age_seconds:
        return False
    try:
        expected = sign_job_fields(fields, secret)
    except ValueError:
        return False
    return hmac.compare_digest(signature, expected)
