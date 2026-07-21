from __future__ import annotations

import json

import pytest

from zhixiao_agent.training import (
    DatasetPolicy,
    TaskSample,
    build_instruction_dataset,
    export_jsonl,
    split_dataset,
)


def test_dataset_pipeline_filters_redacts_deduplicates_and_splits(tmp_path) -> None:
    samples = [
        TaskSample(
            task_id="1",
            instruction="Fix login for alice@example.com",
            input="token sk-example_key_for_redaction",
            output="Done for 13800138000",
            status="succeeded",
            risk=0.1,
            usage_count=2,
        ),
        TaskSample("2", "bad", "", "bad", "failed", 0.1, 2),
        TaskSample("3", "Fix login for alice@example.com", "", "duplicate", "succeeded", 0.1, 2),
    ]

    dataset = build_instruction_dataset(samples, DatasetPolicy())
    train, validation = split_dataset(dataset, validation_ratio=0.5, seed=7)
    output = tmp_path / "dataset.jsonl"
    export_jsonl(dataset, output)

    assert len(dataset) == 1
    assert "[EMAIL]" in dataset[0].instruction
    assert "[API_KEY]" in dataset[0].input
    assert "[PHONE]" in dataset[0].output
    assert len(train) + len(validation) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["task_id"] == "1"


def test_split_rejects_invalid_ratio() -> None:
    with pytest.raises(ValueError, match="validation_ratio"):
        split_dataset([], validation_ratio=1.0)
