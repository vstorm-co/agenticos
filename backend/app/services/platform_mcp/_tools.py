"""The tools the platform's MCP server offers: the public API, one operation each.

Every description names the permission the call needs, because the caller's key
or token decides what succeeds and a model told up front stops asking for what
it will be refused. Reads are marked read-only; nothing here deletes, publishes
or touches a credential (#2058).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from app.services.platform_mcp._api import PlatformApi

_READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

InviteRole = Literal["admin", "builder", "operator", "member", "viewer"]


def register_tools(server: MCPServer, api: PlatformApi) -> None:
    @server.tool(annotations=_READ)
    async def whoami() -> dict[str, Any]:
        """Which organization this connection acts in, and the permissions it holds there."""
        return await api.request("GET", "/me/permissions")

    @server.tool(annotations=_READ)
    async def list_agents(limit: int = 50, skip: int = 0) -> dict[str, Any]:
        """The agents this caller can see. Needs `agents:view`."""
        return await api.request("GET", "/agents", params={"limit": limit, "skip": skip})

    @server.tool(annotations=_READ)
    async def get_agent(agent_id: UUID) -> dict[str, Any]:
        """One agent: its draft and published spec, status and labels. Needs `agents:view`."""
        return await api.request("GET", f"/agents/{agent_id}")

    @server.tool(annotations=_WRITE)
    async def create_agent(
        name: str, instructions: str, description: str | None = None
    ) -> dict[str, Any]:
        """Create an agent draft from a name and instructions. Needs `agents:edit`.

        The draft is not published: a person reviews and publishes it in the
        console, where capabilities, knowledge and limits are added.
        """
        spec: dict[str, Any] = {"name": name, "instructions": instructions}
        if description:
            spec["description"] = description
        return await api.request("POST", "/agents", json={"spec": spec})

    @server.tool(annotations=_WRITE)
    async def run_agent(
        agent_id: UUID, prompt: str, conversation_id: UUID | None = None
    ) -> dict[str, Any]:
        """Ask a published agent something and wait for its answer. Needs `agents:run`.

        The run is recorded, budgeted and audited like any other; the answer
        carries `run_id` and its cost. Pass `conversation_id` to continue a thread.
        """
        body: dict[str, Any] = {"prompt": prompt}
        if conversation_id is not None:
            body["conversation_id"] = str(conversation_id)
        return await api.request("POST", f"/agents/{agent_id}/run", json=body)

    @server.tool(annotations=_READ)
    async def list_runs(
        agent_id: UUID | None = None, limit: int = 20, skip: int = 0
    ) -> dict[str, Any]:
        """Recent runs, newest first, with status, tokens and cost. Needs `runs:view`."""
        params: dict[str, Any] = {"limit": limit, "skip": skip}
        if agent_id is not None:
            params["agent_id"] = str(agent_id)
        return await api.request("GET", "/runs", params=params)

    @server.tool(annotations=_READ)
    async def get_run(run_id: UUID) -> dict[str, Any]:
        """One run: status, the error a failed one stopped on, tokens and cost.

        Needs `runs:view`, or to be the person the run ran as.
        """
        return await api.request("GET", f"/runs/{run_id}")

    @server.tool(annotations=_READ)
    async def list_knowledge_bases() -> dict[str, Any]:
        """The knowledge bases this caller can see, with each one's `collection_name`.

        Needs `collections:view`.
        """
        return await api.request("GET", "/kb")

    @server.tool(annotations=_WRITE)
    async def create_knowledge_base(name: str, description: str | None = None) -> dict[str, Any]:
        """Create an organization knowledge base with the deployment's defaults.

        Needs `collections:edit`.
        """
        body: dict[str, Any] = {"name": name, "scope": "org"}
        if description:
            body["description"] = description
        return await api.request("POST", "/kb", json=body)

    @server.tool(annotations=_WRITE)
    async def add_document(kb_id: UUID, filename: str, content: str) -> dict[str, Any]:
        """Add a text document to a knowledge base; it is parsed and indexed in the background.

        `filename` decides the format by its extension - `.md` or `.txt` for text.
        Needs `collections:edit` on that knowledge base.
        """
        return await api.request(
            "POST",
            f"/kb/{kb_id}/documents",
            files={"file": (filename, content.encode("utf-8"), "text/plain")},
        )

    @server.tool(annotations=_READ)
    async def search_knowledge(collection_name: str, query: str, limit: int = 4) -> dict[str, Any]:
        """Semantic search in one knowledge base, by its `collection_name`.

        Needs `collections:view` on it.
        """
        return await api.request(
            "POST",
            "/rag/search",
            json={"collection_name": collection_name, "query": query, "limit": limit},
        )

    @server.tool(annotations=_READ)
    async def list_skills() -> dict[str, Any]:
        """The skills this caller can see. Needs `skills:view`."""
        return await api.request("GET", "/skills")

    @server.tool(annotations=_READ)
    async def list_members() -> dict[str, Any]:
        """The members of this connection's organization, with their roles."""
        organization_id = (await api.request("GET", "/me/permissions"))["organization_id"]
        return await api.request("GET", f"/orgs/{organization_id}/members")

    @server.tool(annotations=_WRITE)
    async def invite_member(email: str, role: InviteRole = "member") -> dict[str, Any]:
        """Invite somebody to this organization by email. Needs `members:manage`.

        They receive an email with a link to join. A role above your own is refused.
        """
        organization_id = (await api.request("GET", "/me/permissions"))["organization_id"]
        return await api.request(
            "POST",
            f"/orgs/{organization_id}/invitations",
            json={"email": email, "role": role},
        )
