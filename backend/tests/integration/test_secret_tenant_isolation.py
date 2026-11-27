"""A github_oauth_app secret is bound to the organization that sealed it.

The vault's whole promise is that a ciphertext cannot be moved between owners:
even with the row in hand, org B cannot open a secret org A sealed. A mock
cannot prove that - it would only prove the repository's `WHERE` clause holds.
So this stores a real GitHub OAuth App credential through the service, opens it
for its own organization, and then takes the raw envelope and shows it fails to
unseal under a second organization's scope.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, GithubOAuthAppSecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import organization_secret as organization_secret_repo
from app.schemas.model_profile import ModelProfileUpdate
from app.schemas.token_pricing import TokenPricing
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService
from app.services.speech_to_text_settings import SpeechToTextSettingsService

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _member(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _org(db, *, name: str) -> tuple[Organization, User]:
    founder = await _member(db)
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization, founder


def _ctx(organization: Organization, owner: User) -> AuthContext:
    return AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)


async def test_rotating_a_custom_priced_model_key_requires_budget_authority(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    org, owner = await _org(db, name="Priced")
    other_org, _ = await _org(db, name="Other")
    builder = await _member(db)
    admin_ctx = _ctx(org, owner)
    builder_ctx = AuthContext(user_id=builder.id, organization_id=org.id, role=OrgRoleName.BUILDER)
    other_ctx = AuthContext(
        user_id=builder.id, organization_id=other_org.id, role=OrgRoleName.BUILDER
    )
    vault = OrganizationSecretService(db)
    key = await vault.create(
        builder_ctx,
        name="Builder key",
        purpose="openai",
        value=ApiKeySecret(api_key="sk-test-original"),
        visibility=Visibility.PRIVATE,
    )
    next_value = ApiKeySecret(api_key="sk-test-next-1234")
    monkeypatch.setattr(
        "app.services.model_profile.models_for", AsyncMock(return_value=([], "curated"))
    )
    models = ModelProfileService(db)
    automatic = await models.create_profile(
        admin_ctx, label="Automatic", provider="openai", model="gpt-5", secret_id=key.id
    )
    await vault.update(builder_ctx, key.id, value=next_value)
    generation = key.authorization_generation

    zero_rates = TokenPricing(input=Decimal("0"), output=Decimal("0"))
    priced = await models.create_profile(
        admin_ctx,
        label="Priced",
        provider="openai",
        model="gpt-5",
        secret_id=key.id,
        custom_pricing=zero_rates,
    )
    (entry,) = await vault.list_secrets(builder_ctx)
    assert entry.can_edit and not entry.can_rotate
    (entry,) = await vault.list_secrets(admin_ctx)
    assert entry.can_rotate
    with pytest.raises(NotFoundError):
        await vault.update(other_ctx, key.id, value=next_value)
    with pytest.raises(AuthorizationError, match="budgets:manage"):
        await vault.update(builder_ctx, key.id, value=ApiKeySecret(api_key="sk-test-refused"))
    assert key.authorization_generation == generation
    assert key.hint == "1234"
    assert (
        await vault.update(builder_ctx, key.id, description="Current provider key")
    ).description == ("Current provider key")
    rotated = await vault.update(
        admin_ctx, key.id, value=ApiKeySecret(api_key="sk-test-admin-5678")
    )
    assert rotated.hint == "5678"
    assert rotated.authorization_generation != generation

    await models.update_profile(
        admin_ctx, automatic.id, ModelProfileUpdate(custom_pricing=zero_rates)
    )
    await models.update_profile(admin_ctx, priced.id, ModelProfileUpdate(custom_pricing=None))
    with pytest.raises(AuthorizationError, match="budgets:manage"):
        await vault.update(builder_ctx, key.id, value=next_value)
    await models.update_profile(admin_ctx, automatic.id, ModelProfileUpdate(custom_pricing=None))
    (entry,) = await vault.list_secrets(builder_ctx)
    assert entry.can_rotate
    assert (await vault.update(builder_ctx, key.id, value=next_value)).hint == "1234"


class TestAGithubOAuthAppSecretIsBoundToItsOrganization:
    async def test_its_own_organization_opens_both_halves(self, db) -> None:
        organization, owner = await _org(db, name="Acme")
        ctx = _ctx(organization, owner)

        stored = await OrganizationSecretService(db).create(
            ctx,
            name="Acme GitHub app",
            value=GithubOAuthAppSecret(
                client_id="Iv1.0123456789abcdef", client_secret="ghs-live-4242"
            ),
            purpose="github_oauth_app",
        )

        resolved = await OrganizationSecretService(db).resolve_for_bindings(ctx, [stored.id])

        opened = resolved[stored.id]
        assert isinstance(opened, GithubOAuthAppSecret)
        assert opened.client_id == "Iv1.0123456789abcdef"
        assert opened.client_secret.get_secret_value() == "ghs-live-4242"

    async def test_a_second_organization_cannot_unseal_the_row(self, db) -> None:
        """The tenant boundary the envelope exists to draw.

        The repository filters by organization, so the second organization never
        reaches the row through the service; this takes the stored envelope by
        hand and proves the crypto lock holds even then.
        """
        mine, mine_owner = await _org(db, name="Mine")
        theirs, _ = await _org(db, name="Theirs")
        ctx = _ctx(mine, mine_owner)

        stored = await OrganizationSecretService(db).create(
            ctx,
            name="Mine GitHub app",
            value=GithubOAuthAppSecret(
                client_id="Iv1.fedcba9876543210", client_secret="ghs-live-9999"
            ),
            purpose="github_oauth_app",
        )

        row = await organization_secret_repo.get(db, stored.id, organization_id=mine.id)
        assert row is not None
        # The locked read for a compare-and-swap draws the same boundary.
        locked = await organization_secret_repo.get_locked(db, stored.id, organization_id=mine.id)
        assert locked is row
        assert (
            await organization_secret_repo.get_locked(db, stored.id, organization_id=theirs.id)
            is None
        )

        with pytest.raises(BadRequestError, match="Failed to decrypt"):
            unseal_secret(
                row.sealed_secret,
                kind=SecretKind.GITHUB_OAUTH_APP,
                scope=VaultScope.organization(theirs.id),
                key_version=row.key_version,
            )


class TestGetByKindReadsTheOrgsSecretOfThatKind:
    async def test_it_finds_the_org_own_secret_and_none_for_another_org_or_kind(self, db) -> None:
        """The lookup the GitHub connect flow reaches the OAuth App credentials by.

        It is org-scoped, kind-scoped and visibility-scoped: the organization's
        own org-visible github_oauth_app row comes back, while another
        organization's identical kind, a kind this organization never stored, and
        a member's *private* row of the right kind are all absent - the last one
        because a private credential must never be silently spent for the whole
        organization's connection. A mock would only restate the query; this
        proves the `WHERE` against real rows.
        """
        mine, mine_owner = await _org(db, name="Kindful")
        theirs, _ = await _org(db, name="Otherkind")
        ctx = _ctx(mine, mine_owner)

        stored = await OrganizationSecretService(db).create(
            ctx,
            name="Kindful GitHub app",
            value=GithubOAuthAppSecret(
                client_id="Iv1.aaaabbbbccccdddd", client_secret="ghs-live-1111"
            ),
            purpose="github_oauth_app",
        )
        # A member's private OAuth App of the same kind, named to sort first: an
        # unfiltered lookup ordered by name would pick it over the org's own.
        await OrganizationSecretService(db).create(
            ctx,
            name="AAA private app",
            value=GithubOAuthAppSecret(client_id="Iv1.privateprivate", client_secret="ghs-priv"),
            purpose="github_oauth_app",
            visibility=Visibility.PRIVATE,
        )

        found = await organization_secret_repo.list_org_visible_by_kind(
            db, organization_id=mine.id, kind=SecretKind.GITHUB_OAUTH_APP.value
        )
        assert [row.id for row in found] == [stored.id]

        # Another organization does not see it - the org filter.
        assert (
            await organization_secret_repo.list_org_visible_by_kind(
                db, organization_id=theirs.id, kind=SecretKind.GITHUB_OAUTH_APP.value
            )
            == []
        )
        # Nor does a kind this organization has never stored - the kind filter.
        assert (
            await organization_secret_repo.list_org_visible_by_kind(
                db, organization_id=mine.id, kind=SecretKind.API_KEY.value
            )
            == []
        )


class TestATranscriptionKeyIsTheOrganizationsOwn:
    async def test_only_the_named_key_in_this_org_is_spent(self, db) -> None:
        """The key named next to a speech-to-text pair (#1797), against real rows.

        The named key opens and no other: another organization cannot spend it
        by naming its id, a key for another provider is not this one's, and a
        member's private key is never spent on everybody's behalf - only lent
        by an agent its owner published.
        """
        mine, mine_owner = await _org(db, name="Speakers")
        theirs, _ = await _org(db, name="Listeners")
        ctx = _ctx(mine, mine_owner)
        service = OrganizationSecretService(db)

        private = await service.create(
            ctx,
            name="AAA my own key",
            value=ApiKeySecret(api_key="sk-private-1111"),
            purpose="openai",
            visibility=Visibility.PRIVATE,
        )
        team = await service.create(
            ctx,
            name="Team OpenAI",
            value=ApiKeySecret(api_key="sk-team-2222"),
            purpose="openai",
        )

        assert (
            await service.transcription_key(mine.id, team.id, provider="openai", shared=True)
            == "sk-team-2222"
        )
        assert (
            await service.transcription_key(mine.id, team.id, provider="groq", shared=True) is None
        )
        assert (
            await service.transcription_key(theirs.id, team.id, provider="openai", shared=False)
            is None
        )
        assert (
            await service.transcription_key(mine.id, private.id, provider="openai", shared=True)
            is None
        )
        assert (
            await service.transcription_key(mine.id, private.id, provider="openai", shared=False)
            == "sk-private-1111"
        )

    async def test_a_level_may_only_name_a_key_it_is_allowed_to_spend(self, db) -> None:
        """`key_problem` against real rows: the check every speech-to-text level
        saves through. Another organization's key reads as missing; a member's
        private key is refused where the platform spends it for everybody, and
        allowed where its owner lends it to an agent; a key for another provider
        is not this provider's."""
        mine, mine_owner = await _org(db, name="Speakers")
        theirs, theirs_owner = await _org(db, name="Listeners")
        ctx = _ctx(mine, mine_owner)
        service = OrganizationSecretService(db)
        team = await service.create(
            ctx, name="Team OpenAI", value=ApiKeySecret(api_key="sk-team-2222"), purpose="openai"
        )
        private = await service.create(
            ctx,
            name="Mine",
            value=ApiKeySecret(api_key="sk-mine-1111"),
            purpose="openai",
            visibility=Visibility.PRIVATE,
        )
        foreign = await service.create(
            _ctx(theirs, theirs_owner),
            name="Theirs",
            value=ApiKeySecret(api_key="sk-theirs-3333"),
            purpose="openai",
        )
        settings = SpeechToTextSettingsService(db)

        async def problem(secret_id: uuid.UUID, *, provider: str = "openai", lent: bool = False):
            return await settings.key_problem(
                secret_id,
                organization_id=mine.id,
                provider=provider,
                ctx=ctx if lent else None,
            )

        assert await problem(team.id) is None
        assert await problem(foreign.id) == "That key is not in this organization's vault"
        assert (
            await problem(foreign.id, lent=True) == "That key is not in this organization's vault"
        )
        assert "organization-wide" in (await problem(private.id) or "")
        assert await problem(private.id, lent=True) is None
        assert "is a key for openai" in (await problem(team.id, provider="groq") or "")
