"""Native database proof for owner capture, draft authority, and ordinary skill decisions."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.audience import RunAudience
from app.agents.capabilities.skills._log import ServedSkill, SkillUseLog
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec
from app.core.browser_procedure_teaching import (
    BrowserProcedureTeachingGeneration,
    BrowserProcedureTeachingObservation,
    BrowserProcedureTeachingParameter,
    BrowserProcedureTeachingReason,
    BrowserProcedureTeachingRefused,
    BrowserProcedureTeachingReviewedAction,
    BrowserProcedureTeachingState,
)
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun, RunStatus, RunSurface
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.browser_procedure_teaching import BrowserProcedureTeachingPolicy
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.skill import Skill
from app.db.models.skill_proposal import SkillProposal
from app.db.models.skill_version import SkillVersion
from app.db.models.user import User
from app.repositories import browser_procedure_teaching as repo
from app.repositories import skill_proposal as proposal_repo
from app.schemas.browser_procedure_teaching import (
    BrowserProcedureTeachingChange,
    BrowserProcedureTeachingPolicyWrite,
    BrowserProcedureTeachingPropose,
    BrowserProcedureTeachingStart,
)
from app.schemas.resource_usage import ProposalDecision
from app.services.browser_procedure_teaching import _discovery, _generation, _maintenance, _service
from app.services.browser_procedure_teaching._lease import (
    BrowserProcedureTeachingLease,
    BrowserProcedureTeachingTakeover,
    close_connection,
)
from app.services.browser_procedure_teaching._policy import BrowserProcedureTeachingPolicyService
from app.services.browser_procedure_teaching._service import BrowserProcedureTeachingService
from app.services.skill_proposal import SkillProposalService
from tests.integration.test_personal_coding_accounts import context, organization, person
from tests.test_browser_procedure_teaching_contracts import ORIGIN, SECRET, TARGET, review
from tests.test_browser_procedure_teaching_native import Redis, connect

pytestmark = [pytest.mark.anyio, pytest.mark.security]
ENDPOINT = "http://provisioned-browser:9222"


@dataclass
class BrowserProcedureTeachingFixture:
    db: AsyncSession
    owner: User
    org: Organization
    ctx: AuthContext
    agent: Agent
    version: AgentVersion
    run: AgentRun
    held: BrowserProcedureTeachingTakeover
    redis: Redis
    lease: BrowserProcedureTeachingLease
    service: BrowserProcedureTeachingService

    def request(self, **changes):
        return BrowserProcedureTeachingStart(
            request_id=uuid4(),
            run_id=self.run.id,
            call_id=self.held.call_id,
            tab_id=self.held.tab_id,
            takeover_id=self.held.takeover_id,
            title="Synthetic procedure",
            allowed_origins=(ORIGIN,),
        ).model_copy(update=changes)

    async def start(self):
        return await self.service.start(self.ctx, self.request())

    async def append(self, **changes):
        args = {
            "input_id": uuid4(),
            "action": "input_parameter",
            "observation": BrowserProcedureTeachingObservation(origin=ORIGIN, target=TARGET),
        }
        args.update(changes)
        return await self.service.append(self.ctx, self.held, **args)

    async def reviewed(self):
        started = await self.start()
        await self.append()
        stopped = await self.service.stop(self.ctx, started.id)
        chosen = review(
            BrowserProcedureTeachingReviewedAction(
                sequence=1, label="Search for the requested record", parameter="record"
            ),
            parameters=(
                BrowserProcedureTeachingParameter(
                    name="record", description="The requested record"
                ),
            ),
        )
        return await self.service.change(
            self.ctx,
            stopped.id,
            stopped.revision,
            BrowserProcedureTeachingChange(action="review", review=chosen),
        )

    def deps(self):
        return AgentDeps(
            organization_id=self.org.id,
            user_id=str(self.owner.id),
            agent_id=self.agent.id,
            run_id=self.run.id,
            run_person=self.owner.id,
            audience=RunAudience(user_id=self.owner.id, browses_signed_in=True),
        )


@pytest.fixture
async def teaching(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[BrowserProcedureTeachingFixture]:
    owner = await person(db)
    org = await organization(db, owner)
    ctx = context(owner, org)
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", ENDPOINT)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ORGANIZATION_IDS", [org.id])
    spec = AgentSpec.model_validate(
        {
            "name": "Synthetic teacher",
            "capabilities": [
                {
                    "id": "browser_use",
                    "config": {
                        "connection": "built_in",
                        "cdp_url": ENDPOINT,
                        "allow_teaching": True,
                        "learn_site_procedures": True,
                    },
                }
            ],
        }
    ).model_dump(mode="json")
    agent = Agent(
        organization_id=org.id,
        owner_user_id=owner.id,
        name="Synthetic teacher",
        slug=uuid4().hex,
        draft_spec=spec,
    )
    chat = Conversation(organization_id=org.id, user_id=owner.id, title="Private teaching")
    db.add_all(
        [
            agent,
            chat,
            BrowserProcedureTeachingPolicy(
                organization_id=org.id, enabled=True, generation=uuid4()
            ),
        ]
    )
    await db.flush()
    version = AgentVersion(organization_id=org.id, agent_id=agent.id, version=1, spec=spec)
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    run = AgentRun(
        organization_id=org.id,
        user_id=owner.id,
        agent_id=agent.id,
        agent_version_id=version.id,
        conversation_id=chat.id,
        status=RunStatus.RUNNING.value,
        surface=RunSurface.WEB.value,
    )
    db.add(run)
    await db.flush()
    held = BrowserProcedureTeachingTakeover(
        organization_id=org.id,
        run_id=run.id,
        agent_id=agent.id,
        user_id=owner.id,
        controller_id=uuid4(),
        tab_id="main",
        call_id="teaching-call",
        connection_id=uuid4(),
        takeover_id=uuid4(),
    )
    redis = Redis()
    assert await connect(redis, held)
    lease = BrowserProcedureTeachingLease(redis, held)
    await lease.acquire()
    fixture = BrowserProcedureTeachingFixture(
        db,
        owner,
        org,
        ctx,
        agent,
        version,
        run,
        held,
        redis,
        lease,
        BrowserProcedureTeachingService(db, redis),
    )
    try:
        yield fixture
    finally:
        await fixture.lease.close()


async def test_start_is_owner_idempotent_and_input_events_contain_no_values(teaching):
    t = teaching
    request = t.request()
    first = await t.service.start(t.ctx, request)
    assert await t.service.start(t.ctx, request) == first
    with pytest.raises(NotFoundError):
        await t.service.start(t.ctx, request.model_copy(update={"title": "Different intent"}))
    with pytest.raises(ConflictError):
        await t.start()
    input_id = uuid4()
    added = await t.append(input_id=input_id)
    assert added.events[0].sequence == 1 and added.events[0].target == TARGET
    assert await t.append(input_id=input_id) == added
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await t.append(input_id=input_id, action="click")
    assert caught.value.reason == BrowserProcedureTeachingReason.EVENT_CONFLICT
    row = await repo.session(t.db, t.org.id, first.id)
    assert len(row.sanitized_events) == 1
    assert "value" not in str(row.sanitized_events) and SECRET not in str(row.sanitized_events)
    audit = await t.db.scalar(
        select(AppAdminAuditLog).where(
            AppAdminAuditLog.action == "browser_procedure_teaching.started"
        )
    )
    assert audit is not None and SECRET not in str(audit.details)


@pytest.mark.parametrize(
    "field",
    [
        "organization_id",
        "run_id",
        "agent_id",
        "user_id",
        "controller_id",
        "connection_id",
        "takeover_id",
        "tab_id",
        "call_id",
    ],
)
async def test_events_from_any_other_live_identity_never_append(teaching, field):
    t = teaching
    first = await t.start()
    held = t.held.model_copy(update={field: "other" if field in {"tab_id", "call_id"} else uuid4()})
    assert (
        await t.service.append(
            t.ctx,
            held,
            input_id=uuid4(),
            action="input_parameter",
            observation=BrowserProcedureTeachingObservation(origin=ORIGIN, target=TARGET),
        )
        is None
    )
    assert not (await t.service.get(t.ctx, first.id)).events


async def test_members_and_other_tenants_cannot_read_or_change_a_persons_session(teaching):
    t = teaching
    first = await t.start()
    other = await person(t.db)
    t.db.add(OrganizationMember(organization_id=t.org.id, user_id=other.id, role="admin"))
    await t.db.flush()
    foreign = await organization(t.db, other)
    for ctx in (context(other, t.org), context(other, foreign)):
        with pytest.raises(NotFoundError):
            await t.service.get(ctx, first.id)
        with pytest.raises(NotFoundError):
            await t.service.discard(ctx, first.id)


async def test_disconnect_refuses_capture_and_resume_requires_a_new_live_takeover(teaching):
    t = teaching
    first = await t.start()
    await close_connection(
        t.redis, str(t.run.id), t.held.call_id, t.held.connection_id, str(t.owner.id)
    )
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await t.append()
    assert caught.value.reason == BrowserProcedureTeachingReason.OWNERSHIP_LOST
    paused = await t.service.change(
        t.ctx, first.id, first.revision, BrowserProcedureTeachingChange(action="pause")
    )
    with pytest.raises(BrowserProcedureTeachingRefused):
        await t.service.change(
            t.ctx,
            first.id,
            paused.revision,
            BrowserProcedureTeachingChange(action="resume", takeover_id=t.held.takeover_id),
        )
    await t.lease.close()
    old = t.held
    t.held = t.held.model_copy(update={"connection_id": uuid4(), "takeover_id": uuid4()})
    assert await connect(t.redis, t.held)
    t.lease = BrowserProcedureTeachingLease(t.redis, t.held)
    await t.lease.acquire()
    resumed = await t.service.change(
        t.ctx,
        first.id,
        paused.revision,
        BrowserProcedureTeachingChange(action="resume", takeover_id=t.held.takeover_id),
    )
    assert resumed.status == BrowserProcedureTeachingState.RECORDING
    assert (
        await t.service.append(
            t.ctx,
            old,
            input_id=uuid4(),
            action="input_parameter",
            observation=BrowserProcedureTeachingObservation(origin=ORIGIN, target=TARGET),
        )
        is None
    )
    assert len((await t.append()).events) == 1


async def test_authentication_is_a_human_checkpoint_and_pauses_capture(teaching):
    t = teaching
    await t.start()
    result = await t.append(
        observation=BrowserProcedureTeachingObservation(origin=ORIGIN, human_required=True)
    )
    assert result.status == BrowserProcedureTeachingState.PAUSED
    assert result.reason_code == BrowserProcedureTeachingReason.AUTHENTICATION
    assert result.events[0].action == "checkpoint" and result.events[0].target is None
    assert await t.append() == result


@pytest.mark.parametrize("bound", ["origin", "events", "bytes", "capture_time", "retention"])
async def test_capture_limits_stop_or_erase_without_truncating_retained_steps(
    teaching, monkeypatch, bound
):
    t = teaching
    first = await t.start()
    row = await repo.session(t.db, t.org.id, first.id)
    expected = BrowserProcedureTeachingReason.ORIGIN_REFUSED
    changes = {}
    if bound == "origin":
        changes["observation"] = BrowserProcedureTeachingObservation(
            origin="https://other.example.test", target=TARGET
        )
    elif bound == "events":
        monkeypatch.setattr(_service, "MAX_EVENTS", 0)
        expected = BrowserProcedureTeachingReason.EVENT_LIMIT
    elif bound == "bytes":
        monkeypatch.setattr(_service, "MAX_EVENT_BYTES", 1)
        expected = BrowserProcedureTeachingReason.BYTE_LIMIT
    elif bound == "capture_time":
        row.capture_ends_at = datetime.now(UTC) - timedelta(seconds=1)
        expected = BrowserProcedureTeachingReason.TIME_LIMIT
    else:
        await t.append()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        expected = BrowserProcedureTeachingReason.EXPIRED
    await t.db.flush()
    result = await t.append(**changes)
    assert result.reason_code == expected and not result.events
    assert result.status == (
        BrowserProcedureTeachingState.EXPIRED
        if bound == "retention"
        else BrowserProcedureTeachingState.PAUSED
    )


async def test_current_policy_generation_wins_and_stopped_manual_review_survives_run_completion(
    teaching,
):
    t = teaching
    reviewed = await t.reviewed()
    t.run.status = RunStatus.COMPLETED.value
    await t.db.flush()
    changed = await t.service.change(
        t.ctx,
        reviewed.id,
        reviewed.revision,
        BrowserProcedureTeachingChange(action="review", review=reviewed.review),
    )
    assert not changed.procedure.verified_success
    policy = await repo.policy(t.db, t.org.id)
    await BrowserProcedureTeachingPolicyService(t.db).update(
        t.ctx, BrowserProcedureTeachingPolicyWrite(generation=policy.generation, enabled=False)
    )
    with pytest.raises(BrowserProcedureTeachingRefused):
        await _generation.BrowserProcedureTeachingDraftService(t.db, t.redis).propose(
            t.ctx, changed.id, changed.revision, BrowserProcedureTeachingPropose()
        )
    discarded = await t.service.discard(t.ctx, changed.id)
    assert discarded.status == BrowserProcedureTeachingState.DISCARDED and not discarded.events
    assert await t.service.discard(t.ctx, changed.id) == discarded


async def test_review_requires_exact_revision_and_complete_observed_order(teaching):
    t = teaching
    first = await t.start()
    await t.append()
    stopped = await t.service.stop(t.ctx, first.id)
    chosen = review(
        BrowserProcedureTeachingReviewedAction(
            sequence=2, label="Invented step", parameter="record"
        ),
        parameters=(
            BrowserProcedureTeachingParameter(name="record", description="Requested record"),
        ),
    )
    with pytest.raises(ConflictError):
        await t.service.change(
            t.ctx,
            first.id,
            first.revision,
            BrowserProcedureTeachingChange(action="review", review=chosen),
        )
    with pytest.raises(BrowserProcedureTeachingRefused) as caught:
        await t.service.change(
            t.ctx,
            first.id,
            stopped.revision,
            BrowserProcedureTeachingChange(action="review", review=chosen),
        )
    assert caught.value.reason == BrowserProcedureTeachingReason.REVIEW_REQUIRED


@pytest.fixture
def draft_runtime(teaching, monkeypatch):
    t = teaching
    jobs, boundaries = [], []

    async def enqueue(db, task, payload, **kwargs):
        jobs.append((task, payload, kwargs))

    @asynccontextmanager
    async def transaction():
        boundaries.append("enter")
        yield t.db
        await t.db.flush()
        boundaries.append("exit")

    monkeypatch.setattr(_generation.background_jobs, "enqueue", enqueue)
    monkeypatch.setattr(_generation, "get_db_context", transaction)
    monkeypatch.setattr(_maintenance, "get_db_context", transaction)
    return jobs, boundaries


async def generated(t, runtime):
    reviewed = await t.reviewed()
    queued = await _generation.BrowserProcedureTeachingDraftService(t.db, t.redis).propose(
        t.ctx, reviewed.id, reviewed.revision, BrowserProcedureTeachingPropose()
    )
    await _generation.draft_browser_procedure_teaching(runtime[0][-1][1])
    result = await t.service.get(t.ctx, queued.id)
    return result, await proposal_repo.get(t.db, result.proposal_id, organization_id=t.org.id)


async def test_one_durable_generation_attempt_creates_a_pending_proposal_only(
    teaching, draft_runtime
):
    t = teaching
    reviewed = await t.reviewed()
    svc = _generation.BrowserProcedureTeachingDraftService(t.db, t.redis)
    queued = await svc.propose(
        t.ctx, reviewed.id, reviewed.revision, BrowserProcedureTeachingPropose()
    )
    assert queued.generation_state == BrowserProcedureTeachingGeneration.QUEUED
    assert (
        await svc.propose(t.ctx, reviewed.id, reviewed.revision, BrowserProcedureTeachingPropose())
        == queued
    )
    assert len(draft_runtime[0]) == 1
    task, job, kwargs = draft_runtime[0][0]
    assert task.max_attempts == 1 and "source_hash" in job.model_dump()
    assert set(job.model_dump()) == {
        "organization_id",
        "session_id",
        "revision",
        "source_hash",
        "token",
    }
    assert kwargs["dedupe_active"] and kwargs["idempotency_key"] == str(job.token)
    await _generation.draft_browser_procedure_teaching(job)
    await _generation.draft_browser_procedure_teaching(job)
    result = await t.service.get(t.ctx, reviewed.id)
    assert (
        result.status == BrowserProcedureTeachingState.PROPOSED
        and result.generation_state == BrowserProcedureTeachingGeneration.SUCCEEDED
    )
    proposal = await proposal_repo.get(t.db, result.proposal_id, organization_id=t.org.id)
    assert proposal.status == "pending" and proposal.skill_id is None
    assert (
        await t.db.scalar(select(func.count(Skill.id)).where(Skill.organization_id == t.org.id))
        == 0
    )
    assert (
        await t.db.scalar(
            select(func.count(SkillProposal.id)).where(SkillProposal.organization_id == t.org.id)
        )
        == 1
    )
    with pytest.raises(ConflictError):
        await t.service.discard(t.ctx, result.id)


@pytest.mark.parametrize("decision", ["apply", "discard"])
async def test_existing_human_proposal_decision_erases_capture_and_applied_version_keeps_provenance(
    teaching, draft_runtime, decision
):
    t = teaching
    result, proposal = await generated(t, draft_runtime)
    svc = SkillProposalService(t.db)
    decided = await getattr(svc, decision)(
        t.ctx, proposal.id, ProposalDecision(revision=proposal.revision)
    )
    assert decided.status == ("applied" if decision == "apply" else "discarded")
    row = await repo.session(t.db, t.org.id, result.id)
    assert (
        row.sanitized_events == []
        and row.review is None
        and row.procedure is None
        and row.title == ""
    )
    if decision == "apply":
        skill = await t.db.scalar(
            select(Skill).where(Skill.organization_id == t.org.id, Skill.name == proposal.name)
        )
        version = await t.db.get(SkillVersion, skill.latest_version_id)
        assert (
            version.source == "browser_teaching"
            and version.browser_procedure == proposal.browser_procedure
        )


async def test_workspace_rewrite_cannot_overwrite_reviewed_teaching_proposal(
    teaching, draft_runtime
):
    t = teaching
    _, proposal = await generated(t, draft_runtime)
    assert (
        await proposal_repo.get_pending_for_skill(
            t.db,
            organization_id=t.org.id,
            skill_id=None,
            name=proposal.name,
            agent_id=t.agent.id,
        )
        is None
    )
    assert (
        await proposal_repo.replace_body(
            t.db,
            proposal=proposal,
            description=SECRET,
            content=SECRET,
            resources={},
            conversation_id=None,
            base_version=None,
            base_version_id=None,
            fork_id=None,
        )
        is None
    )
    await t.db.refresh(proposal)
    assert SECRET not in proposal.content


async def test_assistant_drafting_has_a_positive_budget_current_authority_and_unknown_no_retry(
    teaching, draft_runtime, monkeypatch
):
    t = teaching
    reviewed = await t.reviewed()
    monkeypatch.setattr(_generation.SystemAgentRunner, "require_runnable", AsyncMock())
    seen = []

    async def model(self, ctx, **kwargs):
        row = await repo.session(t.db, t.org.id, reviewed.id)
        assert row.generation_state == BrowserProcedureTeachingGeneration.GENERATING
        assert draft_runtime[1][-1] == "enter" and "exit" in draft_runtime[1]
        assert kwargs["run_limit_usd"] == Decimal("0.05")
        assert SECRET not in kwargs["prompt"]
        await kwargs["check_model_request"](t.db)
        seen.append("attempt")
        raise TimeoutError(SECRET)

    monkeypatch.setattr(_generation.SystemAgentRunner, "run", model)
    request = BrowserProcedureTeachingPropose(mode="assistant", max_cost_usd=Decimal("0.05"))
    svc = _generation.BrowserProcedureTeachingDraftService(t.db, t.redis)
    await svc.propose(t.ctx, reviewed.id, reviewed.revision, request)
    job = draft_runtime[0][-1][1]
    await _generation.draft_browser_procedure_teaching(job)
    await _generation.draft_browser_procedure_teaching(job)
    result = await svc.propose(t.ctx, reviewed.id, reviewed.revision, request)
    assert result.generation_state == BrowserProcedureTeachingGeneration.UNKNOWN
    assert result.reason_code == BrowserProcedureTeachingReason.GENERATION_UNKNOWN and seen == [
        "attempt"
    ]
    assert result.proposal_id is None and len(draft_runtime[0]) == 1


async def applied_binding(t, runtime):
    _, proposal = await generated(t, runtime)
    await SkillProposalService(t.db).apply(
        t.ctx, proposal.id, ProposalDecision(revision=proposal.revision)
    )
    skill = await t.db.scalar(
        select(Skill).where(Skill.organization_id == t.org.id, Skill.name == proposal.name)
    )
    version = await t.db.get(SkillVersion, skill.latest_version_id)
    spec = AgentSpec.model_validate(t.version.spec).model_copy(update={"skill_ids": [skill.id]})
    published = AgentVersion(
        organization_id=t.org.id, agent_id=t.agent.id, version=2, spec=spec.model_dump(mode="json")
    )
    t.db.add(published)
    await t.db.flush()
    t.agent.current_version_id = published.id
    t.run.status = RunStatus.COMPLETED.value
    next_run = AgentRun(
        organization_id=t.org.id,
        user_id=t.owner.id,
        agent_id=t.agent.id,
        agent_version_id=published.id,
        conversation_id=t.run.conversation_id,
        status=RunStatus.RUNNING.value,
        surface=RunSurface.WEB.value,
    )
    t.db.add(next_run)
    await t.db.flush()
    t.run, t.version = next_run, published
    log = SkillUseLog(agent_id=t.agent.id, served={skill.name: ServedSkill(skill.id, version.id)})
    return skill, version, proposal, log


async def test_later_run_discovers_only_the_applied_bound_version_and_capture_optout_keeps_it(
    teaching, draft_runtime
):
    t = teaching
    skill, version, _, log = await applied_binding(t, draft_runtime)
    result = await _discovery.discover(t.db, t.deps(), log, ORIGIN)
    assert (
        len(result) == 1
        and result[0].skill_id == skill.id
        and result[0].skill_version_id == version.id
    )
    assert "Observe the live page" in result[0].instruction
    assert not result[0].procedure.verified_success
    assert await _discovery.discover(t.db, t.deps(), log, "https://other.example.test") == ()
    policy = await repo.policy(t.db, t.org.id)
    await BrowserProcedureTeachingPolicyService(t.db).update(
        t.ctx, BrowserProcedureTeachingPolicyWrite(generation=policy.generation, enabled=False)
    )
    assert await _discovery.discover(t.db, t.deps(), log, ORIGIN) == result
    assert SECRET not in result[0].model_dump_json()


@pytest.mark.parametrize(
    "change",
    [
        "projected",
        "missing_version",
        "wrong_skill",
        "pending",
        "metadata",
        "content",
        "binding",
        "draft_run",
        "permission",
    ],
)
async def test_discovery_rechecks_current_binding_grant_and_immutable_applied_provenance(
    teaching, draft_runtime, monkeypatch, change
):
    t = teaching
    skill, version, proposal, log = await applied_binding(t, draft_runtime)
    if change == "projected":
        log.served = {skill.name: ServedSkill(skill.id, version.id, projected=True)}
    elif change == "missing_version":
        log.served = {skill.name: ServedSkill(skill.id, uuid4())}
    elif change == "wrong_skill":
        log.served = {skill.name: ServedSkill(uuid4(), version.id)}
    elif change == "pending":
        proposal.status = "pending"
    elif change == "metadata":
        proposal.browser_procedure = {"value": SECRET}
    elif change == "content":
        proposal.content = SECRET
    elif change == "binding":
        newer = AgentSpec.model_validate(t.version.spec).model_copy(update={"skill_ids": []})
        published = AgentVersion(
            organization_id=t.org.id,
            agent_id=t.agent.id,
            version=3,
            spec=newer.model_dump(mode="json"),
        )
        t.db.add(published)
        await t.db.flush()
        t.agent.current_version_id = published.id
    elif change == "draft_run":
        t.run.test_spec = t.version.spec
    else:
        monkeypatch.setattr(_discovery, "resolve_access", AsyncMock(return_value=False))
    await t.db.flush()
    if change == "draft_run":
        with pytest.raises(BrowserProcedureTeachingRefused):
            await _discovery.discover(t.db, t.deps(), log, ORIGIN)
    else:
        assert await _discovery.discover(t.db, t.deps(), log, ORIGIN) == ()


@pytest.mark.parametrize(
    "change", ["impersonated", "delegated", "anonymous", "shared", "owner", "agent", "log_owner"]
)
async def test_discovery_never_uses_publisher_delegated_or_other_person_context(
    teaching, draft_runtime, change
):
    t = teaching
    _, _, _, log = await applied_binding(t, draft_runtime)
    deps = t.deps()
    if change in {"impersonated", "delegated"}:
        setattr(deps, change, True)
    elif change == "anonymous":
        deps.audience = None
    elif change == "shared":
        deps.audience = RunAudience(
            user_id=t.owner.id, browses_signed_in=True, shared_transcript=True
        )
    elif change == "owner":
        deps.run_person = uuid4()
    elif change == "agent":
        deps.agent_id = uuid4()
    else:
        log.own = False
    with pytest.raises(BrowserProcedureTeachingRefused):
        await _discovery.discover(t.db, deps, log, ORIGIN)
