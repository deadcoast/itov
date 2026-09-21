import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "AI" / "dev_tools" / "cipher.py"
SPEC = importlib.util.spec_from_file_location("scm_cipher", SCRIPT)
cipher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cipher)

MAPPING = {"alpha": "fluid_sim", "beta": "mesh_intersection"}


def arguments(mode, source, output, dictionary=None):
    args = ["--mode", mode, "--input", str(source), "--output", str(output)]
    if dictionary is not None:
        args += ["--dict", str(dictionary)]
    return args


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("alpha ALPHA Alpha", "fluid_sim FLUID_SIM Fluid_Sim"),
        ("native_fluid_sim", "native___SCM_LIT_fluid_sim__"),
        ("FLUID_SIM Fluid_Sim", "__SCM_LIT_FLUID_SIM__ __SCM_LIT_Fluid_Sim__"),
        ("alpha_beta", "fluid_sim_mesh_intersection"),
        ("fluid_sim_alpha", "__SCM_LIT_fluid_sim___fluid_sim"),
        ("fluid_sim_mesh_intersection", "__SCM_LIT_fluid_sim_____SCM_LIT_mesh_intersection__"),
        ("alphabet alpha2 2alpha", "alphabet alpha2 2alpha"),
        ("éalpha alphaé αalpha alpha中", "éalpha alphaé αalpha alpha中"),
    ],
)
def test_conversion_preserves_native_terms_case_and_boundaries(text, expected):
    encoded = cipher.process_forward(text, MAPPING)
    assert encoded == expected
    assert cipher.process_reverse(encoded, MAPPING) == text


@pytest.mark.parametrize(
    ("mapping", "text", "expected"),
    [
        ({"alpha": "beta_state", "beta": "gamma"}, "alpha beta", "beta_state gamma"),
        ({"alpha_beta": "state", "gamma": "beta"}, "alpha_beta gamma", "state beta"),
        ({"alpha": "fluid_sim", "beta": "fluid"}, "fluid_sim", "__SCM_LIT_fluid_sim__"),
        ({"alpha_beta": "state", "alpha": "fluid"}, "alpha_beta", "state"),
        ({"alpha": "fluid__sim"}, "fluid__sim", "__SCM_LIT_fluid__sim__"),
        ({"a+b": "c.d"}, "a+b c.d", "c.d __SCM_LIT_c.d__"),
        ({}, "unchanged\r\n", "unchanged\r\n"),
    ],
)
def test_conversion_does_not_rescan_replacements(mapping, text, expected):
    encoded = cipher.process_forward(text, mapping)
    assert encoded == expected
    assert cipher.process_reverse(encoded, mapping) == text


def test_builtin_dictionary_round_trips_all_supported_cases_and_native_terms():
    mapping = cipher.load_json(SCRIPT.with_name("cipher_dict.json"))
    terms = list(mapping) + list(mapping.values())
    original = "\n".join(term for base in terms for term in (base, base.upper(), base.title()))
    assert cipher.process_reverse(cipher.process_forward(original, mapping), mapping) == original


@pytest.mark.parametrize(
    "mapping",
    [
        [],
        None,
        {"alpha": 1},
        {1: "fluid"},
        {"": "fluid"},
        {"alpha": ""},
        {"Alpha": "fluid"},
        {"alpha": "Fluid"},
        {"alpha": " fluid"},
        {"alpha": "fluid", "beta": "fluid"},
        {"alpha": "beta", "beta": "state"},
        {"alpha": "__scm_lit_fluid__"},
        {"álpha": "fluid"},
    ],
)
def test_invalid_dictionary_is_rejected(mapping):
    with pytest.raises(ValueError):
        cipher.process_forward("alpha", mapping)
    with pytest.raises(ValueError):
        cipher.process_reverse("fluid", mapping)


