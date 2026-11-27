"""Explicit reviewed source fixtures for tests of other routine policies."""

from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.agents.mcp import McpSourceIdentity
from app.agents.spec import AgentSpec
from app.db.models.agent_trigger import AgentTrigger
from app.schemas.routine_sources import RoutineSourceAccount, RoutineSourcePolicy
from app.schemas.routine_tool_keys import (
    RoutineAccessMode,
    RoutineDelegateSetting,
    RoutineToolSetting,
)
from app.services.routine_sources import source_scope, spec_fingerprint


def reviewed_sources(
    trigger: AgentTrigger,
    *,
    spec: AgentSpec,
    version_id: UUID,
    sources: Mapping[UUID, McpSourceIdentity] | None = None,
    tools: tuple[str, ...] = (),
    settings: tuple[RoutineToolSetting, ...] = (),
    mode: RoutineAccessMode = "reviewed",
    delegates: RoutineDelegateSetting = "ask",
    grandfathered: bool = False,
) -> RoutineSourcePolicy:
    """A review of `spec`'s sources, stored on `trigger` as its creator saved it.

    `tools` are the MCP tools reviewed on each account; `settings` the tool
    settings. No behavior is recorded, so admission compares the spec hash.
    """
    assert trigger.created_by_user_id is not None
    policy = RoutineSourcePolicy(
        id=uuid4(),
        consented_by=trigger.created_by_user_id,
        reviewed_at=datetime.now(UTC),
        version_id=version_id,
        scope_hash=source_scope(trigger),
        spec_hash=spec_fingerprint(spec),
        mode=mode,
        tools=settings,
        delegates=delegates,
        grandfathered=grandfathered,
        mcp_sources={
            identifier: RoutineSourceAccount(
                endpoint_hash=identity.endpoint_hash,
                authorization_generation=identity.authorization_generation,
                tool_prefix=identity.tool_prefix,
                tool_ids=tools,
            )
            for identifier, identity in (sources or {}).items()
        },
    )
    trigger.approved_sources = policy.model_dump(mode="json")
    return policy
