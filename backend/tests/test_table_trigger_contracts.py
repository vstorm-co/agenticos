"""A table trigger's filter evaluator, and the reads the end-to-end suite leaves (#1785).

`holds` has to say of a record what the record query's SQL says of the same row,
or a trigger and a filtered view disagree about which records match; each case
here is one branch of `_predicate` in `app/repositories/virtual_table.py`.
"""

import uuid
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.resource_grant import GrantLevel
from app.repositories import resource_grant_repo
from app.repositories import virtual_table_trigger as trigger_repo
from app.schemas.virtual_table import ColumnDef, ColumnTypeName, FilterOp, RecordFilter
from app.services.virtual_tables import triggers as trigger_module
from app.services.virtual_tables.computed import visible_link_ids
from app.services.virtual_tables.triggers import TableTriggerService, _checked_filters, holds

pytestmark = pytest.mark.anyio


def _case(type_: ColumnTypeName, op: FilterOp, operand: Any, cell: Any) -> bool:
    column = ColumnDef(id=uuid.uuid4(), label="C", type=type_)
    values = {} if cell is None else {str(column.id): cell}
    return holds(column, RecordFilter(column_id=column.id, op=op, value=operand), values)


@pytest.mark.parametrize(
    ("type_", "op", "operand", "cell", "expected"),
    [
        ("text", "is_null", True, None, True),
        ("text", "is_null", False, None, False),
        ("text", "is_null", False, "a", True),
        ("text", "eq", "a", None, False),
        ("text", "ne", "a", None, False),
        ("text", "eq", "a", "a", True),
        ("text", "ne", "a", "b", True),
        ("text", "contains", "DA", "ada", True),
        ("text", "contains", "x", "ada", False),
        ("text", "starts_with", "Ad", "Ada", True),
        ("text", "starts_with", "ad", "Ada", False),
        ("single_select", "in", ["o1", "o2"], "o2", True),
        ("single_select", "in", ["o1"], "o2", False),
        ("single_select", "in", "not-a-list", "o1", False),
        ("multi_select", "contains", "o1", ["o1", "o2"], True),
        ("multi_select", "contains", "o3", ["o1", "o2"], False),
        ("integer", "gt", 80, 90, True),
        ("integer", "gte", 90, 90, True),
        ("integer", "lt", 80, 90, False),
        ("integer", "lte", 90, 90, True),
        ("number", "eq", 1.5, 1.50, True),
        ("number", "in", [1, 2.5], 2.5, True),
        ("date", "lt", "2026-09-30", "2026-09-29", True),
        ("date", "gt", "2026-09-30", "2026-09-29", False),
        ("datetime", "gte", "2026-09-29T10:30:00+00:00", "2026-09-29T12:00:00+02:00", False),
        ("datetime", "gte", "2026-09-29T10:00:00+00:00", "2026-09-29T11:00:00+00:00", True),
        ("boolean", "eq", True, True, True),
        ("boolean", "eq", True, False, False),
    ],
)
def test_a_filter_holds_where_the_record_query_would_match(
    type_: ColumnTypeName, op: FilterOp, operand: Any, cell: Any, expected: bool
) -> None:
    assert _case(type_, op, operand, cell) is expected


async def test_the_admissions_page_counts_and_lists() -> None:
    row = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [row]
    db = MagicMock(scalar=AsyncMock(return_value=3), execute=AsyncMock(return_value=result))

    assert await trigger_repo.list_admissions(db, trigger_id=uuid.uuid4(), skip=0, limit=10) == (
        [row],
        3,
    )


async def test_the_service_reads_a_triggers_admissions_through_its_table() -> None:
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
    service = TableTriggerService(MagicMock())
    trigger = MagicMock(id=uuid.uuid4())
    with (
        patch.object(service, "_load_table", new=AsyncMock(return_value=MagicMock())),
        patch.object(service, "_trigger", new=AsyncMock(return_value=trigger)),
        patch.object(
            trigger_repo, "list_admissions", new=AsyncMock(return_value=([], 0))
        ) as listed,
    ):
        page = await service.admissions(ctx, uuid.uuid4(), trigger.id, skip=5, limit=10)

    assert (page.items, page.total) == ([], 0)
    listed.assert_awaited_once_with(service.db, trigger_id=trigger.id, skip=5, limit=10)


