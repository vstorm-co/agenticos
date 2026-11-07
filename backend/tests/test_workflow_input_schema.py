"""Portable trigger contracts retain JSON Schema semantics at admission and discovery."""

from copy import deepcopy

import pytest
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import JsonValue, ValidationError

from app.workflows.contracts.input_schema import (
    MAX_NESTING,
    MAX_PROBLEMS,
    _error_paths,
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
