"""Native product operations shared by capabilities, workflows and watches."""

from uuid import UUID

from pydantic_ai.toolsets import FunctionToolset
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.watch_sources import WatchReadReceipt
from app.db.models.mcp_connection import McpConnection
from app.schemas.watch_sources import WatchSources
from app.services.integrations import slack_oauth
from app.services.integrations.app_auth import ApplicationGrant, google_token, microsoft_token
from app.services.integrations.catalog import (
    ODOO_MODELS,
    PRODUCTS,
    Operation,
    Product,
    Provider,
    application_scopes,
)
from app.services.integrations.client import execute as execute_operation
from app.services.integrations.feeds import Change, Changes, changes_since
from app.services.integrations.odoo import execute as execute_odoo_operation
from app.services.integrations.service import (
    AccountSelection,
    AccountToken,
    IntegrationService,
    OdooAccountToken,
    can_read_feed,
)
from app.services.integrations.setup import IntegrationSetup, setup_for

__all__ = [
    "ODOO_MODELS",
    "PRODUCTS",
    "AccountSelection",
    "AccountToken",
    "ApplicationGrant",
    "Change",
    "Changes",
    "IntegrationService",
    "IntegrationSetup",
    "OdooAccountToken",
    "Operation",
    "Product",
    "Provider",
    "application_scopes",
    "build_watch_toolset",
    "can_read_feed",
    "changes_since",
    "execute_odoo_operation",
    "execute_operation",
    "google_token",
    "microsoft_token",
    "poll_account",
    "setup_for",
    "slack_oauth",
]


def build_watch_toolset(
    sources: WatchSources,
    receipt: WatchReadReceipt,
    *,
    organization_id: UUID,
    person_id: UUID,
    watch_id: UUID | None,
    agent_id: UUID,
) -> FunctionToolset[object]:
    """A single approved account's read-only feed, resolved at tool-call time."""
    from app.services.integrations.watch import build_watch_toolset as build

    return build(
        sources,
        receipt,
        organization_id=organization_id,
        person_id=person_id,
        watch_id=watch_id,
        agent_id=agent_id,
    )


async def poll_account(db: AsyncSession, account: McpConnection) -> int:
    """Poll one native account through the existing transactional trigger admission."""
    from app.services.integrations.triggers import poll_account as poll

    return await poll(db, account)
