"""Personal app consent lives on the same records agents already bind to.

An authorization attempt is sealed to its member and expires before its provider link does.
Starting a reconnect never replaces a working grant; only verified completion
promotes the new account and rotates its authorization generation.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConfigurationError,
    ExternalServiceError,
    NotFoundError,
)
from app.core.vault import VaultScope, current_key_version, seal, unseal
from app.db.models.mcp_connection import McpConnection
from app.repositories import mcp_connection as connection_repo
from app.schemas.app_connection import (
    AppActionRead,
    AppCatalogEntry,
    AppCatalogRead,
    AppConnectionCallback,
    AppConnectionCreate,
    AppConnectionList,
    AppConnectionRead,
    AppConnectionStartRead,
)
from app.services.impersonation import refuse_binding_while_impersonating

from ._catalog import (
    APPS,
    ComposioApp,
    get_app_by_catalog_key,
    resolve_action,
    toolkit_from_catalog_key,
)
from ._client import (
    ComposioAccount,
    ComposioAccountMissing,
    ComposioCatalogClient,
    ComposioClient,
    ComposioToolkitMetadata,
    composio_user_id,
)

_ATTEMPT_TTL = timedelta(minutes=10)
_DYNAMIC_ATTEMPT_TTL = timedelta(minutes=30)
_MAX_ACCOUNTS = 50
_MAX_DYNAMIC_ACTIONS = 1000
_META_TOOLKITS = frozenset({"composio"})
_VERIFY_ERROR = "The app authorization could not be checked. Try checking the connection again."


class _PendingConsent(BaseModel):
    attempt_id: UUID
    user_id: UUID
    toolkit: str
    auth_config_id: str | None = None
    account_id: str
    expires_at: datetime
    identity_verified: bool = False
    session_id: str | None = None
    dynamic: bool = False


def is_configured(toolkit: str) -> bool:
    """The same operator gate for the browser catalog and runtime execution."""
    key = settings.COMPOSIO_API_KEY
    return bool(
        key is not None
        and key.get_secret_value().strip()
        and settings.COMPOSIO_AUTH_CONFIGS.get(toolkit, "").strip()
    )


def _runtime_configured() -> bool:
    key = settings.COMPOSIO_API_KEY
    return key is not None and bool(key.get_secret_value().strip())


def _auth_config(toolkit: str) -> str:
    if not is_configured(toolkit):
        raise ConfigurationError(
            message="Set COMPOSIO_API_KEY and this app's COMPOSIO_AUTH_CONFIGS entry to enable it"
        )
    return settings.COMPOSIO_AUTH_CONFIGS[toolkit].strip()


def _app(connection: McpConnection) -> ComposioApp:
    app = get_app_by_catalog_key(connection.catalog_key)
    if app is not None:
        return app
    toolkit = toolkit_from_catalog_key(connection.catalog_key)
    if (
        toolkit is None
        or toolkit in _META_TOOLKITS
        or connection.url != f"https://backend.composio.dev/api/v3.1/toolkits/{toolkit}"
        or not isinstance(connection.allowed_tools, list)
        or not connection.allowed_tools
        or len(connection.allowed_tools) > _MAX_DYNAMIC_ACTIONS
        or any(
            not isinstance(tool, str)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", tool) is None
            or tool.upper().startswith("COMPOSIO_")
            for tool in connection.allowed_tools
        )
    ):
        raise BadRequestError(message="This managed app is no longer in the supported catalog")
    return ComposioApp(
        toolkit=toolkit,
        name=toolkit.replace("-", " ").title(),
        description="Use this connected app account.",
        category="apps",
        actions=(),
    )


def _pending(connection: McpConnection, *, user_id: UUID) -> _PendingConsent:
    if not connection.oauth_pending_payload or not connection.oauth_state:
        raise BadRequestError(message="This connection attempt is no longer available")
    try:
        pending = _PendingConsent.model_validate_json(
            unseal(
                connection.oauth_pending_payload,
                scope=VaultScope.user(user_id),
                key_version=connection.secret_key_version,
            )
        )
    except ValidationError, BadRequestError:
        raise BadRequestError(message="This connection attempt is no longer available") from None
    if (
        pending.user_id != user_id
        or str(pending.attempt_id) != connection.oauth_state
        or pending.toolkit != _app(connection).toolkit
        or pending.expires_at.tzinfo is None
        or (pending.dynamic and pending.session_id is None)
        or (
            not pending.dynamic
            and (pending.session_id is not None or pending.auth_config_id is None)
        )
    ):
        raise BadRequestError(message="This connection attempt did not match the saved account")
    return pending


def _require_live(pending: _PendingConsent) -> None:
    if pending.expires_at <= datetime.now(UTC):
        raise BadRequestError(message="This connection attempt expired. Connect the app again.")


def _sealed_pending(connection: McpConnection, pending: _PendingConsent) -> str:
    return seal(
        pending.model_dump_json(),
        scope=VaultScope.user(pending.user_id),
        key_version=connection.secret_key_version,
    ).ciphertext


def _catalog_entry(
    app: ComposioApp,
    *,
    configured: bool,
    availability: Literal["ready", "setup_required", "unavailable"],
    approval_required: bool,
    action_count: int | None = None,
) -> AppCatalogEntry:
    return AppCatalogEntry(
        key=app.catalog_key,
        toolkit=app.toolkit,
        name=_safe_text(app.name, fallback=app.toolkit.replace("-", " ").title(), limit=100),
        description=_safe_text(app.description, fallback="", limit=500),
        category=_safe_text(app.category, fallback="apps", limit=64).lower(),
        configured=configured,
        availability=availability,
        approval_required=approval_required,
        action_count=action_count if action_count is not None else len(app.actions),
        actions=[
            AppActionRead(
                name=action.name,
                label=_safe_text(action.label, fallback=action.name, limit=100),
                read_only=action.read_only,
                side_effecting=action.side_effecting,
                scopes=list(action.scopes),
            )
            for action in app.actions
        ],
    )


def _safe_text(value: str, *, fallback: str, limit: int) -> str:
    cleaned = "".join(char for char in value if char.isprintable()).strip()[:limit]
    return cleaned or fallback


def _static_entry(app: ComposioApp) -> AppCatalogEntry:
    configured = is_configured(app.toolkit)
    return _catalog_entry(
        app,
        configured=configured,
        availability="ready" if configured else "setup_required",
        approval_required=False,
    )


def _dynamic_entry(
    metadata: ComposioToolkitMetadata,
    *,
    runtime_configured: bool,
) -> AppCatalogEntry:
    app = ComposioApp(
        toolkit=metadata.slug,
        name=metadata.name,
        description=metadata.summary,
        category=metadata.category_name,
        actions=(),
    )
    explicit_auth_config = settings.COMPOSIO_AUTH_CONFIGS.get(metadata.slug, "").strip()
    if (
        metadata.slug in _META_TOOLKITS
        or metadata.no_auth
        or metadata.is_deprecated_flag
        or not metadata.enabled
    ):
        availability: Literal["ready", "setup_required", "unavailable"] = "unavailable"
    elif not runtime_configured:
        availability = "unavailable"
    elif metadata.action_count > _MAX_DYNAMIC_ACTIONS:
        availability = "setup_required"
    elif metadata.has_managed_auth or explicit_auth_config:
        availability = "ready"
    else:
        availability = "setup_required"
    return _catalog_entry(
        app,
        configured=availability == "ready",
        availability=availability,
        approval_required=True,
        action_count=metadata.action_count,
    )


def _connection_entry(connection: McpConnection, app: ComposioApp | None = None) -> AppCatalogEntry:
    resolved = app or _app(connection)
    if get_app_by_catalog_key(connection.catalog_key) is not None:
        configured = is_configured(resolved.toolkit)
        return _catalog_entry(
            resolved,
            configured=configured,
            availability="ready" if configured else "setup_required",
            approval_required=False,
        )
    explicitly_configured = bool(settings.COMPOSIO_AUTH_CONFIGS.get(resolved.toolkit, "").strip())
    has_verified_or_pending_auth = (
        connection.composio_auth_config_id is not None
        or connection.oauth_pending_payload is not None
    )
    ready = _runtime_configured() and (explicitly_configured or has_verified_or_pending_auth)
    return _catalog_entry(
        resolved,
        configured=ready,
        availability=("ready" if ready else "setup_required")
        if _runtime_configured()
        else "unavailable",
        approval_required=True,
        action_count=len(connection.allowed_tools or []),
    )


def _read(
    connection: McpConnection, *, app_entry: AppCatalogEntry | None = None
) -> AppConnectionRead:
    app = _app(connection)
    authorized = connection.account_authorized
    status: Literal["pending", "connected", "expired", "failed", "disabled"] = "pending"
    error = connection.last_error
    if not connection.is_enabled or connection.composio_status == "INACTIVE":
        status = "disabled"
    elif authorized:
        status = "connected"
    elif connection.composio_status in {"EXPIRED", "REVOKED"}:
        status = "expired"
    elif connection.composio_status == "FAILED":
        status = "failed"
    elif connection.oauth_pending_payload and connection.user_id is not None:
        try:
            if _pending(connection, user_id=connection.user_id).expires_at <= datetime.now(UTC):
                status = "expired"
        except BadRequestError:
            status = "failed"
            error = "This connection attempt is no longer available. Connect the app again."
    readiness: Literal["authorization_required", "authorization_verified", "unavailable"] = (
        "unavailable"
        if not (
            is_configured(app.toolkit)
            if get_app_by_catalog_key(connection.catalog_key) is not None
            else _runtime_configured()
        )
        or not connection.is_enabled
        or connection.last_status == "error"
        else "authorization_verified"
        if authorized
        else "authorization_required"
    )
    return AppConnectionRead(
        id=connection.id,
        catalog_key=app.catalog_key,
        toolkit=app.toolkit,
        name=app.name,
        label=connection.label,
        identity=connection.account_email,
        status=status,
        is_enabled=connection.is_enabled,
        is_default=connection.is_default,
        authorized=authorized,
        readiness=readiness,
        app=app_entry or _connection_entry(connection, app),
        last_checked_at=connection.last_checked_at,
        last_error=error,
        created_at=connection.created_at,
    )


class AppConnectionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def catalog(
        self, *, search: str = "", cursor: str | None = None, limit: int = 24
    ) -> AppCatalogRead:
        """Page official native toolkits; only managed, bounded apps can be connected."""
        if cursor is not None and (
            len(cursor) > 512 or re.fullmatch(r"[A-Za-z0-9_+/=-]+", cursor) is None
        ):
            raise BadRequestError(message="The app catalog cursor is invalid")
        try:
            async with ComposioCatalogClient() as client:
                page = await client.list_toolkits(search=search, cursor=cursor, limit=limit)
        except ConfigurationError, ExternalServiceError:
            apps = [_static_entry(app) for app in APPS]
            return AppCatalogRead(
                configured=any(app.configured for app in apps),
                catalog_available=False,
                apps=apps,
                next_cursor=None,
            )

        apps: list[AppCatalogEntry] = []
        for metadata in page.items:
            if toolkit_from_catalog_key(f"composio-{metadata.slug}") is None:
                continue
            curated = next((app for app in APPS if app.toolkit == metadata.slug), None)
            apps.append(
                _static_entry(curated)
                if curated is not None
                else _dynamic_entry(metadata, runtime_configured=_runtime_configured())
            )
        next_cursor = page.next_cursor
        if next_cursor is not None and (
            len(next_cursor) > 512 or re.fullmatch(r"[A-Za-z0-9_+/=-]+", next_cursor) is None
        ):
            raise ExternalServiceError(
                message="The app connection provider returned an invalid catalog cursor"
            )
        return AppCatalogRead(
            configured=_runtime_configured(),
            catalog_available=True,
            apps=apps,
            next_cursor=next_cursor,
        )

    async def list_for_user(self, *, user_id: UUID) -> AppConnectionList:
        connections = await connection_repo.list_composio_for_user(self.db, user_id=user_id)
        return AppConnectionList(
            items=[_read(connection) for connection in connections],
            total=len(connections),
        )

    async def _owned(self, *, user_id: UUID, connection_id: UUID) -> McpConnection:
        connection = await connection_repo.get_by_id_for_update(self.db, connection_id)
        if (
            connection is None
            or connection.scope != "user"
            or connection.user_id != user_id
            or connection.organization_id is not None
            or connection.purpose != "mcp"
            or connection.auth_type != "composio"
        ):
            raise NotFoundError(message="App connection not found")
        _app(connection)
        return connection

    async def connect(self, *, user_id: UUID, data: AppConnectionCreate) -> AppConnectionStartRead:
        refuse_binding_while_impersonating("Connecting an app")
        curated = next((app for app in APPS if app.toolkit == data.toolkit), None)
        dynamic = curated is None
        if curated is not None:
            app = curated
            auth_config_id: str | None = _auth_config(app.toolkit)
            allowed_tools = [resolve_action(action).tool_name for action in app.actions]
        else:
            if not _runtime_configured():
                raise ConfigurationError(message="Set COMPOSIO_API_KEY to enable app connections")
            async with ComposioCatalogClient() as catalog_client:
                metadata = await catalog_client.get_toolkit(data.toolkit)
                if metadata.slug != data.toolkit:
                    raise BadRequestError(message="This app is not available to connect")
                entry = _dynamic_entry(metadata, runtime_configured=True)
                if not entry.configured:
                    raise BadRequestError(
                        message="This app requires operator setup before it can be connected"
                    )
                allowed_tools = await catalog_client.direct_tool_names(toolkit=data.toolkit)
                auth_config_id = (
                    settings.COMPOSIO_AUTH_CONFIGS.get(data.toolkit, "").strip() or None
                )
            app = ComposioApp(
                toolkit=metadata.slug,
                name=metadata.name,
                description=metadata.summary,
                category=metadata.category_name,
                actions=(),
            )
        await connection_repo.lock_account_owner(self.db, user_id=user_id)
        connections = await connection_repo.list_composio_for_user(self.db, user_id=user_id)
        if len(connections) >= _MAX_ACCOUNTS:
            raise BadRequestError(message="Remove an unused app connection before adding another")
        siblings = [
            connection for connection in connections if connection.catalog_key == app.catalog_key
        ]
        connection = await connection_repo.create(
            self.db,
            user_id=user_id,
            name=f"{app.toolkit[:49]}-{uuid4().hex[:12]}",
            # Stable identity only. Runtime creates a separately scoped MCP
            # endpoint after resolving this member's account and agent policy.
            url=f"https://backend.composio.dev/api/v3.1/toolkits/{app.toolkit}",
            auth_token=None,
            secret_key_version=current_key_version(),
            allowed_tools=allowed_tools,
            auth_type="composio",
            catalog_key=app.catalog_key,
            label=data.label or (f"Account {len(siblings) + 1}" if siblings else None),
        )
        await connection_repo.update(
            self.db,
            db_connection=connection,
            update_data={
                "composio_auth_config_id": auth_config_id,
                "composio_status": "INITIATED",
                "is_default": not siblings,
            },
        )
        if dynamic:
            if auth_config_id is not None:
                return await self._start(connection, user_id=user_id, auth_config_id=auth_config_id)
            return await self._start_dynamic(connection, user_id=user_id)
        if auth_config_id is None:
            raise ConfigurationError(message="This app is not configured for managed authorization")
        return await self._start(connection, user_id=user_id, auth_config_id=auth_config_id)

    async def reconnect(self, *, user_id: UUID, connection_id: UUID) -> AppConnectionStartRead:
        refuse_binding_while_impersonating("Connecting an app")
        await connection_repo.lock_account_owner(self.db, user_id=user_id)
        connection = await self._owned(user_id=user_id, connection_id=connection_id)
        if get_app_by_catalog_key(connection.catalog_key) is None:
            auth_config_id = settings.COMPOSIO_AUTH_CONFIGS.get(
                _app(connection).toolkit, ""
            ).strip()
            if auth_config_id:
                return await self._start(connection, user_id=user_id, auth_config_id=auth_config_id)
            return await self._start_dynamic(connection, user_id=user_id)
        return await self._start(
            connection, user_id=user_id, auth_config_id=_auth_config(_app(connection).toolkit)
        )

    async def _start(
        self, connection: McpConnection, *, user_id: UUID, auth_config_id: str
    ) -> AppConnectionStartRead:
        attempt_id = uuid4()
        callback_url = (
            f"{str(settings.FRONTEND_URL).rstrip('/')}/connectors?connection_attempt={attempt_id}"
        )
        async with ComposioClient() as client:
            # A second attempt replaces the pending grant, never the active one.
            # Clean it up first so abandoned reconnects do not accumulate grants.
            if connection.oauth_pending_payload:
                previous = _pending(connection, user_id=user_id)
                if previous.account_id != connection.composio_account_id:
                    await client.delete_account(previous.account_id)
            link = await client.link(
                user_id=composio_user_id(user_id),
                auth_config_id=auth_config_id,
                callback_url=callback_url,
            )
        expires_at = min(link.expires_at, datetime.now(UTC) + _ATTEMPT_TTL)
        if expires_at <= datetime.now(UTC):
            raise ExternalServiceError(
                message="The app connection provider returned an expired link"
            )
        pending = _PendingConsent(
            attempt_id=attempt_id,
            user_id=user_id,
            toolkit=_app(connection).toolkit,
            auth_config_id=auth_config_id,
            account_id=link.connected_account_id,
            expires_at=expires_at,
        )
        await connection_repo.update(
            self.db,
            db_connection=connection,
            update_data={
                "oauth_state": str(attempt_id),
                "oauth_pending_payload": _sealed_pending(connection, pending),
            },
        )
        return AppConnectionStartRead(
            connection_id=connection.id,
            attempt_id=attempt_id,
            redirect_url=link.redirect_url,
            expires_at=expires_at,
        )

    async def _start_dynamic(
        self, connection: McpConnection, *, user_id: UUID
    ) -> AppConnectionStartRead:
        """Open managed authorization with only this app's saved direct tools."""
        app = _app(connection)
        tools = connection.allowed_tools
        if (
            not tools
            or len(tools) > _MAX_DYNAMIC_ACTIONS
            or any(
                not isinstance(tool, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", tool) is None
                or tool.upper().startswith("COMPOSIO_")
                for tool in tools
            )
        ):
            raise BadRequestError(message="This app action list is not available for authorization")
        attempt_id = uuid4()
        async with ComposioClient() as client:
            if connection.oauth_pending_payload:
                previous = _pending(connection, user_id=user_id)
                if previous.account_id != connection.composio_account_id:
                    await client.delete_account(previous.account_id)
            session_id = await client.create_link_session(
                user_id=composio_user_id(user_id), toolkit=app.toolkit, tools=tools
            )
            link = await client.link_session(session_id=session_id, toolkit=app.toolkit)
        expires_at = min(link.expires_at, datetime.now(UTC) + _DYNAMIC_ATTEMPT_TTL)
        if expires_at <= datetime.now(UTC):
            raise ExternalServiceError(
                message="The app connection provider returned an expired link"
            )
        pending = _PendingConsent(
            attempt_id=attempt_id,
            user_id=user_id,
            toolkit=app.toolkit,
            account_id=link.connected_account_id,
            expires_at=expires_at,
            session_id=session_id,
            dynamic=True,
        )
        await connection_repo.update(
            self.db,
            db_connection=connection,
            update_data={
                "oauth_state": str(attempt_id),
                "oauth_pending_payload": _sealed_pending(connection, pending),
            },
        )
        return AppConnectionStartRead(
            connection_id=connection.id,
            attempt_id=attempt_id,
            redirect_url=link.redirect_url,
            expires_at=expires_at,
        )

    async def callback(self, *, user_id: UUID, data: AppConnectionCallback) -> AppConnectionRead:
        refuse_binding_while_impersonating("Connecting an app")
        await connection_repo.lock_account_owner(self.db, user_id=user_id)
        pending_candidates: list[tuple[McpConnection, _PendingConsent]] = []
        if data.attempt_id is not None:
            candidate = await connection_repo.get_by_oauth_state(self.db, str(data.attempt_id))
            if candidate is None:
                raise NotFoundError(message="Connection attempt not found")
            connection = await self._owned(user_id=user_id, connection_id=candidate.id)
            pending = _pending(connection, user_id=user_id)
            _require_live(pending)
            if (
                data.connected_account_id is not None
                and data.connected_account_id != pending.account_id
            ):
                raise BadRequestError(
                    message="The returned account did not match this connection attempt"
                )
            pending_candidates.append((connection, pending))
        else:
            # A project identity-verifier URL is static: Composio sends
            # session_uri without our per-attempt query string. Look only among
            # this member's live attempts, then match its signed response.
            for candidate in await connection_repo.list_composio_for_user(self.db, user_id=user_id):
                if not candidate.oauth_pending_payload:
                    continue
                try:
                    pending = _pending(candidate, user_id=user_id)
                except BadRequestError:
                    # An unrelated abandoned/corrupt attempt must not prevent
                    # the owner finishing a different account.
                    continue
                if pending.expires_at > datetime.now(UTC):
                    pending_candidates.append((candidate, pending))
        if data.session_uri is None:
            raise BadRequestError(
                message="Complete the app's identity verification before connecting"
            )
        if not pending_candidates:
            raise BadRequestError(message="No live connection attempt belongs to this account")
        async with ComposioClient() as client:
            completed = await client.complete_auth(
                session_uri=data.session_uri.get_secret_value(),
                user_id=composio_user_id(user_id),
            )
            matches = [
                (candidate, pending)
                for candidate, pending in pending_candidates
                if pending.account_id == completed.connected_account_id
                and pending.toolkit == completed.toolkit_slug
            ]
            if len(matches) != 1:
                raise BadRequestError(
                    message="The verified account did not match a saved connection attempt"
                )
            candidate, pending = matches[0]
            connection = await self._owned(user_id=user_id, connection_id=candidate.id)
            # Re-read under the row lock: an abandoned or replaced attempt must
            # not be resurrected by an older browser tab.
            current = _pending(connection, user_id=user_id)
            if current.attempt_id != pending.attempt_id:
                raise BadRequestError(message="This connection attempt has been replaced")
            if (
                data.connected_account_id is not None
                and data.connected_account_id != pending.account_id
            ):
                raise BadRequestError(
                    message="The returned account did not match this connection attempt"
                )
            pending.identity_verified = True
            await connection_repo.update(
                self.db,
                db_connection=connection,
                update_data={"oauth_pending_payload": _sealed_pending(connection, pending)},
            )
            return await self._finish(connection, user_id=user_id, client=client)

    async def _verify_pending_account(
        self,
        connection: McpConnection,
        *,
        user_id: UUID,
        client: ComposioClient,
        pending: _PendingConsent,
    ) -> ComposioAccount:
        """Resolve managed auth metadata, seal it, then verify this exact owner grant."""
        if pending.dynamic:
            if pending.session_id is None:
                raise ExternalServiceError(message="The linked app session is unavailable")
            discovered = await client.discover_account_auth_config(
                user_id=composio_user_id(user_id),
                toolkit=pending.toolkit,
                account_id=pending.account_id,
            )
            pending.auth_config_id = discovered.auth_config.id
            await connection_repo.update(
                self.db,
                db_connection=connection,
                update_data={"oauth_pending_payload": _sealed_pending(connection, pending)},
            )
        if pending.auth_config_id is None:
            raise ExternalServiceError(message="The app auth configuration is unavailable")
        return await client.verify_account(
            user_id=composio_user_id(user_id),
            toolkit=pending.toolkit,
            account_id=pending.account_id,
            auth_config_id=pending.auth_config_id,
        )

    async def _finish(
        self, connection: McpConnection, *, user_id: UUID, client: ComposioClient
    ) -> AppConnectionRead:
        refuse_binding_while_impersonating("Connecting an app")
        pending = _pending(connection, user_id=user_id)
        _require_live(pending)
        if not pending.identity_verified:
            return _read(connection)
        try:
            account = await self._verify_pending_account(
                connection,
                user_id=user_id,
                client=client,
                pending=pending,
            )
        except ExternalServiceError:
            # The identity session is single-use. Preserve its successful
            # verification on a transient metadata failure so Refresh can finish
            # the same saved attempt without accepting an unverified grant.
            await connection_repo.update(
                self.db,
                db_connection=connection,
                update_data={
                    "last_status": "error",
                    "last_error": _VERIFY_ERROR,
                    "last_checked_at": datetime.now(UTC),
                },
            )
            return _read(connection)
        if account.status != "ACTIVE" or account.is_disabled or account.auth_config.is_disabled:
            await connection_repo.update(
                self.db,
                db_connection=connection,
                update_data={
                    "last_status": "error",
                    "last_error": "The app has not granted access. Complete authorization or connect again.",
                    "last_checked_at": datetime.now(UTC),
                    **(
                        {"composio_status": account.status}
                        if not connection.composio_account_id
                        else {}
                    ),
                },
            )
            return _read(connection)
        previous_id = connection.composio_account_id
        if previous_id is not None and previous_id != account.id:
            try:
                await client.delete_account(previous_id)
            except ExternalServiceError:
                # Retain the working old grant and the verified pending attempt;
                # Refresh retries cleanup before switching to the new identity.
                await connection_repo.update(
                    self.db,
                    db_connection=connection,
                    update_data={
                        "last_status": "error",
                        "last_error": "The previous authorization could not be removed. Check the connection again.",
                    },
                )
                return _read(connection)
        await connection_repo.update(
            self.db,
            db_connection=connection,
            update_data={
                "composio_account_id": account.id,
                "composio_auth_config_id": pending.auth_config_id,
                "composio_status": "ACTIVE",
                "account_email": account.identity,
                "authorization_generation": uuid4(),
                "last_tools": None,
                "oauth_state": None,
                "oauth_pending_payload": None,
                "last_status": "ok",
                "last_error": None,
                "last_checked_at": datetime.now(UTC),
                "unreachable_since": None,
            },
        )
        return _read(connection)

    async def refresh(self, *, user_id: UUID, connection_id: UUID) -> AppConnectionRead:
        await connection_repo.lock_account_owner(self.db, user_id=user_id)
        connection = await self._owned(user_id=user_id, connection_id=connection_id)
        async with ComposioClient() as client:
            if connection.oauth_pending_payload:
                pending = _pending(connection, user_id=user_id)
                if pending.identity_verified and pending.expires_at > datetime.now(UTC):
                    return await self._finish(connection, user_id=user_id, client=client)
            if connection.composio_account_id is None or connection.composio_auth_config_id is None:
                return _read(connection)
            try:
                account = await client.verify_account(
                    user_id=composio_user_id(user_id),
                    toolkit=_app(connection).toolkit,
                    account_id=connection.composio_account_id,
                    auth_config_id=connection.composio_auth_config_id,
                )
            except ComposioAccountMissing:
                await connection_repo.update(
                    self.db,
                    db_connection=connection,
                    update_data={
                        "composio_status": "REVOKED",
                        "authorization_generation": uuid4(),
                        "last_status": "error",
                        "last_error": "The app authorization is no longer available. Connect again.",
                        "last_checked_at": datetime.now(UTC),
                    },
                )
            except ExternalServiceError:
                await connection_repo.update(
                    self.db,
                    db_connection=connection,
                    update_data={
                        "last_status": "error",
                        "last_error": _VERIFY_ERROR,
                        "last_checked_at": datetime.now(UTC),
                    },
                )
            else:
                await self._record_health(connection, account)
        return _read(connection)

    async def _record_health(self, connection: McpConnection, account: ComposioAccount) -> None:
        status = (
            "INACTIVE" if account.is_disabled or account.auth_config.is_disabled else account.status
        )
        await connection_repo.update(
            self.db,
            db_connection=connection,
            update_data={
                "composio_status": status,
                "account_email": account.identity or connection.account_email,
                "last_status": "ok" if status == "ACTIVE" else "error",
                "last_error": None if status == "ACTIVE" else "This app needs authorization again.",
                "last_checked_at": datetime.now(UTC),
                **(
                    {"authorization_generation": uuid4()}
                    if connection.composio_status != status
                    else {}
                ),
            },
        )

    async def delete(self, *, user_id: UUID, connection_id: UUID) -> None:
        await connection_repo.lock_account_owner(self.db, user_id=user_id)
        connection = await self._owned(user_id=user_id, connection_id=connection_id)
        accounts: set[str] = set()
        if connection.composio_account_id is not None:
            accounts.add(connection.composio_account_id)
        if connection.oauth_pending_payload:
            accounts.add(_pending(connection, user_id=user_id).account_id)
        if accounts:
            async with ComposioClient() as client:
                for account_id in sorted(accounts):
                    await client.delete_account(account_id)
        # Delete removes the credential from Composio and the personal binding
        # from T3OS. Provider-wide consent revocation is not universally supported.
        await connection_repo.delete(self.db, db_connection=connection)
