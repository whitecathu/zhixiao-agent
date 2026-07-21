from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    id: str
    expected: str
    prediction: str
    format: str = "text"


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    total: int
    accuracy: float
    format_compliance: float
    citation_coverage: float
    hallucination_rate: float


_CITATION = re.compile(r"(?:\[source:[^\]]+\]|\[[0-9]+\]|https?://\S+)", re.IGNORECASE)


def evaluate_predictions(cases: list[EvaluationCase]) -> EvaluationReport:
    if not cases:
        return EvaluationReport(0, 0.0, 0.0, 0.0, 0.0)
    correct = sum(_matches(case.expected, case.prediction, case.format) for case in cases)
    compliant = sum(_is_compliant(case.prediction, case.format) for case in cases)
    cited = sum(bool(_CITATION.search(case.prediction)) for case in cases)
    total = len(cases)
    citation_coverage = cited / total
    return EvaluationReport(
        total=total,
        accuracy=correct / total,
        format_compliance=compliant / total,
        citation_coverage=citation_coverage,
        hallucination_rate=1.0 - citation_coverage,
    )


def _matches(expected: str, prediction: str, output_format: str) -> bool:
    if output_format == "json":
        try:
            return bool(json.loads(expected) == json.loads(prediction))
        except json.JSONDecodeError:
            return False
    return expected.strip().casefold() in prediction.strip().casefold()


def _is_compliant(prediction: str, output_format: str) -> bool:
    if output_format == "json":
        try:
            json.loads(prediction)
        except json.JSONDecodeError:
            return False
    elif output_format == "markdown":
        return bool(re.search(r"(?:^|\n)(?:#{1,6}\s|[-*]\s|\d+\.\s)", prediction))
    return bool(prediction.strip())
