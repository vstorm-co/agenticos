"""B52/B53 — in-app notify + round-robin/auto-assign when widget enters queue."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.permissions import OrgRoleName
from app.db.models.notification import NotificationEventType
from app.repositories import member as member_repo
from app.services.notification_center import NotificationCenterService
from app.services.shop_live_agent_recipient import list_customer_care_user_ids
from app.services.shop_live_agent_round_robin import pick_round_robin_user_id
from app.services.shop_live_agent_settings import (
    resolve_auto_assign_enabled,
    resolve_round_robin_enabled,
)
from app.services.shop_channel_conversation import ShopChannelConversationService
from app.services.shop_widget_studio_handling import claim_widget_conversation

logger = logging.getLogger(__name__)

_STUDIO_CONVERSATIONS_PATH = "/studio/agents/conversations"


async def _fallback_org_recipient_ids(
    db: AsyncSession,
    *,
    organization_id: UUID,
) -> list[UUID]:
    return await member_repo.list_member_ids_by_role(
        db,
        organization_id=organization_id,
        roles=[OrgRoleName.OWNER.value, OrgRoleName.ADMIN.value],
    )


async def notify_widget_live_agent_queued(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    conversation_id: UUID,
    customer_label: str,
    preview: str,
) -> None:
    if not settings.SHOP_AI_NATIVE_WIDGET_QUEUE_NOTIFY_ENABLED:
        return

    round_robin = await resolve_round_robin_enabled(db, organization_id=organization_id)
    auto_assign = await resolve_auto_assign_enabled(db, organization_id=organization_id)

    cs_ids = await list_customer_care_user_ids(db, tenant_id=tenant_id)
    assignee_id: UUID | None = None
    if cs_ids:
        if round_robin and len(cs_ids) > 1:
            assignee_id = await pick_round_robin_user_id(
                db,
                organization_id=organization_id,
                candidate_ids=cs_ids,
            )
        else:
            assignee_id = cs_ids[0]

    if auto_assign and assignee_id is not None:
        try:
            await claim_widget_conversation(
                db,
                organization_id=organization_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                claimed_by_user_id=assignee_id,
                claimed_by_name=None,
            )
        except Exception:
            logger.exception(
                "widget_queue_auto_assign_failed org=%s conv=%s assignee=%s",
                organization_id,
                conversation_id,
                assignee_id,
            )

    if cs_ids:
        if assignee_id is not None and round_robin and len(cs_ids) > 1:
            recipients = [assignee_id]
        else:
            recipients = cs_ids
    else:
        recipients = await _fallback_org_recipient_ids(db, organization_id=organization_id)

    if not recipients:
        logger.info(
            "widget_queue_notify_skipped_no_recipients",
            extra={"organization_id": str(organization_id), "conversation_id": str(conversation_id)},
        )
        return

    summary = f"Shop AI — khách chờ nhân viên ({customer_label})"
    snippet = (preview or "").strip()[:500]
    try:
        await NotificationCenterService(db).write(
            recipients=recipients,
            event_type=NotificationEventType.SHOP_LIVE_AGENT_QUEUED,
            occurrence_id=f"shop-widget-queue:{conversation_id}",
            summary=summary if not snippet else f"{summary}: {snippet[:120]}",
            context_url=_STUDIO_CONVERSATIONS_PATH,
            organization_id=organization_id,
            render_context={
                "channel": "widget",
                "conversation_id": str(conversation_id),
                "customer_label": customer_label,
                "preview": snippet,
                "round_robin_enabled": round_robin,
                "auto_assign_enabled": auto_assign,
                "assignee_user_id": str(assignee_id) if assignee_id else None,
            },
            use_savepoint=True,
        )
    except Exception:
        logger.exception(
            "widget_queue_notify_failed org=%s conv=%s",
            organization_id,
            conversation_id,
        )


async def notify_channel_live_agent_queued(
    db: AsyncSession,
    *,
    organization_id: UUID,
    tenant_id: UUID,
    session_id: UUID,
    channel: str,
    customer_label: str,
    preview: str,
) -> None:
    """In-app notify (+ optional auto-claim) when Zalo/Messenger enters queued."""
    if not settings.SHOP_AI_NATIVE_CHANNEL_QUEUE_NOTIFY_ENABLED:
        return

    round_robin = await resolve_round_robin_enabled(db, organization_id=organization_id)
    auto_assign = await resolve_auto_assign_enabled(db, organization_id=organization_id)

    cs_ids = await list_customer_care_user_ids(db, tenant_id=tenant_id)
    assignee_id: UUID | None = None
    if cs_ids:
        if round_robin and len(cs_ids) > 1:
            assignee_id = await pick_round_robin_user_id(
                db,
                organization_id=organization_id,
                candidate_ids=cs_ids,
            )
        else:
            assignee_id = cs_ids[0]

    if auto_assign and assignee_id is not None:
        try:
            await ShopChannelConversationService(db).claim_session(
                organization_id=organization_id,
                minerp_tenant_id=tenant_id,
                session_id=session_id,
                claimed_by_user_id=assignee_id,
                claimed_by_name=None,
            )
        except Exception:
            logger.exception(
                "channel_queue_auto_assign_failed org=%s session=%s assignee=%s",
                organization_id,
                session_id,
                assignee_id,
            )

    if cs_ids:
        if assignee_id is not None and round_robin and len(cs_ids) > 1:
            recipients = [assignee_id]
        else:
            recipients = cs_ids
    else:
        recipients = await _fallback_org_recipient_ids(db, organization_id=organization_id)

    if not recipients:
        logger.info(
            "channel_queue_notify_skipped_no_recipients",
            extra={"organization_id": str(organization_id), "session_id": str(session_id)},
        )
        return

    channel_label = (channel or "channel").strip().lower()
    summary = f"Shop AI — khách chờ nhân viên ({channel_label}: {customer_label})"
    snippet = (preview or "").strip()[:500]
    try:
        await NotificationCenterService(db).write(
            recipients=recipients,
            event_type=NotificationEventType.SHOP_LIVE_AGENT_QUEUED,
            occurrence_id=f"shop-channel-queue:{session_id}",
            summary=summary if not snippet else f"{summary}: {snippet[:120]}",
            context_url=_STUDIO_CONVERSATIONS_PATH,
            organization_id=organization_id,
            render_context={
                "channel": channel_label,
                "channel_session_id": str(session_id),
                "customer_label": customer_label,
                "preview": snippet,
                "round_robin_enabled": round_robin,
                "auto_assign_enabled": auto_assign,
                "assignee_user_id": str(assignee_id) if assignee_id else None,
            },
            use_savepoint=True,
        )
    except Exception:
        logger.exception(
            "channel_queue_notify_failed org=%s session=%s",
            organization_id,
            session_id,
        )
