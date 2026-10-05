# Working in ITOV

This file applies to the repository. Follow the user's current instructions when
they change the scope or supersede the constraints below.

## Start here

1. Inspect the working tree before editing. Preserve user changes and unrelated
   files; do not reset, clean, commit, or push as an incidental development step.
2. Read [TODO.md](TODO.md) for active priorities and execution constraints,
   [README.md](README.md) for supported commands, and the relevant feature document
   under `docs/`. Read [CHANGELOG.md](CHANGELOG.md) and the applicable evidence when
   continuing previous work. Older stage reports are historical, not current task
   authority.
3. Review the implementation and affected tests, identify the required change,
   then implement and verify it. Continue ordinary authorized repairs through a
   concrete result; ask only when missing information actually blocks a decision.

ITOV is an incomplete local ComfyUI application. The current product order is
usable base images, silent image-to-video, then a stable graphical training
workspace. Audio/A/V feature development is deferred. Re-read `TODO.md` rather
than inferring completion or new priorities from old stage checkmarks.

**Further GPU runs are deferred until the user resumes them.** Continue source,
CPU, protocol, and package work. Do not launch inference/training or download
model assets merely to verify an unrelated change. The previous mandatory
independent-human review gate is shelved; do not reintroduce it as a blocker.

## Repository map

| Location | Purpose |
| --- | --- |
| `src/itov/` | Application package; `cli.py` exposes the `itov` command |
| `tests/` | Pytest coverage, including temporary workspaces and process protocols |
| `pyproject.toml`, `uv.lock`, `.python-version` | Dependency, tooling, and interpreter authority |
| `.vscode/settings.json` | Editor interpreter and mypy integration |
| `docs/`, `docs/evidence/` | Feature contracts and retained verification reports |
| `examples/`, `scripts/` | Example inputs and task-specific helpers; inspect before running |
| `workspace/` | Ignored local state, plans, runs, training environment, and verification artifacts |
| `AI/ComfyUI/ComfyUI_windows_portable/` | Ignored local ComfyUI installation, assets, and embedded Python |
| `src/PYTHON_ERRORS.js` | User-supplied editor diagnostic export, not executable application code |

Do not search or lint downloaded runtimes, caches, or generated state by accident.
Prefer scoped `rg` searches in `src/itov`, `tests`, and the relevant documentation.

## Python and uv

- Work from the repository root in PowerShell. Use the existing uv-managed
  `.venv` and repository-local `.uv-cache`; do not replace environments or switch
  to standalone pip.
- `.python-version` selects Python 3.13. The dev group requires Python 3.13+;
  published core code still targets Python 3.11+. Keep source syntax compatible
  with that minimum unless the task explicitly changes it.
- `uv sync --locked` installs the default dev group. It includes pytest, Ruff,
  mypy, Pyright, Pillow, `comfyui-types`, Sourcery, and the ML libraries needed for
  native development. Keep development-only dependencies in that group.
- Read actual constraints before changing versions. Dataset workers require
  `Pillow==12.3.0`; `src/itov/training.py` defines `PINNED` versions checked by the
  training environment probe. A lockfile update alone does not change these
  runtime checks. Investigate compatibility and keep declarations, lockfile, and
  source requirements consistent.
- The checked Windows dev installation uses CPU Torch. The portable CUDA Python
  and `workspace/training/environment/Scripts/python.exe` serve separate runtime
  purposes. Do not synchronize, upgrade, or replace them to fix editor errors.
- Do not install unrelated packages solely because their names resemble an
  unresolved import. Inspect installed metadata, inline types, available stubs,
  interpreter selection, and upstream documentation first; implement the actual
  dependency/configuration fix and verify native imports.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --locked
