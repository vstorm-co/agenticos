"""Portable trigger input contracts, checked without retrieving external schemas."""

import re
from collections.abc import Iterator, Mapping
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import JsonValue
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012, Schema

if TYPE_CHECKING:
    from referencing._core import Resolver

type InputSchema = dict[str, JsonValue]

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
MAX_NESTING = 64

_SAME_VALUE = frozenset({"not", "if", "then", "else", "contentSchema"})
_CHILD_VALUE = frozenset(
    {
        "items",
        "contains",
        "additionalProperties",
        "unevaluatedProperties",
        "propertyNames",
        "unevaluatedItems",
    }
)
_SCHEMA_MAPS = frozenset(
    {"$defs", "definitions", "dependentSchemas", "properties", "patternProperties"}
)
_SCHEMA_LISTS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})


def _too_deep(value: JsonValue) -> bool:
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if depth > MAX_NESTING:
            return True
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)
    return False


def _subschemas(
    schema: Mapping[str, JsonValue],
) -> Iterator[tuple[dict[str, JsonValue] | bool, bool]]:
    """Subschemas and whether they evaluate the same input value as their parent.

    The parent already passed the Draft meta-schema, including child types.
    """
    for keyword, value in schema.items():
        if keyword in _SAME_VALUE | _CHILD_VALUE and isinstance(value, (dict, bool)):
            yield value, keyword in _SAME_VALUE
        elif keyword in _SCHEMA_MAPS and isinstance(value, dict):
            for child in value.values():
                yield cast("dict[str, JsonValue] | bool", child), keyword == "dependentSchemas"
        elif keyword in _SCHEMA_LISTS and isinstance(value, list):
            for child in value:
                yield cast("dict[str, JsonValue] | bool", child), keyword != "prefixItems"


def check_input_schema(schema: InputSchema) -> None:
    """Refuse invalid dialects, unresolved/external references and endless ref loops.

    References may use JSON Pointers or anchors within the supplied document.
    Recursive object/array definitions are supported; a reference cycle that
    evaluates the same input value indefinitely is refused before publication.
    """
    if _too_deep(schema):
        raise ValueError("Input schema exceeds the maximum nesting depth")
    visited: set[int] = set()
    connections: dict[int, set[int]] = {}
    resource = DRAFT202012.create_resource(schema)
    resolver = Registry().resolver_with_root(resource)
    pending: list[tuple[Resource[Schema], Resolver[Schema]]] = [(resource, resolver)]
    while pending:
        current, current_resolver = pending.pop()
        contents = current.contents
        key = id(contents)
        if key in visited:
            continue
        visited.add(key)
        connections[key] = set()
        if isinstance(contents, bool):
            continue
        if not isinstance(contents, Mapping):
            # Pydantic turns ValueError into a config refusal; TypeError would escape as a server error.
            raise ValueError("Input schema reference must point to a schema object or boolean")  # noqa: TRY004
        dialect = contents.get("$schema", DRAFT_2020_12)
        if not isinstance(dialect, str) or dialect not in {DRAFT_2020_12, DRAFT_2020_12 + "#"}:
            raise ValueError("Input schema must use JSON Schema Draft 2020-12")
        try:
            Draft202012Validator.check_schema(contents)
        except SchemaError as exc:
            path = "/".join(str(part) for part in exc.absolute_path)
            raise ValueError(f"Invalid Draft 2020-12 input schema at /{path}") from None
        for keyword in ("$ref", "$dynamicRef"):
            reference = contents.get(keyword)
            if not isinstance(reference, str):
                continue
            if not reference.startswith("#"):
                raise ValueError("Input schema references must stay within the supplied document")
            try:
                resolved = current_resolver.lookup(reference)
            except Unresolvable:
                raise ValueError("Input schema contains an unresolved local reference") from None
            connections[key].add(id(resolved.contents))
            pending.append((DRAFT202012.create_resource(resolved.contents), resolved.resolver))
        for child, same_value in _subschemas(contents):
            child_resource = DRAFT202012.create_resource(child)
            if same_value:
                connections[key].add(id(child))
            pending.append((child_resource, current_resolver.in_subresource(child_resource)))
    try:
        TopologicalSorter(connections).prepare()
    except CycleError:
        raise ValueError(
            "Input schema contains a reference cycle that does not descend into input"
        ) from None


def _message(error: ValidationError) -> str:
    match error.validator:
        case "type":
            expected = error.validator_value
            names = ", ".join(expected) if isinstance(expected, list) else str(expected)
            return f"Must be of type {names}"
        case "enum" | "const":
            return "Must match an allowed value"
        case "required":
            return "Field required"
        case "additionalProperties" | "unevaluatedProperties":
            return "Additional properties are not allowed"
        case "minLength":
            return f"Must contain at least {error.validator_value} characters"
        case "maxLength":
            return f"Must contain at most {error.validator_value} characters"
        case "minItems":
            return f"Must contain at least {error.validator_value} items"
        case "maxItems":
            return f"Must contain at most {error.validator_value} items"
        case "minimum" | "exclusiveMinimum" | "maximum" | "exclusiveMaximum":
            return "Number is outside the allowed range"
        case "pattern":
            return "Must match the required pattern"
        case _:
            return f"Must satisfy the {error.validator or 'schema'} constraint"


def _error_paths(error: ValidationError) -> Iterator[tuple[str | int, ...]]:
    path = tuple(error.absolute_path)
    if error.validator == "required":
        for name in error.validator_value:
            if name not in error.instance:
                yield (*path, name)
    elif (
        error.validator == "additionalProperties"
        and error.validator_value is False
        and isinstance(error.schema, Mapping)
    ):
        properties = error.schema.get("properties", {})
        patterns = error.schema.get("patternProperties", {})
        for name in error.instance:
            if name not in properties and not any(re.search(pattern, name) for pattern in patterns):
                yield (*path, name)
    else:
        yield path


def schema_input_problems(
    schema: InputSchema, run_input: dict[str, JsonValue]
) -> list[dict[str, str]]:
    """Field paths and safe explanations, without quoting the submitted values.

    The same Draft 2020-12 contract used at publication governs admission.
    An empty registry ensures even a mutated schema cannot cause network I/O.
    """
    if _too_deep(run_input):
        return [
            {
                "field": "$",
                "message": "Input exceeds the maximum nesting depth",
                "type": "max_depth",
            }
        ]
    problems: list[dict[str, str]] = []
    try:
        for error in Draft202012Validator(schema, registry=Registry()).iter_errors(run_input):
            for path in _error_paths(error):
                problem = {
                    "field": ".".join(str(part) for part in path) or "$",
                    "message": _message(error),
                    "type": str(error.validator or "schema"),
                }
                if problem not in problems:
                    problems.append(problem)
    except RecursionError:
        return [
            {
                "field": "$",
                "message": "Input exceeds the schema validation nesting limit",
                "type": "max_depth",
            }
        ]
    return problems
