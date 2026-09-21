"""Download reviewed media baseline assets; publish only exact upstream hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from itov.catalog import canonical_bytes, read_document, require
from itov.catalog_store import _atomic_write
from itov.comfyui import parse_json
from itov.config import load_config
from itov.locking import file_lock
from itov.qualification import _file, safe_path


def fetch(root: Path, asset: dict, *, opener=None) -> dict:
    target = safe_path(root, asset["destination"])
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{asset['repository']}/resolve/{asset['revision']}/{asset['source_file']}"
    with file_lock(target.with_suffix(".download.lock")):
        if target.exists():
            metadata = _file(target)
            require(
                metadata["sha256"] == asset["sha256"] and metadata["bytes"] == asset["bytes"],
                f"Existing model differs; refusing overwrite: {target}",
            )
            return {**asset, "url": url, "path": str(target), "status": "verified_existing"}
        require(
            shutil.disk_usage(target.parent).free >= asset["bytes"] + 1024**3,
            "Insufficient disk space for model plus 1 GiB reserve",
        )
        opener = opener or build_opener(ProxyHandler({}))
        partial = None
        try:
            with (
                opener.open(url, timeout=30) as response,
                tempfile.NamedTemporaryFile(
                    dir=target.parent, prefix=".itov-model-", suffix=".partial", delete=False
                ) as output,
            ):
                partial = Path(output.name)
                observed, count, reported = hashlib.sha256(), 0, time.monotonic()
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    require(count <= asset["bytes"], "Model download exceeds pinned length")
                    output.write(chunk)
                    observed.update(chunk)
                    if time.monotonic() - reported > 10:
                        print(f"{asset['id']}: {count / asset['bytes']:.0%}", flush=True)
                        reported = time.monotonic()
                output.flush()
                os.fsync(output.fileno())
            require(
                count == asset["bytes"] and observed.hexdigest() == asset["sha256"],
                f"Model download length or SHA-256 differs; partial retained at {partial}",
            )
            os.link(partial, target)
            partial.unlink()
            return {**asset, "url": url, "path": str(target), "status": "downloaded_and_verified"}
        except BaseException:
            if partial is not None:
                print(f"Unpublished partial retained for inspection: {partial}", flush=True)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("workspace/itov.toml"))
    parser.add_argument("--baseline", choices=("image", "video", "audio"), default="image")
    args = parser.parse_args()
    config = load_config(args.config)
    filename = {
        "image": "inference-assets.json",
        "video": "video-assets.json",
        "audio": "audio-assets.json",
    }[args.baseline]
    manifest = Path(__file__).resolve().parents[1] / "examples" / filename
    assets = parse_json(read_document(manifest))["assets"]
    missing_bytes = sum(
        asset["bytes"]
        for asset in assets
        if not safe_path(config.comfyui_root, asset["destination"]).exists()
    )
    require(
        shutil.disk_usage(config.comfyui_root).free >= missing_bytes + 2 * 1024**3,
        "Insufficient disk space for the complete baseline plus 2 GiB reserve",
    )
    directory = safe_path(config.root, "state/model-downloads")
    directory.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        result = fetch(config.comfyui_root, asset)
        receipt = {**result, "observed_at": datetime.now(UTC).isoformat()}
        path = directory / f"{asset['id']}-{asset['sha256']}.json"
        _atomic_write(path, canonical_bytes(receipt) + b"\n")
        print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