def test_a_filter_that_stopped_fitting_since_publish_validated_it_is_refused() -> None:
    """Publishing checks the filters before it takes the table's lock; a column
    archived in between is refused here, when the trigger is written."""
    score = ColumnDef(id=uuid.uuid4(), label="Score", type="integer")
    gone = ColumnDef(id=uuid.uuid4(), label="Gone", type="text", archived=True)
    with pytest.raises(BadRequestError) as missing:
        _checked_filters([score, gone], [RecordFilter(column_id=gone.id, op="eq", value="x")])
    assert missing.value.details == {"field": "filters.0.column_id"}
    with pytest.raises(BadRequestError) as misfit:
        _checked_filters([score], [RecordFilter(column_id=score.id, op="contains", value=1)])
    assert misfit.value.details == {"field": "filters.0"}
    assert _checked_filters([score], [RecordFilter(column_id=score.id, op="gt", value=7)]) == [
        {"column_id": str(score.id), "op": "gt", "value": 7}
    ]


@pytest.mark.security
@pytest.mark.parametrize("active", [None, False])
async def test_background_authority_refuses_a_user_lost_after_membership_read(monkeypatch, active):
    import importlib
    from types import SimpleNamespace

    module = importlib.import_module("app.services.virtual_tables.triggers")
    monkeypatch.setattr(
        module.member_repo, "get_active", AsyncMock(return_value=SimpleNamespace(role="viewer"))
    )
    user = None if active is None else SimpleNamespace(is_active=False, is_app_admin=True)
    monkeypatch.setattr(module.user_repo, "get_by_id", AsyncMock(return_value=user))
    exposure = SimpleNamespace(
        execution_principal_user_id=uuid.uuid4(), organization_id=uuid.uuid4()
    )
    assert (
        await module.TableTriggerConsumer(MagicMock())._fire_context(exposure, MagicMock()) is None
    )


# -- row-level access on trigger admissions -----------------------------------
#
# A trigger must not hand a workflow run a record its publisher cannot see:
# the run input would disclose the row even though later node reads are
# filtered. Such an event is FILTERED with reason `row_policy`, not FAILED.

from datetime import UTC as _UTC
from datetime import datetime as _datetime
from types import SimpleNamespace

from app.db.models.virtual_table_trigger import AdmissionReason as _AdmissionReason
from app.db.models.virtual_table_trigger import AdmissionStatus as _AdmissionStatus
from app.repositories import virtual_table_repo as _vt_repo
from app.schemas.virtual_table import RowPolicy as _RowPolicy
from app.services.virtual_tables.triggers import TableTriggerConsumer as _Consumer
from app.services.virtual_tables.triggers import _Happened as _Happened

_TRIGGER_TABLE = uuid.uuid4()
_TRIGGER_ID = uuid.uuid4()
_TRIGGER_EVENT = uuid.uuid4()
_TRIGGER_RUN = uuid.uuid4()
_TRIGGER_ENTRY = uuid.uuid4()
_TRIGGER_NODE = uuid.uuid4()
_TRIGGER_ASSIGNEE = uuid.uuid4()
_TRIGGER_MEMBER = uuid.uuid4()
_TRIGGER_OTHER = uuid.uuid4()
_TRIGGER_ORG = uuid.uuid4()
_TRIGGER_POLICY = _RowPolicy(
    rule="assignee",
    view_column_id=_TRIGGER_ASSIGNEE,
    edit_column_id=_TRIGGER_ASSIGNEE,
)
_TRIGGER_COLUMN = ColumnDef(id=_TRIGGER_ASSIGNEE, label="Assignee", type="user")


