"""Registering remote A2A agents, delegating to them, and serving ours (#2092)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr, ValidationError

from app.agents.spec import AgentSpec, ExternalAgentRef
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
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

    @pytest.mark.security
    async def test_a_card_that_cannot_be_read_is_refused_without_repeating_its_address(
        self,
    ) -> None:
        """A signed card URL carries its credential; `details` is logged."""
        signed = "https://agents.example.com/card.json?sig=s3cr3t"
        with (
            patch.object(module, "fetch_card", AsyncMock(side_effect=A2AClientError("HTTP 404"))),
            pytest.raises(BadRequestError, match="HTTP 404") as refused,
        ):
            await ExternalAgentService(MagicMock()).register(
                CTX, ExternalAgentCreate(card_url=signed)
            )
        assert "s3cr3t" not in str(refused.value.details)
        assert refused.value.details["fields"][0]["field"] == "card_url"

    async def test_a_stored_card_that_cannot_be_read_again_names_no_field(self) -> None:
        row = _row(card_url="https://agents.example.com/card.json?sig=s3cr3t")
        with (
            patch.object(module.external_agent_repo, "get", AsyncMock(return_value=row)),
            patch.object(module, "fetch_card", AsyncMock(side_effect=A2AClientError("HTTP 404"))),
            pytest.raises(BadRequestError, match="HTTP 404") as refused,
        ):
            await ExternalAgentService(MagicMock()).refresh(CTX, row.id)
        assert not refused.value.details

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

    @pytest.mark.security
    async def test_a_key_is_never_bound_to_a_plain_http_endpoint(self) -> None:
        """Anyone on the path - a proxy included - would read it off the header."""
        cleartext = CARD.model_copy(update={"url": "http://agents.example.com/a2a"})
        secrets = MagicMock(get_usable=AsyncMock())
        with (
            patch.object(module, "fetch_card", AsyncMock(return_value=cleartext)),
            patch.object(module.external_agent_repo, "get_by_slug", AsyncMock(return_value=None)),
            patch.object(module, "OrganizationSecretService", return_value=secrets),
            patch.object(module.external_agent_repo, "create", AsyncMock()) as create,
            pytest.raises(BadRequestError) as refused,
        ):
            await ExternalAgentService(MagicMock()).register(
                CTX,
                ExternalAgentCreate(card_url="https://agents.example.com", secret_id=uuid.uuid4()),
            )
        assert refused.value.details["fields"][0]["field"] == "card_url"
        create.assert_not_awaited()

        # Nor moved there by a refresh, named by no field - nobody typed it.
        row = _row(secret_id=uuid.uuid4(), created_by_user_id=CTX.user_id)
        with (
            patch.object(module.external_agent_repo, "get", AsyncMock(return_value=row)),
            patch.object(module, "OrganizationSecretService", return_value=secrets),
            patch.object(module, "fetch_card", AsyncMock(return_value=cleartext)),
            patch.object(module.external_agent_repo, "update", AsyncMock()) as update,
            pytest.raises(BadRequestError) as moved,
        ):
            await ExternalAgentService(MagicMock()).refresh(CTX, row.id)
        assert moved.value.details == {"endpoint_host": "agents.example.com"}
        update.assert_not_awaited()

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
    async def test_a_member_changes_only_their_own_registration(self) -> None:
        """Every agent delegating to a registration depends on it, so a member who
        edits only their own agents cannot remove or repoint somebody else's."""
        member = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role="member")
        theirs = _row(created_by_user_id=uuid.uuid4())
        mine = _row(created_by_user_id=member.user_id)
        with (
            patch.object(module.external_agent_repo, "get", AsyncMock(side_effect=[theirs, mine])),
            patch.object(module.external_agent_repo, "delete", AsyncMock()) as deleted,
            patch.object(module, "record_audit", AsyncMock()),
        ):
            service = ExternalAgentService(MagicMock())
            with pytest.raises(AuthorizationError):
                await service.delete(member, theirs.id)
            await service.delete(member, mine.id)
        deleted.assert_awaited_once_with(ANY, mine)

    async def test_a_card_says_only_so_much_about_itself(self) -> None:
        """Its description is a tool description every delegating agent reads."""
        long = CARD.model_copy(update={"description": "x" * 5000})
        row = _row()
        with (
            patch.object(module.external_agent_repo, "get", AsyncMock(return_value=row)),
            patch.object(module, "fetch_card", AsyncMock(return_value=long)),
            patch.object(module.external_agent_repo, "update", AsyncMock(return_value=row)) as up,
        ):
            await ExternalAgentService(MagicMock()).refresh(CTX, row.id)
        stored = up.await_args.kwargs["update_data"]["description"]
        assert len(stored) == module.MAX_DESCRIPTION_CHARS

    async def test_the_list_says_which_registrations_the_caller_may_change(self) -> None:
        """A member is offered Refresh and Remove only on their own: on the
        others the button would be refused."""
        member = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role="member")
        theirs = _row(slug="theirs", created_by_user_id=uuid.uuid4())
        mine = _row(slug="mine", created_by_user_id=member.user_id)
        with patch.object(
            module.external_agent_repo, "list_for_org", AsyncMock(return_value=[theirs, mine])
        ):
            service = ExternalAgentService(MagicMock())
            as_member = (await service.list(member)).items
            as_admin = (await service.list(CTX)).items
        assert [(item.slug, item.can_manage) for item in as_member] == [
            ("theirs", False),
            ("mine", True),
        ]
        assert all(item.can_manage for item in as_admin)

    async def test_a_card_that_moves_the_agent_to_another_host_is_audited(self) -> None:
        moved = CARD.model_copy(update={"url": "https://elsewhere.example.net/a2a"})
        row = _row()
        with (
            patch.object(module.external_agent_repo, "get", AsyncMock(return_value=row)),
            patch.object(module, "fetch_card", AsyncMock(side_effect=[CARD, moved])),
            patch.object(module.external_agent_repo, "update", AsyncMock(return_value=row)),
            patch.object(module, "record_audit", AsyncMock()) as audited,
        ):
            service = ExternalAgentService(MagicMock())
            await service.refresh(CTX, row.id)
            audited.assert_not_awaited()
            await service.refresh(CTX, row.id)

        assert audited.await_args.kwargs["action"] == "external_agent.moved"
        assert audited.await_args.kwargs["details"] == {
            "from_host": "agents.example.com",
            "endpoint_host": "elsewhere.example.net",
        }

    @pytest.mark.security
    def test_an_address_carrying_a_password_is_refused_before_it_is_stored(self) -> None:
        """Stored as configuration and read by whoever reads the table; a key is
        the vault's."""
        with pytest.raises(ValidationError, match="user name or password"):
            ExternalAgentCreate(card_url="https://bot:pw@agents.example.com")
        with pytest.raises(ValidationError, match="user name or password"):
            AgentCard(name="x", url="https://bot:pw@agents.example.com/a2a")

    @pytest.mark.security
    async def test_a_listed_address_keeps_no_credential(self) -> None:
        signed = _row(
            card_url="https://bot:pw@agents.example.com:8443/card.json?sig=s3cret",
            endpoint_url="https://bot:pw@agents.example.com/a2a?token=s3cret",
        )
        listed = module.read(signed, can_manage=False)
        assert listed.card_url == "https://agents.example.com:8443/card.json"
        assert listed.endpoint_url == "https://agents.example.com/a2a"

    @pytest.mark.security
    async def test_a_refresh_needs_the_key_it_will_send_on(self) -> None:
        """A refresh decides where the bound key goes next, so a registrant whose
        access to the key was revoked cannot repoint it at a host of their own."""
        row = _row(secret_id=uuid.uuid4(), created_by_user_id=CTX.user_id)
        refused = AsyncMock(side_effect=NotFoundError(message="Secret not found"))
        fetched = AsyncMock(return_value=CARD)
        with (
            patch.object(module.external_agent_repo, "get", AsyncMock(return_value=row)),
            patch.object(module.OrganizationSecretService, "get_usable", refused),
            patch.object(module, "fetch_card", fetched),
            pytest.raises(NotFoundError),
        ):
            await ExternalAgentService(MagicMock()).refresh(CTX, row.id)
        fetched.assert_not_awaited()

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

    @pytest.mark.security
    @pytest.mark.parametrize(("secret", "visible"), [(None, False), (MagicMock(), False)])
    async def test_publish_refuses_a_remote_agent_whose_key_the_publisher_cannot_use(
        self, secret: object, visible: bool
    ) -> None:
        """Its key is lent to every run, so the publisher must reach it - as a
        capability's key - whoever registered it."""
        ref = ExternalAgentRef(external_agent_id=uuid.uuid4())
        service = AgentRegistryService(MagicMock())
        with (
            patch(
                "app.services.agent_registry.external_agent_repo.get_many",
                AsyncMock(
                    return_value={
                        ref.external_agent_id: _row(slug="reviewer", secret_id=uuid.uuid4())
                    }
                ),
            ),
            patch(
                "app.services.agent_registry.organization_secret_repo.get",
                AsyncMock(return_value=secret),
            ),
            patch("app.services.agent_registry.resolve_access", AsyncMock(return_value=visible)),
        ):
            problems, handles = await service._external_agent_problems(
                CTX, MagicMock(external_agents=[ref])
            )

        assert problems == [
            "Remote agent 'reviewer' sends a key you cannot use; ask whoever registered it "
            "to share the key, or register it with your own."
        ]
        assert handles == ["reviewer"]

    async def test_publish_takes_a_remote_agent_whose_key_the_publisher_may_use(self) -> None:
        ref = ExternalAgentRef(external_agent_id=uuid.uuid4())
        service = AgentRegistryService(MagicMock())
        with (
            patch(
                "app.services.agent_registry.external_agent_repo.get_many",
                AsyncMock(
                    return_value={
                        ref.external_agent_id: _row(slug="reviewer", secret_id=uuid.uuid4())
                    }
                ),
            ),
            patch(
                "app.services.agent_registry.organization_secret_repo.get",
                AsyncMock(return_value=MagicMock()),
            ),
            patch("app.services.agent_registry.resolve_access", AsyncMock(return_value=True)),
        ):
            problems, _ = await service._external_agent_problems(
                CTX, MagicMock(external_agents=[ref])
            )

        assert problems == []

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

    async def test_the_remote_agents_join_the_delegates_the_tree_resolves(self) -> None:
        ref = ExternalAgentRef(external_agent_id=uuid.uuid4())
        remote = SimpleNamespace(name="reviewer")
        runner = AgentRunnerService(MagicMock())
        runner._resolve_external = AsyncMock(return_value=[remote])
        delegation = MagicMock(ctx=CTX)

        resolved = await runner._resolve_delegates(
            delegation,
            spec=MagicMock(capabilities=[], subagents=[], external_agents=[ref]),
            config=MagicMock(share_with_delegates=[], inline=[]),
            resources={},
            depth_remaining=1,
            depth=0,
            ancestors=frozenset(),
        )

        assert resolved == [remote]
        runner._resolve_external.assert_awaited_once_with(delegation, [ref])

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
