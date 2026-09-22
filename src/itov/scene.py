"""Explicit lexical scene constraints on replayed, stock text-conditioning plans."""

from __future__ import annotations

from pathlib import Path

from itov import linting
from itov.catalog import array, integer, object_fields, require, sha256, text
from itov.comfyui import parse_json
from itov.trigger import index as trigger_index

TERM_FIELDS = {"required_positive", "forbidden_positive", "required_negative", "forbidden_negative"}


def load_constraints(path: Path):
    value, source = linting.document(path)
    object_fields(value, {"version", "id", "origin", "presets"}, "scene constraints")
    require(type(value["version"]) is int and value["version"] == 1, "Invalid scene version")
    linting.ids([value["id"]], "scene id")
    linting.origin(value["origin"])
    presets = array(value["presets"], "scene presets")
    require(1 <= len(presets) <= 64, "Scene constraints require 1 to 64 presets")
    seen = set()
    for rule in presets:
        object_fields(
            rule,
            {
                "preset",
                "sampler",
                "required_loras",
                "forbidden_loras",
                "max_loras",
                "max_words",
                "triggers",
                *TERM_FIELDS,
            },
            "scene rule",
        )
        linting.ids([rule["preset"]], "scene preset")
        require(rule["preset"] not in seen, "Duplicate scene preset")
        seen.add(rule["preset"])
        text(rule["sampler"], "sampler")
        require(len(rule["sampler"]) <= 128, "Sampler ID is too long")
        for field in TERM_FIELDS:
            linting.terms(rule[field], field, maximum=64)
        for role in ("positive", "negative"):
            require(
                not any(
                    linting.contains(wanted, banned)
                    for wanted in rule["required_" + role]
                    for banned in rule["forbidden_" + role]
                ),
                "Required phrase contains a forbidden phrase",
            )
        for field in ("required_loras", "forbidden_loras"):
            linting.ids(rule[field], field)
        require(
            not set(rule["required_loras"]) & set(rule["forbidden_loras"]),
            "LoRA cannot be both required and forbidden",
        )
        integer(rule["max_loras"], "max_loras")
        require(len(rule["required_loras"]) <= rule["max_loras"] <= 8, "Invalid LoRA count bound")
        object_fields(rule["max_words"], {"positive", "negative"}, "max_words")
        for maximum in rule["max_words"].values():
            integer(maximum, "max_words")
            require(maximum <= 4096, "Word bound exceeds 4096")
        require(rule["triggers"] in ("all_declared", "none"), "Unknown trigger presence policy")
    return value, {**source, "origin": value["origin"], "scene_id": value["id"]}


def prompt(graph, link):
    """Resolve only known stock conditioning outputs; unknown graphs fail closed."""
    visited = set()
    while True:
        require(
            isinstance(link, list)
            and len(link) == 2
            and isinstance(link[0], str)
            and type(link[1]) is int,
            "Conditioning must be an explicit node link",
        )
        node_id, output = link
        require(node_id in graph and node_id not in visited, "Invalid conditioning path")
        visited.add(node_id)
        node = graph[node_id]
        if node["class_type"] == "CLIPTextEncode":
            require(output == 0, "Invalid CLIPTextEncode output")
            value = node["inputs"].get("text")
            require(
                isinstance(value, str) and len(value) <= 32768,
                "Prompt must be bounded literal CLIPTextEncode text",
            )
            value.encode("utf-8")
            require(
                not any(ord(c) < 32 and c not in "\r\n\t" for c in value),
                "Prompt contains control characters",
            )
            return value, {
                "node": node_id,
                "input": "text",
                "sha256": sha256(value.encode()),
                "words": len(value.split()),
                "characters": len(value),
            }
        require(
            node["class_type"] == "ConditioningStableAudio" and output in (0, 1),
            "Unsupported conditioning path; only stock CLIPTextEncode/StableAudio is checked",
        )
        link = node["inputs"].get("positive" if output == 0 else "negative")


