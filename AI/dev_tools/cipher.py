"""Reversible, dictionary-based text substitution for local source files."""

import argparse
import difflib
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

LITERAL_PREFIX = "__SCM_LIT_"
LITERAL_TEMPLATE = LITERAL_PREFIX + "{}__"
LEDGER_FILE = ".scm_ledger.json"
LEDGER_VERSION = 2


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_json(file_path):
    with open(file_path, encoding="utf-8-sig") as source:
        return json.load(source, object_pairs_hook=_unique_pairs)


def write_text_atomic(text, file_path):
    """Publish a complete UTF-8 file without truncating an existing destination."""
    file_path = Path(file_path)
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=file_path.parent,
            prefix=f".{file_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary_path = Path(output.name)
            output.write(text)
        temporary_path.replace(file_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def save_json(data, file_path):
    write_text_atomic(json.dumps(data, indent=2) + "\n", file_path)


def validate_dictionary(cipher_dict):
    if not isinstance(cipher_dict, dict):
        raise ValueError("Dictionary must be a JSON object mapping terms to terms.")
    for source, target in cipher_dict.items():
        for term in (source, target):
            if (
                not isinstance(term, str)
                or not term.isascii()
                or not term.islower()
                or term != term.lower()
                or term != term.strip()
            ):
                raise ValueError("Dictionary terms must be nonempty lowercase ASCII strings.")
            if LITERAL_PREFIX.lower() in term:
                raise ValueError(
                    f"Dictionary terms cannot contain reserved prefix {LITERAL_PREFIX}."
                )
    if len(set(cipher_dict.values())) != len(cipher_dict):
        raise ValueError("Dictionary targets must be unique for reversible conversion.")
    if set(cipher_dict) & set(cipher_dict.values()):
        raise ValueError("Dictionary source and target terms must not overlap.")


def match_case(original, target):
    if original.isupper():
        return target.upper()
    if original.istitle():
        return target.title()
    if original.islower():
        return target.lower()
    raise ValueError(f"Unsupported mixed-case term: {original!r}; use lower, upper, or title case.")


def _alternatives(terms):
    # The never-matching expression makes an empty dictionary an identity operation.
    return (
        "|".join(re.escape(term) for term in sorted(terms, key=lambda t: (-len(t), t))) or r"(?!)"
    )


def _term_pattern(terms):
    # Underscores separate terms; Unicode letters/digits remain identifier characters.
    # ASCII case folding avoids matching e.g. a Kelvin sign as the letter K.
    return r"(?<![^\W_])(?ai:" + _alternatives(terms) + r")(?![^\W_])"


def _literal_pattern(cipher_dict):
    return (
        re.escape(LITERAL_PREFIX)
        + "(?P<literal>(?ai:"
        + _alternatives(cipher_dict.values())
        + "))__"
    )


def process_forward(text, cipher_dict):
    """Convert once, shielding native target terms from all substitutions."""
    validate_dictionary(cipher_dict)
    if LITERAL_PREFIX.lower() in text.lower():
        raise ValueError(f"Input contains reserved {LITERAL_PREFIX} markers; reverse it first.")

    def replace(match):
        original = match.group(0)
        target = cipher_dict.get(original.lower())
        if target is None:
            return LITERAL_TEMPLATE.format(original)
        return match_case(original, target)

    pattern = _term_pattern(set(cipher_dict) | set(cipher_dict.values()))
    result = re.sub(pattern, replace, text)
    # Compound names or lossy case mappings can otherwise decode into a different term.
    if process_reverse(result, cipher_dict) != text:
        raise ValueError(
            "Dictionary mapping is ambiguous for this input; round trip would lose text."
        )
    return result


def process_reverse(text, cipher_dict):
    """Restore literals and reverse substitutions in one pass, without rescanning output."""
    validate_dictionary(cipher_dict)
    literal_pattern = _literal_pattern(cipher_dict)
    unprotected = re.sub(literal_pattern, "", text)
    if LITERAL_PREFIX.lower() in unprotected.lower():
        raise ValueError("Unrecognized or damaged literal marker; preserve the original markers.")
    reverse_dict = {target: source for source, target in cipher_dict.items()}

    def replace(match):
        if match.group("literal") is not None:
            return match.group("literal")
        original = match.group(0)
        return match_case(original, reverse_dict[original.lower()])

    return re.sub(literal_pattern + "|" + _term_pattern(reverse_dict), replace, text)


def ledger_path_for(encoded_path):
    return encoded_path.with_name(f".{encoded_path.name}{LEDGER_FILE}")


def text_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def dictionary_hash(cipher_dict):
    return text_hash(json.dumps(cipher_dict, sort_keys=True, separators=(",", ":")))


def conversion_counts(text, cipher_dict, mode):
    """Count original matches, without counting text introduced by replacements."""
    terms = {}
    literals = 0
    if mode == "forward":
        pattern = _term_pattern(set(cipher_dict) | set(cipher_dict.values()))
        for match in re.finditer(pattern, text):
            term = match.group(0).lower()
            if term in cipher_dict:
                terms[term] = terms.get(term, 0) + 1
            else:
                literals += 1
    else:
        reverse_dict = {target: source for source, target in cipher_dict.items()}
        pattern = _literal_pattern(cipher_dict) + "|" + _term_pattern(reverse_dict)
        for match in re.finditer(pattern, text):
            if match.group("literal") is not None:
                literals += 1
            else:
                term = reverse_dict[match.group(0).lower()]
                terms[term] = terms.get(term, 0) + 1
    return {"substitutions": sum(terms.values()), "literals": literals, "terms": terms}


def make_ledger(text, result, cipher_dict, input_path, output_path):
    return {
        "version": LEDGER_VERSION,
        "original_file": input_path.name,
        "encoded_file": output_path.name,
        "dictionary": cipher_dict,
        "dictionary_sha256": dictionary_hash(cipher_dict),
        "original_sha256": text_hash(text),
        "encoded_sha256": text_hash(result),
        "track_literals": sorted(
            {m.group("literal").lower() for m in re.finditer(_literal_pattern(cipher_dict), result)}
        ),
        # Keep the standalone script compatible with Python 3.8.
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),  # noqa: UP017
    }


