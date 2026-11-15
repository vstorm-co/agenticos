"""What naming a column makes a reader read: a formula's inputs, a rollup's link, a linked table."""

from uuid import UUID

from app.schemas.virtual_table import ColumnDef
from app.services.virtual_tables import Reach, reach

OTHER_TABLE = UUID("00000000-0000-4000-8000-0000000000f1")
AMOUNT = UUID("00000000-0000-4000-8000-0000000000f2")

LINK = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000001"),
    label="Invoices",
    type="link",
    link_table_id=OTHER_TABLE,
)
TOTAL = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000002"),
    label="Total",
    type="rollup",
    link_column_id=LINK.id,
    target_column_id=AMOUNT,
    aggregate="sum",
)
COUNT = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000003"),
    label="Invoice count",
    type="rollup",
    link_column_id=LINK.id,
    aggregate="count",
)
QUANTITY = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000004"), label="Quantity", type="integer"
)
GONE = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000005"), label="Gone", type="number", archived=True
)
FORMULA = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000006"),
    label="Score",
    type="formula",
    formula="{Total} * {Quantity} + {Gone} + {total}",
)
NAME = ColumnDef(id=UUID("00000000-0000-4000-8000-000000000007"), label="Name", type="text")
COLUMNS = [LINK, TOTAL, COUNT, QUANTITY, GONE, FORMULA, NAME]


def test_reach_follows_a_formula_into_a_rollup_and_its_link():
    # `{Gone}` names an archived column and `{total}` no live label exactly, so
    # neither is read - the way `check_formula` matches a formula's labels.
    reached = reach(COLUMNS, [FORMULA.id, TOTAL.id])

    assert reached == Reach(
        columns=frozenset({FORMULA.id, TOTAL.id, QUANTITY.id, LINK.id}),
        linked={OTHER_TABLE: frozenset({AMOUNT})},
    )


def test_reach_of_a_count_rollup_reads_no_target():
    reached = reach(COLUMNS, [COUNT.id])

    assert reached.columns == frozenset({COUNT.id, LINK.id})
    assert reached.linked == {OTHER_TABLE: frozenset()}


def test_reach_of_a_named_link_names_its_table():
    reached = reach(COLUMNS, [LINK.id, NAME.id])

    assert reached.columns == frozenset({LINK.id, NAME.id})
    assert reached.linked == {OTHER_TABLE: frozenset()}


def test_reach_follows_nothing_from_what_is_not_a_column():
    unknown = UUID("00000000-0000-4000-8000-0000000000e1")
    stray = ColumnDef(
        id=UUID("00000000-0000-4000-8000-000000000008"),
        label="Stray",
        type="lookup",
        link_column_id=unknown,
        target_column_id=AMOUNT,
    )

    reached = reach([*COLUMNS, stray], [stray.id])

    assert reached == Reach(columns=frozenset({stray.id, unknown}), linked={})


def test_rollups_return_json_safe_values_when_finite_inputs_overflow_the_sum():
    import json

    from app.services.virtual_tables.computed import _Linked, _work_out

    amount = ColumnDef(id=AMOUNT, label="Amount", type="number")
    linked = _Linked(
        columns=[amount],
        values={
            "a": {str(AMOUNT): 1e308},
            "b": {str(AMOUNT): 1e308},
        },
        names={},
    )
    assert _work_out(TOTAL, ["a", "b"], linked) is None
    average = TOTAL.model_copy(update={"aggregate": "avg"})
    assert _work_out(average, ["a", "b"], linked) == 1e308
    json.dumps(
        {
            "sum": _work_out(TOTAL, ["a", "b"], linked),
            "avg": _work_out(average, ["a", "b"], linked),
        },
        allow_nan=False,
    )


# -- row-level access on linked records ---------------------------------------
#
# A row the reader may see can link to one they may not. The label would leak
# the linked record's title and a rollup over it would leak that it exists,
# so an invisible linked record yields no label and no id, and rollups count
# only the visible subset.

