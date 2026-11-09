"""Compile a watch's approved sources without borrowing a newly published agent's reach.

A read-only watch approves one personal account and the selected agent's attached
knowledge/context. Other tools, delegates, accounts and executable skills are
outside that approval. Instructions, model and stricter tool/resource settings
continue to come from the selected published version.
"""

import hashlib

from app.agents.mcp import McpSourceIdentity
from app.agents.spec import AgentSpec, PersonalMcpServerRef
from app.core.exceptions import AuthorizationError
from app.db.models.mcp_connection import McpConnection
from app.schemas.watch_sources import WatchSources


def _binding(spec: AgentSpec, catalog_key: str | None) -> PersonalMcpServerRef:
    for ref in spec.mcp_servers:
        if isinstance(ref, PersonalMcpServerRef) and ref.catalog_key == catalog_key:
            return ref
    raise AuthorizationError(
        message="This agent does not have a personal binding for the watched service. Configure the agent before starting the watch."
    )


def _intersection(
    left: list[str] | tuple[str, ...] | None, right: list[str] | None
) -> tuple[str, ...] | None:
    if left is None:
        return None if right is None else tuple(right)
    return tuple(tool for tool in left if right is None or tool in right)


def approve_sources(spec: AgentSpec, connection: McpConnection) -> WatchSources:
    ref = _binding(spec, connection.catalog_key)
    _unattended_reads(spec, ref)
    tools = _intersection(ref.allowed_tools, connection.allowed_tools)
    if tools == ():
        raise AuthorizationError(message="This agent has no allowed tools for the watched account.")
    return WatchSources(
        connection_id=connection.id,
        authorization_generation=connection.authorization_generation,
        catalog_key=ref.catalog_key,
        endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
        allowed_tools=tools,
        collection_ids=tuple(spec.collection_ids),
        context_ids=tuple(spec.context_ids),
    )


WATCH_CAPABILITIES = frozenset(
    {
        "knowledge",
        "context",
        "guardrails",
        "planning",
        "system_reminders",
        "tool_output_limits",
        "compaction",
    }
)
"""What a watch keeps of its agent: reading aids, plus the two that keep each check
cheap - a long page or result is trimmed before the model reads it, and an
overgrown history is summarized rather than resent every step."""

WATCH_MAX_STEPS = 30
"""Model requests one check may make: a ceiling against a runaway check, not a
working budget. An unbounded check of a Notion workspace ran 40 steps and cost $2;
a GitHub check needs about 15 with its parallel reads, so 12 stopped it short
with nothing to show for what it had spent."""


def constrain_sources(spec: AgentSpec, approved: WatchSources) -> AgentSpec:
    """A later publication can narrow, but never widen, this watch's source approval."""
    current = _binding(spec, approved.catalog_key)
    _unattended_reads(spec, current)
    tools = _intersection(approved.allowed_tools, current.allowed_tools)
    if tools == ():
        raise AuthorizationError(
            message="The published agent no longer has approved tools for this watch."
        )
    return spec.model_copy(
        update={
            "capabilities": [
                binding for binding in spec.capabilities if binding.id in WATCH_CAPABILITIES
            ],
            "max_steps": min(spec.max_steps or WATCH_MAX_STEPS, WATCH_MAX_STEPS),
            "mcp_servers": [
                current.model_copy(update={"allowed_tools": None if tools is None else list(tools)})
            ],
            "collection_ids": [
                identifier
                for identifier in spec.collection_ids
                if identifier in approved.collection_ids
            ],
            "context_ids": [
                identifier for identifier in spec.context_ids if identifier in approved.context_ids
            ],
            "code_mode": spec.code_mode.model_copy(update={"enabled": False}),
            "skill_ids": [],
            "subagents": [],
            "external_agents": [],
        }
    )


def _unattended_reads(spec: AgentSpec, ref: PersonalMcpServerRef) -> None:
    if ref.approval == "all" or any(
        binding.approval == "required" or "required" in binding.tool_approval.values()
        for binding in spec.capabilities
        if binding.id in WATCH_CAPABILITIES
    ):
        raise AuthorizationError(
            message="This agent requires interactive approval for watch reads. Review its read approvals before starting an unattended watch."
        )


def source_identity(approved: WatchSources) -> McpSourceIdentity:
    if approved.authorization_generation is None:
        raise AuthorizationError(
            message="Review this watch's sources after the integration upgrade."
        )
    return McpSourceIdentity(
        endpoint_hash=approved.endpoint_hash,
        authorization_generation=approved.authorization_generation,
    )
