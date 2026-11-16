"""Restricted linked data stays private in payloads, exports and legacy updates."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.virtual_table import VirtualTable, VirtualTableRecord
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import (
    CellValue,
    ColumnDef,
    RecordBatchCreate,
    RecordCreate,
    RecordRead,
    RowPolicy,
)
from app.services.virtual_tables import computed, records
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.exceptions import InvalidRecordError, InvalidRowPolicyError
from app.services.virtual_tables.records import RecordOperations, _export_cell, _merge
from app.services.virtual_tables.row_policy import (
    may_edit_row,
    may_view_row,
    parse_policy,
    view_expression,
    visible_project_ids,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]

ORG = UUID("00000000-0000-4000-8000-000000001001")
USER = UUID("00000000-0000-4000-8000-000000001002")
OTHER = UUID("00000000-0000-4000-8000-000000001003")
SOURCE = UUID("00000000-0000-4000-8000-000000001004")
TARGET = UUID("00000000-0000-4000-8000-000000001005")
VISIBLE = UUID("00000000-0000-4000-8000-000000001006")
HIDDEN = UUID("00000000-0000-4000-8000-000000001007")
LINK = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000001008"),
    label="Related",
    type="link",
    link_table_id=TARGET,
)
ASSIGNEE = ColumnDef(id=UUID("00000000-0000-4000-8000-000000001009"), label="Assignee", type="user")
NAME = ColumnDef(id=UUID("00000000-0000-4000-8000-000000001010"), label="Name", type="text")
KEY = str(LINK.id)
POLICY = RowPolicy(rule="assignee", view_column_id=ASSIGNEE.id, edit_column_id=ASSIGNEE.id)


def context(role: str = "member") -> AuthContext:
    return AuthContext(user_id=USER, organization_id=ORG, role=role)


def table() -> VirtualTable:
    return VirtualTable(
        id=TARGET,
        organization_id=ORG,
        owner_user_id=OTHER,
        name="Destinations",
        visibility="org",
        schema_version=1,
        row_policy=POLICY.model_dump(mode="json"),
        created_at=datetime.now(UTC),
    )


def record(values: dict[str, CellValue] | None = None) -> RecordRead:
    return RecordRead(
        id=uuid4(),
        table_id=SOURCE,
        schema_version=1,
        values={KEY: [str(VISIBLE), str(HIDDEN)]} if values is None else values,
        revision=1,
        created_at=datetime.now(UTC),
    )


@pytest.fixture
def linked_data(monkeypatch: pytest.MonkeyPatch) -> VirtualTable:
    target = table()
    rows = [
        VirtualTableRecord(
            id=record_id,
            organization_id=ORG,
            table_id=TARGET,
            schema_version=1,
            values={str(NAME.id): name, str(ASSIGNEE.id): str(assignee)},
        )
        for record_id, assignee, name in (
            (VISIBLE, USER, "Visible destination"),
            (HIDDEN, OTHER, "Restricted destination"),
        )
    ]
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=target))
    monkeypatch.setattr(
        virtual_table_repo,
        "get_schema_version",
        AsyncMock(
            return_value=MagicMock(
                columns=[column.model_dump(mode="json") for column in (NAME, ASSIGNEE)]
            )
        ),
    )
    monkeypatch.setattr(virtual_table_repo, "get_records_by_ids", AsyncMock(return_value=rows))
    monkeypatch.setattr(virtual_table_repo, "get_record_cells_by_ids", AsyncMock(return_value=rows))
    monkeypatch.setattr(computed, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(records, "resolve_access", AsyncMock(return_value=True))
    return target


async def test_the_complete_response_and_labelled_payload_omit_hidden_link_ids(linked_data):
    from app.services.virtual_tables.presentation import labelled

    original = record()
    result = (await computed.read_through(MagicMock(), context(), [LINK], [original]))[0]
    assert result.values[KEY] == [str(VISIBLE)]
    assert str(HIDDEN) not in result.model_dump_json()
    assert "Restricted destination" not in result.model_dump_json()
    source = Operations._read(table(), [LINK], can_edit=False)
    assert str(HIDDEN) not in str(labelled(source, result))
    assert original.values[KEY] == [str(VISIBLE), str(HIDDEN)]


async def test_an_inaccessible_linked_table_exposes_no_ids_or_csv_fallback(
    linked_data, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(computed, "resolve_access", AsyncMock(return_value=False))
    result = (await computed.read_through(MagicMock(), context(), [LINK], [record()]))[0]
    assert result.values[KEY] == []
    assert str(VISIBLE) not in result.model_dump_json()
    assert str(HIDDEN) not in result.model_dump_json()
    assert _export_cell(LINK, result) == ""


def test_export_never_uses_unprojected_link_values():
    assert _export_cell(LINK, record()) == ""


@pytest.mark.parametrize("archived", [False, True])
async def test_unresolved_or_archived_link_fields_do_not_leave_raw_arrays(archived: bool):
    column = LINK.model_copy(update={"archived": archived})
    result = (
        await computed.read_through(MagicMock(), context(), [column], [record()], linked_keys={})
    )[0]
    assert KEY not in result.values
    assert str(HIDDEN) not in result.model_dump_json()


async def test_projected_link_reads_redact_raw_ids_too(linked_data):
    result = (
        await computed.read_through(
            MagicMock(), context(), [LINK], [record()], linked_keys={TARGET: frozenset()}
        )
    )[0]
    assert result.values[KEY] == [str(VISIBLE)]
    assert str(HIDDEN) not in result.model_dump_json()


async def test_invalid_destination_policy_is_unavailable_even_to_a_bypass_role(linked_data):
    linked_data.row_policy = {"rule": "unexpected"}
    result = (await computed.read_through(MagicMock(), context("owner"), [LINK], [record()]))[0]
    assert result.values[KEY] == []
    assert result.links == {}
    assert str(HIDDEN) not in result.model_dump_json()


@pytest.mark.parametrize("role", ["member", "owner"])
async def test_invalid_source_policy_refuses_read_write_and_query(role: str):
    source = table()
    source.row_policy = {"rule": "assignee"}
    for operation in (may_view_row, may_edit_row):
        with pytest.raises(InvalidRowPolicyError):
            await operation(MagicMock(), context(role), source, [ASSIGNEE], {})
    with pytest.raises(InvalidRowPolicyError):
        await view_expression(MagicMock(), context(role), source, [ASSIGNEE])


@pytest.mark.parametrize("operation", ["create", "write"])
async def test_invalid_policy_refuses_batch_before_write_or_receipt(
    operation: str, monkeypatch: pytest.MonkeyPatch
):
    source = table()
    source.row_policy = {"rule": "unexpected"}
    service = RecordOperations(MagicMock())
    monkeypatch.setattr(service, "_load_table", AsyncMock(return_value=source))
    replay = AsyncMock()
    storage = AsyncMock()
    monkeypatch.setattr(records, "run_once", replay)
    monkeypatch.setattr(records.quotas, "lock_storage", storage)
    batch = RecordBatchCreate(records=[RecordCreate(values={})])
    action = service.create_records if operation == "create" else service.write_batch

    with pytest.raises(InvalidRowPolicyError):
        await action(context("owner"), source.id, batch)

    replay.assert_not_awaited()
    storage.assert_not_awaited()


async def test_batch_import_hides_conflict_metadata_for_an_unreadable_external_id(
    monkeypatch: pytest.MonkeyPatch,
):
    source = table()
    now = datetime.now(UTC)
    hidden = VirtualTableRecord(
        id=HIDDEN,
        organization_id=ORG,
        table_id=source.id,
        external_id="known-external-id",
        schema_version=1,
        values={str(ASSIGNEE.id): str(OTHER)},
        revision=7,
        created_at=now,
        updated_at=now,
    )
    service = RecordOperations(MagicMock())
    monkeypatch.setattr(service, "_lookup", AsyncMock(return_value=hidden))
    monkeypatch.setattr(service, "_columns", AsyncMock(return_value=[ASSIGNEE]))
    apply = AsyncMock()
    monkeypatch.setattr(service, "_apply", apply)
    monkeypatch.setattr(records.quotas, "lock_record_count", AsyncMock())

    with pytest.raises(NotFoundError) as refused:
        await service._create_one(
            context(),
            source,
            RecordCreate(external_id="known-external-id", values={}),
            update=True,
            as_of=now - timedelta(seconds=1),
        )

    assert refused.value.details == {"table_id": source.id}
    assert str(HIDDEN) not in str(refused.value)
    apply.assert_not_awaited()


def test_invalid_policy_metadata_remains_available_for_authorized_repair():
    source = table()
    source.row_policy = {"rule": "unexpected"}
    result = Operations._read(source, [ASSIGNEE], can_edit=True)
    assert result.row_policy is None
    assert result.row_policy_valid is False
    assert result.can_edit is True


def test_policy_errors_do_not_repeat_the_stored_document(caplog: pytest.LogCaptureFixture):
    with pytest.raises(InvalidRowPolicyError) as refused:
        parse_policy({"rule": "unexpected", "sensitive": "private-policy-value"})
    assert refused.value.code == "ROW_POLICY_INVALID"
    assert refused.value.status_code == 409
    assert "private-policy-value" not in str(refused.value)
    assert "private-policy-value" not in caplog.text


async def test_an_invalid_project_policy_grants_no_inherited_access(linked_data):
    linked_data.row_policy = {"rule": "unexpected"}
    policy = POLICY.model_copy(
        update={
            "view_project_link_column_id": LINK.id,
            "view_projects_table_id": TARGET,
            "view_project_members_column_id": ASSIGNEE.id,
        }
    )
    assert await visible_project_ids(MagicMock(), context(), policy) == []


@pytest.mark.parametrize("submitted", [[str(VISIBLE)], [], None])
async def test_legacy_replacement_preserves_hidden_existing_links(linked_data, submitted):
    before: dict[str, CellValue] = {KEY: [str(VISIBLE), str(HIDDEN)]}
    requested: dict[str, CellValue] = {KEY: submitted}
    merged = _merge([LINK], requested, before)
    await RecordOperations(MagicMock())._preserve_unreadable_links(
        context(), [LINK], requested, before, merged
    )
    assert str(HIDDEN) in merged[KEY]
    assert (str(VISIBLE) in merged[KEY]) is (submitted == [str(VISIBLE)])
    assert before == {KEY: [str(VISIBLE), str(HIDDEN)]}
    assert requested == {KEY: submitted}


async def test_legacy_replacement_preserves_all_links_when_target_is_unreachable(
    linked_data, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(computed, "resolve_access", AsyncMock(return_value=False))
    before: dict[str, CellValue] = {KEY: [str(VISIBLE), str(HIDDEN)]}
    merged = _merge([LINK], {KEY: []}, before)
    await RecordOperations(MagicMock())._preserve_unreadable_links(
        context(), [LINK], {KEY: []}, before, merged
    )
    assert merged == before


async def test_removing_only_visible_links_preserves_nothing(linked_data):
    before: dict[str, CellValue] = {KEY: [str(VISIBLE)]}
    requested: dict[str, CellValue] = {KEY: []}
    merged = _merge([LINK], requested, before)
    await RecordOperations(MagicMock())._preserve_unreadable_links(
        context(), [LINK], requested, before, merged
    )
    assert not merged[KEY]


@pytest.mark.parametrize("hidden_first", [False, True])
async def test_a_visible_array_round_trip_preserves_hidden_positions(linked_data, hidden_first):
    old = [str(HIDDEN), str(VISIBLE)] if hidden_first else [str(VISIBLE), str(HIDDEN)]
    before: dict[str, CellValue] = {KEY: old}
    requested: dict[str, CellValue] = {KEY: [str(VISIBLE)]}
    merged = _merge([LINK], requested, before)
    await RecordOperations(MagicMock())._preserve_unreadable_links(
        context(), [LINK], requested, before, merged
    )
    assert merged == before


async def test_an_unrelated_field_update_keeps_the_complete_link_set(linked_data):
    before: dict[str, CellValue] = {KEY: [str(VISIBLE), str(HIDDEN)], str(NAME.id): "Old"}
    requested: dict[str, CellValue] = {str(NAME.id): "New"}
    merged = _merge([LINK, NAME], requested, before)
    await RecordOperations(MagicMock())._preserve_unreadable_links(
        context(), [LINK, NAME], requested, before, merged
    )
    assert merged == {KEY: [str(VISIBLE), str(HIDDEN)], str(NAME.id): "New"}


async def test_omitted_hidden_ids_are_not_submitted_on_the_callers_behalf(
    linked_data, monkeypatch: pytest.MonkeyPatch
):
    access = AsyncMock(return_value=False)
    monkeypatch.setattr(records, "resolve_access", access)
    await RecordOperations(MagicMock())._check_links(context(), [LINK], {KEY: []})
    access.assert_not_awaited()


@pytest.mark.parametrize("was_linked", [False, True])
async def test_explicit_hidden_ids_are_refused_even_when_the_update_would_be_a_noop(
    linked_data, monkeypatch: pytest.MonkeyPatch, was_linked: bool
):
    before: dict[str, CellValue] = {KEY: [str(HIDDEN)]} if was_linked else {}
    original = VirtualTableRecord(
        id=uuid4(),
        organization_id=ORG,
        table_id=SOURCE,
        schema_version=1,
        revision=1,
        values=before.copy(),
        created_at=datetime.now(UTC),
    )
    service = RecordOperations(MagicMock())
    monkeypatch.setattr(service, "_columns", AsyncMock(return_value=[LINK]))
    monkeypatch.setattr(records, "may_edit_row", AsyncMock(return_value=True))
    monkeypatch.setattr(
        records, "normalize_task_cells", AsyncMock(return_value={KEY: [str(HIDDEN)]})
    )

    with pytest.raises(InvalidRecordError):
        await service._apply(context(), linked_data, original, {KEY: [str(HIDDEN)]}, 1)

    assert original.values == before
    assert original.revision == 1


async def test_hidden_and_unknown_submitted_link_ids_have_the_same_error(linked_data, monkeypatch):
    operations = RecordOperations(MagicMock())
    rows = virtual_table_repo.get_records_by_ids.return_value
    hidden_row = next(row for row in rows if row.id == HIDDEN)
    errors = []
    for record_id, matching_rows in ((HIDDEN, [hidden_row]), (uuid4(), [])):
        monkeypatch.setattr(
            virtual_table_repo, "get_records_by_ids", AsyncMock(return_value=matching_rows)
        )
        with pytest.raises(InvalidRecordError) as refused:
            await operations._check_links(context(), [LINK], {KEY: [str(record_id)]})
        errors.append(refused.value.details)
    assert errors[0] == errors[1]
    assert str(HIDDEN) not in str(errors[0])


async def test_a_visible_already_linked_id_is_still_validated(linked_data, monkeypatch):
    rows = virtual_table_repo.get_records_by_ids.return_value
    visible_row = next(row for row in rows if row.id == VISIBLE)
    check = AsyncMock(return_value=[visible_row])
    monkeypatch.setattr(virtual_table_repo, "get_records_by_ids", check)
    await RecordOperations(MagicMock())._check_links(context(), [LINK], {KEY: [str(VISIBLE)]})
    check.assert_awaited_once()


async def test_unchanged_links_need_no_destination_read_for_preservation(linked_data, monkeypatch):
    check = AsyncMock()
    monkeypatch.setattr(records, "visible_link_ids", check)
    before: dict[str, CellValue] = {KEY: [str(VISIBLE), str(HIDDEN)]}
    merged = _merge([LINK], before, before)
    await RecordOperations(MagicMock())._preserve_unreadable_links(
        context(), [LINK], before, before, merged
    )
    assert merged == before
    check.assert_not_awaited()


async def test_inaccessible_target_does_not_create_an_absent_link_cell(linked_data, monkeypatch):
    monkeypatch.setattr(computed, "resolve_access", AsyncMock(return_value=False))
    original = record({str(NAME.id): "Unchanged"})
    result = (await computed.read_through(MagicMock(), context(), [LINK, NAME], [original]))[0]
    assert result.values == original.values
    assert KEY not in result.values


async def test_new_hidden_ids_still_cannot_be_added(linked_data):
    with pytest.raises(InvalidRecordError):
        await RecordOperations(MagicMock())._check_links(context(), [LINK], {KEY: [str(HIDDEN)]})


async def test_hidden_preservation_still_enforces_the_final_cell_limit(
    linked_data, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(computed, "resolve_access", AsyncMock(return_value=False))
    before: dict[str, CellValue] = {KEY: [str(uuid4()) for _ in range(100)]}
    requested: dict[str, CellValue] = {KEY: [str(VISIBLE)]}
    merged = _merge([LINK], requested, before)
    with pytest.raises(InvalidRecordError):
        await RecordOperations(MagicMock())._preserve_unreadable_links(
            context(), [LINK], requested, before, merged
        )
