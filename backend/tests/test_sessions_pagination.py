"""Paging a user's signed-in devices.

The interesting part is not that a page comes back - it is that `total` counts
the user's sessions rather than the page. Without that the client cannot tell a
full page from the last one, and revoking the final row on page three leaves it
sitting on a page that no longer exists.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.repositories import session as session_repo
from app.services.session import SessionService

pytestmark = pytest.mark.anyio


def _session_row(device: str) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.device_name = device
    row.device_type = "desktop"
    row.ip_address = "203.0.113.4"
    row.created_at = datetime.now(UTC)
    row.last_used_at = datetime.now(UTC)
    return row


@pytest.fixture
def service() -> SessionService:
    return SessionService(AsyncMock())


async def test_a_page_reports_the_total_not_its_own_length(service: SessionService) -> None:
    """The client pages on `total`; the page's own size cannot tell it anything.

    This was the bug in the unpaginated version: it returned every session and
    set `total` to how many it happened to return, which is only right when
    there is exactly one page.
    """
    user_id = uuid4()
    page = [_session_row("Chrome"), _session_row("Safari")]

    with (
        patch(
            "app.repositories.session.get_user_sessions", new=AsyncMock(return_value=page)
        ) as fetch,
        patch("app.repositories.session.count_user_sessions", new=AsyncMock(return_value=17)),
    ):
        result = await service.list_sessions(user_id, skip=10, limit=2)

    assert len(result.items) == 2
    assert result.total == 17
    assert fetch.await_args.kwargs == {"open_only": True, "skip": 10, "limit": 2}


async def test_the_page_is_what_the_caller_asked_for(service: SessionService) -> None:
    """A limit the route did not pass must not silently become "everything"."""
    with (
        patch(
            "app.repositories.session.get_user_sessions", new=AsyncMock(return_value=[])
        ) as fetch,
        patch("app.repositories.session.count_user_sessions", new=AsyncMock(return_value=0)),
    ):
        await service.list_sessions(uuid4())

    assert fetch.await_args.kwargs["limit"] is not None
    assert fetch.await_args.kwargs["skip"] == 0


class TestRepositoryQuery:
    """The query itself, which is where an unstable page order would come from."""

    @staticmethod
    async def _statement(**kwargs: Any) -> Any:
        db = AsyncMock()
        db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: MagicMock(all=list)))

        await session_repo.get_user_sessions(db, uuid4(), **kwargs)

        return db.execute.await_args.args[0]

    async def test_the_order_is_total_so_a_row_cannot_land_on_two_pages(self) -> None:
        """`last_used_at` ties on two sign-ins in the same moment.

        Postgres is free to return tied rows in any order, and a page boundary
        falling inside a tie shows one session twice and another never.
        """
        statement = await self._statement(skip=5, limit=5)

        assert "ORDER BY sessions.last_used_at DESC, sessions.id" in str(statement)
        assert statement._limit_clause is not None
        assert statement._offset_clause is not None

    async def test_no_limit_means_every_session(self) -> None:
        """Revoking and validating a refresh token need the whole set, not a page."""
        statement = await self._statement()

        assert statement._limit_clause is None
