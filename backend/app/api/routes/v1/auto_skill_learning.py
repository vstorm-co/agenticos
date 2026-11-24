"""Automatic skill learning: apply an approved proposal to its named skill.

One route, under the agent the proposal was written for:
`POST /v1/agents/{agent_id}/learned-skills`.

This route carries no `require(...)` gate: like the skill routes, it
delegates to `AutoSkillLearningService`, which resolves `AGENTS_VIEW` on the
agent and `SKILLS_EDIT` on the skill, so a grant on a single skill is not
refused by a role-level gate. The response says whether the approved text was
updated or was already present — learning the same proposal twice writes
nothing the second time.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Auth, AutoSkillLearningSvc
from app.schemas.auto_skill_learning import LearnedSkillRead, LearnSkillCreate

router = APIRouter()


@router.post("/agents/{agent_id}/learned-skills", response_model=LearnedSkillRead)
async def learn_skill(
    agent_id: UUID, data: LearnSkillCreate, service: AutoSkillLearningSvc, ctx: Auth
) -> Any:
    """Learn one human-approved skill-target proposal into the catalog.

    The proposal must already be applied. The service loads it within this
    organization and agent, checks the submitted fields against it, and uses
    its stored provenance for the audit trail.
    """
    return await service.learn(ctx, agent_id, data)