import uuid as _uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest as _pytest

from app.core.permissions import AuthContext as _AuthContext
from app.repositories import virtual_table_repo as _virtual_table_repo
from app.schemas.virtual_table import RecordRead as _RecordRead
from app.schemas.virtual_table import RowPolicy as _RowPolicy
from app.services.virtual_tables import computed as _computed
from app.services.virtual_tables.computed import LinkedTable as _LinkedTable
from app.services.virtual_tables.computed import linked_cell_keys as _linked_cell_keys
from app.services.virtual_tables.computed import read_through as _read_through

pytestmark = _pytest.mark.anyio

_OTHER_TABLE = UUID("00000000-0000-4000-8000-0000000000a1")
_ASSIGNEE = UUID("00000000-0000-4000-8000-0000000000a2")
_NAME = UUID("00000000-0000-4000-8000-0000000000a3")
_LINK = UUID("00000000-0000-4000-8000-0000000000a4")
_COUNT = UUID("00000000-0000-4000-8000-0000000000a5")
_MEMBER = UUID("00000000-0000-4000-8000-0000000000a6")
_OTHER = UUID("00000000-0000-4000-8000-0000000000a7")
_ORG = UUID("00000000-0000-4000-8000-0000000000a8")
_VISIBLE = UUID("00000000-0000-4000-8000-0000000000a9")
_HIDDEN = UUID("00000000-0000-4000-8000-0000000000aa")

_ASSIGNEE_COL = ColumnDef(id=_ASSIGNEE, label="Assignee", type="user")
_NAME_COL = ColumnDef(id=_NAME, label="Name", type="text")
_LINK_COL = ColumnDef(id=_LINK, label="Task", type="link", link_table_id=_OTHER_TABLE)
_COUNT_COL = ColumnDef(
    id=_COUNT, label="Linked count", type="rollup", link_column_id=_LINK, aggregate="count"
)
_POLICY = _RowPolicy(rule="assignee", view_column_id=_ASSIGNEE, edit_column_id=_ASSIGNEE)


def _linked_row(record_id, assignee, name):
    return SimpleNamespace(
        id=record_id,
        values={str(_NAME): name, str(_ASSIGNEE): str(assignee)},
    )


def _record_with_links():
    return _RecordRead(
        id=_uuid.uuid4(),
        table_id=_uuid.uuid4(),
        external_id=None,
        schema_version=1,
        values={str(_LINK): [str(_VISIBLE), str(_HIDDEN)]},
        revision=1,
        created_at=datetime.now(UTC),
    )


def _linked_table(policy):
    return _LinkedTable(
        table_id=_OTHER_TABLE,
        columns=[_NAME_COL, _ASSIGNEE_COL],
        named_by=_NAME_COL,
        row_policy=policy,
        owner_user_id=_OTHER,
    )


async def test_an_invisible_linked_row_yields_no_label_and_no_rollup(monkeypatch):
    monkeypatch.setattr(
        _computed, "linked_table_access", AsyncMock(return_value=_linked_table(_POLICY))
    )
    monkeypatch.setattr(
        _virtual_table_repo,
        "get_records_by_ids",
        AsyncMock(
            return_value=[
                _linked_row(_VISIBLE, _MEMBER, "Visible"),
                _linked_row(_HIDDEN, _OTHER, "Hidden"),
            ]
        ),
    )
    ctx = _AuthContext(user_id=_MEMBER, organization_id=_ORG, role="member")

    read = await _read_through(MagicMock(), ctx, [_LINK_COL, _COUNT_COL], [_record_with_links()])

    assert len(read[0].links[str(_LINK)]) == 1
    assert read[0].links[str(_LINK)][0].id == _VISIBLE
    assert read[0].links[str(_LINK)][0].label == "Visible"
    assert read[0].values[str(_COUNT)] == 1


