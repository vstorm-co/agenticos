"""The authoring assistant end to end against Postgres, with the improver's model scripted.

- Improve reads the rated-down runs - never an eval run - and records hunks whose
  every quote is found in the run it names; a quote that is not is dropped.
- Accept writes the draft and publishes nothing; Undo puts it back while the
  accepted text stands; a decision on a superseded or published batch, or on a
  hunk somebody already decided, is refused.
- A newer request replaces the open batch, an older one finishing later does not,
  and Verify adds to what is waiting instead of replacing it.
- Check with evals runs the projection, leaves the evidence's cases out, and
  leaves the draft as it was.
- AI assistance off, no `runs:view`, no edit access, another organization, no
  evidence and no budget each refuse before anything is written.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.system_agents import IMPROVER
from app.core.exceptions import (
    AiAssistanceDisabledError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
    PaymentRequiredError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunSurface
from app.db.models.authoring import AuthoringRequest, SpecProposalBatch
from app.db.models.conversation import Conversation, Message
from app.db.models.dataset import DatasetCase
from app.db.models.eval_run import EvalRunArm
from app.db.models.eval_suite import EvalSuite
from app.db.models.message_rating import MessageRating
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.skill import Skill
from app.db.models.skill_proposal import SkillProposal
from app.db.models.user import User
from app.repositories import authoring_repo, eval_suite_repo
from app.schemas.authoring import AuthoringStart, HunkDecision, ProposalCheck
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.services.agent_registry import AgentRegistryService
from app.services.agent_runner import AgentRunnerService
from app.services.authoring import AuthoringService
from app.services.authoring_worker import AuthoringWorker
from app.services.dataset import DatasetService
from app.services.model_profile import ModelProfileService
from app.services.system_agent_runner import SystemAgentRunner

pytestmark = pytest.mark.anyio

INSTRUCTIONS = "You answer refund questions.\nBe brief."
COMMENT = "You said 90 days, it is 30"
_RUN = re.compile(r"## Run ([0-9a-f-]{36})")


async def _user(db: AsyncSession) -> User:
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()
    return user


async def _owner(db: AsyncSession, *, ai: bool = True) -> AuthContext:
    user = await _user(db)
    org = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=user.id,
        ai_assistance_enabled=ai,
    )
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER.value)


async def _member(db: AsyncSession, ctx: AuthContext, role: OrgRoleName) -> AuthContext:
    user = await _user(db)
    db.add(
        OrganizationMember(organization_id=ctx.organization_id, user_id=user.id, role=role.value)
    )
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=ctx.organization_id, role=role.value)


async def _published(
    db: AsyncSession, ctx: AuthContext, *, name: str, spec: dict[str, Any], **values: Any
) -> Agent:
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
        name=name,
        status="published",
        draft_spec=spec,
        **values,
    )
    db.add(agent)
    await db.flush()
    version = AgentVersion(
        agent_id=agent.id, organization_id=ctx.organization_id, version=1, spec=spec
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    await db.flush()
    return agent


async def _improver(db: AsyncSession, ctx: AuthContext, *, monthly_usd: float = 5.0) -> Agent:
    return await _published(
        db,
        ctx,
        name="Authoring assistant",
        spec={"name": "Authoring assistant", "budget": {"monthly_usd": monthly_usd}},
        kind="improver",
        system_key=IMPROVER.key,
    )


async def _clerk(db: AsyncSession, ctx: AuthContext) -> Agent:
    spec = {
        "name": "Clerk",
        "instructions": INSTRUCTIONS,
        "capabilities": [{"id": "charts"}],
    }
    return await _published(db, ctx, name="Clerk", spec=spec)


async def _rated(
    db: AsyncSession,
    ctx: AuthContext,
    agent: Agent,
    *,
    rating: int = -1,
    comment: str | None = COMMENT,
    surface: RunSurface = RunSurface.WEB,
) -> AgentRun:
    conversation = Conversation(organization_id=ctx.organization_id, user_id=ctx.user_id)
    db.add(conversation)
    await db.flush()
    run = AgentRun(
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        user_id=ctx.user_id,
        conversation_id=conversation.id,
        surface=surface.value,
        status="completed",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    db.add(
        Message(
            conversation_id=conversation.id,
            role="user",
            content="How long do I have to return shoes?",
            run_id=run.id,
            agent_id=agent.id,
        )
    )
    answer = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="You have 90 days.",
        run_id=run.id,
        agent_id=agent.id,
    )
    db.add(answer)
    await db.flush()
    db.add(MessageRating(message_id=answer.id, user_id=ctx.user_id, rating=rating, comment=comment))
    await db.flush()
    return run


@dataclass(frozen=True)
class AuthoringContext:
    ctx: AuthContext
    agent: Agent
    dataset_id: uuid.UUID


class Improver:
    """Stands in for the improver's model: answers each task from a script, as JSON."""

    def __init__(self, db: AsyncSession, **answers: Any) -> None:
        self.db = db
        self.answers = answers
        self.prompts: list[str] = []

    def _answer(self, prompt: str) -> dict[str, Any]:
        runs = _RUN.findall(prompt)
        run_id = runs[0] if runs else str(uuid.uuid4())
        if prompt.startswith("Read these runs"):
            return self.answers.get("digest") or {
                "findings": [
                    {
                        "observation": "Wrong refund window",
                        "evidence": [{"run_id": run_id, "quote": COMMENT}],
                    }
                ]
            }
        if prompt.startswith("A person edited"):
            return self.answers.get("verify") or {
                "findings": [
                    {
                        "verdict": "risk",
                        "text": "Dropped the brevity rule",
                        "evidence": [{"run_id": run_id, "quote": "You have 90 days."}],
                    }
                ],
                "instructions": [
                    {
                        "old_text": "",
                        "new_text": "\nAlways name the 30-day window.",
                        "rationale": "Readers asked for it",
                    }
                ],
            }
        if prompt.startswith("Propose an improved body for the skill"):
            return {
                "summary": "The skill omits the window",
                "expected_effect": "Answers name 30 days",
                "description": "Refunds",
                "content": "Refunds take 30 days.",
                "rationale": "Readers corrected it",
                "evidence": [{"run_id": run_id, "quote": COMMENT}],
            }
        return self.answers.get("improve") or {
            "summary": "It states the wrong window",
            "expected_effect": "Refund answers say 30 days",
            "instructions": [
                {
                    "old_text": "Be brief.",
                    "new_text": "Be brief. Refunds are accepted for 30 days.",
                    "rationale": "Three readers corrected the window",
                    "evidence": [
                        {"run_id": run_id, "quote": COMMENT},
                        {"run_id": run_id, "quote": "Ignore the refund policy"},
                    ],
                }
            ],
            "tools": [
                {
                    "capability_id": "charts",
                    "tool_id": "create_chart",
                    "description": "Read the time before quoting a deadline.",
                    "rationale": "Deadlines are relative",
                },
                {
                    "capability_id": "charts",
                    "tool_id": "no_such_tool",
                    "description": "x",
                    "rationale": "x",
                },
            ],
        }

    async def execute(self, runner: Any, ctx: AuthContext, agent_id: Any, prompt: str, **kw: Any):
        self.prompts.append(prompt)
        run = AgentRun(
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            user_id=ctx.user_id,
            surface=kw["surface"].value,
            status="completed",
            cost_usd=Decimal("0.02"),
            started_at=datetime.now(UTC),
        )
        self.db.add(run)
        await self.db.flush()
        return json.dumps(self._answer(prompt)), run