def lint(config, constraints_path: Path, plan_path: Path, *, save=False):
    value, source = load_constraints(constraints_path)
    store, snapshot, plan = linting.context(config, plan_path)
    catalog = snapshot.to_dict()["catalog"]
    loras = {lora["id"]: lora for lora in catalog["loras"]}
    trigger_index(catalog)  # Same declaration and resource bounds as trigger collision lint.
    rules = {r["preset"]: r for r in value["presets"]}
    require(
        set(rules) == {j["preset"] for j in plan["jobs"]},
        "Scene rules must cover exactly the plan's selected presets",
    )
    for rule in rules.values():
        require(
            set(rule["required_loras"] + rule["forbidden_loras"]) <= loras.keys(),
            "Unknown scene LoRA reference",
        )
    findings, checked = [], []
    for job in plan["jobs"]:
        rule = rules[job["preset"]]
        graph = parse_json(job["workflow_json"])
        samplers = [key for key, n in graph.items() if n["class_type"] == "KSampler"]
        require(samplers == [rule["sampler"]], "Scene lint requires exactly the declared KSampler")
        sampler = graph[rule["sampler"]]
        prompts, sources = {}, {}
        for role in ("positive", "negative"):
            prompts[role], sources[role] = prompt(graph, sampler["inputs"].get(role))
        require(
            sources["positive"]["node"] != sources["negative"]["node"],
            "Positive and negative conditioning share the same text node",
        )

        def add(code, *, job=job, **details):
            findings.append(
                {
                    "code": code,
                    "severity": "error",
                    "job_index": job["index"],
                    "preset": job["preset"],
                    **details,
                }
            )
            require(len(findings) <= 10000, "Too many scene findings; narrow the plan")

        if not linting.normalize(prompts["positive"]):
            add("EMPTY_POSITIVE")
        for role in ("positive", "negative"):
            for term in rule["required_" + role]:
                if not linting.contains(prompts[role], term):
                    add("REQUIRED_PHRASE_MISSING", role=role, term=term)
            for term in rule["forbidden_" + role]:
                if linting.contains(prompts[role], term):
                    add("FORBIDDEN_PHRASE_PRESENT", role=role, term=term)
            if sources[role]["words"] > rule["max_words"][role]:
                add(
                    "WORD_LIMIT",
                    role=role,
                    actual=sources[role]["words"],
                    maximum=rule["max_words"][role],
                )
        chosen = {lora["id"] for lora in job["loras"]}
        for key in sorted(set(rule["required_loras"]) - chosen):
            add("REQUIRED_LORA_MISSING", lora=key)
        for key in sorted(set(rule["forbidden_loras"]) & chosen):
            add("FORBIDDEN_LORA_PRESENT", lora=key)
        if len(chosen) > rule["max_loras"]:
            add("LORA_COUNT", actual=len(chosen), maximum=rule["max_loras"])
        if rule["triggers"] == "all_declared":
            for key in sorted(chosen):
                for term in loras[key]["trigger_words"]:
                    if not linting.contains(prompts["positive"], term):
                        add("TRIGGER_MISSING_POSITIVE", lora=key, term=term)
                    if linting.contains(prompts["negative"], term):
                        add("TRIGGER_IN_NEGATIVE", lora=key, term=term)
        checked.append(
            {
                "job_index": job["index"],
                "preset": job["preset"],
                "workflow_sha256": job["workflow_sha256"],
                "sampler": rule["sampler"],
                "prompts": sources,
                "loras": sorted(chosen),
                "trigger_policy": rule["triggers"],
            }
        )
    return linting.finish(
        store,
        snapshot,
        kind="scene",
        inputs={"constraints": source, "plan_id": plan["plan_id"]},
        findings=findings,
        details={
            "jobs": checked,
            "asset_scope": "replayed_plan_asset_bytes",
            "collision_lint": "Run trigger lint separately; presence is not collision analysis",
        },
        save=save,
    )
