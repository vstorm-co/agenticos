"""Personal coding-account ownership, consent and vault persistence."""

import hashlib
from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import run_impersonated
from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from app.core.permissions import AuthContext
from app.core.secret_kinds import (
    ApiKeySecret,
    OpenAICodexSecret,
    SecretKind,
    seal_secret,
    unseal_secret,
)
from app.core.vault import VaultScope
from app.db.models.coding_account import CodingAccount
from app.repositories import coding_account as account_repo
from app.repositories import member as member_repo
from app.schemas.coding_account import CodingAccountCreate, CodingAccountUpdate, CodingHarness


def account_owner(ctx: AuthContext) -> UUID:
    if (
        run_impersonated()
        or ctx.user_id is None
        or ctx.api_key_id is not None
        or ctx.key_scopes is not None
    ):
        raise AuthorizationError(
            message="A personal coding account requires your signed-in session"
        )
    return ctx.user_id


class CodingAccountService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def mine(self, ctx: AuthContext) -> Sequence[CodingAccount]:
        return await account_repo.list_for(
            self.db, organization_id=ctx.organization_id, user_id=account_owner(ctx)
        )

    async def create(self, ctx: AuthContext, data: CodingAccountCreate) -> CodingAccount:
        return await self.save(
            ctx,
            harness=data.harness,
            label=data.label,
            secret=ApiKeySecret(api_key=data.api_key),
            enabled=data.enabled,
        )

    async def save(
        self,
        ctx: AuthContext,
        *,
        harness: CodingHarness,
        label: str,
        secret: ApiKeySecret | OpenAICodexSecret,
        enabled: bool,
    ) -> CodingAccount:
        owner = account_owner(ctx)
        await self._lock_owner(ctx, owner)
        existing = await account_repo.list_for(
            self.db, organization_id=ctx.organization_id, user_id=owner
        )
        matching_harness = [row for row in existing if row.harness == harness]
        if harness == "claude_code" and matching_harness:
            raise AlreadyExistsError(
                message="This provider does not expose a stable account identity; only one Claude account can be connected.",
                details={"harness": harness},
            )

        identity = self._provider_identity(secret)
        for row in matching_harness:
            existing_identity = row.provider_identity_fingerprint
            if existing_identity is None:
                stored = unseal_secret(
                    row.sealed_secret,
                    kind=SecretKind(row.secret_kind),
                    scope=VaultScope.user(owner),
                    key_version=row.key_version,
                )
                if not isinstance(stored, (ApiKeySecret, OpenAICodexSecret)):
                    raise TypeError("A coding account has an unsupported stored credential")
                existing_identity = self._provider_identity(stored)
                if existing_identity is None:
                    raise ConflictError(
                        message="The existing provider account has no verified stable identity.",
                        details={"harness": harness},
                    )
                row.provider_identity_fingerprint = existing_identity
                await self.db.flush()
            if identity is None:
                raise ConflictError(
                    message="This provider credential has no verified stable account identity.",
                    details={"harness": harness},
                )
            if existing_identity == identity:
                raise AlreadyExistsError(
                    message="This provider account is already connected.",
                    details={"harness": harness},
                )

        sealed = seal_secret(secret, scope=VaultScope.user(owner))
        try:
            async with self.db.begin_nested():
                row = await account_repo.create(
                    self.db,
                    CodingAccount(
                        organization_id=ctx.organization_id,
                        user_id=owner,
                        harness=harness,
                        label=label,
                        secret_kind=secret.kind.value,
                        sealed_secret=sealed.ciphertext,
                        key_version=sealed.key_version,
                        enabled=enabled,
                        is_default=not matching_harness,
                        provider_identity_fingerprint=identity,
                    ),
                )
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != "23505":
                raise
            raise AlreadyExistsError(
                message="This provider account is already connected.",
                details={"harness": harness},
            ) from None
        await self._audit(ctx, row, "coding_account.connected")
        return row

    async def own(
        self, ctx: AuthContext, account_id: UUID, *, locked: bool = False
    ) -> CodingAccount:
        row = await account_repo.get(
            self.db,
            organization_id=ctx.organization_id,
            user_id=account_owner(ctx),
            account_id=account_id,
            locked=locked,
        )
        if row is None:
            raise NotFoundError(
                message="Coding account not found", details={"account_id": account_id}
            )
        return row

    async def update(
        self, ctx: AuthContext, account_id: UUID, data: CodingAccountUpdate
    ) -> CodingAccount:
        owner = account_owner(ctx)
        await self._lock_owner(ctx, owner)
        row = await self.own(ctx, account_id, locked=True)
        if row.generation != data.generation:
            raise ConflictError(
                message="The coding account changed. Reload its settings.",
                details={"account_id": account_id},
            )
        consent_changed = row.enabled != data.enabled
        default_changed = data.is_default is True and not row.is_default
        pool_changed = data.pool_member is not None and row.pool_member != data.pool_member
        replaced_defaults: list[CodingAccount] = []
        if data.is_default is True:
            if not data.enabled:
                raise BadRequestError(message="A disabled account cannot be the default")
            for other in await account_repo.list_for(
                self.db, organization_id=ctx.organization_id, user_id=row.user_id
            ):
                if other.harness == row.harness and other.id != row.id and other.is_default:
                    other.is_default = False
                    replaced_defaults.append(other)
            if replaced_defaults:
                await self.db.flush()
            row.is_default = True

        if data.pool_member is not None:
            if data.pool_member and row.harness != "codex":
                raise BadRequestError(
                    message="This provider has no verified account identity for pool selection"
                )
            if data.pool_member and row.provider_identity_fingerprint is None:
                secret = unseal_secret(
                    row.sealed_secret,
                    kind=SecretKind(row.secret_kind),
                    scope=VaultScope.user(owner),
                    key_version=row.key_version,
                )
                if not isinstance(secret, OpenAICodexSecret):
                    raise BadRequestError(
                        message="This provider has no verified account identity for pool selection"
                    )
                row.provider_identity_fingerprint = self._codex_identity(secret)
            if row.pool_member != data.pool_member:
                row.pool_member = data.pool_member
                row.generation = uuid4()
        if row.enabled != data.enabled:
            row.enabled = data.enabled
            row.generation = uuid4()
        await self.db.flush()
        if consent_changed:
            await self._audit(ctx, row, "coding_account.consent_changed")
        if default_changed:
            for previous in replaced_defaults:
                await self._audit(ctx, previous, "coding_account.default_changed")
            await self._audit(ctx, row, "coding_account.default_changed")
        if pool_changed:
            await self._audit(ctx, row, "coding_account.pool_membership_changed")
        return row

    async def disconnect(self, ctx: AuthContext, account_id: UUID) -> None:
        owner = account_owner(ctx)
        await self._lock_owner(ctx, owner)
        row = await self.own(ctx, account_id, locked=True)
        await self._audit(ctx, row, "coding_account.disconnected")
        await account_repo.delete(self.db, row)

    async def _audit(self, ctx: AuthContext, row: CodingAccount, action: str) -> None:
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action=action,
            target_type="coding_account",
            target_id=str(row.id),
            details={
                "harness": row.harness,
                "enabled": row.enabled,
                "is_default": row.is_default,
                "pool_member": row.pool_member,
            },
        )

    async def _lock_owner(self, ctx: AuthContext, owner: UUID) -> None:
        membership = await member_repo.get(
            self.db,
            organization_id=ctx.organization_id,
            user_id=owner,
            for_update=True,
        )
        if membership is None:
            raise AuthorizationError(
                message="A personal coding account requires organization membership"
            )

    @staticmethod
    def _provider_identity(secret: ApiKeySecret | OpenAICodexSecret) -> str | None:
        if not isinstance(secret, OpenAICodexSecret):
            return None
        return CodingAccountService._codex_identity(secret)

    @staticmethod
    def _codex_identity(secret: OpenAICodexSecret) -> str:
        identity = f"openai:{secret.account_id}".encode()
        return hashlib.sha256(identity).hexdigest()
