"""The "Manual or API" trigger's declared fields: the run's input contract.

A trigger with no fields takes any JSON object. With fields, the config is
checked at publish, a binding to `payload.<field>` is type-checked there too,
and the run's input is checked against them before the run is admitted.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.permissions import AuthContext, OrgRoleName
from app.workflows.contracts.io import Binding, NodeOutputRef
from app.workflows.graph.errors import GraphValidationError
from app.workflows.graph.model import Edge, NodeInstance, NodePosition, WorkflowGraph
from app.workflows.graph.validate import validate_graph
from app.workflows.nodes.core_input._handler import (
    STATIC_PORTS,
    ManualTriggerConfig,
    input_problems,
    ports_for,
)

pytestmark = pytest.mark.anyio

FIELDS: list[dict[str, Any]] = [
    {"name": "email", "type": "text"},
    {"name": "seats", "type": "integer"},
    {"name": "price", "type": "number", "required": False},
    {"name": "urgent", "type": "boolean"},
    {"name": "due", "type": "date", "required": False},
    {"name": "plan", "type": "choice", "options": ["basic", "pro"]},
]

FITS = {"email": "ada@example.com", "seats": 3, "urgent": False, "plan": "pro"}


def _config(fields: list[dict[str, Any]] = FIELDS) -> ManualTriggerConfig:
    return ManualTriggerConfig.model_validate({"fields": fields})


class TestTheConfig:
    def test_no_fields_is_the_default_every_existing_graph_has(self):
        assert ManualTriggerConfig.model_validate({}).fields == []

    @pytest.mark.parametrize(
        ("fields", "says"),
        [
            ([{"name": "Email", "type": "text"}], "pattern"),
            ([{"name": "copy", "type": "text"}], "reserved"),
            ([{"name": "plan", "type": "choice"}], "at least one option"),
            ([{"name": "plan", "type": "choice", "options": ["a", " "]}], "none of them blank"),
            ([{"name": "plan", "type": "choice", "options": ["a", "a"]}], "each option once"),
            ([{"name": "email", "type": "text", "options": ["a"]}], "Only a choice"),
            ([{"name": "a", "type": "text"}, {"name": "a", "type": "date"}], "same name"),
        ],
        ids=["bad-name", "reserved", "no-options", "blank", "twice", "not-a-choice", "dupe"],
    )
    def test_a_field_that_could_not_be_asked_for_is_refused(self, fields, says):
        with pytest.raises(ValidationError, match=says):
            _config(fields)


class TestTheRunsInput:
    def test_an_input_that_fits_has_no_problems_and_no_fields_takes_anything(self):
        assert input_problems(_config(), FITS) == []
        assert input_problems(_config(), {**FITS, "price": 9, "due": "2026-10-01"}) == []
        assert input_problems(ManualTriggerConfig(), {"anything": [1]}) == []

    @pytest.mark.parametrize(
        ("change", "field"),
        [
            ({"email": None}, "email"),
            ({"seats": "3"}, "seats"),
            ({"seats": 2.5}, "seats"),
            ({"urgent": 1}, "urgent"),
            ({"price": "cheap"}, "price"),
            ({"due": "01/10/2026"}, "due"),
            ({"due": "2026-02-30"}, "due"),
            ({"plan": "enterprise"}, "plan"),
            ({"extra": "x"}, "extra"),
        ],
        ids=[
            "missing-text",
            "string-for-int",
            "float-for-int",
            "int-for-bool",
            "text-for-number",
            "not-iso",
            "no-such-day",
            "not-an-option",
            "undeclared",
        ],
    )
    def test_each_value_that_does_not_fit_is_named(self, change, field):
        run_input = {**FITS, **change}
        if change.get("email", "") is None:
            del run_input["email"]
        problems = input_problems(_config(), run_input)
        assert [problem["field"] for problem in problems] == [field]
        assert problems[0]["message"]

    def test_a_problem_never_quotes_the_value_it_refused(self):
        problems = input_problems(_config(), {**FITS, "seats": "sk-secret-value"})
        assert "sk-secret-value" not in str(problems)


class TestThePort:
    def test_with_no_fields_the_payload_stays_open(self):
        assert ports_for(ManualTriggerConfig()) is STATIC_PORTS
        assert ports_for(None) is STATIC_PORTS

    def test_with_fields_the_payload_is_typed_by_them(self):
        (out,) = ports_for(_config())
        payload = out.schema.model_fields["payload"].annotation
        assert payload.model_fields["seats"].annotation is int
        assert payload.model_fields["price"].annotation == float | None
        assert out.schema.model_fields["triggered_by"].annotation is str


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def _graph(config: dict[str, Any], field_path: tuple[str, ...]) -> WorkflowGraph:
    trigger = NodeInstance(
        id=uuid4(), definition_id="core.input", definition_version=1, config=config, layout=_pos()
    )
    output = NodeInstance(
        id=uuid4(), definition_id="core.output", definition_version=1, config={}, layout=_pos()
    )
    return WorkflowGraph(
        entry_node_id=trigger.id,
        nodes=(trigger, output),
        edges=(
            Edge(
                id=uuid4(),
                source_node_id=trigger.id,
                source_port="out",
                target_node_id=output.id,
                target_port="in",
            ),
        ),
        bindings=(
            Binding(
                target_node_id=output.id,
                target_field="text",
                source=NodeOutputRef(node_id=trigger.id, port="out", field_path=field_path),
            ),
        ),
    )


class TestPublish:
    def _ctx(self) -> AuthContext:
        return AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER.value)

    async def test_a_declared_field_binds_where_its_type_fits(self, mock_db_session):
        graph = _graph({"fields": FIELDS}, ("payload", "email"))
        assert await validate_graph(mock_db_session, self._ctx(), graph)

    async def test_an_undeclared_payload_path_binds_only_to_an_open_payload(self, mock_db_session):
        assert await validate_graph(mock_db_session, self._ctx(), _graph({}, ("payload", "any")))
        with pytest.raises(GraphValidationError) as refused:
            await validate_graph(
                mock_db_session, self._ctx(), _graph({"fields": FIELDS}, ("payload", "any"))
            )
        assert "does not exist" in str(refused.value.details)

    async def test_a_declared_field_of_another_type_is_refused_at_publish(self, mock_db_session):
        with pytest.raises(GraphValidationError) as refused:
            await validate_graph(
                mock_db_session, self._ctx(), _graph({"fields": FIELDS}, ("payload", "seats"))
            )
        assert "not compatible" in str(refused.value.details)
