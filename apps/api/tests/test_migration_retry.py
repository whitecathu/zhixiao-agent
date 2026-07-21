import pytest
from sqlalchemy.exc import OperationalError

from app.db.migrate import run_migrations_with_retry


def connection_error() -> OperationalError:
    return OperationalError("connect", {}, ConnectionRefusedError("database is starting"))


def test_migration_retries_transient_connection_failure() -> None:
    calls = 0
    delays: list[float] = []

    def migrate() -> None:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise connection_error()

    run_migrations_with_retry(migrate, attempts=3, delay_seconds=0.25, sleep=delays.append)

    assert calls == 3
    assert delays == [0.25, 0.25]


def test_migration_does_not_retry_schema_error() -> None:
    calls = 0

    def migrate() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("invalid migration")

    with pytest.raises(RuntimeError, match="invalid migration"):
        run_migrations_with_retry(migrate, attempts=3, sleep=lambda _: None)

    assert calls == 1


def test_migration_raises_last_connectivity_error() -> None:
    def migrate() -> None:
        raise connection_error()

    with pytest.raises(OperationalError):
        run_migrations_with_retry(migrate, attempts=2, sleep=lambda _: None)
