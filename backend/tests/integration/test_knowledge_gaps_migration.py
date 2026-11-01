"""The knowledge-gap revisions' downgrades, exercised on rows that existed before they ran.

`tests/test_migrations.py` runs the chain over empty tables, so a downgrade that
left a drafter's or a classifier's `system_key` on an ordinary agent would pass
it - and the next upgrade would find an agent anybody may chat with under that
key. Nor would it see a miss read from an answer survive as a search. Each test
upgrades to its revision, seeds the rows, downgrades one step, reads them and
upgrades again.

Each test owns a database of its own - created for it, dropped after it, so
one test's revision is never another's starting point - for the reason
`test_migrations.py` does: it runs real migrations, and pointing
that at the model-built integration database (or a developer's) is how a run
empties something it should not.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text

from app.core.config import settings

pytestmark = pytest.mark.anyio

MIGRATION_DATABASE = f"agenticos_knowledge_gaps_mig_test_p{os.getpid()}"
_MAINTENANCE_DATABASE = "postgres"
_DRAFTERS = "0164_knowledge_gaps"
_SIGNALS = "0167_knowledge_gap_signals"
_COVERED = "0175_knowledge_gap_covered"


def _url(database: str) -> str:
    return f"{settings.DATABASE_URL_SYNC.rsplit('/', 1)[0]}/{database}"


def _alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        capture_output=True,
        text=True,
        cwd=".",
        env={**os.environ, "POSTGRES_DB": MIGRATION_DATABASE},
        timeout=120,
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stderr}"


def _outside_a_transaction(url: str, statement: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(statement)
    finally:
        engine.dispose()


def _server_reachable(url: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect():
            return True
    except Exception:
        return False
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def migration_database() -> Iterator[None]:
    maintenance = _url(_MAINTENANCE_DATABASE)
    if not _server_reachable(maintenance):
        if os.getenv("CI"):
            raise RuntimeError(
                f"No database reachable at {maintenance} but CI is set - refusing to skip."
            )
        pytest.skip("No database reachable - start one with `make docker-db`")

    drop = f'DROP DATABASE IF EXISTS "{MIGRATION_DATABASE}" WITH (FORCE)'
    _outside_a_transaction(maintenance, drop)
    _outside_a_transaction(maintenance, f'CREATE DATABASE "{MIGRATION_DATABASE}"')
    try:
        yield
    finally:
        _outside_a_transaction(maintenance, drop)


def _seed_system_agent(kind: str, key: str) -> tuple[uuid.UUID, uuid.UUID]:
    """An organization holding one system agent, and their ids."""
    user_id, org_id, agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO users (id, email, is_active, is_app_admin) "
                    "VALUES (:id, :email, true, false)"
                ),
                {"id": user_id, "email": f"{uuid.uuid4().hex}@example.com"},
            )
            conn.execute(
                text(
                    "INSERT INTO organizations "
                    "(id, name, slug, created_by_user_id, is_personal, chat_may_waive_approvals) "
                    "VALUES (:id, :name, :slug, :owner, false, false)"
                ),
                {
                    "id": org_id,
                    "name": "Acme",
                    "slug": f"acme-{uuid.uuid4().hex[:8]}",
                    "owner": user_id,
                },
            )
            conn.execute(
                text(
                    "INSERT INTO agents "
                    "(id, organization_id, slug, name, status, visibility, kind, system_key) "
                    "VALUES (:id, :org, :slug, :name, 'draft', 'org', :kind, :key)"
                ),
                {
                    "id": agent_id,
                    "org": org_id,
                    "slug": key.replace("_", "-"),
                    "name": key,
                    "kind": kind,
                    "key": key,
                },
            )
    finally:
        engine.dispose()
    return org_id, agent_id


def _seed_misses(org_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """A run with one search and one answer read as a miss."""
    run_id = uuid.uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_runs (id, organization_id, agent_id, status, surface, "
                    "input_tokens, output_tokens, cost_usd, cost_is_partial) "
                    "VALUES (:id, :org, :agent, 'completed', 'api', 0, 0, 0, false)"
                ),
                {"id": run_id, "org": org_id, "agent": agent_id},
            )
            for signal in ("retrieval", "answer"):
                conn.execute(
                    text(
                        "INSERT INTO knowledge_searches (id, organization_id, run_id, agent_id, "
                        "knowledge_base_ids, query, result_count, signal) VALUES "
                        "(:id, :org, :run, :agent, ARRAY[:kb]::uuid[], :query, 0, :signal)"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "org": org_id,
                        "run": run_id,
                        "agent": agent_id,
                        "kb": uuid.uuid4(),
                        "query": signal,
                        "signal": signal,
                    },
                )
    finally:
        engine.dispose()


def _queries() -> list[str]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            return list(conn.execute(text("SELECT query FROM knowledge_searches")).scalars())
    finally:
        engine.dispose()


def _kind_and_key(agent_id: uuid.UUID) -> tuple[str, str | None]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT kind, system_key FROM agents WHERE id = :id"), {"id": agent_id}
            ).one()
    finally:
        engine.dispose()
    return row.kind, row.system_key


def test_a_downgraded_drafter_is_an_ordinary_agent_holding_no_system_key() -> None:
    _alembic("upgrade", _DRAFTERS)
    _, drafter = _seed_system_agent("drafter", "knowledge_gap_drafter")

    _alembic("downgrade", "-1")
    after = _kind_and_key(drafter)
    _alembic("upgrade", _DRAFTERS)

    assert after == ("agent", None)
    assert _kind_and_key(drafter) == ("agent", None)


def test_undoing_signals_keeps_the_searches_and_unmarks_the_classifier() -> None:
    _alembic("upgrade", _SIGNALS)
    org_id, classifier = _seed_system_agent("classifier", "knowledge_gap_classifier")
    _seed_misses(org_id, classifier)

    _alembic("downgrade", "-1")
    after = _kind_and_key(classifier)
    queries = _queries()
    _alembic("upgrade", _SIGNALS)

    assert after == ("agent", None)
    assert queries == ["retrieval"]


def _seed_covered_and_refused(org_id: uuid.UUID) -> uuid.UUID:
    """A topic covered by a document, and an answer read as a refusal; the topic's id."""
    kb_id, document_id, topic_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conversation_id, message_id = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(_url(MIGRATION_DATABASE), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(
                text(
                    "INSERT INTO knowledge_bases (id, organization_id, name, visibility, scope, "
                    "collection_name, is_default, embedding_model, embedding_dim) VALUES "
                    "(:id, :org, 'Handbook', 'org', 'org', :collection, false, 'm', 3)"
                ),
                {"id": kb_id, "org": org_id, "collection": f"handbook_{kb_id.hex[:8]}"},
            )
            conn.execute(
                text(
                    "INSERT INTO rag_documents (id, collection_name, filename, filesize, "
                    "filetype, status, chunk_count, ingestion_config, organization_id, "
                    "knowledge_base_id, started_at) VALUES (:id, 'c', 'parking.md', 1, 'md', "
                    "'done', 0, '{}', :org, :kb, now())"
                ),
                {"id": document_id, "org": org_id, "kb": kb_id},
            )
            conn.execute(
                text(
                    "INSERT INTO knowledge_gap_topics (id, organization_id, knowledge_base_id, "
                    "centroid, embedding_model, status, covered_by_document_id) VALUES "
                    "(:id, :org, :kb, '[1, 0, 0]', 'm', 'covered', :document)"
                ),
                {"id": topic_id, "org": org_id, "kb": kb_id, "document": document_id},
            )
            conn.execute(
                text(
                    "INSERT INTO conversations (id, organization_id, is_archived) "
                    "VALUES (:id, :org, false)"
                ),
                {"id": conversation_id, "org": org_id},
            )
            conn.execute(
                text(
                    "INSERT INTO messages (id, conversation_id, role, content, ordinal) "
                    "VALUES (:id, :conversation, 'assistant', 'I cannot do that.', 1)"
                ),
                {"id": message_id, "conversation": conversation_id},
            )
            conn.execute(
                text(
                    "INSERT INTO knowledge_gap_classifications (message_id, knowledge_base_id, "
                    "organization_id, signal) VALUES (:message, :kb, :org, 'refused')"
                ),
                {"message": message_id, "kb": kb_id, "org": org_id},
            )
    finally:
        engine.dispose()
    return topic_id


def _status_and_refusals(topic_id: uuid.UUID) -> tuple[str, int]:
    engine = create_engine(_url(MIGRATION_DATABASE))
    try:
        with engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM knowledge_gap_topics WHERE id = :id"), {"id": topic_id}
            ).scalar_one()
            refusals = conn.execute(
                text("SELECT count(*) FROM knowledge_gap_classifications")
            ).scalar_one()
    finally:
        engine.dispose()
    return status, refusals


def test_undoing_covered_topics_reopens_them_and_forgets_refusals() -> None:
    _alembic("upgrade", _COVERED)
    org_id, _ = _seed_system_agent("classifier", "knowledge_gap_classifier")
    topic_id = _seed_covered_and_refused(org_id)

    _alembic("downgrade", "-1")
    after = _status_and_refusals(topic_id)
    _alembic("upgrade", _COVERED)

    assert after == ("open", 0)
    assert _status_and_refusals(topic_id) == ("open", 0)
