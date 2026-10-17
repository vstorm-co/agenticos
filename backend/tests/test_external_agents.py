"""Registering remote A2A agents, delegating to them, and serving ours (#2092)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr, ValidationError

from app.agents.spec import AgentSpec, ExternalAgentRef
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import ApiKeySecret, SecretKind
from app.schemas.a2a import AgentCard
from app.schemas.external_agent import ExternalAgentCreate
from app.services import external_agent as module
from app.services.a2a_client import A2AClientError
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.external_agent import ExternalAgentService

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()
CTX = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role="admin")
CARD = AgentCard(
    name="Contract Reviewer",
    description="Reads contracts.",
    url="https://agents.example.com/a2a/reviewer",
    skills=[{"id": "review", "name": "Review", "description": "Review a contract"}],
)


def _row(**overrides: Any) -> MagicMock:
    row = MagicMock(
        id=uuid.uuid4(),
        organization_id=ORG,
        slug="contract-reviewer",
        description="Reads contracts.",
        card_url="https://agents.example.com",
        endpoint_url=CARD.url,
        card=CARD.model_dump(by_alias=True, mode="json"),
        secret_id=None,
        created_at=datetime(2026, 10, 17, tzinfo=UTC),
        updated_at=None,
    )
    row.name = "Contract Reviewer"
    for field, value in overrides.items():
        setattr(row, field, value)
    return row


class TestRegistering:
    async def test_a_card_is_read_and_kept_under_a_handle_from_its_name(self) -> None:
        created = _row()
        with (
            patch.object(module, "fetch_card", AsyncMock(return_value=CARD)),
            patch.object(module.external_agent_repo, "get_by_slug", AsyncMock(return_value=None)),
            patch.object(
                module.external_agent_repo, "create", AsyncMock(return_value=created)
            ) as create,
            patch.object(module, "record_audit", AsyncMock()) as audited,
        ):
            read = await ExternalAgentService(MagicMock()).register(
                CTX, ExternalAgentCreate(card_url="https://agents.example.com")
            )

        fields = create.await_args.kwargs
        assert fields["slug"] == "contract-reviewer"
        assert fields["endpoint_url"] == CARD.url
        assert fields["organization_id"] == ORG
        assert read.skills[0].name == "Review"
        assert audited.await_args.kwargs["details"] == {"endpoint_host": "agents.example.com"}

    async def test_a_card_that_cannot_be_read_is_a_refusal_saying_why(self) -> None:
        with (
            patch.object(module, "fetch_card", AsyncMock(side_effect=A2AClientError("HTTP 404"))),
            pytest.raises(BadRequestError, match="HTTP 404"),
        ):
            await ExternalAgentService(MagicMock()).register(
                CTX, ExternalAgentCreate(card_url="https://agents.example.com")
            )

    async def test_a_taken_handle_is_refused(self) -> None:
        with (
            patch.object(module, "fetch_card", AsyncMock(return_value=CARD)),
            patch.object(module.external_agent_repo, "get_by_slug", AsyncMock(return_value=_row())),
            pytest.raises(AlreadyExistsError),
        ):
            await ExternalAgentService(MagicMock()).register(
                CTX, ExternalAgentCreate(card_url="https://agents.example.com")
            )

    @pytest.mark.security
    async def test_a_secret_must_be_an_api_key_the_caller_may_see(self) -> None:
        secrets = MagicMock(
            get_usable=AsyncMock(side_effect=NotFoundError(message="Secret not found"))
        )
        with (
            patch.object(module, "fetch_card", AsyncMock(return_value=CARD)),
            patch.object(module.external_agent_repo, "get_by_slug", AsyncMock(return_value=None)),
            patch.object(module, "OrganizationSecretService", return_value=secrets),
            patch.object(module.external_agent_repo, "create", AsyncMock()) as create,
            pytest.raises(NotFoundError),
        ):
            await ExternalAgentService(MagicMock()).register(
                CTX,
                ExternalAgentCreate(card_url="https://agents.example.com", secret_id=uuid.uuid4()),
            )
        assert secrets.get_usable.await_args.kwargs == {"kind": SecretKind.API_KEY}
        create.assert_not_awaited()

    async def test_the_list_refresh_and_removal(self) -> None:
        row = _row()
        refreshed = _row(description="Now also NDAs.")
        with (
            patch.object(module.external_agent_repo, "list_for_org", AsyncMock(return_value=[row])),
            patch.object(module.external_agent_repo, "get", AsyncMock(return_value=row)),
            patch.object(module, "fetch_card", AsyncMock(return_value=CARD)),
            patch.object(module.external_agent_repo, "update", AsyncMock(return_value=refreshed)),
            patch.object(module.external_agent_repo, "delete", AsyncMock()) as deleted,
            patch.object(module, "record_audit", AsyncMock()),
        ):
            service = ExternalAgentService(MagicMock())
            assert [item.slug for item in (await service.list(CTX)).items] == ["contract-reviewer"]
            assert (await service.refresh(CTX, row.id)).description == "Now also NDAs."
            await service.delete(CTX, row.id)
        deleted.assert_awaited_once()

    @pytest.mark.security
    async def test_another_organizations_registration_is_not_found(self) -> None:
        with (
            patch.object(module.external_agent_repo, "get", AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await ExternalAgentService(MagicMock()).delete(CTX, uuid.uuid4())


class TestDelegatingToOne:
    def test_the_same_remote_agent_cannot_be_named_twice(self) -> None:
        ref = {"external_agent_id": str(uuid.uuid4())}
        with pytest.raises(ValidationError, match="more than once"):
            AgentSpec.model_validate(
                {"name": "x", "model_profile_id": str(uuid.uuid4()), "external_agents": [ref, ref]}
            )

    async def test_publish_names_an_unregistered_remote_agent_and_returns_handles(self) -> None:
        known, unknown = uuid.uuid4(), uuid.uuid4()
        spec = MagicMock(
            external_agents=[
                ExternalAgentRef(external_agent_id=known),
                ExternalAgentRef(external_agent_id=unknown),
            ]
        )
        service = AgentRegistryService(MagicMock())
        with patch(
            "app.services.agent_registry.external_agent_repo.get_many",
            AsyncMock(return_value={known: _row(slug="reviewer")}),
        ):
            problems, handles = await service._external_agent_problems(CTX, spec)

        assert problems == [f"Remote agent {unknown} is not registered in this organization."]
        assert handles == ["reviewer"]

    async def test_the_run_builds_one_delegate_per_remote_agent_with_its_key(self) -> None:
        secret_id = uuid.uuid4()
        row = _row(secret_id=secret_id, slug="reviewer")
        runner = AgentRunnerService(MagicMock())
        runner.secrets = MagicMock(
            resolve_for_bindings=AsyncMock(
                return_value={secret_id: ApiKeySecret(api_key=SecretStr("remote-key"))}
            )
        )
        delegation = MagicMock(ctx=CTX)
        with (
            patch(
                "app.services.agent_runner.external_agent_repo.get_many",
                AsyncMock(return_value={row.id: row}),
            ),
            patch("app.services.agent_runner.a2a_delegate") as builder,
        ):
            (resolved,) = await runner._resolve_external(
                delegation, [ExternalAgentRef(external_agent_id=row.id, preferred_mode="async")]
            )

        assert resolved.name == "reviewer"
        assert resolved.preferred_mode == "async"
        assert builder.call_args.kwargs == {
            "handle": "reviewer",
            "endpoint": CARD.url,
            "bearer": "remote-key",
        }

    async def test_a_registration_removed_since_publish_fails_the_run(self) -> None:
        runner = AgentRunnerService(MagicMock())
        with (
            patch(
                "app.services.agent_runner.external_agent_repo.get_many",
                AsyncMock(return_value={}),
            ),
            pytest.raises(BadRequestError, match="no longer registered"),
        ):
            await runner._resolve_external(
                MagicMock(ctx=CTX), [ExternalAgentRef(external_agent_id=uuid.uuid4())]
            )


class TestServingOurs:
    async def test_serving_takes_publish_and_a_published_version(self) -> None:
        service = AgentRegistryService(MagicMock())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=None)
        service.get = AsyncMock(return_value=agent)
        with pytest.raises(BadRequestError, match="Publish the agent"):
            await service.set_a2a(CTX, agent.id, enabled=True)
        assert service.get.await_args.kwargs == {"perm": Perm.AGENTS_PUBLISH}

    @pytest.mark.parametrize(
        ("enabled", "action"), [(True, "agent.a2a_served"), (False, "agent.a2a_withdrawn")]
    )
    async def test_switching_it_is_recorded(self, enabled: bool, action: str) -> None:
        service = AgentRegistryService(MagicMock())
        agent = MagicMock(id=uuid.uuid4(), current_version_id=uuid.uuid4())
        service.get = AsyncMock(return_value=agent)
        with (
            patch(
                "app.services.agent_registry.agent_repo.update", AsyncMock(return_value=agent)
            ) as update,
            patch("app.services.agent_registry.record_audit", AsyncMock()) as audited,
        ):
            await service.set_a2a(CTX, agent.id, enabled=enabled)
        assert update.await_args.kwargs["update_data"] == {"a2a_enabled": enabled}
        assert audited.await_args.kwargs["action"] == action


@pytest.mark.security
@pytest.mark.parametrize(("kind", "found"), [("api_key", True), ("oauth_app", False)])
async def test_only_a_secret_of_the_asked_kind_is_usable(kind: str, found: bool) -> None:
    from app.services.organization_secret import OrganizationSecretService

    service = OrganizationSecretService(MagicMock())
    secret = MagicMock(kind=kind)
    service._get = AsyncMock(return_value=secret)
    if found:
        assert await service.get_usable(CTX, uuid.uuid4(), kind=SecretKind.API_KEY) is secret
    else:
        with pytest.raises(NotFoundError):
            await service.get_usable(CTX, uuid.uuid4(), kind=SecretKind.API_KEY)


def test_the_registry_is_part_of_the_public_api() -> None:
    """An organization key may register what its agents delegate to, as the docs say."""
    from app.api.public_api import is_public_route
    from app.api.routes.v1.external_agents import router

    assert all(is_public_route(route) for route in router.routes)
