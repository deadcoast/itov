# Bamboozle Cipher (SCM)

## Overview

Bamboozle is a local, reversible dictionary-based text translator. It maps configured terms to alternate names for source review and restores them afterward. It provides previews, unified diffs, conversion counts, dictionary validation, and per-file integrity records using only the Python standard library.

It processes UTF-8 text, including identifiers, comments, and string literals. Each forward conversion checks that the unedited result reverses exactly. Edited code still needs review and testing.

## Directory Structure

Ensure your `dev_tools` directory is structured exactly as follows within your ComfyUI Portable installation:

```text
D:\AI\ComfyUI_portable\workshop\dev_tools\
├── cipher_dict.json
├── cipher.py
├── ENCRYPT_FOR_CLAUDE.bat
├── DECRYPT_FOR_CLAUDE.bat
└── README.md
```

## Environment & Package Management (uv)

> `setup.py`

```bash
# Using uv to install the local directory into your specific venv
uv pip install -e "\AI\dev_tools" --python ".venv"
```

We use `uv` for dependency management due to its speed and efficiency. The base SCM script relies entirely on Python standard libraries, so no external dependencies are required for the cipher itself.

However, when you begin expanding your custom ComfyUI nodes and need external packages (like `numpy`, `torch`, etc.), use `uv` to install them directly into ComfyUI's isolated environment.

To install a package using `uv`, point it to the embedded executable:

```bash
uv pip install <package_name> --python ..\..\python_embeded\python.exe
```

## The Development Loop

Follow this strict three-step loop when utilizing an LLM to generate or modify your node logic.

### 1. Forward Pass (Encrypt)

1. Locate your working script containing your explicit variables and functions.
2. Drag and drop the file onto `ENCRYPT_FOR_CLAUDE.bat`.
3. The script outputs a translated file and a separate ledger beside it: `node_safe.py` gets `.node_safe.py.scm_ledger.json`. Native target terms are protected by `__SCM_LIT_...__` markers in the text. The ledger records those terms and the dictionary used; keep it local and preserve the markers when editing the translated file.

### 2. LLM Processing

1. Open the newly generated `_safe.py` file and review the translated terms.
2. Use this file in your code-review or editing workflow.
3. Preserve the `__SCM_LIT_...__` markers and use the same dictionary for reversal. Any editing tool may introduce changes that need manual review.

### 3. Reverse Pass (Decrypt)

1. Save the LLM's generated response as a Python file (you can overwrite the `_safe.py` file).
2. Drag and drop this file onto `DECRYPT_FOR_CLAUDE.bat`.
3. The script outputs a `_ready.py` file and deletes only the matching file's ledger after saving successfully. If that ledger exists, its dictionary must match. Legacy markers can also be reversed without a ledger; old directory-wide `.scm_ledger.json` files are left untouched.
4. Move the `_ready.py` file into your ComfyUI `custom_nodes` directory for testing.

## Dictionary Maintenance (`cipher_dict.json`)

If you need to introduce new explicit terms to your workflow, you must update the dictionary.

**Critical Rules:**

1. **Strict 1:1 Mapping:** No two source terms can map to the same target term. Invalid mappings are rejected before conversion.
2. **Valid JSON Formatting:** Ensure standard JSON syntax. Do not leave trailing commas.
3. **Lowercase Base:** Keys and values must be nonempty lowercase ASCII strings without surrounding whitespace. Source and target sets must be disjoint. Duplicate JSON keys, duplicate targets, and the reserved `__SCM_LIT_` prefix are rejected.
4. **Case and Boundaries:** Lowercase, uppercase, and title case are supported. Mixed case is rejected when a term matches. Underscores separate terms; letters and digits do not. Before writing a forward result, the script checks that reversing it restores the original text exactly and rejects ambiguous mappings.

## Command-line use

From the repository root:

```powershell
# Validate the dictionary without reading or changing any source files.
uv run --locked python AI/dev_tools/cipher.py --mode validate

# Preview a conversion. --diff always implies --dry-run.
uv run --locked python AI/dev_tools/cipher.py --mode forward --input node.py --diff

# Save the converted file and its per-file ledger.
uv run --locked python AI/dev_tools/cipher.py --mode forward --input node.py --output node_safe.py

# Verify the encoded bytes and the restored original against the ledger, without writing.
uv run --locked python AI/dev_tools/cipher.py --mode verify --input node_safe.py

# Reverse an edited file, or add --strict to require the unchanged original conversion.
uv run --locked python AI/dev_tools/cipher.py --mode reverse --input node_safe.py --output node_ready.py
```

