"""Compatibility entry point for declared imports; prefer `itov dataset import`.

Pass a manifest and dataset import flags. Selection, captions and hashes now live
in the declaration. The former fixed-ID invocation is no longer supported.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from itov.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["dataset", "import", *sys.argv[1:]]))
