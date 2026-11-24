"""Read-only figures for the re-sent tool output report, one organization at a time.

Sizes and counts only: a tool call's result is measured in the database with
`length`, which counts characters, and never selected, and a run manifest is read through
`payload->'requests'`, never as a whole, because its messages and instructions
are content.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import Integer, column, func, select, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunSurface, ToolApproval
from app.db.models.conversation import Message, ToolCall
from app.db.models.run_manifest import RunManifest


class ReportRun(NamedTuple):
    """One run in the window, with what decides its capability bindings."""

    id: UUID
    agent_id: UUID
    agent_name: str
    agent_version_id: UUID | None
    parent_run_id: UUID | None
    conversation_id: UUID | None
    system_role: str | None
    test_capabilities: list[dict[str, Any]] | None


class CallSize(NamedTuple):
    """One tool call of a run: which tool, and how many characters it returned."""

    run_id: UUID
    tool_name: str
    tool_id: str | None
    is_mcp: bool
    size: int


class RecordedRequest(NamedTuple):
    """One model request of a run, as its manifest recorded it."""

    run_id: UUID
    index: int
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    tool_calls: list[str]


async def list_runs(
    db: AsyncSession,
    *,
    organization_id: UUID,
    started_from: datetime,
    started_before: datetime,
    include_eval: bool,
    include_tests: bool,
) -> list[ReportRun]:
    """The organization's runs started in `[started_from, started_before)`.

    Eval runs and Builder test runs are left out unless asked for, so the figures
    describe what the agents do in production.
    """
    where = [
        AgentRun.organization_id == organization_id,
        AgentRun.started_at >= started_from,
        AgentRun.started_at < started_before,
    ]
    if not include_eval:
        where.append(AgentRun.surface != RunSurface.EVAL.value)
    if not include_tests:
        where.append(AgentRun.is_test.is_(False))
    rows = await db.execute(
        select(
            AgentRun.id,
            AgentRun.agent_id,
            Agent.name,
            AgentRun.agent_version_id,
            AgentRun.parent_run_id,
            AgentRun.conversation_id,
            AgentRun.system_role,
            AgentRun.test_spec["capabilities"],
        )
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(*where)
        .order_by(AgentRun.started_at, AgentRun.id)
    )
    return [ReportRun(*row) for row in rows.all()]


async def list_call_sizes(
    db: AsyncSession, *, organization_id: UUID, run_ids: Sequence[UUID]
) -> list[CallSize]:
    """Every tool call these runs made that returned something, measured rather than read.

    A call with no stored result - one still parked, or a structured output the
    run ended on - sent nothing back to the model, so it is not a result here.
    """
    rows = await db.execute(
        select(
            AgentRun.id,
            ToolCall.tool_name,
            ToolCall.tool_id,
            ToolCall.mcp_connection_id.is_not(None),
            func.length(ToolCall.result),
        )
        .select_from(ToolCall)
        .join(Message, Message.id == ToolCall.message_id)
        .join(AgentRun, AgentRun.id == Message.run_id)
        .where(
            AgentRun.organization_id == organization_id,
            Message.run_id.in_(run_ids),
            ToolCall.result.is_not(None),
        )
    )
    return [CallSize(*row) for row in rows.all()]


async def list_inherited_sizes(
    db: AsyncSession, *, organization_id: UUID, run_ids: Sequence[UUID]
) -> dict[UUID, int]:
    """For each of these runs, the characters earlier runs of its conversation got back from tools.

    A conversation's checkpoint keeps the model messages of the turns before, tool
    results included, so a follow-up run can carry them in its history. Delegates
    start from an empty history and never add to their parent's, so neither side
    of the comparison is one.
    """
    current = aliased(AgentRun)
    earlier = aliased(AgentRun)
    rows = await db.execute(
        select(current.id, func.sum(func.length(ToolCall.result)))
        .select_from(current)
        .join(Message, Message.conversation_id == current.conversation_id)
        .join(earlier, earlier.id == Message.run_id)
        .join(ToolCall, ToolCall.message_id == Message.id)
        .where(
            current.organization_id == organization_id,
            current.id.in_(run_ids),
            current.parent_run_id.is_(None),
            earlier.organization_id == organization_id,
            earlier.parent_run_id.is_(None),
            earlier.started_at < current.started_at,
            ToolCall.result.is_not(None),
        )
        .group_by(current.id)
    )
    return {run_id: int(size) for run_id, size in rows.all()}


async def list_parked(
    db: AsyncSession, *, organization_id: UUID, run_ids: Sequence[UUID], question_tool: str
) -> set[UUID]:
    """Which of these runs stopped to wait on an approval or a question.

    A resumed run records its manifest again and the second recording replaces
    the first, so its request waterfall is only the last segment's.
    """
    approvals = await db.execute(
        select(ToolApproval.run_id).where(
            ToolApproval.organization_id == organization_id, ToolApproval.run_id.in_(run_ids)
        )
    )
    questions = await db.execute(
        select(AgentRun.id)
        .select_from(ToolCall)
        .join(Message, Message.id == ToolCall.message_id)
        .join(AgentRun, AgentRun.id == Message.run_id)
        .where(
            AgentRun.organization_id == organization_id,
            Message.run_id.in_(run_ids),
            ToolCall.tool_name == question_tool,
        )
    )
    return set(approvals.scalars()) | set(questions.scalars())


async def count_turns(
    db: AsyncSession, *, organization_id: UUID, run_ids: Sequence[UUID]
) -> dict[UUID, int]:
    """How many assistant turns each of these runs wrote."""
    rows = await db.execute(
        select(AgentRun.id, func.count())
        .select_from(Message)
        .join(AgentRun, AgentRun.id == Message.run_id)
        .where(
            AgentRun.organization_id == organization_id,
            Message.run_id.in_(run_ids),
            Message.role == "assistant",
        )
        .group_by(AgentRun.id)
    )
    return {row[0]: row[1] for row in rows.all()}


async def list_requests(
    db: AsyncSession, *, organization_id: UUID, run_ids: Sequence[UUID]
) -> list[RecordedRequest]:
    """The model requests these runs' manifests recorded, in order.

    Each request is expanded in SQL and only its counts and tool names are
    selected, so nothing a model was sent leaves the database.
    """
    request = (
        func.jsonb_array_elements(RunManifest.payload["requests"])
        .table_valued(column("value", JSONB))
        .lateral("request")
    )
    value = request.c.value
    rows = await db.execute(
        select(
            RunManifest.run_id,
            value["index"].astext.cast(Integer),
            func.coalesce(value["input_tokens"].astext.cast(Integer), 0),
            func.coalesce(value["cache_read_tokens"].astext.cast(Integer), 0),
            func.coalesce(value["cache_write_tokens"].astext.cast(Integer), 0),
            value["tool_calls"],
        )
        .select_from(RunManifest)
        .join(request, true())
        .where(
            RunManifest.organization_id == organization_id,
            RunManifest.run_id.in_(run_ids),
            func.jsonb_typeof(RunManifest.payload["requests"]) == "array",
        )
        .order_by(RunManifest.run_id, value["index"].astext.cast(Integer))
    )
    return [
        RecordedRequest(run_id, index, inputs, cache_read, cache_write, list(calls or []))
        for run_id, index, inputs, cache_read, cache_write, calls in rows.all()
    ]


async def list_version_capabilities(
    db: AsyncSession, *, organization_id: UUID, version_ids: Sequence[UUID]
) -> dict[UUID, list[dict[str, Any]]]:
    """The capability bindings each of these published versions declared."""
    if not version_ids:
        return {}
    rows = await db.execute(
        select(AgentVersion.id, AgentVersion.spec["capabilities"]).where(
            AgentVersion.organization_id == organization_id,
            AgentVersion.id.in_(version_ids),
        )
    )
    return {version_id: list(capabilities or []) for version_id, capabilities in rows.all()}
