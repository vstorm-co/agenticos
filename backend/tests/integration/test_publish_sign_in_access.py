"""Who may put an agent on somebody's ChatGPT sign-in, against real rows (#2546).

A sign-in is one person's subscription. A run spends it only for somebody who
may see it in the vault, and publishing (or promoting) a version decides whose
runs those are - so the publisher is held to the same `secrets:view`, decided
by the real role scopes and the real grant table. A builder sees their own
secrets, organization-wide ones and those shared with them; an owner sees all.
"""

import uuid
from dataclasses import replace

import pytest

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.secret_kinds import SecretKind
from app.db.models.agent import Agent, AgentStatus
from app.db.models.credential import ModelProfile
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.user import User
from app.repositories import organization_secret_repo, resource_grant_repo
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import AgentRegistryService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class _Org:
    """An organization with an owner, two builders, and Ada's private ChatGPT sign-in.

    Ada is a builder too, so what lets her publish on the sign-in is that it is
    hers - not her role.
    """

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
        self.bob = await self._user()
        for user, role in (
            (self.owner, OrgRoleName.OWNER),
            (self.ada, OrgRoleName.BUILDER),
            (self.bob, OrgRoleName.BUILDER),
        ):
            db.add(
                OrganizationMember(
                    id=uuid.uuid4(), organization_id=self.org.id, user_id=user.id, role=role.value
                )
            )
        await db.flush()
        self.sign_in = await self._secret("Ada's ChatGPT", SecretKind.OPENAI_CODEX, self.ada)
        self.key = await self._secret("Team OpenAI", SecretKind.API_KEY, None)
        self.codex = await self._profile("Ada's Codex", "openai_codex", self.sign_in.id)
        self.gpt = await self._profile("GPT", "openai", self.key.id)
        self.gpt_to_codex = await self._profile(
            "GPT, then Codex", "openai", self.key.id, fallbacks=[self.codex]
        )
        self.agent = Agent(
            id=uuid.uuid4(),
            organization_id=self.org.id,
            owner_user_id=self.owner.id,
            visibility=Visibility.ORG.value,
            slug=f"helpdesk-{uuid.uuid4().hex[:6]}",
            name="Helpdesk",
            draft_spec={"name": "Helpdesk"},
            status=AgentStatus.DRAFT.value,
        )
        db.add(self.agent)
        await db.flush()
        return self

    def ctx(self, user: User, role: OrgRoleName = OrgRoleName.BUILDER) -> AuthContext:
        return AuthContext(user_id=user.id, organization_id=self.org.id, role=role)

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

    async def _secret(self, name: str, kind: SecretKind, owner: User | None):
        # The sealed value is never opened here: who may use a sign-in is a
        # question about the row, not about the tokens in it.
        return await organization_secret_repo.create(
            self.db,
            organization_id=self.org.id,
            name=name,
            description=None,
            kind=kind.value,
            purpose="openai_codex" if kind is SecretKind.OPENAI_CODEX else "openai",
            visibility=(Visibility.PRIVATE if owner else Visibility.ORG).value,
            owner_user_id=owner.id if owner else None,
            sealed_secret="sealed",
            hint="4242",
            key_version=1,
            created_by_user_id=owner.id if owner else self.owner.id,
        )

    async def _profile(
        self, label: str, provider: str, secret_id: uuid.UUID, *, fallbacks=()
    ) -> ModelProfile:
        profile = ModelProfile(
            organization_id=self.org.id,
            label=label,
            provider=provider,
            model="gpt-5.1-codex" if provider == "openai_codex" else "gpt-4o",
            secret_id=secret_id,
            fallback_profile_ids=[str(fallback.id) for fallback in fallbacks],
        )
        self.db.add(profile)
        await self.db.flush()
        return profile

    async def draft_on(self, profile: ModelProfile) -> None:
        self.agent.draft_spec = {"name": "Helpdesk", "model_profile_id": str(profile.id)}
        await self.db.flush()


def _spec_on(profile: ModelProfile) -> AgentSpec:
    return AgentSpec(name="Helpdesk", model_profile_id=profile.id)


