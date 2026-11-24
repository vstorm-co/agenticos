"""Imports call the normal creation boundaries with private, inactive settings."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.schemas.resource_bundle import BundleResourceKind
from app.services.portability.facade import PortabilityService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    "kind,method,payload",
    [
        ("agent", "AgentRegistryService.create", {"name": "Agent"}),
        ("context", "ContextService.create", {"name": "Policy", "content": "  Exact context\n"}),
        (
            "skill",
            "SkillService.create",
            {"name": "policy", "description": "Policy", "content": "Exact skill"},
        ),
        (
            "model_profile",
            "ModelProfileService.create_profile",
            {
                "label": "Model",
                "provider": "openai",
                "model": "gpt-4.1",
                "secret_id": str(uuid4()),
                "params": {"temperature": 0.2},
            },
        ),
        (
            "mcp_connection",
            "McpConnectionService.create_for_org",
            {
                "name": "notion",
                "url": "https://example.org/mcp",
                "allowed_tools": ["read"],
                "include_instructions": True,
                "trust_read_only_hints": True,
            },
        ),
    ],
)
async def test_create_is_private_and_does_not_publish_run_or_export_credentials(
    mock_db_session: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    method: str,
    payload: dict[str, object],
) -> None:
    identity = uuid4()
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    create = AsyncMock(return_value=SimpleNamespace(id=identity))
    monkeypatch.setattr(f"app.services.portability.facade.{method}", create)
    record = AsyncMock()
    monkeypatch.setattr("app.services.portability.facade.SkillVersionService.record_main", record)
    update = AsyncMock()
    monkeypatch.setattr(
        "app.services.portability.facade.McpConnectionService.update_for_org", update
    )
    assert (
        await PortabilityService(mock_db_session)._create(ctx, BundleResourceKind(kind), payload)
        == identity
    )
    assert create.await_args.args[0] == ctx
    if kind == "agent":
        assert create.await_args.kwargs["choose_model"] is False
        assert "visibility" not in create.await_args.kwargs
    elif kind == "context":
        assert create.await_args.kwargs["content"] == "  Exact context\n"
    elif kind == "mcp_connection":
        data = create.await_args.args[1]
        assert data.is_enabled is False
        assert data.visibility.value == "private"
        assert data.auth_token is None
        assert data.allowed_tools == ["read"]
        assert data.group_ids == [] and data.user_ids == []
        assert update.await_args.kwargs["data"].include_instructions is True
        assert update.await_args.kwargs["data"].trust_read_only_hints is True
    elif kind == "model_profile":
        assert create.await_args.kwargs["params"] == {"temperature": 0.2}
        assert "api_key" not in create.await_args.kwargs
    else:
        record.assert_awaited_once()


@pytest.mark.parametrize("kind,payload", [("agent", {"name": ""}), ("secret", {})])
async def test_invalid_or_unsupported_creations_are_explicit_refusals(
    mock_db_session: AsyncMock, kind: str, payload: dict[str, object]
) -> None:
    with pytest.raises(BadRequestError):
        await PortabilityService(mock_db_session)._create(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"),
            BundleResourceKind(kind),
            payload,
        )
