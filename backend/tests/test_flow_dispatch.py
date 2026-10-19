"""The services that hand background work a row they have just written (#417, #2219).

Each of these writes a row and asks for work whose first act is to read that row
back by id, on a session of its own. Started before the commit, the work looked
for a row no other transaction could see yet and gave up: an upload that answered
`{"status": "processing"}` and stayed that way, a sync log that never moved off
`running`.

Now the work is a job written on the service's own session, so it commits with
the row or not at all - `tests/integration/test_background_job_queue.py` proves
that a rolled-back enqueue leaves nothing behind. These pin each call site to
it: the job is queued on *this* session, as the right kind, carrying the ids
the worker will read back.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, BadRequestError
from app.core.permissions import AuthContext
from app.repositories import rag_document_repo
from app.repositories import sync_log as sync_log_repo
from app.repositories import sync_source as sync_source_repo
from app.services.ingestion_config import IngestionConfig, IngestionConfigService
from app.services.rag_document import RAGDocumentService
from app.services.rag_sync import RAGSyncService
from app.services.sync_source import SyncSourceService
from app.worker import jobs

pytestmark = pytest.mark.anyio


@pytest.fixture
def session():
    """A session with no bind: the queued job is captured before it would reach one."""
    from sqlalchemy.ext.asyncio import AsyncSession

    return AsyncSession()


@pytest.fixture
def queued(monkeypatch) -> list[tuple[object, jobs.TaskKind, jobs.Payload, dict[str, object]]]:
    """Every `enqueue` the services make, with the session it was made on."""
    calls: list[tuple[object, jobs.TaskKind, jobs.Payload, dict[str, object]]] = []

    async def enqueue(db, task, payload, **options):
        calls.append((db, task, payload, options))
        return uuid4()

    for module in (
        "app.services.rag_sync",
        "app.services.sync_source",
        "app.services.rag_document",
    ):
        monkeypatch.setattr(f"{module}.enqueue", enqueue)
    return calls


async def test_a_local_sync_is_queued_on_the_session_that_wrote_its_log(
    session, queued, monkeypatch
) -> None:
    sync_log = SimpleNamespace(id=uuid4())
    kb_id = uuid4()
    monkeypatch.setattr(sync_log_repo, "create", AsyncMock(return_value=sync_log))

    await RAGSyncService(session).start_local_sync(
        collection_name="handbooks", mode="full", path="/srv/docs", knowledge_base_id=kb_id
    )

    [(db, task, payload, _)] = queued
    assert db is session
    assert task is jobs.SYNC_COLLECTION
    assert payload == jobs.SyncCollection(
        sync_log_id=sync_log.id,
        source="local",
        collection_name="handbooks",
        mode="full",
        path="/srv/docs",
        knowledge_base_id=kb_id,
    )


async def test_a_triggered_source_sync_is_queued_waiting_behind_any_other_sync_of_it(
    session, queued, monkeypatch
) -> None:
    source = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        connector_type="google_drive",
        collection_name="handbooks",
        sync_mode="full",
    )
    sync_log = SimpleNamespace(id=uuid4())
    savepoint = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr(session, "begin_nested", AsyncMock(return_value=savepoint))
    monkeypatch.setattr(sync_source_repo, "get_by_id", AsyncMock(return_value=source))
    monkeypatch.setattr(sync_log_repo, "create", AsyncMock(return_value=sync_log))

    assert await SyncSourceService(session).trigger_sync(str(source.id)) is sync_log
    savepoint.commit.assert_awaited_once()

    [(db, task, payload, options)] = queued
    assert db is session
    assert task is jobs.SYNC_SOURCE
    assert payload == jobs.SyncConnectorSource(source_id=source.id, sync_log_id=sync_log.id)
    assert options["concurrency_key"] == options["dedupe_key"] == f"sync-source:{source.id}"
    assert options["organization_id"] == source.organization_id


def _source() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        connector_type="google_drive",
        collection_name="handbooks",
        sync_mode="full",
    )


def _dropping(monkeypatch, session, source, *, queued: list[object], logs: dict) -> SimpleNamespace:
    """`enqueue` drops every insert; `latest_with_dedupe_key` answers `queued` in turn."""
    savepoint = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())
    created = SimpleNamespace(id=uuid4())
    logs[created.id] = created
    monkeypatch.setattr(session, "begin_nested", AsyncMock(return_value=savepoint))
    monkeypatch.setattr(sync_source_repo, "get_by_id", AsyncMock(return_value=source))
    monkeypatch.setattr(sync_log_repo, "create", AsyncMock(return_value=created))
    monkeypatch.setattr(sync_log_repo, "get_by_id", AsyncMock(side_effect=lambda db, i: logs[i]))
    monkeypatch.setattr("app.services.sync_source.enqueue", AsyncMock(return_value=None))
    monkeypatch.setattr(
        "app.services.sync_source.background_job_repo.latest_with_dedupe_key",
        AsyncMock(side_effect=queued),
    )
    savepoint.created = created
    return savepoint


def _queued_job(source, log_id, *, status: str = "queued") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        status=status,
        payload=jobs.SYNC_SOURCE.dump(
            jobs.SyncConnectorSource(source_id=source.id, sync_log_id=log_id)
        ),
    )


async def test_a_sync_asked_for_while_one_is_queued_answers_with_that_one(
    session, monkeypatch
) -> None:
    """No log for a sync no job will ever run: it would read `running` for good."""
    source = _source()
    queued_log = SimpleNamespace(id=uuid4())
    savepoint = _dropping(
        monkeypatch,
        session,
        source,
        queued=[_queued_job(source, queued_log.id)],
        logs={queued_log.id: queued_log},
    )

    answer = await SyncSourceService(session).trigger_sync(str(source.id))

    assert answer is queued_log
    savepoint.rollback.assert_awaited_once()
    savepoint.commit.assert_not_awaited()


async def test_a_queued_scheduled_sync_adopts_the_askers_log(session, monkeypatch) -> None:
    """The scheduler queues a sync with no log; the person who asked gets one that finishes."""
    source = _source()
    scheduled = _queued_job(source, None)
    savepoint = _dropping(monkeypatch, session, source, queued=[scheduled], logs={})
    adopt = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.services.sync_source.background_job_repo.replace_queued_payload", adopt
    )

    answer = await SyncSourceService(session).trigger_sync(str(source.id))

    assert answer is savepoint.created
    savepoint.commit.assert_awaited_once()
    (_db, job_id, payload) = adopt.await_args.args
    assert job_id == scheduled.id
    assert jobs.SYNC_SOURCE.load(payload).sync_log_id == savepoint.created.id


async def test_a_queued_sync_claimed_before_it_was_looked_at_is_queued_behind(
    session, monkeypatch
) -> None:
    source = _source()
    savepoint = _dropping(
        monkeypatch,
        session,
        source,
        queued=[_queued_job(source, None, status="running")],
        logs={},
    )
    monkeypatch.setattr("app.services.sync_source.enqueue", AsyncMock(side_effect=[None, uuid4()]))

    answer = await SyncSourceService(session).trigger_sync(str(source.id))

    assert answer is savepoint.created
    savepoint.commit.assert_awaited_once()


async def test_a_scheduled_sync_claimed_while_adopting_is_queued_behind(
    session, monkeypatch
) -> None:
    source = _source()
    savepoint = _dropping(
        monkeypatch, session, source, queued=[_queued_job(source, None), None], logs={}
    )
    monkeypatch.setattr(
        "app.services.sync_source.background_job_repo.replace_queued_payload",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr("app.services.sync_source.enqueue", AsyncMock(side_effect=[None, uuid4()]))

    assert await SyncSourceService(session).trigger_sync(str(source.id)) is savepoint.created


async def test_dropped_twice_with_nothing_queued_is_a_bug_not_an_answer(
    session, monkeypatch
) -> None:
    source = _source()
    _dropping(monkeypatch, session, source, queued=[None, None], logs={})

    with pytest.raises(AssertionError, match="dropped as queued twice"):
        await SyncSourceService(session).trigger_sync(str(source.id))


async def test_an_uploaded_document_is_queued_for_parsing_on_the_session_that_wrote_it(
    session, queued, monkeypatch, tmp_path: Path
) -> None:
    """The upload path, which is where #417 was actually noticed."""
    document = SimpleNamespace(id=uuid4(), organization_id=uuid4())
    collection = SimpleNamespace(
        collection_name="handbooks",
        embedding_model="text-embedding-3-small",
        ingestion_config=IngestionConfig().model_dump(mode="json"),
    )

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(rag_document_repo, "create", AsyncMock(return_value=document))
    monkeypatch.setattr(
        IngestionConfigService, "resolved_image_model", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        "app.repositories.collection_teardown_repo.is_reserved", AsyncMock(return_value=False)
    )
    storage = SimpleNamespace(save=AsyncMock(return_value="rag/handbooks/policy.txt"))
    monkeypatch.setattr("app.services.rag_document.get_file_storage", lambda: storage)

    accepted = await RAGDocumentService(session).dispatch_upload(
        ctx=AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
        collection=collection,
        file_data=b"a policy nobody reads",
        filename="policy.txt",
        replace=False,
        vector_store=SimpleNamespace(create_collection=AsyncMock()),
    )

    assert accepted.status == "processing"
    [(db, task, payload, options)] = queued
    assert db is session
    assert task is jobs.INGEST_DOCUMENT
    assert isinstance(payload, jobs.IngestDocument)
    assert (payload.rag_document_id, payload.attempt, payload.replace) == (document.id, 1, False)
    assert Path(payload.filepath).read_bytes() == b"a policy nobody reads"
    assert options["organization_id"] == document.organization_id


