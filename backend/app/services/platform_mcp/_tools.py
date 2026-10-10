"""The platform's operations: the public API, one call each.

The MCP server registers them for Claude Code, any MCP client (#2058) and the
in-app AI Architect, which reaches the same server in-process (#2063) - so there
is one name, one description and one call for every caller.

Every description names the permission the call needs, because the caller's key
or token decides what succeeds and a model told up front stops asking for what
it will be refused. Nothing here publishes or touches a credential, and the one
thing that deletes is undoing an agent draft its caller owns and never published.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from app.services.platform_mcp._api import PlatformApi

InviteRole = Literal["admin", "builder", "operator", "member", "viewer"]


@dataclass(frozen=True)
class PlatformTool:
    name: str
    function: Callable[..., Awaitable[dict[str, Any]]]
    writes: bool
    """Whether it changes something. An MCP client is told so through the tool's
    read-only hint, which is also what holds the call for a person's approval
    under a binding's default `writes` policy."""

    @property
    def summary(self) -> str:
        """The first line of the description - what the Builder lists beside the tool."""
        return (self.function.__doc__ or "").strip().splitlines()[0]


def platform_tools(api: PlatformApi) -> tuple[PlatformTool, ...]:
    """Every operation, bound to `api`."""

    async def whoami() -> dict[str, Any]:
        """Which organization this connection acts in, and the permissions it holds there."""
        return await api.request("GET", "/me/permissions")

    async def list_agents(limit: int = 50, skip: int = 0) -> dict[str, Any]:
        """The agents this caller can see. Needs `agents:view`."""
        return await api.request("GET", "/agents", params={"limit": limit, "skip": skip})

    async def get_agent(agent_id: UUID) -> dict[str, Any]:
        """One agent: its draft and published spec, status and labels. Needs `agents:view`."""
        return await api.request("GET", f"/agents/{agent_id}")

    async def create_agent_draft(
        name: str, instructions: str, description: str | None = None
    ) -> dict[str, Any]:
        """Create an agent draft from a name and instructions. Needs `agents:edit`.

        The draft is not published: a person reviews and publishes it in the
        console, where capabilities, knowledge and limits are added.
        """
        # Able to ask the person questions, like every agent the console creates.
        spec: dict[str, Any] = {
            "name": name,
            "instructions": instructions,
            "capabilities": [{"id": "ask_user"}],
        }
        if description:
            spec["description"] = description
        return await api.request("POST", "/agents", json={"spec": spec})

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

    async def discard_agent_draft(agent_id: UUID) -> dict[str, Any]:
        """Undo an agent draft you created: delete it, if it was never published.

        Refused for an agent somebody else owns or one that has a published version -
        undoing is for a draft made by mistake, not for retiring an agent. Needs
        `agents:delete` on it.
        """
        me = await api.request("GET", "/me/permissions")
        if "user_id" not in me:
            return me
        agent = await api.request("GET", f"/agents/{agent_id}")
        if "id" not in agent:
            return agent
        if agent.get("owner_user_id") != me["user_id"]:
            return api.refuse("Only an agent draft you created yourself can be undone")
        if agent.get("current_version_id") is not None:
            return api.refuse(
                "This agent has been published, so it is not undone from here - "
                "archive or delete it in the console"
            )
        await api.request("DELETE", f"/agents/{agent_id}")
        return {"discarded": str(agent_id), "name": agent.get("name")}

    async def get_spend(days: int = 30) -> dict[str, Any]:
        """What the organization's agents cost: month to date, and per agent over `days`.

        Needs `runs:view`.
        """
        return await api.request("GET", "/spend", params={"days": days})

    async def list_runs(
        agent_id: UUID | None = None, limit: int = 20, skip: int = 0
    ) -> dict[str, Any]:
        """Recent runs, newest first, with status, tokens and cost. Needs `runs:view`."""
        params: dict[str, Any] = {"limit": limit, "skip": skip}
        if agent_id is not None:
            params["agent_id"] = str(agent_id)
        return await api.request("GET", "/runs", params=params)

    async def get_run(run_id: UUID) -> dict[str, Any]:
        """One run: status, the error a failed one stopped on, tokens and cost.

        Needs `runs:view`, or to be the person the run ran as.
        """
        return await api.request("GET", f"/runs/{run_id}")

    async def list_knowledge_bases() -> dict[str, Any]:
        """The knowledge bases this caller can see, with each one's `collection_name`.

        Needs `collections:view`.
        """
        return await api.request("GET", "/kb")

    async def create_knowledge_base(name: str, description: str | None = None) -> dict[str, Any]:
        """Create an organization knowledge base with the deployment's defaults.

        Needs `collections:edit`.
        """
        body: dict[str, Any] = {"name": name, "scope": "org"}
        if description:
            body["description"] = description
        return await api.request("POST", "/kb", json=body)

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

    async def search_knowledge(collection_name: str, query: str, limit: int = 4) -> dict[str, Any]:
        """Semantic search in one knowledge base, by its `collection_name`.

        Needs `collections:view` on it.
        """
        return await api.request(
            "POST",
            "/rag/search",
            json={"collection_name": collection_name, "query": query, "limit": limit},
        )

    async def list_skills() -> dict[str, Any]:
        """The skills this caller can see. Needs `skills:view`."""
        return await api.request("GET", "/skills")

    async def list_members() -> dict[str, Any]:
        """The members of this connection's organization, with their roles."""
        me = await api.request("GET", "/me/permissions")
        if "organization_id" not in me:
            return me
        return await api.request("GET", f"/orgs/{me['organization_id']}/members")

    async def invite_member(email: str, role: InviteRole = "member") -> dict[str, Any]:
        """Invite somebody to this organization by email. Needs `members:manage`.

        They receive an email with a link to join. A role above your own is refused.
        """
        me = await api.request("GET", "/me/permissions")
        if "organization_id" not in me:
            return me
        return await api.request(
            "POST",
            f"/orgs/{me['organization_id']}/invitations",
            json={"email": email, "role": role},
        )

    operations = (
        (whoami, False),
        (list_agents, False),
        (get_agent, False),
        (create_agent_draft, True),
        (discard_agent_draft, True),
        (run_agent, True),
        (list_runs, False),
        (get_run, False),
        (get_spend, False),
        (list_knowledge_bases, False),
        (create_knowledge_base, True),
        (add_document, True),
        (search_knowledge, False),
        (list_skills, False),
        (list_members, False),
        (invite_member, True),
    )
    return tuple(
        PlatformTool(name=function.__name__, function=function, writes=writes)
        for function, writes in operations
    )
