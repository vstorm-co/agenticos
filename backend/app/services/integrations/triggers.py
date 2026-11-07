"""Native accounts feed the existing trigger admission, dedupe and transactional job queue."""

import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Mapping, Sequence
from uuid import UUID

from pydantic import JsonValue, SecretStr, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import deferred_savepoint
from app.core.exceptions import AppException, BadRequestError
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.mcp_connection import McpConnection
from app.repositories import agent_trigger_repo
from app.services.integrations.feeds import changes_since
from app.services.integrations.sheets_feed import rows_since, sheet_key
from app.services.portals import PolledEvent, PolledEvents, PortalError, get_adapter

logger = logging.getLogger(__name__)

_CURSOR = TypeAdapter(dict[str, JsonValue])


async def _message_reads(
    key: str,
    account: McpConnection,
    token: SecretStr,
    current: Sequence[AgentTrigger],
    admitted: Mapping[UUID, UUID],
    cursor: dict[str, JsonValue] | None,
) -> tuple[list[tuple[PolledEvents, dict[UUID, UUID]]], dict[str, JsonValue]]:
    from app.schemas.agent_trigger import IntegrationMessageTriggerConfig
    from app.services.integrations.teams_feed import changes as teams_changes

    groups: dict[tuple[str, ...], list[AgentTrigger]] = defaultdict(list)
    for trigger in current:
        channels = IntegrationMessageTriggerConfig.model_validate(trigger.event_config).channels
        groups[tuple(sorted(set(channels)))].append(trigger)
    stored = cursor.get("feeds") if cursor and "feeds" in cursor else None
    if cursor is not None and "feeds" in cursor and not isinstance(stored, dict):
        raise BadRequestError(message="The integration conversation cursor is invalid")
    reads: list[tuple[PolledEvents, dict[UUID, UUID]]] = []
    state: dict[str, JsonValue] = {}
    for channels, candidates in groups.items():
        identity = hashlib.sha256(json.dumps(channels).encode()).hexdigest()
        previous = stored.get(identity) if isinstance(stored, dict) else cursor
        if previous is not None and not isinstance(previous, dict):
            raise BadRequestError(message="The integration conversation cursor is invalid")
        try:
            if key == "teams" and account.auth_type == "application":
                changes = await teams_changes(
                    token,
                    previous,
                    channels=channels,
                    application=True,
                    subject=account.account_email,
                )
            else:
                changes = await changes_since(key, token, cursor=previous, channels=channels)
        except (AppException, PortalError) as exc:
            logger.warning(
                "native_conversation_poll_failed",
                extra={
                    "connection_id": str(account.id),
                    "portal_key": key,
                    "error": type(exc).__name__,
                },
            )
            if previous is not None:
                state[identity] = previous
            continue
        read = PolledEvents(
            events=tuple(
                PolledEvent(delivery_id=event.id, payload=event.payload) for event in changes.events
            ),
            cursor=changes.cursor,
        )
        reads.append((read, {trigger.id: admitted[trigger.id] for trigger in candidates}))
        state[identity] = changes.cursor
    return reads, {"feeds": state}


