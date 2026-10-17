"""D3 slice 2 — Shop MCP catalog/connections on Agentra (tenant → org MCP)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.integrations.minerp_shop.constants import (
    DEFAULT_ORG_CONNECTION_NAME,
    MINERP_INTERNAL_SHOP_CATALOG_KEY,
)
from app.integrations.minerp_shop.provision import ensure_minerp_shop_mcp_for_org
from app.integrations.minerp_shop.toolset import internal_shop_tool_infos
from app.repositories import member_repo, mcp_connection_repo
from app.schemas.mcp_connection import NAME_PATTERN, OrgMcpConnectionCreate, OrgMcpConnectionUpdate
from app.schemas.shop_ai_mcp import (
    ShopMcpCatalogConnectorRead,
    ShopMcpCatalogList,
    ShopMcpConnectionCreate,
    ShopMcpConnectionList,
    ShopMcpConnectionRead,
    ShopMcpConnectionTestResult,
    ShopMcpConnectionUpdate,
)
from app.services import mcp_catalog
from app.services.mcp_connection import McpConnectionService
from app.services.minerp_tenant_lookup import tenant_context_for_minerp_tenant

# Catalog keys exposed in Shop Studio (extend as more Agentra-native shop MCPs land).
SHOP_NATIVE_CATALOG_KEYS: frozenset[str] = frozenset({MINERP_INTERNAL_SHOP_CATALOG_KEY})

# Merchant assistant pack (multi-agent also lists ads/calendar/email — native when ported).
MERCHANT_NATIVE_CATALOG_KEYS: frozenset[str] = frozenset({MINERP_INTERNAL_SHOP_CATALOG_KEY})


def shop_native_mcp_reads_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_MCP_READS_ENABLED


def shop_native_mcp_writes_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_MCP_WRITES_ENABLED


def shop_native_merchant_mcp_reads_enabled() -> bool:
    return settings.SHOP_AI_NATIVE_MERCHANT_MCP_READS_ENABLED


def _should_strangler_mcp_write(data: ShopMcpConnectionCreate) -> bool:
    """OAuth / unknown connectors stay on multi-agent until native parity."""
    if data.connector_id not in SHOP_NATIVE_CATALOG_KEYS:
        return True
    if any(
        field
        for field in (
            data.oauth_authorize_url,
            data.oauth_token_url,
            data.oauth_client_id,
            data.oauth_scopes,
            data.client_secret,
        )
    ):
        return True
    return False


def _should_strangler_mcp_patch(data: ShopMcpConnectionUpdate) -> bool:
    return any(
        field
        for field in (
            data.oauth_authorize_url,
            data.oauth_token_url,
            data.oauth_client_id,
            data.oauth_scopes,
            data.client_secret,
            data.base_url,
        )
    )


def _normalize_org_connection_name(*, raw_name: str, catalog_key: str) -> str:
    if catalog_key == MINERP_INTERNAL_SHOP_CATALOG_KEY:
        return DEFAULT_ORG_CONNECTION_NAME
    slug = re.sub(r"[^a-z0-9-]+", "-", raw_name.lower().strip()).strip("-")[:32]
    if not slug or not re.fullmatch(NAME_PATTERN, slug):
        slug = re.sub(r"[^a-z0-9-]+", "-", catalog_key.lower())[:32].strip("-") or "shop-mcp"
    return slug


async def _owner_auth_context(
    db: AsyncSession,
    *,
    tenant_id: UUID,
) -> tuple[AuthContext, UUID]:
    org_ctx = await tenant_context_for_minerp_tenant(db, tenant_id)
    owner_id = await member_repo.first_owner_id(db, organization_id=org_ctx.organization_id)
    if owner_id is None:
        raise BadRequestError(
            message="Organization has no owner for shop MCP",
            details={"organization_id": str(org_ctx.organization_id)},
        )
    auth = AuthContext(
        user_id=owner_id,
        organization_id=org_ctx.organization_id,
        role=OrgRoleName.OWNER,
        minerp_tenant_id=tenant_id,
    )
    return auth, org_ctx.organization_id


async def _get_shop_native_connection(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    connection_id: UUID,
):
    auth, org_id = await _owner_auth_context(db, tenant_id=tenant_id)
    conn = await mcp_connection_repo.get_org_scoped_by_id(
        db,
        connection_id=connection_id,
        organization_id=org_id,
    )
    if conn is None or (conn.catalog_key or "") not in SHOP_NATIVE_CATALOG_KEYS:
        raise NotFoundError(
            message="MCP connection not found",
            details={"id": str(connection_id)},
        )
    return auth, org_id, conn


def _catalog_connector(entry_key: str) -> ShopMcpCatalogConnectorRead | None:
    entry = mcp_catalog.get_entry(entry_key)
    if entry is None:
        return None
    if entry_key == MINERP_INTERNAL_SHOP_CATALOG_KEY:
        tools = [
            {"name": name, "description": desc, "access": "read"}
            for name, desc in internal_shop_tool_infos()
        ]
        transport = "internal"
    else:
        tools = []
        transport = "http"
    return ShopMcpCatalogConnectorRead(
        id=entry.key,
        name=entry.name,
        description=entry.description,
        transport=transport,
        default_perm="readonly",
        auth=entry.auth.value if hasattr(entry.auth, "value") else str(entry.auth),
        tools=tools,
    )


def _list_catalog_for_keys(keys: frozenset[str]) -> ShopMcpCatalogList:
    items: list[ShopMcpCatalogConnectorRead] = []
    for key in sorted(keys):
        row = _catalog_connector(key)
        if row is not None:
            items.append(row)
    return ShopMcpCatalogList(items=items, total=len(items))


async def list_shop_mcp_catalog() -> ShopMcpCatalogList:
    return _list_catalog_for_keys(SHOP_NATIVE_CATALOG_KEYS)


async def list_merchant_mcp_catalog() -> ShopMcpCatalogList:
    return _list_catalog_for_keys(MERCHANT_NATIVE_CATALOG_KEYS)


def _connection_to_shop_read(
    conn,
    *,
    tenant_id: UUID,
    organization_id: UUID,
) -> ShopMcpConnectionRead:
    connector_id = conn.catalog_key or "custom"
    health_ok = conn.last_status == "ok" if conn.last_status else None
    return ShopMcpConnectionRead(
        id=conn.id,
        connector_id=connector_id,
        name=conn.name,
        account_label=conn.label,
        perm="readonly",
        organization_id=organization_id,
        tenant_id=tenant_id,
        is_active=conn.is_enabled,
        has_credentials=(
            conn.catalog_key == MINERP_INTERNAL_SHOP_CATALOG_KEY
            or conn.auth_token is not None
            or (conn.auth_type == "oauth" and conn.oauth_payload is not None)
        ),
        config_json=None,
        last_health_at=conn.last_checked_at,
        last_health_ok=health_ok,
        last_health_message=conn.last_error,
        oauth_connected=conn.auth_type == "oauth" and conn.oauth_payload is not None,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


async def _list_mcp_connections_for_keys(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    catalog_keys: frozenset[str],
) -> ShopMcpConnectionList:
    ctx = await tenant_context_for_minerp_tenant(db, tenant_id)
    owner_id = await member_repo.first_owner_id(db, organization_id=ctx.organization_id)
    if owner_id is None:
        raise BadRequestError(
            message="Organization has no owner for shop MCP provisioning",
            details={"organization_id": str(ctx.organization_id)},
        )
    await ensure_minerp_shop_mcp_for_org(
        db,
        organization_id=ctx.organization_id,
        created_by_user_id=owner_id,
    )
    rows, _total = await mcp_connection_repo.list_org_scoped(
        db, organization_id=ctx.organization_id
    )
    items = [
        _connection_to_shop_read(
            conn,
            tenant_id=tenant_id,
            organization_id=ctx.organization_id,
        )
        for conn in rows
        if (conn.catalog_key or "") in catalog_keys
    ]
    return ShopMcpConnectionList(items=items, total=len(items))


async def list_shop_mcp_connections(
    db: AsyncSession,
    *,
    tenant_id: UUID,
) -> ShopMcpConnectionList:
    return await _list_mcp_connections_for_keys(
        db, tenant_id=tenant_id, catalog_keys=SHOP_NATIVE_CATALOG_KEYS
    )


async def list_merchant_mcp_connections(
    db: AsyncSession,
    *,
    tenant_id: UUID,
) -> ShopMcpConnectionList:
    return await _list_mcp_connections_for_keys(
        db, tenant_id=tenant_id, catalog_keys=MERCHANT_NATIVE_CATALOG_KEYS
    )


async def create_shop_mcp_connection(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    data: ShopMcpConnectionCreate,
) -> ShopMcpConnectionRead | None:
    if not shop_native_mcp_writes_enabled():
        return None
    if data.perm != "readonly":
        raise BadRequestError(message="Shop MCP connections must use readonly permission")
    if _should_strangler_mcp_write(data):
        return None

    auth, org_id = await _owner_auth_context(db, tenant_id=tenant_id)
    entry = mcp_catalog.get_entry(data.connector_id)
    if entry is None:
        raise BadRequestError(
            message="Connector not available for Shop AI",
            details={"connector_id": data.connector_id},
        )

    if data.connector_id == MINERP_INTERNAL_SHOP_CATALOG_KEY:
        await ensure_minerp_shop_mcp_for_org(
            db,
            organization_id=org_id,
            created_by_user_id=auth.subject_id,
        )
        conn = await mcp_connection_repo.get_org_scoped_by_catalog_key(
            db,
            organization_id=org_id,
            catalog_key=MINERP_INTERNAL_SHOP_CATALOG_KEY,
        )
        if conn is None:
            raise BadRequestError(
                message="Shop catalog MCP could not be provisioned",
                details={"organization_id": str(org_id)},
            )
        return _connection_to_shop_read(
            conn, tenant_id=tenant_id, organization_id=org_id
        )

    url = (data.base_url or entry.url or "").strip()
    if not url:
        raise BadRequestError(
            message="base_url is required for this connector",
            details={"connector_id": data.connector_id},
        )
    org_name = _normalize_org_connection_name(
        raw_name=data.name, catalog_key=data.connector_id
    )
    svc = McpConnectionService(db)
    conn = await svc.create_for_org(
        auth,
        OrgMcpConnectionCreate(
            name=org_name,
            url=url,
            auth_token=data.bearer_token,
            catalog_key=data.connector_id,
            label=data.account_label,
            is_enabled=True,
        ),
    )
    return _connection_to_shop_read(conn, tenant_id=tenant_id, organization_id=org_id)


async def update_shop_mcp_connection(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    connection_id: UUID,
    data: ShopMcpConnectionUpdate,
) -> ShopMcpConnectionRead | None:
    if not shop_native_mcp_writes_enabled():
        return None
    if data.perm is not None and data.perm != "readonly":
        raise BadRequestError(message="Shop MCP connections must stay readonly")
    if _should_strangler_mcp_patch(data):
        return None

    auth, org_id, conn = await _get_shop_native_connection(
        db, tenant_id=tenant_id, connection_id=connection_id
    )
    patch = OrgMcpConnectionUpdate(
        is_enabled=data.is_active,
        label=data.account_label,
        auth_token=data.bearer_token,
    )
    if data.name is not None:
        patch.name = _normalize_org_connection_name(
            raw_name=data.name,
            catalog_key=conn.catalog_key or "custom",
        )
    svc = McpConnectionService(db)
    updated = await svc.update_for_org(
        auth, connection_id=connection_id, data=patch
    )
    return _connection_to_shop_read(
        updated, tenant_id=tenant_id, organization_id=org_id
    )


async def delete_shop_mcp_connection(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    connection_id: UUID,
) -> bool | None:
    """Return True when deleted natively; None → strangler."""
    if not shop_native_mcp_writes_enabled():
        return None
    auth, _org_id, conn = await _get_shop_native_connection(
        db, tenant_id=tenant_id, connection_id=connection_id
    )
    if conn.catalog_key == MINERP_INTERNAL_SHOP_CATALOG_KEY:
        raise BadRequestError(
            message="The default shop catalog connection cannot be deleted",
            details={"connection_id": str(connection_id)},
        )
    svc = McpConnectionService(db)
    await svc.delete_for_org(auth, connection_id=connection_id)
    return True


async def test_shop_mcp_connection(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    connection_id: UUID,
) -> ShopMcpConnectionTestResult | None:
    if not shop_native_mcp_writes_enabled():
        return None
    auth, _org_id, _conn = await _get_shop_native_connection(
        db, tenant_id=tenant_id, connection_id=connection_id
    )
    svc = McpConnectionService(db)
    updated, _tools, error = await svc.test_for_org(
        auth, connection_id=connection_id
    )
    tested_at = updated.last_checked_at or datetime.now(UTC)
    ok = error is None and updated.last_status == "ok"
    message = error or updated.last_error or "Connection OK"
    return ShopMcpConnectionTestResult(ok=ok, message=message, tested_at=tested_at)
