"""Pure case/condition records shared by training and deployed evaluation."""

from dataclasses import dataclass

from itov.records import Document

ROLES = ("base_plain", "base_trigger", "adapter_plain", "adapter_trigger")


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    kind: str
    prompt: str
    negative_prompt: str
    expectation: str
    seeds: tuple[int, ...]

    @classmethod
    def from_validated(cls, value):
        return cls(**{**value, "seeds": tuple(value["seeds"])})

    def conditions(self, trigger):
        return tuple(
            EvaluationCondition(
                self.id,
                seed,
                role,
                ((trigger + " ") if role.endswith("trigger") else "") + self.prompt,
                self.negative_prompt,
            )
            for seed in self.seeds
            for role in ROLES
        )


@dataclass(frozen=True)
class EvaluationCondition:
    case_id: str
    seed: int
    role: str
    prompt: str
    negative_prompt: str

    def to_dict(self):
        return {
            "case_id": self.case_id,
            "seed": self.seed,
            "role": self.role,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
        }


def conditions(suite):
    return tuple(
        condition
        for case in suite["cases"]
        for condition in EvaluationCase.from_validated(case).conditions(suite["trigger"])
    )


@dataclass(frozen=True)
class EvaluationEvidence:
    """Validated curation, frozen suite and complete ordered diagnostic images."""

    curation: Document
    suite: Document
    images: tuple[Document, ...]

    def rows(self):
        return [image.to_dict() for image in self.images]
