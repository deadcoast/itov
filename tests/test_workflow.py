import pytest

from itov.comfyui import parse_json
from itov.workflow import validate_workflow


def codes(report):
    return {issue.code for issue in report.issues}


def test_validation_scopes_and_no_input_mutation(graph, registry):
    import copy

    before = copy.deepcopy(graph)
    structure = validate_workflow(graph)
    live_schema = validate_workflow(graph, registry)
    assert structure.valid and structure.scope == "structure"
    assert live_schema.valid and live_schema.scope == "node_schema"
    assert graph == before


@pytest.mark.parametrize(
    "graph",
    [
        {},
        [],
        {"nodes": []},
        {"workflow": {"nodes": []}},
        {"1": {"class_type": "Fake", "inputs": []}},
    ],
)
def test_non_api_workflows_are_rejected(graph):
    assert not validate_workflow(graph).valid


@pytest.mark.parametrize(
    "link", [["missing", 0], ["1", -1], ["1", True], [1, 0], ["1"], ["1", 0, 1]]
)
def test_invalid_links(graph, link):
    graph["2"]["inputs"]["images"] = link
    assert not validate_workflow(graph).valid


def test_cycles_are_rejected(graph):
    graph["1"]["inputs"]["image"] = ["2", 0]
    assert "cycle" in codes(validate_workflow(graph))


def test_deep_graph_avoids_recursion_limit():
    graph = {"0": {"class_type": "Source", "inputs": {}}}
    for number in range(1, 2000):
        graph[str(number)] = {"class_type": "Link", "inputs": {"source": [str(number - 1), 0]}}
    assert validate_workflow(graph).valid


def test_unknown_node_and_missing_required_input(graph, registry):
    graph["1"]["class_type"] = "ImaginaryModelLoader"
    del graph["2"]["inputs"]["images"]
    assert {"unknown_class", "missing_input"} <= codes(validate_workflow(graph, registry))


def test_model_dropdown_and_output_types(graph, registry):
    graph["1"]["inputs"]["image"] = "not-installed.png"
    graph["2"]["inputs"]["images"] = ["1", 1]
    assert {"invalid_choice", "incompatible_link"} <= codes(validate_workflow(graph, registry))


def test_output_index_out_of_range(graph, registry):
    graph["2"]["inputs"]["images"] = ["1", 4]
    assert "invalid_output" in codes(validate_workflow(graph, registry))


def test_output_node_is_required_with_schema(graph, registry):
    del graph["2"]
    assert "missing_output" in codes(validate_workflow(graph, registry))


@pytest.mark.parametrize(
    "value,code",
    [(True, "invalid_type"), (0, "out_of_range"), (11, "out_of_range"), ("2", "invalid_type")],
)
def test_numeric_input_rules(graph, registry, value, code):
    registry["LoadImage"]["input"]["required"]["count"] = ["INT", {"min": 1, "max": 10}]
    graph["1"]["inputs"]["count"] = value
    assert code in codes(validate_workflow(graph, registry))


@pytest.mark.parametrize(
    "registry",
    [
        [],
        {},
        {"LoadImage": {"input": []}},
        {"LoadImage": {"input": {"required": {"image": []}}, "output": []}},
    ],
)
def test_malformed_registry_fails_cleanly(graph, registry):
    assert "invalid_registry" in codes(validate_workflow(graph, registry))


@pytest.mark.parametrize("value", ['{"1": {}, "1": {}}', '{"x": NaN}', '{"x": Infinity}'])
def test_ambiguous_json_is_rejected(value):
    with pytest.raises(ValueError):
        parse_json(value)


def test_nonfinite_values_and_literal_objects_are_rejected(graph):
    graph["1"]["inputs"]["image"] = {"file": "example.png"}
    graph["2"]["inputs"]["filename_prefix"] = float("inf")
    assert len(validate_workflow(graph).issues) == 2


def test_exponent_overflow_is_not_accepted_as_finite_json():
    with pytest.raises(ValueError, match="Non-finite"):
        parse_json('{"x": 1e999}')
