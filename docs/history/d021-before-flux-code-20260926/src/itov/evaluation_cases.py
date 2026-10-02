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
    strength_milli: int | None = None

    def to_dict(self):
        return {
            "case_id": self.case_id,
            "seed": self.seed,
            "role": self.role,
            "prompt": self.prompt,
            "negative_prompt": self.negative_prompt,
            **({"strength_milli": self.strength_milli} if self.strength_milli is not None else {}),
        }


def conditions(suite, *, baseline=False):
    if suite.get("version") == 2:
        from itov.evaluation_corpus import validate_suite

        validate_suite(suite)
        roles = [(role, 0) for role in ROLES[:2]]
        if not baseline:
            roles += [
                (role, strength) for strength in suite["strengths_milli"] for role in ROLES[2:]
            ]
        return tuple(
            EvaluationCondition(
                case["id"],
                seed,
                role,
                ((suite["trigger"] + " ") if role.endswith("trigger") else "") + case["prompt"],
                case["negative_prompt"],
                strength,
            )
            for case in suite["cases"]
            for seed in case["seeds"]
            for role, strength in roles
        )
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