def _trigger_decide_setup(monkeypatch, *, values, role="member"):
    consumer = _Consumer(MagicMock())
    trigger = SimpleNamespace(
        id=_TRIGGER_ID,
        revision=3,
        organization_id=_TRIGGER_ORG,
        activated_at=_datetime(2026, 1, 1, tzinfo=_UTC),
        watched_column_ids=[],
        filters=[],
        node_instance_id=_TRIGGER_NODE,
        table_id=_TRIGGER_TABLE,
    )
    event = SimpleNamespace(
        id=_TRIGGER_EVENT,
        organization_id=_TRIGGER_ORG,
        table_id=_TRIGGER_TABLE,
        record_id=uuid.uuid4(),
        created_at=_datetime(2026, 6, 1, tzinfo=_UTC),
        event_type="table.record.created",
        payload={},
    )
    snapshot = _Happened(
        event="created",
        values={str(_TRIGGER_ASSIGNEE): values},
        before=None,
        author_id=_TRIGGER_MEMBER,
    )
    table = SimpleNamespace(
        id=_TRIGGER_TABLE,
        organization_id=_TRIGGER_ORG,
        owner_user_id=_TRIGGER_OTHER,
        row_policy=_TRIGGER_POLICY.model_dump(mode="json"),
        schema_version=1,
    )
    ctx = AuthContext(user_id=_TRIGGER_MEMBER, organization_id=_TRIGGER_ORG, role=role)
    admitted = AsyncMock()
    monkeypatch.setattr(_vt_repo, "get_table", AsyncMock(return_value=table))
    monkeypatch.setattr(trigger_repo, "add_admission", admitted)
    monkeypatch.setattr(resource_grant_repo, "record_levels", AsyncMock(return_value={}))
    monkeypatch.setattr(
        _Consumer, "_columns", AsyncMock(return_value={_TRIGGER_ASSIGNEE: _TRIGGER_COLUMN})
    )
    monkeypatch.setattr(
        _Consumer,
        "_fire_context",
        AsyncMock(return_value=(ctx, SimpleNamespace(), SimpleNamespace())),
    )
    consumer.runs = MagicMock()
    consumer.runs.admit_pinned = AsyncMock(
        return_value=(SimpleNamespace(id=_TRIGGER_RUN), _TRIGGER_ENTRY)
    )
    return consumer, trigger, event, snapshot, admitted


async def test_a_trigger_does_not_fire_for_a_row_its_publisher_cannot_see(monkeypatch):
    consumer, trigger, event, snapshot, admitted = _trigger_decide_setup(
        monkeypatch, values=str(_TRIGGER_OTHER)
    )

    assert await consumer._decide(trigger, event, snapshot, None) is None
    consumer.runs.admit_pinned.assert_not_awaited()
    admitted.assert_awaited_once()
    assert admitted.await_args.kwargs["status"] == _AdmissionStatus.FILTERED.value
    assert admitted.await_args.kwargs["reason"] == _AdmissionReason.ROW_POLICY.value


async def test_a_trigger_fires_for_a_row_its_publisher_can_see(monkeypatch):
    consumer, trigger, event, snapshot, admitted = _trigger_decide_setup(
        monkeypatch, values=str(_TRIGGER_MEMBER)
    )

    assert await consumer._decide(trigger, event, snapshot, None) == (
        _TRIGGER_RUN,
        _TRIGGER_ENTRY,
    )
    assert admitted.await_args.kwargs["status"] == _AdmissionStatus.QUEUED.value
    assert admitted.await_args.kwargs["reason"] is None


async def test_a_trigger_fires_for_a_bypass_publisher_on_any_row(monkeypatch):
    consumer, trigger, event, snapshot, admitted = _trigger_decide_setup(
        monkeypatch, values=str(_TRIGGER_OTHER), role="owner"
    )

    assert await consumer._decide(trigger, event, snapshot, None) == (
        _TRIGGER_RUN,
        _TRIGGER_ENTRY,
    )


