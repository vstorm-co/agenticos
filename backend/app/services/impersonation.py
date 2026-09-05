"""An administrator acting as another account, as a session that can be ended.

`POST /admin/users/{id}/impersonate` used to answer with a bare one-hour access
token. It carried the administrator as an `act` claim, so the audit trail could
say who was really acting (#943) - but nothing recorded that the token existed,
so nothing could take it back: the target changing their password, the
administrator closing the tab, an operator who wanted it gone. It was the one
credential on the platform that outlived every control the platform has.

An impersonation is now a **row in `sessions`** under the target's id, with
`impersonator_user_id` naming the administrator, and its access token names
that row in a `sid` claim. Three consequences, each of them the point:

- **It ends when the row does.** The auth dependency calls :meth:`verify` on
  every request carrying `act`, and refuses the token the moment the row is
  gone, deactivated or past `expires_at`. So `DELETE /sessions`, a password
  reset, the administrator's own *End impersonation* and a deleted
  administrator (the column cascades) all end it at once, through the machinery
  every other session already had. A token minted before this module - `act`
  with no `sid` - is refused outright, because it is exactly the credential
  this replaces.
- **Nothing extends it.** There is no refresh token: the window is the access
  token's own lifetime, and `SessionService.validate_refresh_token` declines an
  impersonation row, so the access token cannot be posted back as a refresh
  token to mint a plain week-long session as the target.
- **The credential never reaches a clipboard.** The token is returned to the
  BFF, which puts it in the same HttpOnly cookie every other access token lives
  in; the browser's JavaScript never sees it.

Whether the person is *told* is the deployment's policy - `notify_impersonated_users`
on the settings row, off by default - and the email goes out after the commit,
so a start that failed to record itself notifies nobody. Both ends of an
impersonation are audited: `admin.user.impersonate` when it starts, with the
session id and the expiry, and `admin.user.impersonation_ended` when the
administrator ends it. An expiry writes nothing, because nobody acted.
"""

from __future__ import annotations

import logging
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator, record_audit, set_impersonator
from app.core.background import spawn_after_commit
from app.core.exceptions import AuthenticationError, BadRequestError
from app.core.security import create_access_token
from app.db.models.user import User
from app.repositories import session_repo
from app.schemas.user import ImpersonateResponse, ImpersonationRead, ImpersonatorRead
from app.services.deployment_settings import DeploymentSettingsService
from app.services.email.service import EmailKey, get_email_service
from app.services.session import SessionService, hash_token
from app.services.user import UserService

logger = logging.getLogger(__name__)

WINDOW = timedelta(hours=1)
"""How long an impersonation may last before it ends on its own.

An hour, as before. Long enough to reproduce what a customer reported and short
enough that a tab left open is not an account left open; the administrator ends
it sooner from the banner, and starts another one if an hour was not enough.
"""


@dataclass(frozen=True, slots=True)
class ActiveImpersonation:
    """The impersonation the current request is running under.

    Set by :meth:`ImpersonationService.verify` from the token and the row it
    names, read by `/auth/me` to draw the banner and by :meth:`end` to know which
    row to close. A request that is nobody acting as anybody has none.
    """

    session_id: UUID
    user_id: UUID
    impersonator_id: UUID
    expires_at: datetime


_active: ContextVar[ActiveImpersonation | None] = ContextVar("active_impersonation", default=None)


def current_impersonation() -> ActiveImpersonation | None:
    """The impersonation this request runs under, or None for an ordinary request."""
    return _active.get()


def _uuid_claim(payload: dict[str, Any], name: str) -> UUID | None:
    """A claim read as a uuid, or None when it is absent or not one.

    A malformed claim is no claim rather than a refusal: the token is signed by
    this deployment, so a claim it cannot parse is one this code never wrote,
    and the request stays attributable to its subject (#943).
    """
    value = payload.get(name)
    if not value:
        return None
    try:
        return UUID(str(value))
    except ValueError:
        return None


def impersonator_from(payload: dict[str, Any]) -> UUID | None:
    """The administrator behind an impersonated token, or None for an ordinary one."""
    return _uuid_claim(payload, "act")


