"""Privacy-aware instruction-data, LoRA training, evaluation, and model routing."""

from .dataset import (
    DatasetPolicy,
    InstructionRecord,
    TaskSample,
    build_instruction_dataset,
    export_jsonl,
    format_sft_prompt,
    redact_sensitive_text,
    split_dataset,
)
from .evaluation import EvaluationCase, EvaluationReport, evaluate_predictions
from .registry import FileModelRegistry, RegisteredModel
from .routing import ABModelRouter
from .trainer import (
    LoraTrainingConfig,
    TrainingDependencyError,
    TrainingResult,
    VLLMServiceConfig,
    build_vllm_command,
    train_lora,
)

__all__ = [
    "ABModelRouter",
    "DatasetPolicy",
    "EvaluationCase",
    "EvaluationReport",
    "FileModelRegistry",
    "InstructionRecord",
    "LoraTrainingConfig",
    "RegisteredModel",
    "TaskSample",
    "TrainingDependencyError",
    "TrainingResult",
    "VLLMServiceConfig",
    "build_instruction_dataset",
    "build_vllm_command",
    "evaluate_predictions",
    "export_jsonl",
    "format_sft_prompt",
    "redact_sensitive_text",
    "split_dataset",
    "train_lora",
]