async def test_an_upload_to_a_name_mid_teardown_is_refused(session, monkeypatch) -> None:
    """A write to a reserved collection name is refused the way a claim of one is: the
    durable drop frees the name only after the table is gone, and a write slipped into
    that window would recreate the table the drop then destroys, orphaning this row and
    losing its vectors (#1364). Refused before the file is stored, so nothing to unlink.
    """
    collection = SimpleNamespace(
        collection_name="handbooks",
        embedding_model="text-embedding-3-small",
        ingestion_config=IngestionConfig().model_dump(mode="json"),
    )
    monkeypatch.setattr(
        "app.repositories.collection_teardown_repo.is_reserved", AsyncMock(return_value=True)
    )
    save = AsyncMock()
    monkeypatch.setattr(
        "app.services.rag_document.get_file_storage", lambda: SimpleNamespace(save=save)
    )

    with pytest.raises(AlreadyExistsError):
        await RAGDocumentService(session).dispatch_upload(
            ctx=AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
            collection=collection,
            file_data=b"a policy nobody reads",
            filename="policy.txt",
            replace=False,
            vector_store=SimpleNamespace(create_collection=AsyncMock()),
        )

    save.assert_not_awaited()


def _failed_document() -> SimpleNamespace:
    """A document whose ingestion failed, with the file the upload kept."""
    return SimpleNamespace(
        id=uuid4(),
        status="error",
        storage_path="rag/handbooks/policy.txt",
        collection_name="handbooks",
        filename="policy.txt",
        ingestion_attempt=1,
        organization_id=uuid4(),
    )


