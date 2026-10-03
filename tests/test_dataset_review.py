"""Real fingerprint fixtures and explicit review policy; no corpus/model acceptance."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, PngImagePlugin
from quality_fixtures import curated_inputs as curated_inputs
from test_dataset_import import declare, files
from test_training import document
from test_training import training_inputs as training_inputs

from itov import curation, dataset_import, training
from itov import dataset_freeze as freeze
from itov import dataset_identity as identity
from itov import dataset_inspection as inspection
from itov.catalog import canonical_bytes, sha256
from itov.cli import main
from itov.config import initialize
from itov.training_data import seal


def make_case(tmp_path, *, met=False, stable_ids=False, config=None):
    config = config or initialize(tmp_path / "workspace", tmp_path / "absent-comfy")
    path, manifest = declare(tmp_path / "inputs", met=met)
    if stable_ids:
        for n in range(2):
            metadata = path.parent / f"{n}.json"
            value = json.loads(metadata.read_bytes())
            value["constituents"] = [
                {"constituentID": n + 1, "role": "Artist", "name": f"Artist {n}"}
            ]
            document(metadata, value)
            manifest["samples"][n]["provenance"]["metadata"]["sha256"] = sha256(
                metadata.read_bytes()
            )
        document(path, manifest)
    imported = dataset_import.begin(config, path)
    spec = {
        "version": 1,
        "dataset": inspection.ref(config.root, Path(imported["artifacts"]["prepared"])),
        "curation": inspection.ref(config.root, Path(imported["artifacts"]["curation"]))
        if met
        else None,
        "target": {
            "id": "fixture-target",
            "description": "Fixture rectangles",
            "include": ["Rectangles"],
            "exclude": ["Unrelated imagery"],
        },
        "trigger": "testtrigger",
        "exclusions": [],
        "local_identities": []
        if met
        else [
            {
                "sample": f"sample-{n}",
                "work": [f"local:fixture:work-{n}"],
                "creators": [f"local:fixture:creator-{n}"],
                "notes": "Generated fixture identity",
            }
            for n in range(2)
        ],
    }
    spec_path = document(config.root / "inspection.json", spec)
    return config, spec_path, spec


@pytest.fixture
def case(tmp_path):
    return make_case(tmp_path)


def inspected(case):
    config, path, _ = case
    result = inspection.inspect(config, path, save=True)
    draft = Path(result["artifacts"]["review template"])
    value = json.loads(draft.read_bytes())
    value["reviewer"] = {
        "kind": "assistant",
        "name": "Fixture reviewer",
        "method": "Synthetic protocol attestation",
        "limitations": "Not model evidence",
    }
    for row in value["samples"]:
        row.update(
            decision="include",
            caption_verdict="accept",
            caption_notes="Inspected fixture text",
            target_fit="match",
            target_notes="Fixture rectangle",
            decision_notes="Retain fixture",
        )
    for row in value["pairs"]:
        row.update(
            decision="distinct", notes="Different fixture colors; low-information hash collision"
        )
    return result, draft, value


def invoke(capsys, config, action, path, code, *extra):
    assert (
        main(["dataset", action, str(path), "--config", str(config.file), "--json", *extra]) == code
    )
    captured = capsys.readouterr()
    assert not captured.err
    value = json.loads(captured.out)
    assert value["_cli"]["exit_code"] == code
    return value


def test_public_inspection_review_freeze_reimport_and_offline_verify(case, capsys, monkeypatch):
    config, spec, _ = case
    first = invoke(capsys, config, "inspect", spec, 1, "--save")
    assert first["counts"]["pairs"] == first["counts"]["flagged_pairs"] == 1
    assert all(r["low_information"] for r in first["samples"])
    draft = Path(first["artifacts"]["review template"])
    blocked = invoke(capsys, config, "freeze", draft, 1, "--save")
    assert blocked["blockers"] and Path(blocked["saved_path"]).is_file()
    _, _, reviewed = inspected(case)
    reviewed["samples"][0]["caption"] = "testtrigger red rectangular shape\r\n"
    document(draft, reviewed)
    retained = draft.read_bytes()
    assert inspection.inspect(config, spec, save=True)["inspection_id"] == first["inspection_id"]
    assert draft.read_bytes() == retained  # Do not reset operator edits.
    saved = invoke(capsys, config, "freeze", draft, 0, "--save")
    folder = Path(saved["saved_path"]).parent
    before = files(folder)
    assert saved["counts"] == {"train": 1, "validation": 1}
    assert (
        folder / "captions/sample-0.txt"
    ).read_bytes() == b"testtrigger red rectangular shape\r\n"
    assert freeze.freeze(config, draft, save=True)["freeze_id"] == saved["freeze_id"]
    # A frozen review retains exact draft bytes; later draft edits do not rewrite it.
    reviewed["reviewer"]["name"] = "Another reviewer"
    document(draft, reviewed)
    assert (
        invoke(capsys, config, "review-verify", Path(saved["saved_path"]), 0)["freeze_id"]
        == saved["freeze_id"]
    )
    assert files(folder) == before
    # The generated declaration uses the existing public B-01 preparation path.
    output = dataset_import.begin(config, folder / "import.json", source_root=config.root)
    assert output["ok"] and output["counts"] == saved["counts"]
    imported = json.loads(Path(output["artifacts"]["prepared"]).read_bytes())
    assert imported["dataset"]["samples"][0]["caption"]["sha256"] == sha256(
        b"testtrigger red rectangular shape\r\n"
    )

    def forbid(*a, **k):
        pytest.fail("Saved review verification must not launch the decoder")

    monkeypatch.setattr(inspection, "worker", forbid)
    assert freeze.verify(config, Path(saved["saved_path"]))["ok"]
    assert (
        main(["dataset", "review-verify", saved["saved_path"], "--config", str(config.file)]) == 0
    )
    assert "Freeze id:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "problem",
    [
        "pending",
        "caption",
        "target",
        "identity",
        "creator",
        "pair",
        "pair_missing",
        "missing",
        "duplicate",
        "note",
        "empty_split",
    ],
)
def test_review_cannot_waive_unresolved_selection_or_leakage(case, problem):
    config, spec_path, spec = case
    if problem in {"identity", "creator"}:
        spec["local_identities"][1]["creators"] = (
            [] if problem == "identity" else ["local:fixture:creator-0"]
        )
        document(spec_path, spec)
    observed, draft, value = inspected(case)
    if problem == "pending":
        value["samples"][0]["decision"] = "pending"
    elif problem == "caption":
        value["samples"][0]["caption"] = "testtrigger testtrigger shape"
    elif problem == "target":
        value["samples"][0]["target_fit"] = "uncertain"
    elif problem == "pair":
        value["pairs"][0]["decision"] = "unresolved"
    elif problem == "pair_missing":
        value["pairs"] = []
    elif problem == "missing":
        value["samples"].pop()
    elif problem == "duplicate":
        value["samples"][1] = value["samples"][0]
    elif problem == "note":
        value["samples"][0]["caption_notes"] = "PENDING"
    elif problem == "empty_split":
        value["samples"][1]["decision"] = "exclude"
    document(draft, value)
    if problem in {"pair_missing", "missing", "duplicate"}:
        with pytest.raises(ValueError):
            freeze.freeze(config, draft, save=True)
    else:
        result = freeze.freeze(config, draft, save=True)
        assert not result["ok"] and result["status"] == "review_blocked"
        assert result["blockers"] and Path(result["saved_path"]).is_file()
    assert not (config.root / "state/dataset-reviews/freezes").exists()


@pytest.mark.parametrize("damage", ["caption", "manifest", "extra", "missing", "source", "receipt"])
def test_frozen_artifacts_and_pinned_inputs_cannot_drift(case, damage):
    config, _, _ = case
    observed, draft, value = inspected(case)
    document(draft, value)
    result = freeze.freeze(config, draft, save=True)
    path = Path(result["saved_path"])
    targets = {
        "caption": path.parent / "captions/sample-0.txt",
        "manifest": path.parent / "import.json",
        "extra": path.parent / "extra.txt",
        "missing": path,
        "source": config.root / observed["samples"][0]["source"]["path"],
        "receipt": config.root / value["inspection"]["path"],
    }
    target = targets[damage]
    if damage == "missing":
        target.unlink()
    else:
        target.write_bytes(b"changed")
    with pytest.raises((OSError, ValueError)):
        freeze.verify(config, path)


def test_inspection_late_mutation_refused_before_publication(case, monkeypatch):
    config, spec, _ = case
    original = inspection.derive

    def changed(*args):
        result = original(*args)
        (config.root / result["samples"][0]["source"]["path"]).write_bytes(b"changed after reading")
        return result

    monkeypatch.setattr(inspection, "derive", changed)
    with pytest.raises(ValueError, match="changed during operation"):
        inspection.inspect(config, spec, save=True)
    assert not (config.root / "state/dataset-reviews/inspections").exists()


def test_real_controller_exit_mid_freeze_retries_without_state_edits(case, capsys):
    config, _, _ = case
    _, draft, value = inspected(case)
    document(draft, value)
    script = """
