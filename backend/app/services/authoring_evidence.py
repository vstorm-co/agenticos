"""What the authoring assistant reads, and checking what it quotes back.

The assistant has no tools. Its evidence is gathered here, deterministically,
and handed to it in the prompt - which is what keeps it blind to evals: the
reads below never return an eval run (`authoring_repo.evidence_runs`), and
nothing here touches eval runs, case scores or datasets. A rule the model was
asked to follow could be broken by the model; a row it was never sent cannot.

Everything it quotes back is checked against the same evidence before anybody
sees it. A quote that is not, word for word, in the run it names is dropped
and counted - so a hallucinated or prompt-injected quote never dresses a change
up as supported.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.conversation import Message
from app.repositories import authoring_repo, conversation_repo
from app.repositories.authoring import EvidenceRun
from app.schemas.authoring import MAX_EVIDENCE_ITEMS, MAX_QUOTE_CHARS, EvidenceQuote

MAX_EVIDENCE_RUNS = 20
"""The most runs one request reads."""

GROUP_SIZE = 5
"""How many runs one digest reads, when the evidence is too long to read at once."""

PACK_BUDGET_CHARS = 24_000
"""How much evidence the proposal reads directly; past it, groups are digested first."""

_TURN_CHARS = 2_000
_ARGS_CHARS = 300
_MESSAGES_PER_RUN = 40
_SPACE = re.compile(r"\s+")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]} [...]"


def _normal(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


@dataclass(frozen=True)
class PackedRun:
    """One run as the assistant reads it.

    Attributes:
        run_id: The run.
        conversation_id: Its conversation, which a check leaves out of measurement.
        status: How it ended.
        rating: -1 rated down, 1 rated up, 0 unrated.
        comments: What readers said with their down-ratings.
        prompt: What was asked.
        answer: What the agent answered.
        calls: The tools it called, with clipped arguments.
        error: Why it failed, when it did.
    """

    run_id: UUID
    conversation_id: UUID | None
    status: str
    rating: int
    comments: list[str]
    prompt: str
    answer: str
    calls: list[str]
    error: str | None

    def render(self) -> str:
        """The run as the prompt shows it."""
        rated = {-1: "rated down", 1: "rated up", 0: "not rated"}[self.rating]
        lines = [f"## Run {self.run_id} - {self.status}, {rated}"]
        lines += [f"Reader comment: {comment}" for comment in self.comments]
        lines.append(f"Asked: {self.prompt}")
        lines += [f"Called: {call}" for call in self.calls]
        lines.append(f"Answered: {self.answer}")
        if self.error:
            lines.append(f"Error: {self.error}")
        return "\n".join(lines)

    @property
    def source(self) -> str:
        """Everything a quote may come from, whitespace-normalized."""
        return _normal(
            "\n".join([*self.comments, self.prompt, *self.calls, self.answer, self.error or ""])
        )


@dataclass(frozen=True)
class EvidencePack:
    """The runs one request reads, and what it says about them."""

    runs: list[PackedRun] = field(default_factory=list)

    @property
    def conversation_ids(self) -> list[UUID]:
        seen: dict[UUID, None] = {}
        for run in self.runs:
            if run.conversation_id is not None:
                seen[run.conversation_id] = None
        return list(seen)

    def summary(self) -> dict[str, Any]:
        """The counts the assistant strip shows, and the conversations a check leaves out."""
        return {
            "runs": len(self.runs),
            "rated_down": sum(1 for run in self.runs if run.rating < 0),
            "rated_up": sum(1 for run in self.runs if run.rating > 0),
            "commented": sum(1 for run in self.runs if run.comments),
            "conversation_ids": [str(conversation) for conversation in self.conversation_ids],
        }

    def groups(self) -> list[list[PackedRun]]:
        """The runs in digestible groups - one group when they fit the budget at once."""
        if sum(len(run.render()) for run in self.runs) <= PACK_BUDGET_CHARS:
            return [self.runs] if self.runs else []
        return [self.runs[i : i + GROUP_SIZE] for i in range(0, len(self.runs), GROUP_SIZE)]

    def verify(self, quotes: Sequence[EvidenceQuote]) -> tuple[list[dict[str, str]], int]:
        """The quotes that are, word for word, in the run they name - and how many were not.

        Whitespace is normalized on both sides, so a quote that rewraps a line
        still counts; anything else - another run's id, words the run does not
        contain, a quote past the length limit, an item past the count limit -
        is dropped. A duplicate is dropped too, without counting against the change.
        """
        sources = {run.run_id: run.source for run in self.runs}
        kept: list[dict[str, str]] = []
        seen: set[tuple[UUID, str]] = set()
        dropped = 0
        for item in quotes:
            quote = _normal(item.quote)
            key = (item.run_id, quote)
            if key in seen:
                continue
            seen.add(key)
            source = sources.get(item.run_id)
            if (
                source is None
                or not quote
                or len(quote) > MAX_QUOTE_CHARS
                or quote not in source
                or len(kept) >= MAX_EVIDENCE_ITEMS
            ):
                dropped += 1
                continue
            kept.append({"run_id": str(item.run_id), "quote": quote})
        return kept, dropped


def render_runs(runs: Sequence[PackedRun]) -> str:
    return "\n\n".join(run.render() for run in runs)


def _calls(messages: Sequence[Message]) -> list[str]:
    calls: list[str] = []
    for message in messages:
        for call in message.tool_calls:
            args = json.dumps(call.args, ensure_ascii=False, sort_keys=True, default=str)
            calls.append(f"{call.tool_name}({_clip(args, _ARGS_CHARS)})")
    return calls


class EvidenceService:
    """Gather what the assistant reads about an agent or a skill."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def for_agent(
        self, ctx: AuthContext, agent_id: UUID, *, window_days: int
    ) -> EvidencePack:
        rows = await authoring_repo.evidence_runs(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            since=self._since(window_days),
            limit=MAX_EVIDENCE_RUNS,
        )
        return await self._pack(rows)

    async def for_skill(
        self, ctx: AuthContext, skill_name: str, *, window_days: int
    ) -> EvidencePack:
        """The runs, of any agent, whose model opened the skill and was then rated or failed."""
        since = self._since(window_days)
        run_ids = await authoring_repo.runs_that_loaded_skill(
            self.db,
            organization_id=ctx.organization_id,
            skill_name=skill_name,
            since=since,
            limit=MAX_EVIDENCE_RUNS * 5,
        )
        if not run_ids:
            return EvidencePack()
        rows = await authoring_repo.evidence_runs(
            self.db,
            organization_id=ctx.organization_id,
            run_ids=run_ids,
            since=since,
            limit=MAX_EVIDENCE_RUNS,
        )
        return await self._pack(rows)

    @staticmethod
    def _since(window_days: int) -> datetime:
        return datetime.now(UTC) - timedelta(days=window_days)

    async def _pack(self, rows: Sequence[EvidenceRun]) -> EvidencePack:
        packed: list[PackedRun] = []
        for row in rows:
            # Scoped by the run, which `evidence_runs` read inside the organization.
            messages = await conversation_repo.get_messages_by_run(
                self.db, row.run.id, limit=_MESSAGES_PER_RUN, include_tool_calls=True
            )
            asked = next((m.content for m in messages if m.role == "user"), "")
            answered = next((m.content for m in reversed(messages) if m.role == "assistant"), "")
            packed.append(
                PackedRun(
                    run_id=row.run.id,
                    conversation_id=row.run.conversation_id,
                    status=row.run.status,
                    rating=row.rating,
                    comments=[_clip(comment, _TURN_CHARS) for comment in row.comments],
                    prompt=_clip(asked, _TURN_CHARS),
                    answer=_clip(answered, _TURN_CHARS),
                    calls=_calls(messages),
                    error=None if row.run.error is None else _clip(row.run.error, _TURN_CHARS),
                )
            )
        return EvidencePack(runs=packed)
