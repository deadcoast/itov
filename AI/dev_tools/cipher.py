import json
import re
import argparse
import sys
from pathlib import Path
from datetime import datetime

LITERAL_TEMPLATE = "__SCM_LIT_{}__"
LITERAL_REGEX = r"__SCM_LIT_(.*?)__"
LEDGER_FILE = ".scm_ledger.json"

def load_json(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Error loading JSON {file_path}: {e}")
        sys.exit(1)

def save_json(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)

def match_case(original, target):
    if original.isupper():
        return target.upper()
    elif original.istitle():
        return target.title()
    return target.lower()

def process_forward(text, cipher_dict, input_path):
    # Sort to prevent substring collision (longest first)
    physics_terms = sorted(list(set(cipher_dict.values())), key=len, reverse=True)
    explicit_terms = sorted(list(cipher_dict.keys()), key=len, reverse=True)
    
    tracked_literals = []

    # 1. Protect native physics terms already in the file
    # Using lookarounds instead of \b to handle snake_case (e.g. native_fluid_sim)
    for p_term in physics_terms:
        pattern = r'(?<![a-zA-Z0-9])' + re.escape(p_term) + r'(?![a-zA-Z0-9])'
        if re.search(pattern, text, flags=re.IGNORECASE):
            tracked_literals.append(p_term)
            text = re.sub(pattern, lambda m: LITERAL_TEMPLATE.format(m.group(0)), text, flags=re.IGNORECASE)

    # 2. Swap explicit terms to physics terms
    for e_term in explicit_terms:
        p_term = cipher_dict[e_term]
        pattern = r'(?<![a-zA-Z0-9])' + re.escape(e_term) + r'(?![a-zA-Z0-9])'
        text = re.sub(pattern, lambda m: match_case(m.group(0), p_term), text, flags=re.IGNORECASE)

    # 3. Generate Ledger in the exact same directory as the input file
    ledger_data = {
        "original_file": input_path.name,
        "track_literals": tracked_literals,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    ledger_path = input_path.parent / LEDGER_FILE
    save_json(ledger_data, ledger_path)

    return text

def process_reverse(text, cipher_dict, input_path):
    physics_terms = sorted(list(set(cipher_dict.values())), key=len, reverse=True)
    reverse_dict = {v.lower(): k for k, v in cipher_dict.items()}

    # 1. Swap physics terms back to explicit terms
    for p_term in physics_terms:
        e_term = reverse_dict[p_term.lower()]
        pattern = r'(?<![a-zA-Z0-9])' + re.escape(p_term) + r'(?![a-zA-Z0-9])'
        text = re.sub(pattern, lambda m: match_case(m.group(0), e_term), text, flags=re.IGNORECASE)

    # 2. Unwrap the protected native literals
    text = re.sub(LITERAL_REGEX, r"\1", text)

    # Clean up ledger if it exists in the input file's directory
    ledger_path = input_path.parent / LEDGER_FILE
    if ledger_path.exists():
        ledger_path.unlink()

    return text

def main():
    parser = argparse.ArgumentParser(description="Semantic Cipher Middleware (SCM)")
    parser.add_argument("--mode", choices=["forward", "reverse"], required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dict", default="cipher_dict.json")
    
    args = parser.parse_args()
    input_path = Path(args.input).resolve()

    if not input_path.exists():
        print(f"[!] Input file not found: {args.input}")
        sys.exit(1)

    dict_path = Path(args.dict).resolve()
    cipher_dict = load_json(dict_path)
    
    with open(input_path, 'r', encoding='utf-8') as f:
        text = f.read()

    if args.mode == "forward":
        result = process_forward(text, cipher_dict, input_path)
        print(f"[*] FORWARD PASS: Obfuscated {input_path.name}. Ledger created.")
    else:
        result = process_reverse(text, cipher_dict, input_path)
        print(f"[*] REVERSE PASS: Restored {input_path.name}. Ledger cleared.")

    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(result)
        
if __name__ == "__main__":
    main()
