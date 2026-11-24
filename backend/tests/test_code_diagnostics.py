"""The structural diagnostics recovered from Monty failures stay safe and bounded."""

from unittest.mock import MagicMock

import pytest
from pydantic_monty import MontyRuntimeError, MontySyntaxError

from app.agents import code_diagnostics
from app.agents.code_diagnostics import (
    _safe_identifier,
    identifier_at,
    name_error_issues,
    name_in_source,
    syntax_issues,
    typing_issues,
)


def _frame(line: int, column: int, source_line: str | None) -> MagicMock:
    return MagicMock(line=line, column=column, source_line=source_line)


def test_an_identifier_is_read_only_from_a_real_reference_at_its_position() -> None:
    assert identifier_at("print(missing_config_name)", 1, 7) == "missing_config_name"
    assert identifier_at("print(missing_config_name)", 1, 12) == "missing_config_name"
    assert identifier_at("x = 1\nprint(x)", 2, 7) == "x"


def test_a_position_inside_a_string_or_comment_is_no_identifier() -> None:
    assert identifier_at("'missing_config_name'", 1, 3) is None
    assert identifier_at("print(x)  # missing_config_name", 1, 13) is None


def test_a_position_out_of_bounds_or_a_keyword_is_no_identifier() -> None:
    assert identifier_at("x", 2, 1) is None
    assert identifier_at("x", 1, 10) is None
    assert identifier_at("raise NameError('x')", 1, 1) is None


def test_code_that_does_not_parse_has_no_identifier() -> None:
    assert identifier_at("def f(:", 1, 1) is None
    assert name_in_source("f", "def f(:") is False


def test_a_name_is_reported_only_when_it_is_a_real_reference() -> None:
    assert name_in_source("missing_config_name", "print(missing_config_name)") is True
    assert name_in_source("missing_config_name", "'missing_config_name'") is False
    assert name_in_source("other", "print(missing_config_name)") is False


def test_a_safe_identifier_is_plain_ascii_and_bounded() -> None:
    assert _safe_identifier("ok_name") == "ok_name"
    assert _safe_identifier("") is None
    assert _safe_identifier("x" * 201) is None
    assert _safe_identifier("café") is None
    assert _safe_identifier("1abc") is None
    assert _safe_identifier("raise") is None


def test_an_unresolved_reference_names_the_identifier_at_the_location() -> None:
    display = (
        "error[unresolved-reference]: Name `missing_config_name` used when not defined\n"
        " --> main.py:1:7\n  |\n1 | print(missing_config_name)\n"
    )
    (issue,) = typing_issues(display, "print(missing_config_name)")

    assert issue.field == "code"
    assert issue.code == "unresolved-reference"
    assert issue.expected_type == "defined name"
    assert issue.message == "Name `missing_config_name` is not defined (line 1, column 7)."


def test_an_unresolved_reference_without_a_readable_name_keeps_only_code_and_location() -> None:
    display = "error[unresolved-reference]: Name `x` used when not defined\n --> main.py:1:1\n"
    (issue,) = typing_issues(display, "raise NameError('x')")

    assert issue.field == "code"
    assert issue.code == "unresolved-reference"
    assert issue.message == "Code validation failed: unresolved-reference at line 1, column 1."


def test_an_invalid_syntax_diagnostic_keeps_a_safe_category_and_position() -> None:
    display = "error[invalid-syntax]: Expected an expression\n --> main.py:1:3\n"
    (issue,) = typing_issues(display, "if")

    assert issue.field == "code"
    assert issue.code == "invalid-syntax"
    assert issue.message == "Code validation failed: invalid syntax at line 1, column 3."


def test_another_diagnostic_keeps_only_its_code_and_position() -> None:
    display = (
        "error[invalid-argument-type]: Argument to function `len` is incorrect\n --> main.py:1:5\n"
    )
    (issue,) = typing_issues(display, "len(1)")

    assert issue.field == "code"
    assert issue.code == "invalid-argument-type"
    assert issue.message == "Code validation failed: invalid-argument-type at line 1, column 5."


