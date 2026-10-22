"""A check of suggestions is measured on the draft's base, not on what production runs.

A failing guard can hold production on v1 after v2 is published. The draft is
made from v2, so checking its suggestions against v1 blames them for whatever
v2 broke. The base is the latest published version - or the draft itself once
it has moved from that version - so the suggestions are the one difference
between the two sides. A check is hypothetical: it sends nothing to review by
itself, and it counts as the draft's test only once the draft is what it
checked.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_run import AgentRun
from app.db.models.case_score import CaseScore
from app.db.models.dataset import DatasetCase
from app.db.models.eval_run import EvalRunCase
from app.schemas.authoring import AuthoringStart, HunkDecision, ProposalCheck
from app.schemas.dataset import DatasetCaseCreate, DatasetCreate
from app.schemas.eval_run import ProposalCheckRecord
from app.schemas.scoring import ReviewRequest
from app.services.agent_registry import UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.authoring import AuthoringService
from app.services.dataset import DatasetService
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from app.services.scoring import ScoringService
from tests.integration.test_authoring import (
    COMMENT,
    INSTRUCTIONS,
    Improver,
    _environment,  # noqa: F401 - the autouse fixture that scripts the improver's model
    _improve,
    _sessions,
    _setup,
)

pytestmark = pytest.mark.anyio

CANADA = "\nNever ship to Canada."
SHIPS = "Do you ship to Canada?"
WINDOW = "How many days do I have to return unworn shoes?"


def _reply(spec: AgentSpec, prompt: str) -> str:
    """What an agent with these instructions answers - so each side answers as it reads."""
    if prompt == SHIPS:
        return (
            "We never ship there."
            if "Never ship to Canada" in spec.instructions
            else ("Yes, we ship to Canada.")
        )
    return "Refunds take 30 days." if "30 days" in spec.instructions else "Refunds take 90 days."


async def _finish(db: AsyncSession, ctx: AuthContext, run_id: Any) -> None:
    async def execute(runner: Any, caller: AuthContext, agent_id: Any, prompt: str, **kw: Any):
        candidate = kw["candidate"]
        if isinstance(candidate, UnpublishedCandidate):
            spec = candidate.spec
        else:
            version = await db.get(AgentVersion, candidate.version_id)
            assert version is not None
            spec = AgentSpec.model_validate(version.spec)
        run = AgentRun(
            organization_id=caller.organization_id,
            agent_id=agent_id,
            user_id=caller.user_id,
            surface=kw["surface"].value,
            status="completed",
            cost_usd=Decimal("0.01"),
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()
        return _reply(spec, prompt), run

    with (
        patch.object(AgentRunnerService, "execute", new=execute),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            run_id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()


async def _shop_dataset(db: AsyncSession, ctx: AuthContext) -> Any:
    datasets = DatasetService(db)
    dataset = await datasets.create(ctx, DatasetCreate(name="audit-returns"))
    await datasets.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(input=SHIPS, checks=[{"type": "contains", "value": "Yes, we ship"}]),
    )
    await datasets.add_case(
        ctx,
        dataset.id,
        DatasetCaseCreate(input=WINDOW, checks=[{"type": "contains", "value": "30 days"}]),
    )
    return dataset


async def _publish_held_back(db: AsyncSession, ctx: AuthContext, agent: Agent) -> None:
    """Publish v2 while production stays on v1, as a failing guard leaves it."""
    spec = {**agent.draft_spec, "instructions": INSTRUCTIONS + CANADA}
    db.add(
        AgentVersion(agent_id=agent.id, organization_id=ctx.organization_id, version=2, spec=spec)
    )
    agent.draft_spec = spec
    await db.flush()


async def test_a_check_measures_the_suggestions_on_the_latest_version_not_on_production(db):
    ctx, agent, _ = await _setup(db)
    await _publish_held_back(db, ctx, agent)
    production = agent.current_version_id
    await _improve(db, ctx, agent, Improver(db))
    dataset = await _shop_dataset(db, ctx)
    service = AuthoringService(db)
    evals = EvalRunService(db)
    body = ProposalCheck(dataset_id=dataset.id)

    estimate = await service.estimate_check(ctx, agent.id, body)
    started = await service.check(ctx, agent.id, body)
    await _finish(db, ctx, started.id)
    read = await evals.get(ctx, started.id)

    checked = ProposalCheckRecord(kind="agent", base_version=2, on_draft=False, suggestions=2)
    assert estimate.proposal_check == checked and read.proposal_check == checked
    assert [(arm.role, arm.version_number) for arm in estimate.arms] == [
        ("candidate", None),
        ("baseline", 2),
    ]
    assert agent.current_version_id == production
    # v2 broke the Canada case on both sides; the suggestion only fixed the window.
    assert read.outcome is not None and read.outcome.baseline is not None
    assert read.outcome.baseline.version_number == 2
    assert (read.outcome.regressions_confirmed, read.outcome.fixed_confirmed) == (0, 1)


async def test_a_draft_moved_from_its_base_is_the_baseline_itself(db):
    ctx, agent, _ = await _setup(db)
    agent.draft_spec = {**agent.draft_spec, "instructions": INSTRUCTIONS + CANADA}
    await db.flush()
    await _improve(db, ctx, agent, Improver(db))
    dataset = await _shop_dataset(db, ctx)
    service = AuthoringService(db)
    body = ProposalCheck(dataset_id=dataset.id)

    estimate = await service.estimate_check(ctx, agent.id, body)
    started = await service.check(ctx, agent.id, body)
    await _finish(db, ctx, started.id)
    read = await EvalRunService(db).get(ctx, started.id)

    assert read.proposal_check == ProposalCheckRecord(
        kind="agent", base_version=1, on_draft=True, suggestions=2
    )
    # The draft runs as a second side of its own, never served from an earlier run.
    assert [(arm.role, arm.source) for arm in estimate.arms] == [
        ("candidate", "explicit"),
        ("baseline", "draft"),
    ]
    assert "cached" not in [arm.basis for arm in estimate.arms]
    assert [(arm.role, arm.source, arm.version_number) for arm in read.arms] == [
        ("candidate", "explicit", None),
        ("baseline", "draft", None),
    ]
    # The draft's own Canada rule is on both sides: only the window flipped.
    assert read.outcome is not None
    assert (read.outcome.regressions_confirmed, read.outcome.fixed_confirmed) == (0, 1)


async def test_a_check_is_the_drafts_test_once_the_draft_is_what_it_checked(db):
    ctx, agent, _ = await _setup(db)
    await _publish_held_back(db, ctx, agent)
    await _improve(db, ctx, agent, Improver(db))
    dataset = await _shop_dataset(db, ctx)
    service = AuthoringService(db)
    evals = EvalRunService(db)
    started = await service.check(ctx, agent.id, ProposalCheck(dataset_id=dataset.id))

    assert (await evals.list_for_agent(ctx, agent.id, draft="current")).items == []
    batch = (await service.for_agent(ctx, agent.id)).batch
    assert batch is not None
    for hunk in batch.hunks:
        await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
    tested = await evals.list_for_agent(ctx, agent.id, draft="current")
    assert [run.id for run in tested.items] == [started.id]
    assert (await evals.list_for_agent(ctx, agent.id, draft="earlier")).items == []

    await db.refresh(agent)
    agent.draft_spec = {**agent.draft_spec, "description": "Edited after the check"}
    await db.flush()
    assert (await evals.list_for_agent(ctx, agent.id, draft="current")).items == []
    earlier = await evals.list_for_agent(ctx, agent.id, draft="earlier")
    assert [run.id for run in earlier.items] == [started.id]


@pytest.mark.security
async def test_another_organization_reads_no_draft_test_of_this_agent(db):
    ctx, agent, _ = await _setup(db)
    await _improve(db, ctx, agent, Improver(db))
    dataset = await _shop_dataset(db, ctx)
    await AuthoringService(db).check(ctx, agent.id, ProposalCheck(dataset_id=dataset.id))
    stranger, _, _ = await _setup(db)

    for draft in ("current", "earlier"):
        with pytest.raises(NotFoundError):
            await EvalRunService(db).list_for_agent(stranger, agent.id, draft=draft)


async def test_a_check_sends_nothing_to_review_and_a_person_still_can(db):
    ctx, agent, rated = await _setup(db)
    breaking = {
        "summary": "It ships everywhere",
        "expected_effect": "Fewer orders to Canada",
        "instructions": [
            {
                "old_text": "Be brief.",
                "new_text": "Be brief." + CANADA,
                "rationale": "Readers asked",
                "evidence": [{"run_id": str(rated.id), "quote": COMMENT}],
            }
        ],
        "tools": [],
    }
    await _improve(db, ctx, agent, Improver(db, improve=breaking))
    dataset = await _shop_dataset(db, ctx)
    started = await AuthoringService(db).check(ctx, agent.id, ProposalCheck(dataset_id=dataset.id))
    await _finish(db, ctx, started.id)
    read = await EvalRunService(db).get(ctx, started.id)

    assert read.outcome is not None and read.outcome.regressions_confirmed == 1
    assert read.routed_to_review == 0
    waiting = select(func.count()).select_from(CaseScore).where(CaseScore.review_state == "pending")
    assert (await db.execute(waiting)).scalar() == 0

    candidate = next(arm for arm in read.arms if arm.role == "candidate")
    ships = await db.scalar(select(DatasetCase.case_id).where(DatasetCase.input == SHIPS))
    first = await db.scalar(
        select(EvalRunCase.case_score_id).where(
            EvalRunCase.eval_run_id == started.id,
            EvalRunCase.arm_id == candidate.id,
            EvalRunCase.attempt == 0,
            EvalRunCase.case_id == ships,
        )
    )
    assert first is not None
    sent = await ScoringService(db).request_reviews(
        ctx, dataset.id, ReviewRequest(score_ids=[first])
    )
    assert sent.queued == 1
    assert (await db.execute(waiting)).scalar() == 1


async def test_verify_reads_the_draft_against_its_base(db):
    ctx, agent, _ = await _setup(db)
    await _publish_held_back(db, ctx, agent)

    unchanged = await AuthoringService(db).estimate_agent(
        ctx, agent.id, AuthoringStart(kind="verify")
    )

    assert unchanged.reason == "no_draft_change"
