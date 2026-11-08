"""Portable trigger input contracts, checked without retrieving external schemas."""

import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING, Any, cast

from jsonschema import Draft202012Validator
from jsonschema._utils import find_evaluated_property_keys_by_schema
from jsonschema.exceptions import SchemaError, ValidationError
from jsonschema.validators import extend
from pydantic import JsonValue
from referencing import Registry, Resource
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012, Schema

from app.workflows.contracts.payload import PayloadTooLarge, json_byte_size

if TYPE_CHECKING:
    from referencing._core import Resolver

type InputSchema = dict[str, JsonValue]

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
MAX_NESTING = 64
MAX_PROBLEMS = 100
MAX_SCHEMA_BYTES = 262_144

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
_OBJECT_UNRESTRICTED_KEYS = frozenset(
    {
        "$schema",
        "$id",
        "$anchor",
        "$dynamicAnchor",
        "$comment",
        "$defs",
        "definitions",
        "title",
        "description",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "type",
        "$ref",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
    }
)


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


def _unevaluated_properties(
    validator: Any,
    unevaluated_properties: Schema,
    instance: JsonValue,
    schema: Mapping[str, JsonValue],
) -> Iterator[ValidationError]:
    """Report each unevaluated property key on its own path.

    `jsonschema` aggregates every unevaluated key into one error at the parent
    object's path, so a schema-valued rule cannot say which key had the wrong
    type and `false` cannot name the offending key. Overriding the keyword
    keeps the library's own evaluated-key computation while yielding one error
    per key. The private `find_evaluated_property_keys_by_schema` helper is the
    exact one the library's keyword uses, so `properties`, `patternProperties`,
    `$ref`, `allOf`/`anyOf`/`oneOf` and `if`/`then`/`else` stay Draft 2020-12
    exact; the resolver context for local references and nested `$id` is the
    one the keyword is invoked with, and the lockfile pins its version.
    """
    if not validator.is_type(instance, "object") or not isinstance(instance, dict):
        return
    evaluated_keys = set(find_evaluated_property_keys_by_schema(validator, instance, schema))
    for key in instance:
        if key in evaluated_keys:
            continue
        if unevaluated_properties is False:
            yield ValidationError("Unevaluated property", path=[key])
        else:
            yield from validator.descend(
                instance[key],
                unevaluated_properties,
                path=key,
                schema_path=key,
            )


# `Any` above is the boundary with jsonschema's keyword-validator protocol, whose
# concrete class is created here (and whose `descend`/`_resolver` the protocol omits).
_InputValidator = extend(
    Draft202012Validator,
    {"unevaluatedProperties": _unevaluated_properties},
)

# jsonschema's `evolve` forwards every attrs init field from `self` into the new
# validator; this is the same (attr_name, init_alias) list its `evolve_fields`
# builds. `_ref_resolver` (alias `resolver`) is the deprecated legacy field and
# stays `None`; `_registry` (alias `registry`) and `_resolver` (alias `_resolver`)
# carry the local-reference resolver context. The names are pinned by the lockfile.
_EVOLVE_FIELDS = (
    ("schema", "schema"),
    ("_ref_resolver", "resolver"),
    ("format_checker", "format_checker"),
    ("_registry", "registry"),
    ("_resolver", "_resolver"),
)


def _evolve(self: Any, **changes: Any) -> Any:
    """Rebuild `_InputValidator` regardless of any `$schema` a subschema declares.

    The base `evolve` consults `validator_for`, which returns the globally
    registered 2020-12 validator for a schema that carries `$schema` — silently
    dropping this module's `unevaluatedProperties` override for that subschema.
    `check_input_schema` has already fixed the whole document to Draft 2020-12,
    so `evolve` may always reconstruct `_InputValidator`, forwarding the same
    schema/resolver/format-checker/registry/resolver fields the base `evolve`
    does. This preserves original schema contents (`const`/`default`/`enum`
    annotations included) and never mutates the globally registered validators.
    """
    changes.setdefault("schema", self.schema)
    for attr_name, init_name in _EVOLVE_FIELDS:
        if init_name not in changes:
            changes[init_name] = getattr(self, attr_name)
    return _InputValidator(**changes)


_InputValidator.evolve = _evolve


def _checked_schema(contents: Schema) -> Mapping[str, JsonValue] | None:
    if isinstance(contents, bool):
        return None
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
    return contents


