from __future__ import annotations

import argparse
import importlib
import inspect
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dataset import InstructionRecord, format_sft_prompt


class TrainingDependencyError(RuntimeError):
    """Raised when the GPU training extra has not been installed."""


@dataclass(frozen=True, slots=True)
class LoraTrainingConfig:
    base_model: str
    output_dir: Path
    epochs: float = 3.0
    batch_size: int = 2
    gradient_accumulation_steps: int = 16
    learning_rate: float = 1e-4
    rank: int = 16
    alpha: int = 32
    dropout: float = 0.05
    max_sequence_length: int = 2_048
    target_modules: tuple[str, ...] = (
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    )

    def __post_init__(self) -> None:
        if not self.base_model:
            raise ValueError("base_model must not be empty")
        if self.rank < 1 or self.epochs <= 0 or self.batch_size < 1:
            raise ValueError("Training sizes and epochs must be positive")


@dataclass(frozen=True, slots=True)
class TrainingResult:
    adapter_path: Path
    base_model: str
    samples: int
    metrics: dict[str, float] = field(default_factory=dict)


DependencyLoader = Callable[[str], Any]


def _load_training_dependencies(loader: DependencyLoader) -> dict[str, Any]:
    modules: dict[str, Any] = {}
    try:
        for name in ("torch", "datasets", "transformers", "peft", "trl"):
            modules[name] = loader(name)
    except ImportError as exc:
        raise TrainingDependencyError(
            "LoRA training requires the optional 'training' dependencies; "
            "install zhixiao-agent[training] in a GPU environment."
        ) from exc
    return modules


def train_lora(
    records: Sequence[InstructionRecord],
    config: LoraTrainingConfig,
    *,
    dependency_loader: DependencyLoader = importlib.import_module,
) -> TrainingResult:
    """Run PEFT/TRL supervised fine-tuning; heavy libraries are loaded on demand."""

    modules = _load_training_dependencies(dependency_loader)
    if not records:
        raise ValueError("At least one training record is required")
    transformers = modules["transformers"]
    peft = modules["peft"]
    datasets = modules["datasets"]
    trl = modules["trl"]
    torch = modules["torch"]

    tokenizer = transformers.AutoTokenizer.from_pretrained(config.base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    cuda = getattr(torch, "cuda", None)
    bf16_supported = bool(
        cuda and cuda.is_available() and getattr(cuda, "is_bf16_supported", lambda: False)()
    )
    dtype = getattr(torch, "bfloat16", None) if bf16_supported else None
    model = transformers.AutoModelForCausalLM.from_pretrained(
        config.base_model,
        torch_dtype=dtype,
        device_map="auto",
    )
    lora_config = peft.LoraConfig(
        r=config.rank,
        lora_alpha=config.alpha,
        lora_dropout=config.dropout,
        target_modules=list(config.target_modules),
        task_type="CAUSAL_LM",
    )
    model = peft.get_peft_model(model, lora_config)
    dataset = datasets.Dataset.from_list(
        [{"text": format_sft_prompt(record)} for record in records]
    )
    argument_values = {
        "output_dir": str(config.output_dir),
        "num_train_epochs": config.epochs,
        "per_device_train_batch_size": config.batch_size,
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "learning_rate": config.learning_rate,
        "logging_steps": 10,
        "save_strategy": "epoch",
        "bf16": bf16_supported,
        "report_to": [],
    }
    trainer_parameters = inspect.signature(trl.SFTTrainer).parameters
    if "processing_class" in trainer_parameters and hasattr(trl, "SFTConfig"):
        argument_values.update(dataset_text_field="text", max_length=config.max_sequence_length)
        arguments = _call_supported(trl.SFTConfig, argument_values)
    else:
        arguments = _call_supported(transformers.TrainingArguments, argument_values)
    trainer_values: dict[str, Any] = {
        "model": model,
        "args": arguments,
        "train_dataset": dataset,
    }
    if "processing_class" in trainer_parameters:
        trainer_values["processing_class"] = tokenizer
    elif "tokenizer" in trainer_parameters:
        trainer_values["tokenizer"] = tokenizer
    if "dataset_text_field" in trainer_parameters:
        trainer_values["dataset_text_field"] = "text"
    if "max_seq_length" in trainer_parameters:
        trainer_values["max_seq_length"] = config.max_sequence_length
    trainer = trl.SFTTrainer(**trainer_values)
    output = trainer.train()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(config.output_dir))
    metrics = {
        str(key): float(value)
        for key, value in getattr(output, "metrics", {}).items()
        if isinstance(value, (int, float))
    }
    _write_training_metadata(config, metrics, len(records))
    return TrainingResult(config.output_dir, config.base_model, len(records), metrics)


@dataclass(frozen=True, slots=True)
class VLLMServiceConfig:
    model: str
    served_model_name: str
    host: str = "0.0.0.0"  # noqa: S104 - container service intentionally binds all interfaces
    port: int = 8081
    tensor_parallel_size: int = 1
    api_key_env: str = "VLLM_API_KEY"


def build_vllm_command(config: VLLMServiceConfig) -> tuple[str, ...]:
    if not 1 <= config.port <= 65_535:
        raise ValueError("port must be in 1..65535")
    return (
        "python",
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--model",
        config.model,
        "--served-model-name",
        config.served_model_name,
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--tensor-parallel-size",
        str(config.tensor_parallel_size),
    )


def _call_supported(factory: Callable[..., Any], values: dict[str, Any]) -> Any:
    parameters = inspect.signature(factory).parameters
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        return factory(**values)
    return factory(**{key: value for key, value in values.items() if key in parameters})


def _write_training_metadata(
    config: LoraTrainingConfig, metrics: dict[str, float], sample_count: int
) -> None:
    payload = {
        "base_model": config.base_model,
        "epochs": config.epochs,
        "batch_size": config.batch_size,
        "gradient_accumulation_steps": config.gradient_accumulation_steps,
        "learning_rate": config.learning_rate,
        "rank": config.rank,
        "alpha": config.alpha,
        "dropout": config.dropout,
        "max_sequence_length": config.max_sequence_length,
        "target_modules": list(config.target_modules),
        "sample_count": sample_count,
        "metrics": metrics,
    }
    (config.output_dir / "training_config.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metric_lines = "\n".join(f"- {name}: {value:.6g}" for name, value in sorted(metrics.items()))
    (config.output_dir / "MODEL_CARD.md").write_text(
        "# Zhixiao LoRA Adapter\n\n"
        f"- Base model: `{config.base_model}`\n"
        f"- Training samples: {sample_count}\n\n"
        "## Evaluation metrics\n\n"
        f"{metric_lines or '- No metrics reported by the trainer.'}\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a Zhixiao LoRA adapter")
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=float, default=3.0)
    args = parser.parse_args()
    records: list[InstructionRecord] = []
    with args.dataset.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                records.append(InstructionRecord(**json.loads(line)))
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid instruction record at line {line_number}") from exc
    result = train_lora(
        records,
        LoraTrainingConfig(
            base_model=args.base_model,
            output_dir=args.output,
            epochs=args.epochs,
        ),
    )
    print(json.dumps({"adapter_path": str(result.adapter_path), "metrics": result.metrics}))


if __name__ == "__main__":
    main()