uv lock --check
uv pip check --python .venv/Scripts/python.exe
```

Use `--offline` for checks when their dependencies are already cached. A cache
miss or sandbox network denial is not proof that a package version is incompatible.

## Type checking and editor diagnostics

Both checkers are configured in `pyproject.toml`; VS Code's mypy uses `.venv`.
Do not dismiss unresolved imports as belonging to a separate environment and
leave the user to research the fix.

- ML third-party packages resolve from `.venv`. ComfyUI's `comfy.*`, `execution`,
  and `server` resolve from `AI/ComfyUI/ComfyUI_windows_portable/ComfyUI` via
  Pyright's `extraPaths` and mypy's `mypy_path`. A fresh clone must provision that
  source or point those settings to its actual location.
- `comfyui-types` supplies `comfyui_types` custom-node helpers; it does not supply
  ComfyUI's internal modules. Keep that distinction explicit when diagnosing an
  import rather than guessing a distribution name.
- Keep `src/itov/py.typed` in source and built packages. It makes ITOV's annotations
  available to imported clients and tests.
- Reproduce the current export with the actual tools. Preserve the supplied
  `src/PYTHON_ERRORS.js`; do not edit/delete entries to manufacture a clean result.
- Fix checked boundaries, annotations, and dependency resolution. Do not blanket
  disable diagnostics, add fake stubs, or replace types with `Any` to get green.
  Narrow casts need a documented, verified library contract.
- Current coverage is Pyright basic mode and mypy default body checking.
  `follow_imports = "silent"` retains imported type information while reporting
  errors in requested files. Mypy skips unannotated function bodies by default;
  zero errors does not establish strict typing of every function.

```powershell
uv run --locked pyright
uv run --locked mypy
# Include the test files implicated by the editor export when applicable:
uv run --locked mypy src/itov tests/test_jobs.py tests/test_dataset_review.py
uv run --locked ruff check src tests pyproject.toml
uv run --locked ruff format --check src tests
```

Ruff targets Python 3.11 with a 100-character line length. Keep established module
and import conventions instead of making unrelated formatting changes.

## Verification and evidence

- Run relevant tests for changed behavior. Add meaningful regression coverage for
  defects, especially validation, ownership, failure, and recovery paths. Do not
  weaken expectations to make a run pass or add tests that only repeat the code.
- Use a fresh repository-local pytest base directory for each run. Pytest can
  clear its base directory; never point it at a retained run or evidence folder.
  Windows shared/default temp paths have caused permission failures here.
- Use the full suite for broad source changes or release qualification. A small
  documentation/configuration edit does not automatically require repeating it.
- When packaging is affected, build and verify the wheel/source archive, CLI,
  `py.typed`, and relevant packaged-worker behavior. Check packaged source and
  README parity; normalize line endings when comparing metadata prose.

```powershell
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N')
$verificationDir = "workspace/state/verification/$runId"
New-Item -ItemType Directory -Force $verificationDir | Out-Null
# Add specific tests/test_*.py paths for a targeted run; otherwise this runs the suite.
uv run --locked pytest --basetemp "$verificationDir/pytest-tmp" --junitxml "$verificationDir/pytest.xml" -q
uv build
uv run --locked itov --version
```

Retain failure logs and original run identities. Save new evidence under new
names; do not rewrite an earlier failure as success. Update supported command
documentation and the changelog for delivered behavior. Historical counts are
reference points, not substitutes for current checks. The
[2026-10-03 development profile report](docs/evidence/python-dev-profile-20261003.json)
records the repaired import setup, zero checker errors, 236 targeted tests, and
the exact verification limits. The earlier pass-three report records a different
snapshot, including a full suite and imports that were unresolved at that time.

## Integrity and completion boundaries

- Preserve canonical JSON, hashes, immutable plans, seed declarations, catalog
  lineage, ownership/leases, and refusal/recovery behavior. Use existing helpers
  rather than bypassing those checks to satisfy typing or tests.
- Worker source hashes bind saved plans. Source changes can make old plans stale;
  regenerate plans through supported commands instead of weakening freshness
  validation or mutating retained plans.
- Preserve lazy/isolated worker imports so the dependency-light core CLI does not
  acquire ML/CUDA dependencies at import time.
- On Windows, inspect and stop only owned processes through the existing process
  helpers. Do not use `os.kill(pid, 0)` as a liveness probe or kill unrelated
  Python/ComfyUI processes. Verify exact paths before deleting or moving anything.
- Report implementation, runtime execution, artifact validity, numerical
  reproducibility, and observed model quality separately. `succeeded` is not
  model acceptance, and tests/builds do not prove visual or GPU qualification.
- Finish with the concrete changes, checks actually run, and remaining limits.
  Explain any unresolved dependency or pin in plain terms with its exact source
  requirement and next action; a list of unexplained errors is not a repair.
