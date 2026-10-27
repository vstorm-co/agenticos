"""The platform's operations: the public API, one call each.

The MCP server registers them for Claude Code, any MCP client (#2058) and the
in-app AI Architect, which reaches the same server in-process (#2063) - so there
is one name, one description and one call for every caller.

Every description names the permission the call needs, because the caller's key
or token decides what succeeds and a model told up front stops asking for what
it will be refused. Nothing here touches a credential. What deletes is undoing an
agent draft its caller owns and never published, and removing a routine; what
publishes is `publish_agent`, and `accept_improvement` when the person asked to
publish, each held for the person's approval like every write here but
`UNGATED` (#2301).
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import JsonValue

from app.agents.spec import CapabilityBindingSpec, McpServerRef
from app.schemas.user import ConsoleLocale
from app.services.platform_mcp._api import PlatformApi

InviteRole = Literal["admin", "builder", "operator", "member", "viewer"]

UNGATED = frozenset({"set_my_language"})
"""Writes no binding holds for a person's approval, whatever its policy.

Changing the console's language changes the person asking's own account on their
own word, and Settings undoes it - an approval card for "switch to English" would
be the whole conversation. `set_my_profile` is not here: what it saves is told to
every agent the person runs, in every organization, so a page an agent read must
not be able to write it unseen. `app.agents.mcp` names the same set as
`PLATFORM_UNGATED_TOOLS`, and a test holds the two equal.
"""


HELD = frozenset({"read_conversation", "get_project"})
"""Reads held for a person's approval under a binding's `writes` policy, like a write.

Reading a whole past conversation releases what somebody said before, to a model
that may also be reading a web page written to make it fetch that conversation
and send it on - `list_runs` names the conversations, this returns them. The
person sees which conversation before it is read (Codex on #2324). Project
instructions also require an explicit read: discovery must not load arbitrary
shared instructions into the model (Codex on #2507).
"""

_TOOL_FIELDS = frozenset({"last_tools", "allowed_tools"})
"""A connection's tools - what `list_my_connections` leaves out unless asked."""


@dataclass(frozen=True)
class PlatformTool:
    name: str
    function: Callable[..., Awaitable[dict[str, Any]]]
    writes: bool
    """Whether it changes something. An MCP client is told so through the tool's
    read-only hint, which is also what holds the call for a person's approval
    under a binding's default `writes` policy."""

    @property
    def held(self) -> bool:
        """Whether this read waits for approval as a write does - see `HELD`."""
        return self.name in HELD

    @property
    def ungated(self) -> bool:
        """Whether no binding holds a call to it for approval - see `UNGATED`."""
        return self.name in UNGATED

    @property
    def summary(self) -> str:
        """The first line of the description - what the Builder lists beside the tool."""
        return (self.function.__doc__ or "").strip().splitlines()[0]


def _merge_capabilities(
    current: list[CapabilityBindingSpec], additions: list[str | CapabilityBindingSpec]
) -> list[dict[str, JsonValue]]:
    """Upsert explicit fields; bare ids preserve an existing binding's settings."""
    bindings: dict[str, dict[str, JsonValue]] = {
        binding.id: binding.model_dump(mode="json", exclude_unset=True) for binding in current
    }
    for addition in additions:
        binding = CapabilityBindingSpec(id=addition) if isinstance(addition, str) else addition
        bindings[binding.id] = {
            **bindings.get(binding.id, {}),
            **binding.model_dump(mode="json", exclude_unset=True),
        }
    return list(bindings.values())


_SESSION_FIELDS = (
    "id",
    "status",
    "stage",
    "iteration",
    "max_iterations",
    "stop_reason",
    "spent_usd",
    "budget_usd",
    "created_at",
    "finished_at",
)
"""What a listing says about one improvement session; the rest is in `get_improvement`."""

_CASES_SHOWN = 5
"""Broken and fixed cases `get_eval_run` names, each; the run page has the rest."""

_INPUT_CHARS = 200


def improvement_link(agent_id: UUID | str, session_id: UUID | str) -> str:
    """Where the person follows a session step by step: the Improve wizard."""
    return f"/agents/{agent_id}/improve/{session_id}"


_CLOSED = frozenset({"accepted", "published", "rejected", "cancelled", "stale"})
"""A session that is a record now: nothing on it can be accepted, chosen or tried again."""

_DECISIONS = frozenset(
    {
        "improvement.accepted",
        "improvement.published",
        "improvement.discarded",
        "improvement.rejected",
        "improvement.cancelled",
    }
)


def _outcome(session: dict[str, Any]) -> dict[str, Any] | None:
    """What was decided on a closed session: the attempt, the version, by whom and when."""
    if session["status"] not in _CLOSED:
        return None
    best = session.get("best_iteration_id")
    attempt = next((it["number"] for it in session.get("iterations", []) if it["id"] == best), None)
    decisions = [
        event
        for event in session.get("timeline", [])
        if event["action"] in _DECISIONS and event.get("actor_user_id")
    ]
    decision = max(decisions, key=lambda event: event["at"], default=None)
    return {
        "status": session["status"],
        "attempt": attempt if session["status"] in ("accepted", "published") else None,
        "published_version": session.get("published_version"),
        "published_version_id": session.get("published_version_id"),
        "decided_by": decision and (decision.get("actor_name") or decision["actor_user_id"]),
        "decided_at": decision and decision["at"],
    }


_NEXT_STEPS = {
    "propose": {"after": "Understand", "next_step": "propose changes"},
    "check": {"after": "Changes", "next_step": "test the changes"},
}
"""Where a waiting session stopped and what pressing Next step runs, by its `next_step`."""


_CENT = Decimal("0.01")


def _session_limit(estimate: dict[str, Any]) -> str:
    """The spending limit the wizard offers: the start and every attempt, up to the cent."""
    whole = Decimal(estimate["total_usd"]) + estimate["max_iterations"] * Decimal(
        estimate["per_round_usd"]
    )
    return str(max(_CENT, whole.quantize(_CENT, rounding=ROUND_CEILING)))


def _waiting(session: dict[str, Any]) -> dict[str, Any] | None:
    """What a session paused between steps is waiting for."""
    if session["status"] != "waiting":
        return None
    return _NEXT_STEPS.get(session.get("next_step") or "")


def _session(agent_id: UUID | str, session: dict[str, Any]) -> dict[str, Any]:
    """A session as a listing reads it: where it stands, and what may still be done with it."""
    return {
        **{field: session.get(field) for field in _SESSION_FIELDS},
        "closed": session["status"] in _CLOSED,
        "can_accept": session["status"] == "ready",
        "waiting_for": _waiting(session),
        "outcome": _outcome(session),
        "link": improvement_link(agent_id, session["id"]),
    }


def _attempt(iteration: dict[str, Any], chosen: Any) -> dict[str, Any]:
    """One round of a session, as its verdict reads in plain numbers.

    Each attempt is measured on held-out questions of its own, against the agent
    as it is today on those same questions, so attempts compare by their change -
    fixed less broken - and never by their pass rates, which come from
    different questions.
    """
    detail = iteration.get("verdict_detail") or {}
    fixed, broken = detail.get("fixed"), detail.get("broken")
    return {
        "attempt": iteration["number"],
        "verdict": iteration.get("verdict"),
        "fixed": fixed,
        "broken": broken,
        "change": fixed - broken if fixed is not None and broken is not None else None,
        "held_out": detail.get("held_out"),
        "details": {
            "pass_rate_before": detail.get("baseline_pass_rate"),
            "pass_rate_after": detail.get("candidate_pass_rate"),
        },
        "cost_usd": iteration.get("cost_usd"),
        "chosen": iteration["id"] == chosen,
        "best": iteration.get("verdict") == "better",
    }


_CHOOSING = frozenset({"improvement.round_selected", "improvement.selection_confirmed"})


def _chosen_by(session: dict[str, Any]) -> str | None:
    """Who chose the session's attempt by hand; `None` when the session's own rule did."""
    choices = [
        event
        for event in session.get("timeline", [])
        if event["action"] in _CHOOSING and event.get("actor_user_id")
    ]
    choice = max(choices, key=lambda event: event["at"], default=None)
    return choice and (choice.get("actor_name") or choice["actor_user_id"])


def _topic_state(topic: dict[str, Any], deferred: set[Any]) -> str:
    """Where one missing-knowledge topic stands, in one word, as the knowledge gaps page shows it."""
    if topic.get("status") in ("covered", "dismissed"):
        return topic["status"]
    if topic.get("drafting"):
        return "drafting"
    if topic.get("draft_failed"):
        return "draft_failed"
    if topic.get("has_draft"):
        return "draft_stale" if topic.get("draft_stale") else "draft_ready"
    return "deferred" if topic["id"] in deferred else "missing"


_REASON_CHARS = 150


def _noise(noise: dict[str, Any] | None) -> dict[str, Any] | None:
    """How far a session's test can be trusted, its example questions cut short."""
    if noise is None:
        return None
    return {
        **noise,
        "examples": [
            {**example, "input": example["input"][:_INPUT_CHARS]}
            for example in noise.get("examples", [])
        ],
    }


def _judged(case: dict[str, Any], arm_id: Any) -> str | None:
    """Why the candidate's first answer to a case was graded as it was, in brief.

    Read off the API's own case listing, where a case from a conversation the
    caller cannot open already comes without its reasons.
    """
    attempts = sorted(
        (attempt for attempt in case.get("attempts", []) if attempt["arm_id"] == arm_id),
        key=lambda attempt: attempt["attempt"],
    )
    score = attempts[0].get("score") if attempts else None
    if not score:
        return None
    results = sorted(score.get("results", []), key=lambda result: result["scorer"] != "judge")
    reason = next((result["reason"] for result in results if result.get("reason")), None)
    return reason[:_REASON_CHARS] if reason else None


def _flips(cases: list[dict[str, Any]], flip: str) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case["case_id"],
            "input": case["input"][:_INPUT_CHARS],
            "confirmed": case["confirmed"],
        }
        for case in cases
        if case["flip"] == flip
    ][:_CASES_SHOWN]


