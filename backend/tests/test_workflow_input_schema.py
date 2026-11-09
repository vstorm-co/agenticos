"""Portable trigger contracts retain JSON Schema semantics at admission and discovery."""

import json
from collections.abc import Iterator
from copy import deepcopy
from itertools import permutations

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import JsonValue, ValidationError
from referencing import Resource
from referencing.jsonschema import Schema

from app.services.workflow_execution.exceptions import WorkflowRunInputInvalidError
from app.workflows.contracts import input_schema
from app.workflows.contracts.input_schema import (
    MAX_DIAGNOSTIC_BYTES,
    MAX_DISCOVERY_BYTES,
    MAX_NESTING,
    MAX_PROBLEMS,
    _error_paths,
    check_input_schema,
    schema_input_problems,
)
from app.workflows.nodes.core_input._handler import (
    _CALENDAR_DATE_PATTERN,
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
        ({"$id": 12}, "Invalid Draft"),
        ({"$defs": {"child": {"$id": []}}}, "Invalid Draft"),
        ({"properties": {"value": {"pattern": "["}}}, "Invalid Draft"),
        ({"patternProperties": {"[": {"type": "string"}}}, "Invalid Draft"),
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


def test_local_references_respect_nested_resource_scopes() -> None:
    schema: dict[str, JsonValue] = {
        "$id": "https://example.com/contract",
        "$defs": {"value": {"type": "integer"}},
        "properties": {
            "nested": {
                "$id": "nested",
                "$defs": {"value": {"type": "string"}},
                "properties": {"value": {"$ref": "#/$defs/value"}},
            },
            "value": {"$ref": "#/$defs/value"},
        },
    }
    config = TriggerInputConfig(input_schema=schema)
    assert input_problems(config, {"nested": {"value": "local"}, "value": 2}) == []
    problems = input_problems(config, {"nested": {"value": 2}, "value": "local"})
    assert [(problem["field"], problem["message"]) for problem in problems] == [
        ("nested.value", "Must be of type string"),
        ("value", "Must be of type integer"),
    ]


def test_local_references_cannot_escape_a_nested_resource_to_outer_definitions() -> None:
    schema: dict[str, JsonValue] = {
        "$defs": {"outer": {"type": "string"}},
        "properties": {
            "nested": {"$id": "nested", "properties": {"value": {"$ref": "#/$defs/outer"}}}
        },
    }
    with pytest.raises(ValidationError, match="unresolved local reference"):
        TriggerInputConfig(input_schema=schema)


@pytest.mark.parametrize("keyword", ["anyOf", "oneOf"])
def test_nullable_object_unions_report_nested_errors_in_the_applicable_branch(
    keyword: str,
) -> None:
    schema: dict[str, JsonValue] = {
        "properties": {
            "customer": {
                keyword: [
                    {
                        "type": "object",
                        "properties": {"name": {"type": "string", "minLength": 2}},
                        "required": ["name"],
                    },
                    {"type": "null"},
                ]
            }
        }
    }
    config = TriggerInputConfig(input_schema=schema)
    assert input_problems(config, {"customer": None}) == []
    assert input_problems(config, {"customer": {}}) == [
        {"field": "customer.name", "message": "Field required", "type": "required"}
    ]
    assert input_problems(config, {"customer": {"name": "a"}}) == [
        {
            "field": "customer.name",
            "message": "Must contain at least 2 characters",
            "type": "minLength",
        }
    ]
    assert input_problems(config, {"customer": []})[0]["type"] == keyword


def test_nested_union_errors_keep_array_indices_and_do_not_guess_between_object_variants() -> None:
    config = TriggerInputConfig(
        input_schema={
            "properties": {
                "customers": {
                    "anyOf": [
                        {
                            "type": "array",
                            "items": {
                                "anyOf": [
                                    {"type": "object", "required": ["name"]},
                                    {"type": "null"},
                                ]
                            },
                        },
                        {"type": "null"},
                    ]
                },
                "choice": {
                    "anyOf": [
                        {"type": "object", "required": ["person"]},
                        {"type": "object", "required": ["company"]},
                    ]
                },
                "overlap": {"oneOf": [{"type": "integer"}, {"type": "number"}]},
            }
        }
    )
    problems = input_problems(config, {"customers": [{}], "choice": {}, "overlap": 2})
    assert [(problem["field"], problem["type"]) for problem in problems] == [
        ("customers.0.name", "required"),
        ("choice", "anyOf"),
        ("overlap", "oneOf"),
    ]


def test_schema_looking_values_inside_instance_annotations_are_not_references() -> None:
    schema: dict[str, JsonValue] = {
        "type": "object",
        "default": {"$ref": "https://example.com/instance-data"},
        "properties": {"value": {"const": {"$ref": "https://example.com/instance-data"}}},
    }
    config = TriggerInputConfig(input_schema=schema)
    assert input_problems(config, {"value": {"$ref": "https://example.com/instance-data"}}) == []


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "array"},
        {"type": ["string", "null"]},
        {"const": []},
        {"enum": ["text", 2, None, []]},
        {"$defs": {"rows": {"type": "array"}}, "$ref": "#/$defs/rows"},
        {"$defs": {"never": False}, "$ref": "#/$defs/never"},
        {"$defs": {"value": {"type": "object"}}, "$ref": "#/$defs/value", "type": "array"},
        {"$defs": {"value": {"type": "array"}}, "$ref": "#/$defs/value", "type": "object"},
        {"allOf": [{"type": "object"}, {"type": "array"}]},
        {"allOf": [False]},
        {"anyOf": [{"type": "array"}, {"type": "null"}]},
        {"oneOf": [{"type": "number"}, {"type": "boolean"}]},
        {
            "$defs": {"rows": {"type": "array"}},
            "allOf": [{"$ref": "#/$defs/rows"}],
        },
    ],
)
def test_root_constraints_that_rule_out_json_objects_are_refused(
    schema: dict[str, JsonValue],
) -> None:
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema=schema)


