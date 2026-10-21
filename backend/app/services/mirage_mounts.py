"""The folders of a virtual terminal, resolved for one run, credentials included (#2191).

A capability never reads the vault or the database, so the runner turns each mount
an agent's spec names into what the library is built with before the model is
called: the author's options, every secret unsealed, a connected account's grant, a
Graph token minted for an Entra app. Which secret and which account a folder
reaches is therefore the server's decision, made with the run's own authority.

A mount that cannot be built does not fail the run. It is left out, and the model
is told which folder is missing and why - a person whose agent mounts three
services should still get an answer from the two that work, and a terminal that
hides a missing folder leaves the model searching for it.

Hosts an author typed are checked here, at the moment they are dialled, against
`MIRAGE_ALLOWED_HOSTS` - including the ones inside a secret (a Postgres DSN), which
publish cannot read.
"""

import logging
import re
from collections.abc import Mapping, Sequence
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.mirage import (
    BackendInfo,
    MirageConfig,
    MirageMount,
    MountValue,
    OrganizationAccount,
    ResolvedMount,
    ResolvedTerminal,
    backend,
)
from app.core.config import settings
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, EntraAppSecret, StorableSecret
from app.db.models.mcp_connection import McpConnection
from app.repositories import mcp_connection_repo
from app.services.mcp_connection import AccountGrant, McpConnectionService
from app.services.organization_secret import OrganizationSecretService
from app.services.portals import google_oauth

logger = logging.getLogger(__name__)

_GOOGLE_SCOPES: Mapping[str, frozenset[str]] = {
    "gdrive": frozenset({google_oauth.DRIVE}),
    "gmail": frozenset({google_oauth.GMAIL}),
    "gcal": frozenset({google_oauth.CALENDAR}),
    "gdocs": frozenset({google_oauth.DOCS, google_oauth.DRIVE}),
    "gsheets": frozenset({google_oauth.SHEETS, google_oauth.DRIVE}),
    "gslides": frozenset({google_oauth.SLIDES, google_oauth.DRIVE}),
}
"""What each Google backend needs granted. Docs, Sheets and Slides list through Drive."""

_ENTRA_LOGIN = "https://login.microsoftonline.com"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
_TIMEOUT = httpx.Timeout(10.0)
_SLUG = re.compile(r"[^a-z0-9._-]+")


class _Unmountable(Exception):
    """A folder that cannot be built for this run, and the sentence that says why."""


class MirageMountService:
    """Resolves a terminal's mounts for one run."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.secrets = OrganizationSecretService(db)
        self.connections = McpConnectionService(db)

    async def resolve(
        self, ctx: AuthContext, config: MirageConfig, *, person_id: UUID | None
    ) -> ResolvedTerminal:
        """Every folder the spec names that can be built for this run.

        `person_id` is whoever the run answers - the message's author - for a
        mount that reads each person's own account; `None` where there is nobody
        (an API key, a schedule).
        """
        secret_ids = [secret_id for mount in config.mounts for secret_id in mount.secrets.values()]
        unsealed = await self.secrets.resolve_for_bindings(ctx, secret_ids) if secret_ids else {}
        mounts: list[ResolvedMount] = []
        notes: list[str] = []
        for mount in config.mounts:
            info = backend(mount.backend)
            if info is None or not info.available:
                notes.append(
                    f"{mount.path} is not mounted: this deployment cannot reach that service."
                )
                continue
            try:
                mounts.extend(await self._build(ctx, mount, info, unsealed, person_id))
            except _Unmountable as exc:
                notes.append(f"{mount.path} is not mounted: {exc}")
        return ResolvedTerminal(mounts=tuple(mounts), notes=tuple(notes))

    async def _build(
        self,
        ctx: AuthContext,
        mount: MirageMount,
        info: BackendInfo,
        unsealed: Mapping[UUID, StorableSecret],
        person_id: UUID | None,
    ) -> list[ResolvedMount]:
        options: dict[str, MountValue] = {
            key: _option(value) for key, value in mount.options.items()
        }
        if info.credential == "google":
            return await self._google(ctx, mount, info, options, person_id)
        if info.credential == "microsoft":
            app = unsealed.get(mount.secrets["app"])
            if not isinstance(app, EntraAppSecret):
                raise _Unmountable("its Entra app is no longer in the vault.")
            options["access_token"] = SecretStr(await _graph_token(app))
        elif info.credential == "fields":
            for field, secret_id in mount.secrets.items():
                secret = unsealed.get(secret_id)
                if not isinstance(secret, ApiKeySecret):
                    raise _Unmountable(f"its {field} secret is no longer in the vault.")
                options[field] = secret.api_key
        _check_hosts(info, options)
        return [_resolved(mount, info, options, info.title)]

    async def _google(
        self,
        ctx: AuthContext,
        mount: MirageMount,
        info: BackendInfo,
        options: dict[str, MountValue],
        person_id: UUID | None,
    ) -> list[ResolvedMount]:
        accounts = await self._accounts(ctx, mount, person_id)
        needed = _GOOGLE_SCOPES[info.name]
        resolved: list[ResolvedMount] = []
        for account in accounts:
            grant = await self.connections.account_grant(account)
            if grant is None:
                raise _Unmountable(f"{account.label or 'the account'} has to be connected again.")
            missing = needed - grant.scopes
            if missing:
                raise _Unmountable(
                    f"{grant.email} did not grant access to {info.title}; connect it again "
                    "and allow it."
                )
            path = mount.path if len(accounts) == 1 else f"{mount.path}{_slug(grant.email)}/"
            resolved.append(
                _resolved(
                    mount,
                    info,
                    {**options, **_google_credentials(grant)},
                    f"{info.title} of {grant.email}",
                    path=path,
                )
            )
        return resolved

    async def _accounts(
        self, ctx: AuthContext, mount: MirageMount, person_id: UUID | None
    ) -> Sequence[McpConnection]:
        if isinstance(mount.account, OrganizationAccount):
            account = await mcp_connection_repo.get_account(self.db, mount.account.connection_id)
            if account is None or account.organization_id != ctx.organization_id:
                raise _Unmountable("the organization's account it reads was disconnected.")
            return [account]
        if person_id is None:
            raise _Unmountable(
                "it reads each person's own account, and this run answers nobody who has one."
            )
        accounts = await mcp_connection_repo.list_accounts(
            self.db, provider=google_oauth.PROVIDER, user_id=person_id
        )
        if not accounts:
            raise _Unmountable(
                "it reads each person's own Google account, and they have not connected one. "
                "Tell them to connect it under Vault, Connected accounts."
            )
        return accounts


def _option(value: object) -> MountValue:
    """An author's option as the library takes it: a JSON scalar, or a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _google_credentials(grant: AccountGrant) -> dict[str, MountValue]:
    # The refresh token and its client, so the library renews the access token
    # through the run itself; Google does not rotate refresh tokens.
    return {
        "client_id": grant.client_id,
        "client_secret": grant.client_secret,
        "refresh_token": grant.refresh_token,
    }


