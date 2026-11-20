"""Native Pi exports require independent current vault access, not agent run access."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.secret_kinds import ApiKeySecret
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import Visibility
from app.repositories import member_repo
from app.services.organization_secret import OrganizationSecretService
from tests.integration.test_secret_tenant_isolation import _ctx, _member, _org

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_only_a_current_member_with_private_key_visibility_can_export_it_to_pi(
    db: AsyncSession,
) -> None:
    organization, owner = await _org(db, name="Pi")
    other = await _member(db)
    foreign, foreign_owner = await _org(db, name="Elsewhere")
    db.add_all(
        [
            OrganizationMember(organization_id=organization.id, user_id=owner.id, role="owner"),
            OrganizationMember(organization_id=organization.id, user_id=other.id, role="member"),
            OrganizationMember(organization_id=foreign.id, user_id=foreign_owner.id, role="owner"),
        ]
    )
    await db.flush()
    service = OrganizationSecretService(db)
    secret = await service.create(
        _ctx(organization, owner),
        name="Private Pi API",
        value=ApiKeySecret(api_key="selected-private-key"),
        purpose="deepseek",
        visibility=Visibility.PRIVATE,
    )
    selected = await service.native_runtime_key(
        organization_id=organization.id, user_id=owner.id, secret_id=secret.id, provider="deepseek"
    )
    assert selected.api_key.get_secret_value() == "selected-private-key"
    for organization_id, user_id in [(organization.id, other.id), (foreign.id, foreign_owner.id)]:
        with pytest.raises(NotFoundError):
            await service.native_runtime_key(
                organization_id=organization_id,
                user_id=user_id,
                secret_id=secret.id,
                provider="deepseek",
            )
    # Even a formerly privileged owner cannot export after membership removal.
    member = await member_repo.get(db, organization_id=organization.id, user_id=owner.id)
    assert member is not None
    await db.delete(member)
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.native_runtime_key(
            organization_id=organization.id,
            user_id=owner.id,
            secret_id=secret.id,
            provider="deepseek",
        )
