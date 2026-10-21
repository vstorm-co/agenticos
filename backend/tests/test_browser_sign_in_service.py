"""A person's own saved sign-ins: listing them and forgetting one (#2129).

The service and route halves directly, with the repository mocked; who reaches
which row is a join and is proved against Postgres in
`tests/integration/test_browser_sign_ins.py`.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.routes.v1.browser_sign_ins import forget_sign_in, my_sign_ins
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.repositories import browser_sign_in as sign_in_repo
from app.services.browser_sign_in import BrowserSignInService

pytestmark = pytest.mark.anyio


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role="member")


async def test_the_list_is_the_caller_s_own_in_this_organization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = _ctx()
    rows = [SimpleNamespace(site="linkedin.com")]
    listed = AsyncMock(return_value=rows)
    monkeypatch.setattr(sign_in_repo, "list_for", listed)

    assert await BrowserSignInService(MagicMock()).mine(ctx) == rows
    assert listed.await_args.kwargs == {
        "organization_id": ctx.organization_id,
        "user_id": ctx.user_id,
    }


async def test_forgetting_one_that_is_not_the_caller_s_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sign_in_repo, "get", AsyncMock(return_value=None))
    deleted = AsyncMock()
    monkeypatch.setattr(sign_in_repo, "delete", deleted)

    with pytest.raises(NotFoundError):
        await BrowserSignInService(MagicMock()).forget(_ctx(), uuid.uuid4())
    deleted.assert_not_awaited()


async def test_forgetting_the_caller_s_own_deletes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    row = SimpleNamespace(site="linkedin.com")
    monkeypatch.setattr(sign_in_repo, "get", AsyncMock(return_value=row))
    deleted = AsyncMock()
    monkeypatch.setattr(sign_in_repo, "delete", deleted)
    db = MagicMock()

    await BrowserSignInService(db).forget(_ctx(), uuid.uuid4())

    deleted.assert_awaited_once_with(db, db_sign_in=row)


async def test_the_routes_answer_with_a_count_and_hand_forgetting_to_the_service() -> None:
    ctx = _ctx()
    service = MagicMock(mine=AsyncMock(return_value=["a", "b"]), forget=AsyncMock())
    sign_in_id = uuid.uuid4()

    assert await my_sign_ins(service, ctx) == {"items": ["a", "b"], "total": 2}
    await forget_sign_in(sign_in_id, service, ctx)

    service.forget.assert_awaited_once_with(ctx, sign_in_id)