async def poll_account(db: AsyncSession, account: McpConnection) -> int:
    from app.schemas.agent_trigger import SheetsRowTriggerConfig
    from app.services.agent_trigger import AgentTriggerService
    from app.services.mcp_connection import McpConnectionService, account_source_organization
    from app.services.portal_catalog import get_portal

    organization_id = account.organization_id or account_source_organization(account)
    if organization_id is None:
        raise BadRequestError(message="This native trigger account has no source organization")
    connections = McpConnectionService(db)
    triggers = AgentTriggerService(db)
    groups: dict[str, list[AgentTrigger]] = defaultdict(list)
    for trigger in await agent_trigger_repo.list_for_connection(
        db, connection_id=account.id, organization_id=organization_id
    ):
        if trigger.is_active and trigger.portal_key:
            groups[trigger.portal_key].append(trigger)
    positions = _CURSOR.validate_python((account.poll_cursor or {}).get("products") or {})
    queued = 0
    for key, candidates in groups.items():
        portal = get_portal(key)
        if portal is None or portal.delivery.value != "polling":
            continue
        if portal.native_provider != account.catalog_key:
            raise BadRequestError(
                message="This trigger source belongs to another integration provider"
            )
        try:
            async with deferred_savepoint(db):
                admitted = await triggers.polled_source_admissions(
                    organization_id=organization_id,
                    event_source=portal.event_source,
                    connection=account,
                )
                current = [trigger for trigger in candidates if trigger.id in admitted]
                if not current:
                    continue
                old = positions.get(key)
                cursor = old if isinstance(old, dict) else None
                partitions: list[tuple[PolledEvents, Mapping[UUID, UUID]]] | None = None
                if account.catalog_key == "odoo":
                    from app.services.integrations.odoo_feed import changes as odoo_changes

                    changes = await odoo_changes(
                        connections.integration_odoo_credential(
                            account, organization_id=organization_id
                        ),
                        key,
                        cursor,
                    )
                    read = PolledEvents(
                        events=tuple(
                            PolledEvent(delivery_id=event.id, payload=event.payload)
                            for event in changes.events
                        ),
                        cursor=changes.cursor,
                    )
                elif key == "imap":
                    from app.services.integrations.imap import changed_mail

                    credential = connections.integration_mail_credential(
                        account, organization_id=organization_id
                    )
                    events, next_cursor = await changed_mail(credential, cursor)
                    read = PolledEvents(
                        events=tuple(
                            PolledEvent(
                                delivery_id=f"imap:{next_cursor['uidvalidity']}:{event['uid']}",
                                payload=event,
                            )
                            for event in events
                        ),
                        cursor=next_cursor,
                    )
                else:
                    token = await connections.integration_access_token(
                        account, organization_id=organization_id
                    )
                    if token is None:
                        raise BadRequestError(message="Reconnect this native trigger account")
                    if key in {"slack", "teams"}:
                        message_reads, conversation_cursor = await _message_reads(
                            key, account, token, current, admitted, cursor
                        )
                        partitions = [(part, admissions) for part, admissions in message_reads]
                        read = PolledEvents(events=(), cursor=conversation_cursor)
                    elif key == "google_sheets":
                        state = dict(cursor or {})
                        found: list[PolledEvent] = []
                        selected = {
                            sheet_key(parsed.spreadsheet_id, parsed.sheet_name): parsed
                            for trigger in current
                            if (
                                parsed := SheetsRowTriggerConfig.model_validate(
                                    trigger.event_config
                                )
                            )
                        }
                        for target, config in selected.items():
                            old_sheet = state.get(target)
                            changes = await rows_since(
                                token,
                                old_sheet if isinstance(old_sheet, dict) else None,
                                spreadsheet_id=config.spreadsheet_id,
                                sheet_name=config.sheet_name,
                            )
                            state[target] = changes.cursor
                            found.extend(
                                PolledEvent(delivery_id=event.id, payload=event.payload)
                                for event in changes.events
                            )
                        read = PolledEvents(events=tuple(found), cursor=state)
                    else:
                        adapter = get_adapter(key)
                        if adapter is None:
                            raise BadRequestError(
                                message="No native reader is available for this trigger source"
                            )
                        if (
                            account.auth_type == "application"
                            and account.catalog_key == "microsoft"
                        ):
                            from app.services.portals.microsoft_files import (
                                MicrosoftFilesPortalAdapter,
                            )
                            from app.services.portals.outlook import OutlookPortalAdapter
                            from app.services.portals.outlook_calendar import (
                                OutlookCalendarPortalAdapter,
                            )

                            if key == "microsoft":
                                adapter = OutlookPortalAdapter(subject=account.account_email)
                            elif key == "outlook_calendar":
                                adapter = OutlookCalendarPortalAdapter(
                                    subject=account.account_email
                                )
                            else:
                                adapter = MicrosoftFilesPortalAdapter(subject=account.account_email)
                        places = await triggers.polled_places(
                            organization_id=organization_id,
                            event_source=portal.event_source,
                            source_admissions=admitted,
                        )
                        read = await adapter.poll(
                            access_token=token.get_secret_value(), cursor=cursor, places=places
                        )
                group_queued = 0
                for part, admissions in [(read, admitted)] if partitions is None else partitions:
                    decisions = await triggers.prepare_polled_fires(
                        organization_id=organization_id,
                        event_source=portal.event_source,
                        events=part.events,
                        announced={},
                        source_admissions=admissions,
                    )
                    for decision in decisions:
                        await triggers.queue_fire(
                            decision.trigger_id,
                            organization_id=organization_id,
                            event_context=decision.event_context,
                            source_policy_id=decision.source_policy_id,
                        )
                    group_queued += len(decisions)
                next_cursor = _CURSOR.validate_python(read.cursor)
        except (AppException, PortalError) as exc:
            logger.warning(
                "native_product_poll_failed",
                extra={
                    "connection_id": str(account.id),
                    "portal_key": key,
                    "error": type(exc).__name__,
                },
            )
            continue
        queued += group_queued
        positions[key] = next_cursor
    await connections.store_poll_cursor(account, cursor={"products": positions})
    return queued
