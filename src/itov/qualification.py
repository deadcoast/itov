"""Fail-closed preflight for the supported local, stock-node execution profile."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from itov.audio_media import audio_contract
from itov.batch import replay_plan
from itov.catalog import canonical_bytes, digest, read_document, relative_path, require, sha256
from itov.catalog_store import _atomic_write
from itov.comfyui import ComfyUIClient, parse_json
from itov.config import Config
from itov.media import video_contract, video_tools
from itov.runtime import launch_command, profile_main_argv
from itov.vram_identity import MARKER
from itov.workflow import validate_workflow

PROFILE = "stock-local-v1"
SUPPORTED = {
    "LoadImage",
    "SaveImage",
    "CheckpointLoaderSimple",
    "LoraLoader",
    "LoraLoaderModelOnly",
    "CLIPTextEncode",
    "EmptyLatentImage",
    "KSampler",
    "VAEDecode",
    "VAEEncode",
}
VIDEO_MODULES = {
    "UNETLoader": "nodes",
    "CLIPLoader": "nodes",
    "VAELoader": "nodes",
    "ModelSamplingSD3": "comfy_extras.nodes_model_advanced",
    "Wan22ImageToVideoLatent": "comfy_extras.nodes_wan",
    "CreateVideo": "comfy_extras.nodes_video",
    "SaveVideo": "comfy_extras.nodes_video",
}
MODEL_FOLDERS = {
    "CheckpointLoaderSimple": ("checkpoints",),
    "UNETLoader": ("unet", "diffusion_models"),
    "CLIPLoader": ("text_encoders", "clip"),
    "VAELoader": ("vae",),
}
AUDIO_MODULES = {
    name: "comfy_extras.nodes_audio"
    for name in (
        "EmptyLatentAudio",
        "ConditioningStableAudio",
        "VAEDecodeAudio",
        "SaveAudioAdvanced",
    )
}


def model_path(config: Config, kind: str, name: str) -> Path:
    require(isinstance(name, str) and name.endswith(".safetensors"), "Models must be safetensors")
    candidates = [
        safe_path(config.comfyui_root / "models" / folder, name) for folder in MODEL_FOLDERS[kind]
    ]
    present = [path for path in candidates if path.exists()]
    require(len(present) == 1, f"Expected one unambiguous stock model path for {kind}: {name}")
    require(present[0].is_file(), "Model path must be a regular file")
    return present[0]


def _pin(node: dict, asset: dict, label: str, *, required: bool = False):
    metadata = node.get("_meta", {})
    require(isinstance(metadata, dict), f"{label} metadata must be an object")
    if required or "itov_asset_sha256" in metadata:
        expected = digest(metadata.get("itov_asset_sha256"), label + ".itov_asset_sha256")
        require(asset["sha256"] == expected, f"Pinned {label} SHA-256 mismatch")


def json_text(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def node_schema_hash(registry: dict, used: set[str], *, instrumented: bool) -> str:
    schemas = {key: copy.deepcopy(registry[key]) for key in sorted(used)}
    if instrumented and "VAELoader" in schemas:
        # Stock VAELoader appends built-in names from a set. Every qualified graph
        # explicitly selects and pins vae_name, so choice order cannot change it.
        options = schemas["VAELoader"]["input"]["required"]["vae_name"][0]
        require(
            isinstance(options, list) and all(isinstance(item, str) for item in options),
            "Invalid stock VAE choice schema",
        )
        options.sort()
    return sha256(json_text(schemas).encode())


def safe_path(root: Path, name: str) -> Path:
    relative_path(name, "runtime file")
    path = root / name
    require(
        path.resolve() == path.absolute() and not path.is_symlink(),
        f"Runtime path redirects: {path}",
    )
    return path


def _file(path: Path) -> dict:
    with path.open("rb") as source:
        before = path.stat()
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        after = path.stat()
    require(
        (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
        f"File changed while hashing: {path}",
    )
    return {"path": str(path), "bytes": after.st_size, "sha256": digest}


def qualify(config: Config, plan: dict, *, timeout: float = 3) -> dict:
    """Rebuild the plan and bind stock loader names to actual local file bytes.

    This receipt establishes preflight observations, not model efficacy or a render.
    Runtime and assets must remain under operator control while execution is active.
    """
    replay_plan(config.root, plan)
    return qualify_graphs(config, plan, timeout=timeout)


def qualify_graphs(config: Config, plan: dict, *, timeout: float = 3, extra_sources=()) -> dict:
    """Bind validated plan graphs; callers must first validate their own plan contract."""
    expected_argv = launch_command(config)[2:]
    client = ComfyUIClient(config.url, timeout=timeout)
    stats, registry = client.system_stats(), client.object_info()
    instrumented = stats["system"].get("argv") != expected_argv and (
        stats["system"].get("argv") == profile_main_argv(config) + [MARKER]
    )
    require(
        stats["system"].get("argv") == expected_argv or instrumented,
        "Qualification requires the exact stock runtime launched by itov server start",
    )
    require(
        not (config.comfyui_root / "extra_model_paths.yaml").exists(),
        "Extra model search paths are not supported by this qualification profile",
    )
    used, files = set(), {}
    video = any(
        node["class_type"] in VIDEO_MODULES
        for job in plan["jobs"]
        for node in parse_json(job["workflow_json"]).values()
    )
    audio = any(
        node["class_type"] in AUDIO_MODULES
        for job in plan["jobs"]
        for node in parse_json(job["workflow_json"]).values()
    )
    require(
        not (
            audio
            and any(
                node["class_type"] in {"CreateVideo", "SaveVideo", "Wan22ImageToVideoLatent"}
                for job in plan["jobs"]
                for node in parse_json(job["workflow_json"]).values()
            )
        ),
        "Audio and video generation require separate qualified plans",
    )
    profile = "stock-stable-audio-v1" if audio else "stock-wan22-v1" if video else PROFILE

    def bind(root, name):
        path = safe_path(root, name)
        key = str(path)
        if key not in files:
            files[key] = _file(path)
        return files[key]

    for name in ("main.py", "nodes.py", "folder_paths.py", *extra_sources):
        bind(config.comfyui_root, name)
    observer = None
    if instrumented:
        observer = client._json("/itov/vram").get("identity")
        require(
            isinstance(observer, dict) and observer.get("version") == 1,
            "Missing VRAM observer identity",
        )
        for name, field in (
            ("vram_runtime.py", "bootstrap_sha256"),
            ("vram_identity.py", "identity_sha256"),
        ):
            require(
                observer.get(field) == _file(Path(__file__).with_name(name))["sha256"],
                "VRAM observer source differs from this ITOV installation",
            )
        for name in (
            "execution.py",
            "comfy/model_management.py",
            "comfy/model_patcher.py",
            "comfy/memory_management.py",
        ):
            bind(config.comfyui_root, name)
    for job in plan["jobs"]:
        graph = parse_json(job["workflow_json"])
        validation = validate_workflow(graph, registry).to_dict()
        require(
            validation["valid"],
            f"Live workflow validation failed at job {job['index']}: {validation['issues']}",
        )
        planned_loras = {}
        for item in job["loras"]:
            name, asset_hash = item["loader_name"], item["asset"]["sha256"]
            require(
                name not in planned_loras or planned_loras[name] == asset_hash,
                f"One loader name refers to different planned LoRA assets: {name}",
            )
            planned_loras[name] = asset_hash
        seed_nodes = {
            binding["node"]
            for binding in plan["request"]["bindings"][job["preset"]]["seed_inputs"]
            if binding["class_type"] == "KSampler" and binding["input"] == "seed"
        }
        for node_id, node in graph.items():
            kind, inputs = node["class_type"], node["inputs"]
            require(
                kind in SUPPORTED or kind in VIDEO_MODULES or kind in AUDIO_MODULES,
                f"Node is outside the {profile} profile: {kind}",
            )
            module = AUDIO_MODULES.get(kind, VIDEO_MODULES.get(kind, "nodes"))
            require(
                registry[kind].get("python_module") == module,
                f"Node is not the stock implementation: {kind}",
            )
            if module != "nodes":
                bind(config.comfyui_root, module.replace(".", "/") + ".py")
            used.add(kind)
            if kind == "LoadImage":
                require(
                    not inputs["image"].endswith(("[input]", "[output]", "[temp]")),
                    "Annotated LoadImage paths are outside this qualification profile",
                )
                asset = bind(config.runtime_root / "input", inputs["image"])
                _pin(node, asset, "input image", required=video)
            elif kind == "CLIPTextEncode":
                require(
                    isinstance(inputs["text"], str) and "embedding:" not in inputs["text"].lower(),
                    "External text embeddings are outside this qualification profile",
                )
            elif kind == "CheckpointLoaderSimple":
                asset = bind(config.comfyui_root / "models/checkpoints", inputs["ckpt_name"])
                _pin(node, asset, "checkpoint", required=audio)
            elif kind in MODEL_FOLDERS:
                field = {
                    "UNETLoader": "unet_name",
                    "CLIPLoader": "clip_name",
                    "VAELoader": "vae_name",
                }[kind]
                path = model_path(config, kind, inputs[field])
                asset = bind(path.parent, path.name)
                _pin(node, asset, kind, required=True)
                if kind == "CLIPLoader":
                    require(
                        inputs["type"] == ("stable_audio" if audio else "wan")
                        and inputs.get("device", "default") == "default",
                        "Profile requires its default text encoder type and device",
                    )
                if kind == "UNETLoader":
                    require(
                        inputs["weight_dtype"] == "default",
                        "Video profile requires the pinned model's default dtype",
                    )
            elif kind in {"LoraLoader", "LoraLoaderModelOnly"}:
                name = inputs["lora_name"]
                asset = bind(config.comfyui_root / "models/loras", name)
                require(
                    asset["sha256"] == planned_loras.get(name),
                    f"Loader name does not resolve to the planned LoRA bytes: {name}",
                )
            elif kind in {"SaveImage", "SaveVideo", "SaveAudioAdvanced"}:
                prefix = inputs["filename_prefix"]
                require(
                    isinstance(prefix, str) and "%" not in prefix,
                    f"{kind} requires a literal relative filename prefix",
                )
                safe_path(config.runtime_root / "output", prefix)
                if kind == "SaveAudioAdvanced":
                    require(
                        set(inputs) == {"audio", "filename_prefix", "format"}
                        and inputs["format"] == "flac",
                        "Audio profile requires explicit lossless FLAC output",
                    )
                    metadata = node.get("_meta", {})
                    require(isinstance(metadata, dict), "Audio metadata must be an object")
                    audio_contract(metadata.get("itov_audio"))
                    video_tools()
                if kind == "SaveVideo":
                    require(
                        set(inputs) == {"video", "filename_prefix", "format", "format.codec"}
                        and inputs["format"] == "mp4"
                        and inputs["format.codec"] == "h264",
                        "Video profile requires explicit MP4/H.264 output",
                    )
                    metadata = node.get("_meta", {})
                    require(isinstance(metadata, dict), "Video metadata must be an object")
                    video_contract(metadata.get("itov_video"))
                    video_tools()
            elif kind == "EmptyLatentAudio":
                require(
                    type(inputs["seconds"]) is int
                    and 1 <= inputs["seconds"] <= 10
                    and inputs["batch_size"] == 1,
                    "Audio profile requires 1..10 seconds and batch size one",
                )
            elif kind == "ConditioningStableAudio":
                require(
                    inputs["seconds_start"] == 0 and 1 <= inputs["seconds_total"] <= 10,
                    "Audio conditioning must start at zero and last 1..10 seconds",
                )
            elif kind == "CreateVideo":
                require(
                    set(inputs) == {"images", "fps"},
                    "Video profile supports silent CreateVideo with default encoding only",
                )
            elif kind == "Wan22ImageToVideoLatent":
                require(
                    inputs["batch_size"] == 1 and isinstance(inputs.get("start_image"), list),
                    "Video profile requires one latent batch and an explicit start image",
                )
            elif kind == "KSampler":
                require(
                    node_id in seed_nodes
                    and job["seed"] is not None
                    and inputs["seed"] == job["seed"],
                    "Every KSampler seed must be covered by the plan's seed reservation",
                )
    system = stats["system"]
    body = {
        "version": 1,
        "profile": profile,
        "scope": "runtime_schema_and_asset_binding",
        "plan_id": plan["plan_id"],
        "server": config.url,
        "runtime": {
            key: system.get(key)
            for key in ("argv", "comfyui_version", "python_version", "pytorch_version")
        },
        "devices": [
            {key: item.get(key) for key in ("name", "type", "index")} for item in stats["devices"]
        ],
        "node_schema_sha256": node_schema_hash(registry, used, instrumented=instrumented),
        "files": [files[key] for key in sorted(files)],
        "jobs": len(plan["jobs"]),
    }
    if observer is not None:
        body["vram_observer"] = observer
    return {**body, "qualification_id": sha256(canonical_bytes(body))}


def save_qualification(config: Config, receipt: dict) -> Path:
    path = safe_path(config.root, f"state/qualifications/{receipt['qualification_id']}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical_bytes(receipt) + b"\n"
    try:
        _atomic_write(path, raw, exclusive=True)
    except FileExistsError:
        require(path.read_bytes() == raw, "Existing qualification differs; preserve and inspect")
    return path


def load_qualification(path: Path) -> dict:
    raw = read_document(path)
    receipt = parse_json(raw)
    require(isinstance(receipt, dict), "Qualification must be an object")
    body = {key: value for key, value in receipt.items() if key != "qualification_id"}
    require(
        receipt.get("qualification_id") == sha256(canonical_bytes(body)),
        "Qualification hash mismatch",
    )
    require(raw == canonical_bytes(receipt) + b"\n", "Noncanonical qualification")
    return receipt
