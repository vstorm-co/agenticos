"""The model names itself in logs without dumping its config."""

import uuid

from app.db.models.table_view import TableView


def test_a_repr_identifies_the_row_but_never_prints_its_config():
    view = TableView(
        table_id=uuid.uuid4(),
        name="Board",
        kind="kanban",
        config={"group_by": "s3cret-column-id"},
    )

    text = repr(view)

    assert "Board" in text and "kanban" in text
    assert "s3cret-column-id" not in text