@pytest.mark.parametrize(
    "schema",
    [
        {},
        {"type": "object"},
        {"type": ["object", "null"]},
        {"const": {"name": "Ada"}},
        {"enum": [None, {"name": "Ada"}]},
        {"$defs": {"value": {"type": "object"}}, "$ref": "#/$defs/value"},
        {"$defs": {"unused": {"type": "array"}}},
        {"properties": {"rows": {"type": "array", "items": {"type": "integer"}}}},
        {"properties": {"child": {"$ref": "#"}}},
        {"allOf": [True, {"type": "object"}]},
        {"anyOf": [{"type": "array"}, {"type": "object"}]},
        {"oneOf": [False, {"type": "object"}]},
        {"if": {"type": "array"}},
        {"then": {"type": "array"}},
        {"else": {"type": "array"}},
        {
            "if": {"required": ["kind"]},
            "then": {"required": ["name"]},
            "else": {"required": ["title"]},
        },
        {"not": {"required": ["excluded"]}},
        {
            "$defs": {"dynamic": {"$dynamicAnchor": "value", "type": "array"}},
            "$dynamicRef": "#value",
        },
    ],
)
def test_root_object_compatibility_preserves_open_composed_and_recursive_contracts(
    schema: dict[str, JsonValue],
) -> None:
    assert TriggerInputConfig(input_schema=schema).input_schema == schema


def test_reused_reference_branches_are_classified_without_expanding_their_paths() -> None:
    definitions: dict[str, JsonValue] = {"leaf": {"type": "object"}}
    reference = "#/$defs/leaf"
    for index in range(30):
        name = f"branch_{index}"
        definitions[name] = {"allOf": [{"$ref": reference}, {"$ref": reference}]}
        reference = f"#/$defs/{name}"
    schema: dict[str, JsonValue] = {"$defs": definitions, "$ref": reference}
    assert TriggerInputConfig(input_schema=schema).input_schema == schema


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
                "anyOf": [
                    {
                        "type": "string",
                        "format": "date",
                        "pattern": _CALENDAR_DATE_PATTERN,
                        "maxLength": 10,
                    },
                    {"type": "null"},
                ],
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
    with pytest.raises(ValidationError, match="Input should be None"):
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


def test_object_errors_and_a_property_named_dollar_have_distinct_paths() -> None:
    config = TriggerInputConfig(
        input_schema={"minProperties": 2, "properties": {"$": {"type": "string"}}}
    )
    problems = input_problems(config, {"$": 1})
    assert [(problem["field"], problem["type"]) for problem in problems] == [
        ("", "minProperties"),
        ("$", "type"),
    ]


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
        {"field": "", "message": "Input exceeds the maximum nesting depth", "type": "max_depth"}
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
            "field": "",
            "message": "Input exceeds the schema validation nesting limit",
            "type": "max_depth",
        }
    ]


def test_schema_valued_unevaluated_properties_report_the_key_and_its_type_error() -> None:
    config = TriggerInputConfig(input_schema={"unevaluatedProperties": {"type": "integer"}})
    assert input_problems(config, {"extra": "private-value"}) == [
        {"field": "extra", "message": "Must be of type integer", "type": "type"}
    ]
    assert "private-value" not in str(input_problems(config, {"extra": "private-value"}))


def test_boolean_unevaluated_properties_report_each_forbidden_key() -> None:
    config = TriggerInputConfig(input_schema={"unevaluatedProperties": False})
    assert input_problems(config, {"extra": "private-value"}) == [
        {
            "field": "extra",
            "message": "Additional properties are not allowed",
            "type": "unevaluatedProperties",
        }
    ]


def test_true_unevaluated_properties_allow_any_key() -> None:
    config = TriggerInputConfig(input_schema={"unevaluatedProperties": True})
    assert input_problems(config, {"anything": [1]}) == []


def test_nested_unevaluated_properties_keep_the_parent_path() -> None:
    config = TriggerInputConfig(
        input_schema={"properties": {"nested": {"unevaluatedProperties": {"type": "integer"}}}}
    )
    assert input_problems(config, {"nested": {"extra": "private-value"}}) == [
        {"field": "nested.extra", "message": "Must be of type integer", "type": "type"}
    ]


def test_evaluated_keys_from_a_valid_composition_are_not_unevaluated() -> None:
    config = TriggerInputConfig(
        input_schema={
            "allOf": [{"properties": {"known": {"type": "integer"}}}],
            "unevaluatedProperties": False,
        }
    )
    assert input_problems(config, {"known": 3}) == []
    assert input_problems(config, {"known": 3, "extra": "private-value"}) == [
        {
            "field": "extra",
            "message": "Additional properties are not allowed",
            "type": "unevaluatedProperties",
        }
    ]


def test_evaluated_keys_from_pattern_properties_are_not_unevaluated() -> None:
    config = TriggerInputConfig(
        input_schema={
            "patternProperties": {"^allowed_": {"type": "integer"}},
            "unevaluatedProperties": False,
        }
    )
    assert input_problems(config, {"allowed_key": 3}) == []
    assert input_problems(config, {"allowed_key": 3, "other": 1}) == [
        {
            "field": "other",
            "message": "Additional properties are not allowed",
            "type": "unevaluatedProperties",
        }
    ]


def test_evaluated_keys_from_a_reference_are_not_unevaluated() -> None:
    config = TriggerInputConfig(
        input_schema={
            "$defs": {"obj": {"properties": {"known": {"type": "integer"}}}},
            "allOf": [{"$ref": "#/$defs/obj"}],
            "unevaluatedProperties": False,
        }
    )
    assert input_problems(config, {"known": 3}) == []
    assert input_problems(config, {"known": 3, "extra": "private-value"}) == [
        {
            "field": "extra",
            "message": "Additional properties are not allowed",
            "type": "unevaluatedProperties",
        }
    ]


