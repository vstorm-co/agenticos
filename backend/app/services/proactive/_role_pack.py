"""Installing a role pack: its routines, on the starter agent, as the person (#2301)."""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.repositories import agent_trigger_repo, member_repo
from app.schemas.agent_trigger import TriggerCreate
from app.services.agent_trigger import AgentTriggerService
from app.services.proactive._thinker import ProactiveThinker
from app.services.role_packs import pack, routines_of

logger = logging.getLogger(__name__)


async def install(db: AsyncSession, organization_id: UUID, user_id: UUID, pack_id: str) -> int:
    """Create the pack's routines for this person. Returns how many were made.

    A routine they already have with the same prompt is not made twice, so an
    attempt the worker lost and repeated finishes the pack instead of doubling
    it. The routines are made the way the routine dialog makes them - as the
    person, through `AgentTriggerService.create`, which checks they may run the
    starter agent.
    """
    role_pack = pack(pack_id)
    member = await member_repo.get_active(db, organization_id=organization_id, user_id=user_id)
    agent = await ProactiveThinker(db).starter_agent(organization_id)
    if role_pack is None or member is None or agent is None:
        return 0
    ctx = AuthContext(user_id=user_id, organization_id=organization_id, role=member.role)
    existing = set(
        await agent_trigger_repo.prompts_created_by(
            db, organization_id=organization_id, user_id=user_id
        )
    )
    service = AgentTriggerService(db)
    made = 0
    for template in routines_of(role_pack):
        if template.prompt in existing or template.suggested_cadence is None:
            continue
        cadence = template.suggested_cadence
        await service.create(
            ctx,
            agent.id,
            TriggerCreate(
                name=template.label,
                prompt=template.prompt,
                trigger_type="schedule",
                schedule_kind=cadence.schedule_kind,
                interval_seconds=cadence.interval_seconds,
                cron_expression=cadence.cron_expression,
            ),
        )
        made += 1
    logger.info(
        "role_pack_installed",
        extra={"organization_id": str(organization_id), "pack": pack_id, "routines": made},
    )
    return made
