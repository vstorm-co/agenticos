"""Atomic link intent against a locked record, with repository boundaries stubbed."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import GrantLevel
from app.repositories import resource_grant_repo, virtual_table_repo
from app.schemas.virtual_table import ColumnDef, RecordLinkChange, RecordSource, RowPolicy
from app.services.virtual_tables import record_access, records
from app.services.virtual_tables.exceptions import (
    ArchivedColumnError,
    InvalidRecordError,
    RevisionConflictError,
)
from app.services.virtual_tables.records import RecordOperations
from app.services.virtual_tables.types import MAX_LINKS

pytestmark = pytest.mark.anyio

LINK = UUID("00000000-0000-4000-8000-000000000001")
TEXT = UUID("00000000-0000-4000-8000-000000000002")
READER = UUID("00000000-0000-4000-8000-000000000003")
VISIBLE = UUID("00000000-0000-4000-8000-000000000004")
HIDDEN = UUID("00000000-0000-4000-8000-000000000005")
ADDED = UUID("00000000-0000-4000-8000-000000000006")


@pytest.fixture
def linked(monkeypatch):
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="member")
    owner = uuid4()
    source = SimpleNamespace(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=owner,
        schema_version=1,
        row_policy=None,
        archived_at=None,
    )
    target = SimpleNamespace(
        id=uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=owner,
        schema_version=1,
        row_policy=RowPolicy(
            rule="assignee", view_column_id=READER, edit_column_id=READER
        ).model_dump(mode="json"),
        archived_at=None,
    )
    columns = [
        ColumnDef(id=LINK, label="Items", type="link", link_table_id=target.id),
        ColumnDef(id=TEXT, label="Title", type="text"),
    ]
    target_columns = [ColumnDef(id=READER, label="Reader", type="user")]
    row = SimpleNamespace(
        id=uuid4(),
        table_id=source.id,
        external_id=None,
        schema_version=1,
        revision=1,
        values={str(LINK): [str(HIDDEN), str(VISIBLE)], str(TEXT): "Before"},
        created_at=datetime.now(UTC),
        updated_at=None,
        created_by=ctx.user_id,
        updated_by=None,
        created_source=None,
        updated_source=None,
    )
    targets = {
        key: SimpleNamespace(
            id=key, values={str(READER): str(owner if key == HIDDEN else ctx.user_id)}
        )
        for key in [VISIBLE, HIDDEN, ADDED]
    }

    async def schema(db, *, table_id, version):
        selected = columns if table_id == source.id else target_columns
        return SimpleNamespace(columns=[column.model_dump(mode="json") for column in selected])

    async def found(db, ids, *, table_id, organization_id):
        assert table_id == target.id and organization_id == ctx.organization_id
        return [targets[key] for key in ids if key in targets]

    async def update(db, *, record, values, **_):
        record.values = values
        record.revision += 1

    monkeypatch.setattr(virtual_table_repo, "get_schema_version", schema)
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=target))
    queried = AsyncMock(side_effect=found)
    monkeypatch.setattr(virtual_table_repo, "get_records_by_ids", queried)
    written = AsyncMock(side_effect=update)
    history, outbox = AsyncMock(), AsyncMock()
    monkeypatch.setattr(virtual_table_repo, "update_record", written)
    monkeypatch.setattr(virtual_table_repo, "add_history", history)
    monkeypatch.setattr(virtual_table_repo, "add_outbox", outbox)
    monkeypatch.setattr(records.trigger_repo, "has_active", AsyncMock(return_value=True))
    monkeypatch.setattr(records, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(record_access, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(resource_grant_repo, "record_levels", AsyncMock(return_value={}))
    monkeypatch.setattr(virtual_table_repo, "referenced_access_columns", AsyncMock(return_value=[]))
    monkeypatch.setattr(records.quotas, "enforce_record_size", AsyncMock())
    monkeypatch.setattr(
        records,
        "source_for",
        AsyncMock(return_value=RecordSource(kind="user", id=ctx.user_id, name="Writer")),
    )
    monkeypatch.setattr("app.repositories.task.for_table", AsyncMock(return_value=None))
    return SimpleNamespace(
        service=RecordOperations(db=MagicMock(spec=AsyncSession)),
        ctx=ctx,
        source=source,
        target=target,
        row=row,
        columns=columns,
        queried=queried,
        written=written,
        history=history,
        outbox=outbox,
    )


async def test_a_delta_preserves_hidden_targets_and_writes_one_revision_history_and_event(linked):
    state = linked
    await state.service._apply(
        state.ctx,
        state.source,
        state.row,
        {str(TEXT): "After"},
        1,
        link_changes={LINK: RecordLinkChange(add=[ADDED], remove=[VISIBLE])},
    )
    assert state.row.values == {str(LINK): [str(HIDDEN), str(ADDED)], str(TEXT): "After"}
    assert state.row.revision == 2
    assert [args.args[1] for args in state.queried.await_args_list] == [[ADDED, VISIBLE]]
    state.written.assert_awaited_once()
    state.history.assert_awaited_once()
    assert state.history.await_args.kwargs["revision"] == 2
    state.outbox.assert_awaited_once()


@pytest.mark.security
@pytest.mark.parametrize("changes_access", [False, True])
async def test_row_write_allows_ordinary_edits_but_not_access_link_deltas(
    linked, monkeypatch, changes_access
):
    state = linked

    async def table_reader(db, ctx, table, permission, **kwargs):
        return permission != Perm.TABLES_EDIT

    monkeypatch.setattr(record_access, "resolve_access", table_reader)
    monkeypatch.setattr(
        resource_grant_repo,
        "record_levels",
        AsyncMock(return_value={state.row.id: GrantLevel.EDIT}),
    )
    monkeypatch.setattr(
        virtual_table_repo, "referenced_access_columns", AsyncMock(return_value=[str(LINK)])
    )
    change = {LINK: RecordLinkChange(add=[ADDED])} if changes_access else None

    async def write():
        await state.service._apply(
            state.ctx, state.source, state.row, {str(TEXT): "After"}, 1, link_changes=change
        )

    if changes_access:
        with pytest.raises(AuthorizationError, match="table administration"):
            await write()
        state.written.assert_not_awaited()
        assert state.row.values[str(TEXT)] == "Before"
    else:
        await write()
        assert state.row.values[str(TEXT)] == "After"
        assert state.row.values[str(LINK)] == [str(HIDDEN), str(VISIBLE)]


@pytest.mark.security
@pytest.mark.parametrize("operation", ["add", "remove"])
@pytest.mark.parametrize("target", [HIDDEN, UUID("00000000-0000-4000-8000-000000000099")])
@pytest.mark.parametrize("at_limit", [False, True])
async def test_hidden_and_missing_explicit_targets_are_refused_identically(
    linked, operation, target, at_limit
):
    state = linked
    if at_limit:
        state.row.values[str(LINK)] = [str(HIDDEN), str(VISIBLE)] + [
            str(uuid4()) for _ in range(98)
        ]
    with pytest.raises(InvalidRecordError) as refused:
        await state.service._apply(
            state.ctx,
            state.source,
            state.row,
            {str(TEXT): "Must not land"},
            1,
            link_changes={LINK: RecordLinkChange(**{operation: [target]})},
        )
    assert refused.value.details == {
        "fields": [
            {
                "field": f"link_changes.{LINK}",
                "message": "No record is available in the linked table",
            }
        ]
    }
    assert state.row.revision == 1 and state.row.values[str(TEXT)] == "Before"
    state.written.assert_not_awaited()
    state.history.assert_not_awaited()
    state.outbox.assert_not_awaited()


@pytest.mark.security
@pytest.mark.parametrize("target", [HIDDEN, UUID("00000000-0000-4000-8000-000000000099")])
@pytest.mark.parametrize("was_linked", [False, True])
async def test_removing_an_unavailable_target_does_not_reveal_stored_membership(
    linked, target, was_linked
):
    state = linked
    original = [str(VISIBLE), *([str(target)] if was_linked else [])]
    state.row.values[str(LINK)] = original
    with pytest.raises(InvalidRecordError) as refused:
        await state.service._apply(
            state.ctx,
            state.source,
            state.row,
            {},
            1,
            link_changes={LINK: RecordLinkChange(remove=[target])},
        )
    assert refused.value.details == {
        "fields": [
            {
                "field": f"link_changes.{LINK}",
                "message": "No record is available in the linked table",
            }
        ]
    }
    assert state.row.values == {str(LINK): original, str(TEXT): "Before"}
    assert state.row.revision == 1
    state.written.assert_not_awaited()
    state.history.assert_not_awaited()
    state.outbox.assert_not_awaited()


async def test_link_limit_error_does_not_reveal_hidden_link_count(linked):
    state = linked
    state.row.values[str(LINK)] = [str(HIDDEN), str(VISIBLE)] + [
        str(uuid4()) for _ in range(MAX_LINKS - 2)
    ]

    with pytest.raises(InvalidRecordError) as refused:
        await state.service._apply(
            state.ctx,
            state.source,
            state.row,
            {str(TEXT): "Must not land"},
            1,
            link_changes={LINK: RecordLinkChange(add=[ADDED])},
        )

    assert refused.value.details == {
        "fields": [
            {
                "field": f"link_changes.{LINK}",
                "message": "This cell exceeds the maximum number of links",
            }
        ]
    }
    assert state.row.revision == 1 and state.row.values[str(TEXT)] == "Before"
    state.written.assert_not_awaited()


@pytest.mark.security
async def test_a_delta_cannot_change_a_source_row_the_writer_cannot_edit(linked):
    state = linked
    state.source.row_policy = RowPolicy(
        rule="assignee", view_column_id=READER, edit_column_id=READER
    ).model_dump(mode="json")
    with pytest.raises(NotFoundError):
        await state.service._apply(
            state.ctx,
            state.source,
            state.row,
            {},
            1,
            link_changes={LINK: RecordLinkChange(add=[ADDED])},
        )
    state.queried.assert_not_awaited()
    state.written.assert_not_awaited()


async def test_a_stale_delta_conflicts_before_checking_targets_even_if_it_would_be_a_noop(linked):
    state = linked
    state.row.revision = 2
    with pytest.raises(RevisionConflictError):
        await state.service._apply(
            state.ctx,
            state.source,
            state.row,
            {},
            1,
            link_changes={LINK: RecordLinkChange(add=[VISIBLE])},
        )
    state.queried.assert_not_awaited()
    state.written.assert_not_awaited()


@pytest.mark.parametrize(
    "change", [RecordLinkChange(add=[VISIBLE]), RecordLinkChange(remove=[ADDED])]
)
async def test_a_visible_noop_is_checked_but_creates_no_history_or_revision(linked, change):
    state = linked
    with pytest.raises(records._Unchanged):
        await state.service._apply(
            state.ctx,
            state.source,
            state.row,
            {},
            1,
            link_changes={LINK: change},
        )
    state.queried.assert_awaited_once()
    assert state.row.revision == 1
    state.written.assert_not_awaited()
    state.history.assert_not_awaited()


@pytest.mark.parametrize("kind", ["unknown", "archived", "text", "corrupt", "full"])
async def test_an_invalid_delta_is_refused_without_a_partial_scalar_write(linked, kind):
    state = linked
    key = LINK
    expected = InvalidRecordError
    if kind == "unknown":
        key = uuid4()
    elif kind == "archived":
        state.columns[0].archived = True
        expected = ArchivedColumnError
    elif kind == "text":
        key = TEXT
    elif kind == "corrupt":
        state.row.values[str(LINK)] = False
    else:
        state.row.values[str(LINK)] = [str(uuid4()) for _ in range(100)]
    with pytest.raises(expected):
        await state.service._apply(
            state.ctx,
            state.source,
            state.row,
            {str(TEXT): "Must not land"},
            1,
            link_changes={key: RecordLinkChange(add=[ADDED])},
        )
    assert state.row.values[str(TEXT)] == "Before"
    state.written.assert_not_awaited()


async def test_an_empty_delta_does_not_turn_an_absent_link_into_a_stored_empty_array(linked):
    state = linked
    state.row.values.pop(str(LINK))
    with pytest.raises(records._Unchanged):
        await state.service._apply(
            state.ctx,
            state.source,
            state.row,
            {},
            1,
            link_changes={LINK: RecordLinkChange()},
        )
    assert str(LINK) not in state.row.values
    state.queried.assert_not_awaited()