@pytest.mark.parametrize("level", [GrantLevel.READ, GrantLevel.EDIT, None])
async def test_a_trigger_honours_the_publishers_current_explicit_row_grant(monkeypatch, level):
    consumer, trigger, event, snapshot, admitted = _trigger_decide_setup(
        monkeypatch, values=str(_TRIGGER_OTHER)
    )
    grants = AsyncMock(return_value={} if level is None else {event.record_id: level})
    monkeypatch.setattr(resource_grant_repo, "record_levels", grants)

    result = await consumer._decide(trigger, event, snapshot, None)

    grants.assert_awaited_once_with(
        consumer.db,
        organization_id=_TRIGGER_ORG,
        subject_user_id=_TRIGGER_MEMBER,
        record_ids=[event.record_id],
    )
    if level is None:
        assert result is None
        consumer.runs.admit_pinned.assert_not_awaited()
        assert admitted.await_args.kwargs["reason"] == _AdmissionReason.ROW_POLICY.value
    else:
        assert result == (_TRIGGER_RUN, _TRIGGER_ENTRY)
        assert admitted.await_args.kwargs["status"] == _AdmissionStatus.QUEUED.value


_VISIBLE_LINK = str(uuid.uuid4())
_HIDDEN_BEFORE = str(uuid.uuid4())
_HIDDEN_AFTER = str(uuid.uuid4())


def _trigger_links_setup(monkeypatch):
    consumer, trigger, event, snapshot, admitted = _trigger_decide_setup(
        monkeypatch, values=str(_TRIGGER_MEMBER)
    )
    link = ColumnDef(id=uuid.uuid4(), label="Links", type="link", link_table_id=uuid.uuid4())
    archived = ColumnDef(
        id=uuid.uuid4(),
        label="Old links",
        type="link",
        link_table_id=link.link_table_id,
        archived=True,
    )
    title = ColumnDef(id=uuid.uuid4(), label="Title", type="text")
    columns = {column.id: column for column in (_TRIGGER_COLUMN, title, link, archived)}
    monkeypatch.setattr(_Consumer, "_columns", AsyncMock(return_value=columns))
    targets = AsyncMock(return_value={_VISIBLE_LINK})
    monkeypatch.setattr(trigger_module, "visible_link_ids", targets)
    return SimpleNamespace(
        consumer=consumer,
        trigger=trigger,
        event=event,
        snapshot=snapshot,
        admitted=admitted,
        link=link,
        archived=archived,
        title=title,
        targets=targets,
    )


async def test_trigger_payload_projects_both_snapshots_without_changing_stored_evidence(
    monkeypatch,
):
    setup = _trigger_links_setup(monkeypatch)
    link, archived, title = str(setup.link.id), str(setup.archived.id), str(setup.title.id)
    before = {
        **setup.snapshot.values,
        title: "Before",
        link: [_VISIBLE_LINK, _HIDDEN_BEFORE],
        archived: [_HIDDEN_BEFORE],
    }
    values = {
        **setup.snapshot.values,
        title: "After",
        link: [_VISIBLE_LINK, _HIDDEN_AFTER],
        archived: [_HIDDEN_AFTER],
    }
    original = deepcopy((before, values))
    snapshot = _Happened(event="updated", values=values, before=before, author_id=_TRIGGER_MEMBER)

    assert await setup.consumer._decide(setup.trigger, setup.event, snapshot, None) is not None
    payload = setup.consumer.runs.admit_pinned.await_args.kwargs["run_input"]
    assert payload["values"][link] == payload["before"][link] == [_VISIBLE_LINK]
    assert archived not in payload["values"] and archived not in payload["before"]
    assert payload["changed"] == ["Title"]
    assert _HIDDEN_BEFORE not in str(payload) and _HIDDEN_AFTER not in str(payload)
    assert (before, values) == original
    setup.targets.assert_awaited_once()
    assert setup.targets.await_args.args[3] == {_VISIBLE_LINK, _HIDDEN_BEFORE, _HIDDEN_AFTER}


@pytest.mark.parametrize("watched", [True, False])
@pytest.mark.parametrize(
    "before_links", [None, [], [_HIDDEN_BEFORE], [_VISIBLE_LINK, _HIDDEN_BEFORE]]
)
async def test_hidden_only_link_changes_do_not_admit_a_trigger(monkeypatch, watched, before_links):
    setup = _trigger_links_setup(monkeypatch)
    key = str(setup.link.id)
    setup.trigger.watched_column_ids = [key] if watched else []
    after_links = (
        [_VISIBLE_LINK, _HIDDEN_AFTER]
        if before_links and _VISIBLE_LINK in before_links
        else [_HIDDEN_AFTER]
    )
    snapshot = _Happened(
        event="updated",
        values={**setup.snapshot.values, key: after_links},
        before={**setup.snapshot.values, key: before_links},
        author_id=_TRIGGER_MEMBER,
    )

    assert await setup.consumer._decide(setup.trigger, setup.event, snapshot, None) is None
    setup.consumer.runs.admit_pinned.assert_not_awaited()
    assert setup.admitted.await_args.kwargs["reason"] == _AdmissionReason.FILTER_MISMATCH.value


