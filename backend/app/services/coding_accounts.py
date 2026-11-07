"""Personal coding-account ownership, consent and vault persistence."""

from collections.abc import Sequence
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import run_impersonated
from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, AuthorizationError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, OpenAICodexSecret, seal_secret
from app.core.vault import VaultScope
from app.db.models.coding_account import CodingAccount
from app.repositories import coding_account as account_repo
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
                    ),
                )
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != "23505":
                raise
            raise AlreadyExistsError(
                message="Disconnect the existing coding account before connecting another",
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
        row = await self.own(ctx, account_id, locked=True)
        if row.generation != data.generation:
            raise ConflictError(
                message="The coding account changed. Reload its settings.",
                details={"account_id": account_id},
            )
        row.enabled = data.enabled
        row.generation = uuid4()
        await self.db.flush()
        await self._audit(ctx, row, "coding_account.consent_changed")
        return row

    async def disconnect(self, ctx: AuthContext, account_id: UUID) -> None:
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
            details={"harness": row.harness, "enabled": row.enabled},
        )
