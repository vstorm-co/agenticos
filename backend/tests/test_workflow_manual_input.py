"""The "Manual or API" trigger's declared fields: the run's input contract.

A trigger with no fields takes any JSON object. With fields, the config is
checked at publish, a binding to `payload.<field>` is type-checked there too,
and the run's input is checked against them before the run is admitted.
"""

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
    TriggerInputConfig,
    input_problems,
    ports_for,
)
from app.workflows.nodes.trigger_form._handler import FormTriggerConfig

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


def _config(fields: list[dict[str, Any]] = FIELDS) -> TriggerInputConfig:
    return TriggerInputConfig.model_validate({"fields": fields})


class TestTheConfig:
    def test_no_fields_is_the_default_every_existing_graph_has(self):
        assert TriggerInputConfig.model_validate({}).fields == []

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
    @pytest.mark.parametrize("config_type", [TriggerInputConfig, FormTriggerConfig])
    @pytest.mark.parametrize("value", [[], ["leaf-01", "leaf-02"], ["", " leaf-01 ", "leaf-01"]])
    def test_text_lists_accept_string_arrays_without_changing_items(
        self, config_type: type[TriggerInputConfig], value: list[str]
    ) -> None:
        config = config_type.model_validate(
            {"fields": [{"name": "devices", "type": "string_list"}]}
        )
        assert input_problems(config, {"devices": value}) == []
        (out,) = ports_for(config)
        parsed = out.schema.model_validate({"payload": {"devices": value}, "triggered_by": "api"})
        assert parsed.model_dump()["payload"]["devices"] == value

    @pytest.mark.parametrize(
        ("value", "path", "kind"),
        [
            ("leaf-01", "devices", "list_type"),
            (None, "devices", "list_type"),
            ({"device": "leaf-01"}, "devices", "list_type"),
            (["leaf-01", 2], "devices.1", "string_type"),
            ([True], "devices.0", "string_type"),
            ([None], "devices.0", "string_type"),
            ([["leaf-01"]], "devices.0", "string_type"),
        ],
    )
    def test_text_lists_refuse_scalars_and_non_string_items(
        self, value: object, path: str, kind: str
    ) -> None:
        config = _config([{"name": "devices", "type": "string_list"}])
        problems = input_problems(config, {"devices": value})
        assert [(problem["field"], problem["type"]) for problem in problems] == [(path, kind)]

    def test_text_lists_follow_required_and_optional_field_rules(self) -> None:
        required = _config([{"name": "devices", "type": "string_list"}])
        assert input_problems(required, {})[0]["type"] == "missing"
        optional = _config([{"name": "devices", "type": "string_list", "required": False}])
        assert input_problems(optional, {}) == []
        assert input_problems(optional, {"devices": None}) == []

    def test_an_input_that_fits_has_no_problems_and_no_fields_takes_anything(self):
        assert input_problems(_config(), FITS) == []
        assert input_problems(_config(), {**FITS, "price": 9, "due": "2026-10-01"}) == []
        assert input_problems(TriggerInputConfig(), {"anything": [1]}) == []

    @pytest.mark.parametrize(
        ("change", "field", "kind"),
        [
            ({"email": None}, "email", "missing"),
            ({"seats": "3"}, "seats", "int_type"),
            ({"seats": 2.5}, "seats", "int_type"),
            ({"urgent": 1}, "urgent", "bool_type"),
            ({"price": "cheap"}, "price", "float_type"),
            ({"due": "01/10/2026"}, "due", "value_error"),
            ({"due": "2026-02-30"}, "due", "value_error"),
            ({"plan": "enterprise"}, "plan", "value_error"),
            ({"extra": "x"}, "extra", "extra_forbidden"),
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
    def test_each_value_that_does_not_fit_is_named(self, change, field, kind):
        run_input = {**FITS, **change}
        if change.get("email", "") is None:
            del run_input["email"]
        problems = input_problems(_config(), run_input)
        assert [(problem["field"], problem["type"]) for problem in problems] == [(field, kind)]
        assert problems[0]["message"]

    def test_a_problem_never_quotes_the_value_it_refused(self):
        problems = input_problems(_config(), {**FITS, "seats": "sk-secret-value"})
        assert "sk-secret-value" not in str(problems)


class TestThePort:
    def test_text_list_ports_publish_array_item_types_and_nullability(self) -> None:
        config = _config(
            [
                {"name": "devices", "type": "string_list"},
                {"name": "optional", "type": "string_list", "required": False},
            ]
        )
        (out,) = ports_for(config)
        schema = out.schema.model_json_schema()["$defs"]["Payload"]
        assert schema["properties"]["devices"] == {
            "type": "array",
            "items": {"type": "string"},
            "title": "devices",
        }
        assert schema["properties"]["optional"]["anyOf"] == [
            {"type": "array", "items": {"type": "string"}},
            {"type": "null"},
        ]
        assert schema["required"] == ["devices"]

    def test_with_no_fields_the_payload_stays_open(self):
        assert ports_for(TriggerInputConfig()) is STATIC_PORTS
        assert ports_for(None) is STATIC_PORTS

    def test_with_fields_the_payload_is_typed_by_them(self):
        (out,) = ports_for(_config())
        payload = out.schema.model_fields["payload"].annotation
        assert payload.model_fields["seats"].annotation is int
        assert payload.model_fields["price"].annotation == float | None
        assert out.schema.model_fields["triggered_by"].annotation is str


def _pos() -> NodePosition:
    return NodePosition(x=0, y=0)


def _graph(
    config: dict[str, Any], field_path: tuple[str, ...], trigger_id: str = "core.input"
) -> WorkflowGraph:
    trigger = NodeInstance(
        id=uuid4(), definition_id=trigger_id, definition_version=1, config=config, layout=_pos()
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

    @pytest.mark.parametrize(
        "schema",
        [
            {"$id": 12},
            {"$ref": "#/$defs/missing"},
            {"type": "unknown"},
            {"properties": {"email": {"pattern": "(" * 600 + "a" + ")" * 600}}},
            {"properties": {"email": {"pattern": "a{4294967296}"}}},
            {"type": "array"},
            {
                "$defs": {"rows": {"type": "array"}},
                "allOf": [{"$ref": "#/$defs/rows"}],
            },
        ],
    )
    async def test_invalid_json_schema_is_a_field_refusal_at_publication(
        self, mock_db_session, schema: dict[str, object]
    ) -> None:
        with pytest.raises(GraphValidationError) as refused:
            await validate_graph(
                mock_db_session, self._ctx(), _graph({"input_schema": schema}, ("payload", "email"))
            )
        assert refused.value.status_code == 422
        assert any(
            "input_schema" in problem["field"] for problem in refused.value.details["fields"]
        )

    @pytest.mark.parametrize("trigger_id", ["core.input", "trigger.manual"], ids=["api", "manual"])
    async def test_a_declared_field_binds_where_its_type_fits(self, mock_db_session, trigger_id):
        graph = _graph({"fields": FIELDS}, ("payload", "email"), trigger_id)
        assert await validate_graph(mock_db_session, self._ctx(), graph)

    async def test_an_undeclared_payload_path_binds_only_to_an_open_payload(self, mock_db_session):
        assert await validate_graph(mock_db_session, self._ctx(), _graph({}, ("payload", "any")))
        with pytest.raises(GraphValidationError) as refused:
            await validate_graph(
                mock_db_session, self._ctx(), _graph({"fields": FIELDS}, ("payload", "any"))
            )
        assert "does not exist" in str(refused.value.details)

    @pytest.mark.parametrize("trigger_id", ["core.input", "trigger.manual"], ids=["api", "manual"])
    @pytest.mark.parametrize("field_type", ["integer", "string_list"])
    async def test_a_declared_field_of_another_type_is_refused_at_publish(
        self, mock_db_session, trigger_id: str, field_type: str
    ):
        with pytest.raises(GraphValidationError) as refused:
            await validate_graph(
                mock_db_session,
                self._ctx(),
                _graph(
                    {"fields": [{"name": "seats", "type": field_type}]},
                    ("payload", "seats"),
                    trigger_id,
                ),
            )
        assert "not compatible" in str(refused.value.details)