def test_unevaluated_properties_respect_nested_resource_scopes() -> None:
    schema: dict[str, JsonValue] = {
        "$id": "https://example.com/root",
        "$defs": {"outer": {"properties": {"x": {"type": "integer"}}}},
        "properties": {
            "nested": {
                "$id": "nested",
                "$defs": {"inner": {"properties": {"y": {"type": "integer"}}}},
                "allOf": [{"$ref": "#/$defs/inner"}],
                "unevaluatedProperties": False,
            }
        },
    }
    config = TriggerInputConfig(input_schema=schema)
    # `y` is evaluated by `nested`'s own `$defs/inner`; `x` belongs to the outer
    # resource, so the nested resource must not count it as evaluated.
    assert input_problems(config, {"nested": {"y": 1}}) == []
    assert input_problems(config, {"nested": {"y": 1, "x": 2}}) == [
        {
            "field": "nested.x",
            "message": "Additional properties are not allowed",
            "type": "unevaluatedProperties",
        }
    ]


def test_schema_valued_unevaluated_properties_resolve_local_references() -> None:
    config = TriggerInputConfig(
        input_schema={
            "$defs": {"integer": {"type": "integer"}},
            "unevaluatedProperties": {"$ref": "#/$defs/integer"},
        }
    )
    assert input_problems(config, {"extra": "private-value"}) == [
        {"field": "extra", "message": "Must be of type integer", "type": "type"}
    ]


def test_mixed_required_and_type_errors_keep_deterministic_order() -> None:
    config = TriggerInputConfig(
        input_schema={
            "type": "object",
            "required": ["a", "b", "c"],
            "properties": {"a": {"type": "integer"}},
        }
    )
    assert [(p["field"], p["type"]) for p in input_problems(config, {"a": "wrong"})] == [
        ("b", "required"),
        ("c", "required"),
        ("a", "type"),
    ]


def test_required_missing_names_expand_once_per_constraint_not_per_error() -> None:
    """50 sibling `required` errors share one constraint and expand 50 names, not 2500."""
    names = [f"f{i}" for i in range(50)]
    errors = [
        JsonSchemaValidationError(
            "x is a required property",
            validator="required",
            validator_value=names,
            instance={},
        )
        for _ in range(50)
    ]
    seen_required: set[tuple[tuple[str | int, ...], tuple[str, ...]]] = set()
    paths = [path for error in errors for path in _error_paths(error, seen_required)]
    assert paths == [(f"f{i}",) for i in range(50)]
    assert len(seen_required) == 1


def test_missing_names_within_the_cap_are_all_reported() -> None:
    names = [f"f{i}" for i in range(MAX_PROBLEMS - 1)]
    config = TriggerInputConfig(input_schema={"required": names})
    problems = input_problems(config, {})
    assert [p["field"] for p in problems] == names
    assert all(p["type"] == "required" and p["message"] == "Field required" for p in problems)


@pytest.mark.parametrize("count", [400, 800])
def test_hundreds_of_missing_names_are_capped_and_ordered(count: int) -> None:
    config = TriggerInputConfig(input_schema={"required": [f"f{i}" for i in range(count)]})
    problems = input_problems(config, {})
    assert len(problems) == MAX_PROBLEMS
    assert [p["field"] for p in problems[:-1]] == [f"f{i}" for i in range(MAX_PROBLEMS - 1)]
    assert all(p["type"] == "required" and p["message"] == "Field required" for p in problems[:-1])
    assert problems[-1] == {
        "field": "",
        "message": "More problems than can be shown",
        "type": "truncated",
    }


def test_large_arrays_keep_indices_while_capped() -> None:
    config = TriggerInputConfig(
        input_schema={
            "type": "object",
            "properties": {
                "rows": {"type": "array", "items": {"type": "object", "required": ["id"]}}
            },
        }
    )
    problems = input_problems(config, {"rows": [{} for _ in range(800)]})
    assert len(problems) == MAX_PROBLEMS
    assert [p["field"] for p in problems[:-1]] == [f"rows.{i}.id" for i in range(MAX_PROBLEMS - 1)]
    assert all(p["type"] == "required" for p in problems[:-1])
    assert problems[-1] == {
        "field": "",
        "message": "More problems than can be shown",
        "type": "truncated",
    }


def test_unevaluated_properties_false_does_not_restrict_non_object_values() -> None:
    config = TriggerInputConfig(
        input_schema={"properties": {"v": {"unevaluatedProperties": False}}}
    )
    assert input_problems(config, {"v": []}) == []
    assert input_problems(config, {"v": "private-value"}) == []
    assert input_problems(config, {"v": {"extra": "private-value"}}) == [
        {
            "field": "v.extra",
            "message": "Additional properties are not allowed",
            "type": "unevaluatedProperties",
        }
    ]


def test_duplicate_allof_type_errors_render_one_diagnostic() -> None:
    config = TriggerInputConfig(
        input_schema={"properties": {"v": {"allOf": [{"type": "integer"}, {"type": "integer"}]}}}
    )
    assert input_problems(config, {"v": "private-value"}) == [
        {"field": "v", "message": "Must be of type integer", "type": "type"}
    ]
    assert "private-value" not in str(input_problems(config, {"v": "private-value"}))


def test_schema_valued_unevaluated_properties_survive_an_explicit_nested_dialect() -> None:
    config = TriggerInputConfig(
        input_schema={
            "properties": {
                "child": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "unevaluatedProperties": {"type": "integer"},
                }
            }
        }
    )
    assert input_problems(config, {"child": {"extra": "private-value"}}) == [
        {"field": "child.extra", "message": "Must be of type integer", "type": "type"}
    ]


