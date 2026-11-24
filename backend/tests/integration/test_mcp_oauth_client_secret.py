"""Shared OAuth clients are unique and sealed; rotations invalidate copied grants."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AlreadyExistsError
from app.core.secret_kinds import McpOAuthClientSecret
from app.db.models.resource_grant import Visibility
from app.services.access import SECRET
from app.services.organization_secret import OrganizationSecretService
from app.services.sharing import SharingService
from tests.integration.test_secret_tenant_isolation import _ctx, _org

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_shared_client_lifecycle_and_tenant_boundary(db: AsyncSession):
    org, owner = await _org(db, name="Acme")
    other, other_owner = await _org(db, name="Other")
    ctx, foreign = _ctx(org, owner), _ctx(other, other_owner)
    service = OrganizationSecretService(db)
    value = McpOAuthClientSecret(
        server_url="https://SRV:443/mcp/",
        client_id="shared-client",
        client_secret="never-in-plaintext",
    )
    stored = await service.create(ctx, name="MCP client", value=value, purpose="custom")
    assert "never-in-plaintext" not in stored.sealed_secret
    assert stored.mcp_oauth_server == "https://srv/mcp"
    identity = await service.mcp_oauth_client_identity(ctx, "https://srv/mcp/")
    assert identity is not None and identity[0].client_id == "shared-client"
    assert await service.mcp_oauth_client_identity(foreign, "https://srv/mcp") is None
    assert await service.mcp_oauth_client_identity(ctx, "https://srv/other") is None
    assert await service.mcp_oauth_client_identity(ctx, "https://srv/mcp?client=1") is None
    with pytest.raises(AlreadyExistsError):
        await service.create(ctx, name="Duplicate", value=value, purpose="custom")
    private = await service.create(
        ctx, name="Private", value=value, purpose="custom", visibility=Visibility.PRIVATE
    )
    await service.update(
        ctx, private.id, value=value.model_copy(update={"client_id": "private-client"})
    )
    with pytest.raises(AlreadyExistsError):
        await SharingService(db).set_visibility(
            ctx, private, resource_type=SECRET, visibility=Visibility.ORG
        )
    await service.update(ctx, stored.id, value=value.model_copy(update={"client_id": "rotated"}))
    rotated = await service.mcp_oauth_client_identity(ctx, "https://srv/mcp")
    assert rotated is not None and rotated[2] != identity[2]
    # Hiding the shared client makes it unavailable, even if another private row matches.
    await SharingService(db).set_visibility(
        ctx, stored, resource_type=SECRET, visibility=Visibility.PRIVATE
    )
    assert await service.mcp_oauth_client_identity(ctx, "https://srv/mcp") is None
    await SharingService(db).set_visibility(
        ctx, private, resource_type=SECRET, visibility=Visibility.ORG
    )
    assert (await service.mcp_oauth_client_identity(ctx, "https://srv/mcp"))[1] == private.id
    await service.delete(ctx, private.id)
    assert await service.mcp_oauth_client_identity(ctx, "https://srv/mcp") is None
