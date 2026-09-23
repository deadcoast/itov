"""Pure review decisions and case verdicts, independent of evidence I/O/promotion."""

from dataclasses import dataclass

from itov.catalog import array, identifier, integer, object_fields, require, text
from itov.records import Document

CRITERIA = {
    "activation",
    "prompt_adherence",
    "image_quality",
    "regression",
    "runtime_compatibility",
}
CASE_CRITERIA = {"activation", "prompt_adherence", "image_quality", "regression"}


@dataclass(frozen=True)
class ReviewCheck:
    criterion: str
    passed: bool
    evidence: tuple[Document, ...]


@dataclass(frozen=True)
class ReviewDecision:
    document: Document
    decision: str
    checks: tuple[ReviewCheck, ...]

    @classmethod
    def parse(cls, value, assessment_id, candidate_id):
        object_fields(
            value,
            {"version", "assessment_id", "candidate_id", "reviewer", "decision", "checks", "notes"}
            | (
                {"packet", "reviewer_kind", "cases"}
                if isinstance(value, dict) and value.get("version") in (2, 3)
                else set()
            )
            | (
                {"independent_of_training"}
                if isinstance(value, dict) and value.get("version") == 2
                else set()
            )
            | (
                {"method", "limitations"}
                if isinstance(value, dict) and value.get("version") == 3
                else set()
            ),
            "quality review",
        )
        require(
            type(value["version"]) is int
            and value["version"] in (1, 2, 3)
            and value["assessment_id"] == assessment_id,
            "Quality review is stale or unsupported",
        )
        require(value["candidate_id"] == candidate_id, "Quality review candidate export differs")
        text(value["reviewer"], "reviewer")
        text(value["notes"], "review notes")
        require(value["decision"] in ("approve", "reject"), "Invalid review decision")
        checks = []
        for check in array(value["checks"], "review checks"):
            object_fields(check, {"criterion", "passed", "evidence"}, "review check")
            text(check["criterion"], "review criterion")
            require(type(check["passed"]) is bool, "Review verdict must be boolean")
            refs = array(check["evidence"], "review evidence")
            require(1 <= len(refs) <= 16, "Each review criterion needs evidence")
            checks.append(
                ReviewCheck(
                    check["criterion"],
                    check["passed"],
                    tuple(Document.capture(ref) for ref in refs),
                )
            )
        require(
            len(checks) == len(CRITERIA) and {c.criterion for c in checks} == CRITERIA,
            "Review must cover every acceptance criterion exactly once",
        )
        return cls(Document.capture(value), value["decision"], tuple(checks))

    @property
    def approved(self):
        return self.decision == "approve" and all(check.passed for check in self.checks)


@dataclass(frozen=True)
class CaseReview:
    case_id: str
    seed: int
    verdicts: tuple[tuple[str, bool], ...]
    notes: str

    @classmethod
    def parse(cls, value):
        object_fields(value, {"case_id", "seed", "verdicts", "notes"}, "case review")
        identifier(value["case_id"], "reviewed case")
        integer(value["seed"], "reviewed seed")
        object_fields(value["verdicts"], CASE_CRITERIA, "case verdicts")
        require(
            all(type(v) is bool for v in value["verdicts"].values()),
            "Every case criterion needs a boolean verdict",
        )
        text(value["notes"], "case review notes")
        return cls(
            value["case_id"],
            value["seed"],
            tuple(sorted(value["verdicts"].items())),
            value["notes"],
        )


def review_coverage(value, current):
    if value["version"] == 2:
        require(
            value["reviewer_kind"] == "human" and value["independent_of_training"] is True,
            "Legacy v2 attestation is invalid; use v3 for evidence-backed assistant review",
        )
        require(
            value["reviewer"].strip().casefold() != current["curator"].strip().casefold(),
            "Legacy v2 independence declaration conflicts with curator identity",
        )
    else:
        require(value["reviewer_kind"] in ("assistant", "human"), "Unsupported reviewer kind")
        for key in ("method", "limitations"):
            text(value[key], "review " + key)
            require(len(value[key]) <= 4096, "Review method/limitations exceed supported bounds")
    wanted = [(c["id"], s) for c in current["suite"]["cases"] for s in c["seeds"]]
    rows = tuple(CaseReview.parse(row) for row in array(value["cases"], "case reviews"))
    require(
        sorted((row.case_id, row.seed) for row in rows) == sorted(wanted),
        "Review must cover every case and seed exactly once",
    )
    return all(all(passed for _, passed in row.verdicts) for row in rows)