async def test_a_bypass_caller_and_a_table_without_a_policy_see_every_linked_row(monkeypatch):
    monkeypatch.setattr(
        _computed, "linked_table_access", AsyncMock(return_value=_linked_table(_POLICY))
    )
    monkeypatch.setattr(
        _virtual_table_repo,
        "get_records_by_ids",
        AsyncMock(
            return_value=[
                _linked_row(_VISIBLE, _MEMBER, "Visible"),
                _linked_row(_HIDDEN, _OTHER, "Hidden"),
            ]
        ),
    )
    owner_ctx = _AuthContext(user_id=_MEMBER, organization_id=_ORG, role="owner")
    read = await _read_through(
        MagicMock(), owner_ctx, [_LINK_COL, _COUNT_COL], [_record_with_links()]
    )
    assert len(read[0].links[str(_LINK)]) == 2
    assert read[0].values[str(_COUNT)] == 2

    monkeypatch.setattr(
        _computed, "linked_table_access", AsyncMock(return_value=_linked_table(None))
    )
    member_ctx = _AuthContext(user_id=_MEMBER, organization_id=_ORG, role="member")
    read = await _read_through(
        MagicMock(), member_ctx, [_LINK_COL, _COUNT_COL], [_record_with_links()]
    )
    assert len(read[0].links[str(_LINK)]) == 2


def test_a_projected_read_through_a_policy_table_fetches_the_assignee_cell():
    keys = _linked_cell_keys(_linked_table(_POLICY), frozenset())
    assert str(_ASSIGNEE) in keys
    assert str(_NAME) in keys
    assert _linked_cell_keys(_linked_table(None), frozenset([_NAME])) == [str(_NAME)]


@_pytest.mark.security
def test_a_projected_read_keeps_the_cells_that_decide_linked_project_access() -> None:
    policy = _RowPolicy(
        rule="assignee",
        view_column_id=_ASSIGNEE,
        edit_column_id=_ASSIGNEE,
        view_project_link_column_id=_LINK,
        view_projects_table_id=_OTHER_TABLE,
        view_project_members_column_id=_MEMBER,
    )
    keys = _linked_cell_keys(_linked_table(policy), frozenset([_NAME, _ASSIGNEE]))
    assert keys == sorted([str(_NAME), str(_ASSIGNEE), str(_LINK)])


async def test_linked_table_access_carries_the_linked_tables_policy(monkeypatch):
    table = SimpleNamespace(
        id=_OTHER_TABLE,
        organization_id=_ORG,
        schema_version=1,
        row_policy=_POLICY.model_dump(mode="json"),
        owner_user_id=_OTHER,
    )
    version = SimpleNamespace(
        columns=[
            _NAME_COL.model_dump(mode="json"),
            _ASSIGNEE_COL.model_dump(mode="json"),
        ]
    )
    monkeypatch.setattr(_virtual_table_repo, "get_table", AsyncMock(return_value=table))
    monkeypatch.setattr(_virtual_table_repo, "get_schema_version", AsyncMock(return_value=version))
    monkeypatch.setattr(_computed, "resolve_access", AsyncMock(return_value=True))
    ctx = _AuthContext(user_id=_MEMBER, organization_id=_ORG, role="member")

    linked = await _computed.linked_table_access(MagicMock(), ctx, _OTHER_TABLE)

    assert linked is not None
    assert linked.row_policy == _POLICY
    assert linked.owner_user_id == _OTHER
    assert linked.named_by == _NAME_COL


async def test_linked_table_access_returns_none_when_the_reader_may_not_see_it(monkeypatch):
    monkeypatch.setattr(_virtual_table_repo, "get_table", AsyncMock(return_value=None))
    ctx = _AuthContext(user_id=_MEMBER, organization_id=_ORG, role="member")

    assert await _computed.linked_table_access(MagicMock(), ctx, _OTHER_TABLE) is None