def test_boolean_unevaluated_properties_survive_an_explicit_nested_dialect() -> None:
    config = TriggerInputConfig(
        input_schema={
            "properties": {
                "child": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "unevaluatedProperties": False,
                }
            }
        }
    )
    assert input_problems(config, {"child": {"extra": "private-value"}}) == [
        {
            "field": "child.extra",
            "message": "Additional properties are not allowed",
            "type": "unevaluatedProperties",
        }
    ]


def test_explicit_dialect_keeps_nested_reference_scope() -> None:
    schema: dict[str, JsonValue] = {
        "$defs": {"value": {"type": "integer"}},
        "properties": {
            "child": {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": "child",
                "$defs": {"value": {"type": "string"}},
                "properties": {"name": {"$ref": "#/$defs/value"}},
                "unevaluatedProperties": {"type": "integer"},
            }
        },
    }
    config = TriggerInputConfig(input_schema=schema)
    # `child.name` resolves to `child`'s own string definition, not the root's
    # integer one; the explicit dialect must not move the resolver context.
    assert input_problems(config, {"child": {"name": "ok", "extra": 1}}) == []
    assert [
        (p["field"], p["type"])
        for p in input_problems(config, {"child": {"name": 1, "extra": "x"}})
    ] == [
        ("child.name", "type"),
        ("child.extra", "type"),
    ]


def test_recursive_ref_to_root_with_an_explicit_dialect() -> None:
    config = TriggerInputConfig(
        input_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "properties": {"child": {"$ref": "#"}},
            "unevaluatedProperties": {"type": "integer"},
        }
    )
    assert input_problems(config, {"child": {"extra": "private-value"}}) == [
        {"field": "child.extra", "message": "Must be of type integer", "type": "type"}
    ]


def test_reference_to_a_schema_inside_an_annotation_reports_its_key() -> None:
    config = TriggerInputConfig(
        input_schema={
            "$defs": {
                "holder": {
                    "default": {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "unevaluatedProperties": False,
                    }
                }
            },
            "properties": {"value": {"$ref": "#/$defs/holder/default"}},
        }
    )
    assert input_problems(config, {"value": {"extra": "private-value"}}) == [
        {
            "field": "value.extra",
            "message": "Additional properties are not allowed",
            "type": "unevaluatedProperties",
        }
    ]


def test_an_annotation_schema_keeps_its_const_data_meaning() -> None:
    schema: dict[str, JsonValue] = {
        "$defs": {
            "holder": {
                "default": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "unevaluatedProperties": False,
                }
            }
        },
        "properties": {
            "as_schema": {"$ref": "#/$defs/holder/default"},
            "as_const": {
                "const": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "unevaluatedProperties": False,
                }
            },
        },
    }
    config = TriggerInputConfig(input_schema=schema)
    # The annotation object doubles as a `$ref` target and as literal `const`
    # data; its `$schema` key must survive so the const comparison stays exact.
    assert [
        (p["field"], p["type"])
        for p in input_problems(
            config,
            {
                "as_schema": {"extra": "private-value"},
                "as_const": {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "unevaluatedProperties": False,
                },
            },
        )
    ] == [("as_schema.extra", "unevaluatedProperties")]
    assert [
        p["field"]
        for p in input_problems(
            config, {"as_schema": {}, "as_const": {"unevaluatedProperties": False}}
        )
    ] == ["as_const"]


def test_nested_dynamic_refs_keep_resolver_context_with_an_explicit_dialect() -> None:
    config = TriggerInputConfig(
        input_schema={
            "$id": "https://example.com/tree",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$dynamicAnchor": "node",
            "properties": {"children": {"type": "array", "items": {"$dynamicRef": "#node"}}},
            "unevaluatedProperties": {"type": "integer"},
        }
    )
    # `$dynamicRef` resolves back to the root node (which carries the dialect);
    # the overridden keyword still names the offending key, not its parent.
    assert input_problems(config, {"children": [{"extra": "private-value"}]}) == [
        {"field": "children.0.extra", "message": "Must be of type integer", "type": "type"}
    ]


@pytest.mark.parametrize(
    "negated",
    [
        True,
        {},
        {"type": "object"},
        {"type": ["object", "null"], "description": "Any object"},
        {"allOf": [True, {"type": "object"}]},
        {"anyOf": [{"type": "array"}, {"type": "object"}]},
        {"oneOf": [{"type": "array"}, {"type": "object"}]},
        {"not": {"type": "array"}},
    ],
)
def test_negations_that_exclude_every_object_are_refused(negated: JsonValue) -> None:
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema={"not": negated})
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(
            input_schema={"$defs": {"excluded": negated}, "not": {"$ref": "#/$defs/excluded"}}
        )


@pytest.mark.parametrize(
    "negated",
    [
        False,
        {"type": "string"},
        {"required": ["blocked"]},
        {"$defs": {"value": {"required": ["blocked"]}}, "$ref": "#/not/$defs/value"},
        {"allOf": [{"required": ["blocked"]}]},
        {"anyOf": [{"required": ["blocked"]}, {"type": "array"}]},
        {"oneOf": [{"type": "object"}, {"type": "object"}]},
        {"oneOf": [{"type": "object"}, {"required": ["blocked"]}]},
        {"not": {"type": "object"}},
    ],
)
def test_negations_do_not_reject_usable_object_contracts(negated: JsonValue) -> None:
    config = TriggerInputConfig(input_schema={"not": negated})
    assert any(input_problems(config, payload) == [] for payload in ({}, {"blocked": True}))


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-30",
        "2026-02-29",
        "1900-02-29",
        "2100-02-29",
        "2026-04-31",
        "0000-01-01",
        "0000-02-29",
        "2026-13-01",
        "2026-00-01",
        "2026-01-00",
        "2026-01-32",
        "2026-1-01",
        "2026-01-01\n",
        "٢٠٢٦-01-01",
        "",
        "0001-01-01",
        "0004-02-29",
        "0400-02-29",
        "2000-02-29",
        "2024-02-29",
        "2026-02-28",
        "2026-04-30",
        "2026-12-31",
        "9999-12-31",
        None,
    ],
)
def test_discovered_date_schema_matches_admission_without_format_assertions(
    value: JsonValue,
) -> None:
    config = TriggerInputConfig.model_validate(
        {"fields": [{"name": "due", "type": "date", "required": False}]}
    )
    payload = {"due": value}
    discovered = Draft202012Validator(effective_input_schema(config))
    assert discovered.is_valid(payload) == (input_problems(config, payload) == [])


