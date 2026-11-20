"""Global authority is explicit OAuth consent, separate from organization roles."""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.api.deps import require_deployment_mcp_scope
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.models.organization import Organization
from app.db.models.user import User
from app.schemas.oauth_server import OAuthConsentApprove
from app.services.api_key import KeyCaller
from app.services.approvals import ApprovalService
from app.services.assistant import AssistantService

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ID = UUID("00000000-0000-4000-8000-000000000001")
CTX = AuthContext(user_id=ID, organization_id=ID, role="owner")


def test_global_consent_is_a_separate_strict_boolean_not_an_org_permission() -> None:
    assert OAuthConsentApprove(scopes=[], deployment_admin=True).scopes == []
    for value in (
        {"scopes": []},
        {"scopes": ["deployment:admin"]},
        {"scopes": [], "deployment_admin": "true"},
    ):
        with pytest.raises(ValidationError):
            OAuthConsentApprove.model_validate(value)


@pytest.mark.parametrize(
    "surface,effective,live,allowed",
    [
        ("mcp", True, True, True),
        ("mcp", False, True, False),
        ("mcp", True, False, False),
        ("assistant", True, True, False),
        ("api_key", True, True, False),
    ],
)
async def test_global_scope_guard_requires_both_external_consent_and_live_app_authority(
    surface, effective, live, allowed
) -> None:
    user = User(id=ID, email="admin@example.com", is_active=True, is_app_admin=live)
    organization = Organization(id=ID, name="Team", slug="team", created_by_user_id=ID)
    caller = KeyCaller(
        user=user,
        organization=organization,
        context=replace(CTX, is_app_admin=effective),
        api_key_id=ID,
        prefix="aos_test",
        surface=surface,
    )
    request = Request({"type": "http", "method": "GET", "path": "/admin/settings", "headers": []})
    request.state.api_key_caller = caller
    if allowed:
        await require_deployment_mcp_scope(request, user)
    else:
        with pytest.raises(AuthorizationError):
            await require_deployment_mcp_scope(request, user)


async def test_scope_guard_retains_session_behavior_and_route_admin_checks() -> None:
    request = Request({"type": "http", "method": "GET", "path": "/admin/settings", "headers": []})
    await require_deployment_mcp_scope(
        request, User(id=ID, email="admin@example.com", is_app_admin=True)
    )


async def test_assistant_configuration_is_read_only_and_requires_org_settings() -> None:
    service = AssistantService(MagicMock())
    with patch(
        "app.services.assistant.organization_assistant_repo.get",
        new=AsyncMock(return_value=MagicMock(agent_id=ID, enabled=False, greeting="Welcome")),
    ) as read:
        result = await service.configuration(CTX)
        assert result.installed and result.enabled is False and result.agent_id == ID
        read.assert_awaited_once()
    with pytest.raises(AuthorizationError):
        await service.configuration(replace(CTX, role="viewer"))


@pytest.mark.parametrize("approved,app_admin", [(True, False), (True, True), (False, False)])
async def test_org_approvers_cannot_answer_global_changes_or_remember_them(
    approved: bool, app_admin: bool
) -> None:
    from app.db.models.agent_run import ToolApproval

    row = ToolApproval(
        id=ID,
        organization_id=ID,
        agent_id=ID,
        run_id=ID,
        tool_id="agenticos_change_deployment",
        tool_args={},
        status="pending",
        always_asks=True,
    )
    service = ApprovalService(MagicMock())
    with (
        patch(
            "app.services.approvals.agent_run_repo.get_approval", new=AsyncMock(return_value=row)
        ),
        patch(
            "app.services.approvals.voice_call_repo.is_live_run", new=AsyncMock(return_value=False)
        ),
        patch.object(service, "hidden_fields", new=AsyncMock(return_value=frozenset())),
    ):
        expected = AuthorizationError if approved and not app_admin else BadRequestError
        with pytest.raises(expected):
            await service.decide(
                replace(CTX, is_app_admin=app_admin), ID, approved=approved, remember_scope="agent"
            )
