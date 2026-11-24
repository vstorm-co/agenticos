"""Credential-derived state never reaches the ordinary saved-session reader."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.deps import AgentDeps
from app.core.browser_continuation import BrowserContinuationReason, BrowserContinuationRefused
from app.core.browser_origins import browser_origin
from app.core.browser_session import MAX_SESSION_BYTES, ProtectedSignIn
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.core.secret_scopes import browser_sign_in_scope
from app.core.vault import seal, unseal
from app.db.models.browser_sign_in import BrowserSignIn
from app.db.session import get_db_context
from app.repositories import browser_credential as plans
from app.repositories import browser_sign_in as repo
from app.services.access import member_context

from . import _access
from ._lease import LiveBrowserIdentity


async def remember_protected(db: AsyncSession, state: ProtectedSignIn) -> BrowserSignIn:
    """Caller holds current secret/run authority; save and receipt commit together."""
    origin = state.provenance.origin
    site = urlsplit(origin).hostname
    assert site is not None
    sealed = seal(
        state.model_dump_json(),
        scope=browser_sign_in_scope(
            organization_id=state.provenance.organization_id,
            user_id=state.provenance.user_id,
            protection_kind="credential",
        ),
    )
    return await repo.save(
        db,
        organization_id=state.provenance.organization_id,
        user_id=state.provenance.user_id,
        site=site,
        sealed_state=sealed.ciphertext,
        key_version=sealed.key_version,
        protection_kind="credential",
    )


async def load_protected(
    db: AsyncSession, ctx: AuthContext, identity: LiveBrowserIdentity, origin: str
) -> ProtectedSignIn | None:
    """Retain this transaction through restore; current generation and forget are fenced."""
    origin = browser_origin(origin)
    site = urlsplit(origin).hostname
    assert site is not None
    await plans.lock_run(db, identity.organization_id, identity.run_id)
    row = await repo.protected_for_site(
        db, organization_id=identity.organization_id, user_id=identity.user_id, site=site
    )
    if row is None:
        return None
    ciphertext = row.sealed_state
    try:
        current, _ = await _access.private_run(db, ctx, identity)
        plaintext = unseal(
            ciphertext,
            key_version=row.secret_key_version,
            scope=browser_sign_in_scope(
                organization_id=identity.organization_id,
                user_id=identity.user_id,
                protection_kind="credential",
            ),
        )
        if len(plaintext.encode("utf-8")) > MAX_SESSION_BYTES + 16_384:
            raise BrowserContinuationRefused(BrowserContinuationReason.STATE_REFUSED)
        state = ProtectedSignIn.model_validate_json(plaintext)
        provenance = state.provenance
        if (
            provenance.organization_id != identity.organization_id
            or provenance.user_id != identity.user_id
            or provenance.agent_id != identity.agent_id
            or provenance.origin != origin
            or provenance.secret_id not in identity.credential_ids
            or provenance.expires_at <= datetime.now(UTC)
        ):
            raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED)
        for contributor in provenance.credential_generations:
            if contributor.secret_id not in identity.credential_ids:
                raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED)
            secret = await _access.credential(
                db,
                current,
                secret_id=contributor.secret_id,
                agent_id=identity.agent_id,
                generation=contributor.authorization_generation,
                locked=True,
            )
            if origin not in _access.open_value(secret).allowed_origins:
                raise BrowserContinuationRefused(BrowserContinuationReason.DESTINATION_REFUSED)
        await _access.private_run(db, current, identity)
        # Lock order is run -> secret -> saved row, matching the save transaction.
        locked = await repo.get(
            db,
            row.id,
            organization_id=identity.organization_id,
            user_id=identity.user_id,
            locked=True,
        )
        if (
            locked is None
            or locked.protection_kind != "credential"
            or locked.sealed_state != ciphertext
        ):
            raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED)
        await repo.mark_used(db, [row.id])
    except ValidationError, BadRequestError:
        raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED) from None
    return state


@asynccontextmanager
async def protected_restore(
    deps: AgentDeps, credential_ids: tuple[UUID, ...], tab_id: str, call_id: str, origin: str
) -> AsyncGenerator[ProtectedSignIn | None]:
    """A trusted run's narrow restore boundary, retaining all source locks through I/O."""
    audience = deps.audience
    if (
        not credential_ids
        or deps.organization_id is None
        or deps.run_id is None
        or deps.agent_id is None
        or deps.impersonated
        or deps.delegated
        or audience is None
        or not audience.browses_signed_in
        or audience.shared_transcript
        or audience.user_id is None
        or deps.run_person != audience.user_id
        or deps.user_id != str(audience.user_id)
    ):
        yield None
        return
    identity = LiveBrowserIdentity(
        organization_id=deps.organization_id,
        run_id=deps.run_id,
        agent_id=deps.agent_id,
        user_id=audience.user_id,
        tab_id=tab_id,
        call_id=call_id,
        controller_id=uuid4(),
        credential_ids=credential_ids,
    )
    async with get_db_context() as db:
        current = await member_context(
            db, organization_id=identity.organization_id, user_id=identity.user_id
        )
        if current is None:
            raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED)
        state = await load_protected(db, current, identity, origin)
        yield state
        if state is not None and await load_protected(db, current, identity, origin) != state:
            raise BrowserContinuationRefused(BrowserContinuationReason.AUTHORITY_CHANGED)