@pytest.mark.parametrize("branch", [{"type": "object"}, {}])
def test_overlapping_unrestricted_oneof_branches_cannot_publish(
    branch: dict[str, JsonValue],
) -> None:
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema={"oneOf": [branch, branch]})
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(
            input_schema={
                "$defs": {"branch": branch},
                "oneOf": [{"$ref": "#/$defs/branch"}, {"$ref": "#/$defs/branch"}],
            }
        )


def test_discovery_marks_legacy_integer_token_validation_without_relaxing_admission() -> None:
    config = TriggerInputConfig.model_validate(
        {"fields": [{"name": "count", "type": "integer", "required": False}]}
    )
    schema = effective_input_schema(config)
    assert schema["properties"]["count"]["anyOf"][0] == {
        "type": "integer",
        "x-agenticos-strict-integer": True,
    }
    # Ordinary JSON Schema cannot distinguish 1 from 1.0; the extension names
    # the additional token-level rule, and server admission remains authoritative.
    assert Draft202012Validator(schema).is_valid({"count": 1.0})
    assert input_problems(config, {"count": 1.0}) == [
        {"field": "count", "message": "Input should be a valid integer", "type": "int_type"}
    ]
    assert input_problems(config, {"count": 1}) == []
    assert input_problems(config, {"count": None}) == []
    assert input_problems(config, {}) == []


@pytest.mark.parametrize("referenced", [False, True])
def test_restrictive_duplicate_oneof_branches_cannot_publish(referenced: bool) -> None:
    branch: dict[str, JsonValue] = {"required": ["x"], "properties": {"x": {"type": "string"}}}
    other_order: dict[str, JsonValue] = {"properties": {"x": {"type": "string"}}, "required": ["x"]}
    schema: dict[str, JsonValue] = {"oneOf": [branch, other_order, {"type": "array"}]}
    if referenced:
        schema = {
            "$defs": {"branch": branch},
            "oneOf": [{"$ref": "#/$defs/branch"}, {"$ref": "#/$defs/branch"}],
        }
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema=schema)


def test_oneof_duplicates_preserve_an_independent_restrictive_branch() -> None:
    duplicated: dict[str, JsonValue] = {"required": ["x"]}
    config = TriggerInputConfig(
        input_schema={"oneOf": [duplicated, duplicated, {"required": ["y"]}]}
    )
    assert input_problems(config, {"y": True}) == []
    assert input_problems(config, {"x": True})
    assert input_problems(config, {"x": True, "y": True})


def test_form_catalog_schema_advertises_only_supported_input_contracts() -> None:
    schema = FormTriggerConfig.model_json_schema()
    assert schema["properties"]["input_schema"]["type"] == "null"
    validator = Draft202012Validator(schema)
    supported = {"fields": [{"name": "answer"}], "input_schema": None}
    assert validator.is_valid(supported)
    assert FormTriggerConfig.model_validate(supported).input_schema is None
    assert not validator.is_valid({**supported, "input_schema": {"type": "object"}})
    with pytest.raises(ValidationError, match="Input should be None"):
        FormTriggerConfig.model_validate({**supported, "input_schema": {"type": "object"}})


@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("metadata", [False, True])
def test_duplicate_restrictive_oneof_resolves_static_aliases(inline: bool, metadata: bool) -> None:
    branch: dict[str, JsonValue] = {"required": ["x"]}
    schema: dict[str, JsonValue] = {
        "$defs": {"left": branch, "right": {"$ref": "#/$defs/left"}},
        "oneOf": [branch if inline else {"$ref": "#/$defs/left"}, {"$ref": "#/$defs/right"}],
    }
    if metadata:
        schema["oneOf"][0]["title"] = "A"
        schema["oneOf"][1]["description"] = "B"
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema=schema)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ({"required": ["x", "y"]}, {"required": ["y", "x"]}),
        (
            {"type": ["object", "null"], "required": ["x", "y"]},
            {"type": ["null", "object"], "required": ["y", "x"]},
        ),
        ({"dependentRequired": {"x": ["y", "z"]}}, {"dependentRequired": {"x": ["z", "y"]}}),
        (
            {"properties": {"row": {"required": ["x", "y"]}}},
            {"properties": {"row": {"required": ["y", "x"]}}},
        ),
    ],
)
def test_reordered_name_sets_cannot_make_duplicate_oneof_branches_unique(
    left: dict[str, JsonValue], right: dict[str, JsonValue]
) -> None:
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema={"oneOf": [left, right]})


@pytest.mark.parametrize(
    ("left", "right", "payload"),
    [
        (
            {"const": {"required": ["x", "y"]}},
            {"const": {"required": ["y", "x"]}},
            {"required": ["x", "y"]},
        ),
        (
            {"enum": [{"required": ["x", "y"]}]},
            {"enum": [{"required": ["y", "x"]}]},
            {"required": ["x", "y"]},
        ),
        (
            {"properties": {"row": {"prefixItems": [{"type": "string"}, {"type": "integer"}]}}},
            {"properties": {"row": {"prefixItems": [{"type": "integer"}, {"type": "string"}]}}},
            {"row": ["x", 1]},
        ),
    ],
)
def test_schema_canonicalization_preserves_literal_and_positional_array_order(
    left: dict[str, JsonValue], right: dict[str, JsonValue], payload: dict[str, JsonValue]
) -> None:
    config = TriggerInputConfig(input_schema={"oneOf": [left, right]})
    assert input_problems(config, payload) == []