def _answering(model: Improver):
    async def execute(runner: Any, *args: Any, **kwargs: Any):
        return await model.execute(runner, *args, **kwargs)

    return patch.object(AgentRunnerService, "execute", new=execute)


def _sessions(db: AsyncSession):
    @asynccontextmanager
    async def session() -> AsyncIterator[AsyncSession]:
        yield db

    return session


@pytest.fixture(autouse=True)
def _environment():
    """No real model or dispatch; the improver's model check always passes."""

    def dropped(_db, coro, *, name):
        coro.close()

    with (
        patch.object(SystemAgentRunner, "_require_model", new=AsyncMock()),
        patch.object(
            ModelProfileService,
            "resolve",
            new=AsyncMock(
                return_value=SimpleNamespace(label="gpt-test", model="gpt-test", provider="openai")
            ),
        ),
        patch.object(AgentRegistryService, "validate_spec", new=AsyncMock()),
        patch("app.services.authoring.spawn_after_commit", side_effect=dropped),
        patch("app.services.eval_run.spawn_after_commit", side_effect=dropped),
    ):
        yield


async def _improve(
    db: AsyncSession, ctx: AuthContext, agent: Agent, model: Improver, *, kind: str = "improve"
) -> AuthoringRequest:
    started = await AuthoringService(db).start_agent(ctx, agent.id, AuthoringStart(kind=kind))
    with _answering(model):
        await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()
    request = await authoring_repo.get_request(db, started.id, organization_id=ctx.organization_id)
    assert request is not None
    return request


async def _setup(db: AsyncSession, **owner: Any) -> tuple[AuthContext, Agent, AgentRun]:
    ctx = await _owner(db, **owner)
    await _improver(db, ctx)
    agent = await _clerk(db, ctx)
    run = await _rated(db, ctx, agent)
    return ctx, agent, run


