"""A person's own subscription accounts, signed in through the bundled gateway.

Each person in each organization has one gateway scope: its own CLIProxyAPI
process, sign-ins and keys (`app.subscription_gateway`). The scope is a digest of
the organization and the person, derived here and nowhere else, so a browser
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
    SubscriptionGateway,
    configured_gateway,
)
from app.core.audit import record_audit
from app.core.exceptions import BadRequestError, ConfigurationError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.repositories import member as member_repo
from app.services.background_jobs import enqueue
from app.services.personal_model_key import personal_connection_owner
from app.worker.jobs import WIPE_SUBSCRIPTION_ACCOUNTS, WipeSubscriptionAccounts


def gateway_scope(organization_id: UUID, user_id: UUID) -> str:
    """The person's scope in this organization: stable, opaque, never shared."""
    return hashlib.sha256(f"agenticos:{organization_id}:{user_id}".encode()).hexdigest()


def _gateway() -> SubscriptionGateway:
    gateway = configured_gateway()
    if gateway is None:
        raise ConfigurationError(
            message="Subscription accounts are off on this deployment: set "
            "SUBSCRIPTION_GATEWAY_URL and SUBSCRIPTION_GATEWAY_TOKEN"
        )
    return gateway


def bind_to_person(
    credential: ResolvedCredential, organization_id: UUID, user_id: UUID
) -> ResolvedCredential:
    """Point a subscription-accounts credential at this person's own scope.

    Every other credential is returned as it is.
    """
    if not get_provider(credential.provider).personal_gateway:
        return credential
    gateway = _gateway()
    scope = gateway_scope(organization_id, user_id)
    return replace(
        credential,
        secret=ApiKeySecret(api_key=SecretStr(gateway.token)),
        base_url=gateway.model_endpoint(scope),
        routing={**credential.routing, "gateway_scope": scope},
    )


async def _queue(db: AsyncSession, scopes: list[str], organization_id: UUID | None) -> None:
    if scopes and configured_gateway() is not None:
        await enqueue(
            db,
            WIPE_SUBSCRIPTION_ACCOUNTS,
            WipeSubscriptionAccounts(scopes=sorted(scopes)),
            organization_id=organization_id,
        )


async def queue_wipe(db: AsyncSession, organization_id: UUID, user_ids: Iterable[UUID]) -> None:
    """Delete these people's sign-ins in this organization, durably, once `db` commits."""
    await _queue(
        db, [gateway_scope(organization_id, user_id) for user_id in user_ids], organization_id
    )


async def queue_organization_wipe(db: AsyncSession, organization_id: UUID) -> None:
    """Delete every member's sign-ins in an organization that is going away."""
    if configured_gateway() is None:
        return
    await queue_wipe(
        db, organization_id, await member_repo.list_user_ids(db, organization_id=organization_id)
    )


async def queue_wipe_person(db: AsyncSession, user_id: UUID) -> None:
    """Delete one person's sign-ins in every organization, when their account goes.

    Reads the memberships, so call it before they cascade away with the user.
    """
    if configured_gateway() is None:
        return
    organization_ids = await member_repo.list_organization_ids(db, user_id=user_id)
    await _queue(
        db, [gateway_scope(organization_id, user_id) for organization_id in organization_ids], None
    )


async def wipe_scopes(job: WipeSubscriptionAccounts) -> None:
    """The job `queue_wipe` queues; a gateway that is down makes it retry."""
    gateway = configured_gateway()
    if gateway is None:
        return
    for scope in job.scopes:
        await gateway.wipe(scope)


class SubscriptionAccountService:
    """The caller's own accounts; nobody else's can be named."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def _scope(self, ctx: AuthContext) -> str:
        return gateway_scope(ctx.organization_id, personal_connection_owner(ctx))

    async def accounts(self, ctx: AuthContext) -> list[GatewayAccount]:
        return await _gateway().accounts(self._scope(ctx))

    async def models(self, ctx: AuthContext) -> list[str]:
        return await _gateway().models(self._scope(ctx))

    async def start_login(self, ctx: AuthContext, provider: GatewayProvider) -> LoginStarted:
        started = await _gateway().start_login(self._scope(ctx), provider)
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
        return await _gateway().login_status(self._scope(ctx), state)

    async def complete_login(self, ctx: AuthContext, state: str, redirect_url: str) -> None:
        if not redirect_url.startswith(("http://", "https://")):
            raise BadRequestError(message="Paste the whole address your browser ended on")
        await _gateway().complete_login(self._scope(ctx), state, redirect_url)

    async def cancel_login(self, ctx: AuthContext, state: str) -> None:
        await _gateway().cancel_login(self._scope(ctx), state)

    async def remove(self, ctx: AuthContext, name: str) -> None:
        await _gateway().remove_account(self._scope(ctx), name)
        await record_audit(
            self.db,
            actor_user_id=ctx.user_id,
            organization_id=ctx.organization_id,
            action="subscription_account.removed",
            target_type="subscription_account",
            target_id=name,
        )