@pytest.mark.parametrize(
    "annotation",
    [
        "title",
        "description",
        "$comment",
        "default",
        "examples",
        "readOnly",
        "writeOnly",
        "deprecated",
    ],
)
def test_metadata_annotations_do_not_make_duplicate_branches_unique(annotation: str) -> None:
    values: tuple[JsonValue, JsonValue] = (
        (True, False)
        if annotation in {"readOnly", "writeOnly", "deprecated"}
        else (["A"], ["B"])
        if annotation == "examples"
        else ("A", "B")
    )
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(
            input_schema={
                "oneOf": [
                    {"required": ["x"], annotation: values[0]},
                    {"required": ["x"], annotation: values[1]},
                ]
            }
        )


def test_metadata_keys_inside_literal_values_remain_significant() -> None:
    config = TriggerInputConfig(
        input_schema={"oneOf": [{"const": {"title": "A"}}, {"const": {"title": "B"}}]}
    )
    assert input_problems(config, {"title": "A"}) == []
    assert input_problems(config, {"title": "B"}) == []


@pytest.mark.parametrize(
    "annotation", ["format", "contentEncoding", "contentMediaType", "contentSchema"]
)
def test_nonasserting_format_and_content_annotations_do_not_distinguish_branches(
    annotation: str,
) -> None:
    left: JsonValue = {"type": "string"} if annotation == "contentSchema" else "A"
    right: JsonValue = {"type": "number"} if annotation == "contentSchema" else "B"
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(
            input_schema={
                "oneOf": [
                    {"required": ["x"], annotation: left},
                    {"required": ["x"], annotation: right},
                ]
            }
        )


@pytest.mark.parametrize("keyword", ["allOf", "anyOf", "oneOf"])
def test_applicator_order_cannot_make_equivalent_branches_unique(keyword: str) -> None:
    left: dict[str, JsonValue] = {keyword: [{"required": ["x"]}, {"required": ["y"]}]}
    right: dict[str, JsonValue] = {keyword: [{"required": ["y"]}, {"required": ["x"]}]}
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema={"oneOf": [left, right]})


def test_enum_alternative_order_is_unordered_while_literal_array_values_keep_order() -> None:
    first: dict[str, JsonValue] = {"items": ["x", "y"]}
    second: dict[str, JsonValue] = {"items": ["y", "x"]}
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(
            input_schema={"oneOf": [{"enum": [first, second]}, {"enum": [second, first]}]}
        )
    config = TriggerInputConfig(input_schema={"oneOf": [{"enum": [first]}, {"enum": [second]}]})
    assert input_problems(config, first) == []
    assert input_problems(config, second) == []


@pytest.mark.parametrize("name", ["x" * 100000, "界" * 30000, "😀" * 24000])
def test_large_required_names_cannot_overflow_model_facing_refusals(name: str) -> None:
    schema: dict[str, JsonValue] = {"required": [name]}
    check_input_schema(schema)
    problems = schema_input_problems(schema, {})
    assert problems == [
        {"field": "", "message": "More problems than can be shown", "type": "truncated"}
    ]
    assert len(json.dumps(problems, ensure_ascii=False).encode()) < MAX_DIAGNOSTIC_BYTES
    refusal = WorkflowRunInputInvalidError(problems=problems)
    assert len(str(refusal.details).encode()) < MAX_DISCOVERY_BYTES
    assert len(json.dumps({"error": refusal.details}).encode()) < MAX_DISCOVERY_BYTES


def test_byte_truncation_keeps_useful_errors_before_the_summary() -> None:
    problems = schema_input_problems({"required": ["first", "second", "x" * 100000, "later"]}, {})
    assert [problem["field"] for problem in problems] == ["first", "second", ""]
    assert problems[-1]["type"] == "truncated"


def test_diagnostic_byte_budget_uses_utf8_and_reserves_its_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema: dict[str, JsonValue] = {"required": ["界"]}
    problem = {"field": "界", "message": "Field required", "type": "required"}
    marker = {"field": "", "message": "More problems than can be shown", "type": "truncated"}
    size = len(json.dumps([problem, marker], ensure_ascii=False, separators=(",", ":")).encode())
    monkeypatch.setattr(input_schema, "MAX_DIAGNOSTIC_BYTES", size)
    assert schema_input_problems(schema, {}) == [problem]
    monkeypatch.setattr(input_schema, "MAX_DIAGNOSTIC_BYTES", size - 1)
    assert schema_input_problems(schema, {}) == [marker]


@pytest.mark.parametrize(
    "annotation",
    [
        {"$ref": "#"},
        {"$ref": "#/contentSchema"},
        {"contentSchema": {"$ref": "#/contentSchema"}},
        True,
        False,
    ],
)
def test_nonasserting_content_schema_cycles_do_not_refuse_object_contracts(
    annotation: JsonValue,
) -> None:
    config = TriggerInputConfig(input_schema={"type": "object", "contentSchema": annotation})
    assert input_problems(config, {"anything": True}) == []


def test_a_real_assertion_entering_an_annotation_cycle_is_still_refused() -> None:
    with pytest.raises(ValidationError, match="reference cycle"):
        TriggerInputConfig(
            input_schema={"contentSchema": {"$ref": "#/contentSchema"}, "$ref": "#/contentSchema"}
        )


