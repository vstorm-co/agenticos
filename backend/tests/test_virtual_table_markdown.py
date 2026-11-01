"""Markdown is a text document, preserved across validation and lossless type changes."""

from uuid import uuid4

import pytest

from app.schemas.virtual_table import ColumnDef, ColumnTypeName
from app.services.virtual_tables.conversions import convert, convertible
from app.services.virtual_tables.types import (
    MAX_LONG_TEXT,
    CellProblem,
    validate_cell,
    validate_default,
    validate_filter,
)

DOCUMENT = '---\r\ntitle: "Zażółć"\r\ntags: [notes, team]\r\n---\r\n\r\n# Hello\r\n\r\n- [ ] **Review** `code`\r\n'


def column(kind: ColumnTypeName = "rich_text") -> ColumnDef:
    return ColumnDef(id=uuid4(), label="Notes", type=kind)


def test_markdown_and_frontmatter_survive_writes_defaults_and_filters_exactly() -> None:
    field = column()
    assert validate_cell(field, DOCUMENT) == DOCUMENT
    assert validate_default(field.model_copy(update={"default": DOCUMENT})) == DOCUMENT
    assert validate_filter(field, "contains", "tags: [notes, team]") == "tags: [notes, team]"
    assert validate_cell(field, "") == ""
    assert validate_cell(field, None) is None
    assert validate_cell(field, "x" * MAX_LONG_TEXT) == "x" * MAX_LONG_TEXT


@pytest.mark.parametrize("value", [5, True, {}, [], "a\x00b", "\ud800", "x" * (MAX_LONG_TEXT + 1)])
def test_invalid_rich_text_is_refused(value: object) -> None:
    with pytest.raises(CellProblem):
        validate_cell(column(), value)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("text", "rich_text"),
        ("long_text", "rich_text"),
        ("rich_text", "long_text"),
        ("rich_text", "text"),
    ],
)
def test_plain_text_and_markdown_convert_without_rewriting_source(
    old: ColumnTypeName, new: ColumnTypeName
) -> None:
    assert convertible(old, new)
    assert convert(DOCUMENT, column(old), column(new)) == DOCUMENT


def test_conversion_to_short_text_still_enforces_its_limit() -> None:
    with pytest.raises(CellProblem):
        convert("x" * 1001, column(), column("text"))
    assert not convertible("rich_text", "number")
