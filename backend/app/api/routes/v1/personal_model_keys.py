"""Personal LLM connections; membership and agent run access, no organization-management gate."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, PersonalModelKeySvc
from app.schemas.personal_model_key import (
    AgentModelConnectionRead,
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
