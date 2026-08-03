"""What a turn cost, and how full the workspace behind it is.

Two numbers people ask for in two places and for two different reasons.

*In a chat*, "what did that cost" is curiosity and a sanity check - somebody
watching an agent burn a budget wants to see it happening rather than read about
it in an invoice.

*In a channel*, it is a warning system. A Slack bot that stops answering because
an organization hit its monthly cap looks broken, and the only difference between
"broken" and "out of budget" is somebody having said so beforehand. Which is why
the reporting mode has `near_limit` at all: a footer on every reply is noise a
channel will learn to ignore, and noise nobody reads is not a warning.

**The mode gates the work, not just the display.** A container's memory is a
daemon round trip per sandbox, so a report nobody will see is not fetched. That is
the whole reason `include_sandbox` is a parameter rather than something this module
decides for itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun
from app.repositories import agent_workspace_repo
from app.services.channels.base import DEFAULT_USAGE_REPORTING
from app.services.sandbox_connection import SandboxConnectionService
from app.services.sandbox_workspace import stored_ceiling

logger = logging.getLogger(__name__)

ReportMode = Literal["off", "always", "near_limit", "every_n"]
"""When a channel says what a turn cost.

`off` still *records* it - the log line is written either way, because "the bot
went quiet" is a question somebody asks days later and a report nobody kept is no
help then. Off means unspoken, not unmeasured.
"""


@dataclass(frozen=True)
class SandboxUsage:
    """How full the workspace behind a turn is.

    Which pair of numbers is present depends on the backend, and neither is
    interchangeable with the other: a stored workspace is bytes in a JSONB column
    against a platform cap, and a container is resident memory against a ceiling
    its host set. Reporting one as the other would tell somebody they are near a
    limit that does not apply to them.
    """

    kind: str
    bytes_used: int | None = None
    bytes_limit: int | None = None
    memory_bytes: int | None = None
    memory_limit_bytes: int | None = None

    @property
    def percent(self) -> int | None:
        """How full, or `None` when nothing measurable came back.

        A container whose usage was not sampled and one with no ceiling both
        answer `None`, because "0%" would be a claim and this has none to make.
        """
        for used, limit in (
            (self.bytes_used, self.bytes_limit),
            (self.memory_bytes, self.memory_limit_bytes),
        ):
            if used is not None and limit:
                return round(used * 100 / limit)
        return None


@dataclass(frozen=True)
class UsageReport:
    """What one turn spent, and what it has left.

    Both caps are carried, because they answer different questions to different
    people. The organization's is the one that stops every agent at once, which is
    what a channel needs warning about. The agent's own is the one an *author* can
    act on - raising it is their decision - and reporting only the organization's
    to somebody looking at their agent in the Builder tells them nothing they can
    do anything about.
    """

    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    period_spend_usd: Decimal | None = None
    budget_usd: Decimal | None = None
    agent_spend_usd: Decimal | None = None
    agent_budget_usd: Decimal | None = None
    sandbox: SandboxUsage | None = None

    @property
    def budget_percent(self) -> int | None:
        """How much of the organization's month is gone, if it capped one."""
        return _share(self.period_spend_usd, self.budget_usd)

    @property
    def agent_budget_percent(self) -> int | None:
        """How much of this agent's own month is gone, if it has a cap."""
        return _share(self.agent_spend_usd, self.agent_budget_usd)


def _share(spend: Decimal | None, budget: Decimal | None) -> int | None:
    """Spend as a percentage of a cap, or `None` when there is no cap to be near."""
    if budget is None or budget <= 0:
        return None
    return round(float(spend or Decimal(0)) * 100 / float(budget))


def should_report(policy: dict[str, Any] | None, report: UsageReport, *, turn: int) -> bool:
    """Whether this turn's usage is said out loud in the channel.

    Args:
        policy: The bot's `usage_reporting`, or `None` for a bot that predates
            the column - which reads as the default rather than as `off`, for the
            same reason the default is `near_limit`.
        turn: How many turns this chat has had, for `every_n`. Counted per chat
            rather than per bot: "every tenth message" means in *this*
            conversation, and a bot-wide counter would put the footer in whichever
            channel happened to be tenth.
    """
    settings_ = {**DEFAULT_USAGE_REPORTING, **(policy or {})}
    mode = settings_.get("mode", "near_limit")

    if mode == "off":
        return False
    if mode == "always":
        return True
    if mode == "every_n":
        every = max(1, int(settings_.get("every_n") or 1))
        return turn > 0 and turn % every == 0

    # near_limit: whichever of the two is closest to its ceiling decides. A
    # workspace about to refuse a write is as much of a warning as a budget about
    # to refuse a run, and a bot that only watched the money would go quiet on
    # the other one with nothing said.
    threshold = int(settings_.get("near_limit_percent") or 80)
    return any(
        percent is not None and percent >= threshold
        for percent in (report.budget_percent, report.sandbox.percent if report.sandbox else None)
    )


