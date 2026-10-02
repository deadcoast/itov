"""Validated training data in memory, separate from saved controller/result schemas."""

from dataclasses import dataclass

from itov.evaluation_cases import EvaluationEvidence
from itov.records import Document


@dataclass(frozen=True)
class WeightSnapshot:
    """The exact hash-verified bytes whose tensors passed finite/rank validation."""

    raw: bytes
    sha256: str
    rank: int
    integrity: Document


@dataclass(frozen=True)
class ValidatedTrainingResult:
    result: Document
    dataset: Document
    weights: WeightSnapshot
    evaluation: EvaluationEvidence | None

    def to_dict(self):
        return {
            "result": self.result.to_dict(),
            "dataset": self.dataset.to_dict(),
            "integrity": self.weights.integrity.to_dict(),
        }
