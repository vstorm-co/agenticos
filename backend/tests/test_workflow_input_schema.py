"""Portable trigger contracts retain JSON Schema semantics at admission and discovery."""

from copy import deepcopy

import pytest
from pydantic import JsonValue, ValidationError

from app.workflows.contracts.input_schema import (
    MAX_NESTING,
    check_input_schema,
    schema_input_problems,
)
from app.workflows.nodes.core_input._handler import (
    STATIC_PORTS,
    TriggerInputConfig,
    effective_input_schema,
    input_problems,
    ports_for,
)
from app.workflows.nodes.trigger_form._handler import FormTriggerConfig


def _contract() -> dict[str, JsonValue]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "$defs": {
            "address": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "minLength": 2, "maxLength": 20},
                    "kind": {"enum": ["home", "work"]},
                },
                "required": ["city", "kind"],
                "additionalProperties": False,
            }
        },
        "properties": {
            "customer": {
                "type": "object",
                "properties": {
                    "addresses": {
                        "type": "array",
                        "items": {"$ref": "#/$defs/address"},
                        "minItems": 1,
                        "maxItems": 2,
                    }
                },
                "required": ["addresses"],
                "additionalProperties": False,
            }
        },
        "required": ["customer"],
        "additionalProperties": False,
    }


def test_nested_objects_arrays_and_local_definitions_validate_without_changing_input() -> None:
    config = TriggerInputConfig(input_schema=_contract())
    payload = {"customer": {"addresses": [{"city": "London", "kind": "work"}]}}
    original = deepcopy(payload)
    assert input_problems(config, payload) == []
    assert payload == original
    assert ports_for(config) is STATIC_PORTS
    assert effective_input_schema(config) == _contract()


@pytest.mark.parametrize(
    ("payload", "paths", "rule"),
    [
        ({}, ["customer"], "required"),
        ({"customer": {}}, ["customer.addresses"], "required"),
        (
            {"customer": {"addresses": [{"city": "Paris"}]}},
            ["customer.addresses.0.kind"],
            "required",
        ),
        (
            {"customer": {"addresses": [{}]}},
            ["customer.addresses.0.city", "customer.addresses.0.kind"],
            "required",
        ),
        ({"customer": {"addresses": []}}, ["customer.addresses"], "minItems"),
        (
            {"customer": {"addresses": [{"city": "X", "kind": "home"}]}},
            ["customer.addresses.0.city"],
            "minLength",
        ),
        (
            {"customer": {"addresses": [{"city": "X" * 21, "kind": "home"}]}},
            ["customer.addresses.0.city"],
            "maxLength",
        ),
        (
            {"customer": {"addresses": [{"city": "Paris", "kind": "private-value"}]}},
            ["customer.addresses.0.kind"],
            "enum",
        ),
        (
            {
                "customer": {
                    "addresses": [{"city": "Paris", "kind": "home", "extra": "private-value"}]
                }
            },
            ["customer.addresses.0.extra"],
            "additionalProperties",
        ),
        ({"customer": {"addresses": "private-value"}}, ["customer.addresses"], "type"),
    ],
)
def test_errors_identify_nested_fields_without_echoing_values(
    payload: dict[str, JsonValue], paths: list[str], rule: str
) -> None:
    problems = input_problems(TriggerInputConfig(input_schema=_contract()), payload)
    assert [problem["field"] for problem in problems] == paths
    assert all(problem["type"] == rule and problem["message"] for problem in problems)
    assert "private-value" not in str(problems)


