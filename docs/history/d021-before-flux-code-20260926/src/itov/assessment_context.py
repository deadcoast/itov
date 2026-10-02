"""One technical assessment operation, with owned immutable records and final freshness."""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from itov import training, training_results
from itov.catalog import require
from itov.evidence_reads import EvidenceReads
from itov.records import Document
from itov.training_records import ValidatedTrainingResult


@dataclass(frozen=True)
class AssessmentContext:
    plan: Document
    run: Document
    folder: Path
    validated: ValidatedTrainingResult


@contextmanager
def assessment_context(config, plan_path):
    """Reuse validated values only inside this invocation; check disk before returning.

    Publication must occur after this context exits successfully. Execution's
    separate pre-submission and post-worker revalidation remain in their callers.
    """
    reads = EvidenceReads()
    with reads.capture():
        plan = training.load_plan(plan_path)
        record = training.read_record(config, plan_path)
        require(
            record["status"] in ("succeeded", "artifacts_validated"),
            "A successful owned training attempt with validated artifacts is required",
        )
        require(record.get("result_id"), "Training record has no bound result")
        folder = training.run_folder(config, plan)
        validated = training_results.validate_record(
            config, plan, folder, expected_result_id=record["result_id"]
        )
        yield AssessmentContext(Document.capture(plan), Document.capture(record), folder, validated)
        with training_results.boundary("input_freshness"):
            reads.verify()
