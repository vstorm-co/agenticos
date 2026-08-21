"""Two organizations sharing a collection name each resolve their own config.

`collection_name` is indexed but not unique, so two tenants can name a
collection the same thing. Resolving one by name alone returned whichever row
the database yielded first, which could unseal and bill another organization's
key (#913). The resolvers now take the organization the search or ingest acts
for; these run them against a real database with two tenants on one name and
assert each gets its own embedding and rerank configuration - never the other's.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr

from app.core.secret_kinds import ApiKeySecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.services.embedding_resolution import embeddings_for_collection
from app.services.rerank_resolution import reranker_for_collection

pytestmark = pytest.mark.anyio

_SHARED = "shared_collection"


async def _org(db, name: str) -> Organization:
    founder = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(founder)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name=name,
        slug=f"{name}-{uuid.uuid4().hex[:8]}",
        created_by_user_id=founder.id,
    )
    db.add(org)
    await db.flush()
    return org


async def _cohere_secret(db, org: Organization, key: str) -> OrganizationSecret:
    sealed = seal_secret(
        ApiKeySecret(api_key=SecretStr(key)), scope=VaultScope.organization(org.id)
    )
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="cohere",
        kind="api_key",
        purpose="cohere",
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
        key_version=sealed.key_version,
    )
    db.add(secret)
    await db.flush()
    return secret


async def _kb(db, org: Organization, *, embedding_model: str, rerank_key: str) -> None:
    secret = await _cohere_secret(db, org, rerank_key)
    db.add(
        KnowledgeBase(
            id=uuid.uuid4(),
            name=f"{org.name} handbook",
            scope=KBScope.ORG.value,
            collection_name=_SHARED,
            embedding_model=embedding_model,
            embedding_dim=1536,
            rerank_model="rerank-v3.5",
            rerank_secret_id=secret.id,
            organization_id=org.id,
            ingestion_config={},
        )
    )
    await db.flush()


async def test_each_organization_resolves_its_own_embedding_and_rerank_config(db) -> None:
    org_a = await _org(db, "acme")
    org_b = await _org(db, "globex")
    await _kb(db, org_a, embedding_model="model-a", rerank_key="cohere-key-a")
    await _kb(db, org_b, embedding_model="model-b", rerank_key="cohere-key-b")
    # The resolvers open their own session, so the rows must be committed to be
    # visible to it.
    await db.commit()

    emb_a = await embeddings_for_collection(_SHARED, organization_id=org_a.id)
    emb_b = await embeddings_for_collection(_SHARED, organization_id=org_b.id)
    assert emb_a is not None and emb_a.model == "model-a"
    assert emb_b is not None and emb_b.model == "model-b"

    rer_a = await reranker_for_collection(_SHARED, organization_id=org_a.id)
    rer_b = await reranker_for_collection(_SHARED, organization_id=org_b.id)
    assert rer_a is not None and rer_a.api_key == "cohere-key-a"
    assert rer_b is not None and rer_b.api_key == "cohere-key-b"


async def test_an_organization_without_a_row_for_the_name_resolves_nothing(db) -> None:
    """A third organization sharing neither row gets no config - not another
    tenant's - so it can never unseal a key that is not its own (#913)."""
    org_a = await _org(db, "acme")
    await _kb(db, org_a, embedding_model="model-a", rerank_key="cohere-key-a")
    stranger = await _org(db, "initech")
    await db.commit()

    assert await embeddings_for_collection(_SHARED, organization_id=stranger.id) is None
    assert await reranker_for_collection(_SHARED, organization_id=stranger.id) is None


def _kb_row(org: Organization, name: str, **secret_ids: uuid.UUID) -> KnowledgeBase:
    return KnowledgeBase(
        id=uuid.uuid4(),
        name=name,
        scope=KBScope.ORG.value,
        collection_name=name,
        embedding_model="model",
        embedding_dim=1536,
        organization_id=org.id,
        ingestion_config={},
        **secret_ids,
    )


async def test_an_authorized_kb_id_pins_resolution_to_that_row_not_a_same_named_one(db) -> None:
    """The residual of #913: an `app` KB and a restricted `org` KB can share a
    name, and a name+organization lookup returns the org row (own-org wins) even
    when access only authorized the app row. Passing the authorized `kb.id`
    resolves *that* row, so a member who may read the app collection never
    unseals or spends the restricted org collection's key."""
    org = await _org(db, "acme")
    org_secret = await _cohere_secret(db, org, "org-only-key")

    app_kb = KnowledgeBase(
        id=uuid.uuid4(),
        name="shared (app)",
        scope=KBScope.APP.value,
        collection_name=_SHARED,
        embedding_model="app-model",
        embedding_dim=1536,
        organization_id=None,
        ingestion_config={},
    )
    org_kb = KnowledgeBase(
        id=uuid.uuid4(),
        name="shared (org, restricted)",
        scope=KBScope.ORG.value,
        collection_name=_SHARED,
        embedding_model="org-model",
        embedding_dim=1536,
        rerank_model="rerank-v3.5",
        rerank_secret_id=org_secret.id,
        organization_id=org.id,
        ingestion_config={},
    )
    db.add_all([app_kb, org_kb])
    await db.flush()
    await db.commit()

    # By name+org, own-org wins: the restricted org row, and its key.
    assert (await embeddings_for_collection(_SHARED, organization_id=org.id)).model == "org-model"
    assert await reranker_for_collection(_SHARED, organization_id=org.id) is not None

    # Pinned to the authorized app row: the app config, and no org key.
    pinned_emb = await embeddings_for_collection(
        _SHARED, organization_id=org.id, knowledge_base_id=app_kb.id
    )
    assert pinned_emb is not None and pinned_emb.model == "app-model"
    assert (
        await reranker_for_collection(_SHARED, organization_id=org.id, knowledge_base_id=app_kb.id)
        is None
    )


async def test_knowledge_bases_using_finds_embedding_and_rerank_bindings(db) -> None:
    """A key bound as either a KB embedding or rerank credential is reported, so
    the vault does not call it unused and invite a deletion that SET NULL then
    turns off. Scoped to the organization: another tenant's binding never shows."""
    from app.repositories import knowledge_base_repo

    org = await _org(db, "acme")
    other = await _org(db, "globex")
    secret = await _cohere_secret(db, org, "co-key")
    other_secret = await _cohere_secret(db, other, "other-key")

    db.add_all(
        [
            _kb_row(org, "reranked", rerank_secret_id=secret.id),
            _kb_row(org, "embedded", embedding_secret_id=secret.id),
            _kb_row(org, "unrelated"),
            _kb_row(other, "other-tenant", rerank_secret_id=other_secret.id),
        ]
    )
    await db.flush()

    found = await knowledge_base_repo.knowledge_bases_using(
        db, organization_id=org.id, secret_id=secret.id
    )

    assert {name for _id, name in found} == {"reranked", "embedded"}
