"""The one rule for a name an author gives to an output port.

A switch rule, a classify category, an `error.handle` branch and an approval
choice may not reuse a port their step already has. The config refuses the
static ports on the entry's own field, naming the clash; the graph refuses
`error` on a step that routes its errors, because only the graph knows that.
"""

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.workflows.contracts.policy import NodePolicy
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import _error_port_clash_problems, _resolve_definitions
from app.workflows.nodes.ai_classify._handler import AiClassifyConfig
from app.workflows.nodes.error_handle._handler import ErrorHandleConfig
from app.workflows.nodes.human_approval._handler import HumanApprovalConfig
from app.workflows.nodes.logic_switch._handler import LogicSwitchConfig

_MODEL = "00000000-0000-0000-0000-000000000001"

# (config model, the config, the list's field, the entry's name key, a static port)
_KINDS: list[tuple[type[Any], dict[str, Any], str, str]] = [
    (LogicSwitchConfig, {"rules": []}, "rules", "name"),
    (AiClassifyConfig, {"model_profile_id": _MODEL, "categories": []}, "categories", "name"),
    (ErrorHandleConfig, {"branches": []}, "branches", "name"),
    (HumanApprovalConfig, {"title": "Send?", "choices": []}, "choices", "id"),
]
_ENTRY: dict[str, dict[str, Any]] = {
    "rules": {"condition": "value"},
    "categories": {"description": "d"},
    "branches": {},
    "choices": {"label": "L"},
}
_STATIC: dict[str, tuple[str, ...]] = {
    "rules": ("in", "otherwise"),
    "categories": ("in", "other"),
    "branches": ("in", "default"),
    "choices": ("in", "approved", "rejected"),
}


def _config(model: type[Any], base: dict[str, Any], field: str, key: str, name: str) -> Any:
    return model.model_validate({**base, field: [{key: name, **_ENTRY[field]}]})


@pytest.mark.parametrize(("model", "base", "field", "key"), _KINDS)
def test_a_name_that_is_a_static_port_is_refused_on_its_own_entry(model, base, field, key):
    for name in _STATIC[field]:
        with pytest.raises(ValidationError) as excinfo:
            _config(model, base, field, key, name)
        # A list with a minimum length also says it is now too short; the clash is on the entry.
        (error,) = [e for e in excinfo.value.errors() if e["loc"] == (field, 0, key)]
        assert f"`{name}` is already a port on this step - rename it" in error["msg"]


@pytest.mark.parametrize(("model", "base", "field", "key"), _KINDS)
def test_a_name_the_step_has_no_port_called_is_accepted(model, base, field, key):
    # `unsure` is a classifier's port only with a minimum confidence; `error` is the graph's.
    for name in ("unsure", "error", "sales"):
        assert _config(model, base, field, key, name) is not None


def test_a_category_called_unsure_clashes_only_with_a_minimum_confidence():
    category = {"name": "unsure", "description": "d"}
    base = {"model_profile_id": _MODEL, "categories": [category]}
    AiClassifyConfig.model_validate(base)
    with pytest.raises(ValidationError, match="`unsure` is already a port on this step") as excinfo:
        AiClassifyConfig.model_validate({**base, "min_confidence": 0.5})
    assert [error["loc"] for error in excinfo.value.errors()] == [("categories", 0, "name")]


def test_a_split_branch_may_not_be_called_in_and_may_be_called_default():
    from app.workflows.nodes.logic_split._handler import LogicSplitConfig

    with pytest.raises(ValidationError, match="`in` is already a port on this step"):
        LogicSplitConfig.model_validate({"branches": [{"name": "in"}, {"name": "b"}]})
    assert LogicSplitConfig.model_validate({"branches": [{"name": "default"}, {"name": "b"}]})


def _node(definition_id: str, config: dict[str, Any], *, routes: bool) -> NodeInstance:
    return NodeInstance(
        id=uuid4(),
        definition_id=definition_id,
        definition_version=1,
        config=config,
        layout=NodePosition(x=0, y=0),
        policy=NodePolicy(on_error="route") if routes else None,
    )


def _clashes(node: NodeInstance) -> list[tuple[str, str]]:
    graph = WorkflowGraph(entry_node_id=node.id, nodes=(node,), edges=())
    return _error_port_clash_problems(graph, _resolve_definitions(graph))


_ERROR_CONFIGS = [
    ("logic.switch", {"rules": [{"name": "a", "condition": "value"}, {"name": "error"}]}, "rules"),
    ("ai.classify", {"categories": [{"name": "error"}]}, "categories"),
    ("error.handle", {"branches": [{"name": "a"}, {"name": "b"}, {"name": "error"}]}, "branches"),
    ("human.approval", {"choices": [{"id": "error", "label": "E"}]}, "choices"),
    ("logic.split", {"branches": [{"name": "a"}, {"name": "error"}]}, "branches"),
]


@pytest.mark.parametrize(("definition_id", "config", "field"), _ERROR_CONFIGS)
def test_a_step_that_routes_its_errors_may_not_name_an_output_error(definition_id, config, field):
    node = _node(definition_id, config, routes=True)
    key = "id" if field == "choices" else "name"
    index = len(config[field]) - 1

    assert _clashes(node) == [
        (
            f"nodes.{node.id}.config.{field}.{index}.{key}",
            "`error` is already a port on this step - rename it",
        )
    ]


@pytest.mark.parametrize(("definition_id", "config", "field"), _ERROR_CONFIGS)
def test_a_step_that_does_not_route_its_errors_has_no_error_port_to_clash_with(
    definition_id, config, field
):
    assert _clashes(_node(definition_id, config, routes=False)) == []


@pytest.mark.parametrize(
    ("definition_id", "config"),
    [
        ("debug.echo", {"message": "hi"}),
        ("logic.switch", {}),
        ("logic.switch", {"rules": ["error", {"name": "a"}]}),
    ],
)
def test_a_step_with_no_named_outputs_or_a_malformed_list_is_left_to_its_config(
    definition_id, config
):
    assert _clashes(_node(definition_id, config, routes=True)) == []
