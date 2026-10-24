"""What the authoring assistant reads, and checking what it quotes back.

The assistant has no tools. Chat evidence and completed train-part eval answers
are gathered under the caller's authority and handed to it with train-only tag
and judge-criterion feedback. Holdout answers, notes and grades never enter the
pack. Each paid comparison freezes its held-out case identities and excludes
copies of every question the assistant read, including lost provenance.

Everything it quotes back is checked against the same evidence before anybody
sees it. A quote that is not, word for word, in the run it names is dropped
and counted - so a hallucinated or prompt-injected quote never dresses a change
up as supported.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.db.models.conversation import Message
from app.repositories import agent_repo, authoring_repo, conversation_repo, personal_data_repo
from app.repositories.authoring import EvidenceRun
from app.schemas.authoring import MAX_EVIDENCE_ITEMS, MAX_QUOTE_CHARS, EvidenceQuote
from app.schemas.scoring import ScorerResult
from app.services.access import DATASET, accessible_ids
from app.services.eval_comparison import Attempt, Outcome

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
        people: Whose words it holds - who asked, and who commented - so a
            quote of somebody being erased is not written down.
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
    people: frozenset[UUID] = frozenset()
    evidence_kind: Literal["chat", "train_eval"] = "chat"

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
    training_feedback: str = ""

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
            "source_run_ids": [str(run.run_id) for run in self.runs],
            "rated_down": sum(1 for run in self.runs if run.rating < 0),
            "rated_up": sum(1 for run in self.runs if run.rating > 0),
            "commented": sum(1 for run in self.runs if run.comments),
            "conversation_ids": [str(conversation) for conversation in self.conversation_ids],
        }

    def groups(self) -> list[list[PackedRun]]:
        """The runs in digestible groups - one group when they fit the budget at once."""
        if (
            sum(len(run.render()) for run in self.runs) + len(self.training_feedback)
            <= PACK_BUDGET_CHARS
        ):
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
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        window_days: int,
        excluded_message_ids: Sequence[UUID] = (),
        dataset_id: UUID | None = None,
        dataset_version: int | None = None,
        chat_run_ids: Sequence[UUID] | None = None,
    ) -> EvidencePack:
        """The agent's runs worth reading, less those that gave `excluded_message_ids`.

        An improvement session excludes the answers it found missing knowledge:
        no change to the agent supplies what no source holds.
        """
        rows = await authoring_repo.evidence_runs(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            excluded_message_ids=excluded_message_ids,
            since=self._since(window_days),
            limit=MAX_EVIDENCE_RUNS,
            only_run_ids=chat_run_ids,
        )
        chat = await self._pack(rows)
        train, feedback = await self._train(
            ctx,
            agent_id,
            window_days=window_days,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
        )
        # Training failures and review notes precede chat examples, within one bound.
        used = {run.run_id for run in train}
        return EvidencePack(
            runs=[*train, *(run for run in chat.runs if run.run_id not in used)][
                :MAX_EVIDENCE_RUNS
            ],
            training_feedback=feedback,
        )

    async def for_improvement(
        self, ctx: AuthContext, run_id: UUID, *, excluded_message_ids: Sequence[UUID] = ()
    ) -> EvidencePack:
        from app.core.exceptions import AuthorizationError, NotFoundError
        from app.repositories import improvement_repo
        from app.services.dataset import DatasetService

        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="Reading improvement evidence needs runs:view",
                details={"permission": Perm.RUNS_VIEW.value},
            )
        session = await improvement_repo.get_run(
            self.db, run_id, organization_id=ctx.organization_id
        )
        if session is None:
            raise NotFoundError(message="Improvement session not found")
        await DatasetService(self.db).get(ctx, session.dataset_id, perm=Perm.DATASETS_RUN)
        return await self.for_agent(
            ctx,
            session.agent_id,
            window_days=session.window_days,
            excluded_message_ids=excluded_message_ids,
            dataset_id=session.dataset_id,
            dataset_version=session.dataset_version,
            chat_run_ids=session.chat_evidence_run_ids or [],
        )

    async def _train(
        self,
        ctx: AuthContext,
        agent_id: UUID,
        *,
        window_days: int,
        dataset_id: UUID | None = None,
        dataset_version: int | None = None,
    ) -> tuple[list[PackedRun], str]:
        from app.repositories import eval_run_repo
        from app.services.eval_run import EvalRunService

        since = self._since(window_days)
        candidates = await authoring_repo.evaluated_datasets(
            self.db, organization_id=ctx.organization_id, agent_id=agent_id, since=since
        )
        if dataset_id is not None:
            candidates = [item for item in candidates if item.id == dataset_id]
        allowed = await accessible_ids(
            self.db,
            ctx,
            candidates,
            Perm.DATASETS_RUN if dataset_id is not None else Perm.DATASETS_VIEW,
            resource_type=DATASET,
        )
        rows = await authoring_repo.train_answers(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            dataset_ids=sorted(allowed),
            dataset_version=dataset_version,
            since=since,
        )
        packed: list[PackedRun] = []
        seen: set[UUID] = set()
        outcomes: dict[UUID, dict[UUID, tuple[Outcome, tuple[Outcome, ...], tuple[str, ...]]]] = {}
        flips: dict[UUID, dict[UUID, str]] = {}
        by_tag: dict[str, list[bool | None]] = {}
        by_criterion: dict[str, list[bool | None]] = {}
        fixed = broken = 0
        service = EvalRunService(self.db)
        for row in rows:
            if row.case.case_id in seen:
                continue
            seen.add(row.case.case_id)
            if row.arm.id not in outcomes:
                attempts = await eval_run_repo.list_cases(
                    self.db, row.arm.eval_run_id, organization_id=ctx.organization_id
                )
                outcomes[row.arm.id] = await service.outcomes(ctx, row.arm, attempts)
            first, reruns, _ = outcomes[row.arm.id][row.case.case_id]
            settled = Attempt(
                first,
                reruns=reruns,
                by_person=row.score is not None and row.score.human_passed is not None,
            ).settled
            for tag in row.case.tags or ["(untagged)"]:
                by_tag.setdefault(tag, []).append(settled)
            results = (
                []
                if row.score is None
                else [ScorerResult.model_validate(result) for result in row.score.results]
            )
            for result in results:
                if result.scorer == "judge":
                    by_criterion.setdefault(result.name, []).append(
                        True
                        if result.status == "pass"
                        else False
                        if result.status == "fail"
                        else None
                    )
            if row.arm.eval_run_id not in flips:
                comparison = await service.compare(ctx, row.arm.eval_run_id, measurement_only=False)
                flips[row.arm.eval_run_id] = {
                    case.case_id: case.flip
                    for case in comparison.cases
                    if case.confirmed and comparison.verdict != "invalid"
                }
            flip = flips[row.arm.eval_run_id].get(row.case.case_id)
            fixed += flip == "fixed"
            broken += flip == "regression"
            note = None if row.score is None else row.score.human_note
            if settled is not False and not note and flip != "regression":
                continue
            comments = [f"Review note: {_clip(note, _TURN_CHARS)}"] if note else []
            if flip in {"fixed", "regression"}:
                comments.append(f"Confirmed {flip} in a train-part eval")
            grade_text = "\n".join(
                f"{result.scorer}/{result.name}: {result.reason}" for result in results
            )
            if grade_text:
                comments.append(_clip(grade_text, _TURN_CHARS))
            people = {
                person
                for person in [
                    row.case.created_by_user_id,
                    row.case.asked_by_user_id,
                    row.case.noted_by_user_id,
                    *(row.case.history_author_ids or []),
                    row.run.user_id if not row.run.initiated_by_publisher_fallback else None,
                    row.score.reviewed_by_user_id if row.score else None,
                ]
                if person is not None
            }
            packed.append(
                PackedRun(
                    run_id=row.run.id,
                    conversation_id=None,
                    status="train_eval_failure" if settled is False else "train_eval_reviewed",
                    rating=0,
                    evidence_kind="train_eval",
                    comments=comments,
                    prompt=_clip(row.case.input, _TURN_CHARS),
                    answer=_clip(row.attempt.answer or "", _TURN_CHARS),
                    calls=[],
                    error=None
                    if row.attempt.error is None
                    else _clip(row.attempt.error, _TURN_CHARS),
                    people=frozenset(people),
                )
            )

        def rates(values: dict[str, list[bool | None]]) -> str:
            return "\n".join(
                f"- {name}: {sum(value is True for value in decisions)}/{sum(value is not None for value in decisions)} passed, {sum(value is None for value in decisions)} undecided"
                for name, decisions in sorted(values.items())[:20]
            )

        feedback = (
            ""
            if not rows
            else (
                "# Train-part feedback only; held-out results are not shown\n"
                "From at most 200 recent candidate training answers, using the latest answer per case.\n"
                f"Confirmed newly fixed: {fixed}; newly broken: {broken}.\n"
                f"Pass rate by tag:\n{rates(by_tag)}\nJudge criterion pass rate:\n{rates(by_criterion)}"
            )
        )
        return packed[:MAX_EVIDENCE_RUNS], feedback

    async def for_skill(
        self, ctx: AuthContext, skill_name: str, *, window_days: int
    ) -> EvidencePack:
        """The runs, of any agent, whose model opened the skill and was then rated or failed."""
        rows = await authoring_repo.evidence_runs(
            self.db,
            organization_id=ctx.organization_id,
            skill_name=skill_name,
            since=self._since(window_days),
            limit=MAX_EVIDENCE_RUNS,
        )
        return await self._pack(rows)

    async def for_context(
        self, ctx: AuthContext, context_id: UUID, *, window_days: int
    ) -> EvidencePack:
        """The runs, of the agents whose draft binds the file, that were rated or failed.

        A context file reaches every run of a bound agent - injected, or read on
        demand - so every rated or failed run of those agents is evidence about it.
        """
        bound = await agent_repo.binding_resources(
            self.db,
            organization_id=ctx.organization_id,
            field="context_ids",
            resource_ids=[context_id],
        )
        agents = [agent.id for agent in bound[context_id]]
        if not agents:
            return EvidencePack()
        rows = await authoring_repo.evidence_runs(
            self.db,
            organization_id=ctx.organization_id,
            agent_ids=agents,
            since=self._since(window_days),
            limit=MAX_EVIDENCE_RUNS,
        )
        return await self._pack(rows)

    @staticmethod
    def _since(window_days: int) -> datetime:
        return datetime.now(UTC) - timedelta(days=window_days)

    async def forget_erased(self, pack: EvidencePack) -> EvidencePack:
        """The pack without the runs of anybody being erased, or erased since it was read.

        Called after the last model step, before anything quoting the pack is
        written: what is held then is held until the request's commit, so an
        erasure either comes after it and removes what it wrote, or came first
        and its people's runs are no longer quotable.
        """
        people = {person for run in pack.runs for person in run.people}
        present = await personal_data_repo.present_among(self.db, people)
        return replace(pack, runs=[run for run in pack.runs if run.people <= present])

    async def _pack(self, rows: Sequence[EvidenceRun]) -> EvidencePack:
        packed: list[PackedRun] = []
        linked = await personal_data_repo.linked_people(
            self.db, [row.run.channel_identity_id for row in rows if row.run.channel_identity_id]
        )
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
                    people=frozenset(
                        [
                            *row.commenters,
                            *(
                                [row.run.user_id]
                                if row.run.user_id is not None
                                and not row.run.initiated_by_publisher_fallback
                                else []
                            ),
                            *(
                                [linked[identity]]
                                if (identity := row.run.channel_identity_id) is not None
                                and identity in linked
                                else []
                            ),
                        ]
                    ),
                )
            )
        return EvidencePack(runs=packed)