async def test_retrying_a_failed_document_parses_it_again(
    session, queued, monkeypatch, tmp_path: Path
) -> None:
    """#441: the retry endpoint reported queueing a parse and queued nothing.

    A retry that only moves the row to `processing` and clears the error is
    worse than the failure it was asked to fix - the diagnosis is gone and the
    document waits for a worker that was never told about it.
    """
    document = _failed_document()
    retried = SimpleNamespace(**{**vars(document), "status": "processing", "ingestion_attempt": 2})

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=document))
    monkeypatch.setattr(rag_document_repo, "update_status", AsyncMock(return_value=retried))
    storage = SimpleNamespace(load=AsyncMock(return_value=b"a policy nobody reads"))
    monkeypatch.setattr("app.services.rag_document.get_file_storage", lambda: storage)

    await RAGDocumentService(session).retry_ingestion(str(document.id))

    [(db, task, payload, _)] = queued
    assert (db, task) == (session, jobs.INGEST_DOCUMENT)
    assert isinstance(payload, jobs.IngestDocument)
    assert (payload.rag_document_id, payload.replace, payload.attempt) == (document.id, True, 2), (
        "a retry must replace what the first attempt indexed, or a document "
        "that half-succeeded is represented twice in the collection"
    )
    storage.load.assert_awaited_once_with("rag/handbooks/policy.txt")


