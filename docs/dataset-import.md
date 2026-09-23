# Transactional dataset import (B-01)

`dataset import` prepares declared local JPEG/PNG images and UTF-8 captions into a self-contained, committed dataset. It also supports the selected museum provider, Met Open Access, from retained image, object-metadata and policy files. It does not discover or download images; live acquisition/resumption remains E-02. Training restart remains B-04. The current candidate remains rejected.

## Provision and run

The core CLI has no Pillow or ML import requirement. Preparation launches a separate Python process with **Pillow 12.3.0**. The checkout development environment includes it; installed users can install the wheel's `dataset` extra or select an already provisioned interpreter with `--image-python`. No dependencies are installed by an import command. `status`, `verify`, curation and training planning inspect retained evidence without launching the image decoder.

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
uv sync --inexact --locked
$cfg = 'workspace/itov.toml'
$result = uv run --inexact --locked itov dataset import examples/met-still-life.import.json --source-root workspace --config $cfg --json | ConvertFrom-Json
$result._cli
$operation = $result.artifacts.operation
uv run --inexact --locked itov dataset status $operation --config $cfg
uv run --inexact --locked itov dataset verify $result.artifacts.prepared --config $cfg
uv run --inexact --locked itov dataset curate $result.artifacts.curation --config $cfg --save
Get-FileHash -Algorithm SHA256 $result.artifacts.prepared
```

The [museum declaration](../examples/met-still-life.import.json) pins the retained eight-work pilot in this workspace. A fresh checkout must supply those exact source/caption/metadata/policy files, or write a new declaration for its own inputs. Neither the script nor CLI hardcodes the eight artwork IDs. `scripts/prepare_met_still_life.py` now forwards manifest arguments to `dataset import`; the old `FOLDER --workspace` invocation is retired. The original pilot files and version-one snapshots remain unchanged.

Use the printed `prepared.json` path relative to the workspace and its file SHA-256 in a new training specification. Met imports also produce `curation.json`, accepted by the existing `dataset curate --save` contract. Local imports do not manufacture Met curation; curated model-quality qualification still has its own requirements. Importing data does not train a model or update an existing plan.

## Declaration

Every object rejects missing/extra fields. Version 1 declares:

| Field | Meaning |
| --- | --- |
| `version`, `id` | `1` and a portable dataset identifier |
| `provider`, `purpose` | `local` or `met-open-access`; `smoke` or `training` (Met requires `training`) |
| `origin` | Nonempty `title` and `reference` |
| `rights` | Nonempty `basis`, `reference`, and explicit `training_permitted: true` |
| `transform` | `rgb-fit-pad-512-lanczos-ivory-v1` |
| `curation` | `null` for local inputs; Met fields described below |
| `samples` | 2–256 samples with both `train` and `validation` represented |

Each sample has exactly `id`, `split`, `group`, `source`, `caption`, `provenance`. Source/caption references each contain `path` and lowercase SHA-256. Paths are portable relative names under `--source-root` (default: declaration directory); traversal, device names and redirected paths are refused. The input root may be an explicitly selected directory outside the workspace. It is read only. IDs are lowercase portable identifiers; sample IDs become filenames. A source hash or declared group cannot cross splits. Exact duplicate prepared images are refused by the existing dataset validator.

Local provenance contains `reference`, `selection_note`, `caption_note`, all nonempty text. For example, the following is the structure to populate with real hashes, files and your own rights declaration:

```json
{
  "version": 1,
  "id": "my-local-study",
  "provider": "local",
  "purpose": "smoke",
  "origin": {"title": "My photographs", "reference": "Local source collection"},
  "rights": {"basis": "Photographed and owned by the operator", "reference": "Local ownership record", "training_permitted": true},
  "transform": "rgb-fit-pad-512-lanczos-ivory-v1",
  "curation": null,
  "samples": [
    {"id": "work-one", "split": "train", "group": "work-one", "source": {"path": "one.jpg", "sha256": "REPLACE_WITH_SHA256"}, "caption": {"path": "one.txt", "sha256": "REPLACE_WITH_SHA256"}, "provenance": {"reference": "Original photograph one", "selection_note": "Selected composition", "caption_note": "Operator description"}},
    {"id": "work-two", "split": "validation", "group": "work-two", "source": {"path": "two.png", "sha256": "REPLACE_WITH_SHA256"}, "caption": {"path": "two.txt", "sha256": "REPLACE_WITH_SHA256"}, "provenance": {"reference": "Original photograph two", "selection_note": "Held-out composition", "caption_note": "Operator description"}}
  ]
}
```

Met provenance instead contains `object_id`, pinned `metadata`, `image_url`, `selection_note`, `caption_note`. The group must be `met-OBJECT_ID`. Metadata must declare that exact integer `objectID`, `isPublicDomain: true`, and the selected URL as `primaryImage` or `primaryImageSmall`. URLs must start with the selected Met image host/path. Repeated artwork IDs/URLs and normalized artist-display-name overlap across splits are refused. This is a bounded string/group check, not resolved creator identity or perceptual independence. Met curation declares `curator`, `selection_policy`, the supported `policy_url`, and pinned `policy_snapshot`. Retained provider/rights statements are attributed; hashes do not authenticate their origin. The [Met API documentation](https://metmuseum.github.io/) describes the object metadata being retained.

## Decode and transform

Preparation verifies the exact source hash, image structure and full pixel decode. Pillow opens images lazily, so opening a header alone is insufficient; the worker explicitly verifies, reopens and loads the image. See the [Pillow image reference](https://pillow.readthedocs.io/en/stable/reference/Image.html).

Supported input is one RGB or grayscale JPEG/PNG frame, at most 32 million pixels and 32 MiB. Truncation, decompression warnings, animation, alpha, palette and CMYK modes are refused. The worker applies EXIF orientation, converts to RGB, fits the entire composition inside 512×512 with Lanczos, and centers it on `(245,240,225)` ivory. A fresh canvas strips source metadata; this does not apply an ICC color conversion. See [Pillow ImageOps](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html). The saved PNG is fully decoded again and its RGB pixel hash must equal the generated canvas.

Captions retain exact bytes, including line endings. They must be valid UTF-8, nonempty, at most 64 KiB/4096 characters, with no interior control characters after surrounding whitespace is stripped. Metadata/policy files are bounded to 4 MiB; declarations to 4 MiB; committed files to 32 MiB each and the bundle to 1 GiB. Each decoder subprocess has a 60-second deadline. These are bounded preparation limits, not a resource scheduler.

Each image receipt records original mode/format/dimensions, EXIF orientation, oriented RGB hash, fitted size, padding/offset, output dimensions/bytes/file hash/pixel hash and successful full decode. Its engine identity records the worker hash, Python version/implementation/executable hash, Pillow version/implementation-file hashes and JPEG/zlib codec versions. It is not a hermetic attestation of the OS, all shared libraries or the Python installation. Matching identities and repeated hashes provide the measured reproducibility boundary; cross-platform determinism is not promised.

## Publication and recovery

The sealed operation ID binds the parsed declaration, its exact original UTF-8 bytes and the image engine. Input-root and interpreter locations, timestamps and attempt IDs are outside that identity. A different declaration formatting or engine creates a different operation. The operation is saved before any source copying. Each run receives a UUID attempt directory under `state/dataset-imports/IMPORT_ID/attempts`, with immutable events, an atomic current journal, copied inputs, partial outputs and completed per-image transform receipts. Failure preserves these files.

After all files pass, preparation creates the aggregate receipt, dataset definition, version-two prepared snapshot, optional curation declaration and `READY.json` inventory in the isolated payload. It verifies the complete inventory and reconstructs the snapshot, then renames the directory to `training/imports/IMPORT_ID`. Writers of the same import hold one OS lock. The final path is never incrementally populated or overwritten. This covers cooperative process interruption on the exercised Windows filesystem, not sudden power loss or hostile concurrent file writers.

`dataset verify PREPARED` checks every committed file, hash, size, input/provenance binding, transform receipt and reconstructed snapshot. It checks retained decode evidence; it does not re-run Pillow. Version-two snapshots must be read from their committed path. A staging snapshot, missing/bad marker, extra file, damaged image or changed receipt fails. Legacy preparation commands also require a valid commit for files in the managed import namespace. Existing version-one datasets retain their prior byte/header checks and IDs.

```powershell
uv run --inexact --locked itov dataset status $operation --config $cfg
uv run --inexact --locked itov dataset recover $operation --config $cfg
# If interrupted before the first attempt pointer, supply both locations:
uv run --inexact --locked itov dataset recover $operation --source-root workspace --image-python .venv/Scripts/python.exe --config $cfg
```

Status exposes recorded state, completed image count, retained cause/boundary and artifact paths. `running` is a recorded state, not a liveness guarantee; after a controller crash it remains until recovery. The OS lock refuses competing recovery while the controller holds it. After parent exit, an already launched decoder may finish writing only its abandoned payload; recovery uses a new attempt and does not reuse that output. It never edits or deletes failed attempts. Original pinned inputs and the same engine must still be available. `--source-root` and `--image-python` can relocate them without changing the operation.

If publication completed before the final journal update, status verifies the complete bundle and reports `recovery_required`; recovery only appends the completion event and reconciles the current journal. It does not rerun decoding. A damaged or missing previously committed bundle is an explicit investigation failure, never silently rebuilt in place. Repeating `import` on an intact completed operation is idempotent; an unfinished import requires explicit `recover`.

Invalid declarations and unavailable decoder environments fail admission before an operation can be identified; they produce CLI errors and no preparation attempt. Once admitted, copy/provenance/decode/validation/publication failures retain an attempt. Failed/incomplete reports exit 1; malformed inputs and recovery refusals exit 2; successful commit/verification exits 0. No network requests, GPU work or catalog changes are part of this workflow.

## Evidence boundary

[B-01 verification](evidence/phase-b01-verification-20260923.json) records source/installed tests, real process exits, fresh-folder builds and the retained eight-image museum trial. The original pilot's captions, split and mixed painting styles are preserved. B-02 still owns perceptual duplicate review, stronger creator/work grouping, caption inspection and the intended visual target. Preparation success establishes neither dataset suitability nor model-quality acceptance.
