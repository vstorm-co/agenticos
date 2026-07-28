"""Managing the widgets an agent is published as.

Per-resource routes, so no `require(...)` gate: whether this caller may publish
*this* agent is a question only `resolve_access` can answer, and a role gate
here would refuse a Builder holding an explicit grant on the agent.

The listing hangs off the agent (`/agents/{id}/embeds`) because that is the
question people ask - "where is this agent live?" - while editing and deleting
address the widget by its own id, which is what a table row has.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, status

from app.api.deps import Auth, EmbedSvc
from app.schemas.agent_embed import EmbedCreate, EmbedList, EmbedRead, EmbedUpdate

router = APIRouter()


@router.get("/{agent_id}/embeds", response_model=EmbedList)
async def list_embeds(agent_id: UUID, service: EmbedSvc, ctx: Auth) -> Any:
    """Every widget publishing this agent."""
    items = await service.list_for_agent(ctx, agent_id)
    return EmbedList(items=items, total=len(items))


@router.post("/embeds", response_model=EmbedRead, status_code=status.HTTP_201_CREATED)
async def create_embed(data: EmbedCreate, service: EmbedSvc, ctx: Auth) -> Any:
    """Publish an agent as a widget and return the snippet to paste."""
    return await service.create(ctx, data)


@router.patch("/embeds/{embed_id}", response_model=EmbedRead)
async def update_embed(embed_id: UUID, data: EmbedUpdate, service: EmbedSvc, ctx: Auth) -> Any:
    """Change a widget's look, origins, context or auth."""
    return await service.update(ctx, embed_id, data)


@router.delete("/embeds/{embed_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_embed(embed_id: UUID, service: EmbedSvc, ctx: Auth) -> None:
    """Take a widget down. Every page carrying its key stops working at once."""
    await service.delete(ctx, embed_id)