@pytest.mark.parametrize(
    ("schema", "message"),
    [
        ({"type": "unknown-type"}, "Invalid Draft"),
        ({"minLength": -1}, "Invalid Draft"),
        ({"$schema": "http://json-schema.org/draft-07/schema#"}, "Draft 2020-12"),
        ({"$schema": {}}, "Draft 2020-12"),
        ({"$ref": "https://example.com/schema.json"}, "within the supplied document"),
        ({"$ref": "schema.json#/$defs/value"}, "within the supplied document"),
        ({"$ref": "#/$defs/missing"}, "unresolved local reference"),
        (
            {"$defs": {"unused": {"$ref": "https://example.com/schema.json"}}},
            "within the supplied document",
        ),
        ({"const": "private-value", "$ref": "#/const"}, "schema object or boolean"),
        ({"$ref": "#"}, "reference cycle"),
        ({"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}}, "reference cycle"),
        ({"allOf": [{"$ref": "#"}]}, "reference cycle"),
        ({"dependentSchemas": {"a": {"$ref": "#"}}}, "reference cycle"),
        ({"$dynamicRef": "#"}, "reference cycle"),
    ],
)
def test_invalid_contracts_are_refused_when_the_trigger_config_is_loaded(
    schema: dict[str, JsonValue], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        TriggerInputConfig(input_schema=schema)


def test_a_cycle_is_refused_even_when_a_consuming_path_visits_its_target_first() -> None:
    schema: dict[str, JsonValue] = {
        "$defs": {
            "a": {
                "properties": {"child": {"$ref": "#/$defs/b"}},
                "anyOf": [{"$ref": "#/$defs/b"}],
            },
            "b": {"$ref": "#/$defs/a"},
        }
    }
    with pytest.raises(ValidationError, match="reference cycle"):
        TriggerInputConfig(input_schema=schema)


def test_recursive_objects_arrays_anchors_and_escaped_pointers_are_supported() -> None:
    schema: dict[str, JsonValue] = {
        "$id": "https://example.com/local-schema",
        "$defs": {
            "node/value": {
                "$anchor": "node",
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "children": {"type": "array", "items": {"$ref": "#node"}},
                    "next": {"$ref": "#/$defs/node~1value"},
                },
            }
        },
        "$ref": "#node",
    }
    config = TriggerInputConfig(input_schema=schema)
    assert input_problems(config, {"next": {"children": [{"label": "leaf"}]}}) == []
    problems = input_problems(config, {"children": [{"label": False}]})
    assert problems[0]["field"] == "children.0.label"


def test_schema_looking_values_inside_instance_annotations_are_not_references() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "default": {"$ref": "https://example.com/instance-data"},
        "properties": {"value": {"const": {"$ref": "https://example.com/instance-data"}}},
    }
    config = TriggerInputConfig(input_schema=schema)
    assert input_problems(config, {"value": {"$ref": "https://example.com/instance-data"}}) == []


def test_discovery_keeps_legacy_fields_and_untyped_contracts() -> None:
    assert effective_input_schema(TriggerInputConfig()) == {"type": "object"}
    assert TriggerInputConfig.model_validate({}).input_schema is None
    assert TriggerInputConfig(input_schema=None).input_schema is None
    config = TriggerInputConfig.model_validate(
        {
            "fields": [
                {"name": "name", "type": "text", "label": "Name", "description": "Your name"},
                {"name": "devices", "type": "string_list"},
                {"name": "plan", "type": "choice", "options": ["basic", "pro"]},
                {"name": "date", "type": "date", "required": False},
            ]
        }
    )
    schema = effective_input_schema(config)
    assert schema == {
        "type": "object",
        "properties": {
            "name": {"type": "string", "title": "Name", "description": "Your name"},
            "devices": {"type": "array", "items": {"type": "string"}, "title": "devices"},
            "plan": {"type": "string", "enum": ["basic", "pro"], "title": "plan"},
            "date": {
                "anyOf": [{"type": "string", "format": "date"}, {"type": "null"}],
                "title": "date",
            },
        },
        "required": ["name", "devices", "plan"],
        "additionalProperties": False,
    }


def test_exporting_a_contract_cannot_mutate_the_versioned_config() -> None:
    config = TriggerInputConfig(input_schema=_contract())
    exported = effective_input_schema(config)
    exported["type"] = "array"
    assert config.input_schema == _contract()


def test_simple_fields_and_raw_schema_cannot_silently_override_each_other() -> None:
    with pytest.raises(ValidationError, match="either simple fields or input_schema"):
        TriggerInputConfig.model_validate({"fields": [{"name": "name"}], "input_schema": {}})
    assert input_problems(TriggerInputConfig(input_schema={}), {"anything": [1]}) == []
    with pytest.raises(ValidationError, match="public form uses simple fields"):
        FormTriggerConfig(input_schema={})


@pytest.mark.parametrize(
    ("schema", "payload", "rule"),
    [
        ({"properties": {"x": {"type": ["string", "null"]}}}, {"x": False}, "type"),
        ({"properties": {"x": {"const": "allowed"}}}, {"x": "private-value"}, "const"),
        ({"properties": {"x": {"type": "array", "maxItems": 0}}}, {"x": [1]}, "maxItems"),
        ({"properties": {"x": {"minimum": 5}}}, {"x": 3}, "minimum"),
        ({"properties": {"x": {"maximum": 5}}}, {"x": 7}, "maximum"),
        ({"properties": {"x": {"pattern": "^allowed$"}}}, {"x": "private-value"}, "pattern"),
        ({"unevaluatedProperties": False}, {"x": "private-value"}, "unevaluatedProperties"),
        ({"properties": {"x": False}}, {"x": "private-value"}, "schema"),
        ({"oneOf": [{"required": ["x"]}, {"required": ["y"]}]}, {}, "oneOf"),
    ],
)
def test_other_draft_constraints_have_safe_explanations(
    schema: dict[str, JsonValue], payload: dict[str, JsonValue], rule: str
) -> None:
    config = TriggerInputConfig(input_schema=schema)
    problems = input_problems(config, payload)
    assert problems[0]["type"] == rule
    assert "private-value" not in str(problems)


def test_pattern_properties_and_boolean_subschemas_follow_draft_semantics() -> None:
    config = TriggerInputConfig(
        input_schema={
            "properties": {"fixed": True, "tuple": {"prefixItems": [True, False]}},
            "patternProperties": {"^allowed_": {"type": "integer"}},
            "additionalProperties": False,
        }
    )
    assert input_problems(config, {"fixed": None, "allowed_key": 3, "tuple": ["x"]}) == []
    assert input_problems(config, {"allowed_key": 3, "unexpected": "private-value"}) == [
        {
            "field": "unexpected",
            "message": "Additional properties are not allowed",
            "type": "additionalProperties",
        }
    ]


def _deep_object() -> dict[str, JsonValue]:
    value: dict[str, JsonValue] = {}
    for _ in range(MAX_NESTING + 1):
        value = {"nested": value}
    return value


def test_excessive_document_and_input_nesting_are_clear_refusals() -> None:
    with pytest.raises(ValueError, match="maximum nesting depth"):
        check_input_schema(_deep_object())
    assert schema_input_problems({}, _deep_object()) == [
        {"field": "$", "message": "Input exceeds the maximum nesting depth", "type": "max_depth"}
    ]


def test_a_long_reference_chain_cannot_crash_run_admission() -> None:
    definitions: dict[str, JsonValue] = {
        f"item_{index}": {"$ref": f"#/$defs/item_{index + 1}"} for index in range(500)
    }
    definitions["item_500"] = {"type": "object"}
    schema: dict[str, JsonValue] = {"$defs": definitions, "$ref": "#/$defs/item_0"}
    check_input_schema(schema)
    assert schema_input_problems(schema, {}) == [
        {
            "field": "$",
            "message": "Input exceeds the schema validation nesting limit",
            "type": "max_depth",
        }
    ]