The default dictionary is resolved beside `cipher.py`, regardless of the working directory. Pass `--dict path/to/mapping.json` to use another mapping. If `--output` is omitted, forward uses `<input-stem>_safe<extension>` and reverse uses `<input-stem>_ready<extension>`. For example, reversing `node_safe.py` defaults to `node_safe_ready.py`.

| Option | Behavior |
| --- | --- |
| `--dry-run` | Convert and validate in memory, report counts, and leave outputs and ledgers untouched. |
| `--diff` | Include a unified diff in a preview; never writes conversion files. |
| `--json` | Emit one JSON execution report to stdout, including conversion failures. Can include a diff. |
| `--strict` | Require a valid version-2 ledger and unchanged encoded bytes when reversing. |
| `--keep-ledger` | Preserve the ledger after reversing to a separate output, allowing repeated verification/restoration. |
| `--mode verify` | Read-only check of the dictionary, encoded hash, and restored-original hash. Requires a version-2 ledger. |
| `--mode validate` | Read-only dictionary schema and uniqueness checks; takes no input/output paths. |

The output directory must already exist for a write. Explicit conversion replaces an existing output; use `--diff` to inspect changes first. In-place conversion is supported, but `--keep-ledger` is rejected for in-place reversal because it would leave an encoded-file ledger attached to restored text. An input with an existing cipher ledger is rejected for another forward pass, preventing accidental double conversion.

Successful operations return exit code 0; file, dictionary, conversion, and integrity errors return 1. Invalid CLI arguments return 2 through argparse on stderr, including when `--json` was requested.

### JSON reports

```powershell
uv run --locked python AI/dev_tools/cipher.py --mode forward --input node.py --dry-run --json
```

Reports use `schema_version: 1`. Conversion reports include `status`, `mode`, input/output paths, byte counts and SHA-256 hashes, `changed`, and `counts` (`substitutions`, `literals`, and per-source-term counts). A literal count means protected native terms during forward conversion and restored markers during reverse conversion. `--diff --json` adds a `diff` string. A failed operation includes `error` and `output_saved`, so callers can distinguish a failed conversion from a ledger failure after output publication.

The `integrity` field states exactly what was checked:

| Value | Meaning |
| --- | --- |
| `round_trip_checked` | The forward result reverses to the input exactly. |
| `unchanged` | Encoded and restored hashes both match the version-2 ledger. |
| `edited` | Encoded bytes differ from the forward pass; ordinary reverse allows the changes. |
| `legacy_ledger` | Version-1 metadata matches, but it has no content hashes. |
| `missing_ledger` | Reverse used the supplied dictionary and inline markers without a sidecar. |

### Ledgers and compatibility

New ledgers use version 2 and record SHA-256 hashes of the original UTF-8 bytes, encoded UTF-8 bytes, and canonical dictionary. Dictionary key ordering and JSON formatting do not affect its hash. These hashes check local consistency; they do not authenticate a ledger independently of the file.

Ordinary reverse still accepts version-1 ledgers and files without ledgers, including the existing `__SCM_LIT_...__` marker format. `verify` and `--strict` require version 2. A malformed or mismatched ledger is rejected and preserved. Keep the encoded filename and matching ledger together; the stored filename must match when a sidecar is present.

UTF-8 content, its BOM if present, and existing line endings are preserved. Output files are replaced only after a complete temporary write. Output and ledger updates are separate operations: if a ledger write or cleanup fails after output was saved, the error explicitly says so.

The round-trip check covers unedited text with the same dictionary. Newly introduced, unmarked target terms in edited text are reverse-mapped too. This tool does not parse or validate Python. The `process_forward(text, mapping)` and `process_reverse(text, mapping)` helpers remain pure transformations; the CLI manages files and ledgers.

## Troubleshooting

- **Batch files crashing instantly:** The `.bat` files use relative paths to locate `..\..\python_embeded\python.exe`. If you move the `dev_tools` folder to a different directory depth, you must edit the `.bat` files and update the `PYTHON_EXE` path, otherwise Windows will fail to execute the script.

---
