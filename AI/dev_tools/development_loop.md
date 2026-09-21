# Bamboozle development loop

1. Forward Pass (Encrypt)

- Locate your working script (e.g., gangbang_node.py) containing your explicit variables and functions.
- Drag and drop the file onto ENCRYPT_FOR_CLAUDE.bat.
- The script outputs a translated file and a ledger named `.<output-filename>.scm_ledger.json` beside it. Preserve all `__SCM_LIT_...__` markers: they protect native target terms. Keep the ledger local; it records the dictionary used.
- To preview first, run `python cipher.py --mode forward --input path/to/node.py --diff`. A preview leaves files and ledgers untouched. `--mode validate` checks the dictionary separately.

1. LLM Processing

- Open and review the newly generated `_safe.py` file.
- Use it in your code-review or editing workflow, preserving literal markers.
- Before editing, `python cipher.py --mode verify --input path/to/node_safe.py` checks the encoded file and restored original against the version-2 ledger without changing either file.

1. Reverse Pass (Decrypt)

- Save the LLM's generated response as a Python file (you can overwrite the _safe.py file).
- Drag and drop this file onto DECRYPT_FOR_CLAUDE.bat.
- The script outputs a `_ready.py` file and removes only its matching ledger after a successful save. Use the same dictionary in both passes and review edited code; new unmarked target terms will also be reverse-mapped. See [conversion rules and limits](README.md#dictionary-maintenance-cipher_dictjson).
- Add `--strict` when reversing through the CLI to require an unchanged encoded file. Add `--keep-ledger` when restoring to a separate output if you want to retain the ledger for another check. `--diff` previews reversal without deleting the ledger.
- Move the _ready.py file into your ComfyUI custom_nodes directory for testing.