def platform_tools(api: PlatformApi) -> tuple[PlatformTool, ...]:
    """Every operation, bound to `api`."""

    async def whoami() -> dict[str, Any]:
        """Which organization this connection acts in, and the permissions it holds there."""
        return await api.request("GET", "/me/permissions")

    async def list_projects(q: str | None = None, limit: int = 50, skip: int = 0) -> dict[str, Any]:
        """Find visible projects for ongoing work. Needs `projects:view`.

        Search by name or description before creating another project. Pages
        contain at most 100 projects; follow pagination when checking for a match.
        Only ids and names are returned; read a chosen project explicitly with get_project.
        """
        params: dict[str, str | int] = {"limit": limit, "skip": skip}
        if q is not None:
            params["q"] = q
        listing = await api.request("GET", "/projects", params=params)
        return {
            **listing,
            "items": [
                {field: item[field] for field in ("id", "name")} for item in listing["items"]
            ],
        }

    async def get_project(project_id: UUID) -> dict[str, Any]:
        """Read a project's instructions, default agent and workspace backend.

        Needs access to that project; waits for approval like reading a conversation.
        `state` stores shared files only; `service`
        provides a sandbox host. Check the actual runtime and agent's execution
        settings before promising code execution. Chats keep separate histories.
        """
        return await api.request("GET", f"/projects/{project_id}")

    async def create_project(
        name: str,
        instructions: str = "",
        description: str | None = None,
        default_agent_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Create a private home for ongoing work. Needs `projects:edit`; waits for approval.

        Propose Projects for work continued across chats: research, a wiki,
        writing, coding or recurring analysis. Save the agreed objective, file
        plan and verification rules in instructions (at most 20000 characters).
        Name is at most 120 characters; description at most 500. Use only a real
        agent id the caller may run, or leave the default unset.

        This creates a project, not its files, a new agent or a scheduled job.
        Open `/projects/<returned id>` and start New chat there: an existing
        conversation cannot be moved into it. Files and instructions are shared,
        not full conversation histories. Inspect the returned backend; files-only
        workspaces do not execute code. Sharing remains the caller's choice.
        """
        return await api.request(
            "POST",
            "/projects",
            json={
                "name": name,
                "instructions": instructions,
                "description": description,
                "default_agent_id": str(default_agent_id) if default_agent_id else None,
                "visibility": "private",
            },
        )

    async def list_agents(limit: int = 50, skip: int = 0) -> dict[str, Any]:
        """The agents this caller can see. Needs `agents:view`."""
        return await api.request("GET", "/agents", params={"limit": limit, "skip": skip})

    async def get_agent(agent_id: UUID) -> dict[str, Any]:
        """One agent: its draft and published spec, status and labels. Needs `agents:view`."""
        return await api.request("GET", f"/agents/{agent_id}")

    async def create_agent_draft(
        name: str,
        instructions: str,
        description: str | None = None,
        capabilities: list[str | CapabilityBindingSpec] | None = None,
        model_profile_id: UUID | None = None,
        starters: list[str] | None = None,
        mcp_servers: list[McpServerRef] | None = None,
        skill_ids: list[UUID] | None = None,
        collection_ids: list[UUID] | None = None,
    ) -> dict[str, Any]:
        """Create an agent draft from a name and instructions. Needs `agents:edit`.

        `capabilities` accepts ids from `list_capabilities` or objects with `id`,
        `config`, approval settings and secret references. Read the catalog's
        `config_schema` before choosing settings. For code execution use sandbox
        config `backend: service`, `include_execute: true`; discover connections
        with `list_sandbox_connections` and inspect `get_sandbox_policy` first.
        `mcp_servers` binds organization connection ids or personal catalog keys,
        never a personal connection id. `skill_ids` and `collection_ids` bind
        existing skills and knowledge bases. `model_profile_id` is
        one of `list_models`; a draft needs one before it can be tested or
        published. `starters` are up to four first messages the chat offers
        whoever opens the agent. Nothing goes live: try it with
        `test_agent_draft`, then `publish_agent` - or the person does both in the
        console.
        """
        # Able to ask the person questions, like every agent the console creates.
        spec: dict[str, Any] = {
            "name": name,
            "instructions": instructions,
            "capabilities": _merge_capabilities([], ["ask_user", *(capabilities or [])]),
        }
        if description:
            spec["description"] = description
        if model_profile_id is not None:
            spec["model_profile_id"] = str(model_profile_id)
        if starters:
            spec["starters"] = starters
        if mcp_servers is not None:
            spec["mcp_servers"] = [server.model_dump(mode="json") for server in mcp_servers]
        if skill_ids is not None:
            spec["skill_ids"] = [str(skill_id) for skill_id in skill_ids]
        if collection_ids is not None:
            spec["collection_ids"] = [str(collection_id) for collection_id in collection_ids]
        return await api.request("POST", "/agents", json={"spec": spec})

    async def update_agent_draft(
        agent_id: UUID,
        instructions: str | None = None,
        description: str | None = None,
        add_capabilities: list[str | CapabilityBindingSpec] | None = None,
        remove_capabilities: list[str] | None = None,
        model_profile_id: UUID | None = None,
        skill_ids: list[UUID] | None = None,
        collection_ids: list[UUID] | None = None,
        starters: list[str] | None = None,
        mcp_servers: list[McpServerRef] | None = None,
    ) -> dict[str, Any]:
        """Change an agent's draft - what its next publish makes live. Needs `agents:edit` on it.

        Only what you pass changes. `instructions` replaces the whole prompt, so
        read the current one with `get_agent` and send the edited text.
        `add_capabilities` accepts ids or configured binding objects from
        `list_capabilities`. Objects upsert only their supplied fields, preserving
        other settings; a supplied `config` replaces the whole config object, so
        read the draft first and retain settings you still need. A string leaves
        existing settings intact. `remove_capabilities` switches them off.
        `mcp_servers` replaces the whole MCP binding list; [] disconnects all.
        Bind organization connection ids or personal catalog keys, never personal
        connection ids. `skill_ids`,
        `collection_ids` (knowledge bases) and `starters` each replace their whole
        list. The published version keeps answering until `publish_agent`.
        """
        agent = await api.request("GET", f"/agents/{agent_id}")
        if "draft_spec" not in agent:
            return agent
        spec: dict[str, Any] = dict(agent["draft_spec"])
        if instructions is not None:
            spec["instructions"] = instructions
        if description is not None:
            spec["description"] = description
        if model_profile_id is not None:
            spec["model_profile_id"] = str(model_profile_id)
        removed = set(remove_capabilities or ())
        bindings = [binding for binding in spec["capabilities"] if binding["id"] not in removed]
        spec["capabilities"] = _merge_capabilities(
            [CapabilityBindingSpec.model_validate(binding) for binding in bindings],
            add_capabilities or [],
        )
        if mcp_servers is not None:
            spec["mcp_servers"] = [server.model_dump(mode="json") for server in mcp_servers]
        if skill_ids is not None:
            spec["skill_ids"] = [str(skill_id) for skill_id in skill_ids]
        if collection_ids is not None:
            spec["collection_ids"] = [str(collection_id) for collection_id in collection_ids]
        if starters is not None:
            spec["starters"] = starters
        return await api.request("PUT", f"/agents/{agent_id}/draft", json={"spec": spec})

    async def test_agent_draft(
        agent_id: UUID, prompt: str, conversation_id: UUID | None = None
    ) -> dict[str, Any]:
        """Try an agent's unpublished draft with one message and read its answer.

        A test run, as the Builder's test panel makes: budgeted, recorded and
        marked as a test. Refused with the reason when the draft would not publish -
        no model, a capability missing its key - so it is also the check before
        `publish_agent`. Pass the answer's `conversation_id` to ask a follow-up.
        Needs `agents:edit` on it.
        """
        body: dict[str, Any] = {"prompt": prompt, "draft": True}
        if conversation_id is not None:
            body["conversation_id"] = str(conversation_id)
        return await api.request("POST", f"/agents/{agent_id}/run", json=body)

    async def publish_agent(agent_id: UUID, note: str | None = None) -> dict[str, Any]:
        """Make an agent's draft the version that runs. Needs `agents:publish` on it.

        Runs the checks the console's Publish button runs, and a refusal says what
        to fix. Every place the agent answers - chat, a website widget, Slack -
        answers with the new version at once. `note` says why this version exists.
        Always waits for the person's approval.
        """
        body = {"note": note} if note else {}
        return await api.request("POST", f"/agents/{agent_id}/publish", json=body)

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
        `agents:edit` on it.
        """
        # The server decides on the locked row - whose draft it is and whether it
        # was published, a publish in another tab included. A read first would
        # also need `agents:view`, which a key issued only to edit does not have.
        deleted = await api.request("DELETE", f"/agents/{agent_id}", params={"draft_only": "true"})
        if deleted is not None:
            return deleted
        return {"discarded": str(agent_id)}

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
        """One run: status, the error a failed one stopped on, tokens and cost. Needs `runs:view`."""
        return await api.request("GET", f"/runs/{run_id}")

    async def read_conversation(
        conversation_id: UUID, limit: int = 100, skip: int = 0
    ) -> dict[str, Any]:
        """One of the asker's own conversations, turn by turn. Needs `runs:view`.

        What was asked and answered, oldest first, with the tools each turn called
        and what they returned - for making a skill of how something was done, or
        picking up where a conversation left off. Another member's conversation is
        not found.
        """
        return await api.request(
            "GET",
            f"/conversations/{conversation_id}/transcript",
            params={"limit": limit, "skip": skip},
        )

    async def list_knowledge_bases() -> dict[str, Any]:
        """The knowledge bases this caller can see, with each one's `collection_name`.

        Needs `collections:view`.
        """
        return await api.request("GET", "/kb")

    async def list_embedding_models() -> dict[str, Any]:
        """The providers this deployment can embed through, and the models each serves."""
        return await api.request("GET", "/rag/embedding-models")

    async def create_knowledge_base(
        name: str,
        embedding_provider: str,
        embedding_secret_id: UUID | None = None,
        embedding_endpoint_id: UUID | None = None,
        embedding_model: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create an organization knowledge base. Needs `collections:edit`.

        There is no deployment-wide embedding default: name the provider, and the
        vault key that pays for it (`embedding_secret_id`) - or, for a keyless
        provider, the local service it answers at (`embedding_endpoint_id`). The
        easiest source is a knowledge base that already works: `list_knowledge_bases`
        shows each one's `embedding_provider`, `embedding_model`, `embedding_secret_id`
        and `embedding_endpoint_id`. `list_embedding_models` lists what this
        deployment can embed with.
        """
        body: dict[str, Any] = {
            "name": name,
            "scope": "org",
            "embedding_provider": embedding_provider,
        }
        optional = {
            "embedding_secret_id": embedding_secret_id,
            "embedding_endpoint_id": embedding_endpoint_id,
            "embedding_model": embedding_model,
            "description": description,
        }
        body.update({key: str(value) for key, value in optional.items() if value})
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

    async def list_capabilities() -> dict[str, Any]:
        """Everything an agent can be given - each capability's id, what it does and its tools.

        Includes `config_schema`, defaults and requirements for configuring bindings
        in `create_agent_draft` or `update_agent_draft`. Needs `agents:view`.
        """
        return await api.request("GET", "/agents/capabilities")

    async def list_models() -> dict[str, Any]:
        """The models this organization runs agents on: each one's id, label and provider.

        An agent names one as its `model_profile_id`. Needs `agents:view`.
        """
        return await api.request("GET", "/providers/model-profiles")

    async def list_routines(agent_id: UUID | None = None, limit: int = 50) -> dict[str, Any]:
        """Routines: agents that run themselves on a schedule or when something happens.

        Each has its prompt, cadence (a cron in UTC, or an interval in seconds),
        whether it is active, when it fires next and its last run. Pass `agent_id`
        for one agent's. Needs `agents:view`.
        """
        if agent_id is not None:
            return await api.request("GET", f"/agents/{agent_id}/triggers")
        return await api.request("GET", "/triggers", params={"limit": limit})

    async def create_routine(
        agent_id: UUID,
        prompt: str,
        cron_expression: str | None = None,
        every_minutes: int | None = None,
        name: str | None = None,
        runs_as_me: bool = True,
    ) -> dict[str, Any]:
        """Make an agent run itself on a schedule - a Routine. Needs `agents:run` on it.

        Give one cadence. `cron_expression` is a five-field crontab **in UTC**, so
        convert the person's local time first: 9:00 on weekdays in Warsaw is
        `0 8 * * 1-5` in winter and `0 7 * * 1-5` in summer. `every_minutes` is a
        plain interval. `prompt` is what the agent is asked each time, and that run
        starts with none of this conversation - write it as a complete request:
        what to do, from which sources, in which language, and what to produce.
        `runs_as_me` fires as the person creating it, with their memory and their
        own connected accounts, as in their chat. Every run lands in the routine's
        own log, which the person reads under Routines (`/routines`).
        """
        body: dict[str, Any] = {"prompt": prompt, "runs_as_creator": runs_as_me}
        if name:
            body["name"] = name
        if cron_expression is not None:
            body["schedule_kind"] = "cron"
            body["cron_expression"] = cron_expression
        if every_minutes is not None:
            body["interval_seconds"] = every_minutes * 60
        return await api.request("POST", f"/agents/{agent_id}/triggers", json=body)

    async def update_routine(
        agent_id: UUID,
        routine_id: UUID,
        active: bool | None = None,
        prompt: str | None = None,
        cron_expression: str | None = None,
        every_minutes: int | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Pause or resume a routine, or change its prompt, cadence or name.

        Only what you pass changes; a cron is in UTC, as for `create_routine`.
        Needs to be the routine's creator, or `agents:edit` on its agent.
        """
        body: dict[str, Any] = {}
        if active is not None:
            body["is_active"] = active
        if prompt is not None:
            body["prompt"] = prompt
        if name is not None:
            body["name"] = name
        if cron_expression is not None:
            body["schedule_kind"] = "cron"
            body["cron_expression"] = cron_expression
        if every_minutes is not None:
            body["schedule_kind"] = "interval"
            body["interval_seconds"] = every_minutes * 60
        return await api.request("PATCH", f"/agents/{agent_id}/triggers/{routine_id}", json=body)

    async def run_routine_now(agent_id: UUID, routine_id: UUID) -> dict[str, Any]:
        """Fire a routine once now, its schedule untouched - to show what it will do.

        The run is queued and lands in the routine's log. Needs `agents:run` on its agent.
        """
        return await api.request("POST", f"/agents/{agent_id}/triggers/{routine_id}/run")

    async def delete_routine(agent_id: UUID, routine_id: UUID) -> dict[str, Any]:
        """Remove a routine for good: the agent stops running itself on it.

        To stop it for a while, `update_routine` with `active` false instead. Needs
        to be the routine's creator, or `agents:edit` on its agent.
        """
        deleted = await api.request("DELETE", f"/agents/{agent_id}/triggers/{routine_id}")
        if deleted is not None:
            return deleted
        return {"deleted": str(routine_id)}

    async def search_mcp_servers(query: str, limit: int = 10) -> dict[str, Any]:
        """Search the services an agent can be connected to - GitHub, Notion, Gmail, a CRM.

        Matches name, description and category, the reviewed catalog first. Each
        result has its `key`, what it does and how it signs in (`oauth`, `token` or
        `none`). A person connects one from its card on the MCP servers page,
        `/mcp-servers`. Needs `agents:view`.
        """
        return await api.request("GET", "/agents/mcp-servers", params={"q": query, "limit": limit})

    async def list_sandbox_connections() -> dict[str, Any]:
        """Available sandbox hosts: ids, kind, default runtime and active/default flags.

        Use active ids in sandbox `config.connection_id`, with `backend: service`
        and `include_execute: true` for running code. No credentials are returned.
        Needs `connections:view`. Returns the organization's connection listing.
        """
        return await api.request("GET", "/sandbox-connections")

    async def list_sandbox_runtimes() -> dict[str, Any]:
        """Sandbox runtime aliases and descriptions. Needs `connections:view`.

        Returns the static runtime catalog; a host's `get_sandbox_policy` says
        which aliases it actually permits. Do not invent runtime names.
        """
        return await api.request("GET", "/sandbox-connections/runtimes")

    async def get_sandbox_policy(connection_id: UUID) -> dict[str, Any]:
        """A sandbox host's allowed runtimes and resource ceilings. Needs `connections:view`.

        Returns the host's policy, or the API's refusal if it cannot be read.
        Read before selecting a runtime or resource limits in sandbox config.
        """
        return await api.request("GET", f"/sandbox-connections/{connection_id}/policy")

    async def list_org_connections() -> dict[str, Any]:
        """Organization MCP connections and their tools. Needs `mcp:manage`.

        Returns the organization's listing without credentials. Use a connection's
        id in an `account: organization` MCP binding; personal services instead
        use `account: personal` and a catalog key from `search_mcp_servers`.
        """
        return await api.request("GET", "/mcp-connections")

    async def list_my_connections(include_tools: bool = False) -> dict[str, Any]:
        """The services the person asking has connected with their own account.

        Read it before suggesting a connection, so you never offer what they
        already have. Tokens are never in it. Each connection's tools are left
        out unless `include_tools` is true - whether a service is connected
        needs its name, not the forty tools it offers.
        """
        listing = await api.request("GET", "/me/mcp-connections")
        if include_tools:
            return listing
        return {
            **listing,
            "items": [
                {field: value for field, value in item.items() if field not in _TOOL_FIELDS}
                for item in listing["items"]
            ],
        }

    async def set_my_language(locale: ConsoleLocale) -> dict[str, Any]:
        """Switch the console's language for the person asking: `en`, `pl` or `de`.

        Use it when they ask for the interface - or you - in another language. It
        holds on every device they sign in on, and the console they are looking at
        switches as soon as this answers. Answer in that language from then on.
        """
        return await api.request("PUT", "/users/me/locale", json={"locale": locale})

    async def set_my_profile(
        job_title: str | None = None, about: str | None = None
    ) -> dict[str, Any]:
        """Save what every agent is told about the person asking: their role and their work.

        Use it when they tell you what they do - in the welcome interview, or when
        they correct it - so no agent asks again. Their own words, short: a role
        such as "Head of sales", and what they work on in a sentence. Pass only
        what they told you; what you leave out stays as it is.
        """
        changes = {
            name: value
            for name, value in (("job_title", job_title), ("about", about))
            if value is not None
        }
        return await api.request("PATCH", "/users/me/agent-context", json=changes)

    async def list_skills(limit: int = 50, skip: int = 0) -> dict[str, Any]:
        """The skills this caller can see. Needs `skills:view`."""
        return await api.request("GET", "/skills", params={"limit": limit, "skip": skip})

    async def create_skill(name: str, description: str, content: str) -> dict[str, Any]:
        """Save a procedure as a skill an agent can follow. Needs `skills:edit`.

        Use it when somebody asks to keep something that worked - "make a skill of
        this". Write the skill as instructions for a future agent, not a record of
        this conversation: when to use it, the steps, what to check, what to
        hand back. Then offer to bind it to the agent that should use it.

        Args:
            name: Lowercase letters, digits and hyphens, unique here - `weekly-sales-digest`.
            description: The one line an agent reads before deciding to load it.
            content: The steps, in Markdown.
        """
        return await api.request(
            "POST",
            "/skills",
            json={"name": name, "description": description, "content": content},
        )

    async def list_improvements(agent_id: UUID) -> dict[str, Any]:
        """An agent's Improve sessions, newest first. Needs access to the agent.

        Each has its status, the step it is on, the attempt it reached, why it
        stopped and what it spent, and `link` - the Improve wizard, where the
        person follows it. A `closed` session is a record: its `outcome` says what
        was decided - the attempt, the version it published, by whom - and nothing
        on it can be accepted again. Read one with get_improvement.
        """
        sessions = await api.request("GET", f"/agents/{agent_id}/improvements")
        return {"items": [_session(agent_id, session) for session in sessions]}

    async def get_improvement(session_id: UUID) -> dict[str, Any]:
        """One Improve session by its id: its attempts and verdicts, and what is missing from knowledge.

        Needs access to its agent, whose `agent_id` the answer carries; the
        knowledge topics and `measurement_noise` also need `runs:view`. When
        `measurement_noise.noisy` is true, the test cannot tell a better version
        from a worse one. A session `waiting_for` the person says which step it
        stopped after and what the next one runs; estimate_next_improvement_step
        prices it.
        Each attempt has its verdict, the questions it fixed and broke (confirmed
        on a rerun) and its `change` - fixed less broken - on `held_out`
        questions of its own; compare attempts by that, not by the pass rates in
        their `details`, which come from different questions. Each has its cost.
        `chosen` marks the attempt the session keeps - picked by `chosen_by`, or
        by the session itself when that is empty - and `best` only an attempt
        whose verdict is better; a chosen attempt need not be one. Each knowledge
        topic has its `state`: missing, deferred, drafting, draft_failed,
        draft_ready, draft_stale, covered or dismissed. Only a session with
        `can_accept` can be accepted; a `closed` one is a record, and its
        `outcome` says what was decided. Point the person at `link` rather than
        retelling the wizard's screens.
        """
        session = await api.request("GET", f"/improvements/{session_id}")
        agent_id = session["agent_id"]
        chosen = session.get("best_iteration_id")
        result: dict[str, Any] = {
            "agent_id": agent_id,
            **_session(agent_id, session),
            "attempts": [_attempt(iteration, chosen) for iteration in session["iterations"]],
            "chosen_by": _chosen_by(session),
            "can_discard": session.get("can_discard"),
            "can_restart": session.get("can_restart"),
            "measurement_noise": _noise(session.get("measurement_noise")),
        }
        me = await api.request("GET", "/me/permissions")
        if not any(entry["permission"] == "runs:view" for entry in me.get("permissions", [])):
            return result
        evidence = await api.request(
            "GET", f"/agents/{agent_id}/improvements/{session_id}/evidence"
        )
        topic_ids = {item["topic_id"] for item in evidence["items"] if item.get("topic_id")}
        deferred = set(session.get("deferred_topic_ids") or [])
        topics = await api.request(
            "GET", f"/knowledge-gaps/agents/{agent_id}", params={"limit": 100}
        )
        result["missing_knowledge"] = [
            {
                "topic_id": topic["id"],
                "label": topic["label"],
                "knowledge_base": topic["knowledge_base_name"],
                "state": _topic_state(topic, deferred),
            }
            for topic in topics["items"]
            if topic["id"] in topic_ids
        ]
        return result

    async def estimate_improvement(
        agent_id: UUID,
        dataset_id: UUID | None = None,
        suite_id: UUID | None = None,
        max_iterations: int = 3,
    ) -> dict[str, Any]:
        """What an Improve session would cost, before it starts. Needs `agents:edit`, `runs:view`
        and `datasets:run` on the dataset.

        Name exactly one of `dataset_id` (test questions) or `suite_id` (an
        automatic check, which brings its dataset). `total_usd` is what it costs
        up to its first stop, after Understand, `per_round_usd` about what one
        attempt costs - each later step is priced when it is taken - and
        `limit_usd` the spending limit for the whole session, covering the start
        and every attempt. Tell the person all three before starting one.
        """
        target: dict[str, Any] = {"max_iterations": max_iterations}
        if dataset_id is not None:
            target["dataset_id"] = str(dataset_id)
        if suite_id is not None:
            target["suite_id"] = str(suite_id)
        estimate = await api.request(
            "POST", f"/agents/{agent_id}/improvements/estimate", json=target
        )
        return {**estimate, "limit_usd": _session_limit(estimate)}

    async def start_improvement(
        agent_id: UUID,
        budget_usd: Decimal,
        dataset_id: UUID | None = None,
        suite_id: UUID | None = None,
        max_iterations: int = 3,
    ) -> dict[str, Any]:
        """Start an Improve session, only when the person asked for one. Needs `agents:edit`,
        `runs:view` and `datasets:run` on the dataset.

        Run estimate_improvement first. `budget_usd` is the spending limit for the
        whole session, never below its `total_usd`: the person's figure, or the
        estimate's `limit_usd`. The session never spends more. Say the price and the limit before calling. The session stops for the person after
        Understand, after Changes and at the result, and changes nothing in the
        agent until it is accepted. An agent has one open session at a time: with
        one open, this refuses and names it - end it first, when the person asks.
        """
        sessions = await api.request("GET", f"/agents/{agent_id}/improvements")
        if open_session := next((s for s in sessions if s["status"] not in _CLOSED), None):
            return api.refuse(
                f"This agent already has an open Improve session ({open_session['status']}): "
                f"{improvement_link(agent_id, open_session['id'])}. Continue it there, or end "
                "it with end_improvement and start a new one."
            )
        start: dict[str, Any] = {"max_iterations": max_iterations, "budget_usd": str(budget_usd)}
        if dataset_id is not None:
            start["dataset_id"] = str(dataset_id)
        if suite_id is not None:
            start["suite_id"] = str(suite_id)
        session = await api.request("POST", f"/agents/{agent_id}/improvements", json=start)
        return {
            **{field: session.get(field) for field in _SESSION_FIELDS},
            "link": improvement_link(agent_id, session["id"]),
        }

    async def use_attempt(agent_id: UUID, session_id: UUID, attempt: int) -> dict[str, Any]:
        """Make one finished attempt of a session the one to accept. Needs `agents:edit` and
        `runs:view`.

        Only an attempt that has a verdict can be chosen. Name the attempt and why
        before calling, from get_improvement's numbers.
        """
        session = await api.request(
            "POST", f"/agents/{agent_id}/improvements/{session_id}/rounds/{attempt}/select"
        )
        return {
            **{field: session.get(field) for field in _SESSION_FIELDS},
            "link": improvement_link(agent_id, session_id),
        }

    async def accept_improvement(
        agent_id: UUID, session_id: UUID, publish: bool, automatic_check: bool = False
    ) -> dict[str, Any]:
        """Accept a ready session's chosen attempt into the agent: as a draft, or published.
        Needs `agents:edit` and `runs:view`; `publish` also needs `agents:publish`.

        Publish only when the person asked for exactly that; otherwise accept as a
        draft they publish themselves. An environment guarded by an automatic
        check moves only once that check passes. `automatic_check` adds a check
        that runs the session's test questions on every publish. Refused when the
        agent changed since the session started.
        """
        finished = await api.request(
            "POST",
            f"/agents/{agent_id}/improvements/{session_id}/finish",
            json={"confirmed": True, "publish": publish, "automatic_check": automatic_check},
        )
        return {
            "status": finished["session"]["status"],
            "version": finished.get("version"),
            "link": improvement_link(agent_id, session_id),
        }

    async def end_improvement(agent_id: UUID, session_id: UUID) -> dict[str, Any]:
        """End a session without changing the agent: stop a running one, discard any other open one.
        Needs `agents:edit` and `runs:view`; only whoever started it, or an organization admin.

        A session waiting between steps, a ready one and a stopped or failed one are
        discarded; the agent stays as it was.
        """
        path = f"/agents/{agent_id}/improvements/{session_id}"
        session = await api.request("GET", path)
        if session["status"] in ("queued", "running"):
            ended = await api.request("POST", f"{path}/cancel")
        else:
            ended = await api.request("POST", f"{path}/discard", json={"confirmed": True})
        return {"status": ended["status"], "link": improvement_link(agent_id, session_id)}

    async def estimate_improve_again(
        agent_id: UUID, session_id: UUID, budget_usd: Decimal
    ) -> dict[str, Any]:
        """What trying a session again would cost, and whether it may. Needs `agents:edit`
        and `runs:view`.

        `mode` is the next attempt, resuming one stopped on the budget, or
        retrying a failed step; the session refuses when another attempt cannot
        help. Pass `total_usd` and `candidate_hash` on to improve_again.
        """
        return await api.request(
            "POST",
            f"/agents/{agent_id}/improvements/{session_id}/continue/estimate",
            json={"budget_usd": str(budget_usd)},
        )

    async def improve_again(
        agent_id: UUID,
        session_id: UUID,
        budget_usd: Decimal,
        estimate_usd: Decimal,
        candidate_hash: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Try a session again, only when the person asked for it. Needs `agents:edit` and
        `runs:view`.

        Pass `estimate_usd` and `candidate_hash` from estimate_improve_again and
        say the price before calling; a session that changed since is refused.
        `note` is what the person wants done differently, in their words; the
        next proposal reads it.
        """
        consent: dict[str, Any] = {
            "confirmed": True,
            "budget_usd": str(budget_usd),
            "estimate_usd": str(estimate_usd),
            "candidate_hash": candidate_hash,
        }
        if note is not None:
            consent["note"] = note
        session = await api.request(
            "POST", f"/agents/{agent_id}/improvements/{session_id}/continue", json=consent
        )
        return {
            **{field: session.get(field) for field in _SESSION_FIELDS},
            "link": improvement_link(agent_id, session_id),
        }

    async def estimate_next_improvement_step(
        session_id: UUID, budget_usd: Decimal | None = None
    ) -> dict[str, Any]:
        """What the next step of a session waiting for the person would cost. Needs `agents:edit`
        and `runs:view`.

        After Understand the next step proposes changes; after Changes it tests
        them. `budget_usd` defaults to the session's; pass a higher one when the
        estimate does not fit. Pass `total_usd` and `candidate_hash` on to
        run_next_improvement_step.
        """
        session = await api.request("GET", f"/improvements/{session_id}")
        estimate = await api.request(
            "POST",
            f"/agents/{session['agent_id']}/improvements/{session_id}/continue/estimate",
            json={
                "budget_usd": str(budget_usd if budget_usd is not None else session["budget_usd"])
            },
        )
        return {
            **estimate,
            "waiting_for": _waiting(session),
            "link": improvement_link(session["agent_id"], session_id),
        }

    async def run_next_improvement_step(
        session_id: UUID, budget_usd: Decimal, estimate_usd: Decimal, candidate_hash: str
    ) -> dict[str, Any]:
        """Run the next step of a session waiting for the person, only when they asked for it.
        Needs `agents:edit` and `runs:view`.

        Pass `estimate_usd` and `candidate_hash` from
        estimate_next_improvement_step, and say the step and its price before
        calling; a session that changed since is refused. The step runs as the
        person, and the session stops again at the next step or the result. A
        step that outlasts this conversation's two-hour credential stops, and the
        person finishes it with Next step in the wizard.
        """
        session = await api.request("GET", f"/improvements/{session_id}")
        agent_id = session["agent_id"]
        moved = await api.request(
            "POST",
            f"/agents/{agent_id}/improvements/{session_id}/continue",
            json={
                "confirmed": True,
                "budget_usd": str(budget_usd),
                "estimate_usd": str(estimate_usd),
                "candidate_hash": candidate_hash,
            },
        )
        return _session(agent_id, moved)

    async def estimate_knowledge_draft(topic_id: UUID) -> dict[str, Any]:
        """The most drafting a document for one missing-knowledge topic costs. Needs `runs:view`
        and edit access to the topic's knowledge base.

        `total_usd` is absent when the drafting model has no price. Say the price
        before draft_knowledge_topic.
        """
        return await api.request("GET", f"/knowledge-gaps/{topic_id}/draft/estimate")

    async def draft_knowledge_topic(topic_id: UUID) -> dict[str, Any]:
        """Draft a document for a question the knowledge base could not answer, only when asked.
        Needs `runs:view`, edit access to the topic's knowledge base and AI assistance.

        It is written in the background and kept on the topic for a person to
        review; nothing is added to the knowledge base. Asking again while one is
        being written changes nothing, and asking again later redrafts it from the
        knowledge base as it is then.
        """
        topic = await api.request("POST", f"/knowledge-gaps/{topic_id}/draft")
        return {
            field: topic.get(field)
            for field in (
                "id",
                "label",
                "knowledge_base_name",
                "drafting",
                "draft_failed",
                "draft_stale",
            )
        }

    async def list_datasets(
        agent_id: UUID | None = None, limit: int = 50, skip: int = 0
    ) -> dict[str, Any]:
        """Test question sets (datasets) you can see, optionally those made for or run on one agent.

        Needs `datasets:view`. `can_run` says whether an eval or an Improve session
        may use it.
        """
        params: dict[str, str | int] = {"limit": limit, "skip": skip}
        if agent_id is not None:
            params["agent"] = str(agent_id)
        listing = await api.request("GET", "/datasets", params=params)
        return {
            "total": listing["total"],
            "items": [
                {
                    field: item.get(field)
                    for field in ("id", "name", "case_count", "latest_version", "can_run")
                }
                for item in listing["items"]
            ],
        }

    async def get_eval_run(run_id: UUID) -> dict[str, Any]:
        """One eval run: how it ended and which questions it broke or fixed. Needs `runs:view`.

        `broken` and `fixed` name up to five questions each; `confirmed` means a
        rerun gave the same answer, so it is not luck, and `judge_reason` is why
        the new answer was graded as it was. The run page has the rest.
        """
        run = await api.request("GET", f"/eval-runs/{run_id}")
        outcome = run.get("outcome") or {}
        result: dict[str, Any] = {
            "id": run["id"],
            "agent_id": run["agent_id"],
            "dataset": run["dataset_name"],
            "status": run["status"],
            "cases": run["cases"],
            "cost_usd": run["cost_usd"],
            "verdict": outcome.get("verdict"),
            "pass_rate": {
                "baseline": outcome.get("baseline_pass_rate"),
                "candidate": outcome.get("candidate_pass_rate"),
            },
            "regressions_confirmed": outcome.get("regressions_confirmed"),
            "fixed_confirmed": outcome.get("fixed_confirmed"),
        }
        if run["status"] != "completed" or not run["paired"]:
            return result
        comparison = await api.request("GET", f"/eval-runs/{run_id}/comparison")
        cases = comparison.get("cases", [])
        broken, fixed = _flips(cases, "regression"), _flips(cases, "fixed")
        flipped = [case["case_id"] for case in broken + fixed]
        if flipped:
            listing = await api.request(
                "GET",
                f"/eval-runs/{run_id}/cases",
                params={"case_id": flipped, "limit": len(flipped)},
            )
            candidate = comparison.get("candidate", {}).get("arm_id")
            reasons = {case["case_id"]: _judged(case, candidate) for case in listing["items"]}
            for case in broken + fixed:
                case["judge_reason"] = reasons.get(case["case_id"])
        return {**result, "broken": broken, "fixed": fixed}

    async def list_members(limit: int = 50, skip: int = 0) -> dict[str, Any]:
        """The members of this connection's organization, with their roles. Needs `members:view`."""
        me = await api.request("GET", "/me/permissions")
        if "organization_id" not in me:
            return me
        return await api.request(
            "GET",
            f"/orgs/{me['organization_id']}/members",
            params={"limit": limit, "skip": skip},
        )

    async def invite_member(email: str, role: InviteRole = "member") -> dict[str, Any]:
        """Invite somebody to this organization by email. Needs `members:manage` and `roles:manage`.

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
        (list_projects, False),
        (get_project, False),
        (create_project, True),
        (list_agents, False),
        (get_agent, False),
        (create_agent_draft, True),
        (update_agent_draft, True),
        (test_agent_draft, True),
        (publish_agent, True),
        (discard_agent_draft, True),
        (run_agent, True),
        (list_models, False),
        (list_routines, False),
        (create_routine, True),
        (update_routine, True),
        (run_routine_now, True),
        (delete_routine, True),
        (list_runs, False),
        (get_run, False),
        (read_conversation, False),
        (get_spend, False),
        (list_knowledge_bases, False),
        (list_embedding_models, False),
        (create_knowledge_base, True),
        (add_document, True),
        (search_knowledge, False),
        (list_capabilities, False),
        (list_skills, False),
        (create_skill, True),
        (list_improvements, False),
        (get_improvement, False),
        (estimate_improvement, False),
        (start_improvement, True),
        (use_attempt, True),
        (accept_improvement, True),
        (end_improvement, True),
        (estimate_improve_again, False),
        (improve_again, True),
        (estimate_next_improvement_step, False),
        (run_next_improvement_step, True),
        (estimate_knowledge_draft, False),
        (draft_knowledge_topic, True),
        (list_datasets, False),
        (get_eval_run, False),
        (list_members, False),
        (invite_member, True),
        (search_mcp_servers, False),
        (list_my_connections, False),
        (list_org_connections, False),
        (list_sandbox_connections, False),
        (list_sandbox_runtimes, False),
        (get_sandbox_policy, False),
        (set_my_language, True),
        (set_my_profile, True),
    )
    return tuple(
        PlatformTool(name=function.__name__, function=function, writes=writes)
        for function, writes in operations
    )
