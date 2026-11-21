"""A synthetic, read-only Notion source for the isolated watch scenario."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from app.agents.mcp import probe_mcp_server
from app.agents.spec import AgentSpec, PersonalMcpServerRef
from app.core.permissions import AuthContext
from app.db.session import get_db_context
from app.repositories import agent_repo, organization_repo
from app.schemas.mcp_connection import McpConnectionCreate
from app.services.agent_registry import AgentRegistryService
from app.services.mcp_connection import McpConnectionService

SOURCE_URL = "http://eval-notion:8000/mcp"
AGENT_NAME = "Eval Notion Watch"
CATALOG_KEY = "notion"
SOURCE_TOOLS = ["search"]


@asynccontextmanager
async def notion_watch_source(
    ctx: AuthContext, profile_id: UUID
) -> AsyncIterator[tuple[UUID, UUID]]:
    """Publish a watch-compatible agent and attach the fixture for this case only."""
    await probe_mcp_server(SOURCE_URL)
    async with get_db_context() as db:
        org = await organization_repo.get_by_id(db, ctx.organization_id)
        if org is None:
            raise SystemExit("The eval organization does not exist.")
        saved_watch_policy = org.proactive_watches_enabled, org.proactive_watch_min_minutes
        await organization_repo.set_watch_policy(db, org, enabled=True, min_minutes=30)
        agent = await agent_repo.get_by_slug(
            db, "eval-notion-watch", organization_id=ctx.organization_id
        )
        if agent is None:
            registry = AgentRegistryService(db)
            agent = await registry.create(
                ctx,
                AgentSpec(
                    name=AGENT_NAME,
                    description="Published test agent for the personal Notion Releases source.",
                    instructions="Read only the synthetic release records for the approved watch.",
                    model_profile_id=profile_id,
                    mcp_servers=[
                        PersonalMcpServerRef(
                            account="personal", catalog_key=CATALOG_KEY, allowed_tools=SOURCE_TOOLS
                        )
                    ],
                ),
            )
            await registry.publish(ctx, agent.id)
        connection = await McpConnectionService(db).create(
            user_id=ctx.subject_id,
            data=McpConnectionCreate(
                name="eval-notion",
                label="Notion Releases · eval fixture",
                catalog_key=CATALOG_KEY,
                url=SOURCE_URL,
                allowed_tools=SOURCE_TOOLS,
            ),
        )
        agent_id, connection_id = agent.id, connection.id
    try:
        yield agent_id, connection_id
    finally:
        async with get_db_context() as db:
            org = await organization_repo.get_by_id(db, ctx.organization_id)
            if org is not None:
                enabled, min_minutes = saved_watch_policy
                await organization_repo.set_watch_policy(
                    db, org, enabled=enabled, min_minutes=min_minutes
                )
            await McpConnectionService(db).delete(
                user_id=ctx.subject_id, connection_id=connection_id
            )


server = FastMCP("Eval Notion")


@server.tool(annotations=ToolAnnotations(read_only_hint=True))
def search(query: str) -> dict[str, object]:
    """Find the synthetic Notion Releases database by title."""
    matches = "release" in query.casefold()
    return {
        "results": [
            {
                "id": "2a000000-0000-4000-8000-000000000001",
                "title": "Releases",
                "properties": {"Approval status": "Pending"},
            }
        ]
        if matches
        else [],
    }


if __name__ == "__main__":
    # Compose exposes this read-only fixture only to the test stack network.
    server.run(transport="streamable-http", host="0.0.0.0", port=8000)  # noqa: S104
