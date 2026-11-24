"""Explicit owner consent for named shared accounts, independent of generic secret sharing."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.browser_fill import BrowserFillReason, BrowserFillRefused
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import BROWSER_SECRET_KINDS, seal_secret
from app.core.secret_scopes import organization_secret_scope
from app.db.models.organization_secret import OrganizationSecret
from app.repositories import agent as agent_repo
from app.repositories import browser_credential as repo
from app.repositories import member as member_repo
from app.schemas.browser_credential import BrowserCredentialPolicyRead, BrowserCredentialPolicyWrite
from app.services.access import AGENT, SECRET, resolve_access

from . import _access


class BrowserCredentialPolicyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _owner(
        self, ctx: AuthContext, secret_id: UUID, *, locked: bool = False
    ) -> tuple[AuthContext, OrganizationSecret]:
        current = await _access.person(self.db, ctx)
        row = await repo.secret(self.db, current.organization_id, secret_id, locked=locked)
        if (
            row is None
            or row.kind not in BROWSER_SECRET_KINDS
            or row.owner_user_id != current.personal_user_id
            or row.visibility != "private"
            or row.usage_scope not in ("personal", "organization")
            or (
                row.usage_scope == "organization"
                and not await repo.policy_exists(self.db, current.organization_id, secret_id)
            )
            or not await resolve_access(
                self.db, current, row, Perm.SECRETS_EDIT, resource_type=SECRET
            )
        ):
            raise NotFoundError(message="Browser credential not found")
        return current, row

    async def _read(self, row: OrganizationSecret) -> BrowserCredentialPolicyRead:
        agents, members = await repo.grants(self.db, row.organization_id, row.id)
        return BrowserCredentialPolicyRead(
            secret_id=row.id,
            authorization_generation=row.authorization_generation,
            mode="personal" if row.usage_scope == "personal" else "shared",
            agent_ids=agents,
            member_ids=members,
        )

    async def get(self, ctx: AuthContext, secret_id: UUID) -> BrowserCredentialPolicyRead:
        _, row = await self._owner(ctx, secret_id)
        return await self._read(row)

    async def update(
        self, ctx: AuthContext, secret_id: UUID, data: BrowserCredentialPolicyWrite
    ) -> BrowserCredentialPolicyRead:
        current, row = await self._owner(ctx, secret_id, locked=True)
        if row.authorization_generation != data.generation:
            raise BrowserFillRefused(BrowserFillReason.AUTHORITY_CHANGED)
        previous = await self._read(row)
        agent_ids, member_ids = sorted(data.agent_ids), sorted(data.member_ids)
        if (
            previous.mode == data.mode
            and previous.agent_ids == agent_ids
            and previous.member_ids == member_ids
        ):
            return previous
        if data.mode == "shared":
            _access.enabled(current.organization_id, current.subject_id)
            if not settings.BROWSER_CREDENTIAL_SHARED_ENABLED:
                raise BrowserFillRefused(BrowserFillReason.DISABLED)
            for agent_id in data.agent_ids:
                agent = await agent_repo.get(
                    self.db, agent_id, organization_id=current.organization_id
                )
                if (
                    agent is None
                    or agent.status == "archived"
                    or not await resolve_access(
                        self.db, current, agent, Perm.AGENTS_RUN, resource_type=AGENT
                    )
                ):
                    raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
            for member_id in data.member_ids:
                if (
                    await member_repo.get_active(
                        self.db, organization_id=current.organization_id, user_id=member_id
                    )
                    is None
                ):
                    raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
        value = _access.open_value(row)
        scope = "personal" if data.mode == "personal" else "organization"
        sealed = seal_secret(
            value,
            scope=organization_secret_scope(
                organization_id=row.organization_id,
                kind=row.kind,
                usage_scope=scope,
                owner_user_id=row.owner_user_id,
            ),
        )
        await repo.replace_policy(
            self.db,
            organization_id=row.organization_id,
            secret_id=row.id,
            shared=data.mode == "shared",
            agent_ids=tuple(agent_ids),
            member_ids=tuple(member_ids),
        )
        row.usage_scope = scope
        row.sealed_secret, row.key_version, row.hint = sealed.ciphertext, sealed.key_version, ""
        row.authorization_generation = uuid4()
        await self.db.flush()
        await record_audit(
            self.db,
            organization_id=row.organization_id,
            actor_user_id=current.subject_id,
            action="browser_credential.policy_changed",
            target_type="secret",
            target_id=str(row.id),
            details={
                "mode": data.mode,
                "generation": str(row.authorization_generation),
                "agent_ids": [str(item) for item in agent_ids],
                "member_ids": [str(item) for item in member_ids],
            },
        )
        return await self._read(row)
