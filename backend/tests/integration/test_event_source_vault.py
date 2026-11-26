"""Live Vault references preserve tenant boundaries and rotation on real PostgreSQL."""

from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.secret_kinds import ApiKeySecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.event_source import EventDelivery
from app.db.models.organization_secret import OrganizationSecret
from app.schemas.event_source import EventSourceCreate, SourceAuth, SourceCredentials
from app.services.event_sources import EventSourceService
from tests.integration.test_workflow_exposures import _ctx, _org, _user

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_live_reference_rotates_revokes_and_never_crosses_organization(db):
    user = await _user(db)
    org = await _org(db, owner=user)
    ctx = _ctx(user, org)
    envelope = seal_secret(
        ApiKeySecret(api_key=SecretStr("original-key")), scope=VaultScope.organization(org.id)
    )
    secret = OrganizationSecret(
        id=uuid4(),
        organization_id=org.id,
        name="Ingress",
        kind="api_key",
        purpose="custom",
        visibility="org",
        owner_user_id=None,
        sealed_secret=envelope.ciphertext,
        key_version=envelope.key_version,
    )
    db.add(secret)
    await db.flush()
    service = EventSourceService(db)
    config = EventSourceCreate(
        name="Events",
        auth=SourceAuth(method="api_key", header_name="x-key", signature_prefix=""),
        credentials=SourceCredentials(vault_secret_id=secret.id),
    )
    source = await service.create(ctx, config)
    assert source.reveal_secret is None
    await service.receive(source.id, body=b"{}", headers={"x-key": "original-key"})
    envelope = seal_secret(
        ApiKeySecret(api_key=SecretStr("replacement-key")), scope=VaultScope.organization(org.id)
    )
    secret.sealed_secret, secret.key_version = envelope.ciphertext, envelope.key_version
    await db.flush()
    with pytest.raises(AuthorizationError):
        await service.receive(source.id, body=b"{}", headers={"x-key": "original-key"})
    await service.receive(source.id, body=b"{}", headers={"x-key": "replacement-key"})
    other_org = await _org(db, owner=user)
    with pytest.raises(NotFoundError):
        await service.create(_ctx(user, other_org), config)
    secret.visibility, secret.owner_user_id = "private", user.id
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.receive(source.id, body=b"{}", headers={"x-key": "replacement-key"})
    await db.delete(secret)
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.receive(source.id, body=b"{}", headers={"x-key": "replacement-key"})
    assert (
        await db.scalar(
            select(func.count())
            .select_from(EventDelivery)
            .where(EventDelivery.source_id == source.id)
        )
        == 2
    )
