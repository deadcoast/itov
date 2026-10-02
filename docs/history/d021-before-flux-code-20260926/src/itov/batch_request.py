"""Explicit version-one planning requests and graph input bindings."""

from __future__ import annotations

from itov.catalog import (
    array,
    canonical_bytes,
    digest,
    identifier,
    integer,
    object_fields,
    relative_path,
    require,
    text,
)

MAX_JOBS = 1000
MAX_PRESETS = 64
MAX_LORAS = 256
MAX_SLOTS = 8
LOADERS = {"LoraLoader", "LoraLoaderModelOnly"}


def _ids(value, location, maximum):
    values = array(value, location)
    require(len(values) <= maximum, f"{location}: limit is {maximum}")
    for item in values:
        identifier(item, location)
    require(len(values) == len(set(values)), f"{location}: duplicate IDs")
    return values


def neutral_request(head: str, preset: str, *, count: int = 4, seed: int = 0) -> dict:
    return {
        "version": 1,
        "catalog_head": head,
        "count": count,
        "seed": seed,
        "presets": [preset],
        "no_repeat_within": 0,
        "category_cooldown": 0,
        "lora_policy": {
            "ids": [],
            "slots": [],
            "max_strength_milli": 0,
            "strength_mode": "recommended",
            "soft_conflicts": "exclude",
            "no_repeat_within": 0,
            "preferred_multiplier_milli": 1000,
            "loader_names": {},
        },
        "bindings": {preset: {"seed_inputs": [], "lora_slots": []}},
    }


def validate_request(value, catalog: dict) -> dict:
    object_fields(
        value,
        {
            "version",
            "catalog_head",
            "count",
            "seed",
            "presets",
            "no_repeat_within",
            "category_cooldown",
            "lora_policy",
            "bindings",
        },
        "batch request",
    )
    require(type(value["version"]) is int and value["version"] == 1, "Batch version must be 1")
    digest(value["catalog_head"], "catalog_head")
    integer(value["count"], "count", minimum=1)
    require(value["count"] <= MAX_JOBS, f"Batch count exceeds {MAX_JOBS}")
    integer(value["seed"], "seed")
    for name in ("no_repeat_within", "category_cooldown"):
        integer(value[name], name)
        require(value[name] <= MAX_JOBS, f"{name}: exceeds {MAX_JOBS}")
    presets = _ids(value["presets"], "presets", MAX_PRESETS)
    require(
        bool(presets) and set(presets) <= {p["id"] for p in catalog["presets"]},
        "Presets must name existing catalog entries",
    )
    policy = value["lora_policy"]
    object_fields(
        policy,
        {
            "ids",
            "slots",
            "max_strength_milli",
            "strength_mode",
            "soft_conflicts",
            "no_repeat_within",
            "preferred_multiplier_milli",
            "loader_names",
        },
        "lora_policy",
    )
    ids = _ids(policy["ids"], "lora_policy.ids", MAX_LORAS)
    slots = _ids(policy["slots"], "lora_policy.slots", MAX_SLOTS)
    require(set(ids) <= {item["id"] for item in catalog["loras"]}, "Unknown requested LoRA")
    require(bool(ids) == bool(slots), "LoRA IDs and required slots must both be empty or nonempty")
    integer(policy["max_strength_milli"], "max_strength_milli")
    integer(policy["preferred_multiplier_milli"], "preferred_multiplier_milli", minimum=1)
    integer(policy["no_repeat_within"], "lora_policy.no_repeat_within")
    require(policy["no_repeat_within"] <= MAX_JOBS, "LoRA cooldown exceeds limit")
    require(policy["strength_mode"] in ("recommended", "uniform"), "Invalid strength mode")
    require(policy["soft_conflicts"] in ("exclude", "allow"), "Invalid soft conflict policy")
    object_fields(policy["loader_names"], set(ids), "loader_names")
    names = [relative_path(name, "loader_names") for name in policy["loader_names"].values()]
    require(len({name.casefold() for name in names}) == len(names), "Duplicate loader names")
    object_fields(value["bindings"], set(presets), "bindings")
    for preset_id, binding in value["bindings"].items():
        object_fields(binding, {"seed_inputs", "lora_slots"}, f"binding {preset_id}")
        seeds = array(binding["seed_inputs"], "seed_inputs")
        require(len(seeds) <= 32, "At most 32 seed inputs per preset")
        addresses = set()
        for seed in seeds:
            object_fields(seed, {"node", "class_type", "input"}, "seed binding")
            text(seed["node"], "seed node")
            text(seed["class_type"], "seed class_type")
            require(
                seed["input"] in ("seed", "noise_seed"), "Only seed/noise_seed inputs are supported"
            )
            address = (seed["node"], seed["input"])
            require(address not in addresses, "Duplicate seed binding")
            addresses.add(address)
        used_slots, used_nodes = set(), set()
        for slot in array(binding["lora_slots"], "lora_slots"):
            object_fields(slot, {"slot", "node"}, "LoRA binding")
            identifier(slot["slot"], "LoRA binding.slot")
            text(slot["node"], "LoRA binding.node")
            require(
                slot["slot"] not in used_slots and slot["node"] not in used_nodes,
                "Duplicate slot or loader node binding",
            )
            used_slots.add(slot["slot"])
            used_nodes.add(slot["node"])
        require(used_slots == set(slots), "Each required slot needs exactly one loader binding")
        require(
            not used_nodes.intersection(node for node, _ in addresses),
            "Seed and LoRA bindings cannot share a node",
        )
    canonical_bytes(value)
    return value


def validate_bindings(preset: dict, binding: dict, graph: dict):
    seeds = binding["seed_inputs"]
    require(
        bool(seeds) == (preset["seed"] is not None),
        f"{preset['id']}: seed metadata and bindings must agree",
    )
    for seed in seeds:
        node = graph.get(seed["node"])
        require(
            isinstance(node, dict) and node["class_type"] == seed["class_type"],
            f"{preset['id']}: missing or changed seed node",
        )
        integer(node["inputs"].get(seed["input"]), "Bound seed input must be an integer literal")
    loader_nodes = set()
    for slot in binding["lora_slots"]:
        node = graph.get(slot["node"])
        require(
            isinstance(node, dict) and node["class_type"] in LOADERS,
            f"{preset['id']}: only LoraLoader/LoraLoaderModelOnly bindings are supported",
        )
        inputs = node["inputs"]
        links = ["model", "clip"] if node["class_type"] == "LoraLoader" else ["model"]
        for name in links:
            require(isinstance(inputs.get(name), list), f"Bound loader {name} must be a node link")
        text(inputs.get("lora_name"), "Bound lora_name must be a string literal")
        strengths = ["strength_model"]
        if node["class_type"] == "LoraLoader":
            strengths.append("strength_clip")
        for name in strengths:
            value = inputs.get(name)
            require(
                type(value) in {int, float} and -100 <= value <= 100,
                f"Bound {name} must be a numeric literal within [-100, 100]",
            )
        loader_nodes.add(slot["node"])
    require(
        loader_nodes == {key for key, node in graph.items() if node["class_type"] in LOADERS},
        f"{preset['id']}: every built-in LoRA loader must have a slot binding",
    )