@pytest.mark.parametrize(
    ("op", "operand", "links", "fires"),
    [
        ("contains", _HIDDEN_AFTER, [_VISIBLE_LINK, _HIDDEN_AFTER], False),
        ("contains", _VISIBLE_LINK, [_VISIBLE_LINK, _HIDDEN_AFTER], True),
        ("is_null", False, [_HIDDEN_AFTER], False),
        ("is_null", True, [_HIDDEN_AFTER], True),
    ],
    ids=["hidden-destination", "readable-destination", "hidden-is-empty", "hidden-is-null"],
)
async def test_trigger_link_filters_only_examine_readable_destinations(
    monkeypatch, op, operand, links, fires
):
    setup = _trigger_links_setup(monkeypatch)
    setup.trigger.filters = [
        RecordFilter(column_id=setup.link.id, op=op, value=operand).model_dump(mode="json")
    ]
    snapshot = _Happened(
        event="created",
        values={**setup.snapshot.values, str(setup.link.id): links},
        before=None,
        author_id=_TRIGGER_MEMBER,
    )

    result = await setup.consumer._decide(setup.trigger, setup.event, snapshot, None)
    assert (result is not None) is fires
    if not fires:
        setup.consumer.runs.admit_pinned.assert_not_awaited()
        assert setup.admitted.await_args.kwargs["reason"] == _AdmissionReason.FILTER_MISMATCH.value


async def test_a_trigger_redacts_both_snapshots_when_the_destination_policy_is_invalid(monkeypatch):
    setup = _trigger_links_setup(monkeypatch)
    source = _vt_repo.get_table.return_value
    destination = SimpleNamespace(
        id=setup.link.link_table_id,
        schema_version=1,
        row_policy={"rule": "assignee"},
        owner_user_id=None,
    )
    _vt_repo.get_table.side_effect = lambda db, table_id, **_: (
        source if table_id == _TRIGGER_TABLE else destination
    )
    monkeypatch.setattr(
        _vt_repo, "get_schema_version", AsyncMock(return_value=SimpleNamespace(columns=[]))
    )
    monkeypatch.setattr(
        "app.services.virtual_tables.computed.resolve_access", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(trigger_module, "visible_link_ids", visible_link_ids)
    queried = AsyncMock(
        side_effect=AssertionError("invalid target policy must prevent its row read")
    )
    monkeypatch.setattr(_vt_repo, "get_record_cells_by_ids", queried)
    key, title = str(setup.link.id), str(setup.title.id)
    snapshot = _Happened(
        event="updated",
        values={**setup.snapshot.values, key: [_HIDDEN_AFTER], title: "After"},
        before={**setup.snapshot.values, key: [_HIDDEN_BEFORE], title: "Before"},
        author_id=_TRIGGER_MEMBER,
    )

    assert await setup.consumer._decide(setup.trigger, setup.event, snapshot, None) is not None
    payload = setup.consumer.runs.admit_pinned.await_args.kwargs["run_input"]
    assert payload["values"][key] == payload["before"][key] == []
    assert payload["changed"] == ["Title"]
    queried.assert_not_awaited()


async def test_an_invalid_source_policy_filters_the_event_before_projection(monkeypatch):
    setup = _trigger_links_setup(monkeypatch)
    _vt_repo.get_table.return_value.row_policy = {"rule": "unknown"}

    assert await setup.consumer._decide(setup.trigger, setup.event, setup.snapshot, None) is None
    setup.targets.assert_not_awaited()
    setup.consumer.runs.admit_pinned.assert_not_awaited()
    assert setup.admitted.await_args.kwargs["reason"] == _AdmissionReason.ROW_POLICY.value
