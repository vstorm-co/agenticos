"""New skills stay projections until an authorized person accepts them."""

from dataclasses import replace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills import SkillBody, to_toolkit_skill
from app.agents.spec import AgentSpec
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import AuthoringRequest
from app.db.models.skill import Skill
from app.repositories import eval_run_repo
from app.schemas.authoring import HunkDecision, ProposalCheck, ProposedSkill
from app.schemas.eval_run import EvalRunRequest
from app.services.agent_registry import AgentRegistryService, UnpublishedCandidate
from app.services.agent_runner import AgentRunnerService
from app.services.authoring import AuthoringService
from app.services.eval_run import EvalRunService
from app.services.eval_run_worker import EvalRunWorker
from app.services.skills import SkillService
from tests.integration.test_authoring import Improver, _improve, _owner, _rated, _sessions, _setup
from tests.integration.test_authoring import _environment as _environment
from tests.integration.test_eval_suites import Model, _dataset

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]


async def _proposed(
    db: AsyncSession,
    *,
    evidence_count: int = 3,
    quote: str = "You have 90 days.",
    name: str = "return-procedure",
) -> tuple[AuthContext, Agent, AuthoringRequest]:
    ctx, agent, first = await _setup(db)
    runs = [first, await _rated(db, ctx, agent), await _rated(db, ctx, agent)]
    output = {
        "summary": "Repeated returns procedure",
        "expected_effect": "Consistent returns",
        "new_skills": [
            {
                "name": name,
                "description": "Explain the return window",
                "content": "Ask for the order. Explain the 90-day window. Confirm the next step.",
                "rationale": "The same return procedure appears in three answers.",
                "evidence": [
                    {"run_id": str(run.id), "quote": quote} for run in runs[:evidence_count]
                ],
            }
        ],
    }
    request = await _improve(db, ctx, agent, Improver(db, improve=output))
    return ctx, agent, request


async def test_three_verified_answers_produce_a_skill_proposal_and_dismiss_creates_nothing(
    db: AsyncSession,
) -> None:
    ctx, agent, request = await _proposed(db)
    assert request.status == "completed", request.error
    service = AuthoringService(db)
    read = await service.for_agent(ctx, agent.id)
    assert read.batch is not None
    [hunk] = read.batch.hunks
    assert hunk.kind == "create_skill" and len(hunk.evidence) == 3
    assert await db.scalar(select(func.count()).select_from(Skill)) == 0
    await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="dismiss"))
    assert await db.scalar(select(func.count()).select_from(Skill)) == 0
    assert AgentSpec.model_validate(agent.draft_spec).skill_ids == []


@pytest.mark.parametrize("evidence_count", [1, 2])
async def test_a_procedure_without_three_distinct_verified_answers_is_not_recorded(
    db: AsyncSession, evidence_count: int
) -> None:
    ctx, agent, request = await _proposed(db, evidence_count=evidence_count)
    assert request.report["dropped"] == {"insufficient_evidence": 1}
    read = await AuthoringService(db).for_agent(ctx, agent.id)
    assert read.batch is None or not read.batch.hunks


async def test_accept_creates_and_binds_atomically_and_undo_keeps_the_independent_skill(
    db: AsyncSession,
) -> None:
    ctx, agent, _ = await _proposed(db)
    service = AuthoringService(db)
    before = agent.current_version_id
    [hunk] = (await service.for_agent(ctx, agent.id)).batch.hunks
    decided = await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
    [skill_id] = AgentSpec.model_validate(decided.draft_spec).skill_ids
    stored = await db.get(Skill, skill_id)
    assert stored is not None and stored.name == "return-procedure"
    assert agent.current_version_id == before
    undone = await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="undo"))
    assert AgentSpec.model_validate(undone.draft_spec).skill_ids == []
    assert await db.get(Skill, skill_id) is not None
    accepted_again = await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
    assert AgentSpec.model_validate(accepted_again.draft_spec).skill_ids == [skill_id]
    assert await db.scalar(select(func.count()).select_from(Skill)) == 1


