"""The upsert's lost-race branches, with the database stubbed out.

A real race is covered against Postgres in `tests/integration`; these pin the two
decisions the service makes once the insert has lost, which coverage cannot see
from a run that interleaves on greenlets.
"""

import uuid
from types import SimpleNamespace

import pytest

from app.core.exceptions import ConcurrentChangeError
from app.core.permissions import AuthContext
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import RecordUpsert
from app.services.virtual_tables import records
from app.services.virtual_tables.exceptions import RevisionConflictError, RevisionRequiredError
from app.services.virtual_tables.records import RecordOperations

pytestmark = pytest.mark.anyio


def _record(revision: int):
    return SimpleNamespace(id=uuid.uuid4(), revision=revision, values={})


@pytest.fixture
def service(monkeypatch) -> tuple[RecordOperations, AuthContext, SimpleNamespace]:
    table = SimpleNamespace(id=uuid.uuid4(), archived_at=None, schema_version=1)
    service = RecordOperations(db=None)  # type: ignore[arg-type]

    async def load(ctx, table_id, perm, *, lock=False, share=False):
        return table

    async def passthrough(db, ctx, *, action, **_):
        return await action(), False

    async def no_insert(*args, **kwargs):
        return None

    async def columns(table):
        return []

    monkeypatch.setattr(service, "_load_table", load)
    monkeypatch.setattr(service, "_columns", columns)
    monkeypatch.setattr(records, "run_once", passthrough)

    async def within_quota(*args, **kwargs):
        return None

    monkeypatch.setattr(virtual_table_repo, "insert_record", no_insert)
    monkeypatch.setattr(records.quotas, "enforce_record_size", within_quota)
    monkeypatch.setattr(records.quotas, "enforce_record_count", within_quota)
    monkeypatch.setattr(records.quotas, "lock_record_count", within_quota)
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")
    return service, ctx, table


def _lookups(monkeypatch, *answers):
    queue = list(answers)

    async def lookup(*args, **kwargs):
        return queue.pop(0)

    monkeypatch.setattr(virtual_table_repo, "get_record_by_external_id", lookup)


async def test_a_lost_insert_finds_the_winner_and_asks_for_the_revision(service, monkeypatch):
    ops, ctx, table = service
    winner = _record(revision=1)
    _lookups(monkeypatch, None, None, winner)

    with pytest.raises(RevisionRequiredError) as raised:
        await ops.upsert_record(ctx, table.id, "A-1", RecordUpsert(values={}))

    assert raised.value.details == {"record_id": winner.id, "current_revision": 1}


async def test_a_lost_insert_against_a_stale_revision_is_a_typed_conflict(service, monkeypatch):
    ops, ctx, table = service
    winner = _record(revision=1)
    _lookups(monkeypatch, None, None, winner)

    with pytest.raises(RevisionConflictError):
        await ops.upsert_record(ctx, table.id, "A-1", RecordUpsert(values={}, expected_revision=3))


async def test_a_winner_deleted_before_it_could_be_read_is_a_retryable_conflict(
    service, monkeypatch
):
    ops, ctx, table = service
    _lookups(monkeypatch, None, None, None)

    with pytest.raises(ConcurrentChangeError):
        await ops.upsert_record(ctx, table.id, "A-1", RecordUpsert(values={}))


async def test_a_winner_that_appears_while_waiting_for_the_count_lock_is_updated_not_counted(
    service, monkeypatch
):
    """The rival committed while this call waited for the lock: no insert, no quota check."""
    ops, ctx, table = service
    winner = _record(revision=1)
    inserted: list[object] = []

    async def insert(*args, **kwargs):
        inserted.append(args)

    async def refuse_the_full_table(*args, **kwargs):
        raise AssertionError("the table's count must not be consulted for an existing id")

    monkeypatch.setattr(virtual_table_repo, "insert_record", insert)
    monkeypatch.setattr(records.quotas, "enforce_record_count", refuse_the_full_table)
    _lookups(monkeypatch, None, winner)

    with pytest.raises(RevisionRequiredError) as raised:
        await ops.upsert_record(ctx, table.id, "A-1", RecordUpsert(values={}))

    assert raised.value.details == {"record_id": winner.id, "current_revision": 1}
    assert inserted == []
