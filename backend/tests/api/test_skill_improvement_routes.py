"""Skill session routes pass the caller, the skill and the session to the service, and its
refusals back."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import BaseModel

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.main import app
from app.services.skill_improvement import SkillImprovementService

pytestmark = pytest.mark.anyio

_SKILL, _RUN, _HUNK, _FORK = (UUID(int=n) for n in range(1, 5))
_ROOT = f"/skills/{_SKILL}/improvements"
_ONE = f"{_ROOT}/{_RUN}"
_HASH = "a" * 64


@pytest.mark.parametrize(
    ("method", "path", "operation", "body"),
    [
        ("POST", f"{_ROOT}/estimate", "estimate", {"fork_id": str(_FORK)}),
        ("POST", _ROOT, "start", {"budget_usd": "5"}),
        ("GET", _ROOT, "list_for_skill", None),
        ("GET", _ONE, "read", None),
        ("GET", f"{_ONE}/evidence", "problems", None),
        ("GET", f"{_ONE}/changes", "changes", None),
        ("PUT", f"{_ONE}/changes/{_HUNK}", "edit_change", {"edited_text": "Reworded"}),
        ("PUT", f"{_ONE}/selection", "choose_changes", {"hunk_ids": [str(_HUNK)]}),
        ("POST", f"{_ONE}/continue/estimate", "estimate_continuation", {"mode": "thorough"}),
        ("POST", f"{_ONE}/continue/estimate", "estimate_continuation", None),
        (
            "POST",
            f"{_ONE}/apply",
            "apply",
            {"confirmed": True, "pin_worse": True, "acknowledge_unknown": True},
        ),
        ("POST", f"{_ONE}/fork", "fork", {"confirmed": True, "name": "Returns"}),
        (
            "POST",
            f"{_ONE}/continue",
            "continue_run",
            {
                "confirmed": True,
                "estimate_usd": "0.01",
                "candidate_hash": _HASH,
                "budget_usd": "5",
                "mode": "thorough",
            },
        ),
        ("POST", f"{_ONE}/retry", "retry", None),
        ("POST", f"{_ONE}/cancel", "cancel", None),
        ("POST", f"{_ONE}/discard", "discard", {"confirmed": True}),
    ],
)
async def test_each_route_reaches_its_service_call_with_the_caller_and_the_path(
    client: AsyncClient,
    mock_db_session: MagicMock,
    method: str,
    path: str,
    operation: str,
    body: dict[str, object] | None,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.VIEWER)
    service = SkillImprovementService(mock_db_session)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_skill_improvement_service] = lambda: service
    refusal = AsyncMock(side_effect=NotFoundError(message="Session unavailable"))
    with patch.object(service, operation, refusal):
        response = await client.request(method, f"{settings.API_V1_STR}{path}", json=body)

    assert response.status_code == 404, response.text
    call = refusal.await_args
    assert call is not None and call.args[:2] == (ctx, _SKILL)
    if path.startswith(_ONE):
        assert call.args[2] == _RUN
    if f"/changes/{_HUNK}" in path:
        assert call.args[3] == _HUNK
    if body is not None:
        payload = call.args[-1]
        assert isinstance(payload, BaseModel)
        supplied = payload.model_dump(mode="json", include=set(body))
        for key, value in body.items():
            assert supplied[key] == value


async def test_a_list_reads_its_line_and_page_from_the_query(
    client: AsyncClient, mock_db_session: MagicMock
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    service = SkillImprovementService(mock_db_session)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_skill_improvement_service] = lambda: service
    with patch.object(service, "list_for_skill", AsyncMock(return_value=[])) as listed:
        response = await client.get(
            f"{settings.API_V1_STR}{_ROOT}",
            params={"fork_id": str(_FORK), "main": "true", "skip": 5, "limit": 10},
        )
        attempt = await client.get(f"{settings.API_V1_STR}{_ONE}/changes", params={"attempt": 0})

    assert response.status_code == 200 and response.json() == []
    listed.assert_awaited_once_with(ctx, _SKILL, fork_id=_FORK, main_only=True, skip=5, limit=10)
    assert attempt.status_code == 422


async def test_waiting_for_you_lists_skill_sessions_for_a_reader_of_runs(
    client: AsyncClient, mock_db_session: MagicMock
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    service = SkillImprovementService(mock_db_session)
    app.dependency_overrides[deps.get_skill_improvement_service] = lambda: service
    with patch.object(service, "awaiting", AsyncMock(return_value=[])) as awaiting:
        app.dependency_overrides[deps.get_auth_context] = lambda: ctx
        response = await client.get(f"{settings.API_V1_STR}/skill-improvements/awaiting")
        limited = AuthContext(
            user_id=uuid4(),
            organization_id=uuid4(),
            role=OrgRoleName.OWNER,
            key_scopes=frozenset({Perm.SKILLS_VIEW}),
        )
        app.dependency_overrides[deps.get_auth_context] = lambda: limited
        refused = await client.get(f"{settings.API_V1_STR}/skill-improvements/awaiting")

    assert response.status_code == 200 and response.json() == []
    awaiting.assert_awaited_once_with(ctx)
    assert refused.status_code == 403


def test_the_platforms_own_tools_reach_every_skill_session_route() -> None:
    from app.api.public_api import is_assistant_route
    from app.api.routes.v1 import skill_improvements

    routes = [*skill_improvements.router.routes, *skill_improvements.sessions.routes]

    assert len(routes) == 16
    assert all(is_assistant_route(route) for route in routes)
