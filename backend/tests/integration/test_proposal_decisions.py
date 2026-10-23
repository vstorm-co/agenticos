"""A proposed change to a context file: a real change, decided once, and live where served.

A proposal never carries the wrapper its prompt put around the file, and one
that says what the file already says is not made. A decision names the revision
the reviewer read and wins only while the proposal is still pending at it - of
two made at once exactly one, against Postgres. Applying goes live at once for
every agent whose served version reads the file: the reviewer is told where and
behind which suites, the suites are queued, the owners told, and the audit
entry names the agents.
"""

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import AlreadyExistsError, ConcurrentChangeError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent, AgentVersion
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.context import ContextFile
from app.db.models.context_proposal import ContextProposal
from app.db.models.conversation import Message, ToolCall
from app.db.models.eval_suite import EvalSuite, EvalSuiteResult
from app.db.models.notification import Notification
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.promotion_gate import EnvironmentGuard
from app.db.models.skill import Skill
from app.db.models.skill_proposal import ProposalStatus, SkillProposal
from app.db.models.user import User
from app.repositories import (
    agent_environment_repo,
    authoring_repo,
    context_proposal_repo,
    eval_suite_repo,
    skill_proposal_repo,
)
from app.schemas.authoring import AuthoringStart
from app.schemas.context import ContextFileUpdate
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.resource_usage import ProposalDecision
from app.services.authoring import AuthoringService
from app.services.authoring_worker import AuthoringWorker
from app.services.context import ContextService
from app.services.context_proposal import ContextProposalService
from app.services.dataset import DatasetService
from app.services.skill_proposal import SkillProposalService
from tests.integration.test_authoring import (
    Improver,
    _answering,
    _clerk,
    _environment,  # noqa: F401 - the autouse fixture that scripts the improver's model
    _member,
    _sessions,
    _setup,
)
from tests.integration.test_authoring_context import (
    _bound,
    _improve_context,
    _pending,
    _proposes,
)

pytestmark = pytest.mark.anyio


def _returning(db: AsyncSession, run_id: str, content: str, description: str) -> Improver:
    return Improver(
        db,
        improve={
            "summary": "s",
            "expected_effect": "e",
            "description": description,
            "content": content,
            "rationale": "r",
            "evidence": [{"run_id": run_id, "quote": "x"}],
        },
    )


async def test_the_prompt_wrapper_never_lands_and_an_unchanged_file_is_no_proposal(db):
    ctx, _, file, run_id = await _bound(db)

    unchanged = await _improve_context(
        db,
        ctx,
        file,
        _returning(db, run_id, "<context>\nReturns take 90 days.  \n</context>", "Returns"),
    )
    assert unchanged.status == "completed", unchanged.error
    assert unchanged.report["no_change"] is True
    assert await _pending(db, file) == []

    await _improve_context(
        db,
        ctx,
        file,
        _returning(db, run_id, "<context>\nReturns take 30 days.\n</context>", "Returns"),
    )
    (proposal,) = await _pending(db, file)
    assert proposal.content == "Returns take 30 days."


async def test_a_file_wrapped_in_the_tags_itself_keeps_them(db):
    ctx, _, file, run_id = await _bound(db)
    file.content = "<context>\nReturns take 90 days.\n</context>"
    await db.flush()

    wrapped = "<context>\nReturns take 30 days.\n</context>"
    await _improve_context(db, ctx, file, _returning(db, run_id, wrapped, "Returns"))

    (proposal,) = await _pending(db, file)
    assert proposal.content == wrapped


async def _served_and_guarded(db: AsyncSession, ctx: AuthContext, agent: Agent) -> EvalSuite:
    """Production serves the agent's published version, guarded by a suite that
    watches what the agent reads."""
    environment = await agent_environment_repo.create(
        db,
        organization_id=ctx.organization_id,
        agent_id=agent.id,
        name="production",
        version_id=agent.current_version_id,
        is_default=True,
    )
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name="returns"))
    await datasets.add_case(
        ctx, dataset.id, DatasetCaseCreate(input="Q", checks=[{"type": "contains", "value": "30"}])
    )
    suite = await eval_suite_repo.create(
        db,
        organization_id=ctx.organization_id,
        suite=EvalSuite(
            agent_id=agent.id,
            dataset_id=dataset.id,
            owner_user_id=ctx.user_id,
            name="returns smoke",
            on_dependency_change=True,
        ),
    )
    db.add(
        EnvironmentGuard(
            environment_id=environment.id, suite_id=suite.id, organization_id=ctx.organization_id
        )
    )
    await db.flush()
    return suite


