"""Skill session routes pass the caller, the skill and the session to the service, and its
refusals back."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import BaseModel

from app.api import deps
from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.skill_improvement import SkillImprovementPurpose
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
        ("POST", f"{_ONE}/recheck/estimate", "estimate_recheck", None),
        (
            "POST",
            f"{_ONE}/recheck",
            "recheck",
            {
                "confirmed": True,
                "estimate_usd": "0.30",
                "candidate_hash": _HASH,
                "budget_usd": "5",
            },
        ),
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
        ("POST", f"{_ONE}/return-to-main", "return_to_main", {"confirmed": True}),
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


@pytest.mark.parametrize(
    ("path", "operation", "purpose", "body"),
    [
        ("catch-up/estimate", "estimate_merge", SkillImprovementPurpose.CATCH_UP, None),
        ("catch-up", "start_merge", SkillImprovementPurpose.CATCH_UP, {"budget_usd": "0"}),
        ("to-main/estimate", "estimate_merge", SkillImprovementPurpose.TO_MAIN, None),
        ("to-main", "start_merge", SkillImprovementPurpose.TO_MAIN, {"budget_usd": "1"}),
    ],
)
async def test_a_merge_route_names_its_fork_and_its_purpose(
    client: AsyncClient,
    mock_db_session: MagicMock,
    path: str,
    operation: str,
    purpose: SkillImprovementPurpose,
    body: dict[str, object] | None,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    service = SkillImprovementService(mock_db_session)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_skill_improvement_service] = lambda: service
    refusal = AsyncMock(side_effect=ConcurrentChangeError(message="Nothing to merge"))
    with patch.object(service, operation, refusal):
        response = await client.post(
            f"{settings.API_V1_STR}/skills/{_SKILL}/forks/{_FORK}/{path}", json=body
        )

    assert response.status_code == 409, response.text
    call = refusal.await_args
    assert call is not None and call.args[:4] == (ctx, _SKILL, _FORK, purpose)
    if body is not None:
        assert call.args[4].model_dump(mode="json")["budget_usd"] == body["budget_usd"]


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

    routes = [
        *skill_improvements.router.routes,
        *skill_improvements.sessions.routes,
        *skill_improvements.merges.routes,
    ]

    assert len(routes) == 27
    assert all(is_assistant_route(route) for route in routes)


def test_an_organization_key_is_refused_every_merge_route() -> None:
    from app.api.public_api import is_assistant_route, is_public_route
    from app.api.routes.v1 import skill_improvements, skills

    merge = [
        route
        for route in [*skills.router.routes, *skill_improvements.router.routes]
        if "/improvements/{run_id}/merge" in getattr(route, "path", "")
    ]

    assert len(merge) == 4
    assert not any(is_public_route(route) for route in merge)
    assert all(is_assistant_route(route) for route in merge)


@pytest.mark.parametrize(
    ("refusal", "code"),
    [
        (BadRequestError(message="Only a result is checked again"), 400),
        (PaymentRequiredError(message="The spending limit does not cover this check"), 402),
        (ConcurrentChangeError(message="The check's price changed since it was quoted"), 409),
    ],
)
async def test_check_again_answers_each_refusal_with_its_status(
    client: AsyncClient, mock_db_session: MagicMock, refusal: Exception, code: int
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    service = SkillImprovementService(mock_db_session)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_skill_improvement_service] = lambda: service
    body = {"confirmed": True, "estimate_usd": "0.3", "candidate_hash": _HASH, "budget_usd": "5"}
    with patch.object(service, "recheck", AsyncMock(side_effect=refusal)):
        response = await client.post(f"{settings.API_V1_STR}{_ONE}/recheck", json=body)

    assert response.status_code == code


@pytest.mark.parametrize("confirmed", [None, False])
@pytest.mark.parametrize("path", ["apply", "fork"])
async def test_a_decision_without_confirmation_is_refused_before_the_service(
    client: AsyncClient, mock_db_session: MagicMock, path: str, confirmed: bool | None
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    service = SkillImprovementService(mock_db_session)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_skill_improvement_service] = lambda: service
    body: dict[str, object] = {"name": "Returns"}
    if confirmed is not None:
        body["confirmed"] = confirmed
    with patch.object(service, path, AsyncMock()) as decided:
        response = await client.post(f"{settings.API_V1_STR}{_ONE}/{path}", json=body)

    assert response.status_code == 422
    decided.assert_not_awaited()
