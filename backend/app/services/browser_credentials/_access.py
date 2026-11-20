"""Recheck the person, private run, published binding and exact credential on every use."""

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.audit import current_impersonator
from app.core.browser_fill import BrowserFillReason, BrowserFillRefused
from app.core.config import settings
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import (
    BROWSER_SECRET_KINDS,
    BrowserLoginSecret,
    BrowserProfileSecret,
    BrowserSecret,
    SecretKind,
    unseal_kind,
)
from app.core.secret_scopes import organization_secret_scope
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.organization_secret import OrganizationSecret
from app.repositories import agent as agent_repo
from app.repositories import agent_run as run_repo
from app.repositories import browser_credential as repo
from app.repositories import member as member_repo
from app.services.access import AGENT, SECRET, member_context, resolve_access

from ._lease import LiveBrowserIdentity


def enabled(organization_id: UUID, user_id: UUID) -> None:
    if (
        not settings.BROWSER_CREDENTIAL_FILL_ENABLED
        or organization_id not in settings.BROWSER_CREDENTIAL_ORGANIZATION_IDS
        or (
            settings.BROWSER_CREDENTIAL_USER_IDS
            and user_id not in settings.BROWSER_CREDENTIAL_USER_IDS
        )
    ):
        raise BrowserFillRefused(BrowserFillReason.DISABLED)


async def person(db: AsyncSession, ctx: AuthContext) -> AuthContext:
    user_id = ctx.personal_user_id
    if user_id is None or current_impersonator() is not None:
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    current = await member_context(db, organization_id=ctx.organization_id, user_id=user_id)
    if current is None:
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    return current


def configured_ids(raw: object) -> tuple[UUID, ...]:
    """Browser credential references are independent of generic secret bindings."""
    # Import only after the capability registry has loaded: the browser controller
    # uses this service while its own capability package is being constructed.
    from app.agents.capabilities.browser_use import WebBrowserConfig

    if raw is None:
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    try:
        spec = AgentSpec.model_validate(raw)
        binding = next(
            item for item in spec.capabilities if item.id == "browser_use" and item.enabled
        )
        config = WebBrowserConfig.model_validate(binding.config)
    except ValidationError, StopIteration:
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE) from None
    if (
        config.connection != "built_in"
        or not settings.BROWSER_SIGN_IN_CDP_URL
        or config.cdp_url.rstrip("/") != settings.BROWSER_SIGN_IN_CDP_URL.rstrip("/")
    ):
        raise BrowserFillRefused(BrowserFillReason.LIVE_BROWSER_REQUIRED)
    return tuple(config.browser_credential_ids)


async def bound_ids(db: AsyncSession, run: AgentRun) -> tuple[UUID, ...]:
    """The exact executed version; a later draft cannot add authority to this run."""
    raw = run.test_spec
    if raw is None and run.agent_version_id is not None:
        version = await agent_repo.get_version(
            db, run.agent_version_id, organization_id=run.organization_id
        )
        if version is not None and version.agent_id == run.agent_id:
            raw = version.spec
    return configured_ids(raw)


async def private_run(
    db: AsyncSession, ctx: AuthContext, identity: LiveBrowserIdentity
) -> tuple[AuthContext, AgentRun]:
    current = await person(db, ctx)
    if current.user_id != identity.user_id or current.organization_id != identity.organization_id:
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    enabled(identity.organization_id, identity.user_id)
    run = await run_repo.get_run(db, identity.run_id, organization_id=identity.organization_id)
    if (
        run is None
        or run.status != RunStatus.RUNNING.value
        or run.user_id != identity.user_id
        or run.agent_id != identity.agent_id
        or run.surface != RunSurface.WEB.value
        or run.initiated_by_publisher_fallback
        or run.key_scopes is not None
        or run.parent_run_id is not None
        or run.trigger_id is not None
        or run.routine_origin_id is not None
        or run.system_role is not None
        or run.conversation_id is None
        or not await repo.private_conversation(
            db, identity.organization_id, run.conversation_id, identity.user_id
        )
    ):
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    agent = await agent_repo.get(db, run.agent_id, organization_id=identity.organization_id)
    if (
        agent is None
        or agent.status == "archived"
        or not await resolve_access(db, current, agent, Perm.AGENTS_RUN, resource_type=AGENT)
        or tuple(await bound_ids(db, run)) != identity.credential_ids
    ):
        raise BrowserFillRefused(BrowserFillReason.AUTHORITY_CHANGED)
    # Removing a published binding also revokes an already-running older version.
    # The current version can only subtract; it cannot add to the frozen authority.
    current_spec = agent.draft_spec if run.test_spec is not None else None
    if run.test_spec is None and agent.current_version_id is not None:
        version = await agent_repo.get_version(
            db, agent.current_version_id, organization_id=identity.organization_id
        )
        if version is not None and version.agent_id == agent.id:
            current_spec = version.spec
    if not set(identity.credential_ids) <= set(configured_ids(current_spec)):
        raise BrowserFillRefused(BrowserFillReason.AUTHORITY_CHANGED)
    for contributor in identity.inherited_credentials:
        if contributor.secret_id not in identity.credential_ids:
            raise BrowserFillRefused(BrowserFillReason.AUTHORITY_CHANGED)
        await credential(
            db,
            current,
            secret_id=contributor.secret_id,
            agent_id=identity.agent_id,
            generation=contributor.authorization_generation,
        )
    return current, run


async def credential(
    db: AsyncSession,
    ctx: AuthContext,
    *,
    secret_id: UUID,
    agent_id: UUID,
    generation: UUID | None = None,
    locked: bool = False,
) -> OrganizationSecret:
    row = await repo.secret(db, ctx.organization_id, secret_id, locked=locked)
    if (
        row is None
        or row.kind not in BROWSER_SECRET_KINDS
        or row.owner_user_id is None
        or row.visibility != "private"
        or (generation is not None and row.authorization_generation != generation)
    ):
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    user_id = ctx.personal_user_id
    if user_id is None:
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    if row.usage_scope == "personal":
        if row.owner_user_id != user_id or not await resolve_access(
            db, ctx, row, Perm.SECRETS_VIEW, resource_type=SECRET
        ):
            raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    elif row.usage_scope == "organization":
        if (
            not settings.BROWSER_CREDENTIAL_SHARED_ENABLED
            or await member_repo.get_active(
                db, organization_id=ctx.organization_id, user_id=row.owner_user_id
            )
            is None
            or not await repo.granted(db, ctx.organization_id, row.id, agent_id, user_id)
        ):
            raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    else:
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    if row.kind == SecretKind.BROWSER_PROFILE and not settings.BROWSER_CREDENTIAL_PROFILE_ENABLED:
        raise BrowserFillRefused(BrowserFillReason.DISABLED)
    return row


def open_value(row: OrganizationSecret) -> BrowserSecret:
    if row.kind not in BROWSER_SECRET_KINDS:
        raise BrowserFillRefused(BrowserFillReason.NOT_AVAILABLE)
    model = BrowserLoginSecret if row.kind == SecretKind.BROWSER_LOGIN else BrowserProfileSecret
    return unseal_kind(
        row.sealed_secret,
        model=model,
        scope=organization_secret_scope(
            organization_id=row.organization_id,
            kind=row.kind,
            usage_scope=row.usage_scope,
            owner_user_id=row.owner_user_id,
        ),
        key_version=row.key_version,
    )