async def test_applying_goes_live_where_served_and_says_so_everywhere(db):
    ctx, agent, file, run_id = await _bound(db)
    suite = await _served_and_guarded(db, ctx, agent)
    # An agent whose served version reads another file is not reached.
    bystander = await _clerk(db, ctx)
    await agent_environment_repo.create(
        db,
        organization_id=ctx.organization_id,
        agent_id=bystander.id,
        name="production",
        version_id=bystander.current_version_id,
        is_default=True,
    )
    # Suites watching for changes elsewhere - one of an agent that does not read the
    # file, one of an agent with nothing published - neither run nor show.
    unpublished = await _clerk(db, ctx)
    unpublished.current_version_id = None
    for watcher in (bystander, unpublished):
        await eval_suite_repo.create(
            db,
            organization_id=ctx.organization_id,
            suite=EvalSuite(
                agent_id=watcher.id,
                dataset_id=suite.dataset_id,
                owner_user_id=ctx.user_id,
                name=f"watching {watcher.id}",
                on_dependency_change=True,
            ),
        )
    owner = await _member(db, ctx, OrgRoleName.MEMBER)
    agent.owner_user_id = owner.user_id
    await db.flush()
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    (proposal,) = await _pending(db, file)
    service = ContextProposalService(db)

    # A second guard that does not run on a change checks the agent when it is promoted.
    nightly = await eval_suite_repo.create(
        db,
        organization_id=ctx.organization_id,
        suite=EvalSuite(
            agent_id=agent.id,
            dataset_id=suite.dataset_id,
            owner_user_id=ctx.user_id,
            name="nightly",
        ),
    )
    production = await agent_environment_repo.get_default_for_agent(db, agent_id=agent.id)
    assert production is not None
    db.add(
        EnvironmentGuard(
            environment_id=production.id, suite_id=nightly.id, organization_id=ctx.organization_id
        )
    )
    await db.flush()

    read = await service.read(ctx, proposal.id)
    assert [
        (item.name, item.environments, item.runs_now, item.at_promotion) for item in read.reaches
    ] == [(agent.name, ["production"], ["returns smoke"], ["nightly"])]
    assert read.reaches_hidden == 0

    applied = await service.apply(ctx, proposal.id, ProposalDecision(revision=proposal.revision))

    assert applied.status == "applied" and applied.reaches == []
    queued = (
        await db.scalars(select(EvalSuiteResult).where(EvalSuiteResult.suite_id == suite.id))
    ).all()
    assert [(result.trigger, result.trigger_detail) for result in queued] == [
        ("dependency", {"kind": "context", "id": str(file.id)})
    ]
    assert (
        await db.scalars(select(EvalSuiteResult).where(EvalSuiteResult.suite_id != suite.id))
    ).all() == []
    told = (
        await db.scalars(
            select(Notification).where(Notification.event_type == "shared_change_applied")
        )
    ).all()
    assert [(item.recipient_user_id, item.summary) for item in told] == [
        (owner.user_id, f"A change to the context file {file.name} went live for {agent.name}")
    ]
    (entry,) = (
        await db.scalars(
            select(AppAdminAuditLog).where(AppAdminAuditLog.action == "context.change_applied")
        )
    ).all()
    assert entry.details == {
        "name": file.name,
        "proposal_id": str(proposal.id),
        "revision": proposal.revision,
        "agents": [str(agent.id)],
    }
    assert "Returns take 30 days." not in str(entry.details)


@pytest.mark.security
async def test_a_reader_learns_only_how_many_agents_they_may_not_see_and_no_suite_names(db):
    ctx, agent, file, run_id = await _bound(db)
    await _served_and_guarded(db, ctx, agent)
    stranger = await _member(db, ctx, OrgRoleName.MEMBER)
    agent.owner_user_id = ctx.user_id
    agent.visibility = "private"
    await db.flush()
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    (proposal,) = await _pending(db, file)

    read = await ContextProposalService(db).read(stranger, proposal.id)

    assert (read.reaches, read.reaches_hidden) == ([], 1)


