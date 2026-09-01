"""Tests for the agent's runtime memory store (`_native`).

The store opens its own session per operation; here that session is faked and
the repository mocked, so what is under test is the orchestration and - the part
that carries the poisoning defense - the origin guard: an agent may read an
operator-authored file but edit or delete only its own.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.memory import MemoryOrigin
from app.repositories.memory import FactHit
from app.services.memory import _native
from app.services.rag.embeddings import EmbeddingService

pytestmark = pytest.mark.anyio

NATIVE = "app.services.memory._native"
REPO = "app.repositories.memory"
ORG, AGENT = uuid4(), uuid4()


@asynccontextmanager
async def _fake_session():
    yield MagicMock()


@pytest.fixture(autouse=True)
def _own_session(monkeypatch):
    """Every `_native` call opens its own session; fake it for all of them."""
    monkeypatch.setattr(f"{NATIVE}.get_db_context", _fake_session)


def _row(*, origin=MemoryOrigin.AGENT.value, content="body"):
    row = MagicMock()
    row.origin = origin
    row.content = content
    row.name = "prefs"
    row.description = "d"
    row.kind = "note"
    return row


class TestListFiles:
    async def test_it_returns_detached_index_entries(self):
        with patch(f"{REPO}.list_in_partition", new=AsyncMock(return_value=[_row()])):
            entries = await _native.list_files(organization_id=ORG, agent_id=AGENT, scope_key=None)
        assert entries[0].name == "prefs"
        assert entries[0].kind == "note"


class TestReadFile:
    async def test_it_returns_the_body(self):
        with patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=_row(content="tea"))):
            assert (
                await _native.read_file(
                    organization_id=ORG, agent_id=AGENT, scope_key=None, name="prefs"
                )
                == "tea"
            )

    async def test_a_missing_file_is_none(self):
        with patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)):
            assert (
                await _native.read_file(
                    organization_id=ORG, agent_id=AGENT, scope_key=None, name="gone"
                )
                is None
            )


class TestWriteFile:
    async def test_a_new_name_is_created_as_an_agent_row(self):
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{REPO}.create", new=AsyncMock()) as create,
        ):
            created = await _native.write_file(
                organization_id=ORG,
                agent_id=AGENT,
                scope_key="user:1",
                name="prefs",
                content="x",
                description="d",
                kind="note",
            )
        assert created is True
        assert create.await_args.kwargs["origin"] == MemoryOrigin.AGENT.value
        assert create.await_args.kwargs["end_user_scope_key"] == "user:1"

    async def test_a_taken_name_is_not_overwritten(self):
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=_row())),
            patch(f"{REPO}.create", new=AsyncMock()) as create,
        ):
            created = await _native.write_file(
                organization_id=ORG,
                agent_id=AGENT,
                scope_key=None,
                name="prefs",
                content="x",
                description=None,
                kind="note",
            )
        assert created is False
        create.assert_not_awaited()

    async def test_a_racing_create_is_reported_taken_rather_than_crashing(self, monkeypatch):
        # Two writers pass the name check, and the second loses the unique-index
        # race. The IntegrityError is rolled back and the name reported taken, not
        # left to crash the run.
        session = MagicMock()
        session.rollback = AsyncMock()

        @asynccontextmanager
        async def _session():
            yield session

        monkeypatch.setattr(f"{NATIVE}.get_db_context", _session)
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                f"{REPO}.create",
                new=AsyncMock(side_effect=IntegrityError("insert", {}, Exception("duplicate"))),
            ),
        ):
            created = await _native.write_file(
                organization_id=ORG,
                agent_id=AGENT,
                scope_key=None,
                name="prefs",
                content="x",
                description=None,
                kind="note",
            )
        assert created is False
        session.rollback.assert_awaited_once()


class TestEditFile:
    async def test_a_missing_file_is_missing(self):
        with patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)):
            assert (
                await _native.edit_file(
                    organization_id=ORG, agent_id=AGENT, scope_key=None, name="gone", content="x"
                )
                == "missing"
            )

    async def test_an_operator_file_is_protected(self):
        with (
            patch(
                f"{REPO}.get_by_name",
                new=AsyncMock(return_value=_row(origin=MemoryOrigin.OPERATOR.value)),
            ),
            patch(f"{REPO}.update", new=AsyncMock()) as update,
        ):
            result = await _native.edit_file(
                organization_id=ORG, agent_id=AGENT, scope_key=None, name="policy", content="x"
            )
        assert result == "protected"
        update.assert_not_awaited()

    async def test_an_agent_file_is_edited(self):
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=_row())),
            patch(f"{REPO}.update", new=AsyncMock()) as update,
        ):
            result = await _native.edit_file(
                organization_id=ORG, agent_id=AGENT, scope_key=None, name="prefs", content="new"
            )
        assert result == "ok"
        assert update.await_args.kwargs["update_data"] == {"content": "new"}


class TestDeleteFile:
    async def test_a_missing_file_is_missing(self):
        with patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)):
            assert (
                await _native.delete_file(
                    organization_id=ORG, agent_id=AGENT, scope_key=None, name="gone"
                )
                == "missing"
            )

    async def test_an_operator_file_is_protected(self):
        with (
            patch(
                f"{REPO}.get_by_name",
                new=AsyncMock(return_value=_row(origin=MemoryOrigin.OPERATOR.value)),
            ),
            patch(f"{REPO}.delete", new=AsyncMock()) as remove,
        ):
            result = await _native.delete_file(
                organization_id=ORG, agent_id=AGENT, scope_key=None, name="policy"
            )
        assert result == "protected"
        remove.assert_not_awaited()

    async def test_an_agent_file_is_removed(self):
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=_row())),
            patch(f"{REPO}.delete", new=AsyncMock()) as remove,
        ):
            result = await _native.delete_file(
                organization_id=ORG, agent_id=AGENT, scope_key=None, name="prefs"
            )
        assert result == "ok"
        remove.assert_awaited_once()


class TestEmbedding:
    def test_the_embedder_is_built_once(self):
        first = _native._embedder_service()
        assert first is _native._embedder_service()
        assert isinstance(first, EmbeddingService)

    async def test_embed_runs_the_embedder(self, monkeypatch):
        embedder = MagicMock()
        embedder.embed_query = MagicMock(return_value=[1.0, 2.0])
        monkeypatch.setattr(f"{NATIVE}._embedder_service", lambda: embedder)
        assert await _native._embed("hello") == [1.0, 2.0]
        embedder.embed_query.assert_called_once_with("hello")


class TestRemember:
    async def test_it_embeds_then_stores_scoped(self, monkeypatch):
        monkeypatch.setattr(f"{NATIVE}._embed", AsyncMock(return_value=[0.1, 0.2]))
        with patch(f"{REPO}.create_fact", new=AsyncMock()) as create:
            await _native.remember(
                organization_id=ORG, agent_id=AGENT, scope_key="user:1", content="likes tea"
            )
        assert create.await_args.kwargs["embedding"] == [0.1, 0.2]
        assert create.await_args.kwargs["end_user_scope_key"] == "user:1"
        assert create.await_args.kwargs["content"] == "likes tea"


class TestRecall:
    async def test_it_embeds_the_query_and_returns_hits(self, monkeypatch):
        monkeypatch.setattr(f"{NATIVE}._embed", AsyncMock(return_value=[0.3]))
        hits = [FactHit(content="likes tea", score=0.9)]
        with patch(f"{REPO}.recall_facts", new=AsyncMock(return_value=hits)) as recall:
            out = await _native.recall(
                organization_id=ORG, agent_id=AGENT, scope_key=None, query="q", limit=3
            )
        assert out == hits
        assert recall.await_args.kwargs["query_embedding"] == [0.3]
        assert recall.await_args.kwargs["limit"] == 3
