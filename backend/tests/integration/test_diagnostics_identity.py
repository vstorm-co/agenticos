"""The database, rather than a process-local cache, owns the installation key."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.background_worker import BackgroundWorker
from app.db.models.diagnostics import DiagnosticsIdentity
from app.db.models.rag_document import RAGDocument
from app.repositories import diagnostics as repo

pytestmark = pytest.mark.anyio


async def test_initialization_keeps_the_first_key_and_never_replaces_it(db):
    first = await repo.initialize(db, sealed_seed="first", key_version=1)
    second = await repo.initialize(db, sealed_seed="second", key_version=2)
    assert first.id == second.id == 1
    assert second.sealed_seed == "first"
    assert second.secret_key_version == 1
    assert await repo.get(db, lock=True) is second
    await repo.save(db, row=second)


async def test_a_second_identity_is_rejected_by_the_database(db):
    db.add(DiagnosticsIdentity(id=2, sealed_seed="not-a-second-key", secret_key_version=1))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_aggregates_count_closed_failure_categories_without_loading_contents(db):
    now = datetime.now(UTC)
    assert await repo.get(db) is None
    assert not await repo.worker_alive(db, now=now)
    assert await repo.failures(db, since=now - timedelta(hours=1), until=now) == []
    assert all(
        count == 0
        for count in (await repo.feature_counts(db, since=now - timedelta(days=30))).values()
    )
    db.add(
        BackgroundWorker(
            id="private-host-worker",
            hostname="private-host",
            pools=["system"],
            started_at=now,
            heartbeat_at=now,
        )
    )
    db.add(
        RAGDocument(
            collection_name="private-collection",
            filename="private-file.pdf",
            filetype="pdf",
            status="error",
            error_message="private raw exception",
            updated_at=now,
        )
    )
    await db.flush()
    assert await repo.worker_alive(db, now=now)
    counts = await repo.feature_counts(db, since=now - timedelta(days=30))
    assert counts["rag"] == 1
    failures = await repo.failures(
        db, since=now - timedelta(hours=1), until=now + timedelta(seconds=1)
    )
    assert failures == [("rag", "ingestion_failed", 1)]
    assert "private" not in str((counts, failures))
