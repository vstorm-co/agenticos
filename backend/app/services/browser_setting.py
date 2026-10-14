"""An organization's browser setting: built in, through a proxy, or a hosted browser (#2130).

A deployment's own address is the one sites block first, and a headless browser
next to the API is the one they recognise. So an organization can send its
browses through a proxy of its own - a residential or regional address - or run
them in a hosted browser it pays for, reached over CDP, with the credential in
the vault and the address checked the way every other address a tenant types is.

**Addresses inside the deployment's network are refused** unless the operator
named the host in `BROWSER_CDP_ALLOWED_HOSTS`: the browser dials a proxy, and the
API dials a hosted browser, so an address a tenant typed must not reach the
database or the cloud's metadata service. A name is checked when it is saved and
again when a browse starts - the second check is what stops a name that has been
pointed somewhere private since.
"""

from __future__ import annotations

import logging
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from uuid import UUID
from zoneinfo import available_timezones

import anyio
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.browser_use._route import BrowserRoute
from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.core.sanitize import UrlRefusedError, resolve_pinned_url
from app.core.secret_kinds import ApiKeySecret, SecretKind
from app.repositories import browser_setting as browser_setting_repo
from app.repositories import organization_secret as organization_secret_repo
from app.schemas.browser_setting import BrowserMode, BrowserSettingRead, BrowserSettingUpdate
from app.services.notifications import NotificationService
from app.services.organization_secret import OrganizationSecretService

logger = logging.getLogger(__name__)

PROXY_SCHEMES = frozenset({"http", "https", "socks5"})
REMOTE_SCHEMES = frozenset({"wss"})
"""A hosted browser is reached over TLS, where its key travels in the query."""
_VETTED_ONLY_SCHEMES = frozenset({"ws", "http", "https"})
"""Any other CDP address, allowed only at a host the operator named."""


def _vetted(host: str) -> bool:
    """Whether the operator named this host as one a browser may be reached at."""
    return host.lower() in {name.strip().lower() for name in settings.BROWSER_CDP_ALLOWED_HOSTS}


async def check_address(url: str, *, field: str, schemes: frozenset[str]) -> None:
    """Refuse an address with credentials in it, without a port, or inside the network.

    Raises:
        BadRequestError: Naming `field`, with the reason in a sentence.
    """
    parts = urlsplit(url)
    vetted = bool(parts.hostname) and _vetted(parts.hostname or "")
    allowed = schemes | (_VETTED_ONLY_SCHEMES if vetted and field == "remote_url" else frozenset())
    if parts.scheme not in allowed or not parts.hostname:
        raise refused_field(field, f"Use a {', '.join(sorted(allowed))} address with a host")
    if parts.username or parts.password:
        raise refused_field(
            field, "Keep the credentials out of the address; pick them from the vault"
        )
    try:
        port = parts.port
    except ValueError as exc:
        raise refused_field(field, "The port is not a number") from exc
    if field == "proxy_url" and port is None:
        raise refused_field(field, "A proxy address needs its port")
    if vetted:
        return
    # Resolved off the event loop: it blocks on DNS. The schemes are the address's
    # own, because the check is about where it points rather than what it speaks.
    try:
        await anyio.to_thread.run_sync(
            lambda: resolve_pinned_url(url, allowed_schemes=frozenset({parts.scheme}))
        )
    except UrlRefusedError as exc:
        raise refused_field(field, str(exc)) from exc


def _remote_with_key(remote_url: str, key_param: str, key: str | None) -> str:
    """The hosted browser's address with its key in the query, where it reads it."""
    if key is None:
        return remote_url
    parts = urlsplit(remote_url)
    query = "&".join(q for q in (parts.query, urlencode({key_param: key}, quote_via=quote)) if q)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


