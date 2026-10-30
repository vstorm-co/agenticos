"""Which AgenticOS app a session runs in (#2305, #2097).

The desktop and phone apps load the console in a webview whose User-Agent
names the browser engine, not the app, so the console says which app it is in
and the sessions list names it - and marks the caller's own session.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import NotFoundError
from app.schemas.session import SessionAppUpdate
from app.services.session import SessionService

pytestmark = pytest.mark.anyio


@pytest.fixture
def service() -> SessionService:
    return SessionService(AsyncMock())


def _row(platform: str | None) -> MagicMock:
    row = MagicMock()
    row.id = uuid4()
    row.device_name = "Safari"
    row.device_type = "desktop"
    row.ip_address = "203.0.113.4"
    row.app_platform = platform
    row.app_version = "0.2.0" if platform else None
    row.created_at = datetime.now(UTC)
    row.last_used_at = datetime.now(UTC)
    return row


async def test_the_list_names_the_app_and_marks_the_callers_own_session(
    service: SessionService,
) -> None:
    app_row, browser_row = _row("macos"), _row(None)
    with (
        patch(
            "app.repositories.push_subscription.sessions_with_push",
            new=AsyncMock(return_value={app_row.id}),
        ),
        patch(
            "app.repositories.session.get_user_sessions",
            new=AsyncMock(return_value=[app_row, browser_row]),
        ),
        patch("app.repositories.session.count_user_sessions", new=AsyncMock(return_value=2)),
    ):
        page = await service.list_sessions(uuid4(), current_session_id=app_row.id)

    first, second = page.items
    assert first.push is True and second.push is False
    assert (first.app_platform, first.app_version, first.is_current) == ("macos", "0.2.0", True)
    assert (second.app_platform, second.app_version, second.is_current) == (None, None, False)


async def test_the_app_is_recorded_on_the_callers_own_session(service: SessionService) -> None:
    session_id, user_id = uuid4(), uuid4()
    with patch("app.repositories.session.set_app", new=AsyncMock(return_value=True)) as set_app:
        await service.record_app(
            session_id, user_id, SessionAppUpdate(platform="ios", version="0.1.0")
        )
    assert set_app.await_args.kwargs == {
        "session_id": session_id,
        "user_id": user_id,
        "platform": "ios",
        "version": "0.1.0",
    }


async def test_a_request_with_no_session_or_someone_elses_is_refused(
    service: SessionService,
) -> None:
    app = SessionAppUpdate(platform="android", version="0.1.0")
    with pytest.raises(NotFoundError):
        await service.record_app(None, uuid4(), app)
    with (
        patch("app.repositories.session.set_app", new=AsyncMock(return_value=False)),
        pytest.raises(NotFoundError),
    ):
        await service.record_app(uuid4(), uuid4(), app)


def test_only_a_known_app_and_a_plain_version_are_accepted() -> None:
    for bad in (
        {"platform": "toaster", "version": "1.0"},
        {"platform": "macos", "version": ""},
        {"platform": "macos", "version": "<script>"},
        {"platform": "macos", "version": "1" * 33},
    ):
        with pytest.raises(ValidationError):
            SessionAppUpdate.model_validate(bad)


async def test_the_repository_labels_only_an_open_session_of_the_user() -> None:
    from app.repositories import session as session_repo

    db = AsyncMock()
    db.execute.return_value = MagicMock(rowcount=1)
    assert await session_repo.set_app(
        db, session_id=uuid4(), user_id=uuid4(), platform="linux", version="0.2.0"
    )
    statement = str(db.execute.await_args.args[0])
    for column in ("user_id", "is_active", "impersonator_user_id"):
        assert column in statement
    db.execute.return_value = MagicMock(rowcount=0)
    assert not await session_repo.set_app(
        db, session_id=uuid4(), user_id=uuid4(), platform="linux", version="0.2.0"
    )
