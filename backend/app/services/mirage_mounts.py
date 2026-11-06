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

import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit
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
from app.core.exceptions import BadRequestError, ConfigurationError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, EntraAppSecret
from app.db.models.mcp_connection import McpConnection
from app.repositories import mcp_connection_repo, organization_secret_repo
from app.services.mcp_connection import (
    AccountGrant,
    McpConnectionService,
    account_client_identity,
    account_source_organization,
)
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

    async def authority(
        self, ctx: AuthContext, config: MirageConfig, *, person_id: UUID | None
    ) -> str:
        """An opaque identity of the accounts and credential generations a terminal can reach."""
        material: list[tuple[str, str]] = []
        for mount in config.mounts:
            for identifier in sorted(set(mount.secrets.values())):
                generation = await organization_secret_repo.authorization_generation(
                    self.db, identifier, organization_id=ctx.organization_id
                )
                material.append((f"secret:{mount.path}:{identifier}", str(generation)))
            info = backend(mount.backend)
            if info is not None and info.credential == "google":
                try:
                    accounts = await self._accounts(ctx, mount, person_id)
                except _Unmountable:
                    accounts = []
                for account in accounts:
                    material.append(
                        (
                            f"account:{mount.path}:{account.id}",
                            str(account.authorization_generation),
                        )
                    )
                    client = account_client_identity(account)
                    if client is not None:
                        generation = await organization_secret_repo.authorization_generation(
                            self.db, client[1], organization_id=ctx.organization_id
                        )
                        material.append((f"client:{client[1]}:{client[2]}", str(generation)))
        return hashlib.sha256(json.dumps(sorted(material)).encode()).hexdigest()

    async def resolve(
        self, ctx: AuthContext, config: MirageConfig, *, person_id: UUID | None
    ) -> ResolvedTerminal:
        """Every folder the spec names that can be built for this run.

        `person_id` is whoever the run answers - the message's author - for a
        mount that reads each person's own account; `None` where there is nobody
        (an API key, a schedule).
        """
        secret_ids = [secret_id for mount in config.mounts for secret_id in mount.secrets.values()]
        rows = (
            await organization_secret_repo.get_many(
                self.db, secret_ids, organization_id=ctx.organization_id
            )
            if secret_ids
            else {}
        )
        purposes = {secret_id: row.purpose for secret_id, row in rows.items()}
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
                mounts.extend(await self._build(ctx, mount, info, purposes, person_id, notes))
            except _Unmountable as exc:
                notes.append(f"{mount.path} is not mounted: {exc}")
        return ResolvedTerminal(mounts=tuple(mounts), notes=tuple(notes))

    async def _build(
        self,
        ctx: AuthContext,
        mount: MirageMount,
        info: BackendInfo,
        purposes: Mapping[UUID, str],
        person_id: UUID | None,
        notes: list[str],
    ) -> list[ResolvedMount]:
        options: dict[str, MountValue] = dict(mount.options)
        for field, secret_id in mount.secrets.items():
            purpose = purposes.get(secret_id)
            if purpose is None:
                raise _Unmountable(f"its {field} secret is no longer in the vault.")
            if purpose not in (*info.secret_purposes, "custom"):
                raise _Unmountable(f"its {field} secret belongs to another service.")
        try:
            unsealed = (
                await self.secrets.resolve_for_bindings(ctx, list(mount.secrets.values()))
                if mount.secrets
                else {}
            )
        except (BadRequestError, ConfigurationError) as exc:
            logger.warning("Mirage vault unavailable for %s (%s)", mount.path, type(exc).__name__)
            raise _Unmountable(
                "its vault secrets cannot be read; replace or reconnect them."
            ) from exc
        if info.credential == "google":
            return await self._google(ctx, mount, info, options, person_id, notes)
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
        if info.name in {"mongodb", "gridfs"}:
            options["uri"] = _direct_mongo(options["uri"])
        return [_resolved(mount, info, options, info.title)]

    async def _google(
        self,
        ctx: AuthContext,
        mount: MirageMount,
        info: BackendInfo,
        options: dict[str, MountValue],
        person_id: UUID | None,
        notes: list[str],
    ) -> list[ResolvedMount]:
        accounts = await self._accounts(ctx, mount, person_id)
        needed = _GOOGLE_SCOPES[info.name]
        resolved: list[ResolvedMount] = []
        for account in accounts:
            grant = await self.connections.account_grant(
                account, organization_id=ctx.organization_id
            )
            if grant is None:
                notes.append(
                    f"{mount.path}: {account.label or 'the account'} has to be connected again."
                )
                continue
            missing = needed - grant.scopes
            if missing:
                notes.append(
                    f"{mount.path}: {grant.email} did not grant access to {info.title}; connect it again "
                    "and allow it."
                )
                continue
            path = (
                mount.path
                if len(accounts) == 1
                else f"{mount.path}{_slug(grant.email)}-{account.id.hex}/"
            )
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
        accounts = [
            account
            for account in accounts
            if account_source_organization(account) == ctx.organization_id
        ]
        if not accounts:
            raise _Unmountable(
                "it reads each person's own Google account, and they have not connected one. "
                "Tell them to connect it under Vault, Connected accounts."
            )
        return accounts


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