class TestImprove:
    async def test_rated_down_answers_become_hunks_with_checked_evidence(self, db):
        ctx, agent, run = await _setup(db)
        await _rated(db, ctx, agent, surface=RunSurface.EVAL, comment="An eval case")
        model = Improver(db)

        request = await _improve(db, ctx, agent, model)

        assert request.status == "completed", request.error
        assert request.cost_usd == Decimal("0.02") and len(request.run_ids) == 1
        assert request.evidence["runs"] == 1 and request.evidence["rated_down"] == 1
        assert "An eval case" not in model.prompts[0]
        read = await AuthoringService(db).for_agent(ctx, agent.id)
        assert read.batch is not None
        instruction, tool = read.batch.hunks
        assert instruction.kind == "instructions" and instruction.applies
        assert [item.quote for item in instruction.evidence] == [COMMENT]
        assert instruction.evidence_dropped == 1
        assert tool.tool_id == "create_chart" and tool.base_description is None
        assert read.batch.expected_effect == "Refund answers say 30 days"
        improver_runs = (
            (await db.execute(select(AgentRun).where(AgentRun.id.in_(request.run_ids))))
            .scalars()
            .all()
        )
        assert {row.surface for row in improver_runs} == {"eval"}

    async def test_a_large_body_of_evidence_is_digested_before_the_proposal(self, db, monkeypatch):
        ctx, agent, _ = await _setup(db)
        for _ in range(6):
            await _rated(db, ctx, agent)
        monkeypatch.setattr("app.services.authoring_evidence.PACK_BUDGET_CHARS", 10)
        model = Improver(db)

        request = await _improve(db, ctx, agent, model)

        assert request.status == "completed", request.error
        assert [prompt.split("\n")[0][:15] for prompt in model.prompts] == [
            "Read these runs",
            "Read these runs",
            "Propose improve",
        ]
        assert "Wrong refund window" in model.prompts[-1]

    async def test_accept_writes_the_draft_and_publishes_nothing(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        service = AuthoringService(db)
        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None
        instruction, tool = batch.hunks

        accepted = await service.decide(
            ctx, agent.id, instruction.id, HunkDecision(action="accept")
        )
        await service.decide(ctx, agent.id, tool.id, HunkDecision(action="accept"))

        assert "Refunds are accepted for 30 days." in accepted.draft_spec["instructions"]
        await db.refresh(agent)
        assert agent.draft_spec["capabilities"][0]["tool_overrides"]["create_chart"] == {
            "description": "Read the time before quoting a deadline."
        }
        versions = await db.scalar(
            select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent.id)
        )
        assert versions == 1
        assert agent.status == "published"

        undone = await service.decide(ctx, agent.id, instruction.id, HunkDecision(action="undo"))
        assert undone.draft_spec["instructions"] == INSTRUCTIONS
        await service.decide(ctx, agent.id, tool.id, HunkDecision(action="undo"))
        await db.refresh(agent)
        assert agent.draft_spec["capabilities"][0]["tool_overrides"] == {}

    async def test_a_decision_writes_over_the_draft_as_committed_not_as_first_read(self, db):
        """Two people accepting different hunks at once: the second must build on the
        draft the first wrote, not on the copy it loaded before waiting for the lock."""
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        service = AuthoringService(db)
        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None
        instruction, tool = batch.hunks
        written_elsewhere = {
            **agent.draft_spec,
            "instructions": INSTRUCTIONS.replace("Be brief.", "Be brief. Refunds take 30 days."),
        }
        await db.execute(
            update(Agent)
            .where(Agent.id == agent.id)
            .values(draft_spec=written_elsewhere)
            .execution_options(synchronize_session=False)
        )

        decided = await service.decide(ctx, agent.id, tool.id, HunkDecision(action="accept"))

        assert decided.draft_spec["instructions"] == written_elsewhere["instructions"]
        assert decided.draft_spec["capabilities"][0]["tool_overrides"]["create_chart"] == {
            "description": "Read the time before quoting a deadline."
        }
        assert instruction.status == "pending"

    async def test_an_edit_is_accepted_as_written_and_a_later_hand_edit_blocks_undo(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        service = AuthoringService(db)
        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None
        hunk = batch.hunks[0]

        await service.decide(
            ctx, agent.id, hunk.id, HunkDecision(action="accept", text="Keep it to 30 days.")
        )
        await db.refresh(agent)
        assert agent.draft_spec["instructions"].endswith("Keep it to 30 days.")
        agent.draft_spec = {**agent.draft_spec, "instructions": "Rewritten by hand."}
        await db.flush()

        with pytest.raises(BadRequestError, match="edited by hand"):
            await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="undo"))

    async def test_dismiss_undo_and_a_second_decision(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        service = AuthoringService(db)
        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None
        hunk = batch.hunks[0]

        with pytest.raises(BadRequestError, match="nothing to undo"):
            await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="undo"))
        await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="dismiss"))
        with pytest.raises(ConcurrentChangeError, match="decided this suggestion"):
            await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
        restored = await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="undo"))

        assert restored.authoring.batch is not None
        assert restored.authoring.batch.hunks[0].status == "pending"
        dismissed = await service.dismiss_all(ctx, agent.id)
        assert dismissed.batch is not None
        assert {hunk.status for hunk in dismissed.batch.hunks} == {"dismissed"}

    async def test_a_stale_hunk_is_refused(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        service = AuthoringService(db)
        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None
        agent.draft_spec = {"name": "Clerk", "instructions": "Something else entirely."}
        await db.flush()

        for hunk in batch.hunks:
            with pytest.raises(BadRequestError, match="no longer fits"):
                await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))

    async def test_publishing_closes_the_batch_and_its_decisions(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        service = AuthoringService(db)
        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None

        await AgentRegistryService(db).publish(ctx, agent.id)

        with pytest.raises(ConcurrentChangeError, match="published"):
            await service.decide(ctx, agent.id, batch.hunks[0].id, HunkDecision(action="dismiss"))
        read = await service.for_agent(ctx, agent.id)
        assert read.batch is not None and read.batch.status == "published"

    async def test_a_newer_request_replaces_the_batch_and_skips_what_was_dismissed(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        service = AuthoringService(db)
        first = (await service.for_agent(ctx, agent.id)).batch
        assert first is not None
        await service.decide(ctx, agent.id, first.hunks[0].id, HunkDecision(action="dismiss"))

        await _improve(db, ctx, agent, Improver(db))

        second = (await service.for_agent(ctx, agent.id)).batch
        assert second is not None and second.id != first.id
        assert [hunk.kind for hunk in second.hunks] == ["tool_override"]
        old = await db.get(SpecProposalBatch, first.id)
        assert old is not None and old.status == "superseded"

    async def test_an_older_request_finishing_late_replaces_nothing(self, db):
        ctx, agent, _ = await _setup(db)
        service = AuthoringService(db)
        late = await service.start_agent(ctx, agent.id, AuthoringStart())
        late_row = await db.get(AuthoringRequest, late.id)
        assert late_row is not None
        late_row.created_at = datetime.now(UTC) - timedelta(minutes=5)
        await db.flush()
        await _improve(db, ctx, agent, Improver(db))
        newer = (await service.for_agent(ctx, agent.id)).batch
        assert newer is not None
        late_row.status = "queued"
        late_row.started_at = None
        await db.flush()

        with _answering(Improver(db)):
            worker = AuthoringWorker(late.id, ctx.organization_id, sessions=_sessions(db))
            with patch("app.services.authoring_worker.datetime") as clock:
                clock.now.return_value = datetime.now(UTC) - timedelta(minutes=5)
                await worker.run()

        read = await service.for_agent(ctx, agent.id)
        assert read.batch is not None and read.batch.id == newer.id
        await db.refresh(late_row)
        assert late_row.status == "completed" and late_row.report is not None
        assert late_row.report["recorded"] == 0


class TestVerify:
    async def test_verify_needs_an_edit_and_adds_its_findings_to_what_waits(self, db):
        ctx, agent, _ = await _setup(db)
        service = AuthoringService(db)
        with pytest.raises(BadRequestError, match="nothing to verify"):
            await service.start_agent(ctx, agent.id, AuthoringStart(kind="verify"))
        await _improve(db, ctx, agent, Improver(db))
        waiting = (await service.for_agent(ctx, agent.id)).batch
        assert waiting is not None
        agent.draft_spec = {**agent.draft_spec, "instructions": "You answer refund questions."}
        await db.flush()

        request = await _improve(db, ctx, agent, Improver(db), kind="verify")

        assert request.status == "completed", request.error
        assert request.report is not None
        (finding,) = request.report["findings"]
        assert (
            finding["verdict"] == "risk" and finding["evidence"][0]["quote"] == "You have 90 days."
        )
        read = await service.for_agent(ctx, agent.id)
        assert read.batch is not None and read.batch.id == waiting.id
        assert [hunk.origin for hunk in read.batch.hunks] == ["improve", "improve", "verify"]
        assert read.verify is not None and read.verify.id == request.id
        assert read.verify.report is not None
        assert read.verify.report["findings"][0]["evidence"][0]["quote"] == "You have 90 days."

        member = await _member(db, ctx, OrgRoleName.MEMBER)
        hidden = await service.for_agent(member, agent.id)
        assert hidden.verify is not None and hidden.verify.report is not None
        assert hidden.latest is not None and hidden.latest.report == hidden.verify.report
        (finding,) = hidden.verify.report["findings"]
        assert finding["evidence"] == [
            {"run_id": request.report["findings"][0]["evidence"][0]["run_id"]}
        ]
        assert finding["text"] == "Dropped the brevity rule"

    async def test_verify_with_nothing_waiting_opens_a_batch(self, db):
        ctx, agent, _ = await _setup(db)
        agent.draft_spec = {**agent.draft_spec, "instructions": "You answer refund questions."}
        await db.flush()

        await _improve(db, ctx, agent, Improver(db), kind="verify")

        read = await AuthoringService(db).for_agent(ctx, agent.id)
        assert read.batch is not None and [h.origin for h in read.batch.hunks] == ["verify"]

    async def test_verify_with_nothing_to_change_adds_no_batch(self, db):
        ctx, agent, _ = await _setup(db)
        agent.draft_spec = {**agent.draft_spec, "instructions": "You answer refund questions."}
        await db.flush()
        model = Improver(db, verify={"findings": [], "instructions": [], "tools": []})

        await _improve(db, ctx, agent, model, kind="verify")

        assert (await AuthoringService(db).for_agent(ctx, agent.id)).batch is None


class TestCheck:
    async def test_the_projection_runs_without_the_evidence_and_the_draft_stays(self, db):
        ctx, agent, run = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        datasets = DatasetService(db)
        dataset = await datasets.create(ctx, DatasetCreate(name="refunds"))
        for index in range(2):
            await datasets.add_case(
                ctx,
                dataset.id,
                DatasetCaseCreate(
                    input=f"Q{index}", checks=[{"type": "contains", "value": "30 days"}]
                ),
            )
        first = (
            (
                await db.execute(
                    select(DatasetCase)
                    .where(DatasetCase.dataset_id == dataset.id)
                    .order_by(DatasetCase.input)
                )
            )
            .scalars()
            .first()
        )
        assert first is not None
        first.source_conversation_id = run.conversation_id
        await db.flush()
        service = AuthoringService(db)
        before = dict(agent.draft_spec)

        estimate = await service.estimate_check(ctx, agent.id, ProposalCheck(dataset_id=dataset.id))
        started = await service.check(ctx, agent.id, ProposalCheck(dataset_id=dataset.id))

        assert estimate.cases == 1
        assert started.excluded_case_ids == [first.case_id] and started.paired
        assert started.arms[0].source == "explicit"
        await db.refresh(agent)
        assert agent.draft_spec == before
        read = await service.for_agent(ctx, agent.id)
        assert read.batch is not None and read.batch.check_eval_run_ids == [started.id]

        # An eval suite of the agent names the dataset in its place; another agent's does not.
        suite = await eval_suite_repo.create(
            db,
            organization_id=ctx.organization_id,
            suite=EvalSuite(
                agent_id=agent.id, dataset_id=dataset.id, owner_user_id=ctx.user_id, name="nightly"
            ),
        )
        through_suite = await service.check(ctx, agent.id, ProposalCheck(suite_id=suite.id))
        assert through_suite.dataset_id == dataset.id
        assert through_suite.excluded_case_ids == [first.case_id]
        other = await _clerk(db, ctx)
        foreign = await eval_suite_repo.create(
            db,
            organization_id=ctx.organization_id,
            suite=EvalSuite(
                agent_id=other.id, dataset_id=dataset.id, owner_user_id=ctx.user_id, name="other"
            ),
        )
        with pytest.raises(NotFoundError, match="Eval suite not found"):
            await service.check(ctx, agent.id, ProposalCheck(suite_id=foreign.id))

    async def test_nothing_waiting_has_nothing_to_check(self, db):
        ctx, agent, _ = await _setup(db)

        with pytest.raises(BadRequestError, match="No suggestion is waiting"):
            await AuthoringService(db).check(ctx, agent.id, ProposalCheck(dataset_id=uuid.uuid4()))

    async def test_a_suggestion_that_no_longer_fits_is_never_silently_left_out(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        agent.draft_spec = {**agent.draft_spec, "instructions": "Rewritten by hand."}
        await db.flush()
        service = AuthoringService(db)

        with pytest.raises(BadRequestError, match="1 of the 2 waiting suggestions"):
            await service.check(ctx, agent.id, ProposalCheck(dataset_id=uuid.uuid4()))

        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None
        stale = next(hunk for hunk in batch.hunks if not hunk.applies)
        await service.decide(ctx, agent.id, stale.id, HunkDecision(action="dismiss"))
        with pytest.raises(NotFoundError):
            await service.check(ctx, agent.id, ProposalCheck(dataset_id=uuid.uuid4()))


class TestSkills:
    async def test_a_skill_gets_one_evidence_backed_proposal_per_improver(self, db):
        ctx, agent, run = await _setup(db)
        skill = Skill(
            organization_id=ctx.organization_id,
            owner_user_id=ctx.user_id,
            visibility="org",
            name="refunds",
            description="Refunds",
            content="Refunds take 90 days.",
            version=3,
        )
        db.add(skill)
        await db.flush()
        from app.db.models.conversation import ToolCall

        answer = (
            await db.execute(
                select(Message).where(Message.run_id == run.id, Message.role == "assistant")
            )
        ).scalar_one()
        db.add(
            ToolCall(
                message_id=answer.id,
                tool_call_id="call-1",
                tool_name="load_capability",
                args={"id": "refunds"},
                started_at=datetime.now(UTC),
            )
        )
        await db.flush()
        service = AuthoringService(db)

        for _ in range(2):
            started = await service.start_skill(ctx, skill.id, AuthoringStart())
            with _answering(Improver(db)):
                await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()

        proposals = (
            (await db.execute(select(SkillProposal).where(SkillProposal.skill_id == skill.id)))
            .scalars()
            .all()
        )
        (proposal,) = proposals
        assert proposal.content == "Refunds take 30 days." and proposal.base_version == 3
        assert proposal.evidence == [{"run_id": str(run.id), "quote": COMMENT}]
        listed = await service.for_skill(ctx, skill.id)
        assert len(listed) == 2 and listed[0].status == "completed"
        with pytest.raises(BadRequestError, match="no draft to verify"):
            await service.estimate_skill(ctx, skill.id, AuthoringStart(kind="verify"))


class TestRefusals:
    @pytest.mark.security
    async def test_ai_assistance_off_refuses_every_start_but_not_a_decision(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        org = await db.get(Organization, ctx.organization_id)
        assert org is not None
        org.ai_assistance_enabled = False
        await db.flush()
        service = AuthoringService(db)

        with pytest.raises(AiAssistanceDisabledError):
            await service.start_agent(ctx, agent.id, AuthoringStart())
        with pytest.raises(AiAssistanceDisabledError):
            await service.estimate_agent(ctx, agent.id, AuthoringStart(kind="verify"))
        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None
        decided = await service.decide(
            ctx, agent.id, batch.hunks[0].id, HunkDecision(action="dismiss")
        )
        assert decided.authoring.batch is not None

    @pytest.mark.security
    async def test_runs_view_edit_access_and_the_organization_bound_who_may_start(self, db):
        ctx, agent, _ = await _setup(db)
        member = await _member(db, ctx, OrgRoleName.MEMBER)
        operator = await _member(db, ctx, OrgRoleName.OPERATOR)
        stranger = await _owner(db)
        service = AuthoringService(db)

        with pytest.raises(AuthorizationError, match="runs:view"):
            await service.start_agent(member, agent.id, AuthoringStart())
        with pytest.raises(NotFoundError):
            await service.start_agent(operator, agent.id, AuthoringStart())
        with pytest.raises(NotFoundError):
            await service.for_agent(stranger, agent.id)

    @pytest.mark.security
    async def test_nothing_rated_and_no_budget_refuse_before_anything_is_written(self, db):
        ctx = await _owner(db)
        await _improver(db, ctx, monthly_usd=0.01)
        agent = await _clerk(db, ctx)
        service = AuthoringService(db)

        with pytest.raises(BadRequestError, match="Nothing to learn from yet"):
            await service.start_agent(ctx, agent.id, AuthoringStart())
        await _rated(db, ctx, agent)
        with pytest.raises(PaymentRequiredError, match="too little budget"):
            await service.start_agent(ctx, agent.id, AuthoringStart())
        assert await db.scalar(select(func.count()).select_from(AuthoringRequest)) == 0

    @pytest.mark.security
    async def test_quotes_are_hidden_from_a_reader_without_runs_view(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        member = await _member(db, ctx, OrgRoleName.MEMBER)

        read = await AuthoringService(db).for_agent(member, agent.id)

        assert read.batch is not None
        assert {item.quote for item in read.batch.hunks[0].evidence} == {None}


class TestWorker:
    async def test_a_request_whose_starter_left_fails_and_a_finished_one_is_left_alone(self, db):
        ctx, agent, _ = await _setup(db)
        started = await AuthoringService(db).start_agent(ctx, agent.id, AuthoringStart())
        membership = (
            await db.execute(
                select(OrganizationMember).where(OrganizationMember.user_id == ctx.user_id)
            )
        ).scalar_one()
        await db.delete(membership)
        await db.flush()

        worker = AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db))
        await worker.run()
        await worker.run()
        await AuthoringWorker(uuid.uuid4(), ctx.organization_id, sessions=_sessions(db)).run()

        request = await db.get(AuthoringRequest, started.id)
        assert request is not None and request.status == "failed"
        assert request.error == "Whoever started this is no longer a member."

    async def test_a_refused_or_broken_call_fails_the_request_with_a_reason(self, db):
        ctx, agent, _ = await _setup(db)
        service = AuthoringService(db)

        async def unreadable(runner: Any, caller: Any, agent_id: Any, prompt: str, **kw: Any):
            run = AgentRun(
                organization_id=ctx.organization_id,
                agent_id=agent_id,
                user_id=ctx.user_id,
                surface="eval",
                status="completed",
                cost_usd=Decimal("0.03"),
                started_at=datetime.now(UTC),
            )
            db.add(run)
            await db.flush()
            return "not json", run

        async def broken(*args: Any, **kwargs: Any):
            raise RuntimeError("socket closed")

        for execute, reason in (
            (unreadable, "could not be read"),
            (broken, "stopped unexpectedly"),
        ):
            started = await service.start_agent(ctx, agent.id, AuthoringStart())
            with patch.object(AgentRunnerService, "execute", new=execute):
                await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()
            request = await db.get(AuthoringRequest, started.id)
            assert request is not None and request.status == "failed"
            assert request.error is not None and reason in request.error
            if execute is unreadable:
                # The call was made and paid for, so the request owns its cost.
                assert len(request.run_ids) == 1
                assert request.cost_usd == Decimal("0.03")

    async def test_authority_lost_while_queued_stops_the_request_before_a_run_is_read(self, db):
        ctx, agent, _ = await _setup(db)
        membership = (
            await db.execute(
                select(OrganizationMember).where(OrganizationMember.user_id == ctx.user_id)
            )
        ).scalar_one()
        model = Improver(db)

        for role, reason in (
            (OrgRoleName.MEMBER, "may no longer read runs"),
            (OrgRoleName.OPERATOR, "may no longer edit the agent"),
        ):
            membership.role = OrgRoleName.OWNER.value
            await db.flush()
            started = await AuthoringService(db).start_agent(ctx, agent.id, AuthoringStart())
            membership.role = role.value
            await db.flush()
            with _answering(model):
                await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()

            request = await db.get(AuthoringRequest, started.id)
            assert request is not None and request.status == "failed"
            assert request.error is not None and reason in request.error
        assert model.prompts == []

    async def test_a_gone_target_or_no_evidence_left_fails_the_request(self, db):
        ctx, agent, run = await _setup(db)
        service = AuthoringService(db)
        started = await service.start_agent(ctx, agent.id, AuthoringStart())
        await db.delete(await db.get(AgentRun, run.id))
        await db.flush()

        await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()

        request = await db.get(AuthoringRequest, started.id)
        assert request is not None and request.error is not None
        assert "Nothing to learn from yet" in request.error

    async def test_a_request_the_worker_stopped_hearing_from_is_reported_failed(self, db):
        ctx, agent, _ = await _setup(db)
        service = AuthoringService(db)
        started = await service.start_agent(ctx, agent.id, AuthoringStart())
        row = await db.get(AuthoringRequest, started.id)
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(hours=1)
        await db.flush()

        queued = await service.for_agent(ctx, agent.id)
        assert queued.latest is not None and queued.latest.status == "queued"

        row.status = "running"
        row.heartbeat_at = datetime.now(UTC) - timedelta(minutes=30)
        await db.flush()
        read = await service.for_agent(ctx, agent.id)
        assert read.latest is not None and read.latest.status == "failed"

    async def test_a_request_no_worker_reached_for_a_day_is_reported_failed(self, db):
        ctx, agent, _ = await _setup(db)
        service = AuthoringService(db)
        started = await service.start_agent(ctx, agent.id, AuthoringStart())
        row = await db.get(AuthoringRequest, started.id)
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(hours=25)
        await db.flush()

        read = await service.for_agent(ctx, agent.id)

        assert read.latest is not None and read.latest.status == "failed"


class TestEdges:
    async def test_an_archived_agent_is_not_improved(self, db):
        ctx, agent, _ = await _setup(db)
        agent.status = "archived"
        await db.flush()

        with pytest.raises(BadRequestError, match="archived"):
            await AuthoringService(db).estimate_agent(ctx, agent.id, AuthoringStart())

    @pytest.mark.security
    async def test_an_estimate_prices_a_call_at_the_improvers_model_and_reads_both_budgets(
        self, db
    ):
        ctx = await _owner(db)
        await _published(
            db,
            ctx,
            name="Authoring assistant",
            spec={"name": "Authoring assistant", "model_profile_id": str(uuid.uuid4())},
            kind="improver",
            system_key=IMPROVER.key,
        )
        agent = await _clerk(db, ctx)
        await _rated(db, ctx, agent)
        org = await db.get(Organization, ctx.organization_id)
        assert org is not None
        org.monthly_budget_usd = Decimal("0.01")
        await db.flush()

        with patch("app.services.authoring.price_request", return_value=0.04):
            estimate = await AuthoringService(db).estimate_agent(ctx, agent.id, AuthoringStart())

        assert (estimate.runs, estimate.calls) == (1, 1)
        assert estimate.estimate_usd == Decimal("0.04")
        assert estimate.affordable is False

    async def test_an_unpriced_model_falls_back_to_a_flat_guess(self, db):
        ctx = await _owner(db)
        await _published(
            db,
            ctx,
            name="Authoring assistant",
            spec={"name": "Authoring assistant", "model_profile_id": str(uuid.uuid4())},
            kind="improver",
            system_key=IMPROVER.key,
        )
        agent = await _clerk(db, ctx)
        await _rated(db, ctx, agent)

        with patch("app.services.authoring.price_request", return_value=None):
            estimate = await AuthoringService(db).estimate_agent(ctx, agent.id, AuthoringStart())

        assert estimate.affordable is True and estimate.estimate_usd > 0

    async def test_a_suggestion_is_decided_only_through_its_own_agent(self, db):
        ctx, agent, _ = await _setup(db)
        await _improve(db, ctx, agent, Improver(db))
        other = await _clerk(db, ctx)
        service = AuthoringService(db)
        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None

        with pytest.raises(NotFoundError):
            await service.decide(ctx, other.id, batch.hunks[0].id, HunkDecision(action="dismiss"))
        with pytest.raises(NotFoundError):
            await service.decide(ctx, agent.id, uuid.uuid4(), HunkDecision(action="dismiss"))
        # Deleted between the access check and the lock.
        with (
            patch("app.services.authoring.agent_repo.lock", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError, match="Agent not found"),
        ):
            await service.decide(ctx, agent.id, batch.hunks[0].id, HunkDecision(action="dismiss"))

    async def test_dismissing_all_leaves_accepted_suggestions_and_needs_a_batch(self, db):
        ctx, agent, _ = await _setup(db)
        service = AuthoringService(db)
        assert (await service.dismiss_all(ctx, agent.id)).batch is None
        await _improve(db, ctx, agent, Improver(db))
        batch = (await service.for_agent(ctx, agent.id)).batch
        assert batch is not None
        await service.decide(ctx, agent.id, batch.hunks[0].id, HunkDecision(action="accept"))

        read = await service.dismiss_all(ctx, agent.id)

        assert read.batch is not None
        assert [hunk.status for hunk in read.batch.hunks] == ["accepted", "dismissed"]

    async def test_changes_that_cannot_land_are_not_proposed(self, db):
        ctx, agent, _ = await _setup(db)
        model = Improver(
            db,
            improve={
                "summary": "s",
                "expected_effect": "e",
                "instructions": [
                    {"old_text": "Never written.", "new_text": "x", "rationale": "r"},
                    {"old_text": "Be brief.", "new_text": "Be concise.", "rationale": "r"},
                ],
                "tools": [
                    {
                        "capability_id": "charts",
                        "tool_id": "create_chart",
                        "name": "not a valid name!",
                        "rationale": "r",
                    },
                    {
                        "capability_id": "charts",
                        "tool_id": "create_chart",
                        "description": "x" * 1025,
                        "rationale": "r",
                    },
                    {"capability_id": "charts", "tool_id": "create_chart", "rationale": "r"},
                ],
            },
        )

        request = await _improve(db, ctx, agent, model)

        assert request.report is not None and request.report["recorded"] == 1
        batch = (await AuthoringService(db).for_agent(ctx, agent.id)).batch
        assert batch is not None and [hunk.new_text for hunk in batch.hunks] == ["Be concise."]


class TestWorkerTargets:
    async def test_a_target_gone_mid_request_fails_it(self, db, monkeypatch):
        ctx, agent, _ = await _setup(db)
        service = AuthoringService(db)
        cases = [
            ("improve", "app.services.authoring_worker.agent_repo.get", "The agent is gone."),
            ("verify", "app.services.authoring_worker.agent_repo.get", "no published version"),
        ]
        agent.draft_spec = {**agent.draft_spec, "instructions": "Edited."}
        await db.flush()
        for kind, target, reason in cases:
            started = await service.start_agent(ctx, agent.id, AuthoringStart(kind=kind))
            with patch(target, new=AsyncMock(return_value=None)):
                await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()
            request = await db.get(AuthoringRequest, started.id)
            assert request is not None and request.error is not None and reason in request.error

        started = await service.start_agent(ctx, agent.id, AuthoringStart(kind="verify"))
        with patch(
            "app.services.authoring_worker.agent_repo.get_version", new=AsyncMock(return_value=None)
        ):
            await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()
        request = await db.get(AuthoringRequest, started.id)
        assert request is not None and request.error == "The agent's published version is gone."

    async def test_a_skill_gone_mid_request_fails_it(self, db):
        ctx, agent, run = await _setup(db)
        skill = Skill(
            organization_id=ctx.organization_id,
            owner_user_id=ctx.user_id,
            visibility="org",
            name="refunds",
            description="Refunds",
            content="x",
        )
        db.add(skill)
        await db.flush()
        from app.db.models.conversation import ToolCall

        answer = (
            await db.execute(
                select(Message).where(Message.run_id == run.id, Message.role == "assistant")
            )
        ).scalar_one()
        db.add(
            ToolCall(
                message_id=answer.id,
                tool_call_id="call-1",
                tool_name="load_capability",
                args={"id": "refunds"},
                started_at=datetime.now(UTC),
            )
        )
        await db.flush()
        started = await AuthoringService(db).start_skill(ctx, skill.id, AuthoringStart())

        with patch(
            "app.services.authoring_worker.skill_repo.get", new=AsyncMock(return_value=None)
        ):
            await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()

        request = await db.get(AuthoringRequest, started.id)
        assert request is not None and request.error == "The skill is gone."

        started = await AuthoringService(db).start_skill(ctx, skill.id, AuthoringStart())
        membership = (
            await db.execute(
                select(OrganizationMember).where(OrganizationMember.user_id == ctx.user_id)
            )
        ).scalar_one()
        membership.role = OrgRoleName.OPERATOR.value
        await db.flush()

        await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()

        request = await db.get(AuthoringRequest, started.id)
        assert request is not None
        assert request.error == "Whoever started this may no longer edit the skill."


async def test_an_agent_never_published_has_nothing_to_verify_against(db):
    ctx, agent, _ = await _setup(db)
    agent.current_version_id = None
    await db.flush()

    estimate = await AuthoringService(db).estimate_agent(
        ctx, agent.id, AuthoringStart(kind="verify")
    )

    assert estimate.reason == "no_draft_change" and estimate.calls == 0


class TestSkillCheck:
    async def _proposal(self, db: AsyncSession) -> tuple[AuthoringContext, Skill, SkillProposal]:
        ctx, agent, run = await _setup(db)
        skill = Skill(
            organization_id=ctx.organization_id,
            owner_user_id=ctx.user_id,
            visibility="org",
            name="refunds",
            description="Refunds",
            content="Refunds take 90 days.",
        )
        db.add(skill)
        await db.flush()
        spec = {**agent.draft_spec, "skill_ids": [str(skill.id)]}
        agent.draft_spec = spec
        version = await db.get(AgentVersion, agent.current_version_id)
        assert version is not None
        version.spec = spec
        request = await authoring_repo.create_request(
            db,
            organization_id=ctx.organization_id,
            kind="improve",
            target="skill",
            agent_id=None,
            skill_id=skill.id,
            created_by_user_id=ctx.user_id,
            estimate_usd=Decimal("0.02"),
            window_days=30,
        )
        request.evidence = {"conversation_ids": [str(run.conversation_id)]}
        proposal = SkillProposal(
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            name="refunds",
            description="Refunds, revised",
            content="Refunds take 30 days.",
            resources={},
            authoring_request_id=request.id,
        )
        db.add(proposal)
        await db.flush()
        datasets = DatasetService(db)
        dataset = await datasets.create(ctx, DatasetCreate(name="refund-cases"))
        await datasets.add_case(
            ctx,
            dataset.id,
            DatasetCaseCreate(input="Q", checks=[{"type": "contains", "value": "30 days"}]),
        )
        return AuthoringContext(ctx=ctx, agent=agent, dataset_id=dataset.id), skill, proposal

    async def test_a_skill_change_is_checked_on_an_agent_that_uses_it(self, db):
        setup, skill, proposal = await self._proposal(db)
        service = AuthoringService(db)
        body = ProposalCheck(
            dataset_id=setup.dataset_id, agent_id=setup.agent.id, proposal_id=proposal.id
        )

        estimate = await service.estimate_skill_check(setup.ctx, skill.id, body)
        started = await service.check_skill(setup.ctx, skill.id, body)

        assert estimate.cases == 1
        # The published version on both sides: frozen and validated at publish,
        # so a checker who may only run the agent is not refused its bindings.
        assert started.paired
        assert {arm.source for arm in started.arms} == {"version"}
        assert len({arm.agent_version_id for arm in started.arms}) == 1
        arms = (
            (await db.execute(select(EvalRunArm).where(EvalRunArm.eval_run_id == started.id)))
            .scalars()
            .all()
        )
        assert {arm.role: bool(arm.skill_bodies) for arm in arms} == {
            "candidate": True,
            "baseline": False,
        }
        await db.refresh(skill)
        assert skill.content == "Refunds take 90 days."

    async def test_a_check_needs_a_waiting_change_and_an_agent_that_uses_the_skill(self, db):
        setup, skill, proposal = await self._proposal(db)
        service = AuthoringService(db)
        other = await _clerk(db, setup.ctx)

        with pytest.raises(NotFoundError, match="No change to this skill"):
            await service.check_skill(
                setup.ctx, skill.id, ProposalCheck(dataset_id=setup.dataset_id)
            )
        with pytest.raises(BadRequestError, match="Pick an agent"):
            await service.check_skill(
                setup.ctx,
                skill.id,
                ProposalCheck(dataset_id=setup.dataset_id, proposal_id=proposal.id),
            )
        with pytest.raises(BadRequestError, match="does not use"):
            await service.check_skill(
                setup.ctx,
                skill.id,
                ProposalCheck(
                    dataset_id=setup.dataset_id, agent_id=other.id, proposal_id=proposal.id
                ),
            )
        proposal.authoring_request_id = None
        proposal.status = "discarded"
        await db.flush()
        with pytest.raises(NotFoundError):
            await service.check_skill(
                setup.ctx,
                skill.id,
                ProposalCheck(
                    dataset_id=setup.dataset_id, agent_id=setup.agent.id, proposal_id=proposal.id
                ),
            )

    async def test_a_change_without_a_request_leaves_nothing_out(self, db):
        setup, skill, proposal = await self._proposal(db)
        proposal.authoring_request_id = None
        await db.flush()

        started = await AuthoringService(db).check_skill(
            setup.ctx,
            skill.id,
            ProposalCheck(
                dataset_id=setup.dataset_id, agent_id=setup.agent.id, proposal_id=proposal.id
            ),
        )

        assert started.excluded_case_ids == []


@pytest.mark.security
async def test_what_waits_is_listed_only_for_agents_the_caller_may_edit(db):
    ctx, agent, _ = await _setup(db)
    await _improve(db, ctx, agent, Improver(db))
    db.add(
        SkillProposal(
            organization_id=ctx.organization_id,
            name="refunds",
            description="d",
            content="c",
            resources={},
            authoring_request_id=(
                await authoring_repo.list_requests(
                    db, organization_id=ctx.organization_id, agent_id=agent.id
                )
            )[0].id,
        )
    )
    await db.flush()
    operator = await _member(db, ctx, OrgRoleName.OPERATOR)
    service = AuthoringService(db)

    mine = await service.waiting(ctx)
    theirs = await service.waiting(operator)

    assert [(row.name, row.instructions, row.tools) for row in mine.agents] == [("Clerk", 1, 1)]
    assert mine.skills == 1
    assert theirs.agents == [] and theirs.skills == 0


EVAL_SECRETS = (
    "SECRET-DATASET-CASE",
    "SECRET-CHECK",
    "SECRET-SCORE-ANSWER",
    "SECRET-EVAL-COMMENT",
)


async def _eval_secrets(db: AsyncSession, ctx: AuthContext, agent: Agent) -> None:
    """A dataset, a score and an eval run of `agent`, each holding one of `EVAL_SECRETS`."""
    from app.db.models.case_score import CaseScore
    from app.schemas.eval_run import EvalRunRequest
    from app.services.eval_run import EvalRunService

    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name="hidden-cases"))
    await datasets.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(
            input="SECRET-DATASET-CASE", checks=[{"type": "contains", "value": "SECRET-CHECK"}]
        ),
    )
    case = (
        await db.execute(select(DatasetCase).where(DatasetCase.dataset_id == dataset.id))
    ).scalar_one()
    db.add(
        CaseScore(
            organization_id=ctx.organization_id,
            dataset_id=dataset.id,
            case_revision_id=case.id,
            case_id=case.case_id,
            answer="SECRET-SCORE-ANSWER",
            scoring={},
            results=[],
        )
    )
    await db.flush()
    await EvalRunService(db).start(ctx, agent.id, EvalRunRequest(dataset_id=dataset.id))
    eval_run = await _rated(db, ctx, agent, surface=RunSurface.EVAL, comment="SECRET-EVAL-COMMENT")
    eval_run.input_tokens, eval_run.output_tokens = 900_000, 900_000
    await db.flush()


