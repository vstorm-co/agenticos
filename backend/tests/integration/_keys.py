"""A provider key in an organization's vault, for fixtures whose model has to publish.

Publish refuses a model profile with nothing to authenticate with (#2478), so a
fixture profile on a keyed provider names a real vault row rather than none.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret


async def provider_key(
    db: AsyncSession, organization_id: uuid.UUID, *, purpose: str = "openai"
) -> uuid.UUID:
    """Store an organization-wide API key for `purpose` and return its id."""
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-key"), scope=VaultScope.organization(organization_id)
    )
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=organization_id,
        name=f"{purpose} key {uuid.uuid4().hex[:6]}",
        purpose=purpose,
        visibility="org",
        kind=SecretKind.API_KEY.value,
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
    )
    db.add(secret)
    await db.flush()
    return secret.id