def hosts_of(value: str) -> tuple[str, ...]:
    """Every effective authority host, including PostgreSQL and MongoDB seed lists."""
    try:
        is_url = "://" in value
        parsed = urlsplit(value if is_url else f"//{value}")
        if not is_url and (parsed.path or parsed.query or parsed.fragment):
            return ()
        if parsed.scheme in {"postgres", "postgresql"} and any(
            key.lower() in {"host", "hostaddr", "service"} for key, _ in parse_qsl(parsed.query)
        ):
            return ()
        authority = parsed.netloc.rsplit("@", 1)[-1]
        hosts: list[str] = []
        for target in authority.split(","):
            address = urlsplit(f"//{target}")
            host = address.hostname
            _ = address.port
            if not host or "%" in host or address.path or any(char.isspace() for char in host):
                return ()
            hosts.append(host)
        return tuple(hosts)
    except ValueError:
        return ()


def _direct_mongo(value: MountValue) -> SecretStr:
    if not isinstance(value, SecretStr):
        raise _Unmountable("its MongoDB URI is not a vault credential.")
    uri = value.get_secret_value()
    parsed = urlsplit(uri)
    if parsed.scheme != "mongodb" or len(hosts_of(uri)) != 1:
        raise _Unmountable("MongoDB requires one mongodb:// host; automatic discovery is disabled.")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() != "directconnection"
    ]
    query.append(("directConnection", "true"))
    return SecretStr(parsed._replace(query=urlencode(query)).geturl())


def address_fields(info: BackendInfo, options: Mapping[str, object]) -> tuple[str, ...]:
    """Only the effective Qdrant target is checked; url takes precedence over host."""
    if info.name == "qdrant":
        return ("url",) if options.get("url") else ("host",)
    return info.address_fields


def default_address(info: BackendInfo, field: str) -> str | None:
    """A backend's implicit address is subject to the same policy as a typed one."""
    properties = info.options_schema.get("properties", {})
    spec = properties.get(field, {})
    value = spec.get("default")
    return value if isinstance(value, str) else None


def _check_hosts(info: BackendInfo, options: Mapping[str, MountValue]) -> None:
    allowed = {host.lower() for host in settings.MIRAGE_ALLOWED_HOSTS}
    for field in address_fields(info, options):
        value = options.get(field) or default_address(info, field)
        if value is None:
            continue
        text = value.get_secret_value() if isinstance(value, SecretStr) else str(value)
        hosts = hosts_of(text)
        if not hosts or not set(hosts) <= allowed:
            # The host, never the value: a DSN carries its password.
            raise _Unmountable(
                f"its {field} names a host this deployment does not allow"
                f"{f' ({", ".join(hosts)})' if hosts else ''}."
            )
        if info.name == "postgres" and field == "dsn":
            parsed = urlsplit(text)
            parameters = dict(parse_qsl(parsed.query, keep_blank_values=True))
            host_files = {"passfile", "servicefile", "sslkey", "sslcert", "sslrootcert", "sslcrl"}
            # asyncpg treats empty URI passwords and blank query values as
            # absent, then reads PGPASSWORD or a host-side .pgpass file.
            if not (parsed.password or parameters.get("password")) or host_files.intersection(
                key.lower() for key in parameters
            ):
                raise _Unmountable(
                    "its vault DSN must supply a nonempty password and cannot name host credential files."
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