def _fields(refusal: BadRequestError) -> list[str]:
    return [problem["field"] for problem in refusal.details.get("fields", [])]


class TestPublishing:
    async def test_a_builder_who_cannot_see_the_sign_in_is_refused(self, db) -> None:
        acme = await _Org().build(db)
        await acme.draft_on(acme.codex)

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).publish(acme.ctx(acme.bob), acme.agent.id)

        assert _fields(refused.value) == ["model_profile_id"]
        assert acme.agent.current_version_id is None

    async def test_the_sign_ins_owner_publishes_on_it(self, db) -> None:
        acme = await _Org().build(db)
        await acme.draft_on(acme.codex)

        version = await AgentRegistryService(db).publish(acme.ctx(acme.ada), acme.agent.id)

        assert version.spec["model_profile_id"] == str(acme.codex.id)

    async def test_an_owner_sees_every_secret_and_so_may_publish_on_it(self, db) -> None:
        """The same people the runtime lets spend it: `secrets:view` at `all`."""
        acme = await _Org().build(db)

        await AgentRegistryService(db).validate_spec(
            acme.ctx(acme.owner, OrgRoleName.OWNER), _spec_on(acme.codex)
        )

    async def test_a_member_it_was_shared_with_may_publish_on_it(self, db) -> None:
        acme = await _Org().build(db)
        registry = AgentRegistryService(db)
        with pytest.raises(BadRequestError):
            await registry.validate_spec(acme.ctx(acme.bob), _spec_on(acme.codex))

        await resource_grant_repo.upsert(
            db,
            organization_id=acme.org.id,
            subject_user_id=acme.bob.id,
            resource_type="secret",
            resource_id=acme.sign_in.id,
            level=GrantLevel.READ,
            created_by_user_id=acme.ada.id,
        )

        await registry.validate_spec(acme.ctx(acme.bob), _spec_on(acme.codex))

    async def test_a_fallback_on_the_sign_in_is_refused_too(self, db) -> None:
        acme = await _Org().build(db)

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).validate_spec(
                acme.ctx(acme.bob), _spec_on(acme.gpt_to_codex)
            )

        assert _fields(refused.value) == ["model_profile_id"]
        assert "falls back to 'Ada's Codex'" in refused.value.details["problems"][0]

    async def test_a_rollback_to_a_version_on_the_sign_in_is_refused(self, db) -> None:
        acme = await _Org().build(db)
        registry = AgentRegistryService(db)
        await acme.draft_on(acme.codex)
        on_codex = await registry.publish(acme.ctx(acme.ada), acme.agent.id)
        await acme.draft_on(acme.gpt)
        await registry.publish(acme.ctx(acme.bob), acme.agent.id)

        with pytest.raises(BadRequestError) as refused:
            await registry.rollback(acme.ctx(acme.bob), acme.agent.id, to_version_id=on_codex.id)

        assert _fields(refused.value) == ["model_profile_id"]


class TestPromotion:
    async def _two_versions(self, acme: _Org):
        """v1 on the team key, published by Bob; v2 on Ada's sign-in, published by Ada."""
        registry = AgentRegistryService(acme.db)
        await acme.draft_on(acme.gpt)
        v1 = await registry.publish(acme.ctx(acme.bob), acme.agent.id)
        await acme.draft_on(acme.codex)
        v2 = await registry.publish(acme.ctx(acme.ada), acme.agent.id)
        return v1, v2

    async def test_putting_a_version_on_the_sign_in_somewhere_is_judged_like_publishing(
        self, db
    ) -> None:
        acme = await _Org().build(db)
        v1, v2 = await self._two_versions(acme)
        environments = AgentEnvironmentService(db)

        with pytest.raises(BadRequestError) as refused:
            await environments.create(
                acme.ctx(acme.bob),
                acme.agent.id,
                EnvironmentCreate(name="staging", version_id=v2.id),
            )
        assert refused.value.details["version_id"] == v2.id

        staging = await environments.create(
            acme.ctx(acme.bob), acme.agent.id, EnvironmentCreate(name="staging", version_id=v1.id)
        )
        with pytest.raises(BadRequestError):
            await environments.update(
                acme.ctx(acme.bob), acme.agent.id, staging.id, EnvironmentUpdate(version_id=v2.id)
            )
        assert staging.version_id == v1.id

        promoted = await environments.update(
            acme.ctx(acme.ada), acme.agent.id, staging.id, EnvironmentUpdate(version_id=v2.id)
        )
        assert promoted.version_id == v2.id


