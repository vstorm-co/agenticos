"""Standalone, bounded JSONSchema validator run as a subprocess.

Spawned by `tool_schema_validation.py` so a pathological `pattern` - or any
schema that hangs `jsonschema` - costs a killed process, never the parent's
event loop. Imports only the standard library plus `jsonschema` and
`referencing`, never `app`, and speaks one JSON request/response over
stdin/stdout. Applies its own POSIX CPU and address-space limits before doing
any work, so the parent's wall-clock kill is not the only bound.

POSIX only: `resource` is absent on Windows, where this module does not run.
"""

import json
import sys
from typing import TextIO, cast

from jsonschema import FormatChecker, validators
from jsonschema.exceptions import SchemaError, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

type JsonValue = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None

DEFAULT_CPU_SECONDS = 5
"""The child's own CPU ceiling when the parent passes none."""

MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
"""The child's address-space ceiling, a backstop against runaway allocation."""

MAX_PROBLEMS = 10
"""The most problems one validation reports."""

# The constraint keys the parent needs to format a native message, and nothing
# more: descriptions, defaults, examples, patterns and `$defs` are dropped so a
# problem never duplicates a large advertised document. Numeric and array bounds
# remain available to the argument correction formatter.
_TRIM_KEYS = frozenset(
    {
        "type",
        "format",
        "enum",
        "const",
        "maxLength",
        "minLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
    }
)


def main(argv: list[str], stdin: TextIO, stdout: TextIO) -> int:
    """Read one request from `stdin`, write one response to `stdout`, exit 0.

    The CPU ceiling arrives as `argv[1]` (seconds), aligned with the parent's
    wall budget; the parent's kill is the primary bound and this is the backstop.
    """
    _apply_limits(_cpu_seconds(argv))
    stdout.write(json.dumps(_handle(_read_request(stdin))))
    return 0


def _cpu_seconds(argv: list[str]) -> int:
    try:
        return int(argv[1])
    except IndexError, ValueError:
        return DEFAULT_CPU_SECONDS


def _apply_limits(cpu_seconds: int) -> None:
    """Bound this child's own CPU and address space, where the host allows it.

    Applied here, in the child, never via `preexec_fn`, so no arbitrary Python
    runs between fork and exec in the threaded parent. `resource` is imported
    lazily because it is absent on Windows, where the parent's wall-clock kill
    is the only bound. A limit the platform will not accept is skipped rather
    than failing the run.
    """
    try:
        import resource
    except ImportError:
        return
    limits = (
        (resource.RLIMIT_CPU, cpu_seconds),
        (resource.RLIMIT_AS, MEMORY_LIMIT_BYTES),
    )
    for res, value in limits:
        if value <= 0:
            continue
        try:
            _, hard = resource.getrlimit(res)
            ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(res, (ceiling, ceiling))
        except ValueError, OSError:
            pass


def _read_request(stdin: TextIO) -> object:
    """Parse stdin as JSON, or `None` when it is not one JSON document."""
    try:
        return json.loads(stdin.read())
    except json.JSONDecodeError:
        return None


def _handle(request: object) -> dict[str, object]:
    """Validate a parsed request, or report a controlled `invalid_schema`.

    The request is built by the trusted parent, so a request that is not a
    dict-shaped schema/arguments pair is a bug to fail closed, not a crash.
    """
    if not isinstance(request, dict):
        return {"ok": False, "error": "invalid_schema"}
    schema = request.get("schema")
    arguments = request.get("arguments")
    if not isinstance(schema, dict) or not isinstance(arguments, dict):
        return {"ok": False, "error": "invalid_schema"}
    return _validate(cast(dict[str, JsonValue], schema), cast(dict[str, JsonValue], arguments))


