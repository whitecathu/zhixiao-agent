from zhixiao_agent.job_security import (
    ISSUED_AT_FIELD,
    NONCE_FIELD,
    SIGNATURE_FIELD,
    sign_job_fields,
    verify_job_fields,
)


def signed_fields(now: int = 1_700_000_000) -> dict[str, str]:
    fields = {
        "run_id": "42",
        "prompt": "inspect",
        ISSUED_AT_FIELD: str(now),
        NONCE_FIELD: "a" * 32,
    }
    fields[SIGNATURE_FIELD] = sign_job_fields(fields, "s" * 32)
    return fields


def test_job_signature_detects_tampering() -> None:
    fields = signed_fields()
    assert verify_job_fields(fields, "s" * 32, now=1_700_000_010)
    fields["permission_mode"] = "full"
    assert not verify_job_fields(fields, "s" * 32, now=1_700_000_010)


def test_job_signature_rejects_expired_job() -> None:
    fields = signed_fields()
    assert not verify_job_fields(fields, "s" * 32, now=1_700_004_000)