async def test_retrying_a_document_conditions_the_write_on_the_attempt_it_read(
    session, queued, monkeypatch, tmp_path: Path
) -> None:
    """Two concurrent retries reading the same `ingestion_attempt` must not
    both win - the same "still current, not just read-then-write" guarantee
    `complete_ingestion`/`fail_ingestion` already condition their own writes
    on. An unconditional write here let two racing retries both compute
    `new_attempt=2` and dispatch two parses under one occurrence id."""
    document = _failed_document()
    retried = SimpleNamespace(**{**vars(document), "status": "processing"})

    monkeypatch.setattr(settings, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=document))
    update = AsyncMock(return_value=retried)
    monkeypatch.setattr(rag_document_repo, "update_status", update)
    storage = SimpleNamespace(load=AsyncMock(return_value=b"a policy nobody reads"))
    monkeypatch.setattr("app.services.rag_document.get_file_storage", lambda: storage)

    await RAGDocumentService(session).retry_ingestion(str(document.id))

    assert update.call_args.kwargs["expected_attempt"] == document.ingestion_attempt


async def test_retrying_a_document_with_no_stored_file_is_refused(session, monkeypatch) -> None:
    """Documents ingested before uploads kept their file have nothing to re-read."""
    document = _failed_document()
    document.storage_path = ""
    update = AsyncMock()
    monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=document))
    monkeypatch.setattr(rag_document_repo, "update_status", update)

    with pytest.raises(BadRequestError):
        await RAGDocumentService(session).retry_ingestion(str(document.id))

    # The row keeps the error that explains it: a refusal must not clear the
    # diagnosis on the way out, which is what made #441 one-way.
    update.assert_not_awaited()


async def test_retrying_a_document_that_did_not_fail_is_refused_not_a_500(
    session, monkeypatch
) -> None:
    """It raised a bare `ValueError`, which the handlers can only call a 500."""
    document = _failed_document()
    document.status = "done"
    monkeypatch.setattr(rag_document_repo, "get_by_id", AsyncMock(return_value=document))

    with pytest.raises(BadRequestError):
        await RAGDocumentService(session).retry_ingestion(str(document.id))


async def test_a_scheduled_runs_log_is_opened_with_nothing_queued(session, monkeypatch) -> None:
    """The run is already going; queueing another would sync the source twice (#2248)."""
    source = _source()
    created = SimpleNamespace(id=uuid4())
    create = AsyncMock(return_value=created)
    monkeypatch.setattr(sync_log_repo, "create", create)
    queued = AsyncMock()
    monkeypatch.setattr("app.services.sync_source.enqueue", queued)

    log = await SyncSourceService(session).open_sync_log(source, collection_name="handbooks")

    assert log is created
    assert create.await_args.kwargs["triggered_by_user_id"] is None
    assert create.await_args.kwargs["collection_name"] == "handbooks"
    queued.assert_not_awaited()