def test_duplicate_json_keys_are_rejected(tmp_path):
    dictionary = tmp_path / "dict.json"
    dictionary.write_text('{"alpha": "fluid", "alpha": "state"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        cipher.load_json(dictionary)


def test_ambiguous_compound_and_case_mapping_are_rejected():
    with pytest.raises(ValueError, match="ambiguous"):
        cipher.process_forward("alpha_sim", {"alpha": "fluid", "beta": "fluid_sim"})
    with pytest.raises(ValueError, match="ambiguous"):
        cipher.process_forward("Alpha", {"alpha": "x"})
    with pytest.raises(ValueError, match="mixed-case"):
        cipher.process_forward("aLpHa", MAPPING)


def test_unicode_casefold_does_not_match_ascii_terms():
    assert cipher.process_forward("Kelvin", {"kelvin": "temperature"}) == "Kelvin"


@pytest.mark.parametrize(
    "text", ["__SCM_LIT_unknown__", "__SCM_LIT_fluid_sim", "__scm_lit_fluid_sim__"]
)
def test_reserved_or_damaged_markers_are_rejected(text):
    with pytest.raises(ValueError, match="reserved"):
        cipher.process_forward(text, MAPPING)
    with pytest.raises(ValueError, match="marker"):
        cipher.process_reverse(text, MAPPING)


def test_cli_round_trip_from_another_directory_preserves_bytes(tmp_path):
    source = tmp_path / "original.py"
    encoded = tmp_path / "encoded.py"
    restored = tmp_path / "restored.py"
    original = '\ufeffnude = "base_topology"\r\n# café\nNUDE = 1\r\n'.encode()
    source.write_bytes(original)
    for mode, input_path, output_path in [
        ("forward", source, encoded),
        ("reverse", encoded, restored),
    ]:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments(mode, input_path, output_path)],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
        assert "Saved" in result.stdout
        if mode == "forward":
            assert cipher.ledger_path_for(encoded).is_file()
    assert restored.read_bytes() == original
    assert source.read_bytes() == original
    assert not cipher.ledger_path_for(encoded).exists()