async def test_a_reader_without_runs_view_counts_the_suites_without_their_names(db):
    ctx, agent, file, run_id = await _bound(db)
    await _served_and_guarded(db, ctx, agent)
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    (proposal,) = await _pending(db, file)
    member = await _member(db, ctx, OrgRoleName.MEMBER)
    assert not member.has(Perm.RUNS_VIEW)

    (item,) = (await ContextProposalService(db).read(member, proposal.id)).reaches

    assert (item.runs_now, item.runs_now_count) == ([], 1)


async def test_deleting_a_file_queues_the_suites_of_the_agents_that_read_it(db):
    ctx, agent, file, _ = await _bound(db)
    suite = await _served_and_guarded(db, ctx, agent)

    await ContextService(db).delete(ctx, file.id)

    queued = (
        await db.scalars(select(EvalSuiteResult).where(EvalSuiteResult.suite_id == suite.id))
    ).all()
    assert [(result.trigger, result.trigger_detail) for result in queued] == [
        ("dependency", {"kind": "context", "id": str(file.id)})
    ]


async def test_a_decision_on_a_revision_a_newer_run_replaced_writes_nothing(db):
    ctx, _, file, run_id = await _bound(db)
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    await _improve_context(db, ctx, file, _proposes(db, run_id, "Returns take 14 days."))
    (proposal,) = await _pending(db, file)
    service = ContextProposalService(db)

    assert proposal.revision == 2
    for decide in (service.apply, service.discard):
        with pytest.raises(ConcurrentChangeError, match="changed since you opened it"):
            await decide(ctx, proposal.id, ProposalDecision(revision=1))

    await db.refresh(file)
    await db.refresh(proposal)
    assert (file.content, proposal.status) == ("Returns take 90 days.", "pending")


async def test_a_change_to_who_may_see_a_file_queues_no_suite(db):
    ctx, agent, file, _ = await _bound(db)
    suite = await _served_and_guarded(db, ctx, agent)
    contexts = ContextService(db)

    await contexts.update(ctx, file.id, ContextFileUpdate(visibility="private"))
    assert (
        await db.scalars(select(EvalSuiteResult).where(EvalSuiteResult.suite_id == suite.id))
    ).all() == []

    await contexts.update(ctx, file.id, ContextFileUpdate(content="Returns take 60 days."))
    assert (
        len(
            (
                await db.scalars(
                    select(EvalSuiteResult).where(EvalSuiteResult.suite_id == suite.id)
                )
            ).all()
        )
        == 1
    )


async def _committed_proposal(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[AuthContext, uuid.UUID, uuid.UUID]:
    """An owner, a file and a pending proposal for it, committed for other sessions to see."""
    async with factory() as setup:
        user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex}@example.com", hashed_password="x")
        org = Organization(
            id=uuid.uuid4(),
            name="Acme",
            slug=f"acme-{uuid.uuid4().hex[:8]}",
            created_by_user_id=user.id,
        )
        setup.add(user)
        await setup.flush()
        setup.add(org)
        await setup.flush()
        setup.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
        file = ContextFile(
            organization_id=org.id,
            owner_user_id=user.id,
            visibility="org",
            name="returns",
            description="Returns",
            content="Returns take 90 days.",
            mode="inject",
        )
        setup.add(file)
        await setup.flush()
        proposal = ContextProposal(
            organization_id=org.id,
            context_id=file.id,
            base_updated_at=file.updated_at,
            description="Returns",
            content="Returns take 30 days.",
        )
        setup.add(proposal)
        await setup.commit()
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER.value)
    return ctx, file.id, proposal.id