async def test_a_reader_without_skill_creation_can_read_the_proposal_but_cannot_accept_it(
    db: AsyncSession,
) -> None:
    ctx, agent, _ = await _proposed(db)
    limited = replace(
        ctx, key_scopes=frozenset({Perm.AGENTS_VIEW, Perm.AGENTS_EDIT, Perm.RUNS_VIEW})
    )
    service = AuthoringService(db)
    [hunk] = (await service.for_agent(limited, agent.id)).batch.hunks
    assert hunk.blocked == "create_skill_permission"
    with pytest.raises(AuthorizationError):
        await service.decide(limited, agent.id, hunk.id, HunkDecision(action="accept"))
    assert await db.scalar(select(func.count()).select_from(Skill)) == 0
    other = await _owner(db)
    with pytest.raises(NotFoundError):
        await service.decide(other, agent.id, hunk.id, HunkDecision(action="accept"))


async def test_eval_reads_the_projected_skill_without_creating_a_resource(db: AsyncSession) -> None:
    ctx, agent, _ = await _proposed(db)
    dataset = await _dataset(db, ctx, cases=5)
    projected_quote = await AuthoringService(db).estimate_check(
        ctx, agent.id, ProposalCheck(dataset_id=dataset.id)
    )
    ordinary_quote = await EvalRunService(db).estimate(
        ctx,
        agent.id,
        EvalRunRequest(dataset_id=dataset.id, candidate="draft", paired_baseline=True),
        candidate_spec=AgentSpec.model_validate(agent.draft_spec),
        baseline_spec=AgentSpec.model_validate(agent.draft_spec),
    )
    assert projected_quote.total_usd > ordinary_quote.total_usd
    assert projected_quote.rerun_ceiling_usd > ordinary_quote.rerun_ceiling_usd
    run = await AuthoringService(db).check(ctx, agent.id, ProposalCheck(dataset_id=dataset.id))
    candidate = next(arm for arm in run.arms if arm.role == "candidate")
    stored = await eval_run_repo.get_arm(db, candidate.id, organization_id=ctx.organization_id)
    assert stored is not None and stored.skill_bodies
    assert next(iter(stored.skill_bodies.values()))["name"] == "return-procedure"
    model = Model(db)
    projected: list[str] = []

    async def execute(
        runner: AgentRunnerService,
        actor: AuthContext,
        agent_id: UUID,
        prompt: str,
        **kwargs: object,
    ) -> tuple[str, AgentRun]:
        version = kwargs["candidate"]
        assert isinstance(version, UnpublishedCandidate)
        if version.skill_bodies:
            rows = await SkillService(db).resolve_for_agent(
                actor, version.spec.skill_ids, projected=version.skill_bodies
            )
            [skill] = rows
            assert skill.version == 1 and skill.visibility == "private"
            projected.append(
                to_toolkit_skill(skill, next(iter(version.skill_bodies.values()))).content
            )
        return await model.execute(runner, actor, agent_id, prompt, **kwargs)

    with (
        patch.object(AgentRunnerService, "execute", new=execute),
        patch("app.services.eval_run_worker.settings.EVAL_RUN_CONCURRENCY", 1),
    ):
        await EvalRunWorker(
            run.id, ctx.organization_id, sessions=_sessions(db), sleep=AsyncMock()
        ).run()
    assert projected and all("90-day window" in content for content in projected)
    assert await db.scalar(select(func.count()).select_from(Skill)) == 0
    assert AgentSpec.model_validate(agent.draft_spec).skill_ids == []


async def test_two_projected_skills_with_one_name_are_refused_before_a_run(
    db: AsyncSession,
) -> None:
    ctx, agent, _ = await _setup(db)
    first, second = uuid4(), uuid4()
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"skill_ids": [first, second]}
    )
    body = SkillBody(name="return-procedure", description="Returns", content="Check the date.")
    with pytest.raises(BadRequestError, match="Projected skills must have distinct names"):
        await AgentRegistryService(db).get_candidate_spec(
            ctx,
            agent.id,
            UnpublishedCandidate(
                spec, skill_bodies={first: body, second: replace(body, content="Other steps.")}
            ),
        )
    assert await db.scalar(select(func.count()).select_from(Skill)) == 0


@pytest.mark.parametrize(
    "quote,name,reason",
    [
        ("You said 90 days, it is 30", "return-procedure", "insufficient_evidence"),
        ("You have 90 days.", "knowledge", "invalid_config"),
    ],
)
async def test_comments_do_not_prove_a_repeated_answer_and_reserved_names_are_refused(
    db: AsyncSession, quote: str, name: str, reason: str
) -> None:
    _, _, request = await _proposed(db, quote=quote, name=name)
    assert request.report is not None
    assert request.report["dropped"] == {reason: 1}


