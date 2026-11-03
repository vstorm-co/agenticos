"""The authoring worker's two steps for a skill session, with a scripted model.

Grouping the bad answers writes the problems the session's Understand shows, quotes
checked against the runs; proposing writes edits anchored on the line's text, or
records what it could not anchor - and each wakes the session it ran for.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.authoring import AuthoringRequest, SpecProposalBatch, SpecProposalHunk
from app.db.models.background_job import BackgroundJob
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill
from app.db.models.skill_improvement import SkillImprovementRun
from app.repositories import skill_improvement_repo
from app.services.authoring import AuthoringService
from app.services.authoring_evidence import EvidencePack
from app.services.authoring_worker import AuthoringWorker
from app.services.skill_improvement import SkillImprovementService
from tests.integration.test_authoring import (
    Improver,
    _answering,
    _environment,  # noqa: F401 - the autouse fixture that scripts the improver's model
    _improver,
    _member,
    _owner,
    _sessions,
)
from tests.integration.test_skill_bindings import _fork
from tests.integration.test_skill_improvement import (
    _BODY,
    _continue,
    _packed,
    _skill_on_main,
    _start,
    fixed_evidence,
)

pytestmark = pytest.mark.anyio

_RUN_ID = uuid.uuid4()


@pytest.fixture
def evidence(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return fixed_evidence(monkeypatch)


_QUOTE = "Wrong: refunds take 30 days"


class SkillImprover(Improver):
    """Answers a skill session's analysis and proposal."""

    describes = True

    def _answer(self, prompt: str) -> dict[str, Any]:
        if prompt.startswith("Group the bad answers"):
            return {
                "problems": [
                    {
                        "title": "Wrong refund window",
                        "summary": "The skill says 14 days.",
                        "cause": "skill",
                        "run_ids": [str(_RUN_ID), str(uuid.uuid4())],
                        "evidence": [
                            {"run_id": str(_RUN_ID), "quote": "Refunds take 14 days."},
                            {"run_id": str(_RUN_ID), "quote": "Never said"},
                        ],
                    }
                ]
            }
        if prompt.startswith("Propose edits to the skill"):
            return {
                "summary": "Name the 30-day window",
                "expected_effect": "Answers say 30 days",
                "edits": [
                    {
                        "old_text": "Refunds take 14 days.",
                        "new_text": "Refunds take 30 days.",
                        "rationale": "Readers corrected it",
                        "evidence": [{"run_id": str(_RUN_ID), "quote": _QUOTE}],
                    },
                    {"old_text": "Not in the body.", "new_text": "x", "rationale": "x"},
                ],
                "description": "How refunds and returns work." if self.describes else None,
                "description_rationale": "Opened for returns too",
            }
        return super()._answer(prompt)


async def _session(db: AsyncSession, evidence: dict[str, Any]) -> tuple[AuthContext, Any]:
    ctx = await _owner(db)
    await _improver(db, ctx)
    evidence["runs"] = [_packed(_RUN_ID)]
    skill = await _skill_on_main(db, ctx)
    read = await SkillImprovementService(db).start(ctx, skill.id, _start())
    await SkillImprovementService(db).advance(read.id, ctx.organization_id)
    run = await db.get(SkillImprovementRun, read.id)
    assert run is not None
    await db.refresh(run)
    return ctx, run


async def _work(
    db: AsyncSession, ctx: AuthContext, request_id: uuid.UUID, *, describes: bool = True
) -> AuthoringRequest:
    model = SkillImprover(db)
    model.describes = describes
    with _answering(model):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()
    request = await db.get(AuthoringRequest, request_id)
    assert request is not None
    await db.refresh(request)
    return request


async def _wakes(db: AsyncSession, run: SkillImprovementRun) -> int:
    rows = await db.scalars(
        select(BackgroundJob).where(
            BackgroundJob.kind == "advance-skill-improvement",
            BackgroundJob.organization_id == run.organization_id,
        )
    )
    return len([row for row in rows if row.payload.get("run_id") == str(run.id)])


async def test_the_analysis_writes_problems_with_checked_quotes_and_wakes_the_session(db, evidence):
    ctx, run = await _session(db, evidence)
    assert run.analysis_request_id is not None

    request = await _work(db, ctx, run.analysis_request_id)

    [problem] = request.report["problems"]
    assert request.status == "completed"
    assert (problem["cause"], problem["run_ids"]) == ("skill", [str(_RUN_ID)])
    assert [quote["quote"] for quote in problem["evidence"]] == ["Refunds take 14 days."]
    assert request.report["usage_unknown"] == 2
    assert await _wakes(db, run) >= 1

    await SkillImprovementService(db).advance(run.id, ctx.organization_id)
    await db.refresh(run)
    assert (run.status, run.stage) == ("waiting", "classifying")


