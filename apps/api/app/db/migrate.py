"""Run Alembic migrations with bounded retries for transient DB connectivity."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from alembic import command
from alembic.config import Config
from sqlalchemy.exc import OperationalError


def _upgrade() -> None:
    command.upgrade(Config("alembic.ini"), "head")


def run_migrations_with_retry(
    migrate: Callable[[], None] = _upgrade,
    *,
    attempts: int = 15,
    delay_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Retry only transient connection failures; migration defects fail immediately."""
    if attempts < 1:
        raise ValueError("attempts must be at least one")

    for attempt in range(1, attempts + 1):
        try:
            migrate()
            return
        except OperationalError:
            if attempt == attempts:
                raise
            sleep(delay_seconds)


def main() -> None:
    attempts = int(os.getenv("DB_MIGRATION_MAX_ATTEMPTS", "15"))
    delay_seconds = float(os.getenv("DB_MIGRATION_RETRY_DELAY_SECONDS", "2"))
    run_migrations_with_retry(attempts=attempts, delay_seconds=delay_seconds)


if __name__ == "__main__":
    main()
