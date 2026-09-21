import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "AI" / "dev_tools"
SPEC = importlib.util.spec_from_file_location(
    "bamboozle_under_test", TOOLS / "__init__.py", submodule_search_locations=[str(TOOLS)]
)
PACKAGE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PACKAGE
SPEC.loader.exec_module(PACKAGE)
cli = importlib.import_module("bamboozle_under_test.cli")
cipher = cli.cipher


@pytest.fixture
def files(tmp_path):
    source = tmp_path / "source file.py"
    source.write_bytes(b"alpha = 'fluid_sim'\r\n")
    mapping = tmp_path / "mapping.json"
    mapping.write_text('{"alpha": "fluid_sim"}', encoding="utf-8")
    return source, mapping


def run_cli(args, cwd, text_input=None):
    return subprocess.run(
        [sys.executable, str(TOOLS / "cli.py"), *map(str, args)],
        input=text_input,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=15,
    )


def snapshot(directory):
    return {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def test_no_arguments_in_a_pipe_shows_help_without_waiting(tmp_path):
    result = run_cli([], tmp_path, "")
    assert result.returncode == 0
    assert "encode" in result.stdout and "interactive" in result.stdout
    assert "Action:" not in result.stdout


def test_directory_entry_point_works_without_installation(tmp_path):
    result = subprocess.run(
        [sys.executable, str(TOOLS), "validate", "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "dictionary_valid"


def test_version_flag_reports_the_package_version(tmp_path):
    result = run_cli(["--version"], tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == "Bamboozle " + PACKAGE.__version__


def test_interactive_reprompts_for_a_missing_file_without_restarting_action(files):
    source, mapping = files
    before = snapshot(source.parent)
    result = run_cli(
        ["interactive", "--dict", mapping],
        source.parent,
        f"e\nmissing.py\n{source}\nc\nq\n",
    )
    assert result.returncode == 0
    assert "Choose an existing file" in result.stderr
    assert "-alpha" in result.stdout
    assert snapshot(source.parent) == before


def test_json_without_a_command_is_an_argument_error():
    with pytest.raises(SystemExit) as error:
        cli.main(["--json"])
    assert error.value.code == 2


def test_cli_reports_saved_output_when_temporary_cleanup_fails(files, monkeypatch, capsys):
    source, mapping = files
    original_unlink = Path.unlink

    def deny_cleanup(path, *args, **kwargs):
        if path.suffix == ".tmp":
            raise PermissionError("temporary cleanup denied")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_cleanup)
    assert cli.main(["encode", str(source), "--dict", str(mapping), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "error"
    assert report["output_saved"] is True
    assert Path(report["output"]).is_file()


@pytest.mark.parametrize(
    "command", ["preview", "encode", "decode", "verify", "validate", "interactive"]
)
def test_subcommands_have_help(command, tmp_path):
    result = run_cli([command, "--help"], tmp_path)
    assert result.returncode == 0
    assert "usage: bamboozle" in result.stdout


@pytest.mark.parametrize("flags_first", [False, True])
def test_preview_and_global_options_work_on_either_side(files, capsys, flags_first):
    source, mapping = files
    before = snapshot(source.parent)
    command = ["preview", str(source)]
    flags = ["--dict", str(mapping), "--json"]
    assert cli.main(flags + command if flags_first else command + flags) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "preview"
    assert "-alpha" in report["diff"]
    assert snapshot(source.parent) == before


def test_commands_encode_verify_and_decode_with_spaces(files):
    source, mapping = files
    encoded = source.with_name("source file_safe.py")
    restored = source.with_name("restored file.py")
    commands = [
        ["encode", source],
        ["verify", encoded],
        ["decode", encoded, "-o", restored, "--strict", "--keep-ledger"],
    ]
    for args in commands:
        result = run_cli([*args, "--dict", mapping, "--json"], source.parent)
        assert result.returncode == 0, result.stdout + result.stderr
    assert restored.read_bytes() == source.read_bytes()
    assert cipher.ledger_path_for(encoded).is_file()


@pytest.mark.parametrize("flag", ["--preview", "--diff", "--dry-run"])
def test_encode_preview_flags_never_write(files, capsys, flag):
    source, mapping = files
    before = snapshot(source.parent)
    assert cli.main(["encode", str(source), "--dict", str(mapping), flag, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "preview"
    assert snapshot(source.parent) == before


def test_new_commands_require_force_for_existing_destinations(files, capsys):
    source, mapping = files
    encoded = source.with_name("source file_safe.py")
    encoded.write_bytes(b"existing output")
    ledger = cipher.ledger_path_for(encoded)
    ledger.write_bytes(b"existing ledger")
    before = snapshot(source.parent)
    args = ["encode", str(source), "--dict", str(mapping), "--json"]
    assert cli.main(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert "--force" in report["error"]
    assert report["output_saved"] is False
    assert snapshot(source.parent) == before
    assert cli.main(args + ["--force"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "saved"
    assert cipher.load_json(ledger)["version"] == 2


def test_interactive_preview_and_save_with_quoted_path(files):
    source, mapping = files
    result = run_cli(
        ["interactive", "--dict", mapping],
        source.parent,
        f'e\n"{source}"\ns\nq\n',
    )
    assert result.returncode == 0, result.stderr
    assert "-alpha" in result.stdout
    assert "Saved" in result.stdout
    encoded = source.with_name("source file_safe.py")
    assert encoded.read_bytes() == b"fluid_sim = '__SCM_LIT_fluid_sim__'\r\n"
    assert cipher.ledger_path_for(encoded).exists()


@pytest.mark.parametrize("ending", ["\nq\n", "c\nq\n", ""])
def test_interactive_cancel_enter_and_eof_leave_files_untouched(files, ending):
    source, mapping = files
    before = snapshot(source.parent)
    result = run_cli(["interactive", "--dict", mapping], source.parent, f"e\n{source}\n{ending}")
    assert result.returncode == 0, result.stderr
    assert snapshot(source.parent) == before


def test_interactive_can_change_output_path(files):
    source, mapping = files
    output = source.with_name("chosen output.py")
    result = run_cli(
        ["interactive", "--dict", mapping],
        source.parent,
        f"e\n{source}\no\n'{output}'\ns\nq\n",
    )
    assert result.returncode == 0, result.stderr
    assert output.exists()
    assert not source.with_name("source file_safe.py").exists()


@pytest.mark.parametrize("confirm", ["no", "OVERWRITE"])
def test_interactive_overwrite_requires_the_displayed_confirmation(files, confirm):
    source, mapping = files
    encoded = source.with_name("source file_safe.py")
    encoded.write_bytes(b"existing")
    ending = "q\n" if confirm == "OVERWRITE" else "c\nq\n"
    result = run_cli(
        ["interactive", "--dict", mapping],
        source.parent,
        f"e\n{source}\ns\n{confirm}\n{ending}",
    )
    assert result.returncode == 0, result.stderr
    assert "Existing destination:" in result.stdout
    assert (encoded.read_bytes() != b"existing") == (confirm == "OVERWRITE")


def test_interactive_decode_and_verify(files):
    source, mapping = files
    encoded = source.with_name("source file_safe.py")
    assert cli.main(["encode", str(source), "--dict", str(mapping)]) == 0
    result = run_cli(
        ["interactive", "--dict", mapping],
        source.parent,
        f"v\n{encoded}\nd\n{encoded}\ns\nq\n",
    )
    assert result.returncode == 0, result.stderr
    assert "VERIFIED" in result.stdout
    assert source.with_name("source file_safe_ready.py").read_bytes() == source.read_bytes()


def test_interactive_recovers_from_bad_actions_and_paths(files):
    source, mapping = files
    before = snapshot(source.parent)
    result = run_cli(
        ["interactive", "--dict", mapping],
        source.parent,
        "garbage\ne\nmissing.py\ne\n\nq\n",
    )
    assert result.returncode == 0
    assert "Choose E, D, V, or Q" in result.stdout
    assert "[!]" in result.stderr
    assert "Traceback" not in result.stderr
    assert snapshot(source.parent) == before


@pytest.mark.parametrize("changed", ["source", "dictionary", "output", "ledger"])
def test_apply_rejects_changes_since_preview(files, changed):
    source, mapping = files
    plan = cipher.prepare_conversion("forward", source, dict_path=mapping)
    paths = {
        "source": source,
        "dictionary": mapping,
        "output": plan["output_path"],
        "ledger": plan["ledger_path"],
    }
    paths[changed].write_bytes(b"changed after preview")
    before = snapshot(source.parent)
    with pytest.raises(ValueError, match="changed since preview"):
        cipher.apply_conversion(plan)
    assert snapshot(source.parent) == before


def test_interactive_saves_only_the_reviewed_text(files, monkeypatch, capsys):
    source, mapping = files
    answers = iter(["e", str(source), "s", "q"])

    def answer(prompt):
        if "[S] Save" in prompt:
            source.write_bytes(b"edited while preview was open")
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(["interactive", "--dict", str(mapping)]) == 0
    assert "changed since preview" in capsys.readouterr().err
    assert not source.with_name("source file_safe.py").exists()


def test_no_clobber_publication_preserves_a_raced_in_output(files, monkeypatch):
    source, mapping = files
    plan = cipher.prepare_conversion("forward", source, dict_path=mapping)
    original_link = os.link

    def concurrent_creation(src, dst):
        Path(dst).write_bytes(b"created by someone else")
        return original_link(src, dst)

    monkeypatch.setattr(cipher.os, "link", concurrent_creation)
    with pytest.raises(FileExistsError):
        cipher.apply_conversion(plan, overwrite=False)
    assert plan["output_path"].read_bytes() == b"created by someone else"
    assert not plan["ledger_path"].exists()
    assert not list(source.parent.glob("*.tmp"))


def test_a_saved_plan_cannot_be_applied_twice(files):
    source, mapping = files
    plan = cipher.prepare_conversion("forward", source, dict_path=mapping)
    cipher.apply_conversion(plan, overwrite=False)
    before = snapshot(source.parent)
    with pytest.raises(ValueError, match="unsaved"):
        cipher.apply_conversion(plan)
    assert snapshot(source.parent) == before


def test_ctrl_c_exits_cleanly(files, monkeypatch, capsys):
    source, mapping = files
    before = snapshot(source.parent)

    def interrupt(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert cli.main(["interactive", "--dict", str(mapping)]) == 130
    assert "Interrupted" in capsys.readouterr().err
    assert snapshot(source.parent) == before


def test_interruption_after_output_publication_is_reported(files, monkeypatch, capsys):
    source, mapping = files

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cipher, "save_json", interrupt)
    assert cli.main(["encode", str(source), "--dict", str(mapping), "--json"]) == 130
    report = json.loads(capsys.readouterr().out)
    assert report["output_saved"] is True
    assert report["status"] == "error"
    assert "Interrupted" in report["error"]


@pytest.mark.parametrize(
    "args",
    [
        ["encode"],
        ["preview", "unused.py", "--strict"],
        ["interactive", "--json"],
    ],
)
def test_invalid_cli_arguments_return_two(args):
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell launcher")
def test_powershell_launcher_works_from_another_directory(files):
    source, mapping = files
    result = subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(TOOLS / "bamboozle.ps1"),
            "preview",
            source.name,
            "--dict",
            mapping.name,
            "--json",
        ],
        cwd=source.parent,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "preview"
    assert report["input"] == str(source)
    assert not source.with_name("source file_safe.py").exists()


def test_cli_and_legacy_restore_custom_mapping_without_dictionary_argument(files):
    source, mapping = files
    assert run_cli(["encode", source, "--dict", mapping], source.parent).returncode == 0
    mapping.unlink()
    encoded = source.with_name("source file_safe.py")
    for command in (["verify", encoded], ["preview", encoded, "--reverse"]):
        result = run_cli([*command, "--json"], source.parent)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["dictionary_source"] == "ledger"
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "cipher.py"),
            "--mode",
            "reverse",
            "--input",
            str(encoded),
            "--json",
        ],
        cwd=source.parent,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path(json.loads(result.stdout)["output"]).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("command", ["encode", "decode", "preview"])
def test_context_option_implies_a_read_only_diff(files, capsys, command):
    source, mapping = files
    source.write_bytes(b"neighbor\nalpha\ntail\n")
    before = snapshot(source.parent)
    assert cli.main([command, str(source), "--dict", str(mapping), "--context", "0", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "preview"
    assert report["diff_context"] == 0
    assert "neighbor" not in report["diff"]
    assert snapshot(source.parent) == before


@pytest.mark.parametrize("value", ["-1", "invalid"])
def test_invalid_context_is_an_argument_error(value):
    with pytest.raises(SystemExit) as error:
        cli.main(["preview", "unused.py", "--context", value])
    assert error.value.code == 2


def test_interactive_refresh_reviews_updated_source_before_save(files, monkeypatch, capsys):
    source, mapping = files
    answers = iter(["e", str(source), "r", "s", "q"])
    previews = 0

    def answer(prompt):
        nonlocal previews
        if "[S] Save" in prompt:
            previews += 1
            if previews == 1:
                source.write_bytes(b"alpha alpha\r\n")
        return next(answers)

    monkeypatch.setattr("builtins.input", answer)
    assert cli.main(["interactive", "--dict", str(mapping)]) == 0
    shown = capsys.readouterr().out
    assert previews == 2 and "-alpha alpha" in shown
    assert source.with_name("source file_safe.py").read_bytes() == b"fluid_sim fluid_sim\r\n"


def test_interactive_restore_displays_saved_dictionary(files):
    source, mapping = files
    assert run_cli(["encode", source, "--dict", mapping], source.parent).returncode == 0
    mapping.unlink()
    encoded = source.with_name("source file_safe.py")
    result = run_cli(["interactive"], source.parent, f"d\n{encoded}\ns\nq\n")
    assert result.returncode == 0, result.stderr
    assert "Dictionary: saved in ledger" in result.stdout
    assert source.with_name("source file_safe_ready.py").read_bytes() == source.read_bytes()


def test_force_does_not_bypass_destination_ledger_conflict(files, capsys):
    source, mapping = files
    encoded = cipher.prepare_conversion("forward", source, dict_path=mapping)
    cipher.apply_conversion(encoded, overwrite=False)
    output = source.with_name("other.py")
    output.write_bytes(b"other encoded file")
    cipher.ledger_path_for(output).write_bytes(b"other ledger")
    before = snapshot(source.parent)
    assert (
        cli.main(["decode", str(encoded["output_path"]), "-o", str(output), "--force", "--json"])
        == 1
    )
    report = json.loads(capsys.readouterr().out)
    assert "own cipher ledger" in report["error"]
    assert report["output_saved"] is False
    assert snapshot(source.parent) == before


def test_interactive_preview_preserves_unicode_separators_in_diff_lines(files, capsys):
    source, mapping = files
    source.write_text("alpha\u2028tail\n", encoding="utf-8")
    plan = cipher.prepare_conversion("forward", source, dict_path=mapping)
    cipher.add_preview_diff(plan)
    cli.show_preview(plan)
    assert "-alpha\u2028tail\n+fluid_sim\u2028tail\n" in capsys.readouterr().out
