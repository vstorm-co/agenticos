"""The quota checks, with the database stubbed: where the line is, and what a refusal is.

The counting and the locking are checked against Postgres in
`tests/integration/test_virtual_table_quotas.py`; these pin the boundary itself and the
shape of the refusal without a database, so an off-by-one shows here first.
"""

import uuid
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.permissions import AuthContext
from app.repositories import virtual_table_repo
from app.services.virtual_tables import quotas
from app.services.virtual_tables.exceptions import QuotaExceededError

pytestmark = pytest.mark.anyio


@pytest.fixture
def ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="owner")


@pytest.fixture
def audited(monkeypatch) -> list[dict]:
    """Record what would have been audited instead of opening a session for it."""
    entries: list[dict] = []

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *exc):
            return False

    async def record(db, **entry):
        entries.append(entry)

    monkeypatch.setattr(quotas, "get_worker_db_context", lambda: _Session())
    monkeypatch.setattr(quotas, "record_audit", record)
    return entries


def test_a_records_size_is_its_compact_utf8_json():
    assert quotas.record_size({}) == 2
    assert quotas.record_size({"a": "b"}) == len(b'{"a":"b"}')
    assert quotas.record_size({"a": "é"}) == len('{"a":"é"}'.encode())


async def test_a_record_exactly_at_the_limit_is_accepted_and_one_byte_over_is_refused(
    ctx, audited, monkeypatch
):
    table = SimpleNamespace(id=uuid.uuid4())
    values = {"a": "xxxx"}
    monkeypatch.setattr(settings, "TABLES_MAX_RECORD_BYTES", quotas.record_size(values))

    await quotas.enforce_record_size(ctx, table, values)
    with pytest.raises(QuotaExceededError) as raised:
        await quotas.enforce_record_size(ctx, table, {"a": "xxxxx"})

    assert raised.value.details == {"quota": "record_bytes", "limit": quotas.record_size(values)}
    assert audited[0]["details"] == raised.value.details
    assert audited[0]["action"] == "table.quota_refused"
    assert audited[0]["target_id"] == str(table.id)


@pytest.mark.parametrize(("held", "refused"), [(2, False), (3, True), (4, True)])
async def test_the_table_limit_refuses_at_the_ceiling_not_below_it(
    ctx, audited, monkeypatch, held, refused
):
    async def count(db, *, organization_id):
        assert organization_id == ctx.organization_id
        return held

    monkeypatch.setattr(settings, "TABLES_MAX_PER_ORGANIZATION", 3)
    monkeypatch.setattr(virtual_table_repo, "count_tables", count)

    if refused:
        with pytest.raises(QuotaExceededError) as raised:
            await quotas.enforce_table_count(None, ctx)
        assert raised.value.details == {"quota": "tables", "limit": 3}
        assert audited[0]["target_type"] == "organization"
        assert audited[0]["target_id"] == str(ctx.organization_id)
    else:
        await quotas.enforce_table_count(None, ctx)
        assert audited == []


@pytest.mark.parametrize(("held", "refused"), [(2, False), (3, True)])
async def test_the_record_limit_takes_the_count_lock_and_refuses_at_the_ceiling(
    ctx, audited, monkeypatch, held, refused
):
    table = SimpleNamespace(id=uuid.uuid4())
    locked: list[uuid.UUID] = []

    async def hold(db, scope, subject):
        locked.append(subject)

    async def count(db, *, table_id, organization_id, ceiling):
        assert (table_id, organization_id, ceiling) == (table.id, ctx.organization_id, 3)
        return held

    monkeypatch.setattr(settings, "TABLES_MAX_RECORDS_PER_TABLE", 3)
    monkeypatch.setattr(quotas, "hold_subject", hold)
    monkeypatch.setattr(virtual_table_repo, "count_records_up_to", count)

    if refused:
        with pytest.raises(QuotaExceededError) as raised:
            await quotas.enforce_record_count(None, ctx, table)
        assert raised.value.details == {"quota": "records", "limit": 3}
        assert audited[0]["target_type"] == "table"
    else:
        await quotas.enforce_record_count(None, ctx, table)
    assert locked == [table.id]