def test_an_unreadable_display_yields_no_issue() -> None:
    assert typing_issues("not a diagnostic", "x") == []


@pytest.mark.parametrize(
    "display",
    [
        f"error[{'x' * 1000}]: message\n --> main.py:1:1\n",
        f"error[invalid-syntax]: message\n --> main.py:{'1' * 5000}:1\n",
    ],
)
def test_an_oversized_diagnostic_header_yields_no_issue(display: str) -> None:
    assert typing_issues(display, "x") == []


def test_an_ast_depth_failure_omits_the_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    def too_deep(_code: str) -> None:
        raise RecursionError

    monkeypatch.setattr(code_diagnostics.ast, "parse", too_deep)

    assert identifier_at("x", 1, 1) is None
    assert name_in_source("x", "x") is False


def test_a_syntax_error_carries_its_position() -> None:
    error = MagicMock(spec=MontySyntaxError)
    error.traceback.return_value = [_frame(1, 7, "def f(:")]

    (issue,) = syntax_issues(error)

    assert issue.field == "code"
    assert issue.code == "invalid-syntax"
    assert issue.message == "Code validation failed: invalid syntax at line 1, column 7."


def test_a_syntax_error_without_a_frame_yields_no_issue() -> None:
    error = MagicMock(spec=MontySyntaxError)
    error.traceback.return_value = []

    assert syntax_issues(error) == []


def _runtime_error(*frames: MagicMock) -> MagicMock:
    error = MagicMock(spec=MontyRuntimeError)
    error.traceback.return_value = list(frames)
    return error


def test_a_name_error_keeps_a_name_that_also_occurs_in_the_source() -> None:
    inner = NameError(name="missing_config_name")

    (issue,) = name_error_issues(
        inner,
        _runtime_error(_frame(1, 7, "print(missing_config_name)")),
        "print(missing_config_name)",
    )

    assert issue.field == "code"
    assert issue.code == "name-error"
    assert issue.message == "Name `missing_config_name` is not defined (line 1, column 7)."


def test_a_name_error_does_not_disclose_a_name_absent_from_the_source() -> None:
    inner = NameError(name="sk_private_token")

    (issue,) = name_error_issues(
        inner,
        _runtime_error(_frame(1, 7, "print(missing_config_name)")),
        "print(missing_config_name)",
    )

    assert issue.field == "code"
    assert "sk_private_token" not in issue.message
    assert issue.message == "Name `missing_config_name` is not defined (line 1, column 7)."


def test_a_name_error_without_a_name_reads_it_from_the_source() -> None:
    inner = NameError()

    (issue,) = name_error_issues(
        inner, _runtime_error(_frame(1, 7, "print(undefined_name)")), "print(undefined_name)"
    )

    assert issue.field == "code"
    assert issue.message == "Name `undefined_name` is not defined (line 1, column 7)."


@pytest.mark.security
def test_a_name_error_with_a_secret_name_reads_only_from_the_source() -> None:
    inner = NameError(name="https://internal.invalid/?token=secret")

    (issue,) = name_error_issues(
        inner, _runtime_error(_frame(1, 7, "print(undefined_name)")), "print(undefined_name)"
    )

    assert "internal.invalid" not in issue.message
    assert "secret" not in issue.message
    assert issue.message == "Name `undefined_name` is not defined (line 1, column 7)."


def test_a_name_error_with_no_readable_name_keeps_only_the_location() -> None:
    inner = NameError()

    (issue,) = name_error_issues(
        inner, _runtime_error(_frame(1, 1, "raise NameError('x')")), "raise NameError('x')"
    )

    assert issue.field == "code"
    assert issue.message == "A name is not defined (line 1, column 1)."


def test_a_name_error_without_a_source_frame_yields_no_issue() -> None:
    inner = NameError()

    assert name_error_issues(inner, _runtime_error(_frame(1, 1, None)), "x") == []
