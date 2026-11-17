"""A watch gets one fixed account's changes, without a model-controlled cursor."""

import hashlib
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from pydantic_ai.toolsets import FunctionToolset

from app.agents.watch_sources import WatchReadReceipt
from app.core.exceptions import AuthorizationError, BadRequestError
from app.db.session import get_db_context
from app.repositories import mcp_connection_repo, watch_repo
from app.schemas.watch_sources import WatchSources
from app.services.integrations.feeds import changes_since
from app.services.mcp_connection import McpConnectionService, account_source_organization

_CURSOR = TypeAdapter(dict[str, JsonValue])


def build_watch_toolset(
    sources: WatchSources,
    receipt: WatchReadReceipt,
    *,
    organization_id: UUID,
    person_id: UUID,
    watch_id: UUID | None,
    agent_id: UUID,
) -> FunctionToolset[object]:
    cached: dict[str, JsonValue] | None = None

    async def read_changes() -> dict[str, JsonValue]:
        """Read only new items in this watch's approved integration account.

        Returns:
            New events since the last successfully consumed batch. An empty events
            list is a successful quiet check; the first check only establishes a baseline.
        """
        nonlocal cached
        if receipt.check is None or watch_id is None or sources.integration_product_id is None:
            raise AuthorizationError(message="This integration read requires an authorized watch")
        await receipt.check(agent_id)
        if cached is not None:
            return cached
        async with get_db_context() as db:
            account = await mcp_connection_repo.get_account(db, sources.connection_id)
            watch = await watch_repo.get_by_id(db, watch_id)
            if (
                account is None
                or watch is None
                or watch.connection_id != account.id
                or watch.organization_id != organization_id
                or watch.user_id != person_id
                or account.user_id != person_id
                or account.scope != "user"
                or account.purpose != "account"
                or not account.is_enabled
                or account.authorization_generation != sources.authorization_generation
                or account.catalog_key != sources.catalog_key
                or account_source_organization(account) != organization_id
                or hashlib.sha256(account.url.encode()).hexdigest() != sources.endpoint_hash
            ):
                raise AuthorizationError(
                    message="This integration watch's account authorization changed"
                )
            if account.catalog_key == "odoo":
                from app.services.integrations.odoo_feed import changes as odoo_changes

                credential = McpConnectionService(db).integration_odoo_credential(
                    account, organization_id=organization_id
                )
                read = await odoo_changes(
                    credential,
                    sources.integration_product_id,
                    _CURSOR.validate_python(watch.integration_cursor)
                    if watch.integration_cursor
                    else None,
                )
            elif sources.integration_product_id == "imap_mail":
                from app.services.integrations.feeds import Change, Changes
                from app.services.integrations.imap import changed_mail

                credential = McpConnectionService(db).integration_mail_credential(
                    account, organization_id=organization_id
                )
                events, cursor = await changed_mail(
                    credential,
                    _CURSOR.validate_python(watch.integration_cursor)
                    if watch.integration_cursor
                    else None,
                )
                read = Changes(
                    events=[
                        Change(id=f"imap:{cursor['uidvalidity']}:{event['uid']}", payload=event)
                        for event in events
                    ],
                    cursor=cursor,
                )
            else:
                token = await McpConnectionService(db).integration_access_token(
                    account, organization_id=organization_id
                )
                if token is None:
                    raise BadRequestError(
                        message="Reconnect this integration account before reading the watch"
                    )
                if sources.integration_product_id == "teams" and account.auth_type == "application":
                    from app.services.integrations.teams_feed import changes as teams_changes

                    read = await teams_changes(
                        token,
                        _CURSOR.validate_python(watch.integration_cursor)
                        if watch.integration_cursor
                        else None,
                        application=True,
                        channels=sources.integration_channels,
                        subject=account.account_email
                        if account.auth_type == "application"
                        else None,
                    )
                else:
                    read = await changes_since(
                        sources.integration_product_id,
                        token,
                        cursor=_CURSOR.validate_python(watch.integration_cursor)
                        if watch.integration_cursor
                        else None,
                        channels=sources.integration_channels,
                        subject=account.account_email
                        if account.auth_type == "application"
                        else None,
                    )
        receipt.integration_cursor = read.cursor
        cached = _CURSOR.validate_python(
            {"events": [event.model_dump(mode="json") for event in read.events]}
        )
        return cached

    toolset: FunctionToolset[object] = FunctionToolset()
    toolset.add_function(
        read_changes,
        name="read_integration_changes",
        metadata={"annotations": {"readOnlyHint": True}},
    )
    return toolset