def validate_ledger(ledger, cipher_dict, input_path):
    if (
        not isinstance(ledger, dict)
        or type(ledger.get("version")) is not int
        or ledger["version"] not in (1, LEDGER_VERSION)
        or ledger.get("encoded_file") != input_path.name
        or ledger.get("dictionary") != cipher_dict
    ):
        raise ValueError("Ledger does not match this file and dictionary; left untouched.")
    if ledger["version"] == LEDGER_VERSION:
        for field in ("dictionary_sha256", "original_sha256", "encoded_sha256"):
            value = ledger.get(field)
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError(f"Ledger has an invalid or missing {field}.")
        if ledger["dictionary_sha256"] != dictionary_hash(cipher_dict):
            raise ValueError("Ledger dictionary hash does not match the current dictionary.")


def reverse_integrity(text, result, ledger, strict=False):
    if ledger is None or ledger["version"] == 1:
        if strict:
            raise ValueError("Verification requires a version-2 ledger with integrity hashes.")
        return "missing_ledger" if ledger is None else "legacy_ledger"
    if text_hash(text) != ledger["encoded_sha256"]:
        if strict:
            raise ValueError(
                "Encoded file has changed since the forward pass; verification failed."
            )
        return "edited"
    if text_hash(result) != ledger["original_sha256"]:
        raise ValueError("Restored text does not match the original hash recorded in the ledger.")
    return "unchanged"


def preview_diff(original, result, input_path, output_path):
    lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        result.splitlines(keepends=True),
        fromfile=str(input_path),
        tofile=str(output_path),
    )
    # Keep a final unterminated source line from swallowing the next diff line.
    return "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n" for line in lines
    )


