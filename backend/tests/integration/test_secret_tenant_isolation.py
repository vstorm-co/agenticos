"""A github_oauth_app secret is bound to the organization that sealed it.

The vault's whole promise is that a ciphertext cannot be moved between owners:
even with the row in hand, org B cannot open a secret org A sealed. A mock
cannot prove that - it would only prove the repository's `WHERE` clause holds.
So this stores a real GitHub OAuth App credential through the service, opens it
for its own organization, and then takes the raw envelope and shows it fails to
unseal under a second organization's scope.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import GithubOAuthAppSecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.organization import Organization
from app.db.models.resource_grant import Visibility
from app.db.models.user import User
from app.repositories import organization_secret as organization_secret_repo
from app.services.organization_secret import OrganizationSecretService

pytestmark = pytest.mark.anyio


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