def _validate(schema: dict[str, JsonValue], arguments: dict[str, JsonValue]) -> dict[str, object]:
    """Run `check_schema` then `iter_errors`, capped and stripped of instance data.

    Both run in the child so neither a schema that fails to check nor one that
    errors while iterating - invalid, unresolved or recursively deep - can reach
    the parent's loop. An empty `Registry` disables jsonschema's default URL
    retriever, so a schema cannot read files or dial an unchecked host; local
    `#/...` references still resolve against the document itself.
    """
    try:
        validator = validators.validator_for(schema)
        validator.check_schema(schema)
    except SchemaError, Unresolvable, RecursionError:
        return {"ok": False, "error": "invalid_schema"}
    checker = validator(schema, format_checker=FormatChecker(), registry=Registry())
    problems: list[dict[str, object]] = []
    try:
        for error in checker.iter_errors(arguments):
            for problem in _expand(error, schema):
                if problem not in problems:
                    problems.append(problem)
                if len(problems) >= MAX_PROBLEMS:
                    return {"ok": True, "problems": problems}
    except SchemaError, Unresolvable, RecursionError:
        return {"ok": False, "error": "invalid_schema"}
    return {"ok": True, "problems": problems}


def _expand(error: ValidationError, root: dict[str, JsonValue]) -> list[dict[str, object]]:
    """Turn one validation error into safe, trimmed problem descriptors.

    A `required` error reports its missing names at the parent object; each is
    expanded into its own problem carrying the field's own schema, so the parent
    can format per-field messages. Everything else is one problem at the error's
    absolute path.
    """
    if error.validator == "required":
        missing = [name for name in error.validator_value if name not in error.instance]
        problems: list[dict[str, object]] = []
        for name in missing[:MAX_PROBLEMS]:
            problems.append(
                _problem(
                    [*error.absolute_path, name],
                    "required",
                    _trim_schema(_local_schema(root, _property_schema(error.schema, name))),
                    [name],
                )
            )
        return problems
    return [
        _problem(
            list(error.absolute_path),
            str(error.validator),
            _trim_schema(error.schema),
            [],
        )
    ]


def _property_schema(subschema: object, name: str) -> dict[str, JsonValue]:
    """The advertised schema of one property, or `{}` when absent."""
    if not isinstance(subschema, dict):
        return {}
    properties = subschema.get("properties")
    if not isinstance(properties, dict):
        return {}
    field = properties.get(name)
    return cast(dict[str, JsonValue], field) if isinstance(field, dict) else {}


def _local_schema(root: dict[str, JsonValue], schema: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Resolve a local `#/$defs/` reference against the root, else the schema."""
    reference = schema.get("$ref")
    if isinstance(reference, str) and reference.startswith("#/$defs/"):
        definitions = root.get("$defs")
        resolved = (
            definitions.get(reference.removeprefix("#/$defs/"))
            if isinstance(definitions, dict)
            else None
        )
        return resolved if isinstance(resolved, dict) else {}
    return schema


def _trim_schema(schema: object) -> dict[str, JsonValue]:
    """Keep only the constraint keys the parent needs, recursively for `items`/`anyOf`."""
    if not isinstance(schema, dict):
        return {}
    trimmed: dict[str, JsonValue] = {}
    for key in _TRIM_KEYS:
        if key in schema:
            trimmed[key] = schema[key]
    items = schema.get("items")
    if isinstance(items, dict):
        trimmed["items"] = _trim_schema(items)
    alternatives = schema.get("anyOf")
    if isinstance(alternatives, list):
        trimmed["anyOf"] = [_trim_schema(alt) for alt in alternatives if isinstance(alt, dict)]
    return trimmed


def _problem(
    path: list[str | int], validator: str, schema: dict[str, JsonValue], missing: list[str]
) -> dict[str, object]:
    problem: dict[str, object] = {"path": path, "validator": validator, "schema": schema}
    if missing:
        problem["missing"] = missing
    return problem


if __name__ == "__main__":
    sys.exit(main(sys.argv, sys.stdin, sys.stdout))