def _resolved(
    mount: MirageMount,
    info: BackendInfo,
    config: dict[str, MountValue],
    title: str,
    *,
    path: str | None = None,
) -> ResolvedMount:
    return ResolvedMount(
        path=path or mount.path,
        backend=info.name,
        mode=mount.mode,
        approve_writes=mount.approve_writes,
        config=config,
        title=title,
    )


def _slug(email: str) -> str:
    return _SLUG.sub("-", email.lower()).strip("-.")[:63] or "account"


def host_of(value: str) -> str | None:
    """The host a typed address names: a URL or DSN's, or a bare host's."""
    if "://" in value:
        try:
            return urlsplit(value).hostname
        except ValueError:
            return None
    host = value.rsplit("@", 1)[-1].split(":", 1)[0].strip()
    return host.lower() or None


def _check_hosts(info: BackendInfo, options: Mapping[str, MountValue]) -> None:
    allowed = {host.lower() for host in settings.MIRAGE_ALLOWED_HOSTS}
    for field in info.address_fields:
        value = options.get(field)
        if value is None:
            continue
        text = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        host = host_of(text)
        if host is None or host not in allowed:
            # The host, never the value: a DSN carries its password.
            raise _Unmountable(
                f"its {field} names a host this deployment does not allow"
                f"{f' ({host})' if host else ''}."
            )


async def _graph_token(app: EntraAppSecret) -> str:
    """A Microsoft Graph token for the Entra app, by the client credentials flow."""
    form = {
        "grant_type": "client_credentials",
        "client_id": app.client_id,
        "client_secret": app.client_secret.get_secret_value(),
        "scope": _GRAPH_SCOPE,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_ENTRA_LOGIN}/{app.tenant_id}/oauth2/v2.0/token", data=form
            )
    except httpx.HTTPError as exc:
        logger.warning("mirage_entra_unreachable", extra={"error": exc.__class__.__name__})
        raise _Unmountable("Microsoft Entra could not be reached to sign its app in.") from exc
    if response.status_code != 200:
        logger.warning("mirage_entra_refused", extra={"status": response.status_code})
        raise _Unmountable(
            "Microsoft Entra refused its app's credentials; check them in the vault."
        )
    try:
        token = response.json().get("access_token")
    except ValueError, AttributeError:
        token = None
    if not isinstance(token, str) or not token:
        raise _Unmountable("Microsoft Entra answered the sign-in with no token.")
    return token
