"""A paused source is refused before a manual trigger creates any work."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from click.testing import CliRunner
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands import rag as rag_command
from app.core.exceptions import BadRequestError
from app.db.models.sync_source import SyncSource
from app.repositories import sync_log_repo, sync_source_repo
from app.services import sync_source as source_module
from app.services.sync_source import PAUSED_SOURCE, SyncSourceService

pytestmark = pytest.mark.anyio


@pytest.fixture
def paused(monkeypatch: pytest.MonkeyPatch) -> SyncSource:
    source = SyncSource(id=uuid4(), collection_name="docs", is_active=False)
    monkeypatch.setattr(sync_source_repo, "get_by_id", AsyncMock(return_value=source))
    return source


async def test_a_paused_source_creates_neither_a_log_nor_a_job(
    paused: SyncSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_log, enqueue = AsyncMock(), AsyncMock()
    monkeypatch.setattr(sync_log_repo, "create", create_log)
    monkeypatch.setattr(source_module, "enqueue", enqueue)
    async with AsyncSession() as db:
        with pytest.raises(BadRequestError) as refusal:
            await SyncSourceService(db).trigger_sync(str(paused.id))

    assert refusal.value.message == PAUSED_SOURCE
    assert refusal.value.details == {"source_id": str(paused.id)}
    create_log.assert_not_awaited()
    enqueue.assert_not_awaited()


def test_the_cli_reports_a_paused_source_without_queueing_work(
    paused: SyncSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    @asynccontextmanager
    async def session() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession() as db:
            yield db

    enqueue = AsyncMock()
    monkeypatch.setattr(rag_command, "get_db_context", session)
    monkeypatch.setattr(source_module, "enqueue", enqueue)

    result = CliRunner().invoke(rag_command.rag_source_sync, [str(paused.id)])

    assert PAUSED_SOURCE in result.output
    assert "Sync triggered" not in result.output
    enqueue.assert_not_awaited()