def _object_possible(
    schema: Mapping[str, JsonValue] | bool,
    possible: Mapping[int, bool],
    reference: int | None,
    unrestricted: Mapping[int, bool],
    identities: Mapping[int, str],
) -> bool:
    """Conservative object compatibility from already classified dependencies.

    Type/value restrictions, static references and compositions can prove that
    objects are excluded. Other constraints remain unknown; this is not a
    schema satisfiability check, and dynamic references retain their runtime scope.
    """
    if isinstance(schema, bool):
        return schema
    declared = schema.get("type")
    if isinstance(declared, str):
        if declared != "object":
            return False
    elif isinstance(declared, list) and "object" not in declared:
        return False
    if "const" in schema and not isinstance(schema["const"], dict):
        return False
    choices = schema.get("enum")
    if isinstance(choices, list) and not any(isinstance(choice, dict) for choice in choices):
        return False
    if reference is not None and not possible[reference]:
        return False
    negated = schema.get("not")
    if isinstance(negated, (dict, bool)) and unrestricted[id(negated)]:
        return False
    for keyword in ("allOf", "anyOf", "oneOf"):
        alternatives = schema.get(keyword)
        if isinstance(alternatives, list):
            compatibility = (possible[id(child)] for child in alternatives)
            if keyword == "allOf":
                if not all(compatibility):
                    return False
            elif not any(compatibility) or (
                keyword == "oneOf" and sum(unrestricted[id(child)] for child in alternatives) > 1
            ):
                return False
            elif keyword == "oneOf":
                # Repeated branches can never be the sole match. Keep a
                # restrictive singleton as a possible witness instead of
                # rejecting every schema that happens to contain duplicates.
                fingerprints = [identities[id(child)] for child in alternatives]
                counts = Counter(fingerprints)
                if not any(
                    possible[id(child)] and counts[fingerprint] == 1
                    for child, fingerprint in zip(alternatives, fingerprints, strict=True)
                ):
                    return False
    return True


def _canonical_schema(schema: JsonValue) -> JsonValue:
    """Normalize unordered names, without treating literal data as schemas.

    `required`, type unions and dependent-required names have set semantics.
    The document has already passed its meta-schema. Literal arrays and
    positional schema arrays retain their original order,
    including data that a local JSON Pointer may also use as a schema target.
    """
    if not isinstance(schema, dict):
        return schema
    result = dict(schema)
    for keyword, value in schema.items():
        if keyword in {"required", "type"} and isinstance(value, list):
            result[keyword] = sorted(value, key=lambda item: json.dumps(item, sort_keys=True))
        elif keyword == "dependentRequired" and isinstance(value, dict):
            result[keyword] = {
                name: sorted(
                    cast("list[JsonValue]", names),
                    key=lambda item: json.dumps(item, sort_keys=True),
                )
                for name, names in value.items()
            }
        elif keyword in _SAME_VALUE | _CHILD_VALUE:
            result[keyword] = _canonical_schema(value)
        elif keyword in _SCHEMA_MAPS and isinstance(value, dict):
            result[keyword] = {name: _canonical_schema(child) for name, child in value.items()}
        elif keyword in _SCHEMA_LISTS and isinstance(value, list):
            result[keyword] = [_canonical_schema(child) for child in value]
    return result


def _every_object_matches(
    schema: Mapping[str, JsonValue] | bool,
    possible: Mapping[int, bool],
    unrestricted: Mapping[int, bool],
    reference: int | None,
    identities: Mapping[int, str],
) -> bool:
    """Prove universal object acceptance only for known non-restricting keywords.

    An unknown or value-specific constraint stays undecided, so its negation
    cannot accidentally reject a usable contract. Dependencies are classified
    once in topological order, including references and nested negations.
    """
    if isinstance(schema, bool):
        return schema
    if schema.keys() - _OBJECT_UNRESTRICTED_KEYS:
        return False
    if not _object_possible(schema, possible, reference, unrestricted, identities):
        return False
    if reference is not None and not unrestricted[reference]:
        return False
    negated = schema.get("not")
    if isinstance(negated, (dict, bool)) and possible[id(negated)]:
        return False
    for keyword in ("allOf", "anyOf", "oneOf"):
        alternatives = schema.get(keyword)
        if not isinstance(alternatives, list):
            continue
        universal = [unrestricted[id(child)] for child in alternatives]
        if keyword == "allOf":
            if not all(universal):
                return False
        elif keyword == "anyOf":
            if not any(universal):
                return False
        elif sum(universal) != 1 or any(
            possible[id(child)]
            for child, accepts_all in zip(alternatives, universal, strict=True)
            if not accepts_all
        ):
            return False
    return True


