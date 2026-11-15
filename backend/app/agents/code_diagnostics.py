"""Structural compiler diagnostics recovered from Monty failures, without vendor prose.

A `MontyTypingError` arrives pre-rendered: the type checker runs inside the worker
subprocess and only its formatted text crosses the boundary, so the structured
diagnostics must be recovered from that text. Only the controlled diagnostic code
and the numeric source location are kept; the checker's message, source lines and
carets are never returned. Identifiers are read back from the submitted source, so
a name shown to the model is always one the model itself wrote.

Each helper yields at most one `ToolArgumentIssue`, whose message is built from the
extracted code, location and identifier - all of which are bounded - so an
adversarial or changed diagnostic format cannot grow the error envelope.
"""

import ast
import keyword
import re

from pydantic_monty import Frame, MontyRuntimeError, MontySyntaxError

from app.agents.tool_errors import ToolArgumentIssue

_MAX_IDENTIFIER_CHARS = 200
"""How long a name may be before it is not trusted as an identifier."""

_DIAGNOSTIC_CODE = re.compile(r"(?m)^error\[([a-z][a-z0-9-]{0,79})\]:")
"""The leading diagnostic code of a ty full-format report."""

_LOCATION = re.compile(r"(?m)^ --> [^\n]*:(\d{1,9}):(\d{1,9})(?:\n|$)")
"""The ` --> file:line:column` header naming the diagnostic's source position."""


def identifier_at(code: str, line: int, column: int) -> str | None:
    """The identifier reference in `code` at the 1-based `line`/`column`, or `None`.

    Resolved against the parsed source, so a position inside a string literal or a
    comment yields nothing and only a real `ast.Name` reference is returned. The
    result is always text the model itself supplied.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError, ValueError, RecursionError:
        return None
    offset = column - 1
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name):
            continue
        end = node.end_col_offset
        if end is not None and node.lineno == line and node.col_offset <= offset < end:
            return _safe_identifier(node.id)
    return None


def name_in_source(name: str, code: str) -> bool:
    """Whether `name` occurs as an identifier reference anywhere in `code`."""
    try:
        tree = ast.parse(code)
    except SyntaxError, ValueError, RecursionError:
        return False
    return any(isinstance(node, ast.Name) and node.id == name for node in ast.walk(tree))


def _safe_identifier(name: str) -> str | None:
    """`name` when it is a plain, bounded Python identifier, otherwise `None`."""
    if not name or len(name) > _MAX_IDENTIFIER_CHARS:
        return None
    if not name.isascii() or not name.isidentifier() or keyword.iskeyword(name):
        return None
    return name


def _typing_location(display: str) -> tuple[str, int, int] | None:
    """The first diagnostic's code and 1-based source position, or `None`."""
    code = _DIAGNOSTIC_CODE.search(display)
    location = _LOCATION.search(display)
    if code is None or location is None:
        return None
    return code.group(1), int(location.group(1)), int(location.group(2))


def typing_issues(display: str, code: str) -> list[ToolArgumentIssue]:
    """Structural issues from a pre-rendered `MontyTypingError`, empty when unreadable."""
    located = _typing_location(display)
    if located is None:
        return []
    diagnostic_code, line, column = located
    if diagnostic_code == "unresolved-reference":
        identifier = identifier_at(code, line, column)
        if identifier is not None:
            return [
                ToolArgumentIssue(
                    field="code",
                    code=diagnostic_code,
                    expected_type="defined name",
                    message=f"Name `{identifier}` is not defined (line {line}, column {column}).",
                )
            ]
    if diagnostic_code == "invalid-syntax":
        return [
            ToolArgumentIssue(
                field="code",
                code=diagnostic_code,
                expected_type="valid Python",
                message=f"Code validation failed: invalid syntax at line {line}, column {column}.",
            )
        ]
    return [
        ToolArgumentIssue(
            field="code",
            code=diagnostic_code,
            expected_type="valid Python",
            message=f"Code validation failed: {diagnostic_code} at line {line}, column {column}.",
        )
    ]


def syntax_issues(error: MontySyntaxError) -> list[ToolArgumentIssue]:
    """One structural issue carrying the 1-based syntax-error position."""
    frames = error.traceback()
    if not frames:
        return []
    frame = frames[-1]
    return [
        ToolArgumentIssue(
            field="code",
            code="invalid-syntax",
            expected_type="valid Python",
            message=f"Code validation failed: invalid syntax at line {frame.line}, column {frame.column}.",
        )
    ]


def name_error_issues(
    inner: NameError, error: MontyRuntimeError, code: str
) -> list[ToolArgumentIssue]:
    """The safe missing identifier of a runtime `NameError`, when one is available.

    The exception's own text is never parsed. Its `name` attribute is trusted only
    when it is a plain identifier that also occurs in the submitted code; otherwise
    the name is read from the submitted source at the failing frame's position. When
    neither yields a name, only the numeric location is kept.
    """
    name = getattr(inner, "name", None)
    identifier = _safe_identifier(name) if isinstance(name, str) else None
    if identifier is not None and not name_in_source(identifier, code):
        identifier = None
    frame = _source_frame(error)
    if identifier is None and frame is not None:
        identifier = identifier_at(code, frame.line, frame.column)
    position = f" (line {frame.line}, column {frame.column})" if frame is not None else ""
    if identifier is not None:
        return [
            ToolArgumentIssue(
                field="code",
                code="name-error",
                expected_type="defined name",
                message=f"Name `{identifier}` is not defined{position}.",
            )
        ]
    if frame is not None:
        return [
            ToolArgumentIssue(
                field="code",
                code="name-error",
                expected_type="defined name",
                message=f"A name is not defined{position}.",
            )
        ]
    return []


def _source_frame(error: MontyRuntimeError) -> Frame | None:
    """The innermost frame that maps to submitted code, or `None` without one."""
    for frame in reversed(error.traceback()):
        if frame.source_line is not None:
            return frame
    return None
