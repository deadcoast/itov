# development loop

1. Forward Pass (Encrypt)

- Locate your working script (e.g., gangbang_node.py) containing your explicit variables and functions.
- Drag and drop the file onto ENCRYPT_FOR_CLAUDE.bat.
- The script will output a sanitized file (e.g., gangbang_node_safe.py) and generate a .scm_ledger.json file. This ledger tracks native physics terms already present in your code to prevent collisions during decryption.

1. LLM Processing

- Open the newly generated _safe.py file. All restricted terms will be replaced with their mapped physics equivalents.
- Copy and paste this sanitized code into your LLM of choice.
- Prompt the LLM to modify, fix, or expand the code as needed. It will process the logic without throwing safety errors.

1. Reverse Pass (Decrypt)

- Save the LLM's generated response as a Python file (you can overwrite the _safe.py file).
- Drag and drop this file onto DECRYPT_FROM_CLAUDE.bat.
- The script will output a _ready.py file with all explicit terminology perfectly restored, and it will automatically delete the .scm_ledger.json file.
- Move the _ready.py file into your ComfyUI custom_nodes directory for testing.