async def test_of_an_apply_and_a_discard_made_at_once_exactly_one_wins(engine: AsyncEngine):
    """Two sessions, two transactions: the apply holds the proposal row it
    decided; the discard, which read it pending, waits on that row and - once the
    apply commits - finds it decided and is refused, writing nothing."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx, file_id, proposal_id = await _committed_proposal(factory)
    decision = ProposalDecision(revision=1)

    session_a = factory()
    discarding: asyncio.Task[object] | None = None
    try:
        await ContextProposalService(session_a).apply(ctx, proposal_id, decision)

        async def discard() -> object:
            async with factory() as session_b:
                decided = await ContextProposalService(session_b).discard(
                    ctx, proposal_id, decision
                )
                await session_b.commit()
                return decided

        discarding = asyncio.create_task(discard())
        await asyncio.sleep(0.4)
        assert not discarding.done()  # waiting on the row the apply decided

        await session_a.commit()
        with pytest.raises(ConcurrentChangeError, match="changed since you opened it"):
            await discarding
        discarding = None
    finally:
        if discarding is not None:
            discarding.cancel()
            with contextlib.suppress(BaseException):
                await discarding
        await session_a.close()

    async with factory() as check:
        stored = await check.get(ContextProposal, proposal_id)
        written = await check.get(ContextFile, file_id)
        assert stored is not None and written is not None
        assert (stored.status, written.content) == ("applied", "Returns take 30 days.")


async def _opened(db: AsyncSession, *, content: str) -> tuple[AuthContext, Agent, Skill]:
    """A skill a rated run opened, bound by the agent's published version."""
    ctx, agent, run = await _setup(db)
    skill = Skill(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        name="refunds",
        description="Refunds",
        content=content,
    )
    db.add(skill)
    await db.flush()
    answer = await db.scalar(
        select(Message).where(Message.run_id == run.id, Message.role == "assistant")
    )
    assert answer is not None
    db.add(
        ToolCall(
            message_id=answer.id,
            tool_call_id="call-1",
            tool_name="load_capability",
            args={"id": "refunds"},
            started_at=datetime.now(UTC),
        )
    )
    spec = {**agent.draft_spec, "skill_ids": [str(skill.id)]}
    agent.draft_spec = spec
    version = await db.get(AgentVersion, agent.current_version_id)
    assert version is not None
    version.spec = spec
    await db.flush()
    return ctx, agent, skill


async def test_a_skill_proposal_that_says_what_the_skill_says_is_not_made(db):
    # The improver's answer is exactly this body and description.
    ctx, _, skill = await _opened(db, content="Refunds take 30 days.")

    started = await AuthoringService(db).start_skill(ctx, skill.id, AuthoringStart())
    with _answering(Improver(db)):
        await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()

    request = await authoring_repo.get_request(db, started.id, organization_id=ctx.organization_id)
    assert request is not None and request.report is not None
    assert request.report["no_change"] is True
    assert (
        await db.scalars(select(SkillProposal).where(SkillProposal.skill_id == skill.id))
    ).all() == []


async def test_applying_a_skill_change_goes_live_where_served_and_tells_the_owners(db):
    ctx, agent, skill = await _opened(db, content="Refunds take 90 days.")
    await _served_and_guarded(db, ctx, agent)
    owner = await _member(db, ctx, OrgRoleName.MEMBER)
    agent.owner_user_id = owner.user_id
    proposal = SkillProposal(
        organization_id=ctx.organization_id,
        skill_id=skill.id,
        name="refunds",
        description="Refunds",
        content="Refunds take 30 days.",
        resources={},
    )
    db.add(proposal)
    await db.flush()
    service = SkillProposalService(db)

    read = await service.read(ctx, proposal.id)
    applied = await service.apply(ctx, proposal.id, ProposalDecision(revision=1))

    assert [(item.name, item.environments) for item in read.reaches] == [
        (agent.name, ["production"])
    ]
    assert applied.status == "applied"
    told = (
        await db.scalars(
            select(Notification).where(Notification.event_type == "shared_change_applied")
        )
    ).all()
    assert [(item.recipient_user_id, item.summary) for item in told] == [
        (owner.user_id, f"A change to the skill refunds went live for {agent.name}")
    ]
    (entry,) = (
        await db.scalars(
            select(AppAdminAuditLog).where(AppAdminAuditLog.action == "skill.change_applied")
        )
    ).all()
    assert entry.details is not None and entry.details["agents"] == [str(agent.id)]
    with pytest.raises(AlreadyExistsError):
        await service.discard(ctx, proposal.id, ProposalDecision(revision=1))


@pytest.mark.security
async def test_an_owner_who_cannot_see_the_skill_is_told_without_its_name(db):
    """An agent may read a private skill its publisher was given; its owner learns
    that something it reads changed, not what the skill is called."""
    ctx, agent, skill = await _opened(db, content="Refunds take 90 days.")
    await _served_and_guarded(db, ctx, agent)
    skill.visibility = "private"
    owner = await _member(db, ctx, OrgRoleName.MEMBER)
    agent.owner_user_id = owner.user_id
    proposal = SkillProposal(
        organization_id=ctx.organization_id,
        skill_id=skill.id,
        name="refunds",
        description="Refunds",
        content="Refunds take 30 days.",
        resources={},
    )
    db.add(proposal)
    await db.flush()

    await SkillProposalService(db).apply(ctx, proposal.id, ProposalDecision(revision=1))

    (told,) = (
        await db.scalars(
            select(Notification).where(Notification.event_type == "shared_change_applied")
        )
    ).all()
    assert told.summary == f"A change to a skill it reads went live for {agent.name}"
    assert "refunds" not in str(told.render_context)


