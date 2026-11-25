"""Personal LLM connections; membership and agent run access, no organization-management gate."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, CopilotSignInSvc, PersonalModelKeySvc
from app.schemas.personal_model_key import (
    AgentModelConnectionRead,
    CopilotSignInChallenge,
    CopilotSignInPoll,
    CopilotSignInResult,
    CopilotSignInStart,
    PersonalModelKeyCreate,
    PersonalModelKeyList,
)

router = APIRouter()


@router.get("", response_model=PersonalModelKeyList)
async def mine(ctx: Auth, service: PersonalModelKeySvc) -> Any:
    return {"items": await service.mine(ctx)}


@router.get("/agents/{agent_id}", response_model=AgentModelConnectionRead)
async def connection(agent_id: UUID, ctx: Auth, service: PersonalModelKeySvc) -> Any:
    return await service.status(ctx, agent_id)


@router.put("/agents/{agent_id}", response_model=AgentModelConnectionRead)
async def connect(
    agent_id: UUID, data: PersonalModelKeyCreate, ctx: Auth, service: PersonalModelKeySvc
) -> Any:
    return await service.save(ctx, agent_id, data)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def disconnect(key_id: UUID, ctx: Auth, service: PersonalModelKeySvc) -> Any:
    await service.delete(ctx, key_id)


@router.post("/agents/{agent_id}/copilot/sign-in", response_model=CopilotSignInChallenge)
async def copilot_sign_in(
    agent_id: UUID, data: CopilotSignInStart, ctx: Auth, service: CopilotSignInSvc
) -> Any:
    """Start this person's Copilot device sign-in for the agent's approved model."""
    return await service.start(ctx, agent_id, data.expected_destination)


@router.post("/agents/{agent_id}/copilot/poll", response_model=CopilotSignInResult)
async def copilot_poll(
    agent_id: UUID, data: CopilotSignInPoll, ctx: Auth, service: CopilotSignInSvc
) -> Any:
    """Check one authorization interval; tokens never leave the personal vault."""
    return await service.poll(ctx, agent_id, data.handle)