async def test_the_proposal_anchors_its_edits_and_records_the_ones_it_cannot(db, evidence):
    ctx, run = await _session(db, evidence)
    assert run.analysis_request_id is not None
    await _work(db, ctx, run.analysis_request_id)
    service = SkillImprovementService(db)
    await service.advance(run.id, ctx.organization_id)
    await db.refresh(run)
    await _continue(db, ctx, run)
    await service.advance(run.id, ctx.organization_id)
    iteration = await skill_improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=run.id, number=1
    )
    assert iteration is not None and iteration.authoring_request_id is not None

    request = await _work(db, ctx, iteration.authoring_request_id)
    batch = (
        await db.scalars(
            select(SpecProposalBatch).where(SpecProposalBatch.request_id == request.id)
        )
    ).one()
    hunks = list(
        await db.scalars(select(SpecProposalHunk).where(SpecProposalHunk.batch_id == batch.id))
    )

    assert (request.report["proposed"], request.report["recorded"]) == (3, 2)
    assert (batch.agent_id, batch.skill_id, batch.status) == (None, run.skill_id, "candidate")
    assert sorted(hunk.kind for hunk in hunks) == ["skill_body", "skill_description"]
    body = next(hunk for hunk in hunks if hunk.kind == "skill_body")
    assert body.old_text in _BODY and [item["quote"] for item in body.evidence] == [_QUOTE]

    await service.advance(run.id, ctx.organization_id)
    await service.advance(run.id, ctx.organization_id)
    await db.refresh(run)
    assert (run.status, run.stage) == ("waiting", "filtering")


async def test_a_step_for_a_session_that_ended_or_a_skill_its_starter_cannot_edit_fails(
    db, evidence
):
    ctx, run = await _session(db, evidence)
    assert run.analysis_request_id is not None
    await SkillImprovementService(db).cancel(ctx, run.skill_id, run.id)

    request = await _work(db, ctx, run.analysis_request_id)

    assert (request.status, request.error) == ("failed", "The improvement session stopped.")

    other_ctx, other = await _session(db, evidence)
    assert other.analysis_request_id is not None
    skill = await db.get(Skill, other.skill_id)
    assert skill is not None
    skill.visibility = Visibility.PRIVATE.value
    builder = await _member(db, other_ctx, OrgRoleName.BUILDER)
    analysis = await db.get(AuthoringRequest, other.analysis_request_id)
    assert analysis is not None
    analysis.created_by_user_id = builder.user_id
    await db.flush()

    failed = await _work(db, other_ctx, other.analysis_request_id)

    assert (failed.status, failed.error) == (
        "failed",
        "Whoever started this may no longer edit the skill.",
    )


async def test_a_proposal_that_keeps_the_description_proposes_only_body_edits(db, evidence):
    ctx, run = await _session(db, evidence)
    assert run.analysis_request_id is not None
    await _work(db, ctx, run.analysis_request_id)
    service = SkillImprovementService(db)
    await service.advance(run.id, ctx.organization_id)
    await db.refresh(run)
    await _continue(db, ctx, run)
    await service.advance(run.id, ctx.organization_id)
    iteration = await skill_improvement_repo.get_iteration(
        db, organization_id=ctx.organization_id, run_id=run.id, number=1
    )
    assert iteration is not None and iteration.authoring_request_id is not None

    request = await _work(db, ctx, iteration.authoring_request_id, describes=False)

    assert (request.report["proposed"], request.report["recorded"]) == (2, 1)


async def test_reading_a_lines_evidence_is_priced_like_any_improve(db):
    ctx = await _owner(db)
    await _improver(db, ctx)

    priced = await AuthoringService(db).estimate_pack(ctx, EvidencePack())

    assert (priced.runs, priced.reason) == (0, "no_evidence")


async def test_the_analysis_reads_what_a_handing_agents_improve_found(db, evidence):
    ctx, run = await _session(db, evidence)
    assert run.analysis_request_id is not None
    run.seed = {"problems": ["The window is wrong"], "quotes": []}
    await db.flush()
    model = SkillImprover(db)

    with _answering(model):
        await AuthoringWorker(
            run.analysis_request_id, ctx.organization_id, sessions=_sessions(db)
        ).run()

    [analysis] = [prompt for prompt in model.prompts if prompt.startswith("Group the bad answers")]
    assert "# What an agent's own Improve found in this skill" in analysis
    assert "- The window is wrong" in analysis and "(none)" in analysis


async def test_a_fork_sessions_analysis_reads_the_forks_own_text(db, evidence):
    ctx = await _owner(db)
    await _improver(db, ctx)
    evidence["runs"] = [_packed(_RUN_ID)]
    skill = await _skill_on_main(db, ctx)
    fork = await _fork(db, ctx, skill, "Returns are free within 60 days.")
    service = SkillImprovementService(db)
    read = await service.start(ctx, skill.id, _start(fork_id=fork.id))
    await service.advance(read.id, ctx.organization_id)
    run = await db.get(SkillImprovementRun, read.id)
    assert run is not None and run.analysis_request_id is not None
    model = SkillImprover(db)

    with _answering(model):
        await AuthoringWorker(
            run.analysis_request_id, ctx.organization_id, sessions=_sessions(db)
        ).run()

    [analysis] = [prompt for prompt in model.prompts if prompt.startswith("Group the bad answers")]
    assert "Returns are free within 60 days." in analysis and _BODY not in analysis
    assert "(returns)" in analysis