import os,sys
from itov import dataset_freeze as d
from itov.cli import main
original=d._atomic_write
def stop(*args,**kwargs):
    original(*args,**kwargs)
    os._exit(74)
d._atomic_write=stop
main(sys.argv[1:])
"""
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "dataset",
            "freeze",
            str(draft),
            "--save",
            "--config",
            str(config.file),
            "--json",
        ],
        capture_output=True,
        timeout=60,
    )
    assert child.returncode == 74, child.stderr
    attempt = next((config.root / "state/dataset-reviews/attempts").iterdir())
    before = files(attempt)
    assert before and not (config.root / "state/dataset-reviews/freezes").exists()
    result = invoke(capsys, config, "freeze", draft, 0, "--save")
    assert result["ok"] and files(attempt) == before


def test_full_pair_distances_and_pixel_equality_against_real_images(tmp_path):
    image = Image.new("RGB", (96, 64), (240, 220, 180))
    draw = ImageDraw.Draw(image)
    draw.rectangle((3, 9, 48, 51), fill=(160, 20, 30))
    draw.ellipse((52, 5, 88, 42), fill=(20, 110, 60))
    variants = {}
    for name in ("original", "metadata", "jpeg", "resize", "mirror"):
        path = tmp_path / (name + ".image")
        if name == "metadata":
            info = PngImagePlugin.PngInfo()
            info.add_text("note", "Same decoded pixels; different encoded file")
            image.save(path, format="PNG", pnginfo=info)
        elif name == "jpeg":
            image.save(path, format="JPEG", quality=90)
        elif name == "resize":
            image.resize((192, 128)).save(path, format="PNG")
        elif name == "mirror":
            image.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(path, format="PNG")
        else:
            image.save(path, format="PNG")
        data = inspection.worker(Path(sys.executable), [path, sha256(path.read_bytes())])
        data.pop("engine")
        variants[name] = data
    assert variants["metadata"]["rgb_sha256"] == variants["original"]["rgb_sha256"]
    assert variants["metadata"]["source_sha256"] != variants["original"]["source_sha256"]
    for name in ("jpeg", "resize", "metadata"):
        assert (
            int(variants[name]["dhash"], 16) ^ int(variants["original"]["dhash"], 16)
        ).bit_count() <= 6
    assert (
        variants["mirror"]["dhash"] != variants["original"]["dhash"]
    )  # No rotation/mirror guarantee.
    rows = [
        {
            "sample": name,
            "split": "train",
            "features": data,
            "image": {"sha256": data["source_sha256"]},
            "identity": {"work_tokens": [], "creator_tokens": [], "creator_labels": []},
        }
        for name, data in sorted(variants.items())
    ]
    pairs = inspection.pairwise(rows)
    assert len(pairs) == 10
    exact = next(p for p in pairs if {p["left"], p["right"]} == {"original", "metadata"})
    assert exact["exact"] == ["source_pixels"] and exact["flagged"]


def test_transitive_creator_alias_bridge_cannot_be_removed_to_bypass_leakage(case):
    _, _, _ = case
    observed, _, value = inspected(case)
    # Pure policy fixture extends the observed pool with an excluded alias bridge.
    a, b = observed["samples"]
    a["identity"]["creator_tokens"] = ["local:fixture:a"]
    b["identity"]["creator_tokens"] = ["local:fixture:b"]
    bridge = copy.deepcopy(a)
    bridge["sample"] = "bridge"
    bridge["identity"]["creator_tokens"] = ["local:fixture:a", "local:fixture:b"]
    observed["samples"].append(bridge)
    observed["groups"]["creator"] = identity.components(observed["samples"], "creator_tokens")
    excluded = copy.deepcopy(value["samples"][0])
    excluded.update(sample="bridge", decision="exclude")
    value["samples"].append(excluded)
    result = freeze.decide(observed, value, inspection.retained(canonical_bytes(value)))
    assert any(b["code"] == "creator_overlap" for b in result["blockers"])


def test_met_stable_ids_aliases_and_qualified_attribution():
    metadata = {
        "objectID": 1,
        "artistDisplayName": "Different display name",
        "artistWikidata_URL": "https://www.wikidata.org/wiki/Q123",
        "artistULAN_URL": "http://vocab.getty.edu/page/ulan/456",
        "constituents": [
            {
                "constituentID": 7,
                "role": "Artist",
                "name": "Artist Alias",
                "constituentWikidata_URL": "https://www.wikidata.org/wiki/Q123",
            }
        ],
    }
    first = identity.met(metadata)
    assert first["creator_tokens"] == ["met:creator:7", "ulan:456", "wikidata:Q123"]
    assert first["issues"] == []
    metadata["constituents"][0]["name"] = "Style of Artist Alias"
    assert "Qualified creator attribution in constituent name" in identity.met(metadata)["issues"]
    metadata["artistPrefix"] = "Possibly by"
    assert len(identity.met(metadata)["issues"]) == 2
    assert identity.met({"objectID": 2, "artistDisplayName": "Unknown"})["issues"]


def test_exact_duplicate_cannot_be_waived_as_distinct(case):
    observed, _, value = inspected(case)
    pair = observed["pairs"][0]
    pair["exact"] = ["source_pixels"]
    result = freeze.decide(observed, value, inspection.retained(canonical_bytes(value)))
    assert any(b["code"] == "exact_or_identity_conflict" for b in result["blockers"])


def test_source_engine_and_feature_coverage_changes_are_refused(case, monkeypatch):
    config, path, _ = case
    original = inspection.worker
    calls = 0

    def changing(python, args):
        nonlocal calls
        value = original(python, args)
        calls += 1
        if calls == 3:
            value["engine"]["worker_sha256"] = "0" * 64
        return value

    monkeypatch.setattr(inspection, "worker", changing)
    with pytest.raises(ValueError, match="engine changed"):
        inspection.inspect(config, path, save=True)
    assert not (config.root / "state/dataset-reviews/inspections").exists()


def test_met_inspection_requires_provider_curation(tmp_path):
    config, path, value = make_case(tmp_path, met=True)
    observed = inspection.inspect(config, path)
    assert observed["counts"]["unresolved_samples"] == 2  # Fixture has names but no stable IDs.
    value["curation"] = None
    document(path, value)
    with pytest.raises(ValueError, match="requires its curation"):
        inspection.inspect(config, path)


def test_core_review_imports_no_optional_libraries():
    script = """
