from __future__ import annotations

import hashlib
import json
import random
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TaskSample:
    task_id: str
    instruction: str
    input: str
    output: str
    status: str
    risk: float
    usage_count: int


@dataclass(frozen=True, slots=True)
class InstructionRecord:
    task_id: str
    instruction: str
    input: str
    output: str


@dataclass(frozen=True, slots=True)
class DatasetPolicy:
    accepted_status: str = "succeeded"
    max_risk: float = 0.5
    min_usage_count: int = 1
    min_output_length: int = 1


_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[API_KEY]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[PHONE]"),
    (re.compile(r"(?i)(password|passwd|secret)\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~-]+"), "Bearer [TOKEN]"),
)


def redact_sensitive_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted.strip()


def build_instruction_dataset(
    samples: Iterable[TaskSample], policy: DatasetPolicy | None = None
) -> list[InstructionRecord]:
    selected_policy = policy or DatasetPolicy()
    records: list[InstructionRecord] = []
    seen_instructions: set[str] = set()
    for sample in samples:
        if sample.status != selected_policy.accepted_status:
            continue
        if sample.risk >= selected_policy.max_risk:
            continue
        if sample.usage_count < selected_policy.min_usage_count:
            continue
        instruction = redact_sensitive_text(sample.instruction)
        output = redact_sensitive_text(sample.output)
        if not instruction or len(output) < selected_policy.min_output_length:
            continue
        fingerprint = hashlib.sha256(instruction.casefold().encode("utf-8")).hexdigest()
        if fingerprint in seen_instructions:
            continue
        seen_instructions.add(fingerprint)
        records.append(
            InstructionRecord(
                task_id=sample.task_id,
                instruction=instruction,
                input=redact_sensitive_text(sample.input),
                output=output,
            )
        )
    return records


def split_dataset(
    records: Sequence[InstructionRecord], *, validation_ratio: float = 0.1, seed: int = 42
) -> tuple[list[InstructionRecord], list[InstructionRecord]]:
    if not 0 <= validation_ratio < 1:
        raise ValueError("validation_ratio must be in [0, 1)")
    shuffled = list(records)
    random.Random(seed).shuffle(shuffled)  # noqa: S311 - deterministic dataset partitioning
    validation_count = round(len(shuffled) * validation_ratio)
    if validation_ratio > 0 and len(shuffled) > 1:
        validation_count = max(1, validation_count)
    validation_count = min(validation_count, max(0, len(shuffled) - 1))
    return shuffled[validation_count:], shuffled[:validation_count]


def export_jsonl(records: Iterable[InstructionRecord], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(asdict(record), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def format_sft_prompt(record: InstructionRecord) -> str:
    input_section = f"\n\nInput:\n{record.input}" if record.input else ""
    return f"Instruction:\n{record.instruction}{input_section}\n\nResponse:\n{record.output}"
