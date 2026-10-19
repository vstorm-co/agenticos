"""Scoring a recorded run against a dataset case, against a real database.

The judge runs for real: the seeded eval judge, through the runner's own
`execute`, with only the model replaced. So what is asserted about its budget,
its run row and its surface is what the platform does, not what a stub was told.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.model_resolver import ModelRequestSpec
from app.agents.spec import AgentSpec
from app.agents.system_agents import JUDGE
from app.core.exceptions import (
    AiAssistanceDisabledError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    NothingToScoreError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.agent import Agent, AgentStatus
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.credential import ModelProfile
from app.db.models.dataset import DatasetVersion
from app.db.models.eval_run import EvalRun
from app.db.models.intercepted_tool_call import (
    InterceptedToolCall,
    InterceptionOutcome,
    InterceptionReason,
)
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.user import User
from app.repositories import (
    agent_repo,
    agent_run_repo,
    case_score_repo,
    conversation_repo,
    dataset_repo,
    intercepted_tool_call_repo,
)
from app.schemas.dataset import (
    DatasetCaseCreate,
    DatasetCreate,
    DatasetUpdate,
    ExpectedToolCall,
)
from app.schemas.resource_grant import VisibilityLiteral
from app.schemas.scoring import (
    CaseScoreCreate,
    CaseVerdict,
    ChecksScorer,
    DatasetScoring,
    JudgeCreate,
    JudgeScorer,
    ReferenceScorer,
    RescoreRequest,
    ReviewRequest,
    ReviewScorer,
    RubricCriterion,
    TrajectoryScorer,
)
from app.services.agent_registry import AgentRegistryService
from app.services.dataset import DatasetService
from app.services.scorers import JUDGE_PROMPT_VERSION
from app.services.scoring import STARTING_CRITERION, ScoringService
from app.services.system_agents import SystemAgentService

pytestmark = pytest.mark.anyio

SCHEMA = {"type": "object", "properties": {"days": {"type": "integer"}}, "required": ["days"]}
RUBRIC = [
    RubricCriterion(name="correctness", description="The refund window is right"),
    RubricCriterion(name="tone", description="Warm and polite"),
]


@dataclass
class Tenant:
    organization: Organization
    owner: User
    ctx: AuthContext


class Judge:
    """The judge's model: grades every criterion id it is handed, and counts calls."""

    def __init__(self, grades: dict[str, int] | None = None, reason: str = "Looks right") -> None:
        self.calls = 0
        self.grades = grades or {}
        self.reason = reason
        self.quotes: list[str] = []

    def model(self) -> FunctionModel:
        async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            self.calls += 1
            prompt = str(messages[-1].parts[-1].content)  # type: ignore[union-attr]
            ids = re.findall(r"^- (\w+) \(", prompt, flags=re.MULTILINE)
            grades = [
                {
                    "id": item,
                    "score": self.grades.get(item, 5),
                    "reason": self.reason,
                    "quotes": self.quotes,
                }
                for item in ids
            ]
            return ModelResponse(parts=[TextPart(json.dumps({"grades": grades}))])

        return FunctionModel(respond)


@pytest.fixture
def judge(monkeypatch) -> Iterator[Judge]:
    judging = Judge()
    monkeypatch.setattr(ModelRequestSpec, "build", lambda self: judging.model())
    yield judging


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password="x",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _tenant(db) -> Tenant:
    owner = await _user(db)
    organization = Organization(
        id=uuid.uuid4(),
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        created_by_user_id=owner.id,
        ai_assistance_enabled=True,
    )
    db.add(organization)
    await db.flush()
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=organization.id,
            user_id=owner.id,
            role=OrgRoleName.OWNER.value,
        )
    )
    await db.flush()
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    return Tenant(organization=organization, owner=owner, ctx=ctx)


async def _join(db, tenant: Tenant, role: OrgRoleName) -> AuthContext:
    user = await _user(db)
    db.add(
        OrganizationMember(
            id=uuid.uuid4(),
            organization_id=tenant.organization.id,
            user_id=user.id,
            role=role.value,
        )
    )
    await db.flush()
    return AuthContext(user_id=user.id, organization_id=tenant.organization.id, role=role)


async def _model(db, tenant: Tenant) -> ModelProfile:
    """A model profile with a key behind it, so a run can be assembled."""
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-key"), scope=VaultScope.organization(tenant.organization.id)
    )
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=tenant.organization.id,
        name="Key",
        purpose="openai",
        visibility="org",
        kind=SecretKind.API_KEY.value,
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
    )
    db.add(secret)
    await db.flush()
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=tenant.organization.id,
        label="Default",
        provider="openai",
        model="gpt-4.1",
        secret_id=secret.id,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _scored_run(db, tenant: Tenant, *, answer: str = '{"days": 30}') -> AgentRun:
    """A finished run of a support agent: one answer, two tool calls written at one instant.

    The calls are inserted in the reverse of the order the turn's `parts` record,
    so only the parts can put them right.
    """
    registry = AgentRegistryService(db)
    agent = await registry.create(tenant.ctx, AgentSpec(name=f"Support {uuid.uuid4().hex[:6]}"))
    conversation = await conversation_repo.create_conversation(
        db, organization_id=tenant.organization.id, user_id=tenant.owner.id
    )
    started = datetime.now(UTC) - timedelta(seconds=3)
    run = await agent_run_repo.create_run(
        db,
        organization_id=tenant.organization.id,
        agent_id=agent.id,
        agent_version_id=None,
        user_id=tenant.owner.id,
        conversation_id=conversation.id,
        surface=RunSurface.WEB.value,
        model_label="gpt-4.1",
        started_at=started,
    )
    run = await agent_run_repo.finish_run(
        db,
        run=run,
        status=RunStatus.COMPLETED.value,
        input_tokens=100,
        output_tokens=20,
        cost_usd=Decimal("0.004"),
        cost_is_partial=False,
        ended_at=started + timedelta(milliseconds=1500),
    )
    message = await conversation_repo.create_message(
        db,
        conversation_id=conversation.id,
        role="assistant",
        content=answer,
        parts=[
            {"type": "tool", "tool_call_id": "call-search"},
            {"type": "tool", "tool_call_id": "call-lookup"},
            {"type": "text", "text": answer},
        ],
        agent_id=agent.id,
        run_id=run.id,
    )
    instant = datetime.now(UTC)
    for call_id, tool, args in (
        ("call-lookup", "lookup_order", {"order": 7}),
        ("call-search", "search_kb", {"query": "refunds", "limit": 5}),
    ):
        await conversation_repo.create_tool_call(
            db,
            message_id=message.id,
            tool_call_id=call_id,
            tool_name=tool,
            args=args,
            started_at=instant,
        )
    return run


async def _dataset(
    db, tenant: Tenant, *, scoring: DatasetScoring, visibility: VisibilityLiteral = "private"
):
    datasets = DatasetService(db)
    dataset = await datasets.create(
        tenant.ctx, DatasetCreate(name=f"Refunds {uuid.uuid4().hex[:6]}", visibility=visibility)
    )
    case = await datasets.add_case(
        tenant.ctx,
        dataset.id,
        DatasetCaseCreate(
            input="How long do I have to return an order?",
            reference_answer="Thirty days.",
            expected_tool_calls=[
                ExpectedToolCall(tool="search_kb", args={"query": "refunds"}),
                ExpectedToolCall(tool="lookup_order"),
            ],
            order_mode="in_order",
            checks=[{"type": "json_schema", "schema": SCHEMA}],
        ),
    )
    await ScoringService(db).set_scoring(tenant.ctx, dataset.id, scoring)
    return dataset, case


def _rubric(**overrides) -> DatasetScoring:
    return DatasetScoring(judge=JudgeScorer(enabled=True, criteria=RUBRIC), **overrides)


async def _eval_run(db, tenant: Tenant, dataset, run: AgentRun) -> uuid.UUID:
    """An eval run's row, for a score to belong to."""
    version = await db.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.number.desc())
    )
    eval_run = EvalRun(
        organization_id=tenant.organization.id,
        agent_id=run.agent_id,
        dataset_id=dataset.id,
        dataset_version_id=version.id,
        status="completed",
        purpose="manual",
        scoring={},
        scoring_hash="",
        estimate_usd=Decimal(0),
    )
    db.add(eval_run)
    await db.flush()
    return eval_run.id


