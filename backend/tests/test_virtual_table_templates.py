"""Named document templates are bounded metadata with an explicit default."""

from uuid import uuid4

import pytest

from app.schemas.virtual_table import ColumnInput, DocumentTemplate
from app.services.virtual_tables.exceptions import InvalidSchemaError
from app.services.virtual_tables.schema import build_columns


def template(name: str = "Brief", body: str = "# Goal\n") -> DocumentTemplate:
    return DocumentTemplate(id=uuid4(), name=name, body=body)


def test_default_body_follows_its_template_and_old_clients_preserve_the_library():
    start = template()
    first = build_columns(
        [
            ColumnInput(
                label="Notes",
                type="rich_text",
                document_templates=[start],
                default_template_id=start.id,
            )
        ],
        [],
    )[0]
    assert first.default == start.body
    preserved = build_columns(
        [ColumnInput(id=first.id, label="Renamed", type="rich_text", default=start.body)], [first]
    )[0]
    assert preserved.document_templates == [start]
    assert preserved.default_template_id == start.id
    updated = start.model_copy(update={"body": "# Changed\n"})
    changed = build_columns(
        [ColumnInput(id=first.id, label="Notes", type="rich_text", document_templates=[updated])],
        [first],
    )[0]
    assert changed.default == "# Changed\n"
    manual = build_columns(
        [ColumnInput(id=first.id, label="Notes", type="rich_text", default="Custom")], [first]
    )[0]
    assert manual.default == "Custom"
    assert manual.default_template_id is None


@pytest.mark.parametrize(
    "failure", ["duplicate_name", "duplicate_id", "missing_default", "too_large", "wrong_type"]
)
def test_inconsistent_libraries_are_rejected(failure: str):
    start = template()
    second = template("Second")
    selected = start.id
    kind = "rich_text"
    if failure == "duplicate_name":
        second = second.model_copy(update={"name": "BRIEF"})
    elif failure == "duplicate_id":
        second = second.model_copy(update={"id": start.id})
    elif failure == "missing_default":
        selected = uuid4()
    elif failure == "too_large":
        second = second.model_copy(update={"body": "x" * 100000})
    else:
        kind = "text"
    with pytest.raises(InvalidSchemaError):
        build_columns(
            [
                ColumnInput(
                    label="Notes",
                    type=kind,
                    document_templates=[start, second],
                    default_template_id=selected,
                )
            ],
            [],
        )