@pytest.mark.parametrize(
    ("reference", "message"),
    [
        ("https://example.com/schema", "within the supplied document"),
        ("#/$defs/missing", "unresolved local reference"),
    ],
)
def test_nonasserting_content_schema_references_still_require_local_resolution(
    reference: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        TriggerInputConfig(input_schema={"contentSchema": {"$ref": reference}})


@pytest.mark.parametrize("keyword", ["const", "enum"])
def test_integral_float_literals_do_not_make_duplicate_object_branches_unique(keyword: str) -> None:
    left: dict[str, JsonValue] = {"rows": [{"x": 1, "zero": 0}]}
    right: dict[str, JsonValue] = {"rows": [{"x": 1.0, "zero": -0.0}]}
    schema: dict[str, JsonValue] = {
        "oneOf": [
            {keyword: [left] if keyword == "enum" else left},
            {keyword: [right] if keyword == "enum" else right},
        ]
    }
    original = deepcopy(schema)
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema=schema)
    assert schema == original
    assert isinstance(right["rows"][0]["x"], float)
    accepted = TriggerInputConfig(input_schema={"const": right})
    assert isinstance(effective_input_schema(accepted)["const"]["rows"][0]["x"], float)


@pytest.mark.parametrize(
    ("left", "right"), [(True, 1), (False, 0), (1.5, 2.5), ([1, 2], [2.0, 1.0])]
)
def test_literal_canonicalization_preserves_boolean_fractional_and_positional_differences(
    left: JsonValue, right: JsonValue
) -> None:
    config = TriggerInputConfig(
        input_schema={"oneOf": [{"const": {"x": left}}, {"const": {"x": right}}]}
    )
    assert input_problems(config, {"x": left}) == []
    assert input_problems(config, {"x": right}) == []


@pytest.mark.parametrize("pattern", ["(" * 600 + "a" + ")" * 600, "a{4294967296}"])
def test_regex_compiler_limits_are_controlled_configuration_refusals(pattern: str) -> None:
    with pytest.raises(ValidationError, match="validator complexity limits"):
        TriggerInputConfig(input_schema={"properties": {"name": {"pattern": pattern}}})


@pytest.mark.parametrize("keyword", ["x-note", "customValidation", "minimumLength"])
def test_unsupported_keywords_do_not_make_equivalent_branches_unique(keyword: str) -> None:
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(
            input_schema={
                "oneOf": [
                    {"required": ["x"], keyword: "A"},
                    {"required": ["x"], keyword: "B"},
                ]
            }
        )


def test_unsupported_keywords_do_not_restrict_universal_object_branches() -> None:
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema={"not": {"type": "object", "x-note": "A"}})


def test_unsupported_keyword_names_inside_literal_objects_remain_significant() -> None:
    config = TriggerInputConfig(
        input_schema={"oneOf": [{"const": {"x-note": "A"}}, {"const": {"x-note": "B"}}]}
    )
    assert input_problems(config, {"x-note": "A"}) == []
    assert input_problems(config, {"x-note": "B"}) == []


@pytest.mark.parametrize("keyword", ["allOf", "anyOf"])
def test_idempotent_applicator_duplicates_do_not_distinguish_outer_branches(keyword: str) -> None:
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(
            input_schema={
                "oneOf": [
                    {keyword: [{"required": ["x"]}]},
                    {keyword: [{"required": ["x"]}, {"required": ["x"]}]},
                ]
            }
        )


def test_oneof_duplicate_multiplicity_remains_significant() -> None:
    config = TriggerInputConfig(
        input_schema={
            "oneOf": [
                {"oneOf": [{"required": ["x"]}, {"required": ["y"]}]},
                {
                    "oneOf": [
                        {"required": ["x"]},
                        {"required": ["x"]},
                        {"required": ["y"]},
                    ]
                },
            ]
        }
    )
    assert input_problems(config, {"x": 1}) == []


@pytest.mark.parametrize("nested_resource", [False, True])
def test_empty_reference_recurses_within_the_current_resource(nested_resource: bool) -> None:
    node: dict[str, JsonValue] = {
        "$id": "https://example.com/node",
        "type": "object",
        "properties": {"label": {"type": "string"}, "child": {"$ref": ""}},
    }
    schema: dict[str, JsonValue] = {"properties": {"node": node}} if nested_resource else node
    config = TriggerInputConfig(input_schema=schema)
    valid: dict[str, JsonValue] = {"child": {"child": {"label": "leaf"}}}
    invalid: dict[str, JsonValue] = {"child": {"label": False}}
    assert input_problems(config, {"node": valid} if nested_resource else valid) == []
    problems = input_problems(config, {"node": invalid} if nested_resource else invalid)
    assert problems[0]["field"] == ("node.child.label" if nested_resource else "child.label")


def test_empty_reference_to_the_same_value_still_refuses_cycles() -> None:
    with pytest.raises(ValidationError, match="reference cycle"):
        TriggerInputConfig(input_schema={"$ref": ""})


def test_references_into_extension_keywords_keep_their_assertions() -> None:
    config = TriggerInputConfig(
        input_schema={"x-contract": {"required": ["x"]}, "$ref": "#/x-contract"}
    )
    assert input_problems(config, {"x": 1}) == []
    assert input_problems(config, {})[0]["field"] == "x"


@pytest.mark.parametrize("required", [False, True])
def test_scalar_and_singleton_type_arrays_do_not_distinguish_branches(required: bool) -> None:
    left: dict[str, JsonValue] = {"type": "object"}
    right: dict[str, JsonValue] = {"type": ["object"]}
    if required:
        left["required"] = ["x"]
        right["required"] = ["x"]
    with pytest.raises(ValidationError, match="must allow a JSON object"):
        TriggerInputConfig(input_schema={"oneOf": [left, right]})


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
@pytest.mark.parametrize("reference", ["https://example.com/node", "node", "/node"])
def test_resource_uri_references_recurse_without_external_retrieval(
    keyword: str, reference: str
) -> None:
    config = TriggerInputConfig(
        input_schema={
            "$id": "https://example.com/node",
            "type": "object",
            "properties": {"label": {"type": "string"}, "child": {keyword: reference}},
        }
    )
    assert input_problems(config, {"child": {"child": {"label": "leaf"}}}) == []
    assert input_problems(config, {"child": {"label": 7}})[0]["field"] == "child.label"


