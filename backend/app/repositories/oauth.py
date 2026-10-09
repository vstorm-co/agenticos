"""OAuth repository for the platform's MCP authorization server (PostgreSQL async)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.api_key import ApiKey
from app.db.models.oauth import (
    OAuthAuthorizationCode,
    OAuthAuthorizationRequest,
    OAuthClient,
    OAuthGrant,
    OAuthRefreshToken,
)
from app.db.models.user import User


async def get_client(db: AsyncSession, client_id: str) -> OAuthClient | None:
    return await db.get(OAuthClient, client_id)


async def create_client(db: AsyncSession, *, client_id: str, info: dict[str, Any]) -> OAuthClient:
    client = OAuthClient(client_id=client_id, info=info)
    db.add(client)
    await db.flush()
    await db.refresh(client)
    return client


async def create_request(
    db: AsyncSession, *, client_id: str, params: dict[str, Any], expires_at: datetime
) -> OAuthAuthorizationRequest:
    row = OAuthAuthorizationRequest(client_id=client_id, params=params, expires_at=expires_at)
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_request(db: AsyncSession, request_id: UUID) -> OAuthAuthorizationRequest | None:
    return await db.get(OAuthAuthorizationRequest, request_id)


async def delete_request(db: AsyncSession, request: OAuthAuthorizationRequest) -> None:
    await db.delete(request)
    await db.flush()


async def create_grant(
    db: AsyncSession, *, client_id: str, user_id: UUID, organization_id: UUID, scopes: list[str]
) -> OAuthGrant:
    grant = OAuthGrant(
        client_id=client_id, user_id=user_id, organization_id=organization_id, scopes=scopes
    )
    db.add(grant)
    await db.flush()
    await db.refresh(grant)
    return grant


async def get_grant(db: AsyncSession, grant_id: UUID) -> OAuthGrant | None:
    return await db.get(OAuthGrant, grant_id)


async def get_grant_in_org(
    db: AsyncSession, grant_id: UUID, *, organization_id: UUID
) -> OAuthGrant | None:
    result = await db.execute(
        select(OAuthGrant).where(
            OAuthGrant.id == grant_id, OAuthGrant.organization_id == organization_id
        )
    )
    return result.scalar_one_or_none()


async def list_grants(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID | None
) -> list[tuple[OAuthGrant, OAuthClient, str]]:
    """Live grants with their client and the consenting member's email, newest first."""
    query = (
        select(OAuthGrant, OAuthClient, User.email)
        .join(OAuthClient, OAuthClient.client_id == OAuthGrant.client_id)
        .join(User, User.id == OAuthGrant.user_id)
        .where(OAuthGrant.organization_id == organization_id, OAuthGrant.revoked_at.is_(None))
        .order_by(OAuthGrant.created_at.desc())
    )
    if user_id is not None:
        query = query.where(OAuthGrant.user_id == user_id)
    result = await db.execute(query)
    return [(grant, client, email) for grant, client, email in result.all()]


async def revoke_grant(db: AsyncSession, grant: OAuthGrant, *, at: datetime) -> None:
    """Revoke a grant and every access token issued under it."""
    grant.revoked_at = at
    await db.execute(
        sql_update(ApiKey)
        .where(ApiKey.oauth_grant_id == grant.id, ApiKey.revoked_at.is_(None))
        .values(revoked_at=at)
    )
    await db.flush()


async def create_code(
    db: AsyncSession,
    *,
    code_hash: str,
    grant_id: UUID,
    code_challenge: str,
    redirect_uri: str,
    redirect_uri_provided_explicitly: bool,
    resource: str | None,
    expires_at: datetime,
) -> OAuthAuthorizationCode:
    code = OAuthAuthorizationCode(
        code_hash=code_hash,
        grant_id=grant_id,
        code_challenge=code_challenge,
        redirect_uri=redirect_uri,
        redirect_uri_provided_explicitly=redirect_uri_provided_explicitly,
        resource=resource,
        expires_at=expires_at,
    )
    db.add(code)
    await db.flush()
    return code


async def get_code(
    db: AsyncSession, code_hash: str
) -> tuple[OAuthAuthorizationCode, OAuthGrant] | None:
    """A code with the grant it binds - one row, as the foreign key guarantees."""
    result = await db.execute(
        select(OAuthAuthorizationCode, OAuthGrant)
        .join(OAuthGrant, OAuthGrant.id == OAuthAuthorizationCode.grant_id)
        .where(OAuthAuthorizationCode.code_hash == code_hash)
    )
    found = result.first()
    return (found[0], found[1]) if found else None


async def create_refresh_token(
    db: AsyncSession, *, token_hash: str, grant_id: UUID, scopes: list[str], expires_at: datetime
) -> OAuthRefreshToken:
    token = OAuthRefreshToken(
        token_hash=token_hash, grant_id=grant_id, scopes=scopes, expires_at=expires_at
    )
    db.add(token)
    await db.flush()
    return token


async def get_refresh_token(
    db: AsyncSession, token_hash: str
) -> tuple[OAuthRefreshToken, OAuthGrant] | None:
    """A refresh token with the grant it renews."""
    result = await db.execute(
        select(OAuthRefreshToken, OAuthGrant)
        .join(OAuthGrant, OAuthGrant.id == OAuthRefreshToken.grant_id)
        .where(OAuthRefreshToken.token_hash == token_hash)
    )
    found = result.first()
    return (found[0], found[1]) if found else None


async def mark_used(
    db: AsyncSession, row: OAuthAuthorizationCode | OAuthRefreshToken, at: datetime
) -> None:
    row.used_at = at
    await db.flush()


async def delete_expired_requests(db: AsyncSession, *, before: datetime) -> None:
    await db.execute(
        delete(OAuthAuthorizationRequest).where(OAuthAuthorizationRequest.expires_at < before)
    )
