"""Installed command recipes with explicit inputs and no automatic execution."""

from pathlib import Path

TOPICS = (
    "overview",
    "setup",
    "generation",
    "models",
    "training",
    "evaluation",
    "catalog",
    "recovery",
)


def command(config, label, *argv, needs=(), when="After inspecting the result"):
    return {
        "label": label,
        "argv": ["itov", *map(str, argv), "--config", str(config.file)],
        "needs": list(needs),
        "when": when,
    }


def guide(config_path, topic):
    from types import SimpleNamespace

    config = SimpleNamespace(file=Path(config_path).absolute())
    root = config.file.parent

    def step(label, *argv, **kwargs):
        return command(config, label, *argv, **kwargs)

    recipes = {
        "overview": (
            "Choose a task; inspect durable state before starting another attempt.",
            [
                step("Inspect workspace", "workspace", "status"),
                *[step(name.capitalize(), "workspace", "guide", name) for name in TOPICS[1:]],
            ],
        ),
        "setup": (
            (
                "Supply your local ComfyUI installation and interpreter. The CLI does "
                "not install models or optional environments."
            ),
            [
                {
                    "label": "Initialize once",
                    "argv": [
                        "itov",
                        "init",
                        str(root),
                        "--comfyui-root",
                        "COMFYUI_ROOT",
                        "--comfyui-python",
                        "COMFYUI_PYTHON",
                    ],
                    "needs": ["COMFYUI_ROOT", "COMFYUI_PYTHON"],
                    "when": "For a new workspace only; existing configuration is preserved",
                },
                step("Check local installation", "doctor", "--offline"),
                step("Inspect launch arguments", "server", "start", "--print-command"),
                step(
                    "Start the configured server",
                    "server",
                    "start",
                    when="In a separate terminal; Ctrl+C stops this server",
                ),
                step("Check the server", "doctor"),
                step("Create neutral inputs", "workspace", "starter"),
            ],
        ),
        "generation": (
            (
                "Complete a neutral image-copy session using packaged inputs. This "
                "tests image I/O, not model generation or quality."
            ),
            [
                step("Create or verify starter inputs", "workspace", "starter"),
                step(
                    "Validate against the server",
                    "workflow",
                    "validate",
                    root / "workflows/itov-starter.api.json",
                    "--live",
                ),
                step(
                    "Submit one image-copy job",
                    "job",
                    "run",
                    root / "workflows/itov-starter.api.json",
                    when="After server validation; an explicit new submission",
                ),
                step("Find its durable record", "workspace", "status", "--kind", "jobs"),
                step(
                    "Inspect the returned record",
                    "workspace",
                    "inspect",
                    "JOB_RECORD",
                    needs=["JOB_RECORD"],
                ),
                step(
                    "Observe or replay the same job",
                    "job",
                    "wait",
                    "JOB_RECORD",
                    needs=["JOB_RECORD"],
                    when="Use its exact record; do not submit a duplicate",
                ),
                step("Continue through catalog batching", "workspace", "guide", "catalog"),
            ],
        ),
        "models": (
            (
                "Describe a base image with inference spec, or provide a declared "
                "model specification and exact installed asset hashes. "
                "V1 media plans use batch execution; v2/v3 image inference "
                "has its own owner. Each prepare/plan result supplies the next "
                "commands. FLUX.2 Klein is experimental; its GPU and visual "
                "qualification remain pending."
            ),
            [
                step("Inspect inference capabilities", "inference", "capabilities"),
                step(
                    "Inspect experimental FLUX assets and limits",
                    "inference",
                    "capabilities",
                    "--model",
                    "flux2-klein-4b-fp8",
                ),
                step(
                    "Describe and save a base image request",
                    "inference",
                    "spec",
                    "--prompt",
                    "IMAGE_DESCRIPTION",
                    "--seed",
                    "0",
                    "--save",
                    needs=["IMAGE_DESCRIPTION"],
                ),
                step(
                    "Prepare image model assets",
                    "inference",
                    "prepare",
                    "INFERENCE_SPEC",
                    needs=["INFERENCE_SPEC"],
                ),
                step(
                    "Plan image inference",
                    "inference",
                    "plan",
                    "INFERENCE_SPEC",
                    "--save",
                    needs=["INFERENCE_SPEC"],
                ),
                step(
                    "Prepare image-to-video", "video", "prepare", "VIDEO_SPEC", needs=["VIDEO_SPEC"]
                ),
                step("Plan video", "video", "plan", "VIDEO_SPEC", "--save", needs=["VIDEO_SPEC"]),
                step("Prepare audio", "audio", "prepare", "AUDIO_SPEC", needs=["AUDIO_SPEC"]),
                step("Plan audio", "audio", "plan", "AUDIO_SPEC", "--save", needs=["AUDIO_SPEC"]),
                step("Inspect saved plans", "workspace", "status"),
            ],
        ),
        "training": (
            (
                "Use reviewed local images, captions, provenance, independent "
                "validation cases and pinned base/config/tokenizer assets. Data "
                "selection and training are explicit; failed runs are retained. The "
                "training spec names its separate Python environment."
            ),
            [
                step(
                    "Check image dependencies",
                    "workspace",
                    "dependencies",
                    "dataset",
                    "--python",
                    "IMAGE_PYTHON",
                    "--save",
                    needs=["IMAGE_PYTHON"],
                ),
                step(
                    "Check trainer dependencies",
                    "workspace",
                    "dependencies",
                    "training",
                    "--python",
                    "TRAINING_PYTHON",
                    "--save",
                    needs=["TRAINING_PYTHON"],
                ),
                step(
                    "Inspect declared source data",
                    "dataset",
                    "inspect",
                    "DATASET_DECLARATION",
                    "--image-python",
                    "IMAGE_PYTHON",
                    "--save",
                    needs=["DATASET_DECLARATION", "IMAGE_PYTHON"],
                ),
                step(
                    "Freeze the completed data review",
                    "dataset",
                    "freeze",
                    "DATA_REVIEW",
                    "--save",
                    needs=["DATA_REVIEW"],
                ),
                step(
                    "Import the frozen declaration",
                    "dataset",
                    "import",
                    "IMPORT_DECLARATION",
                    "--source-root",
                    "SOURCE_ROOT",
                    "--image-python",
                    "IMAGE_PYTHON",
                    needs=["IMPORT_DECLARATION", "SOURCE_ROOT", "IMAGE_PYTHON"],
                ),
                step(
                    "Plan configured training",
                    "training",
                    "plan",
                    "TRAINING_SPEC",
                    "--save",
                    needs=["TRAINING_SPEC"],
                ),
                step(
                    "Inspect the saved plan",
                    "workspace",
                    "inspect",
                    "TRAINING_PLAN",
                    needs=["TRAINING_PLAN"],
                ),
                step(
                    "Run the explicit attempt",
                    "training",
                    "run",
                    "TRAINING_PLAN",
                    "--gpu",
                    "GPU_UUID",
                    needs=["TRAINING_PLAN", "GPU_UUID"],
                ),
                step(
                    "Inspect result and failure boundaries",
                    "training",
                    "status",
                    "TRAINING_PLAN",
                    needs=["TRAINING_PLAN"],
                ),
                step(
                    "Assess technical artifacts",
                    "evaluation",
                    "assess",
                    "TRAINING_PLAN",
                    "--save",
                    needs=["TRAINING_PLAN"],
                ),
                step(
                    "Export candidate",
                    "training",
                    "candidate",
                    "TRAINING_PLAN",
                    "--save",
                    needs=["TRAINING_PLAN"],
                ),
                step("Continue to deployed review", "workspace", "guide", "evaluation"),
            ],
        ),
        "evaluation": (
            (
                "Bind the exact training plan to a frozen v2 evaluation corpus. "
                "Render every declared condition, inspect all images and comparisons, "
                "and retain failures and uncertainty. Technical success cannot "
                "activate a model."
            ),
            [
                step(
                    "Plan deployed comparison",
                    "evaluation",
                    "plan",
                    "EVALUATION_SPEC",
                    "--save",
                    needs=["EVALUATION_SPEC"],
                ),
                step(
                    "Run declared conditions",
                    "evaluation",
                    "run",
                    "EVALUATION_PLAN",
                    needs=["EVALUATION_PLAN"],
                ),
                step(
                    "Inspect saved execution",
                    "workspace",
                    "inspect",
                    "EVALUATION_PLAN",
                    needs=["EVALUATION_PLAN"],
                ),
                step(
                    "Replay technical evidence",
                    "evaluation",
                    "replay",
                    "EVALUATION_PLAN",
                    "--save",
                    needs=["EVALUATION_PLAN"],
                ),
                step(
                    "Probe actual loader mapping",
                    "evaluation",
                    "mapping",
                    "EVALUATION_PLAN",
                    "--save",
                    needs=["EVALUATION_PLAN"],
                    when="CPU checkpoint load requires sufficient host memory",
                ),
                step(
                    "Create complete review packet",
                    "evaluation",
                    "review-packet",
                    "EVALUATION_PLAN",
                    "--mapping",
                    "MAPPING",
                    "--save",
                    needs=["EVALUATION_PLAN", "MAPPING"],
                ),
                step(
                    "Record the completed review",
                    "evaluation",
                    "decide",
                    "PACKET",
                    "--review",
                    "REVIEW",
                    "--save",
                    needs=["PACKET", "REVIEW"],
                ),
                step(
                    "Revalidate disposition and deployment",
                    "candidate",
                    "summary",
                    "DECISION",
                    needs=["DECISION"],
                ),
                step(
                    "Preview explicit lifecycle policy",
                    "candidate",
                    "preview",
                    "DECISION",
                    "--strength-milli",
                    "500",
                    "--save",
                    needs=[
                        "DECISION",
                        "Select a strength from the reviewed matrix; 500 is an example",
                    ],
                ),
            ],
        ),
        "catalog": (
            (
                "Starter import is for an empty catalog. Preserve an existing catalog "
                "and explicitly review any merge. Saved requests bind the exact HEAD; "
                "batching still requires runtime qualification. Candidate apply "
                "requires fresh deployed approval."
            ),
            [
                step("Inspect current catalog", "catalog", "show"),
                step(
                    "Initialize an absent catalog",
                    "catalog",
                    "init",
                    when="Only when no catalog or pending intent exists",
                ),
                step(
                    "Validate starter catalog",
                    "catalog",
                    "validate",
                    root / "templates/itov-starter.catalog.json",
                    "--check-files",
                ),
                step(
                    "Import into the empty catalog",
                    "catalog",
                    "import",
                    root / "templates/itov-starter.catalog.json",
                    "--expected-head",
                    "EMPTY_CATALOG_HEAD",
                    needs=["EMPTY_CATALOG_HEAD"],
                    when="Only after confirming no existing entries will be replaced",
                ),
                step(
                    "Build a pinned neutral request",
                    "workspace",
                    "request",
                    "itov-starter",
                    "--save",
                ),
                step(
                    "Save batch plan",
                    "batch",
                    "plan",
                    "BATCH_REQUEST",
                    "--save",
                    needs=["BATCH_REQUEST"],
                ),
                step(
                    "Qualify runtime",
                    "batch",
                    "qualify",
                    "BATCH_PLAN",
                    "--save",
                    needs=["BATCH_PLAN"],
                ),
                step(
                    "Execute qualified batch",
                    "batch",
                    "run",
                    "BATCH_PLAN",
                    "--qualification",
                    "QUALIFICATION",
                    needs=["BATCH_PLAN", "QUALIFICATION"],
                ),
                step("Inspect candidate lifecycle", "candidate", "status"),
            ],
        ),
        "recovery": (
            (
                "Inspect the owning record first. Waiting/resuming observes accepted "
                "work; no generic command restarts training, clears ownership, "
                "retries an uncertain POST or approves a candidate."
            ),
            [
                step("Inventory durable state", "workspace", "status"),
                step(
                    "Find the correct owner and commands",
                    "workspace",
                    "inspect",
                    "SAVED_ARTIFACT",
                    needs=["SAVED_ARTIFACT"],
                ),
                step("Inspect lifecycle journal", "candidate", "status"),
                step("Inspect configured launch", "server", "start", "--print-command"),
            ],
        ),
    }
    description, steps = recipes[topic]
    return {
        "scope": "workspace_guide",
        "ok": True,
        "topic": topic,
        "description": description,
        "steps": steps,
        "limits": (
            "Instructions only; nothing executed. Named inputs must be supplied "
            "explicitly. Model quality and environment readiness remain separate "
            "checks."
        ),
    }