class ImpersonationService:
    """Start, verify, describe and end an administrator's access to another account."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def start(
        self,
        *,
        admin: User,
        target_id: UUID,
        ip_address: str | None,
        user_agent: str | None,
    ) -> ImpersonateResponse:
        """Open an impersonation of `target_id` and mint the token that is it.

        The row's id is decided here, before either exists: the token has to name
        the row in `sid` and the row has to hold the token's hash, so one of them
        is chosen first and an id is the cheaper one to choose. If this request is
        itself impersonated - one app admin acting as another, who impersonates a
        third - the row and the claim keep naming the human who started the chain
        rather than the account one hop up it (#943).

        Raises:
            NotFoundError: For a target that does not exist.
            BadRequestError: For acting as yourself, which is nobody acting as
                anybody, or as a suspended account, which every request would
                refuse anyway - a credential that cannot be used is a confusing
                artifact rather than a feature.
        """
        target = await UserService(self.db).get_by_id(target_id)
        if target.id == admin.id:
            raise BadRequestError(message="You cannot impersonate yourself")
        if not target.is_active:
            raise BadRequestError(
                message="A suspended account cannot be impersonated",
                details={"user_id": target.id},
            )

        actor = current_impersonator() or admin.id
        session_id = uuid4()
        expires_at = datetime.now(UTC) + WINDOW
        token = create_access_token(
            subject=str(target.id),
            expires_delta=WINDOW,
            act=str(actor),
            sid=str(session_id),
        )
        row = await SessionService(self.db).open_impersonation(
            session_id=session_id,
            target_id=target.id,
            impersonator_id=actor,
            access_token=token,
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await record_audit(
            self.db,
            actor_user_id=admin.id,
            action="admin.user.impersonate",
            target_type="user",
            target_id=str(target.id),
            details={
                "target_email": target.email,
                "session_id": str(row.id),
                "expires_at": row.expires_at.isoformat(),
            },
            ip_address=ip_address,
        )

        settings_service = DeploymentSettingsService(self.db)
        if await settings_service.notifies_impersonated_users():
            spawn_after_commit(
                self.db,
                _notify_target(
                    to=target.email,
                    name=target.full_name or target.email,
                    admin_email=admin.email,
                    app_name=await settings_service.effective_app_name(),
                ),
                name=f"impersonation_notice:{target.id}",
            )

        return ImpersonateResponse(
            access_token=token,
            token_type="bearer",
            impersonated_user_id=str(target.id),
            impersonated_by=str(admin.id),
            expires_in=int(WINDOW.total_seconds()),
            expires_at=row.expires_at,
            session_id=row.id,
        )

    async def verify(
        self, *, payload: dict[str, Any], token: str, subject: str
    ) -> ActiveImpersonation | None:
        """Bind an `act` token to the row it names, or refuse it.

        Called by the auth dependency on every request. An ordinary token - no
        `act` - clears the request's impersonation context and costs no query.
        An impersonated one is refused unless its `sid` names a row that is still
        active, not yet expired, held by the administrator the claim names, under
        the subject the token names, and minted for *this* token - the hash on the
        row is what stops a `sid` being carried onto a token it was not issued
        with, however the signature was obtained.

        Raises:
            AuthenticationError: For an `act` token with no `sid` (minted before
                impersonations were sessions, and exactly the unendable credential
                this replaces) and for one whose row has been ended.
        """
        impersonator = impersonator_from(payload)
        if impersonator is None:
            set_impersonator(None)
            _active.set(None)
            return None

        session_id = _uuid_claim(payload, "sid")
        if session_id is None:
            raise AuthenticationError(message="An impersonation without a session is not accepted")

        row = await session_repo.get_by_id(self.db, session_id)
        if (
            row is None
            or not row.is_active
            or row.expires_at <= datetime.now(UTC)
            or row.impersonator_user_id != impersonator
            or str(row.user_id) != subject
            or not secrets.compare_digest(row.refresh_token_hash, hash_token(token))
        ):
            raise AuthenticationError(message="Impersonation has ended")

        active = ActiveImpersonation(
            session_id=row.id,
            user_id=row.user_id,
            impersonator_id=impersonator,
            expires_at=row.expires_at,
        )
        set_impersonator(impersonator)
        _active.set(active)
        return active

    async def describe(self) -> ImpersonationRead | None:
        """What the banner needs: who is acting, and until when. None when nobody is."""
        active = _active.get()
        if active is None:
            return None
        admin = await UserService(self.db).get_by_id(active.impersonator_id)
        return ImpersonationRead(
            session_id=active.session_id,
            impersonator=ImpersonatorRead(
                id=admin.id, email=admin.email, full_name=admin.full_name
            ),
            expires_at=active.expires_at,
        )

    async def end(self, *, ip_address: str | None) -> None:
        """Close the impersonation this request runs under.

        The credential that *is* the impersonation is what ends it, which is why
        this takes no id: the administrator's browser holds nothing else at that
        moment, and a row id in the body would be a second thing to authorise.
        Recorded with the administrator as the actor - the same shape as the
        start - rather than as the target with an impersonator behind them.

        Raises:
            BadRequestError: When this request is nobody acting as anybody.
        """
        active = _active.get()
        if active is None:
            raise BadRequestError(message="This session is not an impersonation")
        await session_repo.deactivate(self.db, active.session_id)
        await record_audit(
            self.db,
            actor_user_id=active.impersonator_id,
            action="admin.user.impersonation_ended",
            target_type="user",
            target_id=str(active.user_id),
            details={"session_id": str(active.session_id)},
            ip_address=ip_address,
        )


async def _notify_target(*, to: str, name: str, admin_email: str, app_name: str) -> None:
    """Tell the person an administrator is acting as them. Reports its own failure."""
    try:
        await get_email_service().send(
            key=EmailKey.IMPERSONATION_NOTICE,
            to=to,
            context={"name": name, "admin_email": admin_email, "app_name": app_name},
        )
    except Exception:
        logger.exception("impersonation_notice_failed", extra={"to": to})
