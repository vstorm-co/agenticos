"""The eval worker rechecks a queued knowledge check before it spends, and again as it answers.

A draft check is paid for with the starter's authority and pinned to the draft
and the collection it was quoted on. Whatever moved since - the draft, the
collection, the starter's access, the organization's consent to AI assistance or
the key it was started with - stops the check, and an answer already given keeps
nothing the withdrawn draft could have shaped.
"""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.core.permissions import ROLE_PERMS, AuthContext, OrgRoleName
from app.db.models.case_score import CaseScore
from app.db.models.eval_run import EvalRun, EvalRunCase
from app.db.models.organization import Organization, OrganizationMember
from app.repositories import eval_run_repo, knowledge_gap_repo
from app.schemas.api_key import ApiKeyCreate
from app.services.agent_registry import UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.api_key import ApiKeyService
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from app.services.knowledge_gaps import KnowledgeGapService
from app.services.notifications import NotificationService
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_authoring import _sessions
from tests.integration.test_eval_suites import Model
from tests.integration.test_improvement_knowledge import _start

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]

_NO_LONGER_RUNS = "Whoever started this eval may no longer run its agent or its dataset."
_WITHDRAWN = "The knowledge draft is no longer available"


async def _work(db: AsyncSession, ctx: AuthContext, run_id, *, during=None, fails=False) -> list:
    """Run the check to its end; `during` acts after the first answer, `fails` makes it fail."""
    model = Model(db)
    asked: list[bool] = []

    async def answer(runner, *args, **kwargs):
        candidate = kwargs["candidate"]
        assert isinstance(candidate, UnpublishedCandidate)
        asked.append(bool(candidate.context_bodies))
        _, paid = await model.execute(runner, *args, **kwargs)
        if during is not None and len(asked) == 1:
            await during()
        if fails:
            raise ModelHTTPError(503, "gpt-test")
        return ("30 days" if candidate.context_bodies else "90 days"), paid

    with (
        patch.object(AgentRunnerService, "execute", new=answer),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            run_id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    return asked


async def _stored(db: AsyncSession, run_id) -> EvalRun:
    run = await db.get(EvalRun, run_id)
    assert run is not None
    await db.refresh(run)
    return run


async def _knowledge(db: AsyncSession, run_id, **changes: Any) -> None:
    run = await _stored(db, run_id)
    record = dict(run.proposal_check or {})
    record["knowledge"] = {**record["knowledge"], **changes}
    run.proposal_check = record
    await db.flush()


async def _demote(db: AsyncSession, ctx: AuthContext) -> None:
    member = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == ctx.organization_id,
                OrganizationMember.user_id == ctx.user_id,
            )
        )
    ).scalar_one()
    member.role = OrgRoleName.VIEWER.value
    await db.flush()


async def _attempts(db: AsyncSession, run_id) -> list[EvalRunCase]:
    attempts = list(await db.scalars(select(EvalRunCase).where(EvalRunCase.eval_run_id == run_id)))
    for attempt in attempts:
        await db.refresh(attempt)
    return attempts


async def test_a_retrieval_check_whose_collection_moved_is_not_started(db: AsyncSession) -> None:
    ctx, _, _, _, child = await _start(db)
    await _knowledge(db, child.id, mode="retrieval", collection_name="kb_somewhere_else")

    assert await _work(db, ctx, child.id) == []

    run = await _stored(db, child.id)
    assert (run.status, run.error) == ("failed", _NO_LONGER_RUNS)


async def test_a_draft_edited_behind_the_check_is_not_started(db: AsyncSession) -> None:
    """Saved through anything but the service, the check was never invalidated; its pin was."""
    ctx, _, _, target, child = await _start(db)
    topic = await knowledge_gap_repo.get_topic(
        db, target.topic_id, organization_id=ctx.organization_id
    )
    assert topic is not None
    topic.draft_content = "Returns take 60 days."
    await db.flush()

    assert await _work(db, ctx, child.id) == []

    run = await _stored(db, child.id)
    assert (run.status, run.error) == ("failed", _NO_LONGER_RUNS)


@pytest.mark.security
async def test_a_starter_who_may_no_longer_edit_the_knowledge_base_does_not_start_it(
    db: AsyncSession,
) -> None:
    ctx, _, _, _, child = await _start(db)
    await _demote(db, ctx)

    assert await _work(db, ctx, child.id) == []

    run = await _stored(db, child.id)
    assert (run.status, run.error) == ("failed", _NO_LONGER_RUNS)


