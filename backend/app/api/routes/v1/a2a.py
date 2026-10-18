"""Agents served over A2A: their cards, and the tasks other systems send them (#2092).

The card is read without a session - that is what A2A discovery is - and only an
agent its organization chose to serve has one. The task endpoint is part of the
public API: an organization key or an OAuth access token this deployment issued,
allowed to run the agent, sends `message/send` and gets a task back.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import A2AServerSvc, Auth, limit_agent_run
from app.api.public_api import PUBLIC
from app.schemas.a2a import PARSE_ERROR

card_router = APIRouter()
router = APIRouter(dependencies=[PUBLIC])


@card_router.get("/{agent_id}/.well-known/agent-card.json", response_model=None)
async def get_agent_card(agent_id: UUID, service: A2AServerSvc) -> Any:
    """The A2A agent card of an agent its organization serves.

    No session: a client reads the card to learn how to authenticate. An agent that
    is not served answers 404, whichever of the reasons it is.
    """
    card = await service.card(agent_id)
    return JSONResponse(card.model_dump(by_alias=True, exclude_none=True))


@router.post("/{agent_id}", response_model=None)
async def a2a_request(agent_id: UUID, request: Request, service: A2AServerSvc, ctx: Auth) -> Any:
    """One A2A JSON-RPC request: `message/send` runs the agent, `tasks/get` reads a task.

    Answered with HTTP 200 and a JSON-RPC result or error, as A2A expects. Each
    task is an ordinary run, recorded on the `a2a` surface, under the caller's
    key and its scopes. Only `message/send`, the one request that runs the
    agent, counts against the caller's run allowance: a client polling a task it
    started reads it every few seconds, and charged for that it ran out within a
    minute - before the answer it was waiting for. A refused or unknown method
    starts nothing either.
    """
    try:
        body = await request.json()
    except ValueError:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": PARSE_ERROR, "message": "Not JSON"}}
    if isinstance(body, dict) and body.get("method") == "message/send":
        await limit_agent_run(ctx)
    return await service.handle(ctx, agent_id, body)
