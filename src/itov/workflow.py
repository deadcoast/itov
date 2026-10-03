"""Validate exported API graphs without submitting jobs or loading models."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path

from itov.comfyui import parse_json


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    node_id: str | None = None
    input_name: str | None = None


@dataclass
class Validation:
    scope: str
    node_count: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            **asdict(self),
            "limits": (
                "Static checks only; custom node validation and rendering were not executed."
                if self.scope == "node_schema"
                else "Structure only; node availability, models, and execution are unverified."
            ),
        }


def load_json(path: Path) -> object:
    return parse_json(path.read_text(encoding="utf-8-sig"))


def _compatible(actual: str, expected: str) -> bool:
    source = {part.strip() for part in actual.split(",")}
    target = {part.strip() for part in expected.split(",")}
    return "*" in source or "*" in target or bool(source & target)


def _expand_inputs(required: dict, optional: dict, values: dict) -> tuple[dict, dict]:
    """Expand selected V3 dynamic combos into their dotted API input names."""
    groups: dict[str, dict] = {"required": {}, "optional": {}}
    pending = [("required", required, "", 0), ("optional", optional, "", 0)]
    while pending:
        group, declarations, prefix, depth = pending.pop()
        if not isinstance(declarations, dict) or depth > 8:
            raise ValueError("Invalid or excessively nested input schema")
        for name, spec in declarations.items():
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(spec, list)
                or not spec
                or not isinstance(spec[0], (str, list))
                or (len(spec) > 1 and not isinstance(spec[1], dict))
            ):
                raise ValueError("Invalid input declaration")
            key = prefix + name
            if key in groups["required"] or key in groups["optional"]:
                raise ValueError("Overlapping dynamic input names")
            if spec[0] == "COMBO":
                choices = spec[1].get("options") if len(spec) > 1 else None
                if not isinstance(choices, list):
                    raise ValueError("Invalid COMBO choices")
                groups[group][key] = [choices]
            elif spec[0] == "COMFY_DYNAMICCOMBO_V3":
                choices = spec[1].get("options") if len(spec) > 1 else None
                if (
                    not isinstance(choices, list)
                    or not choices
                    or any(
                        not isinstance(choice, dict)
                        or not isinstance(choice.get("key"), str)
                        or not isinstance(choice.get("inputs"), dict)
                        for choice in choices
                    )
                ):
                    raise ValueError("Invalid dynamic combo choices")
                keys = [choice["key"] for choice in choices]
                if len(set(keys)) != len(keys):
                    raise ValueError("Duplicate dynamic combo choices")
                groups[group][key] = [keys]
                selected = next(
                    (choice for choice in choices if choice["key"] == values.get(key)), None
                )
                if selected is not None:
                    for child_group in ("required", "optional"):
                        pending.append(
                            (
                                child_group,
                                selected["inputs"].get(child_group, {}),
                                key + ".",
                                depth + 1,
                            )
                        )
            else:
                groups[group][key] = spec
            if len(groups["required"]) + len(groups["optional"]) > 1024:
                raise ValueError("Excessive input declarations")
    return groups["required"], groups["optional"]


def validate_workflow(graph: object, object_info: object | None = None) -> Validation:
    report = Validation(scope="node_schema" if object_info is not None else "structure")

    def issue(code: str, message: str, node: str | None = None, name: str | None = None):
        report.issues.append(Issue(code, message, node, name))

    if not isinstance(graph, dict) or not graph:
        issue("invalid_graph", "Expected a nonempty node-ID mapping from ComfyUI Export (API)")
        return report
    report.node_count = len(graph)
    nodes = {}
    for node_id, node in graph.items():
        if (
            not isinstance(node_id, str)
            or not node_id
            or not isinstance(node, dict)
            or not isinstance(node.get("class_type"), str)
            or not node["class_type"].strip()
            or not isinstance(node.get("inputs"), dict)
        ):
            issue(
                "invalid_node",
                "Expected class_type and inputs object; use Export (API), not editor workflow JSON",
                str(node_id),
            )
            continue
        nodes[node_id] = node

    dependencies: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    links: dict[tuple[str, str], tuple[str, int]] = {}
    for node_id, node in nodes.items():
        for name, value in node["inputs"].items():
            if not isinstance(name, str) or not name:
                issue("invalid_input", "Input names must be nonempty strings", node_id)
            elif isinstance(value, list):
                if (
                    len(value) != 2
                    or not isinstance(value[0], str)
                    or type(value[1]) is not int
                    or value[1] < 0
                ):
                    issue(
                        "invalid_link",
                        "Expected [source_node_id, nonnegative_output_index]",
                        node_id,
                        name,
                    )
                elif value[0] not in nodes:
                    issue(
                        "missing_source",
                        f"Source node {value[0]!r} is absent or invalid",
                        node_id,
                        name,
                    )
                else:
                    dependencies[node_id].add(value[0])
                    links[node_id, name] = (value[0], value[1])
            elif isinstance(value, dict) or (isinstance(value, float) and not math.isfinite(value)):
                issue("invalid_value", "Expected a finite scalar or a node link", node_id, name)

    # Iterative graph walk also handles deep, valid graphs without recursion limits.
    dependents: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for node_id, sources in dependencies.items():
        for source in sources:
            dependents[source].add(node_id)
    pending = {node_id: len(sources) for node_id, sources in dependencies.items()}
    ready = deque(node_id for node_id, count in pending.items() if count == 0)
    visited = 0
    while ready:
        source = ready.popleft()
        visited += 1
        for destination in dependents[source]:
            pending[destination] -= 1
            if pending[destination] == 0:
                ready.append(destination)
    if visited != len(nodes):
        issue("cycle", "Workflow contains a dependency cycle")

    if object_info is None:
        return report
    if not isinstance(object_info, dict) or not object_info:
        issue("invalid_registry", "Object info must be a nonempty node registry")
        return report

    schemas = {}
    for node_id, node in nodes.items():
        class_type = node["class_type"]
        if class_type not in object_info:
            issue("unknown_class", f"Node class {class_type!r} is not installed", node_id)
            continue
        metadata = object_info[class_type]
        if not isinstance(metadata, dict) or not isinstance(metadata.get("input"), dict):
            issue("invalid_registry", f"Invalid input metadata for {class_type}", node_id)
            continue
        inputs = metadata["input"]
        required = inputs.get("required", {})
        optional = inputs.get("optional", {})
        outputs = metadata.get("output")
        if (
            not isinstance(required, dict)
            or not isinstance(optional, dict)
            or not isinstance(outputs, list)
            or any(not isinstance(value, str) for value in outputs)
        ):
            issue("invalid_registry", f"Invalid input/output schema for {class_type}", node_id)
            continue
        try:
            required, optional = _expand_inputs(required, optional, node["inputs"])
        except ValueError:
            issue("invalid_registry", f"Invalid input declaration for {class_type}", node_id)
            continue
        declarations = {**required, **optional}
        schemas[node_id] = metadata, declarations
        for name in sorted(required.keys() - node["inputs"].keys()):
            issue("missing_input", f"Required input {name!r} is missing", node_id, name)
        for name, value in node["inputs"].items():
            # Dynamic custom-node inputs may not appear in static object_info.
            if name not in declarations or isinstance(value, list):
                continue
            spec = declarations[name]
            kind = spec[0]
            options = spec[1] if len(spec) > 1 else {}
            if isinstance(kind, list):
                if not any(type(value) is type(choice) and value == choice for choice in kind):
                    issue(
                        "invalid_choice",
                        f"Value is not an available choice for {name}",
                        node_id,
                        name,
                    )
                continue
            valid_type = {
                "INT": type(value) is int,
                "FLOAT": type(value) in (int, float),
                "STRING": isinstance(value, str),
                "BOOLEAN": type(value) is bool,
            }.get(kind)
            if valid_type is False:
                issue("invalid_type", f"Expected {kind}", node_id, name)
            elif valid_type is True and kind in {"INT", "FLOAT"}:
                for bound, comparison in (("min", lambda a, b: a < b), ("max", lambda a, b: a > b)):
                    limit = options.get(bound)
                    if type(limit) in (int, float) and comparison(value, limit):
                        issue("out_of_range", f"Value violates {bound}={limit}", node_id, name)
            elif valid_type is None and kind != "*":
                issue("expected_link", f"Input type {kind} requires a node link", node_id, name)

    for (node_id, name), (source, output_index) in links.items():
        if source not in schemas:
            continue
        outputs = schemas[source][0]["output"]
        if output_index >= len(outputs):
            issue("invalid_output", f"Node {source} has no output {output_index}", node_id, name)
            continue
        if node_id in schemas and name in schemas[node_id][1]:
            expected = schemas[node_id][1][name][0]
            if isinstance(expected, str) and not _compatible(outputs[output_index], expected):
                issue(
                    "incompatible_link",
                    f"Output {outputs[output_index]} does not match input {expected}",
                    node_id,
                    name,
                )
    if schemas and not any(metadata.get("output_node") is True for metadata, _ in schemas.values()):
        issue("missing_output", "Graph has no installed output node")
    return report
