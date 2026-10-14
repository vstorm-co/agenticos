"""Scoring a recorded run against a dataset case, against a real database.

The judge runs for real: the seeded eval judge, through the runner's own
`execute`, with only the model replaced. So what is asserted about its budget,
its run row and its surface is what the platform does, not what a stub was told.
"""

from __future__ import annotations

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

from app.agents.model_resolver import ModelRequestSpec
from app.agents.spec import AgentSpec
from app.agents.system_agents import JUDGE
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    NothingToScoreError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.agent import AgentStatus
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.credential import ModelProfile
from app.db.models.intercepted_tool_call import (
    InterceptedToolCall,
    InterceptionOutcome,
    InterceptionReason,
)
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.user import User
from app.repositories import (
    agent_repo,
    agent_run_repo,
    conversation_repo,
    dataset_repo,
    intercepted_tool_call_repo,
)
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate, ExpectedToolCall
from app.schemas.scoring import (
    CaseScoreCreate,
    CaseVerdict,
    ChecksScorer,
    DatasetScoring,
    JudgeScorer,
    ReferenceScorer,
    ReviewScorer,
    RubricCriterion,
    TrajectoryScorer,
)
from app.services.agent_registry import AgentRegistryService
from app.services.dataset import DatasetService
from app.services.scoring import ScoringService
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


async def _dataset(db, tenant: Tenant, *, scoring: DatasetScoring, visibility: str = "private"):
    datasets = DatasetService(db)
    dataset = await datasets.create(
        tenant.ctx, DatasetCreate(name=f"Refunds {uuid.uuid4().hex[:6]}")
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
    if visibility != "private":
        row = await dataset_repo.get(db, dataset.id, organization_id=tenant.organization.id)
        await dataset_repo.update(db, dataset=row, update_data={"visibility": visibility})
    return dataset, case


def _rubric(**overrides) -> DatasetScoring:
    return DatasetScoring(judge=JudgeScorer(enabled=True, criteria=RUBRIC), **overrides)


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
        assert again.judge == first.judge
        assert narrower.judge.rubric_hash != first.judge.rubric_hash

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

        reasons = {r.reason for r in score.results if r.scorer == "judge"}
        assert reasons == {'5/5: Looks right [not in the answer, unverified: "ninety days"]'}
        assert score.passed is True

    @pytest.mark.security
    async def test_a_secret_the_judge_quotes_is_not_kept(self, db, judge) -> None:
        tenant = await _tenant(db)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)
        judge.reason = "It leaked ghp_" + "a1B2" * 9

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        reasons = [r.reason for r in score.results if r.scorer == "judge"]
        assert all("[redacted:github_token]" in reason for reason in reasons)
        assert not any("ghp_" in reason for reason in reasons)

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
        assert score.judge is None
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
        tenant = await _tenant(db)
        await SystemAgentService(db).ensure(organization_id=tenant.organization.id, key=JUDGE.key)
        await _model(db, tenant)
        dataset, case = await _dataset(db, tenant, scoring=_rubric())
        run = await _scored_run(db, tenant)

        score = await ScoringService(db).score_run(
            tenant.ctx, dataset.id, case.case_id, CaseScoreCreate(run_id=run.id)
        )

        judged = [r for r in score.results if r.scorer == "judge"]
        assert {r.reason_code for r in judged} == {"judge_unpublished"}

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
            return ModelResponse(parts=[TextPart("It is fine.")])

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
        assert score.passed is False


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

    async def test_a_judge_model_from_another_organization_is_refused(self, db, judge) -> None:
        mine, theirs = await _tenant(db), await _tenant(db)
        foreign = await _model(db, theirs)
        dataset, _ = await _dataset(db, mine, scoring=DatasetScoring())

        with pytest.raises(BadRequestError, match="no such model"):
            await ScoringService(db).set_scoring(
                mine.ctx,
                dataset.id,
                DatasetScoring(
                    judge=JudgeScorer(enabled=True, criteria=RUBRIC, model_profile_id=foreign.id)
                ),
            )

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
