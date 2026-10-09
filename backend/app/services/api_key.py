"""Organization API keys: issuing, listing, revoking, and authenticating a request (#1794).

A key carries its issuer's authority, narrowed twice: to the scopes it was issued
with, and - at every use - to what the issuer may still do. Authentication
therefore re-reads the issuer's membership on every request rather than trusting
anything frozen into the key, which is what makes demoting or removing a member
narrow or stop every key they hold.

The plaintext is in exactly one response, the one that creates it. It is never
logged, audited or returned again; refusals name the key by its prefix at most.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.api_key import ApiKey
from app.db.models.organization import Organization
from app.db.models.user import User
from app.repositories import api_key as api_key_repo
from app.repositories import member as member_repo
from app.repositories import organization as organization_repo
from app.repositories import user as user_repo
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyList,
    ApiKeyPreset,
    ApiKeyRead,
    ApiKeyScopeCatalog,
    ApiKeyStatus,
)

KEY_PREFIX = "aos_"
"""What every organization key starts with - so a secret scanner, a log scrubber
and :func:`is_api_key` recognise one without a database round trip."""

_PREFIX_LENGTH = len(KEY_PREFIX) + 8
_SECRET_BYTES = 32
_TOUCH_EVERY = timedelta(minutes=1)
_REFUSED = "Invalid, expired or revoked API key"

# Keys never manage keys: a leaked one must not be able to mint its successors.
_NOT_GRANTABLE = frozenset({Perm.API_KEYS_CREATE, Perm.API_KEYS_MANAGE})

_READ_ONLY = frozenset(
    {
        Perm.AGENTS_VIEW,
        Perm.COLLECTIONS_VIEW,
        Perm.SKILLS_VIEW,
        Perm.CONTEXT_VIEW,
        Perm.ARTIFACTS_VIEW,
        Perm.RUNS_VIEW,
    }
)
_KNOWLEDGE_INGEST = frozenset({Perm.COLLECTIONS_VIEW, Perm.COLLECTIONS_EDIT})


def is_api_key(token: str) -> bool:
    """Whether a bearer token is an organization key rather than a session JWT."""
    return token.startswith(KEY_PREFIX)


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _status(key: ApiKey, now: datetime) -> ApiKeyStatus:
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at is not None and key.expires_at <= now:
        return "expired"
    return "active"


def _read(key: ApiKey, issuer_email: str, now: datetime) -> ApiKeyRead:
    return ApiKeyRead(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        scopes=list(key.scopes),
        user_id=key.user_id,
        issuer_email=issuer_email,
        status=_status(key, now),
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
    )


@dataclass(frozen=True)
class KeyCaller:
    """Who a key-authenticated request is: the issuer, and their narrowed context."""

    user: User
    organization: Organization
    context: AuthContext
    api_key_id: UUID
    prefix: str


class ApiKeyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _grantable(ctx: AuthContext) -> list[Perm]:
        return sorted(perm for perm in ctx.permissions if perm not in _NOT_GRANTABLE)

    def scope_catalog(self, ctx: AuthContext) -> ApiKeyScopeCatalog:
        """The permissions the caller may put on a key, and the presets over them.

        "Read-only" and "Full access" hold what the caller has of them, so a
        Member's full access is a Member's. "Knowledge ingest" is a task rather than
        a ceiling - read a collection and add to it - so it is offered only to a
        caller who can do both; half of it would be a key that cannot ingest.
        """
        held = self._grantable(ctx)
        presets: list[ApiKeyPreset] = []
        read_only = [perm.value for perm in held if perm in _READ_ONLY]
        if read_only:
            presets.append(ApiKeyPreset(id="read_only", scopes=read_only))
        if set(held) >= _KNOWLEDGE_INGEST:
            presets.append(ApiKeyPreset(id="knowledge_ingest", scopes=sorted(_KNOWLEDGE_INGEST)))
        if held:
            presets.append(ApiKeyPreset(id="full_access", scopes=[perm.value for perm in held]))
        return ApiKeyScopeCatalog(scopes=[perm.value for perm in held], presets=presets)

    async def create(self, ctx: AuthContext, data: ApiKeyCreate) -> ApiKeyCreated:
        """Issue a key carrying the caller's authority, narrowed to `data.scopes`.

        Raises:
            BadRequestError: A scope the caller does not hold, or cannot grant, or an
                expiry already in the past - named on the field.
        """
        held = set(self._grantable(ctx))
        refused = sorted(perm.value for perm in data.scopes if perm not in held)
        if refused:
            raise refused_field(
                "scopes", f"You cannot grant what you do not hold: {', '.join(refused)}"
            )
        now = datetime.now(UTC)
        if data.expires_at is not None and data.expires_at <= now:
            raise refused_field("expires_at", "The expiry has to be in the future")
        prefix = KEY_PREFIX + secrets.token_hex(4)
        key = prefix + secrets.token_urlsafe(_SECRET_BYTES)
        row = await api_key_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            name=data.name,
            prefix=prefix,
            key_hash=_digest(key),
            scopes=sorted({perm.value for perm in data.scopes}),
            expires_at=data.expires_at,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="api_key.created",
            target_type="api_key",
            target_id=str(row.id),
            details={"name": row.name, "prefix": row.prefix, "scopes": row.scopes},
        )
        issuer = await user_repo.get_by_id(self.db, ctx.subject_id)
        email = issuer.email if issuer is not None else ""
        return ApiKeyCreated(**_read(row, email, now).model_dump(), key=key)

    async def list_keys(self, ctx: AuthContext) -> ApiKeyList:
        """Every key in the organization for `api_keys:manage`, otherwise the caller's own."""
        mine_only = None if ctx.has(Perm.API_KEYS_MANAGE) else ctx.subject_id
        rows = await api_key_repo.list_for_organization(
            self.db, organization_id=ctx.organization_id, user_id=mine_only
        )
        now = datetime.now(UTC)
        items = [_read(key, email, now) for key, email in rows]
        return ApiKeyList(items=items, total=len(items))

    async def revoke(self, ctx: AuthContext, key_id: UUID) -> ApiKeyRead:
        """Stop a key working, at once. Revoking a revoked key changes nothing.

        Raises:
            NotFoundError: Not this organization's key, or somebody else's for a
                caller without `api_keys:manage` - the same answer, so an id cannot
                be used to learn which keys exist.
        """
        key = await api_key_repo.get(self.db, key_id, organization_id=ctx.organization_id)
        if key is None or (key.user_id != ctx.subject_id and not ctx.has(Perm.API_KEYS_MANAGE)):
            raise NotFoundError(message="API key not found", details={"api_key_id": key_id})
        now = datetime.now(UTC)
        if key.revoked_at is None:
            key = await api_key_repo.update(self.db, key=key, update_data={"revoked_at": now})
            await record_audit(
                self.db,
                actor_user_id=ctx.subject_id,
                organization_id=ctx.organization_id,
                action="api_key.revoked",
                target_type="api_key",
                target_id=str(key.id),
                details={"name": key.name, "prefix": key.prefix},
            )
        issuer = await user_repo.get_by_id(self.db, key.user_id)
        return _read(key, issuer.email if issuer is not None else "", now)

    async def authenticate(self, raw: str) -> KeyCaller:
        """The issuer and narrowed context a presented key stands for.

        Every refusal is the same sentence: whether a prefix exists, was revoked or
        has expired is not something a caller holding a wrong key may learn.

        Raises:
            AuthenticationError: Unknown, wrong, revoked or expired key, or an issuer
                who is no longer an active member of the key's organization.
        """
        prefix = raw[:_PREFIX_LENGTH]
        key = await api_key_repo.get_by_prefix(self.db, prefix)
        if key is None or not secrets.compare_digest(key.key_hash, _digest(raw)):
            raise AuthenticationError(message=_REFUSED)
        now = datetime.now(UTC)
        if _status(key, now) != "active":
            raise AuthenticationError(message=_REFUSED, details={"prefix": key.prefix})
        membership = await member_repo.get_active(
            self.db, organization_id=key.organization_id, user_id=key.user_id
        )
        issuer = await user_repo.get_by_id(self.db, key.user_id)
        organization = await organization_repo.get_by_id(self.db, key.organization_id)
        if membership is None or issuer is None or not issuer.is_active or organization is None:
            raise AuthenticationError(message=_REFUSED, details={"prefix": key.prefix})
        await api_key_repo.touch(self.db, key.id, at=now, stale_before=now - _TOUCH_EVERY)
        return KeyCaller(
            user=issuer,
            organization=organization,
            api_key_id=key.id,
            prefix=key.prefix,
            context=AuthContext(
                user_id=key.user_id,
                organization_id=key.organization_id,
                role=membership.role,
                api_key_id=key.id,
                key_scopes=frozenset(Perm(scope) for scope in key.scopes if scope in Perm),
            ),
        )
