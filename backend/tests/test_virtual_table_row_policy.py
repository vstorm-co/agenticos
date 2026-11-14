"""Row-level access: the policy document, its evaluation, and its SQL form.

Unit tests, with the database stubbed out: the predicate's SQL is checked by
compiling it for PostgreSQL, never by executing it - there is no database
here. The end-to-end behaviour (the compiled predicate returns the right
rows) belongs to the integration suite.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.permissions import AuthContext
from app.db.models.virtual_table import VirtualTable
from app.repositories import virtual_table_repo
from app.repositories.virtual_table import FilterClause, SqlKind, _matching, policy_expression
from app.schemas.virtual_table import ColumnDef, RowPolicy, RowPolicyUpdate, TableRead
from app.services.virtual_tables import row_policy
from app.services.virtual_tables._base import Operations
from app.services.virtual_tables.deadline import ReadDeadline
from app.services.virtual_tables.exceptions import DeadlineReached
from app.services.virtual_tables.row_policy import (
    bypasses_policy,
    may_edit_row,
    may_view_row,
    parse_policy,
    row_matches,
    view_expression,
    visible_project_ids,
)

pytestmark = pytest.mark.anyio

ORG = UUID("00000000-0000-4000-8000-000000000001")
OWNER = UUID("00000000-0000-4000-8000-000000000002")
MEMBER = UUID("00000000-0000-4000-8000-000000000003")
OTHER = UUID("00000000-0000-4000-8000-000000000004")
ASSIGNEE = UUID("00000000-0000-4000-8000-000000000010")
PROJECT_LINK = UUID("00000000-0000-4000-8000-000000000011")
PROJECTS_TABLE = UUID("00000000-0000-4000-8000-000000000012")
MEMBERS = UUID("00000000-0000-4000-8000-000000000013")
PROJECT_A = UUID("00000000-0000-4000-8000-000000000014")
PROJECT_B = UUID("00000000-0000-4000-8000-000000000015")
TABLE_ID = UUID("00000000-0000-4000-8000-000000000016")

ASSIGNEE_COL = ColumnDef(id=ASSIGNEE, label="Assignee", type="user")
ASSIGNEES_COL = ColumnDef(id=ASSIGNEE, label="Assignees", type="multi_user")
LINK_COL = ColumnDef(id=PROJECT_LINK, label="Project", type="link", link_table_id=PROJECTS_TABLE)
MEMBERS_COL = ColumnDef(id=MEMBERS, label="Members", type="multi_user")
TEXT_COL = ColumnDef(id=UUID("00000000-0000-4000-8000-000000000017"), label="Title", type="text")
ARCHIVED_COL = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000018"),
    label="Old assignee",
    type="user",
    archived=True,
)

POLICY = RowPolicy(rule="assignee", view_column_id=ASSIGNEE, edit_column_id=ASSIGNEE)
PROJECT_POLICY = RowPolicy(
    rule="assignee",
    view_column_id=ASSIGNEE,
    edit_column_id=ASSIGNEE,
    view_project_link_column_id=PROJECT_LINK,
    view_projects_table_id=PROJECTS_TABLE,
    view_project_members_column_id=MEMBERS,
)


def _ctx(user_id: UUID | None, role: str = "member", *, admin: bool = False) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=ORG, role=role, is_app_admin=admin)


def _table(policy: RowPolicy | None, *, owner: UUID | None = OWNER) -> VirtualTable:
    table = VirtualTable(
        organization_id=ORG,
        owner_user_id=owner,
        name="Tasks",
        visibility="private",
        schema_version=1,
        created_at=datetime.now(UTC),
    )
    table.id = TABLE_ID
    table.row_policy = None if policy is None else policy.model_dump(mode="json")
    return table


def _sql(expression) -> str:
    return str(expression.compile(dialect=postgresql.dialect()))


# -- the policy document ------------------------------------------------------


def test_clearing_a_policy_needs_no_columns_but_an_assignee_policy_names_both():
    assert RowPolicyUpdate(rule="none").rule == "none"
    with pytest.raises(ValidationError):
        RowPolicyUpdate(rule="assignee", view_column_id=ASSIGNEE)
    with pytest.raises(ValidationError):
        RowPolicyUpdate(rule="assignee", edit_column_id=ASSIGNEE)
    assert (
        RowPolicyUpdate(
            rule="assignee", view_column_id=ASSIGNEE, edit_column_id=ASSIGNEE
        ).view_column_id
        == ASSIGNEE
    )


def test_the_project_half_is_set_together_or_not_at_all():
    with pytest.raises(ValidationError):
        RowPolicyUpdate(
            rule="assignee",
            view_column_id=ASSIGNEE,
            edit_column_id=ASSIGNEE,
            view_project_link_column_id=PROJECT_LINK,
        )
    assert (
        RowPolicyUpdate(
            rule="assignee",
            view_column_id=ASSIGNEE,
            edit_column_id=ASSIGNEE,
            view_project_link_column_id=PROJECT_LINK,
            view_projects_table_id=PROJECTS_TABLE,
            view_project_members_column_id=MEMBERS,
        ).view_projects_table_id
        == PROJECTS_TABLE
    )


def test_parse_policy_reads_none_as_no_policy_and_none_rule_as_no_policy():
    assert parse_policy(None) is None
    assert parse_policy({"rule": "none"}) is None
    assert parse_policy(POLICY.model_dump(mode="json")) == POLICY


def test_parse_policy_reads_an_unvalidatable_document_as_no_policy():
    assert parse_policy({"rule": "assignee"}) is None
    assert parse_policy({"rule": "grants", "view_column_id": str(ASSIGNEE)}) is None


# -- the bypass ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("ctx", "owner", "expected"),
    [
        (_ctx(MEMBER, "member", admin=True), OWNER, True),
        (_ctx(OWNER, "member"), OWNER, True),
        (_ctx(MEMBER, "owner"), OTHER, True),
        (_ctx(MEMBER, "admin"), OTHER, True),
        (_ctx(MEMBER, "builder"), OTHER, False),
        (_ctx(MEMBER, "operator"), OTHER, False),
        (_ctx(MEMBER, "member"), OTHER, False),
        (_ctx(MEMBER, "viewer"), OTHER, False),
        (_ctx(None, "owner"), OWNER, False),
        (_ctx(MEMBER, "member"), None, False),
    ],
)
def test_only_the_superadmin_the_table_owner_and_owner_or_admin_skip_the_predicate(
    ctx, owner, expected
):
    assert bypasses_policy(ctx, owner_user_id=owner) is expected


# -- one row, in Python -------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "cell", "subject", "expected"),
    [
        (ASSIGNEE_COL, str(MEMBER), MEMBER, True),
        (ASSIGNEE_COL, str(OTHER), MEMBER, False),
        (ASSIGNEE_COL, None, MEMBER, False),
        (ASSIGNEES_COL, [str(OTHER), str(MEMBER)], MEMBER, True),
        (ASSIGNEES_COL, [str(OTHER)], MEMBER, False),
        (ASSIGNEES_COL, [], MEMBER, False),
        (ASSIGNEES_COL, None, MEMBER, False),
    ],
)
def test_a_row_matches_when_the_caller_is_in_its_assignee_column(column, cell, subject, expected):
    columns = [column]
    policy = RowPolicy(rule="assignee", view_column_id=column.id, edit_column_id=column.id)
    values = {} if cell is None else {str(column.id): cell}
    assert row_matches(values, policy, columns, subject, kind="view") is expected
    assert row_matches(values, policy, columns, subject, kind="edit") is expected


def test_a_row_with_no_subject_matches_nobody():
    assert (
        row_matches({str(ASSIGNEE): str(MEMBER)}, POLICY, [ASSIGNEE_COL], None, kind="view")
        is False
    )


def test_a_policy_naming_a_gone_or_archived_or_wrong_typed_column_matches_nobody():
    assert (
        row_matches(
            {str(ASSIGNEE): str(MEMBER)},
            RowPolicy(
                rule="assignee",
                view_column_id=UUID("00000000-0000-4000-8000-000000000099"),
                edit_column_id=ASSIGNEE,
            ),
            [ASSIGNEE_COL],
            MEMBER,
            kind="view",
        )
        is False
    )
    assert (
        row_matches(
            {str(ARCHIVED_COL.id): str(MEMBER)},
            RowPolicy(
                rule="assignee",
                view_column_id=ARCHIVED_COL.id,
                edit_column_id=ARCHIVED_COL.id,
            ),
            [ARCHIVED_COL],
            MEMBER,
            kind="view",
        )
        is False
    )
    assert (
        row_matches(
            {str(TEXT_COL.id): str(MEMBER)},
            RowPolicy(
                rule="assignee",
                view_column_id=TEXT_COL.id,
                edit_column_id=TEXT_COL.id,
            ),
            [TEXT_COL],
            MEMBER,
            kind="view",
        )
        is False
    )


def test_view_widens_to_project_members_while_edit_stays_assignee_only():
    columns = [ASSIGNEE_COL, LINK_COL]
    values = {str(PROJECT_LINK): [str(PROJECT_A)]}
    assert (
        row_matches(values, PROJECT_POLICY, columns, MEMBER, kind="view", project_ids=[PROJECT_A])
        is True
    )
    assert (
        row_matches(values, PROJECT_POLICY, columns, MEMBER, kind="view", project_ids=[PROJECT_B])
        is False
    )
    assert (
        row_matches(values, PROJECT_POLICY, columns, MEMBER, kind="edit", project_ids=[PROJECT_A])
        is False
    )
    assert (
        row_matches(
            {str(ASSIGNEE): str(MEMBER), str(PROJECT_LINK): [str(PROJECT_A)]},
            PROJECT_POLICY,
            columns,
            MEMBER,
            kind="view",
            project_ids=[],
        )
        is True
    )


# -- the project half ---------------------------------------------------------


async def test_no_project_config_means_no_project_lookup(monkeypatch):
    async def fail(*args, **kwargs):
        raise AssertionError("no projects table may be read without a project config")

    monkeypatch.setattr(virtual_table_repo, "get_table", fail)
    assert await visible_project_ids(SimpleNamespace(), _ctx(MEMBER), POLICY) == []


async def test_an_unresolvable_project_half_degrades_to_assignee_only(monkeypatch):
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=None))
    assert await visible_project_ids(SimpleNamespace(), _ctx(MEMBER), PROJECT_POLICY) == []

    archived = SimpleNamespace(
        id=PROJECTS_TABLE, archived_at=datetime.now(UTC), schema_version=1, row_policy=None
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=archived))
    assert await visible_project_ids(SimpleNamespace(), _ctx(MEMBER), PROJECT_POLICY) == []


async def test_a_projects_table_without_a_members_column_degrades_to_assignee_only(monkeypatch):
    projects = SimpleNamespace(
        id=PROJECTS_TABLE, archived_at=None, schema_version=1, row_policy=None, owner_user_id=None
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=projects))
    monkeypatch.setattr(
        virtual_table_repo,
        "get_schema_version",
        AsyncMock(return_value=SimpleNamespace(columns=[TEXT_COL.model_dump(mode="json")])),
    )
    assert await visible_project_ids(SimpleNamespace(), _ctx(MEMBER), PROJECT_POLICY) == []


async def test_the_project_lookup_reads_the_members_column_and_nothing_else(monkeypatch):
    projects = SimpleNamespace(
        id=PROJECTS_TABLE, archived_at=None, schema_version=1, row_policy=None, owner_user_id=None
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=projects))
    monkeypatch.setattr(
        virtual_table_repo,
        "get_schema_version",
        AsyncMock(return_value=SimpleNamespace(columns=[MEMBERS_COL.model_dump(mode="json")])),
    )
    listed = AsyncMock(return_value=[PROJECT_A, PROJECT_B])
    monkeypatch.setattr(virtual_table_repo, "list_record_ids", listed)

    assert await visible_project_ids(SimpleNamespace(), _ctx(MEMBER), PROJECT_POLICY) == [
        PROJECT_A,
        PROJECT_B,
    ]
    filters = listed.await_args.kwargs["filters"]
    assert len(filters) == 1
    assert filters[0].column_id == MEMBERS
    assert filters[0].kind is SqlKind.ARRAY
    assert filters[0].op == "contains"
    assert filters[0].value == str(MEMBER)


@pytest.mark.parametrize("remaining", [(90, 60, 30), (0,), (90, 0), (90, 60, 0)])
async def test_a_bounded_project_lookup_refreshes_the_timeout_and_stops_on_expiry(
    monkeypatch, remaining
):
    events = []
    db = SimpleNamespace()
    deadline = ReadDeadline(1, 100)
    monkeypatch.setattr(deadline, "remaining_ms", Mock(side_effect=remaining))

    async def arm(session, *, ms):
        assert session is db
        events.append(("timeout", ms))

    async def table(session, table_id, *, organization_id):
        assert session is db and table_id == PROJECTS_TABLE and organization_id == ORG
        events.append(("table", None))
        return SimpleNamespace(
            id=PROJECTS_TABLE,
            archived_at=None,
            schema_version=1,
            row_policy=None,
            owner_user_id=None,
        )

    async def schema(session, *, table_id, version):
        assert session is db and table_id == PROJECTS_TABLE and version == 1
        events.append(("schema", None))
        return SimpleNamespace(columns=[MEMBERS_COL.model_dump(mode="json")])

    async def records(session, *, table_id, organization_id, filters):
        assert session is db and table_id == PROJECTS_TABLE and organization_id == ORG
        assert len(filters) == 1 and filters[0].value == str(MEMBER)
        events.append(("records", None))
        return [PROJECT_A]

    monkeypatch.setattr(virtual_table_repo, "set_statement_timeout", arm)
    monkeypatch.setattr(virtual_table_repo, "get_table", table)
    monkeypatch.setattr(virtual_table_repo, "get_schema_version", schema)
    monkeypatch.setattr(virtual_table_repo, "list_record_ids", records)

    async def read():
        return await view_expression(
            db,
            _ctx(MEMBER),
            _table(PROJECT_POLICY),
            [ASSIGNEE_COL, LINK_COL],
            deadline=deadline,
        )

    if remaining[-1] == 0:
        with pytest.raises(DeadlineReached):
            await read()
    else:
        assert await read() is not None

    completed = [ms for ms in remaining if ms > 0]
    assert events == [
        event
        for ms, operation in zip(completed, ("table", "schema", "records"), strict=False)
        for event in (("timeout", ms), (operation, None))
    ]


async def test_the_project_lookup_honours_the_projects_table_own_policy(monkeypatch):
    own_policy = RowPolicy(rule="assignee", view_column_id=ASSIGNEE, edit_column_id=ASSIGNEE)
    projects = SimpleNamespace(
        id=PROJECTS_TABLE,
        archived_at=None,
        schema_version=1,
        row_policy=own_policy.model_dump(mode="json"),
        owner_user_id=OTHER,
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=projects))
    monkeypatch.setattr(
        virtual_table_repo,
        "get_schema_version",
        AsyncMock(
            return_value=SimpleNamespace(
                columns=[
                    MEMBERS_COL.model_dump(mode="json"),
                    ASSIGNEE_COL.model_dump(mode="json"),
                ]
            )
        ),
    )
    listed = AsyncMock(return_value=[PROJECT_A])
    monkeypatch.setattr(virtual_table_repo, "list_record_ids", listed)

    assert await visible_project_ids(SimpleNamespace(), _ctx(MEMBER), PROJECT_POLICY) == [PROJECT_A]
    filters = listed.await_args.kwargs["filters"]
    assert [clause.column_id for clause in filters] == [MEMBERS, ASSIGNEE]


# -- one row, through the service helpers -------------------------------------


async def test_a_bypass_caller_and_a_table_without_a_policy_see_every_row():
    table = _table(None)
    assert await may_view_row(SimpleNamespace(), _ctx(MEMBER, "builder"), table, [], {}) is True
    assert (
        await may_view_row(SimpleNamespace(), _ctx(OWNER, "member"), _table(POLICY), [], {}) is True
    )
    assert await may_edit_row(SimpleNamespace(), _ctx(MEMBER, "member"), table, [], {}) is True


async def test_a_subject_less_caller_sees_no_row_of_a_policy_table():
    assert (
        await may_view_row(
            SimpleNamespace(), _ctx(None, "member"), _table(POLICY), [ASSIGNEE_COL], {}
        )
        is False
    )
    assert (
        await may_edit_row(
            SimpleNamespace(), _ctx(None, "member"), _table(POLICY), [ASSIGNEE_COL], {}
        )
        is False
    )


async def test_a_member_sees_only_the_rows_they_are_assigned_to(monkeypatch):
    table = _table(POLICY)
    mine = {str(ASSIGNEE): str(MEMBER)}
    theirs = {str(ASSIGNEE): str(OTHER)}
    assert await may_view_row(SimpleNamespace(), _ctx(MEMBER), table, [ASSIGNEE_COL], mine) is True
    assert (
        await may_view_row(SimpleNamespace(), _ctx(MEMBER), table, [ASSIGNEE_COL], theirs) is False
    )
    assert await may_edit_row(SimpleNamespace(), _ctx(MEMBER), table, [ASSIGNEE_COL], mine) is True
    assert (
        await may_edit_row(SimpleNamespace(), _ctx(MEMBER), table, [ASSIGNEE_COL], theirs) is False
    )


# -- the SQL predicate --------------------------------------------------------


async def test_no_policy_or_a_bypass_caller_means_no_predicate():
    assert await view_expression(SimpleNamespace(), _ctx(MEMBER), _table(None), []) is None
    assert (
        await view_expression(SimpleNamespace(), _ctx(OWNER), _table(POLICY), [ASSIGNEE_COL])
        is None
    )


async def test_a_subject_less_caller_gets_a_predicate_matching_nothing():
    expression = await view_expression(
        SimpleNamespace(), _ctx(None), _table(POLICY), [ASSIGNEE_COL]
    )
    assert expression is not None
    assert _sql(expression) == "false"


async def test_a_broken_driving_column_gets_a_predicate_matching_nothing():
    expression = await view_expression(SimpleNamespace(), _ctx(MEMBER), _table(POLICY), [TEXT_COL])
    assert expression is not None
    assert _sql(expression) == "false"


async def test_a_user_assignee_becomes_an_equality_on_the_cell_text():
    expression = await view_expression(
        SimpleNamespace(), _ctx(MEMBER), _table(POLICY), [ASSIGNEE_COL]
    )
    assert expression is not None
    compiled = _sql(expression)
    assert "->>" in compiled
    assert compiled.rstrip().endswith("=") or " = " in compiled


async def test_a_multi_user_assignee_becomes_a_json_contains():
    policy = RowPolicy(rule="assignee", view_column_id=ASSIGNEE, edit_column_id=ASSIGNEE)
    expression = await view_expression(
        SimpleNamespace(), _ctx(MEMBER), _table(policy), [ASSIGNEES_COL]
    )
    assert expression is not None
    assert "@>" in _sql(expression)


async def test_the_project_half_is_an_or_over_the_callers_projects(monkeypatch):
    monkeypatch.setattr(row_policy, "visible_project_ids", AsyncMock(return_value=[PROJECT_A]))
    expression = await view_expression(
        SimpleNamespace(), _ctx(MEMBER), _table(PROJECT_POLICY), [ASSIGNEE_COL, LINK_COL]
    )
    assert expression is not None
    compiled = _sql(expression)
    assert " OR " in compiled
    assert "?|" in compiled
    assert "@>" not in compiled


def test_policy_expression_builds_nothing_from_nothing():
    assert policy_expression(None) is None
    assert policy_expression(None, link_column_id=PROJECT_LINK, project_ids=[]) is None


def test_policy_expression_with_only_a_project_half_names_the_link():
    expression = policy_expression(None, link_column_id=PROJECT_LINK, project_ids=[PROJECT_A])
    assert expression is not None
    assert "?|" in _sql(expression)


@pytest.mark.security
def test_matching_ands_the_policy_with_the_tenant_and_the_callers_filters():
    clause = FilterClause(column_id=TEXT_COL.id, kind=SqlKind.TEXT, op="eq", value="x")
    expression = policy_expression(
        FilterClause(column_id=ASSIGNEE, kind=SqlKind.TEXT, op="eq", value=str(MEMBER))
    )
    compiled = _sql(_matching(TABLE_ID, ORG, [clause], None, expression))
    assert "virtual_table_records.table_id" in compiled
    assert "virtual_table_records.organization_id" in compiled
    assert " = " in compiled
    assert " AND " in compiled


@pytest.mark.security
async def test_matching_record_ids_keep_the_tenant_table_filter_and_policy_predicate() -> None:
    clause = FilterClause(column_id=TEXT_COL.id, kind=SqlKind.TEXT, op="eq", value="visible")
    policy = policy_expression(
        FilterClause(column_id=ASSIGNEE, kind=SqlKind.TEXT, op="eq", value=str(MEMBER))
    )
    returned = Mock(all=Mock(return_value=[(PROJECT_A,), (PROJECT_B,)]))
    db = Mock(execute=AsyncMock(return_value=returned))
    ids = await virtual_table_repo.list_record_ids(
        db, table_id=TABLE_ID, organization_id=ORG, filters=[clause], extra=policy
    )
    assert ids == [PROJECT_A, PROJECT_B]
    assert db.execute.await_args is not None
    statement = db.execute.await_args.args[0].compile(dialect=postgresql.dialect())
    sql = str(statement)
    assert "SELECT virtual_table_records.id" in sql
    assert "virtual_table_records.table_id" in sql
    assert "virtual_table_records.organization_id" in sql
    assert " AND " in sql
    assert TABLE_ID in statement.params.values()
    assert ORG in statement.params.values()
    assert "visible" in statement.params.values()
    assert str(MEMBER) in statement.params.values()


# -- the service, with the database stubbed out -------------------------------
#
# The pattern of `test_virtual_table_upsert_race.py`: the service under test,
# the repository boundary mocked, `run_once` a passthrough. A test here pins
# the decision the service makes - which rows it hands to the repository, and
# which writes it refuses - not the rows a database would return for the
# predicate, which is the integration suite's question.

import uuid as _uuid
from unittest.mock import MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.schemas.virtual_table import (
    RecordBatchCreate,
    RecordCountQuery,
    RecordCreate,
    RecordExportQuery,
    RecordQuery,
    RecordSource,
    RecordUpdate,
    RecordUpsert,
)
from app.services.virtual_tables import records as records_module
from app.services.virtual_tables.exceptions import InvalidRecordError
from app.services.virtual_tables.records import RecordOperations

LINK_TARGET = UUID("00000000-0000-4000-8000-000000000020")
LINK_COL = ColumnDef(
    id=UUID("00000000-0000-4000-8000-000000000021"),
    label="Task",
    type="link",
    link_table_id=LINK_TARGET,
)


def _row(values: dict, *, revision: int = 1, record_id: UUID | None = None):
    return SimpleNamespace(
        id=record_id or _uuid.uuid4(),
        table_id=TABLE_ID,
        external_id=None,
        schema_version=1,
        revision=revision,
        created_at=datetime.now(UTC),
        updated_at=None,
        created_by=MEMBER,
        updated_by=MEMBER,
        values=dict(values),
        created_source=None,
        updated_source=None,
    )


@pytest.fixture
def ops(monkeypatch):
    table = SimpleNamespace(
        id=TABLE_ID,
        organization_id=ORG,
        owner_user_id=OTHER,
        name="Tasks",
        archived_at=None,
        schema_version=1,
        row_policy=POLICY.model_dump(mode="json"),
    )
    service = RecordOperations(db=MagicMock(spec=AsyncSession))
    ctx = _ctx(MEMBER, "member")

    async def load(ctx, table_id, perm, *, lock=False, share=False, deadline=None):
        return table

    async def columns(table):
        return [ASSIGNEE_COL]

    async def passthrough(db, ctx, *, action, **_):
        return await action(), False

    async def source_for(db, ctx):
        return RecordSource(kind="user", id=ctx.user_id, name="Record author")

    async def within_quota(*args, **kwargs):
        return None

    monkeypatch.setattr(records_module, "source_for", source_for)
    monkeypatch.setattr(service, "_load_table", load)
    monkeypatch.setattr(service, "_columns", columns)
    monkeypatch.setattr(records_module, "run_once", passthrough)
    monkeypatch.setattr(records_module, "resolve_access", AsyncMock(return_value=True))
    monkeypatch.setattr(records_module, "principal_problems", AsyncMock(return_value=[]))
    monkeypatch.setattr(records_module.quotas, "enforce_record_size", within_quota)
    monkeypatch.setattr(records_module.quotas, "enforce_record_count", within_quota)
    monkeypatch.setattr(records_module.quotas, "lock_record_count", within_quota)
    monkeypatch.setattr(records_module.quotas, "lock_storage", within_quota)
    monkeypatch.setattr(records_module.quotas, "enforce_storage", within_quota)
    monkeypatch.setattr(records_module.quotas, "delete_snapshot", MagicMock(return_value={}))
    monkeypatch.setattr(records_module.trigger_repo, "has_active", AsyncMock(return_value=False))
    return service, ctx, table


@pytest.fixture(autouse=True)
def ordinary_tables_only(monkeypatch):
    monkeypatch.setattr("app.repositories.task.for_table", AsyncMock(return_value=None))


def _mine() -> dict:
    return {str(ASSIGNEE): str(MEMBER)}


def _theirs() -> dict:
    return {str(ASSIGNEE): str(OTHER)}


async def test_a_listing_hands_the_predicate_to_the_repository(ops, monkeypatch):
    service, ctx, table = ops
    listed = AsyncMock(return_value=[])
    monkeypatch.setattr(virtual_table_repo, "list_records", listed)

    await service.list_records(ctx, table.id, RecordQuery())

    extra = listed.await_args.kwargs["extra"]
    assert extra is not None
    assert "@>" not in _sql(extra) and "->>" in _sql(extra)


async def test_a_listing_by_a_bypass_caller_hands_no_predicate(ops, monkeypatch):
    service, ctx, table = ops
    listed = AsyncMock(return_value=[])
    monkeypatch.setattr(virtual_table_repo, "list_records", listed)

    await service.list_records(_ctx(MEMBER, "owner"), table.id, RecordQuery())

    assert listed.await_args.kwargs["extra"] is None


async def test_a_count_and_an_export_hand_the_same_predicate(ops, monkeypatch):
    service, ctx, table = ops
    counted = AsyncMock(return_value=2)
    monkeypatch.setattr(virtual_table_repo, "count_records", counted)
    monkeypatch.setattr(
        records_module.rate_limit,
        "consume_with_local_floor",
        AsyncMock(return_value=SimpleNamespace(allowed=True, retry_after_seconds=0)),
    )
    monkeypatch.setattr(records_module, "try_hold_name", AsyncMock(return_value=True))
    streamed = {}

    async def _stream(*args, **kwargs):
        streamed.update(kwargs)
        yield []

    monkeypatch.setattr(virtual_table_repo, "stream_export_records", _stream)

    count = await service.count_records(ctx, table.id, RecordCountQuery())
    assert count.count == 2
    assert counted.await_args.kwargs["extra"] is not None
    export = await service.export_records(ctx, table.id, RecordExportQuery())
    assert [line async for line in export.lines]
    assert streamed["extra"] is not None
    assert _sql(streamed["extra"]) == _sql(counted.await_args.kwargs["extra"])


async def test_a_bound_read_hands_the_predicate_to_the_size_query(ops, monkeypatch):
    service, ctx, table = ops
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=table))
    sized = AsyncMock(return_value=[])
    monkeypatch.setattr(virtual_table_repo, "list_record_sizes", sized)
    deadline = MagicMock()
    deadline.arm = AsyncMock()

    bound = await service.read_bound(
        ctx,
        table_id=table.id,
        columns=[ASSIGNEE_COL],
        filters=[],
        sort=RecordQuery().sort,
        column_ids=[ASSIGNEE_COL.id],
        shape=lambda record: dict(record.values),
        max_records=10,
        max_bytes=10_000,
        deadline=deadline,
    )

    assert bound.records == []
    assert sized.await_args.kwargs["extra"] is not None


async def test_a_bound_read_of_a_table_that_is_gone_is_a_404(ops, monkeypatch):
    service, ctx, table = ops
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=None))
    deadline = MagicMock()
    deadline.arm = AsyncMock()

    with pytest.raises(NotFoundError):
        await service.read_bound(
            ctx,
            table_id=table.id,
            columns=[ASSIGNEE_COL],
            filters=[],
            sort=RecordQuery().sort,
            column_ids=[ASSIGNEE_COL.id],
            shape=lambda record: dict(record.values),
            max_records=10,
            max_bytes=10_000,
            deadline=deadline,
        )


async def test_a_single_read_of_an_invisible_row_is_a_404(ops, monkeypatch):
    service, ctx, table = ops
    monkeypatch.setattr(virtual_table_repo, "get_record", AsyncMock(return_value=_row(_theirs())))
    monkeypatch.setattr(
        virtual_table_repo,
        "get_record_by_external_id",
        AsyncMock(return_value=_row(_theirs())),
    )

    with pytest.raises(NotFoundError):
        await service.get_record(ctx, table.id, _uuid.uuid4())
    with pytest.raises(NotFoundError):
        await service.get_record_by_external_id(ctx, table.id, "EXT-1")


async def test_a_single_read_of_a_visible_row_returns_it(ops, monkeypatch):
    service, ctx, table = ops
    row = _row(_mine())
    monkeypatch.setattr(virtual_table_repo, "get_record", AsyncMock(return_value=row))

    read = await service.get_record(ctx, table.id, row.id)
    assert read.id == row.id
    assert read.values == _mine()


async def test_record_exists_answers_for_the_callers_visibility(ops, monkeypatch):
    service, ctx, table = ops
    exists = AsyncMock(return_value=True)
    monkeypatch.setattr(virtual_table_repo, "record_exists", exists)

    assert await service.record_exists(ctx, table.id, "EXT-1") is True
    assert exists.await_args.kwargs["extra"] is not None

    table.row_policy = None
    assert await service.record_exists(ctx, table.id, "EXT-1") is True
    assert exists.await_args.kwargs["extra"] is None


async def test_a_create_assigned_to_someone_else_is_refused(ops, monkeypatch):
    service, ctx, table = ops
    monkeypatch.setattr(
        virtual_table_repo, "get_record_by_external_id", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(virtual_table_repo, "insert_record", AsyncMock(return_value=_row(_mine())))
    monkeypatch.setattr(virtual_table_repo, "add_history", AsyncMock())
    monkeypatch.setattr(virtual_table_repo, "add_outbox", AsyncMock())

    with pytest.raises(NotFoundError):
        await service.create_record(ctx, table.id, RecordCreate(values=_theirs()))

    written = await service.create_record(ctx, table.id, RecordCreate(values=_mine()))
    assert written.record.values == _mine()
    assert written.created is True


async def test_a_batch_reports_the_refused_row_and_writes_the_rest(ops, monkeypatch):
    service, ctx, table = ops
    monkeypatch.setattr(
        virtual_table_repo, "database_time", AsyncMock(return_value=datetime.now(UTC))
    )
    monkeypatch.setattr(
        virtual_table_repo, "get_record_by_external_id", AsyncMock(return_value=None)
    )

    async def insert(*args, **kwargs):
        return _row(kwargs["values"])

    monkeypatch.setattr(virtual_table_repo, "insert_record", insert)
    monkeypatch.setattr(virtual_table_repo, "add_history", AsyncMock())
    monkeypatch.setattr(virtual_table_repo, "add_outbox", AsyncMock())

    result = await service.create_records(
        ctx,
        table.id,
        RecordBatchCreate(records=[RecordCreate(values=_mine()), RecordCreate(values=_theirs())]),
    )
    assert result.created == 1
    assert len(result.failed) == 1
    assert result.failed[0].index == 1
    assert result.failed[0].code == "NOT_FOUND"


async def test_an_update_of_an_invisible_row_is_a_404(ops, monkeypatch):
    service, ctx, table = ops
    monkeypatch.setattr(virtual_table_repo, "get_record", AsyncMock(return_value=_row(_theirs())))

    with pytest.raises(NotFoundError):
        await service.update_record(
            ctx, table.id, _uuid.uuid4(), RecordUpdate(expected_revision=1, values=_mine())
        )


async def test_an_update_moving_a_row_out_of_visibility_is_refused(ops, monkeypatch):
    service, ctx, table = ops
    row = _row(_mine())
    monkeypatch.setattr(virtual_table_repo, "get_record", AsyncMock(return_value=row))

    async def update(*args, **kwargs):
        row.values = kwargs["values"]
        return row

    monkeypatch.setattr(virtual_table_repo, "update_record", update)
    monkeypatch.setattr(virtual_table_repo, "add_history", AsyncMock())

    with pytest.raises(NotFoundError):
        await service.update_record(
            ctx, table.id, row.id, RecordUpdate(expected_revision=1, values=_theirs())
        )


async def test_an_update_that_changes_nothing_on_an_invisible_row_is_still_a_404(ops, monkeypatch):
    service, ctx, table = ops
    row = _row(_theirs())
    monkeypatch.setattr(virtual_table_repo, "get_record", AsyncMock(return_value=row))

    with pytest.raises(NotFoundError):
        await service.update_record(
            ctx, table.id, row.id, RecordUpdate(expected_revision=1, values=_theirs())
        )


async def test_an_update_that_changes_nothing_on_a_visible_row_returns_it(ops, monkeypatch):
    service, ctx, table = ops
    row = _row(_mine())
    monkeypatch.setattr(virtual_table_repo, "get_record", AsyncMock(return_value=row))

    written = await service.update_record(
        ctx, table.id, row.id, RecordUpdate(expected_revision=1, values=_mine())
    )
    assert written.record.values == _mine()
    assert written.created is False


async def test_an_upsert_refuses_both_branches_outside_visibility(ops, monkeypatch):
    service, ctx, table = ops
    monkeypatch.setattr(
        virtual_table_repo, "get_record_by_external_id", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        virtual_table_repo, "insert_record", AsyncMock(return_value=_row(_theirs()))
    )
    monkeypatch.setattr(virtual_table_repo, "add_history", AsyncMock())
    monkeypatch.setattr(virtual_table_repo, "add_outbox", AsyncMock())

    with pytest.raises(NotFoundError):
        await service.upsert_record(ctx, table.id, "EXT-1", RecordUpsert(values=_theirs()))

    existing = _row(_theirs())
    monkeypatch.setattr(
        virtual_table_repo, "get_record_by_external_id", AsyncMock(return_value=existing)
    )
    with pytest.raises(NotFoundError):
        await service.upsert_record(
            ctx, table.id, "EXT-1", RecordUpsert(values=_mine(), expected_revision=1)
        )


async def test_a_delete_of_an_invisible_row_writes_nothing(ops, monkeypatch):
    service, ctx, table = ops
    monkeypatch.setattr(virtual_table_repo, "get_record", AsyncMock(return_value=_row(_theirs())))
    deleted = AsyncMock()
    monkeypatch.setattr(virtual_table_repo, "delete_record", deleted)
    monkeypatch.setattr(virtual_table_repo, "add_history", AsyncMock())
    monkeypatch.setattr(
        "app.services.task_execution.TaskExecution",
        MagicMock(return_value=SimpleNamespace(deleted=AsyncMock())),
    )

    with pytest.raises(NotFoundError):
        await service.delete_record(ctx, table.id, _uuid.uuid4(), expected_revision=1)
    deleted.assert_not_awaited()


async def test_a_delete_of_a_visible_row_deletes_it(ops, monkeypatch):
    service, ctx, table = ops
    row = _row(_mine())
    monkeypatch.setattr(virtual_table_repo, "get_record", AsyncMock(return_value=row))
    deleted = AsyncMock()
    monkeypatch.setattr(virtual_table_repo, "delete_record", deleted)
    monkeypatch.setattr(virtual_table_repo, "add_history", AsyncMock())
    monkeypatch.setattr(
        "app.services.task_execution.TaskExecution",
        MagicMock(return_value=SimpleNamespace(deleted=AsyncMock())),
    )

    await service.delete_record(ctx, table.id, row.id, expected_revision=1)
    deleted.assert_awaited_once()


async def test_a_link_to_an_invisible_row_fails_like_a_missing_one(ops, monkeypatch):
    service, ctx, table = ops
    target = SimpleNamespace(
        id=LINK_TARGET,
        organization_id=ORG,
        owner_user_id=OTHER,
        archived_at=None,
        schema_version=1,
        row_policy=POLICY.model_dump(mode="json"),
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=target))
    monkeypatch.setattr(
        virtual_table_repo,
        "get_schema_version",
        AsyncMock(return_value=SimpleNamespace(columns=[ASSIGNEE_COL.model_dump(mode="json")])),
    )
    invisible_id = _uuid.uuid4()
    monkeypatch.setattr(
        virtual_table_repo,
        "get_records_by_ids",
        AsyncMock(return_value=[_row(_theirs(), record_id=invisible_id)]),
    )

    with pytest.raises(InvalidRecordError) as refused:
        await service._check_links(ctx, [LINK_COL], {str(LINK_COL.id): [str(invisible_id)]})
    assert refused.value.details == {
        "fields": [
            {
                "field": f"values.{LINK_COL.id}",
                "message": f"No record {invisible_id} in the linked table",
            }
        ]
    }

    monkeypatch.setattr(
        virtual_table_repo,
        "get_records_by_ids",
        AsyncMock(return_value=[_row(_mine(), record_id=invisible_id)]),
    )
    await service._check_links(ctx, [LINK_COL], {str(LINK_COL.id): [str(invisible_id)]})

    monkeypatch.setattr(virtual_table_repo, "get_records_by_ids", AsyncMock(return_value=[]))
    with pytest.raises(InvalidRecordError) as missing:
        await service._check_links(ctx, [LINK_COL], {str(LINK_COL.id): [str(invisible_id)]})
    assert missing.value.details == refused.value.details


def test_a_table_read_carries_its_row_policy_and_none_without_one():
    read = Operations._read(_table(POLICY), [ASSIGNEE_COL], can_edit=True)
    assert isinstance(read, TableRead)
    assert read.row_policy == POLICY
    assert Operations._read(_table(None), [], can_edit=False).row_policy is None


def test_a_virtual_table_row_holds_its_policy_document():
    table = VirtualTable(organization_id=ORG, name="Tasks", row_policy={"rule": "none"})
    assert table.row_policy == {"rule": "none"}


# -- setting a policy ---------------------------------------------------------
#
# Anyone holding `tables:edit` may set it - the service decides access via
# `resolve_access`, so a grant holder is not refused by a route-level role
# gate. A managed board table and an archived table refuse, and the columns
# a policy names are validated at set time. Archiving or retyping a driving
# column afterwards is refused until the policy is cleared.


from app.core.exceptions import BadRequestError
from app.services.virtual_tables.exceptions import InvalidSchemaError, TableArchivedError
from app.services.virtual_tables.schema import SchemaDiff
from app.services.virtual_tables.tables import TableOperations

_PROJECT_LINK_COL = ColumnDef(
    id=PROJECT_LINK, label="Project", type="link", link_table_id=PROJECTS_TABLE
)


def _table_ops(monkeypatch, *, table, columns, board=None, stored_policy=POLICY):
    ops = TableOperations(db=MagicMock())
    monkeypatch.setattr(TableOperations, "_load_table", AsyncMock(return_value=table))
    monkeypatch.setattr(TableOperations, "_columns", AsyncMock(return_value=columns))
    monkeypatch.setattr(
        "app.services.virtual_tables.tables.task_repo.for_table",
        AsyncMock(return_value=board),
    )
    updated = _table(stored_policy)
    monkeypatch.setattr(
        "app.services.virtual_tables.tables.virtual_table_repo.update_table",
        AsyncMock(return_value=updated),
    )
    monkeypatch.setattr("app.services.virtual_tables.tables.record_audit", AsyncMock())
    return ops


async def test_setting_a_policy_stores_it_and_audits_the_change(monkeypatch):
    ops = _table_ops(monkeypatch, table=_table(None), columns=[ASSIGNEE_COL])

    read = await ops.set_row_policy(
        _ctx(MEMBER),
        TABLE_ID,
        RowPolicyUpdate(rule="assignee", view_column_id=ASSIGNEE, edit_column_id=ASSIGNEE),
    )

    assert read.row_policy == POLICY
    from app.services.virtual_tables import tables as _tables

    _tables.virtual_table_repo.update_table.assert_awaited_once()
    stored = _tables.virtual_table_repo.update_table.await_args.kwargs["update_data"]
    assert stored == {"row_policy": POLICY.model_dump(mode="json")}
    _tables.record_audit.assert_awaited_once()
    audit = _tables.record_audit.await_args.kwargs
    assert audit["action"] == "table.row_policy_changed"
    assert audit["details"] == {"rule": "assignee"}


async def test_clearing_a_policy_stores_null(monkeypatch):
    ops = _table_ops(monkeypatch, table=_table(POLICY), columns=[ASSIGNEE_COL], stored_policy=None)

    read = await ops.set_row_policy(_ctx(MEMBER), TABLE_ID, RowPolicyUpdate(rule="none"))

    assert read.row_policy is None
    from app.services.virtual_tables import tables as _tables

    stored = _tables.virtual_table_repo.update_table.await_args.kwargs["update_data"]
    assert stored == {"row_policy": None}


async def test_setting_a_policy_on_a_board_table_is_refused(monkeypatch):
    ops = _table_ops(
        monkeypatch, table=_table(None), columns=[ASSIGNEE_COL], board=SimpleNamespace(id=TABLE_ID)
    )

    with pytest.raises(BadRequestError, match="managed board table"):
        await ops.set_row_policy(
            _ctx(MEMBER),
            TABLE_ID,
            RowPolicyUpdate(rule="assignee", view_column_id=ASSIGNEE, edit_column_id=ASSIGNEE),
        )


async def test_setting_a_policy_on_an_archived_table_is_refused(monkeypatch):
    archived = _table(None)
    archived.archived_at = datetime.now(UTC)
    ops = _table_ops(monkeypatch, table=archived, columns=[ASSIGNEE_COL])

    with pytest.raises(TableArchivedError):
        await ops.set_row_policy(
            _ctx(MEMBER),
            TABLE_ID,
            RowPolicyUpdate(rule="assignee", view_column_id=ASSIGNEE, edit_column_id=ASSIGNEE),
        )


async def test_a_policy_naming_a_missing_archived_or_wrong_kind_column_is_refused(monkeypatch):
    ops = _table_ops(
        monkeypatch,
        table=_table(None),
        columns=[ASSIGNEE_COL, TEXT_COL, ARCHIVED_COL],
    )
    ctx = _ctx(MEMBER)
    missing = UUID("00000000-0000-4000-8000-000000000099")

    with pytest.raises(InvalidSchemaError) as error:
        await ops.set_row_policy(
            ctx,
            TABLE_ID,
            RowPolicyUpdate(rule="assignee", view_column_id=missing, edit_column_id=ASSIGNEE),
        )
    assert error.value.details["fields"][0]["field"] == "view_column_id"

    with pytest.raises(InvalidSchemaError) as error:
        await ops.set_row_policy(
            ctx,
            TABLE_ID,
            RowPolicyUpdate(rule="assignee", view_column_id=TEXT_COL.id, edit_column_id=ASSIGNEE),
        )
    assert error.value.details["fields"][0]["field"] == "view_column_id"

    with pytest.raises(InvalidSchemaError) as error:
        await ops.set_row_policy(
            ctx,
            TABLE_ID,
            RowPolicyUpdate(
                rule="assignee", view_column_id=ARCHIVED_COL.id, edit_column_id=ASSIGNEE
            ),
        )
    assert error.value.details["fields"][0]["field"] == "view_column_id"


async def test_a_policy_whose_projects_table_cannot_be_viewed_is_refused(monkeypatch):
    ops = _table_ops(monkeypatch, table=_table(None), columns=[ASSIGNEE_COL, _PROJECT_LINK_COL])
    monkeypatch.setattr(
        TableOperations,
        "_load_table",
        AsyncMock(side_effect=[_table(None), NotFoundError(message="Table not found")]),
    )

    with pytest.raises(InvalidSchemaError) as error:
        await ops.set_row_policy(
            _ctx(MEMBER),
            TABLE_ID,
            RowPolicyUpdate(
                rule="assignee",
                view_column_id=ASSIGNEE,
                edit_column_id=ASSIGNEE,
                view_project_link_column_id=PROJECT_LINK,
                view_projects_table_id=PROJECTS_TABLE,
                view_project_members_column_id=MEMBERS,
            ),
        )
    assert error.value.details["fields"][0]["field"] == "view_projects_table_id"


async def test_a_policy_with_a_valid_project_half_stores_it(monkeypatch):
    projects = _table(None)
    projects.id = PROJECTS_TABLE
    ops = _table_ops(
        monkeypatch,
        table=_table(None),
        columns=[ASSIGNEE_COL, _PROJECT_LINK_COL],
        stored_policy=PROJECT_POLICY,
    )
    monkeypatch.setattr(
        TableOperations,
        "_load_table",
        AsyncMock(side_effect=[_table(None), projects]),
    )
    monkeypatch.setattr(
        TableOperations,
        "_columns",
        AsyncMock(side_effect=[[ASSIGNEE_COL, _PROJECT_LINK_COL], [MEMBERS_COL]]),
    )

    read = await ops.set_row_policy(
        _ctx(MEMBER), TABLE_ID, RowPolicyUpdate(**PROJECT_POLICY.model_dump())
    )

    assert read.row_policy == PROJECT_POLICY


def test_archiving_or_retyping_a_driving_column_is_refused():
    ops = TableOperations(db=MagicMock())
    table = _table(POLICY)
    columns = [ASSIGNEE_COL]

    with pytest.raises(InvalidSchemaError) as error:
        ops._refuse_policy_column_change(
            table,
            columns,
            SchemaDiff(archived=frozenset({ASSIGNEE}), required=frozenset(), retyped=frozenset()),
        )
    assert error.value.details["fields"][0]["field"] == "columns.0.archived"

    retyped = [ASSIGNEE_COL.model_copy(update={"type": "text"})]
    with pytest.raises(InvalidSchemaError) as error:
        ops._refuse_policy_column_change(
            table,
            retyped,
            SchemaDiff(archived=frozenset(), required=frozenset(), retyped=frozenset({ASSIGNEE})),
        )
    assert error.value.details["fields"][0]["field"] == "columns.0.type"

    # Retyping between the two user kinds is fine, and a table without a
    # policy takes any change.
    multi = [ASSIGNEE_COL.model_copy(update={"type": "multi_user"})]
    ops._refuse_policy_column_change(
        table,
        multi,
        SchemaDiff(archived=frozenset(), required=frozenset(), retyped=frozenset({ASSIGNEE})),
    )
    ops._refuse_policy_column_change(
        _table(None),
        columns,
        SchemaDiff(archived=frozenset({ASSIGNEE}), required=frozenset(), retyped=frozenset()),
    )


async def test_visible_project_ids_with_no_subject_sees_no_projects(monkeypatch):
    projects = SimpleNamespace(
        id=PROJECTS_TABLE, archived_at=None, schema_version=1, row_policy=None, owner_user_id=None
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=projects))
    monkeypatch.setattr(
        virtual_table_repo,
        "get_schema_version",
        AsyncMock(return_value=SimpleNamespace(columns=[MEMBERS_COL.model_dump(mode="json")])),
    )
    assert await visible_project_ids(SimpleNamespace(), _ctx(None), PROJECT_POLICY) == []


async def test_a_projects_table_whose_own_policy_is_broken_degrades_to_assignee_only(monkeypatch):
    broken_own = RowPolicy(rule="assignee", view_column_id=TEXT_COL.id, edit_column_id=TEXT_COL.id)
    projects = SimpleNamespace(
        id=PROJECTS_TABLE,
        archived_at=None,
        schema_version=1,
        row_policy=broken_own.model_dump(mode="json"),
        owner_user_id=OTHER,
    )
    monkeypatch.setattr(virtual_table_repo, "get_table", AsyncMock(return_value=projects))
    monkeypatch.setattr(
        virtual_table_repo,
        "get_schema_version",
        AsyncMock(
            return_value=SimpleNamespace(
                columns=[
                    MEMBERS_COL.model_dump(mode="json"),
                    TEXT_COL.model_dump(mode="json"),
                ]
            )
        ),
    )
    listed = AsyncMock(return_value=[PROJECT_A])
    monkeypatch.setattr(virtual_table_repo, "list_record_ids", listed)

    assert await visible_project_ids(SimpleNamespace(), _ctx(MEMBER), PROJECT_POLICY) == []
    listed.assert_not_awaited()


def test_a_row_whose_project_link_is_not_a_list_does_not_match_by_project():
    values = {str(ASSIGNEE): str(OTHER), str(PROJECT_LINK): str(PROJECT_A)}
    assert (
        row_matches(
            values,
            PROJECT_POLICY,
            [ASSIGNEE_COL, _PROJECT_LINK_COL],
            MEMBER,
            kind="view",
            project_ids=[PROJECT_A],
        )
        is False
    )


async def test_a_policy_naming_a_missing_or_archived_link_column_is_refused(monkeypatch):
    ops = _table_ops(monkeypatch, table=_table(None), columns=[ASSIGNEE_COL, _PROJECT_LINK_COL])
    ctx = _ctx(MEMBER)
    missing = UUID("00000000-0000-4000-8000-000000000099")

    with pytest.raises(InvalidSchemaError) as error:
        await ops.set_row_policy(
            ctx,
            TABLE_ID,
            RowPolicyUpdate(
                rule="assignee",
                view_column_id=ASSIGNEE,
                edit_column_id=ASSIGNEE,
                view_project_link_column_id=missing,
                view_projects_table_id=PROJECTS_TABLE,
                view_project_members_column_id=MEMBERS,
            ),
        )
    assert error.value.details["fields"][0]["field"] == "view_project_link_column_id"

    archived_link = _PROJECT_LINK_COL.model_copy(update={"archived": True})
    ops = _table_ops(monkeypatch, table=_table(None), columns=[ASSIGNEE_COL, archived_link])
    with pytest.raises(InvalidSchemaError) as error:
        await ops.set_row_policy(
            ctx,
            TABLE_ID,
            RowPolicyUpdate(
                rule="assignee",
                view_column_id=ASSIGNEE,
                edit_column_id=ASSIGNEE,
                view_project_link_column_id=PROJECT_LINK,
                view_projects_table_id=PROJECTS_TABLE,
                view_project_members_column_id=MEMBERS,
            ),
        )
    assert error.value.details["fields"][0]["field"] == "view_project_link_column_id"


async def test_a_policy_whose_link_column_does_not_link_to_the_projects_table_is_refused(
    monkeypatch,
):
    wrong_link = ColumnDef(id=PROJECT_LINK, label="Task", type="link", link_table_id=TABLE_ID)
    ops = _table_ops(monkeypatch, table=_table(None), columns=[ASSIGNEE_COL, wrong_link])

    with pytest.raises(InvalidSchemaError) as error:
        await ops.set_row_policy(
            _ctx(MEMBER),
            TABLE_ID,
            RowPolicyUpdate(
                rule="assignee",
                view_column_id=ASSIGNEE,
                edit_column_id=ASSIGNEE,
                view_project_link_column_id=PROJECT_LINK,
                view_projects_table_id=PROJECTS_TABLE,
                view_project_members_column_id=MEMBERS,
            ),
        )
    assert error.value.details["fields"][0]["field"] == "view_project_link_column_id"


async def test_a_policy_naming_a_missing_archived_or_wrong_kind_members_column_is_refused(
    monkeypatch,
):
    projects = _table(None)
    projects.id = PROJECTS_TABLE
    data = RowPolicyUpdate(
        rule="assignee",
        view_column_id=ASSIGNEE,
        edit_column_id=ASSIGNEE,
        view_project_link_column_id=PROJECT_LINK,
        view_projects_table_id=PROJECTS_TABLE,
        view_project_members_column_id=MEMBERS,
    )
    cases = [
        ([ASSIGNEE_COL], "view_project_members_column_id"),
        (
            [ColumnDef(id=MEMBERS, label="Members", type="multi_user", archived=True)],
            "view_project_members_column_id",
        ),
        (
            [ColumnDef(id=MEMBERS, label="Members", type="text")],
            "view_project_members_column_id",
        ),
    ]
    for project_columns, field in cases:
        ops = _table_ops(monkeypatch, table=_table(None), columns=[ASSIGNEE_COL, _PROJECT_LINK_COL])
        monkeypatch.setattr(
            TableOperations,
            "_load_table",
            AsyncMock(side_effect=[_table(None), projects]),
        )
        monkeypatch.setattr(
            TableOperations,
            "_columns",
            AsyncMock(side_effect=[[ASSIGNEE_COL, _PROJECT_LINK_COL], project_columns]),
        )
        with pytest.raises(InvalidSchemaError) as error:
            await ops.set_row_policy(_ctx(MEMBER), TABLE_ID, data)
        assert error.value.details["fields"][0]["field"] == field


def test_archiving_the_project_link_column_is_refused():
    ops = TableOperations(db=MagicMock())
    table = _table(PROJECT_POLICY)
    columns = [ASSIGNEE_COL, _PROJECT_LINK_COL]

    with pytest.raises(InvalidSchemaError) as error:
        ops._refuse_policy_column_change(
            table,
            columns,
            SchemaDiff(
                archived=frozenset({PROJECT_LINK}), required=frozenset(), retyped=frozenset()
            ),
        )
    assert error.value.details["fields"][0]["field"] == "columns.1.archived"