class BrowserSettingService:
    """Read, write and resolve how an organization's browses run."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.secrets = OrganizationSecretService(db)

    async def get(self, ctx: AuthContext) -> BrowserSettingRead:
        """The setting, or the default for an organization that never changed it."""
        row = await browser_setting_repo.get(self.db, organization_id=ctx.organization_id)
        if row is None:
            return BrowserSettingRead()
        return BrowserSettingRead.model_validate(row)

    async def update(self, ctx: AuthContext, data: BrowserSettingUpdate) -> BrowserSettingRead:
        """Write the whole setting.

        The fields of the mode not chosen are kept, so switching back does not lose
        what was typed; only the chosen mode's are required and checked.

        Raises:
            BadRequestError: A required field is missing, an address is refused,
                the time zone is unknown, or the credential is not an API key of
                this organization's.
        """
        if data.mode is BrowserMode.PROXY:
            if not data.proxy_url:
                raise refused_field("proxy_url", "Say which proxy the browser goes through")
            await check_address(data.proxy_url, field="proxy_url", schemes=PROXY_SCHEMES)
            if data.secret_id is not None and urlsplit(data.proxy_url).scheme == "socks5":
                # Chromium has no way to sign in to a SOCKS proxy: the browse would
                # fail on its first request, inside somebody's conversation.
                raise refused_field(
                    "secret_id",
                    "Chromium cannot sign in to a SOCKS proxy; use an HTTP proxy for one "
                    "that needs a password",
                )
        if data.mode is BrowserMode.REMOTE:
            if not data.remote_url:
                raise refused_field("remote_url", "Say where the hosted browser is")
            await check_address(data.remote_url, field="remote_url", schemes=REMOTE_SCHEMES)
        if data.timezone and data.timezone not in available_timezones():
            raise refused_field("timezone", "Use an IANA time zone, such as Europe/Warsaw")
        if data.secret_id is not None:
            secret = await organization_secret_repo.get(
                self.db, data.secret_id, organization_id=ctx.organization_id
            )
            if secret is None or secret.kind != SecretKind.API_KEY.value:
                raise refused_field("secret_id", "Pick an API key from this organization's vault")

        row = await browser_setting_repo.save(
            self.db, organization_id=ctx.organization_id, values=data.model_dump()
        )
        notifications = NotificationService(self.db)
        # Before the audit entry, never after it: `record_audit` holds the chain
        # lock to the end of the transaction (#1763).
        audience = await notifications.hold_security_audience(ctx.organization_id)
        entry = await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="browser_setting.updated",
            target_type="browser_setting",
            target_id=str(ctx.organization_id),
            # Where the traffic goes is the point of recording this; the credential
            # is a reference and is not named.
            details={
                "mode": row.mode,
                "proxy_host": urlsplit(row.proxy_url or "").hostname,
                "remote_host": urlsplit(row.remote_url or "").hostname,
            },
        )
        await notifications.security_event(entry, recipients=audience)
        return BrowserSettingRead.model_validate(row)

    async def resolve(self, ctx: AuthContext) -> BrowserRoute | None:
        """How this run's browses go out, for the runner to hand the capability.

        `None` for the default with nothing to say about where the browser is.
        The address is checked again here: a name that pointed outside when it
        was saved may point inside now.

        Raises:
            BadRequestError: The address is refused now, or the hosted browser's
                credential was removed from the vault - a browse that went out
                some other way would not be the one the organization chose.
        """
        row = await browser_setting_repo.get(self.db, organization_id=ctx.organization_id)
        if row is None:
            return None
        mode = BrowserMode(row.mode)
        if mode is BrowserMode.BUILT_IN and not (row.timezone or row.locale):
            return None
        secret = await self._credential(ctx, row.secret_id)
        if mode is BrowserMode.PROXY and row.proxy_url:
            await check_address(row.proxy_url, field="proxy_url", schemes=PROXY_SCHEMES)
            username, _, password = (secret or "").partition(":")
            return BrowserRoute(
                proxy_server=row.proxy_url,
                proxy_username=username or None,
                proxy_password=SecretStr(password) if password else None,
                timezone=row.timezone,
                locale=row.locale,
            )
        if mode is BrowserMode.REMOTE and row.remote_url:
            await check_address(row.remote_url, field="remote_url", schemes=REMOTE_SCHEMES)
            if row.secret_id is not None and secret is None:
                raise BadRequestError(
                    message=(
                        "The hosted browser's key was removed from the vault, so this "
                        "organization's browses cannot start. Pick one in Web browser settings."
                    ),
                    details={"secret_id": str(row.secret_id)},
                )
            url = _remote_with_key(row.remote_url, row.remote_key_param, secret)
            return BrowserRoute(remote_url=SecretStr(url), timezone=row.timezone, locale=row.locale)
        return BrowserRoute(timezone=row.timezone, locale=row.locale)

    async def _credential(self, ctx: AuthContext, secret_id: UUID | None) -> str | None:
        """The vault entry's value, or `None` where there is none or it is gone."""
        if secret_id is None:
            return None
        resolved = (await self.secrets.resolve_for_bindings(ctx, [secret_id])).get(secret_id)
        if not isinstance(resolved, ApiKeySecret):
            return None
        return resolved.api_key.get_secret_value()