def check_input_schema(schema: InputSchema) -> None:
    """Refuse invalid dialects, unresolved/external references and endless ref loops.

    References may use JSON Pointers or anchors within the supplied document.
    Recursive object/array definitions are supported; a reference cycle that
    evaluates the same input value indefinitely is refused before publication.
    Root constraints that explicitly exclude JSON objects are refused through
    a conservative compatibility check, without proving arbitrary satisfiability.
    """
    if _too_deep(schema):
        raise ValueError("Input schema exceeds the maximum nesting depth")
    try:
        json_byte_size(schema, limit=MAX_SCHEMA_BYTES)
    except PayloadTooLarge:
        raise ValueError(f"Input schema may take at most {MAX_SCHEMA_BYTES} bytes") from None
    # Registry construction reads $id immediately, before reference traversal.
    _checked_schema(schema)
    checked: dict[int, Mapping[str, JsonValue] | bool] = {}
    connections: dict[int, set[int]] = {}
    references: dict[int, int] = {}
    resource = DRAFT202012.create_resource(schema)
    resolver = Registry().resolver_with_root(resource)
    pending: list[tuple[Resource[Schema], Resolver[Schema]]] = [(resource, resolver)]
    while pending:
        current, current_resolver = pending.pop()
        contents = current.contents
        key = id(contents)
        if key in checked:
            continue
        connections[key] = set()
        contents = _checked_schema(contents)
        checked[key] = contents if contents is not None else bool(current.contents)
        if contents is None:
            continue
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
            if keyword == "$ref":
                references[key] = id(resolved.contents)
            pending.append((DRAFT202012.create_resource(resolved.contents), resolved.resolver))
        for child, same_value in _subschemas(contents):
            child_resource = DRAFT202012.create_resource(child)
            if same_value:
                connections[key].add(id(child))
            pending.append((child_resource, current_resolver.in_subresource(child_resource)))
    possible: dict[int, bool] = {}
    unrestricted: dict[int, bool] = {}
    identities: dict[int, str] = {}
    try:
        for key in TopologicalSorter(connections).static_order():
            contents = checked[key]
            reference = references.get(key)
            # A static reference with no siblings has exactly its target's
            # meaning. Reuse its identity without expanding reference paths.
            identities[key] = (
                identities[reference]
                if isinstance(contents, Mapping) and len(contents) == 1 and reference is not None
                else json.dumps(
                    _canonical_schema(
                        dict(contents) if isinstance(contents, Mapping) else contents
                    ),
                    sort_keys=True,
                )
            )
            possible[key] = _object_possible(
                contents, possible, reference, unrestricted, identities
            )
            unrestricted[key] = _every_object_matches(
                contents, possible, unrestricted, reference, identities
            )
    except CycleError:
        raise ValueError(
            "Input schema contains a reference cycle that does not descend into input"
        ) from None
    if not possible[id(schema)]:
        raise ValueError("Workflow input schema must allow a JSON object")


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


def _error_paths(
    error: ValidationError,
    seen_required: set[tuple[tuple[str | int, ...], tuple[str, ...]]],
) -> Iterator[tuple[str | int, ...]]:
    path = tuple(error.absolute_path)
    if error.validator == "required":
        names = tuple(cast("list[str]", error.validator_value))
        constraint = (path, names)
        if constraint not in seen_required:
            seen_required.add(constraint)
            for name in names:
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


def _specific_errors(error: ValidationError) -> Iterator[ValidationError]:
    """Expose a union branch's field errors when its input type is unambiguous."""
    if error.validator not in {"anyOf", "oneOf"} or not error.context:
        yield error
        return
    branches: dict[str | int, list[ValidationError]] = {}
    wrong_type: set[str | int] = set()
    for child in error.context:
        branch = child.schema_path[0]
        branches.setdefault(branch, []).append(child)
        if child.validator == "type" and not child.path:
            wrong_type.add(branch)
    candidates = [errors for branch, errors in branches.items() if branch not in wrong_type]
    if len(candidates) != 1:
        yield error
        return
    for child in candidates[0]:
        yield from _specific_errors(child)


def schema_input_problems(
    schema: InputSchema, run_input: dict[str, JsonValue]
) -> list[dict[str, str]]:
    """Field paths and safe explanations, without quoting the submitted values.

    The same Draft 2020-12 contract used at publication governs admission.
    An empty registry ensures even a mutated schema cannot cause network I/O.
    At most `MAX_PROBLEMS` problems are rendered; when more exist the final
    entry is a value-free truncation summary.
    """
    if _too_deep(run_input):
        return [
            {
                "field": "",
                "message": "Input exceeds the maximum nesting depth",
                "type": "max_depth",
            }
        ]
    problems: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    seen_required: set[tuple[tuple[str | int, ...], tuple[str, ...]]] = set()
    truncated = False
    try:
        for error in _InputValidator(schema, registry=Registry()).iter_errors(run_input):
            for specific in _specific_errors(error):
                for path in _error_paths(specific, seen_required):
                    problem = {
                        "field": ".".join(str(part) for part in path),
                        "message": _message(specific),
                        "type": str(specific.validator or "schema"),
                    }
                    key = (problem["field"], problem["message"], problem["type"])
                    if key in seen:
                        continue
                    if len(problems) >= MAX_PROBLEMS - 1:
                        truncated = True
                        break
                    seen.add(key)
                    problems.append(problem)
                if truncated:
                    break
            if truncated:
                break
    except RecursionError:
        return [
            {
                "field": "",
                "message": "Input exceeds the schema validation nesting limit",
                "type": "max_depth",
            }
        ]
    if truncated:
        problems.append(
            {
                "field": "",
                "message": "More problems than can be shown",
                "type": "truncated",
            }
        )
    return problems