import sys
from itov import dataset_inspection, dataset_freeze
assert not any(k.split('.')[0] in {'PIL','numpy','torch','diffusers'} for k in sys.modules)
"""
    run = subprocess.run([sys.executable, "-c", script], capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize(
    "damage", ["pair", "coverage", "caption", "group", "counts", "dimensions", "hash"]
)
def test_resealed_inspection_inconsistency_is_not_accepted(case, damage):
    config, _, _ = case
    observed, draft, value = inspected(case)
    path = Path(observed["saved_path"])
    raw = json.loads(path.read_bytes())
    if damage == "pair":
        raw["pairs"][0]["dhash_distance"] += 1
    elif damage == "coverage":
        raw["samples"].pop()
    elif damage == "caption":
        raw["samples"][0]["caption"] = "changed"
    elif damage == "group":
        raw["groups"]["creator"] = []
    elif damage == "counts":
        raw["counts"]["flagged_pairs"] = 0
    elif damage == "dimensions":
        raw["samples"][0]["features"]["oriented_size"] = [False, 40]
    else:
        raw["samples"][0]["features"]["dhash"] = "not-a-hash"
    document(path, seal({k: v for k, v in raw.items() if k != "inspection_id"}, "inspection_id"))
    value["inspection"] = inspection.ref(config.root, path)
    document(draft, value)
    with pytest.raises(ValueError):
        freeze.freeze(config, draft, save=True)


def test_met_alias_identifier_crosses_different_display_names(tmp_path):
    config = initialize(tmp_path / "workspace", tmp_path / "absent-comfy")
    path, manifest = declare(tmp_path / "inputs", met=True)
    for n in range(2):
        metadata = path.parent / f"{n}.json"
        value = json.loads(metadata.read_bytes())
        value["artistWikidata_URL"] = "https://www.wikidata.org/wiki/Q123"
        value["constituents"] = [{"constituentID": n + 1, "role": "Artist", "name": f"Alias {n}"}]
        document(metadata, value)
        manifest["samples"][n]["provenance"]["metadata"]["sha256"] = sha256(metadata.read_bytes())
    document(path, manifest)
    imported = dataset_import.begin(config, path)
    assert imported["ok"]  # The B-01 display-name check has distinct strings.
    _, _, spec = make_case(tmp_path / "other")
    spec["dataset"] = inspection.ref(config.root, Path(imported["artifacts"]["prepared"]))
    spec["curation"] = inspection.ref(config.root, Path(imported["artifacts"]["curation"]))
    spec["local_identities"] = []
    spec_path = document(config.root / "inspection.json", spec)
    observed, draft, value = inspected((config, spec_path, spec))
    assert observed["split_leakage"][0]["kind"] == "creator"
    document(draft, value)
    result = freeze.freeze(config, draft)
    assert any(b["code"] == "creator_overlap" for b in result["blockers"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("work", []),
        ("creators", []),
        ("work", ["display-name"]),
        ("sample", []),
        ("work", ["local:x:a", "local:x:a"]),
    ],
)
def test_local_identity_admission_and_unresolved_findings(case, field, value):
    config, path, spec = case
    spec["local_identities"][0][field] = value
    document(path, spec)
    if field in {"work", "creators"} and value == []:
        report = inspection.inspect(config, path)
        assert report["counts"]["unresolved_samples"] == 1
    else:
        with pytest.raises(ValueError):
            inspection.inspect(config, path)


def test_external_exclusion_is_pinned_and_cannot_be_silently_changed(case):
    config, path, spec = case
    external = document(config.root / "excluded-metadata.json", {"reason": "fixture"})
    spec["exclusions"] = [
        {
            "id": "excluded",
            "metadata": inspection.ref(config.root, external),
            "source": None,
            "reason": "Metadata-only exclusion",
            "limitations": "No image available",
        }
    ]
    document(path, spec)
    observed, draft, value = inspected(case)
    assert observed["definition"]["exclusions"] == spec["exclusions"]
    document(draft, value)
    external.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SHA-256"):
        freeze.freeze(config, draft)


def test_freeze_refuses_late_input_change_and_preserves_unpublished_attempt(case, monkeypatch):
    config, _, _ = case
    observed, draft, value = inspected(case)
    document(draft, value)
    original = freeze.verify_files

    def changed(folder, files):
        original(folder, files)
        (config.root / observed["samples"][0]["source"]["path"]).write_bytes(b"late mutation")

    monkeypatch.setattr(freeze, "verify_files", changed)
    with pytest.raises(ValueError, match="changed during operation"):
        freeze.freeze(config, draft, save=True)
    assert not (config.root / "state/dataset-reviews/freezes").exists()
    assert list((config.root / "state/dataset-reviews/attempts").iterdir())


def test_report_treats_supplied_markdown_html_as_literal_text(case):
    config, _, _ = case
    observed, _, _ = inspected(case)
    # Rendering receives observed text; this check does not forge saved evidence.
    malicious = (
        '<img src="https://untrusted.invalid/pixel"> ![x](https://untrusted.invalid/pixel) ```'
    )
    observed["samples"][0]["caption"] = malicious
    rendered = inspection.markdown(config.root, observed).decode()
    assert "Caption:\n\n```json\n" + json.dumps(malicious) + "\n```" in rendered


def test_public_inspection_text_has_counts_and_actionable_refs(case, capsys):
    config, path, _ = case
    assert main(["dataset", "inspect", str(path), "--config", str(config.file), "--save"]) == 1
    output = capsys.readouterr().out
    assert "Review pool: 2 samples, 1 pairs, 1 flagged" in output
    assert "Unresolved identities: 0" in output and "review template" in output
    assert "Samples: [{" not in output


def reviewed_met(tmp_path, config=None):
    case = make_case(tmp_path, met=True, stable_ids=True, config=config)
    observed, draft, value = inspected(case)
    document(draft, value)
    config = case[0]
    frozen = freeze.freeze(config, draft, save=True)
    assert frozen["ok"]
    imported = dataset_import.begin(
        config, Path(frozen["artifacts"]["import declaration"]), source_root=config.root
    )
    assert imported["ok"]
    return config, case, frozen, imported


def test_reviewed_curation_binds_freeze_through_training_plan(curated_inputs, tmp_path, capsys):
    config, case, frozen, imported = reviewed_met(tmp_path / "reviewed", curated_inputs.config)
    result = invoke(
        capsys,
        config,
        "curate",
        Path(imported["artifacts"]["curation"]),
        0,
        "--freeze",
        frozen["saved_path"],
        "--save",
    )
    assert result["version"] == 2 and result["freeze_id"] == frozen["freeze_id"]
    spec = copy.deepcopy(curated_inputs.spec)
    spec["dataset"] = inspection.ref(config.root, Path(imported["artifacts"]["prepared"]))
    spec["qualification"]["curation"] = inspection.ref(config.root, Path(result["saved_path"]))
    plan = training.plan(config, document(config.root / "reviewed-training.json", spec))
    assert plan["dataset_id"] == imported["dataset_id"]
    assert {"dataset_freeze.py", "dataset_inspection.py", "dataset_identity.py"} <= plan[
        "worker_sources"
    ].keys()
    (Path(frozen["saved_path"]).parent / "captions/sample-0.txt").write_text("changed")
    with pytest.raises(ValueError, match="Frozen artifact differs"):
        training.revalidate(config, plan)


def test_freeze_cannot_be_bound_to_another_import_even_with_valid_provenance(tmp_path):
    config, case, frozen, imported = reviewed_met(tmp_path)
    original_curation = case[2]["curation"]
    with pytest.raises(ValueError, match="differs from the frozen selection"):
        curation.bind_selection(
            config.root, config.root / original_curation["path"], Path(frozen["saved_path"])
        )
    bound = curation.bind_selection(
        config.root, Path(imported["artifacts"]["curation"]), Path(frozen["saved_path"]), save=True
    )
    value = json.loads(Path(bound["saved_path"]).read_bytes())
    value["curator"] = "Someone else"
    changed = document(config.root / "changed-curation.json", value)
    with pytest.raises(ValueError, match="differs from committed provider"):
        curation.validate(config.root, changed)


def test_reviewed_curation_cannot_form_recursive_inspection_chains(tmp_path):
    config, case, frozen, imported = reviewed_met(tmp_path)
    bound = curation.bind_selection(
        config.root, Path(imported["artifacts"]["curation"]), Path(frozen["saved_path"]), save=True
    )
    spec = copy.deepcopy(case[2])
    spec["dataset"] = inspection.ref(config.root, Path(imported["artifacts"]["prepared"]))
    spec["curation"] = inspection.ref(config.root, Path(bound["saved_path"]))
    with pytest.raises(ValueError, match="base version-one provenance"):
        inspection.inspect(config, document(config.root / "recursive-inspection.json", spec))


@pytest.mark.parametrize(
    "mode,rgb_hash,dhash,ahash,luma_range",
    [
        (
            "RGB",
            "e06308b85a6cce1776b5474b16f6c8327c6fc45768a307527a2903f9a12e6891",
            "33d1f9f8fefeffff",
            "f8f87c3e1e1f0f07",
            228,
        ),
        (
            "L",
            "2fda891b2494c329910232575f9b42ed8d83618f5d77c6f947a42ef06c34ac84",
            "3f8bd1fcfeffffff",
            "80e0f8fe7f1f0701",
            253,
        ),
    ],
)
def test_isolated_fingerprints_preserve_pre_correction_vectors(
    tmp_path, mode, rgb_hash, dhash, ahash, luma_range
):
    image = Image.new(mode, (12, 8))
    pixels = [
        ((x * 23 + y * 17) % 256, (x * 11 + y * 31) % 256, (x * 7 + y * 47) % 256)
        for y in range(8)
        for x in range(12)
    ]
    image.putdata(pixels if mode == "RGB" else [pixel[0] for pixel in pixels])
    exif = image.getexif()
    exif[274] = 6
    path = tmp_path / "oriented.png"
    image.save(path, exif=exif)
    value = inspection.worker(Path(sys.executable), [path, sha256(path.read_bytes())])
    assert value["source_size"] == [12, 8]
    assert value["oriented_size"] == [8, 12]
    assert value["rgb_sha256"] == rgb_hash
    assert value["dhash"] == dhash
    assert value["ahash"] == ahash
    assert value["luma_range"] == luma_range
