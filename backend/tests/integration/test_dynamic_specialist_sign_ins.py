"""Which models a specialist the run's model invents may run on, against real rows.

An agent with `allow_dynamic` hands its model a catalog of the organization's
models. A ChatGPT sign-in in it is one person's subscription, which the run of
anybody who may see it - its owner, an owner, an admin - would then spend for an
agent whose author never chose it; and for anybody who may not, resolving it is
refused, which used to fail the whole run. Real secrets, sealed and unsealed, and
the real `secrets:view` decision.
"""

import uuid
from typing import Any
from unittest.mock import patch

import pytest

from app.agents.factory import build_agent
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.agents.subagent_runtime import SUBAGENT_RUNTIME_RESOURCE, SubagentRuntime
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, OpenAICodexSecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class _Org:
    """An owner, Ada (a builder) with her private ChatGPT sign-in, and an API key."""

    async def build(self, db) -> _Org:
        self.db = db
        self.owner = await self._user()
        self.org = Organization(
            id=uuid.uuid4(),
            name="Acme",
            slug=f"acme-{uuid.uuid4().hex[:8]}",
            created_by_user_id=self.owner.id,
        )
        db.add(self.org)
        await db.flush()
        self.ada = await self._user()
        for user, role in ((self.owner, OrgRoleName.OWNER), (self.ada, OrgRoleName.BUILDER)):
            db.add(
                OrganizationMember(
                    id=uuid.uuid4(), organization_id=self.org.id, user_id=user.id, role=role.value
                )
            )
        await db.flush()
        key = await self._secret(ApiKeySecret(api_key="sk-test-key"), purpose="openai", owner=None)
        sign_in = await self._secret(
            OpenAICodexSecret(
                access_token="access-token-1234",
                refresh_token="refresh-token-1234",
                account_id="acct",
            ),
            purpose="openai_codex",
            owner=self.ada,
        )
        self.gpt = await self._profile("GPT", "openai", key)
        self.codex = await self._profile("Ada's Codex", "openai_codex", sign_in)
        self.gpt_then_codex = await self._profile(
            "GPT, then Codex", "openai", key, fallbacks=[self.codex]
        )
        return self

    def ctx(self, user: User, role: OrgRoleName, **fields: Any) -> AuthContext:
        return AuthContext(user_id=user.id, organization_id=self.org.id, role=role, **fields)

    async def _user(self) -> User:
        user = User(
            id=uuid.uuid4(),
            email=f"{uuid.uuid4().hex}@example.com",
            hashed_password="x",
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()
        return user

    async def _secret(
        self, value: ApiKeySecret | OpenAICodexSecret, *, purpose: str, owner: User | None
    ) -> uuid.UUID:
        sealed = seal_secret(value, scope=VaultScope.organization(self.org.id))
        secret = OrganizationSecret(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            name=f"{purpose} {uuid.uuid4().hex[:6]}",
            purpose=purpose,
            visibility=(Visibility.PRIVATE if owner else Visibility.ORG).value,
            owner_user_id=owner.id if owner else None,
            kind=value.kind.value,
            sealed_secret=sealed.ciphertext,
            hint=sealed.hint,
        )
        self.db.add(secret)
        await self.db.flush()
        return secret.id

    async def _profile(
        self, label: str, provider: str, secret_id: uuid.UUID, *, fallbacks=()
    ) -> ModelProfile:
        profile = ModelProfile(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            label=label,
            provider=provider,
            model="gpt-5.1-codex" if provider == "openai_codex" else "gpt-4.1",
            secret_id=secret_id,
            fallback_profile_ids=[str(fallback.id) for fallback in fallbacks],
        )
        self.db.add(profile)
        await self.db.flush()
        return profile

    async def published(self, publisher: AuthContext, model: ModelProfile) -> uuid.UUID:
        """An agent on `model` that may invent specialists, published by `publisher`."""
        spec = AgentSpec(
            name="Desk",
            model_profile_id=model.id,
            capabilities=[CapabilityBindingSpec(id="subagents", config={"allow_dynamic": True})],
        )
        registry = AgentRegistryService(self.db)
        agent = await registry.create(publisher, spec)
        await registry.publish(publisher, agent.id)
        # Committed: whether somebody may spend a sign-in is read on a session of
        # its own (`VaultCodexCredentials.visible_to`), as production reads it.
        await self.db.commit()
        return agent.id


async def _catalog(db, ctx: AuthContext, agent_id: uuid.UUID) -> tuple[str, ...]:
    """Prepare a run of the agent and say which models its model may invent on."""
    with patch("app.services.agent_runner.build_agent", wraps=build_agent) as build:
        await AgentRunnerService(db).prepare(ctx, agent_id)
    runtime: SubagentRuntime = build.call_args_list[0].kwargs["resources"][
        SUBAGENT_RUNTIME_RESOURCE
    ]
    assert runtime.dynamic is not None
    return runtime.dynamic.allowed_models


async def test_an_api_key_run_is_not_failed_by_a_members_sign_in(db) -> None:
    """A key's holder may spend nobody's sign-in, so `resolve` refuses Ada's -
    which used to fail every API-key and widget run of an agent that names no
    sign-in at all."""
    org = await _Org().build(db)
    owner = org.ctx(org.owner, OrgRoleName.OWNER)
    agent_id = await org.published(owner, org.gpt)

    catalog = await _catalog(
        db, org.ctx(org.owner, OrgRoleName.OWNER, api_key_id=uuid.uuid4()), agent_id
    )

    assert catalog == ("GPT",)


async def test_an_owners_run_is_not_offered_a_sign_in_the_agent_does_not_name(db) -> None:
    """An owner may see Ada's sign-in, so `resolve` would hand it over: the
    catalog itself has to leave it out, and the profile that falls back to it."""
    org = await _Org().build(db)
    owner = org.ctx(org.owner, OrgRoleName.OWNER)
    agent_id = await org.published(owner, org.gpt)

    assert await _catalog(db, owner, agent_id) == ("GPT",)


async def test_the_sign_in_the_agent_runs_on_stays_in_its_catalog(db) -> None:
    """Ada published her agent on her own sign-in, so her run may invent on it."""
    org = await _Org().build(db)
    ada = org.ctx(org.ada, OrgRoleName.BUILDER)
    agent_id = await org.published(ada, org.codex)

    assert set(await _catalog(db, ada, agent_id)) == {"GPT", "Ada's Codex"}
