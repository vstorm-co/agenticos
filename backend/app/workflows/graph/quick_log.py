"""A Quick Log's message template: which references it holds, and how it renders.

A reference is `{{name}}` or `{{a.b}}`. Four names are the platform's - `step`,
`outcome`, and `error.code` / `error.message` on a failed step - and anything else
reads the step's own output. Rendering is lenient by design: the line is written
while a step settles, so a reference with no value renders empty and nothing here
raises. `error.details` is never readable; a failure's details can carry what the
step was handed.
"""

import json
import re
from collections.abc import Mapping
from typing import Any

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}")
"""A reference as written. Dotted names walk into an object."""

ERROR_FIELDS = frozenset({"code", "message"})
"""What of a failed step's error a message may read."""


def references(message: str) -> tuple[tuple[str, ...], ...]:
    """Every reference in `message`, as its path, in order of appearance."""
    return tuple(tuple(match.split(".")) for match in PLACEHOLDER.findall(message))


def refused_reference(path: tuple[str, ...]) -> bool:
    """Whether a message may not read `path`: anything of `error` but its code and message."""
    return path[0] == "error" and not (len(path) == 2 and path[1] in ERROR_FIELDS)


def _text(value: Any, limit: int) -> str:
    """`value` as text, cut at `limit` characters while it is built."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), default=str)
    parts: list[str] = []
    size = 0
    for chunk in encoder.iterencode(value):
        parts.append(chunk)
        size += len(chunk)
        if size >= limit:
            break
    return "".join(parts)[:limit]


def render(
    message: str,
    *,
    step: str,
    outcome: str,
    output: Mapping[str, Any] | None,
    error: Mapping[str, Any] | None,
    limit: int,
) -> str:
    """`message` with each reference replaced by its value, or by nothing.

    `output` is what the step completed with and `error` what it failed with;
    a reference to the one the step did not produce renders empty. The text is
    built only up to `limit` characters: a large output never becomes a large
    string, because this runs while the run's lock is held.
    """

    def value(path: tuple[str, ...]) -> str:
        if path == ("step",):
            return step
        if path == ("outcome",):
            return outcome
        if refused_reference(path):
            return ""
        current: Any = error if path[0] == "error" else output
        for part in path[1:] if path[0] == "error" else path:
            current = current.get(part) if isinstance(current, Mapping) else None
        return _text(current, limit)

    parts: list[str] = []
    size = 0
    position = 0
    for match in PLACEHOLDER.finditer(message):
        parts.append(message[position : match.start()])
        parts.append(value(tuple(match.group(1).split("."))))
        position = match.end()
        size += len(parts[-2]) + len(parts[-1])
        if size >= limit:
            break
    else:
        parts.append(message[position:])
    return "".join(parts)[:limit]
