"""`WorkflowPreparationCreate`: a new table and its placeholder travel together."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.virtual_table import ColumnInput, TableCreate
from app.schemas.workflow import WorkflowPreparationCreate
from app.workflows.graph.model import WorkflowGraph


def _graph() -> WorkflowGraph:
    return WorkflowGraph(entry_node_id=uuid4(), nodes=(), edges=(), bindings=())


def _table() -> TableCreate:
    return TableCreate(name="Contacts", columns=[ColumnInput(label="Name", type="text")])


class TestAPreparationPairsItsTableWithItsPlaceholder:
    def test_a_table_without_its_placeholder_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="both table and table_placeholder_id"):
            WorkflowPreparationCreate(name="Contacts", graph=_graph(), table=_table())

    def test_a_placeholder_without_a_table_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="both table and table_placeholder_id"):
            WorkflowPreparationCreate(name="Contacts", graph=_graph(), table_placeholder_id=uuid4())

    def test_both_together_or_neither_is_accepted(self) -> None:
        paired = WorkflowPreparationCreate(
            name="Contacts", graph=_graph(), table=_table(), table_placeholder_id=uuid4()
        )
        bare = WorkflowPreparationCreate(name="Contacts", graph=_graph())

        assert paired.table is not None and paired.table_placeholder_id is not None
        assert bare.table is None and bare.table_placeholder_id is None