async def test_whoever_applies_a_change_is_not_told_of_it(db):
    ctx, agent, file, run_id = await _bound(db)
    await _served_and_guarded(db, ctx, agent)
    assert agent.owner_user_id == ctx.user_id
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    (proposal,) = await _pending(db, file)

    await ContextProposalService(db).apply(ctx, proposal.id, ProposalDecision(revision=1))

    assert (
        await db.scalars(
            select(Notification).where(Notification.event_type == "shared_change_applied")
        )
    ).all() == []


async def test_a_run_rewriting_a_proposal_an_apply_decided_meanwhile_leaves_it_alone(
    engine: AsyncEngine,
):
    """The apply holds the proposal row it decided; a run that read the proposal
    pending waits on that row and - once the apply commits - finds it decided,
    so it writes nothing over the record of what went live."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    ctx, file_id, proposal_id = await _committed_proposal(factory)
    session_a = factory()
    rewriting: asyncio.Task[object] | None = None
    try:
        async with factory() as reader:
            read = await reader.get(ContextProposal, proposal_id)
            assert read is not None
        await ContextProposalService(session_a).apply(
            ctx, proposal_id, ProposalDecision(revision=1)
        )

        async def rewrite() -> object:
            async with factory() as session_b:
                rewritten = await context_proposal_repo.rewrite(
                    session_b, proposal=read, values={"content": "Returns take 7 days."}
                )
                await session_b.commit()
                return rewritten

        rewriting = asyncio.create_task(rewrite())
        await asyncio.sleep(0.4)
        assert not rewriting.done()  # waiting on the row the apply decided

        await session_a.commit()
        assert await rewriting is None
        rewriting = None
    finally:
        if rewriting is not None:
            rewriting.cancel()
            with contextlib.suppress(BaseException):
                await rewriting
        await session_a.close()

    async with factory() as check:
        stored = await check.get(ContextProposal, proposal_id)
        assert stored is not None
        assert (stored.status, stored.content, stored.revision) == (
            "applied",
            "Returns take 30 days.",
            1,
        )


async def test_a_run_whose_pending_proposal_was_decided_proposes_anew(db, monkeypatch):
    ctx, _, file, run_id = await _bound(db)
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    (first,) = await _pending(db, file)

    async def decided_meanwhile(db: AsyncSession, *, proposal: ContextProposal, values: object):
        await context_proposal_repo.decide_if(
            db,
            proposal_id=proposal.id,
            organization_id=proposal.organization_id,
            revision=proposal.revision,
            status=ProposalStatus.APPLIED,
            decided_by=None,
        )

    monkeypatch.setattr(context_proposal_repo, "rewrite", decided_meanwhile)

    await _improve_context(db, ctx, file, _proposes(db, run_id, "Returns take 14 days."))

    rows = (
        await db.scalars(select(ContextProposal).where(ContextProposal.context_id == file.id))
    ).all()
    assert sorted(row.content for row in rows) == ["Returns take 14 days.", "Returns take 30 days."]
    assert first.revision == 1


async def _skill_decided_meanwhile(db: AsyncSession, *, proposal: SkillProposal, **_: object):
    await skill_proposal_repo.decide_if(
        db,
        proposal_id=proposal.id,
        organization_id=proposal.organization_id,
        revision=proposal.revision,
        status=ProposalStatus.APPLIED,
        decided_by=None,
    )


async def test_a_skill_run_whose_pending_proposal_was_decided_proposes_anew(db, monkeypatch):
    ctx, _, skill = await _opened(db, content="Refunds take 90 days.")
    service = AuthoringService(db)

    for _ in range(2):
        started = await service.start_skill(ctx, skill.id, AuthoringStart())
        with _answering(Improver(db)):
            await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()
        monkeypatch.setattr(skill_proposal_repo, "replace_body", _skill_decided_meanwhile)

    rows = (await db.scalars(select(SkillProposal).where(SkillProposal.skill_id == skill.id))).all()
    assert len(rows) == 2