async def test_a_check_queued_before_ai_assistance_was_turned_off_is_not_started(
    db: AsyncSession,
) -> None:
    ctx, _, _, _, child = await _start(db)
    organization = await db.get(Organization, ctx.organization_id)
    assert organization is not None
    organization.ai_assistance_enabled = False
    await db.flush()

    assert await _work(db, ctx, child.id) == []

    run = await _stored(db, child.id)
    assert (run.status, run.error) == ("failed", _NO_LONGER_RUNS)


async def test_a_retrieval_check_stored_without_its_embedding_fails_unanswered(
    db: AsyncSession,
) -> None:
    """The candidate is never answered without the draft it is meant to search."""
    ctx, _, _, target, child = await _start(db)
    topic = await KnowledgeGapService(db)._topic(ctx, target.topic_id)
    kb = await KnowledgeGapService(db)._knowledge_base(ctx, topic.knowledge_base_id)
    await _knowledge(db, child.id, mode="retrieval", collection_name=kb.collection_name)
    asked: list[bool] = []

    async def answer(runner, *args, **kwargs):
        asked.append(bool(kwargs["candidate"].context_bodies))
        _, paid = await Model(db).execute(runner, *args, **kwargs)
        return "90 days", paid

    with (
        patch.object(AgentRunnerService, "execute", new=answer),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
        pytest.raises(BadRequestError, match="retrieval check is incomplete"),
    ):
        await EvalRunWorker(
            child.id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()

    assert True not in asked
    run = await _stored(db, child.id)
    assert run.status == "failed"
    assert run.error == "This eval stopped on an error before it finished. Run it again."


@pytest.mark.security
@pytest.mark.parametrize("fails", [False, True])
async def test_a_starter_demoted_mid_check_keeps_no_answer_and_stops_it(
    db: AsyncSession, fails: bool
) -> None:
    ctx, _, _, _, child = await _start(db)

    async def demote() -> None:
        await _demote(db, ctx)

    asked = await _work(db, ctx, child.id, during=demote, fails=fails)

    assert len(asked) == 1
    run = await _stored(db, child.id)
    assert (run.status, run.error) == ("failed", _NO_LONGER_RUNS)
    [answered] = [attempt for attempt in await _attempts(db, child.id) if attempt.ended_at]
    assert (answered.status, answered.error, answered.answer) == ("failed", _WITHDRAWN, None)
    assert answered.fault == "infrastructure"
    if not fails:
        score = await db.get(CaseScore, answered.case_score_id)
        assert score is not None and score.answer is None


@pytest.mark.security
async def test_a_key_revoked_mid_check_keeps_no_answer_and_stops_it(db: AsyncSession) -> None:
    ctx, _, _, _, child = await _start(db)
    scopes = sorted(p for p in ROLE_PERMS[OrgRoleName.OWNER] if not p.startswith("api_keys"))
    key = await ApiKeyService(db).create(ctx, ApiKeyCreate(name="ci", scopes=scopes))
    run = await _stored(db, child.id)
    run.created_by_api_key_id = key.id
    await db.flush()

    async def revoke() -> None:
        await ApiKeyService(db).revoke(ctx, key.id)

    asked = await _work(db, ctx, child.id, during=revoke)

    assert len(asked) == 1
    run = await _stored(db, child.id)
    assert (run.status, run.error) == ("failed", _NO_LONGER_RUNS)
    [answered] = [attempt for attempt in await _attempts(db, child.id) if attempt.ended_at]
    assert (answered.status, answered.error, answered.answer) == ("failed", _WITHDRAWN, None)


@pytest.mark.security
async def test_an_attempt_claimed_before_its_check_was_cancelled_leaves_the_cancellation(
    db: AsyncSession,
) -> None:
    ctx, _, _, _, child = await _start(db)
    worker = EvalRunWorker(child.id, ctx.organization_id, sessions=_sessions(db))
    working = await worker._begin()
    assert working is not None
    claimed = await eval_run_repo.claim_next(
        db, child.id, organization_id=ctx.organization_id, org_limit=10, now=datetime.now(UTC)
    )
    assert claimed is not None
    await EvalRunService(db).cancel(ctx, child.id)
    await _demote(db, ctx)

    with patch.object(NotificationService, "eval_run_finished", new=AsyncMock()) as announced:
        assert await worker._answer(working, claimed.id) is True

    run = await _stored(db, child.id)
    assert (run.status, run.error) == ("cancelled", None)
    announced.assert_not_awaited()