def emit_report(report, as_json):
    if as_json:
        print(json.dumps(report, sort_keys=True))
        return
    status = report["status"]
    if status == "dictionary_valid":
        print(f"[*] Dictionary valid: {report['entries']} mappings ({report['dictionary']}).")
        return
    if status == "verified":
        print(f"[*] VERIFIED: {report['input']}; encoded and restored hashes match the ledger.")
        return
    counts = report["counts"]
    summary = f"{counts['substitutions']} substitutions, {counts['literals']} native literals"
    if status == "preview":
        print(f"[*] PREVIEW: {report['output']} ({summary}). No files written.")
    else:
        print(f"[*] {report['mode'].upper()} PASS: Saved {report['output']} ({summary}).")
    if report.get("integrity") == "edited":
        print("[*] Input differs from the forward pass; restored edited text requires review.")
    if report.get("diff"):
        print(report["diff"], end="")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Bamboozle Cipher — reversible local text conversion"
    )
    parser.add_argument(
        "--mode", choices=["forward", "reverse", "verify", "validate"], required=True
    )
    parser.add_argument("--input", type=Path, help="UTF-8 source file")
    parser.add_argument(
        "--output", type=Path, help="Destination (default: input stem + _safe or _ready)"
    )
    parser.add_argument(
        "--dict",
        default=Path(__file__).with_name("cipher_dict.json"),
        type=Path,
        help="Mapping JSON (default: cipher_dict.json beside this script)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing files")
    parser.add_argument(
        "--diff", action="store_true", help="Show a unified diff; implies --dry-run"
    )
    parser.add_argument("--json", action="store_true", help="Print a machine-readable report")
    parser.add_argument(
        "--strict", action="store_true", help="Reverse only a verified, unchanged file"
    )
    parser.add_argument(
        "--keep-ledger", action="store_true", help="Keep the ledger after reversing"
    )
    args = parser.parse_args(argv)
    if args.mode != "validate" and args.input is None:
        parser.error("--input is required for forward, reverse, and verify")
    if args.mode in ("validate", "verify") and (args.output or args.diff or args.dry_run):
        parser.error("--output, --diff, and --dry-run apply only to forward and reverse")
    if args.mode == "validate" and args.input:
        parser.error("--input does not apply to dictionary validation")
    if args.mode != "reverse" and (args.strict or args.keep_ledger):
        parser.error("--strict and --keep-ledger apply only to reverse")

    output_saved = False
    report = {"schema_version": 1, "mode": args.mode}
    try:
        dict_path = args.dict.resolve()
        cipher_dict = load_json(dict_path)
        validate_dictionary(cipher_dict)
        if args.mode == "validate":
            report.update(
                status="dictionary_valid",
                dictionary=str(dict_path),
                entries=len(cipher_dict),
                dictionary_sha256=dictionary_hash(cipher_dict),
            )
            emit_report(report, args.json)
            return 0

        input_path = args.input.resolve()
        suffix = "_safe" if args.mode == "forward" else "_ready"
        output_path = (
            args.output.resolve()
            if args.output
            else input_path.with_name(input_path.stem + suffix + input_path.suffix)
        )
        encoded_path = output_path if args.mode == "forward" else input_path
        ledger_path = ledger_path_for(encoded_path)
        if args.mode != "verify" and (
            output_path in (dict_path, ledger_path_for(input_path))
            or ledger_path in (input_path, output_path, dict_path)
        ):
            raise ValueError("Input, output, dictionary, and ledger paths must not conflict.")
        if args.keep_ledger and output_path == input_path:
            raise ValueError("Cannot keep the encoded-file ledger when reversing in place.")
        report.update(input=str(input_path), ledger=str(ledger_path))
        with input_path.open(encoding="utf-8", newline="") as source:
            text = source.read()

        ledger_data = None
        if args.mode == "forward":
            if ledger_path_for(input_path).exists():
                raise ValueError(
                    "Input already has a cipher ledger; reverse it before encoding again."
                )
            result = process_forward(text, cipher_dict)
            ledger_data = make_ledger(text, result, cipher_dict, input_path, output_path)
            integrity = "round_trip_checked"
        else:
            if ledger_path.exists():
                ledger_data = load_json(ledger_path)
                validate_ledger(ledger_data, cipher_dict, input_path)
            result = process_reverse(text, cipher_dict)
            integrity = reverse_integrity(
                text, result, ledger_data, strict=args.strict or args.mode == "verify"
            )

        report.update(
            integrity=integrity,
            input_sha256=text_hash(text),
            output_sha256=text_hash(result),
            input_bytes=len(text.encode("utf-8")),
            output_bytes=len(result.encode("utf-8")),
            counts=conversion_counts(text, cipher_dict, args.mode),
            changed=text != result,
        )
        if args.mode == "verify":
            report["status"] = "verified"
            emit_report(report, args.json)
            return 0

        report["output"] = str(output_path)
        if args.diff:
            report["diff"] = preview_diff(text, result, input_path, output_path)
        if args.dry_run or args.diff:
            report["status"] = "preview"
        else:
            write_text_atomic(result, output_path)
            output_saved = True
            if args.mode == "forward":
                save_json(ledger_data, ledger_path)
            elif ledger_data is not None and not args.keep_ledger:
                ledger_path.unlink()
            report["status"] = "saved"
        emit_report(report, args.json)
        return 0
    except (OSError, UnicodeError, ValueError) as error:
        if args.json:
            report.update(status="error", error=str(error), output_saved=output_saved)
            emit_report(report, True)
        elif output_saved:
            print(
                f"[!] Output saved to {output_path}, but finalization failed: {error}",
                file=sys.stderr,
            )
        else:
            print(f"[!] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
