"""Guarantees only the database can make about a service connection's key."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.service_connection import ServiceConnection
from app.db.models.user import User

pytestmark = pytest.mark.anyio


async def _org(db) -> Organization:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
    )
    db.add(org)
    await db.flush()
    db.add(
        OrganizationMember(id=uuid.uuid4(), organization_id=org.id, user_id=user.id, role="owner")
    )
    await db.flush()
    return org


async def _secret(db, org: Organization) -> OrganizationSecret:
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=org.id,
        name="gateway",
        purpose="openai_compatible",
        visibility="org",
        kind="api_key",
        sealed_secret="{}",
        hint="1234",
    )
    db.add(secret)
    await db.flush()
    return secret


def _connection(
    *, organization_id: uuid.UUID | None, secret_id: uuid.UUID | None = None, requires_key=False
) -> ServiceConnection:
    return ServiceConnection(
        id=uuid.uuid4(),
        organization_id=organization_id,
        kind="embedding",
        provider="openai_compatible",
        name=f"gw-{uuid.uuid4().hex[:6]}",
        base_url="https://gateway.example.com/v1",
        secret_id=secret_id,
        requires_key=requires_key,
    )


@pytest.mark.security
async def test_a_deployment_owned_connection_cannot_hold_a_key(db):
    org = await _org(db)
    secret = await _secret(db, org)
    db.add(_connection(organization_id=None, secret_id=secret.id, requires_key=True))
    with pytest.raises(IntegrityError) as raised:
        await db.flush()
    assert "service_connections_ck_service_connections_deployment_k_44ad" in str(raised.value)


@pytest.mark.security
async def test_deleting_the_key_nulls_secret_id_and_keeps_requires_key(db):
    org = await _org(db)
    secret = await _secret(db, org)
    connection = _connection(organization_id=org.id, secret_id=secret.id, requires_key=True)
    db.add(connection)
    await db.flush()

    await db.delete(secret)
    await db.flush()
    await db.refresh(connection)

    assert connection.secret_id is None
    assert connection.requires_key is True


async def test_deleting_the_connection_nulls_the_knowledge_bases_endpoint(db):
    org = await _org(db)
    connection = _connection(organization_id=org.id)
    db.add(connection)
    await db.flush()
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name="Docs",
        scope=KBScope.ORG.value,
        organization_id=org.id,
        collection_name=f"c_{uuid.uuid4().hex[:12]}",
        embedding_model="my-embed",
        embedding_dim=1024,
        embedding_provider="openai_compatible",
        embedding_endpoint_id=connection.id,
        visibility="org",
    )
    db.add(kb)
    await db.flush()

    await db.delete(connection)
    await db.flush()
    await db.refresh(kb)

    assert kb.embedding_endpoint_id is None
