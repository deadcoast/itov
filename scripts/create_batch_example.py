"""Create a neutral planning request pinned to the current reviewed catalog."""

import argparse
from pathlib import Path

from itov.batch_request import neutral_request, validate_request
from itov.catalog import canonical_bytes, require
from itov.catalog_store import CatalogStore
from itov.config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
    args = parser.parse_args()
    config = load_config(args.config)
    snapshot = CatalogStore(config.root).snapshot(require_clean=True)
    catalog = snapshot.to_dict()["catalog"]
    request = validate_request(neutral_request(snapshot.head, "neutral-copy"), catalog)
    path = config.root / "templates/neutral.batch.json"
    require(path.resolve() == path.absolute() and not path.is_symlink(), "Request path redirects")
    with path.open("xb") as output:
        output.write(canonical_bytes(request) + b"\n")
    print(f"Created {path}")


if __name__ == "__main__":
    main()
