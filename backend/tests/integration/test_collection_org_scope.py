"""Per-collection resolution stays inside the caller's organization (#913).

`knowledge_bases.collection_name` is indexed but not unique: two organizations
can name a collection the same thing and share one vector table. Resolving by
name alone - `get_by_collection_name(...).first()` - returns whichever row the
database orders first, so an embedding call for org A could land on org B's
knowledge base and unseal *B's* vault key for *A's* request, billing B and
running A's text through B's credential.

A mock would only restate the `WHERE`; these seed two real tenants that share a
name and prove the resolution picks each tenant's own row, falls back to an
app-scoped one, and never crosses to a third tenant - and that the embedding
resolver unseals only the caller organization's key.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr

from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import knowledge_base_repo
from app.services.embedding_resolution import EmbeddingKeySource, embeddings_for_collection
from app.services.organization_secret import OrganizationSecretService

pytestmark = pytest.mark.anyio


async def _org(db, *, name: str) -> tuple[Organization, User]:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    organization = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(organization)
    await db.flush()
    return organization, founder


def _kb(
    organization_id: uuid.UUID | None,
    collection_name: str,
    *,
    scope: str = KBScope.ORG.value,
    secret_id: uuid.UUID | None = None,
) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=collection_name,
        scope=scope,
        collection_name=collection_name,
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        embedding_provider="openrouter",
        organization_id=organization_id,
        embedding_secret_id=secret_id,
        visibility="org" if scope == KBScope.ORG.value else None,
    )


class TestTheLookupStaysInsideTheOrganization:
    async def test_a_shared_name_resolves_each_organizations_own_row(self, db) -> None:
        org_a, _ = await _org(db, name="Alpha")
        org_b, _ = await _org(db, name="Beta")
        kb_a = _kb(org_a.id, "shared")
        kb_b = _kb(org_b.id, "shared")
        db.add_all([kb_a, kb_b])
        await db.flush()

        resolved_a = await knowledge_base_repo.get_for_collection(db, "shared", org_a.id)
        resolved_b = await knowledge_base_repo.get_for_collection(db, "shared", org_b.id)

        assert resolved_a is not None and resolved_a.id == kb_a.id
        assert resolved_b is not None and resolved_b.id == kb_b.id

    async def test_a_third_organization_gets_no_row_rather_than_a_foreign_one(self, db) -> None:
        """The refusal: a tenant that holds no such collection resolves to None,
        never to another tenant's row of the same name."""
        org_a, _ = await _org(db, name="Alpha")
        org_c, _ = await _org(db, name="Gamma")
        db.add(_kb(org_a.id, "shared"))
        await db.flush()

        assert await knowledge_base_repo.get_for_collection(db, "shared", org_c.id) is None

    async def test_an_app_scoped_row_is_the_fallback_a_foreign_org_row_is_not(self, db) -> None:
        """An app-scoped collection belongs to no organization and is deployment-wide,
        so it is the second-pass match; a third tenant's org-scoped row is never one."""
        org_a, _ = await _org(db, name="Alpha")
        org_c, _ = await _org(db, name="Gamma")
        kb_a = _kb(org_a.id, "shared")
        kb_app = _kb(None, "shared", scope=KBScope.APP.value)
        db.add_all([kb_a, kb_app])
        await db.flush()

        assert (await knowledge_base_repo.get_for_collection(db, "shared", org_a.id)).id == kb_a.id
        assert (
            await knowledge_base_repo.get_for_collection(db, "shared", org_c.id)
        ).id == kb_app.id


class TestTheEmbeddingResolverUnsealsOnlyTheCallersKey:
    async def test_a_shared_name_never_unseals_another_tenants_vault_key(self, db) -> None:
        """The security payoff (#913): org A chose its own key; resolving the same
        collection name for org B must not open A's vault entry and bill A - it
        resolves B's own configuration, which here is the deployment fallback."""
        org_a, owner_a = await _org(db, name="Alpha")
        org_b, _ = await _org(db, name="Beta")
        secret = await OrganizationSecretService(db).create(
            AuthContext(user_id=owner_a.id, organization_id=org_a.id, role=OrgRoleName.OWNER),
            name="Alpha key",
            value=ApiKeySecret(api_key=SecretStr("sk-alpha-only")),
            purpose="openrouter",
        )
        db.add_all([_kb(org_a.id, "shared", secret_id=secret.id), _kb(org_b.id, "shared")])
        # The resolver opens its own session, so the rows must be committed.
        await db.commit()

        resolved_a = await embeddings_for_collection("shared", org_a.id)
        resolved_b = await embeddings_for_collection("shared", org_b.id)

        assert resolved_a is not None and resolved_a.api_key == "sk-alpha-only"
        assert resolved_a.key_source is EmbeddingKeySource.ORGANIZATION

        assert resolved_b is not None
        assert resolved_b.api_key != "sk-alpha-only"
        assert resolved_b.key_source is EmbeddingKeySource.DEPLOYMENT
