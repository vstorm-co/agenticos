"""The worker ingestion gate refuses a write to a collection mid-teardown (#1382).

`_still_ingestable` is the `still_wanted` gate shared by upload, sync and retry: it
skips the vector write when the document's tracking row is gone (a collection dropped
while the file parsed, #1275) or the name is reserved for a deferred drop. The
reservation is the window the row check alone misses - a default cleared with an
active sync keeps its row, so the row survives while its table is reserved to be
dropped, and re-indexing would recreate the very table the drop is about to destroy.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.worker.tasks import rag_tasks

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _db() -> Any:
    yield MagicMock()


def _patches(*, is_reserved: AsyncMock, row: object | None) -> list[Any]:
    return [
        patch.object(rag_tasks, "get_worker_db_context", _db),
        patch("app.repositories.collection_teardown_repo.is_reserved", is_reserved),
        patch("app.repositories.rag_document_repo.get_by_id", AsyncMock(return_value=row)),
    ]


class TestTheIngestionGate:
    async def test_a_reserved_collection_is_not_ingestable_even_with_a_live_row(self) -> None:
        """The row survives a default clear, so the reservation is what stops the sync
        re-indexing into the table the drop is about to destroy (#1382)."""
        get_by_id = AsyncMock(return_value=MagicMock())
        with (
            patch.object(rag_tasks, "get_worker_db_context", _db),
            patch(
                "app.repositories.collection_teardown_repo.is_reserved",
                AsyncMock(return_value=True),
            ),
            patch("app.repositories.rag_document_repo.get_by_id", get_by_id),
        ):
            assert await rag_tasks._still_ingestable(str(uuid4()), "docs") is False
        get_by_id.assert_not_awaited()  # reservation short-circuits before the row read

    async def test_a_missing_row_is_not_ingestable(self) -> None:
        for p in _patches(is_reserved=AsyncMock(return_value=False), row=None):
            p.start()
        try:
            assert await rag_tasks._still_ingestable(str(uuid4()), "docs") is False
        finally:
            patch.stopall()

    async def test_a_live_row_in_an_unreserved_collection_is_ingestable(self) -> None:
        for p in _patches(is_reserved=AsyncMock(return_value=False), row=MagicMock()):
            p.start()
        try:
            assert await rag_tasks._still_ingestable(str(uuid4()), "docs") is True
        finally:
            patch.stopall()

    async def test_an_error_is_fail_safe_and_answers_yes(self) -> None:
        """Any failure indexes anyway, so the guard never blocks a legitimate write."""
        for p in _patches(is_reserved=AsyncMock(side_effect=RuntimeError("db down")), row=None):
            p.start()
        try:
            assert await rag_tasks._still_ingestable(str(uuid4()), "docs") is True
        finally:
            patch.stopall()