class TestPinnedDelegates:
    """A run resolves a pinned delegate's model for its own caller, so pinning a
    version on Ada's sign-in reaches it for the owner's runs as surely as naming
    it would."""

    async def _research_on_codex(self, acme: _Org):
        """Ada's own delegate, published by her on her own sign-in."""
        research = Agent(
            id=uuid.uuid4(),
            organization_id=acme.org.id,
            owner_user_id=acme.ada.id,
            visibility=Visibility.ORG.value,
            slug=f"research-{uuid.uuid4().hex[:6]}",
            name="Research",
            draft_spec={"name": "Research", "model_profile_id": str(acme.codex.id)},
            status=AgentStatus.DRAFT.value,
        )
        acme.db.add(research)
        await acme.db.flush()
        version = await AgentRegistryService(acme.db).publish(acme.ctx(acme.ada), research.id)
        acme.agent.draft_spec = {
            "name": "Helpdesk",
            "model_profile_id": str(acme.gpt.id),
            "capabilities": [{"id": "subagents"}],
            "subagents": [{"agent_id": str(research.id), "agent_version_id": str(version.id)}],
        }
        await acme.db.flush()

    async def test_a_builder_who_cannot_see_the_delegates_sign_in_is_refused(self, db) -> None:
        acme = await _Org().build(db)
        await self._research_on_codex(acme)

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).publish(acme.ctx(acme.bob), acme.agent.id)

        assert _fields(refused.value) == ["subagents.0.agent_version_id"]
        assert refused.value.details["problems"][0].startswith(
            "Delegate 'Research': Model 'Ada's Codex'"
        )
        assert acme.agent.current_version_id is None

    async def test_the_sign_ins_owner_pins_it(self, db) -> None:
        acme = await _Org().build(db)
        await self._research_on_codex(acme)

        version = await AgentRegistryService(db).publish(acme.ctx(acme.ada), acme.agent.id)

        assert version.spec["subagents"]


class TestApiKeys:
    """A run under a key spends no sign-in, so a key may point an agent at none -
    even Ada's own key, carrying `secrets:view`, on Ada's own sign-in."""

    def _adas_key(self, acme: _Org) -> AuthContext:
        return replace(
            acme.ctx(acme.ada),
            api_key_id=uuid.uuid4(),
            key_scopes=frozenset(
                {Perm.AGENTS_VIEW, Perm.AGENTS_EDIT, Perm.AGENTS_PUBLISH, Perm.SECRETS_VIEW}
            ),
        )

    async def test_publishing_with_a_key_on_its_issuers_sign_in_is_refused(self, db) -> None:
        acme = await _Org().build(db)
        await acme.draft_on(acme.codex)

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).publish(self._adas_key(acme), acme.agent.id)

        assert _fields(refused.value) == ["model_profile_id"]
        assert "which an API key cannot use" in refused.value.details["problems"][0]
        assert acme.agent.current_version_id is None

    async def test_promoting_with_a_key_onto_its_issuers_sign_in_is_refused(self, db) -> None:
        acme = await _Org().build(db)
        await acme.draft_on(acme.codex)
        on_codex = await AgentRegistryService(db).publish(acme.ctx(acme.ada), acme.agent.id)

        with pytest.raises(BadRequestError) as refused:
            await AgentEnvironmentService(db).create(
                self._adas_key(acme),
                acme.agent.id,
                EnvironmentCreate(name="staging", version_id=on_codex.id),
            )

        assert refused.value.details["version_id"] == on_codex.id

    async def test_a_key_still_publishes_on_an_ordinary_key(self, db) -> None:
        acme = await _Org().build(db)
        await acme.draft_on(acme.gpt)

        version = await AgentRegistryService(db).publish(self._adas_key(acme), acme.agent.id)

        assert version.spec["model_profile_id"] == str(acme.gpt.id)
