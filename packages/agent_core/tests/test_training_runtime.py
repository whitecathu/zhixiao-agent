from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from zhixiao_agent.training import (
    ABModelRouter,
    EvaluationCase,
    FileModelRegistry,
    InstructionRecord,
    LoraTrainingConfig,
    TrainingDependencyError,
    evaluate_predictions,
    train_lora,
)


def test_evaluation_computes_accuracy_format_and_citation_metrics() -> None:
    report = evaluate_predictions(
        [
            EvaluationCase("1", expected="yes", prediction="yes [source:1]", format="text"),
            EvaluationCase("2", expected='{"ok": true}', prediction='{"ok": true}', format="json"),
        ]
    )

    assert report.total == 2
    assert report.accuracy == pytest.approx(1.0)
    assert report.format_compliance == pytest.approx(1.0)
    assert report.citation_coverage == pytest.approx(0.5)
    assert report.hallucination_rate == pytest.approx(0.5)


def test_file_registry_versions_models_atomically(tmp_path) -> None:
    registry = FileModelRegistry(tmp_path / "registry.json")
    first = registry.register("zhixiao", "adapter/v1", {"accuracy": 0.8})
    second = registry.register("zhixiao", "adapter/v2", {"accuracy": 0.9})

    assert first.version == 1
    assert second.version == 2
    assert registry.latest("zhixiao") == second
    assert len(json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))) == 2


def test_ab_router_is_stable_and_validates_weights() -> None:
    router = ABModelRouter({"base": 0.5, "lora": 0.5}, salt="experiment-1")

    assert router.route("task-42") == router.route("task-42")
    with pytest.raises(ValueError, match="sum to 1"):
        ABModelRouter({"base": 0.2, "lora": 0.2})


def test_training_entrypoint_has_clear_optional_dependency_error(tmp_path) -> None:
    config = LoraTrainingConfig(base_model="tiny", output_dir=tmp_path / "out")

    with pytest.raises(TrainingDependencyError, match="training"):
        train_lora(
            [], config, dependency_loader=lambda _: (_ for _ in ()).throw(ImportError("missing"))
        )


def test_training_entrypoint_runs_with_injected_tiny_backend(tmp_path) -> None:
    class Tokenizer:
        pad_token = None
        eos_token = "<eos>"

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(name):
            return Tokenizer()

    class AutoModel:
        @staticmethod
        def from_pretrained(name, **kwargs):
            return object()

    class Dataset:
        @staticmethod
        def from_list(rows):
            return rows

    class Trainer:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def train(self):
            return SimpleNamespace(metrics={"train_loss": 0.1})

        def save_model(self, path):
            self.saved = path

    modules = {
        "torch": SimpleNamespace(bfloat16="bf16"),
        "datasets": SimpleNamespace(Dataset=Dataset),
        "transformers": SimpleNamespace(
            AutoTokenizer=AutoTokenizer,
            AutoModelForCausalLM=AutoModel,
            TrainingArguments=lambda **kwargs: kwargs,
        ),
        "peft": SimpleNamespace(
            LoraConfig=lambda **kwargs: kwargs,
            get_peft_model=lambda model, config: model,
        ),
        "trl": SimpleNamespace(SFTTrainer=Trainer),
    }
    config = LoraTrainingConfig(base_model="tiny", output_dir=tmp_path / "adapter")

    result = train_lora(
        [InstructionRecord("1", "fix", "input", "output")],
        config,
        dependency_loader=modules.__getitem__,
    )

    assert result.samples == 1
    assert result.metrics == {"train_loss": 0.1}
    assert result.adapter_path.is_dir()
    assert (result.adapter_path / "training_config.json").is_file()
    model_card = (result.adapter_path / "MODEL_CARD.md").read_text(encoding="utf-8")
    assert "Base model: `tiny`" in model_card