def test_ledgers_follow_each_output_and_cleanup_only_the_matching_file(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("base_topology nude", encoding="utf-8")
    destination = tmp_path / "outputs"
    destination.mkdir()
    first = destination / "first.py"
    second = destination / "second.py"
    legacy = destination / cipher.LEDGER_FILE
    legacy.write_text("unrelated legacy ledger", encoding="utf-8")
    for output in (first, second):
        assert cipher.main(arguments("forward", source, output)) == 0
    assert not cipher.ledger_path_for(source).exists()
    first_ledger = cipher.ledger_path_for(first)
    second_ledger = cipher.ledger_path_for(second)
    second_bytes = second_ledger.read_bytes()
    assert cipher.load_json(first_ledger)["track_literals"] == ["base_topology"]
    restored = tmp_path / "restored.py"
    assert cipher.main(arguments("reverse", first, restored)) == 0
    assert restored.read_bytes() == source.read_bytes()
    assert not first_ledger.exists()
    assert second_ledger.read_bytes() == second_bytes
    assert legacy.read_text(encoding="utf-8") == "unrelated legacy ledger"


def test_failed_output_keeps_existing_output_and_ledger(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.py"
    source.write_text("nude base_topology", encoding="utf-8")
    encoded = tmp_path / "encoded.py"
    output = tmp_path / "restored.py"
    assert cipher.main(arguments("forward", source, encoded)) == 0
    ledger = cipher.ledger_path_for(encoded)
    ledger_bytes = ledger.read_bytes()
    output.write_bytes(b"existing output")
    capsys.readouterr()

    def fail_replace(*_args):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(Path, "replace", fail_replace)
    assert cipher.main(arguments("reverse", encoded, output)) == 1
    assert output.read_bytes() == b"existing output"
    assert ledger.read_bytes() == ledger_bytes
    assert not list(tmp_path.glob("*.tmp"))
    captured = capsys.readouterr()
    assert "PASS" not in captured.out
    assert "simulated publication failure" in captured.err


def test_dictionary_change_is_rejected_without_destroying_files(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("alpha", encoding="utf-8")
    encoded = tmp_path / "encoded.py"
    output = tmp_path / "restored.py"
    dictionary = tmp_path / "dictionary.json"
    dictionary.write_text(json.dumps(MAPPING), encoding="utf-8")
    assert cipher.main(arguments("forward", source, encoded, dictionary)) == 0
    dictionary.write_text('{"gamma": "fluid_sim"}', encoding="utf-8")
    assert cipher.main(arguments("reverse", encoded, output, dictionary)) == 1
    assert not output.exists()
    assert cipher.ledger_path_for(encoded).exists()


@pytest.mark.parametrize("mode", ["forward", "reverse"])
def test_ledger_failure_reports_that_output_was_already_saved(tmp_path, monkeypatch, capsys, mode):
    source = tmp_path / "source.py"
    source.write_text("nude base_topology", encoding="utf-8")
    encoded = tmp_path / "encoded.py"
    if mode == "reverse":
        assert cipher.main(arguments("forward", source, encoded)) == 0
        capsys.readouterr()
        ledger = cipher.ledger_path_for(encoded)
        original_unlink = Path.unlink

        def fail_ledger_unlink(path, *args, **kwargs):
            if path == ledger:
                raise OSError("simulated ledger failure")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", fail_ledger_unlink)
        source = encoded
        output = tmp_path / "restored.py"
        expected = "nude base_topology"
    else:

        def fail_save(*_args):
            raise OSError("simulated ledger failure")

        monkeypatch.setattr(cipher, "save_json", fail_save)
        output = encoded
        expected = "base_topology __SCM_LIT_base_topology__"
    assert cipher.main(arguments(mode, source, output)) == 1
    assert output.read_text(encoding="utf-8") == expected
    captured = capsys.readouterr()
    assert "Output saved" in captured.err
    assert "simulated ledger failure" in captured.err
    assert "PASS" not in captured.out


def test_reverse_without_sidecar_supports_legacy_markers(tmp_path):
    source = tmp_path / "encoded.py"
    source.write_text("__SCM_LIT_base_topology__ base_topology", encoding="utf-8")
    restored = tmp_path / "restored.py"
    assert cipher.main(arguments("reverse", source, restored)) == 0
    assert restored.read_text(encoding="utf-8") == "base_topology nude"


def test_in_place_round_trip(tmp_path):
    source = tmp_path / "source.py"
    original = b"nude base_topology\r\n"
    source.write_bytes(original)
    assert cipher.main(arguments("forward", source, source)) == 0
    assert cipher.main(arguments("reverse", source, source)) == 0
    assert source.read_bytes() == original


@pytest.mark.parametrize(
    "failure", ["missing", "directory", "invalid_utf8", "invalid_json", "collision"]
)
def test_cli_errors_leave_inputs_untouched(tmp_path, capsys, failure):
    source = tmp_path / "source.py"
    output = tmp_path / "output.py"
    dictionary = tmp_path / "dictionary.json"
    dictionary.write_text(json.dumps(MAPPING), encoding="utf-8")
    if failure == "directory":
        source.mkdir()
    elif failure != "missing":
        source.write_bytes(b"\xff" if failure == "invalid_utf8" else b"alpha")
    if failure == "invalid_json":
        dictionary.write_text("{broken", encoding="utf-8")
    if failure == "collision":
        output = dictionary
    dictionary_before = dictionary.read_bytes()
    assert cipher.main(arguments("forward", source, output, dictionary)) == 1
    assert dictionary.read_bytes() == dictionary_before
    assert not cipher.ledger_path_for(output).exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[!]" in captured.err
    assert "Traceback" not in captured.err


@pytest.fixture
def encoded_case(tmp_path, capsys):
    source = tmp_path / "source.py"
    source.write_bytes(b"alpha ALPHA fluid_sim\r\n")
    dictionary = tmp_path / "dictionary.json"
    dictionary.write_text(json.dumps(MAPPING), encoding="utf-8")
    encoded = tmp_path / "encoded.py"
    restored = tmp_path / "restored.py"
    assert cipher.main(arguments("forward", source, encoded, dictionary)) == 0
    capsys.readouterr()
    return source, encoded, restored, dictionary


def file_snapshot(directory):
    return {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def test_forward_preview_reports_counts_without_overwriting_anything(tmp_path, capsys):
    source = tmp_path / "source.py"
    source.write_text("alpha ALPHA fluid_sim", encoding="utf-8")
    output = tmp_path / "output.py"
    output.write_bytes(b"existing output")
    cipher.ledger_path_for(output).write_bytes(b"existing ledger")
    dictionary = tmp_path / "dictionary.json"
    dictionary.write_text(json.dumps(MAPPING), encoding="utf-8")
    before = file_snapshot(tmp_path)
    assert (
        cipher.main(arguments("forward", source, output, dictionary) + ["--dry-run", "--json"]) == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "preview"
    assert report["schema_version"] == 1
    assert report["counts"] == {"substitutions": 2, "literals": 1, "terms": {"alpha": 2}}
    assert report["integrity"] == "round_trip_checked"
    assert report["changed"] is True
    assert file_snapshot(tmp_path) == before


def test_diff_implies_preview_and_handles_unterminated_lines(tmp_path, capsys):
    source = tmp_path / "source.py"
    source.write_bytes(b"nude")
    before = file_snapshot(tmp_path)
    assert cipher.main(["--mode", "forward", "--input", str(source), "--diff", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["output"] == str(tmp_path / "source_safe.py")
    assert "-nude\n" in report["diff"]
    assert "+base_topology\n" in report["diff"]
    assert report["diff"].count("\\ No newline at end of file") == 2
    assert file_snapshot(tmp_path) == before


def test_reverse_preview_preserves_the_encoded_file_and_ledger(encoded_case, capsys):
    source, encoded, restored, dictionary = encoded_case
    before = file_snapshot(source.parent)
    assert (
        cipher.main(arguments("reverse", encoded, restored, dictionary) + ["--diff", "--json"]) == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["integrity"] == "unchanged"
    assert report["counts"]["substitutions"] == 2
    assert report["counts"]["literals"] == 1
    assert report["output_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert file_snapshot(source.parent) == before


def test_dictionary_validation_is_read_only_and_canonical(tmp_path, capsys):
    dictionary = tmp_path / "dictionary.json"
    dictionary.write_text(json.dumps(MAPPING), encoding="utf-8")
    before = file_snapshot(tmp_path)
    args = ["--mode", "validate", "--dict", str(dictionary), "--json"]
    assert cipher.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "dictionary_valid"
    assert report["entries"] == 2
    assert file_snapshot(tmp_path) == before
    dictionary.write_text(json.dumps(dict(reversed(list(MAPPING.items())))), encoding="utf-8")
    assert cipher.main(args) == 0
    assert json.loads(capsys.readouterr().out)["dictionary_sha256"] == report["dictionary_sha256"]


def test_version_two_ledger_verifies_byte_hashes_without_writes(encoded_case, capsys):
    source, encoded, _restored, dictionary = encoded_case
    ledger = cipher.load_json(cipher.ledger_path_for(encoded))
    assert ledger["version"] == 2
    assert ledger["original_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert ledger["encoded_sha256"] == hashlib.sha256(encoded.read_bytes()).hexdigest()
    before = file_snapshot(source.parent)
    assert (
        cipher.main(
            ["--mode", "verify", "--input", str(encoded), "--dict", str(dictionary), "--json"]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "verified"
    assert report["integrity"] == "unchanged"
    assert file_snapshot(source.parent) == before


@pytest.mark.parametrize("mode", ["verify", "reverse"])
def test_strict_verification_rejects_edited_input_without_writes(encoded_case, capsys, mode):
    source, encoded, restored, dictionary = encoded_case
    encoded.write_bytes(encoded.read_bytes() + b"mesh_intersection\n")
    restored.write_bytes(b"existing output")
    before = file_snapshot(source.parent)
    if mode == "verify":
        args = ["--mode", mode, "--input", str(encoded), "--dict", str(dictionary), "--json"]
    else:
        args = arguments(mode, encoded, restored, dictionary) + ["--strict", "--json"]
    assert cipher.main(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "error"
    assert "changed" in report["error"]
    assert report["output_saved"] is False
    assert file_snapshot(source.parent) == before


def test_reverse_allows_edits_and_reports_integrity(encoded_case, capsys):
    source, encoded, restored, dictionary = encoded_case
    encoded.write_bytes(encoded.read_bytes() + b"mesh_intersection\n")
    assert cipher.main(arguments("reverse", encoded, restored, dictionary) + ["--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "saved"
    assert report["integrity"] == "edited"
    assert restored.read_bytes() == source.read_bytes() + b"beta\n"


@pytest.mark.parametrize("damage", ["missing", "malformed", "dictionary", "original", "version"])
def test_damaged_integrity_ledger_is_rejected(encoded_case, capsys, damage):
    source, encoded, restored, dictionary = encoded_case
    ledger_path = cipher.ledger_path_for(encoded)
    ledger = cipher.load_json(ledger_path)
    if damage == "missing":
        del ledger["original_sha256"]
    elif damage == "malformed":
        ledger["encoded_sha256"] = 17
    elif damage == "version":
        ledger["version"] = True
    else:
        ledger[f"{damage}_sha256"] = "0" * 64
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    before = file_snapshot(source.parent)
    assert cipher.main(arguments("reverse", encoded, restored, dictionary) + ["--json"]) == 1
    assert json.loads(capsys.readouterr().out)["output_saved"] is False
    assert file_snapshot(source.parent) == before


def test_legacy_ledger_can_reverse_but_cannot_claim_verification(encoded_case, capsys):
    source, encoded, restored, dictionary = encoded_case
    ledger_path = cipher.ledger_path_for(encoded)
    ledger_path.write_text(
        json.dumps(
            {
                "version": 1,
                "original_file": source.name,
                "encoded_file": encoded.name,
                "dictionary": MAPPING,
                "track_literals": ["fluid_sim"],
            }
        ),
        encoding="utf-8",
    )
    before = file_snapshot(source.parent)
    assert (
        cipher.main(["--mode", "verify", "--input", str(encoded), "--dict", str(dictionary)]) == 1
    )
    assert "version-2" in capsys.readouterr().err
    assert file_snapshot(source.parent) == before
    assert cipher.main(arguments("reverse", encoded, restored, dictionary) + ["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["integrity"] == "legacy_ledger"
    assert restored.read_bytes() == source.read_bytes()


def test_verify_requires_a_ledger(tmp_path, capsys):
    source = tmp_path / "encoded.py"
    source.write_bytes(b"base_topology")
    before = file_snapshot(tmp_path)
    assert cipher.main(["--mode", "verify", "--input", str(source), "--json"]) == 1
    assert "version-2" in json.loads(capsys.readouterr().out)["error"]
    assert file_snapshot(tmp_path) == before


def test_keep_ledger_allows_repeated_strict_reverse(encoded_case):
    source, encoded, restored, dictionary = encoded_case
    ledger = cipher.ledger_path_for(encoded)
    ledger_before = ledger.read_bytes()
    args = arguments("reverse", encoded, restored, dictionary) + ["--strict", "--keep-ledger"]
    assert cipher.main(args) == 0
    assert cipher.main(args) == 0
    assert ledger.read_bytes() == ledger_before
    assert restored.read_bytes() == source.read_bytes()


def test_keep_ledger_is_rejected_for_in_place_reverse(encoded_case):
    source, encoded, _restored, dictionary = encoded_case
    before = file_snapshot(source.parent)
    assert cipher.main(arguments("reverse", encoded, encoded, dictionary) + ["--keep-ledger"]) == 1
    assert file_snapshot(source.parent) == before


def test_double_encoding_is_rejected_even_without_literal_markers(tmp_path, capsys):
    source = tmp_path / "source.py"
    source.write_bytes(b"nude")
    assert cipher.main(["--mode", "forward", "--input", str(source)]) == 0
    capsys.readouterr()
    encoded = tmp_path / "source_safe.py"
    before = file_snapshot(tmp_path)
    assert cipher.main(["--mode", "forward", "--input", str(encoded)]) == 1
    assert "already has a cipher ledger" in capsys.readouterr().err
    assert file_snapshot(tmp_path) == before


def test_json_failure_identifies_a_saved_output(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.py"
    source.write_bytes(b"nude")

    def fail_save(*_args):
        raise OSError("ledger failed")

    monkeypatch.setattr(cipher, "save_json", fail_save)
    assert cipher.main(["--mode", "forward", "--input", str(source), "--json"]) == 1
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["output_saved"] is True
    assert report["status"] == "error"
    assert Path(report["output"]).read_bytes() == b"base_topology"
    assert captured.err == ""


@pytest.mark.parametrize(
    "args",
    [
        ["--mode", "forward"],
        ["--mode", "validate", "--input", "unused.py"],
        ["--mode", "verify", "--input", "unused.py", "--output", "unused-out.py"],
        ["--mode", "verify", "--input", "unused.py", "--diff"],
        ["--mode", "forward", "--input", "unused.py", "--strict"],
        ["--mode", "forward", "--input", "unused.py", "--keep-ledger"],
    ],
)
def test_invalid_option_combinations_are_argument_errors(args):
    with pytest.raises(SystemExit) as error:
        cipher.main(args)
    assert error.value.code == 2


def test_new_cli_modes_work_in_subprocesses_with_default_output_names(tmp_path):
    source = tmp_path / "source.py"
    source.write_bytes(b"nude base_topology\r\n")
    encoded = tmp_path / "source_safe.py"
    commands = [
        ["--mode", "validate"],
        ["--mode", "forward", "--input", str(source), "--diff"],
        ["--mode", "forward", "--input", str(source)],
        ["--mode", "verify", "--input", str(encoded)],
        ["--mode", "reverse", "--input", str(encoded), "--strict"],
    ]
    statuses = ["dictionary_valid", "preview", "saved", "verified", "saved"]
    for args, expected in zip(commands, statuses, strict=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *args, "--json"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr or result.stdout
        assert json.loads(result.stdout)["status"] == expected
        if expected == "preview":
            assert not encoded.exists()
    assert (tmp_path / "source_safe_ready.py").read_bytes() == source.read_bytes()