def test_resource_uri_references_can_resolve_supplied_subresources() -> None:
    config = TriggerInputConfig(
        input_schema={
            "$id": "https://example.com/root",
            "$defs": {"part": {"$id": "part", "type": "string"}},
            "properties": {"value": {"$ref": "part"}},
        }
    )
    assert input_problems(config, {"value": "local"}) == []
    assert input_problems(config, {"value": 3})[0]["field"] == "value"


def test_resource_uri_references_still_refuse_same_value_cycles() -> None:
    with pytest.raises(ValidationError, match="reference cycle"):
        TriggerInputConfig(
            input_schema={"$id": "https://example.com/root", "$ref": "https://example.com/root"}
        )


def test_sibling_resource_references_index_the_document_once_per_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = 128
    schema: dict[str, JsonValue] = {
        "$id": "https://example.com/root",
        "$defs": {f"part{i}": {"$id": f"part{i}", "type": "object"} for i in range(count)},
        "allOf": [{"$ref": f"part{i}"} for i in range(count)],
    }
    visits = 0
    original = Resource.subresources

    def subresources(resource: Resource[Schema]) -> Iterator[Resource[Schema]]:
        nonlocal visits
        visits += 1
        yield from original(resource)

    monkeypatch.setattr(Resource, "subresources", subresources)
    check_input_schema(schema)
    assert visits <= count * 4
    visits = 0
    assert schema_input_problems(schema, {}) == []
    assert visits <= count * 4


@pytest.mark.parametrize(
    "schema",
    [
        {"if": False, "then": {"$ref": "#"}},
        {"if": True, "else": {"$ref": "#"}},
        {"then": {"$ref": "#"}},
        {"else": {"$ref": "#"}},
    ],
)
def test_statically_inactive_conditional_branches_do_not_create_cycles(
    schema: dict[str, JsonValue],
) -> None:
    config = TriggerInputConfig(input_schema=schema)
    assert input_problems(config, {}) == []


@pytest.mark.parametrize(
    "schema",
    [
        {"if": True, "then": {"$ref": "#"}},
        {"if": False, "else": {"$ref": "#"}},
        {"then": {"$ref": "#"}, "$ref": "#/then"},
    ],
)
def test_executed_conditional_references_still_refuse_same_value_cycles(
    schema: dict[str, JsonValue],
) -> None:
    with pytest.raises(ValidationError, match="reference cycle"):
        TriggerInputConfig(input_schema=schema)


def test_inactive_conditional_branches_still_require_supplied_references() -> None:
    with pytest.raises(ValidationError, match="within the supplied document"):
        TriggerInputConfig(input_schema={"if": False, "then": {"$ref": "https://outside.test"}})


@pytest.mark.parametrize("order", list(permutations(("base", "wrapper", "use"))))
def test_rebound_dynamic_anchor_cycles_are_refused_in_every_definition_order(
    order: tuple[str, ...],
) -> None:
    definitions: dict[str, JsonValue] = {
        "base": {"$id": "base", "$dynamicAnchor": "x"},
        "wrapper": {"$id": "wrapper", "$dynamicAnchor": "x", "$ref": "use"},
        "use": {"$id": "use", "$dynamicRef": "base#x"},
    }
    with pytest.raises(ValidationError, match="reference cycle"):
        TriggerInputConfig(
            input_schema={
                "$id": "https://example.com/root",
                "$defs": {name: definitions[name] for name in order},
                "$ref": "wrapper",
            }
        )


def test_rebound_dynamic_anchors_can_recurse_through_child_input() -> None:
    config = TriggerInputConfig(
        input_schema={
            "$id": "https://example.com/root",
            "$defs": {
                "base": {
                    "$id": "base",
                    "$dynamicAnchor": "x",
                    "type": "object",
                    "properties": {"child": {"$dynamicRef": "base#x"}},
                },
                "wrapper": {
                    "$id": "wrapper",
                    "$dynamicAnchor": "x",
                    "$ref": "base",
                    "required": ["tag"],
                },
            },
            "$ref": "wrapper",
        }
    )
    assert input_problems(config, {"tag": "root", "child": {"tag": "child"}}) == []
    assert input_problems(config, {"tag": "root", "child": {}})[0]["field"] == "child.tag"


@pytest.mark.parametrize("limit", ["MAX_DYNAMIC_CONTEXTS", "MAX_DYNAMIC_SCOPE"])
def test_dynamic_reference_analysis_has_explicit_context_limits(
    limit: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(input_schema, limit, 0)
    with pytest.raises(ValidationError, match="dynamic reference context limits"):
        TriggerInputConfig(
            input_schema={
                "$id": "https://example.com/root",
                "properties": {"child": {"$dynamicRef": "https://example.com/root"}},
            }
        )


def test_dynamic_rebinding_can_enter_an_otherwise_nonasserting_schema() -> None:
    config = TriggerInputConfig(
        input_schema={
            "$id": "https://example.com/root",
            "$defs": {
                "base": {"$id": "base", "$dynamicAnchor": "x"},
                "wrapper": {
                    "$id": "wrapper",
                    "$ref": "use",
                    "contentSchema": {"$dynamicAnchor": "x", "allOf": [True]},
                },
                "use": {"$id": "use", "$dynamicRef": "base#x"},
            },
            "$ref": "wrapper",
        }
    )
    assert input_problems(config, {}) == []


def test_context_cycle_analysis_reports_unresolved_references() -> None:
    with pytest.raises(ValueError, match="unresolved local reference"):
        input_schema._check_dynamic_cycles({"$dynamicRef": "https://outside.test"}, {})
