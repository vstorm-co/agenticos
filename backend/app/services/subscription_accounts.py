"""A person's own subscription accounts, signed in through the bundled gateway.

Each person in each organization has one gateway scope: its own CLIProxyAPI
process, sign-ins and keys (`app.subscription_gateway`). The scope is a digest of
the organization, person and membership generation, derived here and nowhere else, so a browser
never names one and the same person in two organizations holds two separate
sets of accounts. A run on a `subscription_accounts` model spends the running
person's scope only (`bind_to_person`); background work, API keys and visitors
reach nobody's.
"""

import hashlib
from collections.abc import Iterable
from dataclasses import replace
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.model_resolver import ResolvedCredential, get_provider
from app.clients.subscription_gateway import (
    GatewayAccount,
    GatewayProvider,
    LoginStarted,
    LoginStatus,
    SelectedAccountModel,
    SubscriptionGateway,
    configured_gateway,
)
from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, ConfigurationError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.repositories import member as member_repo
from app.services.background_jobs import enqueue
from app.services.personal_model_key import personal_connection_owner
from app.subscription_gateway.contracts import AccountUsage
from app.worker.jobs import WIPE_SUBSCRIPTION_ACCOUNTS, WipeSubscriptionAccounts


def gateway_scope(organization_id: UUID, user_id: UUID, membership_id: UUID | None = None) -> str:
    """An opaque membership scope; no generation names only pre-generation cleanup."""
    identity = f"agenticos:{organization_id}:{user_id}"
    if membership_id is not None:
        identity += f":{membership_id}"
    return hashlib.sha256(identity.encode()).hexdigest()


async def _member_scope(db: AsyncSession, organization_id: UUID, user_id: UUID) -> str:
    # Serialize account operations with membership departure until the caller commits.
    member = await member_repo.get(
        db, organization_id=organization_id, user_id=user_id, for_update=True
    )
    if member is None:
        raise AuthorizationError(
            message="An active membership is required for subscription accounts"
        )
    return gateway_scope(organization_id, user_id, member.id)


def _gateway() -> SubscriptionGateway:
    gateway = configured_gateway()
    if gateway is None:
        raise ConfigurationError(
            message="Subscription accounts are off on this deployment: set "
            "SUBSCRIPTION_GATEWAY_URL and SUBSCRIPTION_GATEWAY_TOKEN"
        )
    return gateway


async def bind_to_person(
    db: AsyncSession, credential: ResolvedCredential, organization_id: UUID, user_id: UUID
) -> ResolvedCredential:
    """Point a subscription-accounts credential at this person's own scope.

    Every other credential is returned as it is.
    """
    if not get_provider(credential.provider).personal_gateway:
        return credential
    gateway = _gateway()
    scope = await _member_scope(db, organization_id, user_id)
    return replace(
        credential,
        secret=ApiKeySecret(api_key=SecretStr(gateway.token)),
        base_url=gateway.model_endpoint(scope),
        routing={**credential.routing, "gateway_scope": scope},
    )


async def _queue(db: AsyncSession, scopes: list[str], organization_id: UUID | None) -> None:
    if scopes:
        await enqueue(
            db,
            WIPE_SUBSCRIPTION_ACCOUNTS,
            WipeSubscriptionAccounts(scopes=sorted(scopes)),
            organization_id=organization_id,
        )


async def queue_wipe(db: AsyncSession, organization_id: UUID, user_ids: Iterable[UUID]) -> None:
    """Delete these people's sign-ins in this organization, durably, once `db` commits."""
    scopes: set[str] = set()
    for user_id in user_ids:
        # Retire pre-generation directories too; new connections never use those paths.
        scopes.add(gateway_scope(organization_id, user_id))
        member = await member_repo.get(db, organization_id=organization_id, user_id=user_id)
        if member is not None:
            scopes.add(gateway_scope(organization_id, user_id, member.id))
    await _queue(db, list(scopes), organization_id)


async def queue_organization_wipe(db: AsyncSession, organization_id: UUID) -> None:
    """Delete every member's sign-ins in an organization that is going away."""
    await queue_wipe(
        db, organization_id, await member_repo.list_user_ids(db, organization_id=organization_id)
    )


async def queue_wipe_person(db: AsyncSession, user_id: UUID) -> None:
    """Delete one person's sign-ins in every organization, when their account goes.

    Reads the memberships, so call it before they cascade away with the user.
    """
    organization_ids = await member_repo.list_organization_ids(db, user_id=user_id)
    for organization_id in organization_ids:
        await queue_wipe(db, organization_id, [user_id])


async def wipe_scopes(job: WipeSubscriptionAccounts) -> None:
    """The job `queue_wipe` queues; a gateway that is down makes it retry."""
    gateway = _gateway()
    for scope in job.scopes:
        await gateway.wipe(scope)


class SubscriptionAccountService:
    """The caller's own accounts; nobody else's can be named."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _scope(self, ctx: AuthContext) -> str:
        return await _member_scope(self.db, ctx.organization_id, personal_connection_owner(ctx))

    async def accounts(self, ctx: AuthContext) -> list[GatewayAccount]:
        return await _gateway().accounts(await self._scope(ctx))

    async def models(self, ctx: AuthContext) -> list[str]:
        return await _gateway().models(await self._scope(ctx))

    async def account_usage(self, ctx: AuthContext, name: str) -> AccountUsage:
        """Read limits only for an account in the caller's own scope."""
        return await _gateway().account_usage(await self._scope(ctx), name)

    async def account_models(self, ctx: AuthContext, name: str) -> list[str]:
        """Models advertised by this account in the caller's own gateway scope."""
        return await _gateway().account_models(await self._scope(ctx), name)

    async def select_account_model(
        self, ctx: AuthContext, name: str, model: str
    ) -> SelectedAccountModel:
        """Pin a model to an account owned by this caller; never select another person's account."""
        return await _gateway().select_account_model(await self._scope(ctx), name, model)

    async def start_login(self, ctx: AuthContext, provider: GatewayProvider) -> LoginStarted:
        started = await _gateway().start_login(await self._scope(ctx), provider)
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action="subscription_account.sign_in_started",
            target_type="subscription_account",
            details={"provider": provider},
        )
        return started

    async def login_status(self, ctx: AuthContext, state: str) -> LoginStatus:
        return await _gateway().login_status(await self._scope(ctx), state)

    async def complete_login(self, ctx: AuthContext, state: str, redirect_url: str) -> None:
        if not redirect_url.startswith(("http://", "https://")):
            raise BadRequestError(message="Paste the whole address your browser ended on")
        await _gateway().complete_login(await self._scope(ctx), state, redirect_url)

    async def cancel_login(self, ctx: AuthContext, state: str) -> None:
        await _gateway().cancel_login(await self._scope(ctx), state)

    async def remove(self, ctx: AuthContext, name: str) -> None:
        await _gateway().remove_account(await self._scope(ctx), name)
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action="subscription_account.removed",
            target_type="subscription_account",
            target_id=name,
        )