def needs_sandbox_sample(policy: dict[str, Any] | None) -> bool:
    """Whether a container's memory is worth a round trip for this bot.

    `off` never asks. Everything else may, because `near_limit` cannot know it is
    near a workspace limit without reading the workspace - which is the one place
    this trade is unavoidable, and it is per turn on one session rather than a
    listing of all of them.
    """
    mode = {**DEFAULT_USAGE_REPORTING, **(policy or {})}.get("mode", "near_limit")
    return mode != "off"


def format_footer(report: UsageReport) -> str:
    """The report as one line a channel can carry.

    One line on purpose. This sits under an answer somebody actually wanted, and
    a three-line accounting block under every reply is how a channel learns to
    skip the part that later says "the budget is nearly gone".
    """
    parts = [
        f"{report.input_tokens + report.output_tokens:,} tokens · ${report.cost_usd:.4f}",
    ]
    budget = report.budget_percent
    if budget is not None:
        parts.append(f"{budget}% of this month's budget")
    if report.sandbox is not None:
        percent = report.sandbox.percent
        label = "workspace" if report.sandbox.kind == "state" else "sandbox memory"
        parts.append(f"{label} {percent}% full" if percent is not None else f"{label} in use")
    return " · ".join(parts)


class UsageReportService:
    """Assembles what a turn cost from what is already recorded."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.connections = SandboxConnectionService(db)

    async def for_run(
        self,
        ctx: AuthContext,
        run: AgentRun,
        *,
        period_spend_usd: Decimal | None = None,
        budget_usd: Decimal | None = None,
        agent_spend_usd: Decimal | None = None,
        agent_budget_usd: Decimal | None = None,
        include_sandbox: bool = False,
    ) -> UsageReport:
        """What this run spent, and how full its workspace is.

        The token half is read off the run row, which the runner has already
        written by the time anything asks - so it costs nothing and cannot
        disagree with what the ledger recorded.

        Never raises. A report is a courtesy attached to an answer somebody is
        waiting for; a workspace that cannot be measured is reported without that
        half rather than turning a successful turn into an error.
        """
        sandbox = None
        if include_sandbox and run.conversation_id is not None:
            sandbox = await self._sandbox(ctx, run.conversation_id)
        return UsageReport(
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cost_usd=run.cost_usd,
            period_spend_usd=period_spend_usd,
            budget_usd=budget_usd,
            agent_spend_usd=agent_spend_usd,
            agent_budget_usd=agent_budget_usd,
            sandbox=sandbox,
        )

    async def _sandbox(self, ctx: AuthContext, conversation_id: UUID) -> SandboxUsage | None:
        rows = await agent_workspace_repo.list_for_conversation(
            self.db, organization_id=ctx.organization_id, conversation_id=conversation_id
        )
        if not rows:
            return None
        row = rows[0]
        if row.backend == "state":
            return SandboxUsage(
                kind="state",
                bytes_used=row.bytes_total,
                bytes_limit=stored_ceiling(row),
            )
        return await self._container(ctx, row)

    async def _container(self, ctx: AuthContext, row: Any) -> SandboxUsage:
        """A container's resident memory, sampled from its host.

        The one place this module pays for a round trip, and the reason the caller
        has to opt in. One session is asked about rather than the whole listing:
        the service samples each sandbox individually, so asking for all of them
        to find one would cost a round trip per sandbox the organization has open.

        A failure is reported as "in use" rather than propagated - the sandbox is
        demonstrably there, the turn just used it, and a number nobody could read
        is not worth losing an answer over.
        """
        usage = SandboxUsage(kind="service")
        if row.connection_id is None or row.session_id is None:
            return usage
        try:
            sampled = await self.connections.session_usage(ctx, row.connection_id, row.session_id)
        except Exception:
            logger.info("sandbox_usage_unavailable", extra={"session_id": row.session_id})
            return usage
        return SandboxUsage(
            kind="service",
            memory_bytes=sampled.get("memory_bytes"),
            memory_limit_bytes=sampled.get("memory_limit_bytes"),
        )


def usage_frame(report: UsageReport | None) -> dict[str, Any] | None:
    """The report as a client reads it.

    Numbers rather than the sentence a channel gets: a chat draws a bar and a
    tooltip, and a pre-formatted string would force it to parse ours back apart.
    `None` stays `None` so a client can tell "nothing was measured" from "zero",
    which are different things to draw.
    """
    if report is None:
        return None
    frame: dict[str, Any] = {
        "input_tokens": report.input_tokens,
        "output_tokens": report.output_tokens,
        "cost_usd": float(report.cost_usd),
        "budget_percent": report.budget_percent,
        "agent_budget_percent": report.agent_budget_percent,
        "sandbox": None,
    }
    if report.sandbox is not None:
        frame["sandbox"] = {
            "kind": report.sandbox.kind,
            "percent": report.sandbox.percent,
            "bytes_used": report.sandbox.bytes_used,
            "bytes_limit": report.sandbox.bytes_limit,
            "memory_bytes": report.sandbox.memory_bytes,
            "memory_limit_bytes": report.sandbox.memory_limit_bytes,
        }
    return frame
