"""The authoring worker's two steps for a skill session, with a scripted model.

Grouping the bad answers writes the problems the session's Understand shows, quotes
checked against the runs; proposing writes edits anchored on the line's text, or
records what it could not anchor - and each wakes the session it ran for.
"""

import uuid
from dataclasses import replace
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
from app.repositories import skill_improvement_repo, skill_version_repo
from app.schemas.skill import SkillUpdate
from app.schemas.skill_version import SkillVersionCreate
from app.services.authoring import AuthoringService
from app.services.authoring_evidence import EvidencePack
from app.services.authoring_worker import AuthoringWorker
from app.services.skill_catch_up import SkillCatchUpService
from app.services.skill_improvement import SkillImprovementService
from app.services.skill_versions import SkillVersionService
from app.services.skills import SkillService
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
from tests.integration.test_skill_catch_up_session import _advance as _merge_advance
from tests.integration.test_skill_catch_up_session import (
    _described,
    _diverged,
    call_price,  # noqa: F401 - the fixture that prices a merge's conflicts call
)
from tests.integration.test_skill_catch_up_session import _started as _merge_started
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
    merged: tuple[str, ...] = ("Refunds take 30 days.\n",)

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
        if prompt.startswith("Two lines of a skill"):
            return {"texts": list(self.merged)}
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
    run.status = "stale"
    await db.flush()

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


class _FailingImprover(SkillImprover):
    """Fails the one model call whose prompt starts with `fails_on`."""

    fails_on = ""

    def _answer(self, prompt: str) -> dict[str, Any]:
        if prompt.startswith(self.fails_on):
            raise RuntimeError("The model is unavailable")
        return super()._answer(prompt)


@pytest.mark.parametrize("step", ["Group the bad answers", "Propose edits to the skill"])
@pytest.mark.parametrize("erased", [False, True])
async def test_a_failed_model_call_still_rechecks_the_evidence_it_was_given(
    db, evidence, step: str, erased: bool
):
    """A source erased while the model ran is what the step reports, not the model's failure."""
    ctx, run = await _session(db, evidence)
    request_id = run.analysis_request_id
    assert request_id is not None
    if step.startswith("Propose"):
        await _work(db, ctx, request_id)
        service = SkillImprovementService(db)
        await service.advance(run.id, ctx.organization_id)
        await db.refresh(run)
        await _continue(db, ctx, run)
        await service.advance(run.id, ctx.organization_id)
        iteration = await skill_improvement_repo.get_iteration(
            db, organization_id=ctx.organization_id, run_id=run.id, number=1
        )
        assert iteration is not None and iteration.authoring_request_id is not None
        request_id = iteration.authoring_request_id
    if erased:
        evidence["runs"] = [replace(_packed(_RUN_ID), people=frozenset({uuid.uuid4()}))]
    model = _FailingImprover(db)
    model.fails_on = step

    with _answering(model):
        await AuthoringWorker(request_id, ctx.organization_id, sessions=_sessions(db)).run()

    request = await db.get(AuthoringRequest, request_id)
    assert request is not None
    await db.refresh(request)
    assert (request.status, request.report) == ("failed", None)
    assert request.error == (
        "An evidence source was erased while the assistant worked. Start again with current "
        "evidence."
        if erased
        else "The assistant stopped unexpectedly. Try again."
    )


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


async def _fork_latest(db: AsyncSession, ctx: AuthContext, skill: Skill, fork_id: uuid.UUID):
    fork = await skill_version_repo.get_fork(
        db, fork_id, organization_id=ctx.organization_id, skill_id=skill.id
    )
    assert fork is not None and fork.latest_version_id is not None
    return fork.latest_version_id


async def _merging(db: AsyncSession) -> tuple[AuthContext, SkillImprovementRun]:
    """A catch-up whose one conflict waits for the model's text."""
    ctx = await _owner(db)
    await _improver(db, ctx)
    skill, fork = await _diverged(db, ctx, conflict=True)
    run = await _merge_started(db, ctx, skill, fork)
    await _merge_advance(db, run)
    await _merge_advance(db, run)
    return ctx, run


async def _merge_request(db: AsyncSession, run: SkillImprovementRun) -> uuid.UUID:
    iteration = await skill_improvement_repo.get_iteration(
        db, organization_id=run.organization_id, run_id=run.id, number=1
    )
    assert iteration is not None and iteration.authoring_request_id is not None
    return iteration.authoring_request_id


@pytest.mark.usefixtures("call_price")
async def test_a_merges_conflicts_take_the_models_texts_and_wake_the_session(db):
    ctx, run = await _merging(db)

    request = await _work(db, ctx, await _merge_request(db, run))

    merge = await SkillCatchUpService(db).merge_for_run(run.id, organization_id=ctx.organization_id)
    assert merge is not None
    merged = await SkillCatchUpService(db).candidate_of(merge)
    assert (request.status, request.report) == ("completed", {"proposed": 1})
    assert merged is not None and merged.content.startswith("Refunds take 30 days.\n")
    assert await _wakes(db, run) >= 1


@pytest.mark.usefixtures("call_price")
async def test_an_answer_for_another_number_of_conflicts_leaves_them_to_a_person(db):
    ctx, run = await _merging(db)
    model_texts = ("One.\n", "Two.\n")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SkillImprover, "merged", model_texts)
        request = await _work(db, ctx, await _merge_request(db, run))

    merge = await SkillCatchUpService(db).merge_for_run(run.id, organization_id=ctx.organization_id)
    assert merge is not None and merge.unresolved == 1
    assert (request.status, request.error) == (
        "failed",
        "The assistant did not answer every conflict; settle them at Changes.",
    )


@pytest.mark.usefixtures("call_price")
async def test_a_session_a_person_took_over_keeps_their_conflicts(db):
    ctx, run = await _merging(db)
    run.stage = "filtering"
    await db.flush()

    request = await _work(db, ctx, await _merge_request(db, run))

    merge = await SkillCatchUpService(db).merge_for_run(run.id, organization_id=ctx.organization_id)
    assert merge is not None and merge.unresolved == 1
    assert (request.status, request.error) == ("failed", "The improvement session moved on.")


@pytest.mark.usefixtures("call_price")
async def test_a_description_past_its_limit_is_left_to_a_person_and_the_rest_is_kept(db):
    ctx = await _owner(db)
    await _improver(db, ctx)
    skill, fork = await _described(db, ctx)
    await SkillVersionService(db).edit(
        ctx,
        skill.id,
        SkillVersionCreate(
            fork_id=fork.id,
            base_version_id=(await _fork_latest(db, ctx, skill, fork.id)),
            description="How refunds and returns work.",
            content=_BODY.replace("14 days", "30 days"),
        ),
    )
    await SkillService(db).update(
        ctx, skill.id, SkillUpdate(content=_BODY.replace("14 days", "21 days"))
    )
    run = await _merge_started(db, ctx, skill, fork)
    await _merge_advance(db, run)
    await _merge_advance(db, run)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(SkillImprover, "merged", ("x" * 600, "Refunds take 30 days.\n"))
        request = await _work(db, ctx, await _merge_request(db, run))
    await _merge_advance(db, run)

    merge = await SkillCatchUpService(db).merge_for_run(run.id, organization_id=ctx.organization_id)
    assert merge is not None and request.status == "completed"
    assert (merge.description["result"], merge.unresolved) == (None, 1)
    assert [part["result"] for part in merge.parts if part["state"] == "conflict"] == [
        "Refunds take 30 days.\n"
    ]
    assert (run.status, run.stage) == ("waiting", "filtering")
