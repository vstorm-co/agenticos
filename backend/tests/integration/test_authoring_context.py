"""Context file changes end to end: proposed from evidence, checked with evals, applied once.

- Improve on a context file reads the rated runs of the agents that bind it and
  leaves one proposal waiting for the file, its quotes checked, written against
  the file as it stood.
- Apply writes the file once and is refused when the file changed since or the
  proposal was already decided; discard keeps the record.
- A reviewer sees which agents read the file, quotes only with `runs:view`, and
  nothing of a file they may not see.
- Check runs a dataset on an agent bound to the file, its published version on
  both sides, the proposed body served on the candidate alone.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.authoring import AuthoringRequest
from app.db.models.context import ContextFile
from app.db.models.context_proposal import ContextProposal
from app.db.models.eval_run import EvalRunArm
from app.db.models.eval_suite import EvalSuite
from app.db.models.organization import OrganizationMember
from app.repositories import authoring_repo, eval_suite_repo
from app.schemas.authoring import AuthoringStart, ProposalCheck
from app.schemas.context import ContextFileUpdate
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.services.authoring import AuthoringService
from app.services.authoring_worker import AuthoringWorker
from app.services.context import ContextService
from app.services.context_proposal import ContextProposalService
from app.services.dataset import DatasetService
from app.services.eval_run import EvalRunService
from tests.integration.test_authoring import (
    COMMENT,
    Improver,
    _answering,
    _assert_reads_no_eval,
    _clerk,
    _environment,  # noqa: F401 - the autouse fixture that scripts the improver's model
    _eval_secrets,
    _improver,
    _member,
    _owner,
    _rated,
    _read_while_working,
    _sessions,
)

pytestmark = pytest.mark.anyio


async def _bound(db: AsyncSession) -> tuple[AuthContext, Agent, ContextFile, str]:
    """An owner, an agent whose draft and published version bind a file, and a rated run."""
    ctx = await _owner(db)
    await _improver(db, ctx)
    agent = await _clerk(db, ctx)
    file = ContextFile(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        name=f"returns-{uuid.uuid4().hex[:4]}",
        description="Returns",
        content="Returns take 90 days.",
        mode="inject",
    )
    db.add(file)
    await db.flush()
    spec = {**agent.draft_spec, "context_ids": [str(file.id)]}
    agent.draft_spec = spec
    version = await db.get(AgentVersion, agent.current_version_id)
    assert version is not None
    version.spec = spec
    run = await _rated(db, ctx, agent)
    await db.flush()
    return ctx, agent, file, str(run.id)


def _proposes(db: AsyncSession, run_id: str, content: str = "Returns take 30 days.") -> Improver:
    return Improver(
        db,
        improve={
            "summary": "Readers corrected the window",
            "expected_effect": "Answers name 30 days",
            "description": "Returns, corrected",
            "content": content,
            "rationale": "Three readers corrected it",
            "evidence": [
                {"run_id": run_id, "quote": COMMENT},
                {"run_id": run_id, "quote": "Never said"},
            ],
        },
    )


async def _improve_context(
    db: AsyncSession, ctx: AuthContext, file: ContextFile, model: Improver
) -> Any:
    started = await AuthoringService(db).start_context(ctx, file.id, AuthoringStart())
    with _answering(model):
        await AuthoringWorker(started.id, ctx.organization_id, sessions=_sessions(db)).run()
    return await authoring_repo.get_request(db, started.id, organization_id=ctx.organization_id)


async def _pending(db: AsyncSession, file: ContextFile) -> list[ContextProposal]:
    rows = await db.scalars(
        select(ContextProposal).where(
            ContextProposal.context_id == file.id, ContextProposal.status == "pending"
        )
    )
    return list(rows)


@pytest.mark.security
async def test_improving_a_file_never_reads_an_eval_run_a_score_or_a_dataset(db):
    """The second way into the improver: the runs of every agent bound to the file,
    and still no eval run, score or dataset case among them."""
    ctx, agent, file, run_id = await _bound(db)
    await _eval_secrets(db, ctx, agent)
    model = _proposes(db, run_id)

    started = await AuthoringService(db).start_context(ctx, file.id, AuthoringStart())
    request, read = await _read_while_working(db, ctx, started.id, model)

    _assert_reads_no_eval(model, read)
    assert request.evidence["runs"] == 1
    (proposal,) = await _pending(db, file)
    assert proposal.content == "Returns take 30 days."


async def test_improve_leaves_one_proposal_for_the_file_with_checked_evidence(db):
    ctx, _, file, run_id = await _bound(db)
    model = _proposes(db, run_id)

    request = await _improve_context(db, ctx, file, model)

    assert request is not None and request.status == "completed", request and request.error
    assert "Returns take 90 days." in model.prompts[-1]
    assert "put into every bound agent's instructions" in model.prompts[-1]
    (proposal,) = await _pending(db, file)
    assert proposal.content == "Returns take 30 days."
    assert proposal.base_updated_at == file.updated_at
    assert [item["quote"] for item in proposal.evidence] == [COMMENT]
    assert proposal.evidence_dropped == 1
    assert request.report is not None
    assert request.report["context_proposal_id"] == str(proposal.id)

    await _improve_context(db, ctx, file, _proposes(db, run_id, "Returns take 30 days, by post."))

    (replaced,) = await _pending(db, file)
    assert replaced.id == proposal.id and replaced.content.endswith("by post.")
    listed = await AuthoringService(db).for_context(ctx, file.id)
    assert [item.context_id for item in listed] == [file.id, file.id]
    waiting = await AuthoringService(db).waiting(ctx)
    assert waiting.contexts == 1


async def test_apply_writes_the_file_once_and_refuses_a_file_that_moved(db):
    ctx, agent, file, run_id = await _bound(db)
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    (proposal,) = await _pending(db, file)
    service = ContextProposalService(db)

    read = await service.read(ctx, proposal.id)
    assert (read.stale, read.current_content) == (False, "Returns take 90 days.")
    assert [usage.id for usage in read.used_by] == [agent.id]
    applied = await service.apply(ctx, proposal.id)

    assert applied.status == "applied"
    await db.refresh(file)
    assert (file.content, file.description) == ("Returns take 30 days.", "Returns, corrected")
    with pytest.raises(AlreadyExistsError, match="already applied"):
        await service.apply(ctx, proposal.id)

    await _improve_context(db, ctx, file, _proposes(db, run_id, "Returns take 14 days."))
    (newer,) = await _pending(db, file)
    await ContextService(db).update(ctx, file.id, ContextFileUpdate(content="Edited by hand."))
    # The test is one transaction, where `now()` stands still; a person's edit is a later one.
    file.updated_at = datetime.now(UTC) + timedelta(minutes=1)
    await db.flush()
    assert (await service.read(ctx, newer.id)).stale is True
    with pytest.raises(ConcurrentChangeError, match="changed since"):
        await service.apply(ctx, newer.id)
    discarded = await service.discard(ctx, newer.id)
    assert discarded.status == "discarded"
    listed = await service.list_read(ctx)
    assert sorted(item.status for item in listed.items) == ["applied", "discarded"]
    assert (await service.list_read(ctx, status="applied")).total == 1


async def test_a_reviewer_sees_quotes_only_with_runs_view_and_nothing_of_a_hidden_file(db):
    ctx, _, file, run_id = await _bound(db)
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    (proposal,) = await _pending(db, file)
    member = await _member(db, ctx, OrgRoleName.MEMBER)
    service = ContextProposalService(db)

    read = await service.read(member, proposal.id)
    assert [item["quote"] for item in read.evidence] == [None]

    file.visibility = "private"
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.read(member, proposal.id)
    assert (await service.list_read(member)).items == []
    with pytest.raises(NotFoundError, match="Context change not found"):
        await service.read(ctx, uuid.uuid4())


async def test_a_context_change_is_checked_on_an_agent_that_binds_it(db):
    ctx, agent, file, run_id = await _bound(db)
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    (proposal,) = await _pending(db, file)
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name="returns-cases"))
    await datasets.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(input="Q", checks=[{"type": "contains", "value": "30 days"}]),
    )
    service = AuthoringService(db)
    body = ProposalCheck(dataset_id=dataset.id, agent_id=agent.id, proposal_id=proposal.id)

    estimate = await service.estimate_context_check(ctx, file.id, body)
    started = await service.check_context(ctx, file.id, body)

    assert estimate.cases == 1
    assert {arm.source for arm in started.arms} == {"version"}
    candidate = next(arm for arm in started.arms if arm.role == "candidate")
    assert candidate.context_ids == [file.id]
    arms = (
        (await db.execute(select(EvalRunArm).where(EvalRunArm.eval_run_id == started.id)))
        .scalars()
        .all()
    )
    assert {arm.role: arm.context_bodies for arm in arms} == {
        "candidate": {
            str(file.id): {"description": "Returns, corrected", "content": "Returns take 30 days."}
        },
        "baseline": None,
    }
    await db.refresh(file)
    assert file.content == "Returns take 90 days."

    other = await _clerk(db, ctx)
    for check, reason in (
        (ProposalCheck(dataset_id=dataset.id, agent_id=agent.id), NotFoundError),
        (ProposalCheck(dataset_id=dataset.id, proposal_id=proposal.id), BadRequestError),
        (
            ProposalCheck(dataset_id=dataset.id, agent_id=other.id, proposal_id=proposal.id),
            BadRequestError,
        ),
    ):
        with pytest.raises(reason):
            await service.check_context(ctx, file.id, check)


async def test_a_context_change_checked_on_a_suite_keeps_the_suite_it_ran_on(db):
    ctx, agent, file, run_id = await _bound(db)
    await _improve_context(db, ctx, file, _proposes(db, run_id))
    (proposal,) = await _pending(db, file)
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name="returns-cases"))
    await datasets.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(input="Q", checks=[{"type": "contains", "value": "30 days"}]),
    )
    suite = await eval_suite_repo.create(
        db,
        organization_id=ctx.organization_id,
        suite=EvalSuite(
            agent_id=agent.id, dataset_id=dataset.id, owner_user_id=ctx.user_id, name="returns"
        ),
    )

    started = await AuthoringService(db).check_context(
        ctx, file.id, ProposalCheck(suite_id=suite.id, agent_id=agent.id, proposal_id=proposal.id)
    )

    read = await EvalRunService(db).get(ctx, started.id)
    assert read.suite_check is not None
    assert (read.suite_check.suite_id, read.suite_check.name) == (suite.id, "returns")


async def test_what_refuses_an_improve_on_a_context_file(db):
    ctx, _, file, _ = await _bound(db)
    service = AuthoringService(db)
    member = await _member(db, ctx, OrgRoleName.MEMBER)
    lonely = ContextFile(
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility="org",
        name="unused",
        content="x",
        mode="link",
    )
    db.add(lonely)
    await db.flush()

    with pytest.raises(BadRequestError, match="no draft to verify"):
        await service.estimate_context(ctx, file.id, AuthoringStart(kind="verify"))
    with pytest.raises(AuthorizationError, match="runs:view"):
        await service.estimate_context(member, file.id, AuthoringStart())
    assert (await service.estimate_context(ctx, lonely.id, AuthoringStart())).reason == (
        "no_evidence"
    )
    assert (await service.waiting(member)).contexts == 0


async def test_the_worker_stops_on_a_file_gone_or_out_of_the_starters_reach(db):
    ctx, _, file, run_id = await _bound(db)
    service = AuthoringService(db)
    gone = await service.start_context(ctx, file.id, AuthoringStart())
    with patch("app.services.authoring_worker.context_repo.get", new=AsyncMock(return_value=None)):
        await AuthoringWorker(gone.id, ctx.organization_id, sessions=_sessions(db)).run()
    lost = await service.start_context(ctx, file.id, AuthoringStart())
    membership = (
        await db.execute(
            select(OrganizationMember).where(OrganizationMember.user_id == ctx.user_id)
        )
    ).scalar_one()
    membership.role = OrgRoleName.OPERATOR.value
    await db.flush()
    with _answering(_proposes(db, run_id)):
        await AuthoringWorker(lost.id, ctx.organization_id, sessions=_sessions(db)).run()

    errors = {
        request.id: request.error
        for request in await db.scalars(
            select(AuthoringRequest).where(AuthoringRequest.id.in_([gone.id, lost.id]))
        )
    }
    assert errors == {
        gone.id: "The context file is gone.",
        lost.id: "Whoever started this may no longer edit the context file.",
    }