async def _read_while_working(
    db: AsyncSession, ctx: AuthContext, request_id: Any, model: Improver
) -> tuple[AuthoringRequest, str]:
    """Work a request, and every statement it sent to the database meanwhile."""
    from sqlalchemy import event

    statements: list[str] = []
    engine = db.sync_session.get_bind()

    def seen(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", seen)
    try:
        with _answering(model):
            await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    finally:
        event.remove(engine, "before_cursor_execute", seen)
    request = await db.get(AuthoringRequest, request_id)
    assert request is not None and request.status == "completed", request and request.error
    return request, "\n".join(statements)


def _assert_reads_no_eval(model: Improver, read: str) -> None:
    """No eval secret reached the model, and no eval or dataset table was read."""
    sent = "\n".join(model.prompts)
    for secret in EVAL_SECRETS:
        assert secret not in sent
    assert "agent_runs" in read
    for table in ("eval_runs", "eval_run_cases", "eval_run_arms", "case_scores", "dataset_cases"):
        assert table not in read, table
    assert "FROM datasets" not in read and "JOIN datasets" not in read


@pytest.mark.security
async def test_the_improver_never_reads_an_eval_run_a_score_or_a_dataset(db):
    """What checks the assistant must never be what it learns from: no eval run, no
    score and no dataset case reaches the model, and the request reads none of
    their tables - pricing a change of model included."""
    from app.db.models.credential import ModelProfile

    ctx, agent, run = await _setup(db)
    await _eval_secrets(db, ctx, agent)
    cheaper = ModelProfile(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        label="gpt-4o-mini",
        provider="openai",
        model="gpt-4o-mini",
    )
    db.add(cheaper)
    await db.flush()
    model = Improver(
        db,
        improve={
            "summary": "s",
            "expected_effect": "e",
            "instructions": [],
            "tools": [],
            "fields": [
                {
                    "path": "model_profile_id",
                    "op": "set",
                    "value": str(cheaper.id),
                    "rationale": "r",
                    "expected_effect": "e",
                    "evidence": [{"run_id": str(run.id), "quote": COMMENT}],
                }
            ],
        },
    )

    started = await AuthoringService(db).start_agent(ctx, agent.id, AuthoringStart())
    request, read = await _read_while_working(db, ctx, started.id, model)

    _assert_reads_no_eval(model, read)
    assert request.evidence["runs"] == 1
    batch = (await AuthoringService(db).for_agent(ctx, agent.id)).batch
    assert batch is not None
    (hunk,) = batch.hunks
    assert hunk.effect is not None and hunk.effect["runs"] == 1