async def _score_for_an_eval(db, tenant: Tenant, dataset, case, run: AgentRun, eval_run_id):
    """Score `run` as an eval run scores it: never queued by the dataset's review setting."""
    service = ScoringService(db)
    row = await dataset_repo.get(db, dataset.id, organization_id=tenant.organization.id)
    revision = await service.datasets.case_at(tenant.ctx, row, case.case_id, version=None)
    answer = await service.answer_of(tenant.ctx, run.id)
    return await service.score_case(
        tenant.ctx,
        dataset=row,
        case=revision,
        answer=answer,
        enqueue_review=False,
        eval_run_id=eval_run_id,
    )


async def _eval_runs(db, tenant: Tenant) -> list[AgentRun]:
    rows = await db.scalars(
        select(AgentRun).where(
            AgentRun.organization_id == tenant.organization.id,
            AgentRun.surface == RunSurface.EVAL.value,
        )
    )
    return list(rows)


class TestScoringARun:
    async def test_a_schema_check_an_expected_call_and_a_rubric_each_give_a_reason(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        judge.grades = {"r2": 2}

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        found = {(r.scorer, r.name): r for r in score.results}
        assert found[("check", "json_schema")].status == "pass"
        assert found[("check", "json_schema")].reason == "Matches the schema"
        assert found[("trajectory", "tool calls (in_order)")].status == "pass"
        assert (
            found[("trajectory", "tool calls (in_order)")].reason
            == "Called search_kb, lookup_order"
        )
        assert found[("judge", "correctness")].status == "pass"
        assert found[("judge", "correctness")].reason == "5/5: Looks right"
        assert found[("judge", "tone")].status == "fail"
        assert found[("judge", "tone")].reason == "2/5: Looks right"
        assert score.passed is False
        assert score.run_id == run.id
        assert (score.question, score.reference_answer) == (
            "How long do I have to return an order?",
            "Thirty days.",
        )
        assert score.run_model == "gpt-4.1"

    async def test_a_score_pins_the_judge_that_graded_it(self, db, judge) -> None:
        tenant = await _tenant(db)
        profile = await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)
        judge_agent = await SystemAgentService(db).ensure(
            organization_id=tenant.organization.id, key=JUDGE.key
        )

        first = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        again = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        await scoring.set_scoring(
            tenant.ctx,
            dataset.id,
            DatasetScoring(judge=JudgeScorer(enabled=True, criteria=RUBRIC[:1])),
        )
        narrower = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        assert first.judge is not None and narrower.judge is not None
        assert (first.judge.agent_version_id, first.judge.spec_version) == (
            judge_agent.current_version_id,
            1,
        )
        assert first.judge.model_profile_id == profile.id
        assert (first.judge_model, first.run_model) == ("Default", "gpt-4.1")
        assert again.judge == first.judge
        assert narrower.judge.rubric_hash != first.judge.rubric_hash
        graded = await scoring.list_scores(tenant.ctx, dataset.id, judge_id=judge_agent.id)
        elsewhere = await scoring.list_scores(tenant.ctx, dataset.id, judge_id=uuid.uuid4())
        assert {score.id for score in graded.items} == {first.id, again.id, narrower.id}
        assert elsewhere.total == 0

    async def test_a_judge_model_gone_or_never_pinned_is_named_as_nothing(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)
        unpinned = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        row = await case_score_repo.get(
            db, unpinned.id, organization_id=tenant.organization.id, dataset_id=dataset.id
        )
        assert row is not None and row.judge is not None
        await case_score_repo.update(
            db, score=row, update_data={"judge": {**row.judge, "model_profile_id": None}}
        )
        orphaned = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        row = await case_score_repo.get(
            db, orphaned.id, organization_id=tenant.organization.id, dataset_id=dataset.id
        )
        assert row is not None and row.judge is not None
        await case_score_repo.update(
            db,
            score=row,
            update_data={"judge": {**row.judge, "model_profile_id": str(uuid.uuid4())}},
        )

        listed = await scoring.list_scores(tenant.ctx, dataset.id)

        assert {item.id: item.judge_model for item in listed.items} == {
            unpinned.id: None,
            orphaned.id: None,
        }

    async def test_the_judge_is_a_recorded_eval_run_in_activity(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        [judged] = await _eval_runs(db, tenant)
        judge_agent = await agent_repo.get_system(
            db, organization_id=tenant.organization.id, key=JUDGE.key
        )
        assert judge_agent is not None
        assert judged.agent_id == judge_agent.id
        assert judged.status == RunStatus.COMPLETED.value
        assert judged.user_id == tenant.owner.id
        assert {r.judge_run_id for r in score.results if r.scorer == "judge"} == {judged.id}
        assert judge.calls == 1

    @pytest.mark.security
    async def test_a_spent_judge_budget_is_refused_before_the_model_and_still_recorded(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        judge_agent = await SystemAgentService(db).ensure(
            organization_id=tenant.organization.id, key=JUDGE.key
        )
        spent = await agent_run_repo.create_run(
            db,
            organization_id=tenant.organization.id,
            agent_id=judge_agent.id,
            agent_version_id=judge_agent.current_version_id,
            user_id=tenant.owner.id,
            conversation_id=None,
            surface=RunSurface.EVAL.value,
            model_label="gpt-4.1",
            started_at=datetime.now(UTC),
        )
        await agent_run_repo.finish_run(
            db,
            run=spent,
            status=RunStatus.COMPLETED.value,
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal(str(JUDGE.monthly_usd + 1)),
            cost_is_partial=False,
            ended_at=datetime.now(UTC),
        )

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        judged = [r for r in score.results if r.scorer == "judge"]
        assert {(r.status, r.reason_code) for r in judged} == {("skipped", "judge_budget")}
        assert judge.calls == 0
        refused = [r for r in await _eval_runs(db, tenant) if r.id != spent.id]
        assert [r.status for r in refused] == [RunStatus.BUDGET_EXCEEDED.value]
        assert {r.judge_run_id for r in judged} == {refused[0].id}
        assert score.passed is None

    async def test_calls_written_at_one_instant_keep_the_order_the_turn_recorded(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        run = await _scored_run(db, tenant)

        answer = await ScoringService(db).answer_of(tenant.ctx, run.id)

        assert [call.tool for call in answer.calls] == ["search_kb", "lookup_order"]
        assert answer.latency_ms == 1500
        assert answer.cost_usd == Decimal("0.004")

    async def test_a_write_the_isolated_run_blocked_still_meets_the_expected_call(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        await intercepted_tool_call_repo.add_many(
            db,
            run_id=run.id,
            organization_id=tenant.organization.id,
            calls=[
                InterceptedToolCall(
                    tool_call_id="call-lookup",
                    tool_name="lookup_order",
                    tool_id="tool:lookup_order",
                    args={"order": 7},
                    outcome=InterceptionOutcome.BLOCKED,
                    reason=InterceptionReason.WRITES,
                ),
                InterceptedToolCall(
                    tool_call_id="call-search",
                    tool_name="search_kb",
                    tool_id="tool:search_kb",
                    args={"query": "refunds", "limit": 5},
                    outcome=InterceptionOutcome.REPLAYED,
                ),
            ],
        )

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        [trajectory] = [r for r in score.results if r.scorer == "trajectory"]
        assert trajectory.status == "pass"
        assert (
            trajectory.reason
            == "Called search_kb, lookup_order (lookup_order blocked, not executed)"
        )
        assert score.passed is True

    async def test_a_reference_answer_is_graded_by_the_judge(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(
            db, tenant, scoring=DatasetScoring(reference=ReferenceScorer(enabled=True))
        )
        run = await _scored_run(db, tenant)
        judge.grades = {"ref": 1}

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        [reference] = [r for r in score.results if r.scorer == "reference"]
        assert reference.status == "fail"
        assert score.passed is False

    async def test_a_quote_the_answer_does_not_hold_is_flagged_on_a_kept_score(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        judge.quotes = ['"days": 30', "ninety days"]

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        graded = {
            (r.reason, tuple(r.unverified_quotes)) for r in score.results if r.scorer == "judge"
        }
        assert graded == {("5/5: Looks right", ("ninety days",))}
        assert score.passed is True

    @pytest.mark.security
    async def test_a_secret_the_judge_quotes_is_not_kept(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        judge.reason = "It leaked ghp_" + "a1B2" * 9
        judge.quotes = ["the key ghp_" + "c3D4" * 9]

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        judged = [r for r in score.results if r.scorer == "judge"]
        assert all("[redacted:github_token]" in result.reason for result in judged)
        quotes = [quote for result in judged for quote in result.unverified_quotes]
        assert quotes and all("[redacted:github_token]" in quote for quote in quotes)
        assert not any("ghp_" in text for text in [*quotes, *(r.reason for r in judged)])

    async def test_a_run_with_no_answer_cannot_be_scored(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        agent = await AgentRegistryService(db).create(tenant.ctx, AgentSpec(name="Silent"))
        run = await agent_run_repo.create_run(
            db,
            organization_id=tenant.organization.id,
            agent_id=agent.id,
            agent_version_id=None,
            user_id=tenant.owner.id,
            conversation_id=None,
            surface=RunSurface.API.value,
            model_label=None,
            started_at=datetime.now(UTC),
        )

        with pytest.raises(BadRequestError, match="no answer to score"):
            await ScoringService(db).score_run(
                tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
            )


class TestADatasetsOwnJudge:
    async def test_it_grades_the_dataset_and_the_score_pins_it(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)

        made = await scoring.create_judge(
            tenant.ctx, dataset.id, JudgeCreate(name="Refunds judge", instructions="Be strict.")
        )
        score = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        own = made.scoring.judge.agent_id
        assert own is not None
        assert (made.scoring.judge.enabled, made.judge_name) == (True, "Refunds judge")
        [judged] = await _eval_runs(db, tenant)
        assert judged.agent_id == own
        assert score.judge is not None and score.judge.agent_id == own

    @pytest.mark.security
    async def test_it_is_as_visible_as_the_dataset_it_grades(self, db, judge) -> None:
        """Its prompt holds the dataset's name, description and what it must know,
        so a private dataset does not get a judge the whole organization reads."""
        tenant = await _tenant(db)
        await _model(db, tenant)
        private, _ = await _dataset(db, tenant, scoring=_rubric())
        shared, _ = await _dataset(db, tenant, scoring=_rubric(), visibility="org")
        scoring = ScoringService(db)

        hidden = await scoring.create_judge(
            tenant.ctx, private.id, JudgeCreate(name="Private judge")
        )
        seen = await scoring.create_judge(tenant.ctx, shared.id, JudgeCreate(name="Org judge"))

        visibility = {}
        for made in (hidden, seen):
            own = made.scoring.judge.agent_id
            assert own is not None
            agent = await agent_repo.get(db, own, organization_id=tenant.organization.id)
            assert agent is not None
            visibility[made.id] = agent.visibility
        assert visibility == {private.id: "private", shared.id: "org"}

    async def test_a_creator_who_may_not_publish_gets_a_draft_judge(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        member = await _join(db, tenant, OrgRoleName.MEMBER)
        dataset = await DatasetService(db).create(member, DatasetCreate(name="Mine"))

        made = await ScoringService(db).create_judge(
            member, dataset.id, JudgeCreate(name="My judge")
        )

        own = made.scoring.judge.agent_id
        assert own is not None
        agent = await agent_repo.get(db, own, organization_id=tenant.organization.id)
        assert agent is not None
        assert (agent.kind, agent.current_version_id) == ("judge", None)

    async def test_it_grades_by_the_default_judge_s_rules_with_the_dataset_added(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, _ = await _dataset(db, tenant, scoring=_rubric())
        await DatasetService(db).update(
            tenant.ctx, dataset.id, DatasetUpdate(description="Returns and refunds")
        )
        scoring = ScoringService(db)

        template = await scoring.judge_template(tenant.ctx, dataset.id)
        made = await scoring.create_judge(
            tenant.ctx, dataset.id, JudgeCreate(name="Refunds judge", knowledge="30 days.")
        )

        assert template.instructions.startswith(JUDGE.instructions)
        assert (
            f'dataset "{dataset.name}". It is about: Returns and refunds' in template.instructions
        )
        own = made.scoring.judge.agent_id
        assert own is not None
        agent = await agent_repo.get(db, own, organization_id=tenant.organization.id)
        assert agent is not None and agent.current_version_id is not None
        version = await agent_repo.get_version(
            db, agent.current_version_id, organization_id=tenant.organization.id
        )
        assert version is not None
        cloned = version.spec["instructions"]
        assert "a counter-example is given, it is a known bad answer" in cloned
        assert "Do not reward length, confidence or polish" in cloned
        assert cloned == f"{template.instructions}\n\nWhat you must know to grade:\n30 days."

    async def test_creating_it_switches_grading_on_with_a_criterion_and_the_reference(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring())
        empty = await DatasetService(db).create(tenant.ctx, DatasetCreate(name="Tone"))
        await ScoringService(db).set_scoring(tenant.ctx, empty.id, DatasetScoring())

        made = await ScoringService(db).create_judge(
            tenant.ctx, dataset.id, JudgeCreate(name="Refunds judge", instructions="Be strict.")
        )
        bare = await ScoringService(db).create_judge(
            tenant.ctx, empty.id, JudgeCreate(name="Tone judge", instructions="Be fair.")
        )

        assert made.scoring.judge.enabled is True
        assert [c.name for c in made.scoring.judge.criteria] == [STARTING_CRITERION.name]
        assert made.scoring.reference.enabled is True
        assert (bare.scoring.judge.enabled, bare.scoring.reference.enabled) == (True, False)

    async def test_creating_it_keeps_the_rubric_the_dataset_already_has(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, _ = await _dataset(db, tenant, scoring=_rubric())

        made = await ScoringService(db).create_judge(
            tenant.ctx, dataset.id, JudgeCreate(name="Refunds judge", instructions="Be strict.")
        )

        assert [c.name for c in made.scoring.judge.criteria] == ["correctness", "tone"]

    async def test_with_ai_assistance_off_creating_it_only_picks_it(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring())
        tenant.organization.ai_assistance_enabled = False
        await db.flush()

        made = await ScoringService(db).create_judge(
            tenant.ctx, dataset.id, JudgeCreate(name="Refunds judge", instructions="Be strict.")
        )

        assert made.scoring.judge.agent_id is not None
        assert (made.scoring.judge.enabled, made.scoring.judge.criteria) == (False, [])
        assert made.scoring.reference.enabled is False

    async def test_it_knows_what_it_was_told_and_grades_at_temperature_zero(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, _ = await _dataset(db, tenant, scoring=_rubric())

        made = await ScoringService(db).create_judge(
            tenant.ctx,
            dataset.id,
            JudgeCreate(
                name="Refunds judge",
                instructions="Be strict.",
                knowledge="  Refunds are allowed for 30 days.  ",
            ),
        )

        own = made.scoring.judge.agent_id
        assert own is not None
        agent = await agent_repo.get(db, own, organization_id=tenant.organization.id)
        assert agent is not None and agent.current_version_id is not None
        version = await agent_repo.get_version(
            db, agent.current_version_id, organization_id=tenant.organization.id
        )
        assert version is not None
        assert version.spec["instructions"] == (
            "Be strict.\n\nWhat you must know to grade:\nRefunds are allowed for 30 days."
        )
        assert version.spec["model_settings"] == {"temperature": 0.0}

    async def test_a_judge_that_is_gone_skips_the_judge_and_says_so(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)
        made = await scoring.create_judge(
            tenant.ctx, dataset.id, JudgeCreate(name="Refunds judge", instructions="Be strict.")
        )
        own = made.scoring.judge.agent_id
        assert own is not None
        gone = await agent_repo.get(db, own, organization_id=tenant.organization.id)
        assert gone is not None
        await agent_repo.delete(db, gone)

        score = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        codes = {result.reason_code for result in score.results if result.scorer == "judge"}
        assert codes == {"judge_missing"}
        assert score.passed is None
        assert judge.calls == 0

    async def test_an_ordinary_agent_cannot_be_picked_as_the_judge(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring())
        mine = await AgentRegistryService(db).create(tenant.ctx, AgentSpec(name="Support"))

        with pytest.raises(BadRequestError) as refused:
            await ScoringService(db).set_scoring(
                tenant.ctx,
                dataset.id,
                DatasetScoring(judge=JudgeScorer(enabled=True, agent_id=mine.id, criteria=RUBRIC)),
            )

        assert refused.value.details["fields"][0]["field"] == "judge.agent_id"

    async def test_one_of_the_organization_s_judges_can_be_picked(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring())
        other = await SystemAgentService(db).create_judge(
            tenant.ctx,
            name="Tone judge",
            description="Grades tone.",
            visibility=Visibility.ORG,
            instructions="Be fair.",
        )

        saved = await ScoringService(db).set_scoring(
            tenant.ctx,
            dataset.id,
            DatasetScoring(judge=JudgeScorer(enabled=True, agent_id=other.id, criteria=RUBRIC)),
        )

        assert (saved.scoring.judge.agent_id, saved.judge_name) == (other.id, "Tone judge")

    async def test_datasets_list_by_their_judge_picked_grading_or_not(self, db, judge) -> None:
        tenant = await _tenant(db)
        default = await SystemAgentService(db).ensure(
            organization_id=tenant.organization.id, key=JUDGE.key
        )
        by_default, _ = await _dataset(db, tenant, scoring=_rubric())
        ungraded, _ = await _dataset(db, tenant, scoring=DatasetScoring())
        by_own, _ = await _dataset(db, tenant, scoring=_rubric())
        made = await ScoringService(db).create_judge(
            tenant.ctx, by_own.id, JudgeCreate(name="Refunds judge", instructions="Be strict.")
        )
        own = made.scoring.judge.agent_id
        assert own is not None
        paused, _ = await _dataset(
            db, tenant, scoring=DatasetScoring(judge=JudgeScorer(agent_id=own))
        )
        datasets = DatasetService(db)

        graded_by_default = await datasets.list_readable(tenant.ctx, judge_id=default.id)
        graded_by_own = await datasets.list_readable(tenant.ctx, judge_id=own)
        everything = await datasets.list_readable(tenant.ctx)

        assert [item.id for item in graded_by_default.items] == [by_default.id]
        assert {item.id for item in graded_by_own.items} == {by_own.id, paused.id}
        names = {item.id: item.judge_name for item in everything.items}
        assert names == {
            by_default.id: default.name,
            ungraded.id: default.name,
            by_own.id: "Refunds judge",
            paused.id: "Refunds judge",
        }


class TestWhenTheJudgeCannotRun:
    async def test_switched_off_the_judge_is_skipped_and_the_checks_still_score(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        tenant.organization.ai_assistance_enabled = False
        await db.flush()

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        by_scorer = {r.scorer: r for r in score.results}
        assert by_scorer["check"].status == "pass"
        assert by_scorer["trajectory"].status == "pass"
        judged = [r for r in score.results if r.scorer == "judge"]
        assert {(r.status, r.reason_code) for r in judged} == {("skipped", "ai_assistance_off")}
        assert score.passed is None
        assert (score.judge, score.judge_model) == (None, None)
        assert judge.calls == 0
        assert await _eval_runs(db, tenant) == []

    async def test_a_deleted_judge_model_skips_the_judge_and_the_checks_still_score(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        profile = await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        await SystemAgentService(db).ensure(organization_id=tenant.organization.id, key=JUDGE.key)
        await db.delete(profile)
        await db.flush()

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        by_scorer = {r.scorer: r for r in score.results}
        assert by_scorer["check"].status == "pass"
        assert by_scorer["trajectory"].status == "pass"
        judged = [r for r in score.results if r.scorer == "judge"]
        assert {(r.status, r.reason_code) for r in judged} == {("skipped", "judge_no_model")}
        assert judge.calls == 0
        assert score.passed is None

    async def test_an_unpublished_judge_says_so(self, db, judge) -> None:
        """A dataset's own judge created before any model stays a draft until published."""
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        await ScoringService(db).create_judge(
            tenant.ctx, dataset.id, JudgeCreate(name="Refunds judge", instructions="Be strict.")
        )
        await _model(db, tenant)
        run = await _scored_run(db, tenant)

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        judged = [r for r in score.results if r.scorer == "judge"]
        assert {r.reason_code for r in judged} == {"judge_unpublished"}

    async def test_the_seeded_judge_waits_unpublished_while_there_is_no_model(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        judged = [r for r in score.results if r.scorer == "judge"]
        assert {r.reason_code for r in judged} == {"judge_unpublished"}
        assert judge.calls == 0

    async def test_an_archived_judge_says_so(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        judge_agent = await SystemAgentService(db).ensure(
            organization_id=tenant.organization.id, key=JUDGE.key
        )
        await agent_repo.update(
            db, agent=judge_agent, update_data={"status": AgentStatus.ARCHIVED.value}
        )
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        assert {r.reason_code for r in score.results if r.scorer == "judge"} == {"judge_archived"}

    async def test_an_unreadable_judge_answer_is_an_error_on_its_recorded_run(
        self, db, monkeypatch
    ) -> None:
        async def prose(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("It is fine.\n\n" + "Truly " * 400)])

        monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(prose))
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        judged = [r for r in score.results if r.scorer == "judge"]
        [recorded] = await _eval_runs(db, tenant)
        assert {(r.status, r.reason_code, r.judge_run_id) for r in judged} == {
            ("error", "judge_output_invalid", recorded.id)
        }
        assert (score.passed, score.unscored_reason) == (None, "judge_output_invalid")
        said = {r.judge_said for r in judged}
        assert len(said) == 1
        [shown] = said
        assert shown is not None and shown.startswith("It is fine. Truly Truly")
        assert (len(shown), shown[-1]) == (2_001, "…")
        assert recorded.error is not None
        assert recorded.error.startswith("The answer did not match the shape asked for - ")
        assert "Truly" not in recorded.error


class TestJudgeAgreement:
    async def test_people_agreed_with_the_judge_on_some_of_what_they_decided(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric(), visibility="private")
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)
        judge.grades = {"r2": 2}
        scores = [
            await scoring.score_run(
                tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
            )
            for _ in range(3)
        ]
        assert {score.passed for score in scores} == {False}
        await scoring.set_verdict(tenant.ctx, dataset.id, scores[0].id, CaseVerdict(passed=False))
        await scoring.set_verdict(tenant.ctx, dataset.id, scores[1].id, CaseVerdict(passed=True))
        judge_agent = await agent_repo.get_system(
            db, organization_id=tenant.organization.id, key=JUDGE.key
        )
        assert judge_agent is not None
        stranger = await _join(db, tenant, OrgRoleName.MEMBER)

        mine = await scoring.judge_agreement(tenant.ctx, judge_agent.id)
        theirs = await scoring.judge_agreement(stranger, judge_agent.id)
        other = await scoring.judge_agreement(tenant.ctx, uuid.uuid4())

        assert (mine.agreed, mine.decided) == (1, 2)
        assert (theirs.agreed, theirs.decided) == (0, 0)
        assert (other.agreed, other.decided) == (0, 0)


class TestJudgeAgreementIsTheJudgesOwn:
    async def test_a_check_failing_beside_the_judge_is_not_counted_against_it(
        self, db, monkeypatch
    ) -> None:
        judging = Judge()
        answers = iter(["", "", "It is fine."])

        def model(self) -> FunctionModel:
            async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                if next(answers, "") == "It is fine.":
                    return ModelResponse(parts=[TextPart("It is fine.")])
                return await judging.model().function(messages, info)  # type: ignore[misc]

            return FunctionModel(respond)

        monkeypatch.setattr(ModelRequestSpec, "build", model)
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant, answer="Thirty days, as the policy says.")
        scoring = ScoringService(db)
        scores = [
            await scoring.score_run(
                tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
            )
            for _ in range(3)
        ]
        # The answer is not JSON, so the required schema check fails every case,
        # while the judge passes two and cannot read the third.
        assert [score.passed for score in scores] == [False, False, False]
        assert {r.reason_code for r in scores[2].results if r.scorer == "judge"} == {
            "judge_output_invalid"
        }
        for score in scores:
            await scoring.set_verdict(tenant.ctx, dataset.id, score.id, CaseVerdict(passed=True))
        judge_agent = await agent_repo.get_system(
            db, organization_id=tenant.organization.id, key=JUDGE.key
        )
        assert judge_agent is not None

        agreement = await scoring.judge_agreement(tenant.ctx, judge_agent.id)

        assert (agreement.agreed, agreement.decided) == (2, 2)


class TestGradingAgain:
    async def test_a_score_the_judge_failed_is_graded_again_on_the_same_answer(
        self, db, monkeypatch
    ) -> None:
        judging = Judge()
        answers = iter(["It is fine."])

        def model(self) -> FunctionModel:
            async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                text = next(answers, None)
                if text is not None:
                    return ModelResponse(parts=[TextPart(text)])
                return await judging.model().function(messages, info)  # type: ignore[misc]

            return FunctionModel(respond)

        monkeypatch.setattr(ModelRequestSpec, "build", model)
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(
            db, tenant, scoring=_rubric(review=ReviewScorer(select="failed"))
        )
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)
        failed = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        sound = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        await scoring.set_verdict(tenant.ctx, dataset.id, failed.id, CaseVerdict(passed=False))
        await scoring.set_scoring(tenant.ctx, dataset.id, DatasetScoring())

        result = await scoring.rescore(
            tenant.ctx, dataset.id, RescoreRequest(score_ids=[failed.id, sound.id, failed.id])
        )

        [again] = result.rescored
        assert result.kept == [sound.id]
        assert again.id == failed.id
        assert (again.passed, again.unscored_reason) == (True, None)
        assert {r.status for r in again.results} == {"pass"}
        assert {r.scorer for r in again.results} == {"check", "trajectory", "judge"}
        assert again.judge is not None and again.judge.prompt_version == JUDGE_PROMPT_VERSION
        assert (again.human_passed, again.outcome, again.review_state) == (False, False, "done")
        assert len(await _eval_runs(db, tenant)) == 3

    async def test_a_waiting_answer_scored_again_to_a_pass_leaves_the_queue(
        self, db, monkeypatch
    ) -> None:
        judging = Judge()
        answers = iter(["It is fine."])

        def model(self) -> FunctionModel:
            async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                if next(answers, None) is not None:
                    return ModelResponse(parts=[TextPart("It is fine.")])
                return await judging.model().function(messages, info)  # type: ignore[misc]

            return FunctionModel(respond)

        monkeypatch.setattr(ModelRequestSpec, "build", model)
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(
            db, tenant, scoring=_rubric(review=ReviewScorer(select="failed"))
        )
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)
        waiting = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        assert (waiting.passed, waiting.review_state) == (None, "pending")

        [again] = (
            await scoring.rescore(tenant.ctx, dataset.id, RescoreRequest(score_ids=[waiting.id]))
        ).rescored

        assert (again.passed, again.review_state) == (True, "none")

    async def test_nothing_is_graded_again_when_one_answer_cannot_be_read(
        self, db, monkeypatch
    ) -> None:
        async def prose(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("It is fine.")])

        monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(prose))
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)
        readable = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        lost = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        row = await case_score_repo.get(
            db, lost.id, organization_id=tenant.organization.id, dataset_id=dataset.id
        )
        assert row is not None
        await case_score_repo.update(db, score=row, update_data={"run_id": None})
        before = len(await _eval_runs(db, tenant))

        with pytest.raises(BadRequestError, match="names no run"):
            await scoring.rescore(
                tenant.ctx, dataset.id, RescoreRequest(score_ids=[readable.id, lost.id])
            )

        assert len(await _eval_runs(db, tenant)) == before

    async def test_a_cause_still_there_or_an_eval_runs_judge_changed_since_is_refused(
        self, db, monkeypatch
    ) -> None:
        async def prose(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("It is fine.")])

        monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(prose))
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)
        eval_run_id = await _eval_run(db, tenant, dataset, run)
        failed = await _score_for_an_eval(db, tenant, dataset, case, run, eval_run_id)
        assert failed.judge is not None
        assert failed.judge["prompt_version"] == JUDGE_PROMPT_VERSION
        before = len(await _eval_runs(db, tenant))
        tenant.organization.ai_assistance_enabled = False
        await db.flush()

        with pytest.raises(AiAssistanceDisabledError):
            await scoring.rescore(tenant.ctx, dataset.id, RescoreRequest(score_ids=[failed.id]))

        tenant.organization.ai_assistance_enabled = True
        await db.flush()
        judge_agent = await agent_repo.get_system(
            db, organization_id=tenant.organization.id, key=JUDGE.key
        )
        assert judge_agent is not None
        await AgentRegistryService(db).publish(tenant.ctx, judge_agent.id, note="Stricter")

        with pytest.raises(BadRequestError, match="published anew"):
            await scoring.rescore(tenant.ctx, dataset.id, RescoreRequest(score_ids=[failed.id]))
        assert len(await _eval_runs(db, tenant)) == before

    async def test_an_eval_runs_score_kept_without_the_prompt_it_failed_on_is_refused(
        self, db, monkeypatch
    ) -> None:
        async def prose(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("It is fine.")])

        monkeypatch.setattr(ModelRequestSpec, "build", lambda self: FunctionModel(prose))
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        failed = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        kept = await case_score_repo.update(db, score=failed, update_data={"judge": None})
        results, before = kept.results, len(await _eval_runs(db, tenant))

        with pytest.raises(BadRequestError, match="asked differently"):
            await ScoringService(db).rescore(
                tenant.ctx, dataset.id, RescoreRequest(score_ids=[failed.id])
            )

        row = await case_score_repo.get(
            db, failed.id, organization_id=tenant.organization.id, dataset_id=dataset.id
        )
        assert row is not None
        assert (row.judge, row.results, row.passed) == (None, results, None)
        assert len(await _eval_runs(db, tenant)) == before

    async def test_an_eval_runs_score_is_graded_again_by_the_judge_that_failed_on_it(
        self, db, monkeypatch
    ) -> None:
        judging = Judge()
        answers = iter(["It is fine."])

        def model(self) -> FunctionModel:
            async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                text = next(answers, None)
                if text is not None:
                    return ModelResponse(parts=[TextPart(text)])
                return await judging.model().function(messages, info)  # type: ignore[misc]

            return FunctionModel(respond)

        monkeypatch.setattr(ModelRequestSpec, "build", model)
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        eval_run_id = await _eval_run(db, tenant, dataset, run)
        failed = await _score_for_an_eval(db, tenant, dataset, case, run, eval_run_id)

        result = await ScoringService(db).rescore(
            tenant.ctx, dataset.id, RescoreRequest(score_ids=[failed.id])
        )

        [again] = result.rescored
        assert (again.id, again.eval_run_id) == (failed.id, eval_run_id)
        assert (again.passed, again.unscored_reason) == (True, None)

    async def test_an_answer_graded_on_its_own_is_graded_by_the_judge_published_since(
        self, db, monkeypatch
    ) -> None:
        judging = Judge()
        answers = iter(["It is fine."])

        def model(self) -> FunctionModel:
            async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
                text = next(answers, None)
                if text is not None:
                    return ModelResponse(parts=[TextPart(text)])
                return await judging.model().function(messages, info)  # type: ignore[misc]

            return FunctionModel(respond)

        monkeypatch.setattr(ModelRequestSpec, "build", model)
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)
        failed = await scoring.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        judge_agent = await agent_repo.get_system(
            db, organization_id=tenant.organization.id, key=JUDGE.key
        )
        assert judge_agent is not None
        published = await AgentRegistryService(db).publish(
            tenant.ctx, judge_agent.id, note="Stricter"
        )

        result = await scoring.rescore(
            tenant.ctx, dataset.id, RescoreRequest(score_ids=[failed.id])
        )

        [again] = result.rescored
        assert (again.passed, again.unscored_reason) == (True, None)
        assert again.judge is not None
        assert again.judge.agent_version_id == published.id

    async def test_a_score_of_another_dataset_refuses_the_request(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring())

        with pytest.raises(NotFoundError) as refused:
            await ScoringService(db).rescore(
                tenant.ctx, dataset.id, RescoreRequest(score_ids=[uuid.uuid4()])
            )

        assert refused.value.details["missing"]

    async def test_a_viewer_cannot_grade_again(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring(), visibility="org")
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)

        with pytest.raises((NotFoundError, AuthorizationError)):
            await ScoringService(db).rescore(
                viewer, dataset.id, RescoreRequest(score_ids=[uuid.uuid4()])
            )


class TestVerdicts:
    async def test_a_person_s_verdict_decides_and_the_judge_s_opinion_stays(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(
            db, tenant, scoring=_rubric(review=ReviewScorer(select="failed"))
        )
        run = await _scored_run(db, tenant)
        judge.grades = {"r1": 1}
        service = ScoringService(db)
        scored = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        assert (scored.passed, scored.outcome, scored.review_state) == (False, False, "pending")

        decided = await service.set_verdict(
            tenant.ctx, dataset.id, scored.id, CaseVerdict(passed=True, note="Policy changed")
        )

        assert decided.outcome is True
        assert decided.passed is False
        assert decided.results == scored.results
        assert (decided.review_state, decided.human_note) == ("done", "Policy changed")
        assert decided.reviewed_by_user_id == tenant.owner.id

    async def test_withdrawing_a_verdict_puts_the_score_back_in_the_queue(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        scored = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        await service.set_verdict(tenant.ctx, dataset.id, scored.id, CaseVerdict(passed=False))

        withdrawn = await service.set_verdict(
            tenant.ctx, dataset.id, scored.id, CaseVerdict(passed=None, note="ignored")
        )

        assert (withdrawn.human_passed, withdrawn.human_note, withdrawn.review_state) == (
            None,
            None,
            "pending",
        )
        assert withdrawn.outcome is True

    async def test_a_score_can_be_sent_to_review_and_a_decided_one_stays_decided(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        scored = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        assert scored.review_state == "none"

        queued = await service.request_review(tenant.ctx, dataset.id, scored.id)
        await service.set_verdict(tenant.ctx, dataset.id, scored.id, CaseVerdict(passed=True))
        again = await service.request_review(tenant.ctx, dataset.id, scored.id)

        assert queued.review_state == "pending"
        assert again.review_state == "done"

    async def test_an_eval_run_s_score_waits_only_once_someone_sends_it(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(
            db, tenant, scoring=DatasetScoring(review=ReviewScorer(select="all"))
        )
        run = await _scored_run(db, tenant)
        eval_run_id = await _eval_run(db, tenant, dataset, run)
        service = ScoringService(db)
        score = await _score_for_an_eval(db, tenant, dataset, case, run, eval_run_id)
        assert (score.review_state, score.eval_run_id) == ("none", eval_run_id)

        sent = await service.request_reviews(
            tenant.ctx, dataset.id, ReviewRequest(score_ids=[score.id, score.id])
        )
        again = await service.request_reviews(
            tenant.ctx, dataset.id, ReviewRequest(score_ids=[score.id])
        )

        assert (sent.queued, sent.already) == (1, 0)
        assert (again.queued, again.already) == (0, 1)
        [waiting] = (await service.list_scores(tenant.ctx, dataset.id, pending=True)).items
        assert (waiting.id, waiting.eval_run_id) == (score.id, eval_run_id)

    async def test_an_eval_run_routes_one_score_per_case_and_never_twice(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        other, other_case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        eval_run_id = await _eval_run(db, tenant, dataset, run)
        service = ScoringService(db)
        first = await _score_for_an_eval(db, tenant, dataset, case, run, eval_run_id)
        second = await _score_for_an_eval(db, tenant, dataset, case, run, eval_run_id)
        elsewhere = await _score_for_an_eval(db, tenant, other, other_case, run, eval_run_id)

        routed = await service.route_to_review(
            tenant.ctx,
            dataset_id=dataset.id,
            score_ids=[first.id, second.id, elsewhere.id, uuid.uuid4()],
        )
        again = await service.route_to_review(
            tenant.ctx, dataset_id=dataset.id, score_ids=[second.id]
        )

        assert (routed.queued, routed.replaced, again.queued) == (1, 0, 0)
        waiting = (await service.list_scores(tenant.ctx, dataset.id, pending=True)).items
        assert [score.id for score in waiting] == [first.id]
        assert (await service.list_scores(tenant.ctx, other.id, pending=True)).total == 0

    async def test_a_newer_score_of_a_case_replaces_the_one_waiting_and_not_a_decided_one(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        decided = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        waiting = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        newer = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        now = datetime.now(UTC)
        for score, age in ((decided, 3), (waiting, 2)):
            await case_score_repo.update(
                db, score=score, update_data={"created_at": now - timedelta(days=age)}
            )
        await service.route_to_review(tenant.ctx, dataset_id=dataset.id, score_ids=[decided.id])
        await service.set_verdict(tenant.ctx, dataset.id, decided.id, CaseVerdict(passed=False))
        await service.route_to_review(tenant.ctx, dataset_id=dataset.id, score_ids=[waiting.id])

        routed = await service.route_to_review(
            tenant.ctx, dataset_id=dataset.id, score_ids=[newer.id]
        )

        assert (routed.queued, routed.replaced, routed.already) == (1, 1, 0)
        states = {
            score.id: (score.review_state, score.human_passed)
            for score in (await service.list_scores(tenant.ctx, dataset.id)).items
        }
        assert states == {
            decided.id: ("done", False),
            waiting.id: ("none", None),
            newer.id: ("pending", None),
        }

    async def test_a_judge_error_never_takes_the_place_of_a_regression_waiting(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        regression = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        await case_score_repo.update(
            db,
            score=regression,
            update_data={"passed": False, "created_at": datetime.now(UTC) - timedelta(days=1)},
        )
        await service.route_to_review(tenant.ctx, dataset_id=dataset.id, score_ids=[regression.id])
        ungraded = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        await case_score_repo.update(db, score=ungraded, update_data={"passed": None})
        older_error = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        await case_score_repo.update(
            db,
            score=older_error,
            update_data={"passed": None, "created_at": datetime.now(UTC) - timedelta(days=2)},
        )

        routed = await service.route_to_review(
            tenant.ctx, dataset_id=dataset.id, score_ids=[ungraded.id]
        )
        sent = await service.request_reviews(
            tenant.ctx, dataset.id, ReviewRequest(score_ids=[ungraded.id, older_error.id])
        )

        assert (routed.queued, routed.replaced, routed.already) == (0, 0, 1)
        assert (sent.queued, sent.replaced, sent.already) == (0, 0, 2)
        waiting = (await service.list_scores(tenant.ctx, dataset.id, pending=True)).items
        assert [score.id for score in waiting] == [regression.id]

    async def test_a_regression_takes_the_place_of_a_judge_error_waiting(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        error = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        await case_score_repo.update(db, score=error, update_data={"passed": None})
        await service.route_to_review(tenant.ctx, dataset_id=dataset.id, score_ids=[error.id])
        regression = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        another_error = await _score_for_an_eval(
            db, tenant, dataset, case, run, await _eval_run(db, tenant, dataset, run)
        )
        await case_score_repo.update(db, score=regression, update_data={"passed": False})
        await case_score_repo.update(db, score=another_error, update_data={"passed": None})

        routed = await service.route_to_review(
            tenant.ctx, dataset_id=dataset.id, score_ids=[another_error.id, regression.id]
        )

        assert (routed.queued, routed.replaced, routed.already) == (1, 1, 1)
        waiting = (await service.list_scores(tenant.ctx, dataset.id, pending=True)).items
        assert [score.id for score in waiting] == [regression.id]

    async def test_two_sends_of_one_case_at_once_leave_one_score_waiting(
        self, db, engine, judge
    ) -> None:
        """Each send reads which of the case's scores waits before it queues; racing,
        both read none and both queued, until the case is locked for the read."""
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        older = await _score_for_an_eval(db, tenant, dataset, case, run, uuid.uuid4())
        newer = await _score_for_an_eval(db, tenant, dataset, case, run, uuid.uuid4())
        await case_score_repo.update(
            db, score=older, update_data={"created_at": datetime.now(UTC) - timedelta(days=1)}
        )
        await db.commit()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        first_sent = asyncio.Event()

        async def send(score_id: uuid.UUID, *, first: bool) -> None:
            async with factory() as session:
                if not first:
                    await first_sent.wait()
                await ScoringService(session).route_to_review(
                    tenant.ctx, dataset_id=dataset.id, score_ids=[score_id]
                )
                if first:
                    first_sent.set()
                    await asyncio.sleep(0.3)
                await session.commit()

        await asyncio.gather(send(older.id, first=True), send(newer.id, first=False))

        async with factory() as fresh:
            waiting = await case_score_repo.waiting_for_cases(
                fresh, [case.case_id], organization_id=tenant.organization.id, dataset_id=dataset.id
            )
        assert [score.id for score in waiting] == [newer.id]

    async def test_an_older_score_sent_by_hand_leaves_the_newer_one_waiting(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        older = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        twin = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        newer = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        row = await case_score_repo.get(
            db, older.id, organization_id=tenant.organization.id, dataset_id=dataset.id
        )
        assert row is not None
        await case_score_repo.update(
            db, score=row, update_data={"created_at": datetime.now(UTC) - timedelta(days=1)}
        )
        await service.request_review(tenant.ctx, dataset.id, newer.id)

        alone = await service.request_review(tenant.ctx, dataset.id, older.id)
        sent = await service.request_reviews(
            tenant.ctx, dataset.id, ReviewRequest(score_ids=[older.id, twin.id])
        )

        assert alone.review_state == "none"
        assert (sent.queued, sent.replaced, sent.already) == (0, 0, 2)
        waiting = (await service.list_scores(tenant.ctx, dataset.id, pending=True)).items
        assert [score.id for score in waiting] == [newer.id]

    @pytest.mark.security
    async def test_a_reader_who_may_not_view_the_agent_reads_the_outcome_not_the_answer(
        self, db, judge
    ) -> None:
        """A dataset shared with somebody does not share the answers of an agent
        they may not see - nor the reasons and quotes that repeat them."""
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring(), visibility="org")
        run = await _scored_run(db, tenant, answer='{"days": 30} as the private policy says')
        service = ScoringService(db)
        await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        agent = await db.get(Agent, run.agent_id)
        assert agent is not None
        agent.visibility = "private"
        await db.flush()
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)

        [owned] = (await service.list_scores(tenant.ctx, dataset.id)).items
        [hidden] = (await service.list_scores(viewer, dataset.id)).items
        db.add(
            ResourceGrant(
                organization_id=tenant.organization.id,
                resource_type="agent",
                resource_id=agent.id,
                subject_user_id=viewer.user_id,
                level=GrantLevel.READ.value,
                created_by_user_id=tenant.owner.id,
            )
        )
        await db.flush()
        [granted] = (await service.list_scores(viewer, dataset.id)).items

        assert owned.answer is not None and not owned.answer_hidden
        assert any(result.reason for result in owned.results)
        assert (hidden.answer, hidden.answer_hidden) == (None, True)
        assert all(
            (result.reason, result.unverified_quotes, result.judge_said) == ("", [], None)
            for result in hidden.results
        )
        assert [r.status for r in hidden.results] == [r.status for r in owned.results]
        assert (hidden.outcome, hidden.question) == (owned.outcome, owned.question)
        assert (granted.answer, granted.answer_hidden) == (owned.answer, False)

    @pytest.mark.security
    async def test_an_answer_whose_run_is_gone_is_read_only_by_who_sees_every_agent(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring(), visibility="org")
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        score = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        row = await case_score_repo.get(
            db, score.id, organization_id=tenant.organization.id, dataset_id=dataset.id
        )
        assert row is not None
        await case_score_repo.update(db, score=row, update_data={"run_id": None})
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)

        [owned] = (await service.list_scores(tenant.ctx, dataset.id)).items
        [hidden] = (await service.list_scores(viewer, dataset.id)).items

        assert (owned.answer is not None, owned.answer_hidden) == (True, False)
        assert (hidden.answer, hidden.answer_hidden) == (None, True)

    async def test_a_score_keeps_the_answer_it_graded_and_who_gave_it(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        secret = "ghp_" + "a1B2" * 9
        run = await _scored_run(db, tenant, answer=f'{{"days": 30}} {secret} ' + "x" * 9_000)

        scored = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        assert scored.answer is not None
        assert scored.answer.startswith('{"days": 30} [redacted:github_token]')
        assert scored.answer.endswith("x…")
        assert secret not in scored.answer
        assert scored.agent_id == run.agent_id
        assert scored.agent_name is not None and scored.agent_name.startswith("Support ")
        assert (scored.order_mode, [call.tool for call in scored.expected_tool_calls]) == (
            "in_order",
            ["search_kb", "lookup_order"],
        )
        assert [check.type for check in scored.checks] == ["json_schema"]

    async def test_scores_come_out_of_the_queue_undecided_and_a_decision_stays(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(
            db, tenant, scoring=DatasetScoring(review=ReviewScorer(select="all"))
        )
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        waiting = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        decided = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        await service.set_verdict(tenant.ctx, dataset.id, decided.id, CaseVerdict(passed=False))

        taken = await service.withdraw_reviews(
            tenant.ctx, dataset.id, ReviewRequest(score_ids=[waiting.id, decided.id])
        )

        assert (taken.removed, taken.kept) == (1, 1)
        states = {
            item.id: (item.review_state, item.human_passed)
            for item in (await service.list_scores(tenant.ctx, dataset.id)).items
        }
        assert states == {waiting.id: ("none", None), decided.id: ("done", False)}

    async def test_scores_narrow_by_outcome_agent_eval_run_and_tag(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(
            db,
            tenant,
            scoring=DatasetScoring(
                checks=ChecksScorer(defaults=[{"type": "contains", "value": "ninety"}])
            ),
        )
        mine = await _scored_run(db, tenant)
        other = await _scored_run(db, tenant)
        eval_run_id = await _eval_run(db, tenant, dataset, mine)
        service = ScoringService(db)
        failed = await _score_for_an_eval(db, tenant, dataset, case, mine, eval_run_id)
        overruled = await _score_for_an_eval(db, tenant, dataset, case, other, None)
        await service.set_verdict(tenant.ctx, dataset.id, overruled.id, CaseVerdict(passed=True))

        async def ids(**filters) -> set[uuid.UUID]:
            listed = await service.list_scores(tenant.ctx, dataset.id, **filters)
            return {item.id for item in listed.items}

        assert await ids(outcome="failed") == {failed.id}
        assert await ids(outcome="passed") == {overruled.id}
        assert await ids(outcome="not_graded") == set()
        assert await ids(agent_id=mine.agent_id) == {failed.id}
        assert await ids(eval_run_id=eval_run_id) == {failed.id}
        assert await ids(tag="none-of-these") == set()

    async def test_scores_narrow_to_a_tag_of_the_scored_case(self, db, judge) -> None:
        tenant = await _tenant(db)
        datasets = DatasetService(db)
        dataset = await datasets.create(tenant.ctx, DatasetCreate(name="tagged"))
        tagged = await datasets.add_case(
            tenant.ctx,
            dataset.id,
            DatasetCaseCreate(
                input="q",
                reference_answer="a",
                checks=[{"type": "contains", "value": "a"}],
                tags=["billing"],
            ),
        )
        plain = await datasets.add_case(
            tenant.ctx,
            dataset.id,
            DatasetCaseCreate(
                input="r", reference_answer="b", checks=[{"type": "contains", "value": "b"}]
            ),
        )
        run = await _scored_run(db, tenant)
        on_tagged = await _score_for_an_eval(db, tenant, dataset, tagged, run, None)
        await _score_for_an_eval(db, tenant, dataset, plain, run, None)

        listed = await ScoringService(db).list_scores(tenant.ctx, dataset.id, tag="billing")

        assert [(item.id, item.case_tags) for item in listed.items] == [(on_tagged.id, ["billing"])]

    async def test_the_queue_and_the_listing_show_what_waits(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(
            db,
            tenant,
            scoring=DatasetScoring(
                checks=ChecksScorer(defaults=[{"type": "contains", "value": "ninety"}]),
                review=ReviewScorer(select="failed"),
            ),
        )
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        scored = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        everything, other = await _dataset(
            db, tenant, scoring=DatasetScoring(review=ReviewScorer(select="all"))
        )
        for _ in range(2):
            await service.score_run(
                tenant.ctx, everything.id, other.case_id, CaseScoreCreate(run_id=run.id)
            )

        queue = await service.review_queue(tenant.ctx, limit=1)
        pending = await service.list_scores(tenant.ctx, dataset.id, pending=True)
        for_case = await service.list_scores(tenant.ctx, dataset.id, case_id=case.case_id)

        names = {dataset.id: dataset.name, everything.id: everything.name}
        [oldest] = queue.items
        assert oldest.dataset_name == names[oldest.dataset_id]
        assert queue.total == 3
        assert [(d.dataset_id, d.failed, d.unscored, d.passed) for d in queue.datasets] == [
            (everything.id, 0, 0, 2),
            (dataset.id, 1, 0, 0),
        ]
        assert [item.id for item in pending.items] == [scored.id]
        assert for_case.total == 1


@pytest.mark.security
class TestRefusals:
    async def test_another_organization_s_dataset_is_not_found(self, db, judge) -> None:
        mine, theirs = await _tenant(db), await _tenant(db)
        dataset, case = await _dataset(db, theirs, scoring=DatasetScoring())
        run = await _scored_run(db, mine)

        with pytest.raises(NotFoundError):
            await ScoringService(db).score_run(
                mine.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
            )

    async def test_another_organization_s_run_is_not_found(self, db, judge) -> None:
        mine, theirs = await _tenant(db), await _tenant(db)
        dataset, case = await _dataset(db, mine, scoring=DatasetScoring())
        run = await _scored_run(db, theirs)

        with pytest.raises(NotFoundError):
            await ScoringService(db).score_run(
                mine.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
            )

    async def test_a_private_dataset_is_out_of_reach_without_a_grant(self, db, judge) -> None:
        """Running reaches what is shared with a member; configuring, only what a
        builder owns or was handed - the role alone opens neither."""
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        member = await _join(db, tenant, OrgRoleName.MEMBER)
        builder = await _join(db, tenant, OrgRoleName.BUILDER)
        service = ScoringService(db)

        with pytest.raises(NotFoundError):
            await service.score_run(
                member, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
            )
        with pytest.raises(NotFoundError):
            await service.set_scoring(builder, dataset.id, DatasetScoring())

    async def test_a_viewer_reads_scores_but_cannot_score_or_decide(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring(), visibility="org")
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        scored = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)

        assert (await service.list_scores(viewer, dataset.id)).total == 1
        with pytest.raises(NotFoundError):
            await service.score_run(
                viewer, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
            )
        with pytest.raises(NotFoundError):
            await service.set_verdict(viewer, dataset.id, scored.id, CaseVerdict(passed=True))

    async def test_scoring_needs_runs_view_as_well(self, db, judge) -> None:
        """A member may run evals on a shared dataset but not read others' runs."""
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring(), visibility="org")
        run = await _scored_run(db, tenant)
        member = await _join(db, tenant, OrgRoleName.MEMBER)

        with pytest.raises(AuthorizationError):
            await ScoringService(db).score_run(
                member, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
            )

    async def test_a_model_named_for_the_judge_is_accepted_and_dropped(self, db, judge) -> None:
        mine, theirs = await _tenant(db), await _tenant(db)
        foreign = await _model(db, theirs)
        dataset, _ = await _dataset(db, mine, scoring=DatasetScoring())

        saved = await ScoringService(db).set_scoring(
            mine.ctx,
            dataset.id,
            DatasetScoring.model_validate(
                {
                    "judge": {
                        "enabled": True,
                        "criteria": [c.model_dump() for c in RUBRIC],
                        "model_profile_id": str(foreign.id),
                    }
                }
            ),
        )

        assert saved.scoring.judge.model_profile_id is None
        row = await dataset_repo.get(db, dataset.id, organization_id=mine.organization.id)
        assert row is not None and row.scoring["judge"]["model_profile_id"] is None

    @pytest.mark.parametrize(
        ("scoring", "field"),
        [
            (
                DatasetScoring(
                    checks=ChecksScorer(enabled=False), trajectory=TrajectoryScorer(enabled=False)
                ),
                "checks.enabled",
            ),
            (DatasetScoring(judge=JudgeScorer(enabled=True)), "judge.criteria"),
        ],
    )
    async def test_a_scoring_that_can_score_nothing_is_refused(
        self, db, judge, scoring, field
    ) -> None:
        tenant = await _tenant(db)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring())

        with pytest.raises(BadRequestError) as refused:
            await ScoringService(db).set_scoring(tenant.ctx, dataset.id, scoring)

        assert [problem["field"] for problem in refused.value.details["fields"]] == [field]

    @pytest.mark.parametrize(
        ("scoring", "field"),
        [
            (DatasetScoring(judge=JudgeScorer(enabled=True, criteria=RUBRIC)), "judge.enabled"),
            (DatasetScoring(reference=ReferenceScorer(enabled=True)), "reference.enabled"),
        ],
    )
    async def test_the_judge_cannot_be_turned_on_while_ai_assistance_is_off(
        self, db, judge, scoring, field
    ) -> None:
        tenant = await _tenant(db)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring())
        tenant.organization.ai_assistance_enabled = False
        await db.flush()

        with pytest.raises(BadRequestError) as refused:
            await ScoringService(db).set_scoring(tenant.ctx, dataset.id, scoring)

        assert [problem["field"] for problem in refused.value.details["fields"]] == [field]
        assert "AI assistance is off" in refused.value.message

    async def test_a_judge_already_on_stays_while_the_rules_change_with_ai_off(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, _ = await _dataset(db, tenant, scoring=_rubric())
        tenant.organization.ai_assistance_enabled = False
        await db.flush()

        saved = await ScoringService(db).set_scoring(
            tenant.ctx, dataset.id, _rubric(trajectory=TrajectoryScorer(enabled=False))
        )

        assert (saved.scoring.judge.enabled, saved.scoring.trajectory.enabled) == (True, False)

    async def test_a_case_the_scorers_have_nothing_to_check_on_keeps_no_score(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring())
        bare = await DatasetService(db).add_case(
            tenant.ctx, dataset.id, DatasetCaseCreate(input="Hi?", reference_answer="Hello.")
        )
        run = await _scored_run(db, tenant)
        scoring = ScoringService(db)

        with pytest.raises(NothingToScoreError):
            await scoring.score_run(
                tenant.ctx, dataset.id, bare.case_id, CaseScoreCreate(run_id=run.id)
            )

        assert (await scoring.list_scores(tenant.ctx, dataset.id)).total == 0
        assert judge.calls == 0

    async def test_a_viewer_cannot_take_scores_out_of_the_queue(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(
            db,
            tenant,
            scoring=DatasetScoring(review=ReviewScorer(select="all")),
            visibility="org",
        )
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        waiting = await service.score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        viewer = await _join(db, tenant, OrgRoleName.VIEWER)

        with pytest.raises(NotFoundError):
            await service.withdraw_reviews(
                viewer, dataset.id, ReviewRequest(score_ids=[waiting.id])
            )

        assert (await service.list_scores(tenant.ctx, dataset.id, pending=True)).total == 1

    async def test_a_review_request_naming_another_dataset_s_score_changes_nothing(
        self, db, judge
    ) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(db, tenant, scoring=DatasetScoring())
        other, other_case = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        mine = await _score_for_an_eval(db, tenant, dataset, case, run, None)
        theirs = await _score_for_an_eval(db, tenant, other, other_case, run, None)
        service = ScoringService(db)

        with pytest.raises(NotFoundError) as refused:
            await service.request_reviews(
                tenant.ctx, dataset.id, ReviewRequest(score_ids=[mine.id, theirs.id])
            )

        assert refused.value.details["missing"] == [theirs.id]
        assert (await service.list_scores(tenant.ctx, dataset.id, pending=True)).total == 0

    async def test_a_score_from_another_dataset_is_not_found(self, db, judge) -> None:
        tenant = await _tenant(db)
        first, case = await _dataset(db, tenant, scoring=DatasetScoring())
        second, _ = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        service = ScoringService(db)
        scored = await service.score_run(
            tenant.ctx, first.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        with pytest.raises(NotFoundError):
            await service.set_verdict(tenant.ctx, second.id, scored.id, CaseVerdict(passed=True))

    async def test_the_queue_leaves_out_datasets_the_caller_cannot_see(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, case = await _dataset(
            db, tenant, scoring=DatasetScoring(review=ReviewScorer(select="all"))
        )
        run = await _scored_run(db, tenant)
        await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )
        member = await _join(db, tenant, OrgRoleName.MEMBER)

        hidden = await ScoringService(db).review_queue(member)
        assert (hidden.total, hidden.datasets) == (0, [])
        assert (await ScoringService(db).review_queue(tenant.ctx)).total == 1

    async def test_a_case_the_version_does_not_hold_is_not_found(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset, _ = await _dataset(db, tenant, scoring=DatasetScoring())
        run = await _scored_run(db, tenant)
        service = ScoringService(db)

        with pytest.raises(NotFoundError, match="holds no such case"):
            await service.score_run(
                tenant.ctx, dataset.id, uuid.uuid4(), CaseScoreCreate(run_id=run.id)
            )
        with pytest.raises(NotFoundError):
            await service.score_run(
                tenant.ctx, dataset.id, uuid.uuid4(), CaseScoreCreate(run_id=run.id, version=9)
            )

    async def test_a_dataset_with_no_version_yet_holds_no_case(self, db, judge) -> None:
        tenant = await _tenant(db)
        dataset = await DatasetService(db).create(tenant.ctx, DatasetCreate(name="Empty"))
        run = await _scored_run(db, tenant)

        with pytest.raises(NotFoundError, match="holds no such case"):
            await ScoringService(db).score_run(
                tenant.ctx, dataset.id, uuid.uuid4(), CaseScoreCreate(run_id=run.id)
            )
