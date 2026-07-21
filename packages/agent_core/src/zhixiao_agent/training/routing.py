from __future__ import annotations

import hashlib
import math


class ABModelRouter:
    """Deterministic weighted routing so retries keep the same model variant."""

    def __init__(self, variants: dict[str, float], *, salt: str = "zhixiao") -> None:
        if not variants or any(weight <= 0 for weight in variants.values()):
            raise ValueError("Variant weights must be positive")
        if not math.isclose(sum(variants.values()), 1.0, abs_tol=1e-9):
            raise ValueError("Variant weights must sum to 1")
        self._variants = tuple(variants.items())
        self._salt = salt

    def route(self, task_id: str) -> str:
        digest = hashlib.sha256(f"{self._salt}:{task_id}".encode()).digest()
        bucket = int.from_bytes(digest[:8], "big") / 2**64
        cumulative = 0.0
        for variant, weight in self._variants:
            cumulative += weight
            if bucket < cumulative:
                return variant
        return self._variants[-1][0]