async def test_new_skill_edits_and_a_repeated_accept_do_not_create_more_resources(
    db: AsyncSession,
) -> None:
    ctx, agent, _ = await _proposed(db)
    service = AuthoringService(db)
    read = await service.for_agent(ctx, agent.id)
    assert read.batch is not None
    [hunk] = read.batch.hunks
    with pytest.raises(BadRequestError):
        await service.decide(
            ctx, agent.id, hunk.id, HunkDecision(action="accept", text="Another procedure")
        )
    assert await db.scalar(select(func.count()).select_from(Skill)) == 0
    await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
    with pytest.raises(ConcurrentChangeError):
        await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
    await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="undo"))
    skill = await db.scalar(select(Skill))
    assert skill is not None
    skill.content = "A person changed this independently."
    await db.flush()
    with pytest.raises(ConcurrentChangeError):
        await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
    assert AgentSpec.model_validate(agent.draft_spec).skill_ids == []
    assert await db.scalar(select(func.count()).select_from(Skill)) == 1


def _idea(name: str = "return-procedure") -> ProposedSkill:
    return ProposedSkill(
        name=name,
        description="Explain the return window",
        content="Ask for the order. Explain the 90-day window. Confirm the next step.",
    )


async def test_a_person_creates_an_unrecorded_skill_idea_into_the_draft_only_once(
    db: AsyncSession,
) -> None:
    ctx, agent, request = await _proposed(db, evidence_count=2)
    [idea] = request.report["rejected"]
    assert idea["change"]["answers"] == 2 and idea["change"]["content"]
    service = AuthoringService(db)
    published = agent.current_version_id

    made = await service.create_proposed_skill(ctx, agent.id, request.id, 0, _idea("returns"))
    again = await service.create_proposed_skill(ctx, agent.id, request.id, 0, _idea("other"))

    assert again.skill_id == made.skill_id
    assert AgentSpec.model_validate(made.draft_spec).skill_ids == [made.skill_id]
    skill = await db.get(Skill, made.skill_id)
    assert skill is not None and skill.name == "returns"
    assert await db.scalar(select(func.count()).select_from(Skill)) == 1
    assert agent.current_version_id == published
    stored = await db.get(AuthoringRequest, request.id)
    assert stored.report["rejected"][0]["skill_id"] == str(made.skill_id)


async def test_creating_an_idea_is_refused_without_rights_or_outside_its_agent(
    db: AsyncSession,
) -> None:
    ctx, agent, request = await _proposed(db, evidence_count=2)
    service = AuthoringService(db)
    limited = replace(
        ctx, key_scopes=frozenset({Perm.AGENTS_VIEW, Perm.AGENTS_EDIT, Perm.RUNS_VIEW})
    )
    with pytest.raises(AuthorizationError):
        await service.create_proposed_skill(limited, agent.id, request.id, 0, _idea())
    with pytest.raises(NotFoundError):
        await service.create_proposed_skill(await _owner(db), agent.id, request.id, 0, _idea())
    other_ctx, other_agent, _ = await _setup(db)
    with pytest.raises(NotFoundError):
        await service.create_proposed_skill(other_ctx, other_agent.id, request.id, 0, _idea())
    for missing in (1, -1):
        with pytest.raises(NotFoundError):
            await service.create_proposed_skill(ctx, agent.id, request.id, missing, _idea())
    assert await db.scalar(select(func.count()).select_from(Skill)) == 0


async def test_an_idea_kept_without_its_text_asks_for_the_assistant_again(
    db: AsyncSession,
) -> None:
    ctx, agent, request = await _proposed(db, evidence_count=2)
    request.report = {
        **request.report,
        "rejected": [
            {"kind": "instructions", "reason": "unanchored", "change": {}},
            {"kind": "create_skill", "reason": "insufficient_evidence", "change": {"name": "x"}},
        ],
    }
    await db.flush()
    service = AuthoringService(db)
    with pytest.raises(NotFoundError):
        await service.create_proposed_skill(ctx, agent.id, request.id, 0, _idea())
    with pytest.raises(BadRequestError, match="Ask the assistant again"):
        await service.create_proposed_skill(ctx, agent.id, request.id, 1, _idea())
    request.report = None
    await db.flush()
    with pytest.raises(NotFoundError):
        await service.create_proposed_skill(ctx, agent.id, request.id, 0, _idea())
