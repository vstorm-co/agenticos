"""Agent Improve reports a skill's problems for the skill and never writes the skill into the agent."""

import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.agents.system_agents import IMPROVER
from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.resource_grant import GrantLevel, ResourceGrant, Visibility
from app.db.models.skill import Skill
from app.repositories import authoring_repo, skill_usage_repo
from app.schemas.authoring import AuthoringStart, IdeaDecision
from app.schemas.skill import SkillUpdate
from app.schemas.skill_usage import SkillUseRecord
from app.services.authoring import AuthoringService
from app.services.skills import SKILL_BODY_CHARS, SkillService
from tests.integration.test_authoring import (
    COMMENT,
    Improver,
    _clerk,
    _improve,
    _member,
    _owner,
    _published,
    _rated,
    _setup,
)
from tests.integration.test_authoring import _environment as _environment

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]

RETURNS = (
    "When a customer asks to return an item, ask for the order number first. Explain that "
    "returns are accepted for ninety days from delivery, that the item must be unused, and "
    "that the refund reaches the original payment method within five working days."
)


async def _skill(db: AsyncSession, ctx: AuthContext, name: str, content: str) -> Skill:
    return await SkillService(db).create(
        ctx, name=name, description=f"How {name} works", content=content, visibility=Visibility.ORG
    )


async def _bound(db: AsyncSession, agent: Agent, *skills: Skill) -> None:
    agent.draft_spec = {**agent.draft_spec, "skill_ids": [str(skill.id) for skill in skills]}
    await db.flush()


def _use(skill: Skill, agent: Agent, version_id: uuid.UUID | None = None) -> SkillUseRecord:
    return SkillUseRecord(
        agent_id=agent.id,
        skill_id=skill.id,
        skill_version_id=version_id or skill.latest_version_id,
        loaded=True,
    )


async def _used(db: AsyncSession, ctx: AuthContext, run: AgentRun, *uses: SkillUseRecord) -> None:
    await skill_usage_repo.record_uses(
        db,
        list(uses),
        organization_id=ctx.organization_id,
        run_id=run.id,
        started_at=run.started_at,
    )


def _improve_prompt(model: Improver) -> str:
    return next(prompt for prompt in model.prompts if prompt.startswith("Propose improvements"))


async def test_a_problem_is_kept_only_for_a_bound_skill_the_cited_runs_used(db: AsyncSession):
    ctx, agent, run = await _setup(db)
    returns = await _skill(db, ctx, "returns-policy", RETURNS)
    shipping = await _skill(db, ctx, "shipping", "Ship within two days.")
    await _bound(db, agent, returns, shipping)
    # A delegate opened shipping in the same run: that is the delegate's use, not the agent's.
    delegate = await _clerk(db, ctx)
    await _used(db, ctx, run, _use(returns, agent), _use(shipping, delegate))
    cited = [{"run_id": str(run.id), "quote": COMMENT}]
    model = Improver(
        db,
        improve={
            "summary": "The returns skill states the wrong window",
            "expected_effect": "Answers say 30 days",
            "skill_problems": [
                {"skill": "Returns-Policy", "problem": "It says ninety days", "evidence": cited},
                {"skill": "no-such-skill", "problem": "Missing", "evidence": cited},
                {"skill": "shipping", "problem": "Never opened", "evidence": cited},
                {
                    "skill": "returns-policy",
                    "problem": "Unquoted",
                    "evidence": [{"run_id": str(run.id), "quote": "Nobody wrote this"}],
                },
            ],
        },
    )

    request = await _improve(db, ctx, agent, model)

    assert request.status == "completed", request.error
    [problem] = request.report["skill_problems"]
    assert (problem["skill_id"], problem["skill_name"]) == (str(returns.id), "returns-policy")
    assert problem["problem"] == "It says ninety days"
    assert [item["quote"] for item in problem["evidence"]] == [COMMENT]
    assert request.report["dropped"] == {
        "unknown_skill": 1,
        "skill_not_used": 1,
        "insufficient_evidence": 1,
    }
    prompt = _improve_prompt(model)
    assert "- returns-policy (main): How returns-policy works" in prompt
    assert '<skill name="returns-policy">' in prompt and RETURNS in prompt
    assert "- shipping (main)" in prompt and '<skill name="shipping">' not in prompt


async def test_instructions_that_copy_a_skill_and_a_new_skill_that_repeats_one_are_refused(
    db: AsyncSession,
):
    ctx, agent, first = await _setup(db)
    returns = await _skill(db, ctx, "returns-policy", RETURNS)
    await _bound(db, agent, returns)
    runs = [first, await _rated(db, ctx, agent), await _rated(db, ctx, agent)]
    answered = [{"run_id": str(run.id), "quote": "You have 90 days."} for run in runs]
    model = Improver(
        db,
        improve={
            "summary": "Returns are explained badly",
            "expected_effect": "Answers explain returns",
            "instructions": [
                {
                    "old_text": "",
                    "new_text": f"\n{RETURNS.upper()}",
                    "rationale": "Readers asked how returns work",
                    "evidence": [{"run_id": str(first.id), "quote": COMMENT}],
                },
                {
                    "old_text": "Be brief.",
                    "new_text": "Be brief. Refunds are accepted for 30 days.",
                    "rationale": "Three readers corrected the window",
                    "evidence": [{"run_id": str(first.id), "quote": COMMENT}],
                },
            ],
            "new_skills": [
                {
                    "name": "returns-policy",
                    "description": "Returns",
                    "content": "Ask for the order and name the window.",
                    "rationale": "Repeated in three answers",
                    "evidence": answered,
                },
                {
                    "name": "return-steps",
                    "description": "Returns, step by step",
                    "content": RETURNS,
                    "rationale": "Repeated in three answers",
                    "evidence": answered,
                },
            ],
        },
    )

    request = await _improve(db, ctx, agent, model)

    assert request.status == "completed", request.error
    assert request.report["dropped"] == {"copies_skill": 1, "duplicates_skill": 2}
    assert request.report["recorded"] == 1
    assert request.report["skill_problems"] == []


async def test_a_problem_keeps_only_the_quotes_of_runs_that_used_the_skill(db: AsyncSession):
    ctx, agent, run = await _setup(db)
    returns = await _skill(db, ctx, "returns-policy", RETURNS)
    await _bound(db, agent, returns)
    await _used(db, ctx, run, _use(returns, agent))
    other = await _rated(db, ctx, agent, comment="Where is my parcel")
    model = Improver(
        db,
        improve={
            "summary": "The returns skill states the wrong window",
            "expected_effect": "Answers say 30 days",
            "skill_problems": [
                {
                    "skill": "returns-policy",
                    "problem": "It says ninety days",
                    "evidence": [
                        {"run_id": str(run.id), "quote": COMMENT},
                        {"run_id": str(other.id), "quote": "Where is my parcel"},
                    ],
                },
            ],
        },
    )

    request = await _improve(db, ctx, agent, model)

    [problem] = request.report["skill_problems"]
    assert [item["run_id"] for item in problem["evidence"]] == [str(run.id)]
    assert problem["evidence_dropped"] == 1


async def test_a_run_served_another_version_of_the_skill_is_not_its_evidence(db: AsyncSession):
    ctx, agent, run = await _setup(db)
    returns = await _skill(db, ctx, "returns-policy", RETURNS)
    older = returns.latest_version_id
    await SkillService(db).update(ctx, returns.id, SkillUpdate(content="Returns: thirty days."))
    await _bound(db, agent, returns)
    await _used(db, ctx, run, _use(returns, agent, older))
    cited = [{"run_id": str(run.id), "quote": COMMENT}]
    model = Improver(
        db,
        improve={
            "summary": "The returns skill states the wrong window",
            "expected_effect": "Answers say 30 days",
            "skill_problems": [
                {"skill": "returns-policy", "problem": "It says ninety days", "evidence": cited}
            ],
        },
    )

    request = await _improve(db, ctx, agent, model)

    assert request.report["skill_problems"] == []
    assert request.report["dropped"] == {"skill_not_used": 1}
    assert '<skill name="returns-policy">' not in _improve_prompt(model)


@pytest.mark.security
async def test_a_reader_without_runs_view_reads_no_skill_problem(
    db: AsyncSession,
):
    ctx, agent, run = await _setup(db)
    returns = await _skill(db, ctx, "returns-policy", RETURNS)
    await _bound(db, agent, returns)
    await _used(db, ctx, run, _use(returns, agent))
    cited = [{"run_id": str(run.id), "quote": COMMENT}]
    model = Improver(
        db,
        improve={
            "summary": "The returns skill states the wrong window",
            "expected_effect": "Answers say 30 days",
            "skill_problems": [
                {"skill": "returns-policy", "problem": "It says ninety days", "evidence": cited}
            ],
        },
    )
    await _improve(db, ctx, agent, model)

    member = await _member(db, ctx, OrgRoleName.MEMBER)
    with pytest.raises(AuthorizationError, match="runs:view"):
        await AuthoringService(db).for_agent(member, agent.id)
    shown = (await AuthoringService(db).for_agent(ctx, agent.id)).latest

    assert shown is not None and shown.report is not None
    assert shown.report["skill_problems"][0]["evidence"][0]["quote"] == COMMENT


@pytest.mark.security
async def test_a_reader_who_may_not_see_a_skill_reads_nothing_the_improver_drew_from_it(
    db: AsyncSession,
):
    ctx, agent, first = await _setup(db)
    returns = await SkillService(db).create(
        ctx,
        name="returns-policy",
        description="How returns work",
        content=RETURNS,
        visibility=Visibility.PRIVATE,
    )
    await _bound(db, agent, returns)
    await _used(db, ctx, first, _use(returns, agent))
    runs = [first, await _rated(db, ctx, agent), await _rated(db, ctx, agent)]
    answered = [{"run_id": str(run.id), "quote": "You have 90 days."} for run in runs]
    cited = [{"run_id": str(first.id), "quote": COMMENT}]
    model = Improver(
        db,
        improve={
            "summary": "The returns skill states the wrong window",
            "expected_effect": "Answers say 30 days",
            "instructions": [
                {
                    "old_text": "",
                    "new_text": f"\n{RETURNS.upper()}",
                    "rationale": "Readers asked how returns work",
                    "evidence": cited,
                }
            ],
            "new_skills": [
                {
                    "name": "return-steps",
                    "description": "Returns, step by step",
                    "content": RETURNS,
                    "rationale": "Repeated in three answers",
                    "evidence": answered,
                }
            ],
            "skill_problems": [
                {"skill": "returns-policy", "problem": "It says ninety days", "evidence": cited},
                {"skill": "gift-wrap", "problem": "It wraps nothing", "evidence": cited},
            ],
        },
    )
    request = await _improve(db, ctx, agent, model)
    member = await _member(db, ctx, OrgRoleName.MEMBER)
    db.add(
        ResourceGrant(
            organization_id=ctx.organization_id,
            subject_user_id=member.user_id,
            resource_type="agent",
            resource_id=agent.id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()

    with _with_runs_view():
        hidden = (await AuthoringService(db).for_agent(member, agent.id)).latest
    shown = (await AuthoringService(db).for_agent(ctx, agent.id)).latest

    assert hidden is not None and hidden.report is not None
    assert hidden.report["skill_problems"] == []
    assert len(hidden.report["rejected"]) == 3
    assert all(item["change"] == {} for item in hidden.report["rejected"])
    assert RETURNS not in str(hidden.report) and "ninety" not in str(hidden.report)
    assert shown is not None and shown.report is not None
    assert [item["skill_name"] for item in shown.report["skill_problems"]] == ["returns-policy"]
    assert all(item["change"] for item in shown.report["rejected"])
    idea = next(
        index
        for index, item in enumerate(request.report["rejected"])
        if item["kind"] == "create_skill"
    )
    with _with_runs_view(), pytest.raises(NotFoundError):
        await AuthoringService(db).decide_idea(
            member, agent.id, request.id, idea, IdeaDecision(action="dismiss")
        )
    verify = await authoring_repo.create_request(
        db,
        organization_id=ctx.organization_id,
        kind="verify",
        target="agent",
        agent_id=agent.id,
        skill_id=None,
        created_by_user_id=ctx.user_id,
        estimate_usd=Decimal("0.01"),
        window_days=30,
    )
    verify.status = "completed"
    verify.report = {"findings": [], "proposed": 0, "recorded": 0}
    await db.flush()
    with _with_runs_view():
        checked = (await AuthoringService(db).for_agent(member, agent.id)).verify
    assert checked is not None and checked.report == verify.report


def _with_runs_view():
    """The caller's role, plus `runs:view` - so only a skill's own access can hide it."""
    held = AuthContext.has

    def has(ctx: AuthContext, perm: Perm) -> bool:
        return perm == Perm.RUNS_VIEW or held(ctx, perm)

    return patch.object(AuthContext, "has", has)


async def test_the_improver_reads_no_skill_the_person_who_started_it_may_not_see(
    db: AsyncSession,
):
    ctx, agent, run = await _setup(db)
    returns = await SkillService(db).create(
        ctx,
        name="returns-policy",
        description="How returns work",
        content=RETURNS,
        visibility=Visibility.PRIVATE,
    )
    await _bound(db, agent, returns)
    await _used(db, ctx, run, _use(returns, agent))
    member = await _member(db, ctx, OrgRoleName.MEMBER)
    db.add(
        ResourceGrant(
            organization_id=ctx.organization_id,
            subject_user_id=member.user_id,
            resource_type="agent",
            resource_id=agent.id,
            level=GrantLevel.EDIT.value,
        )
    )
    await db.flush()
    spec = AgentSpec.model_validate(agent.draft_spec)

    skills, _ = await SkillService(db).read_by_improver(member, agent.id, spec, [run.id])
    owners, _ = await SkillService(db).read_by_improver(ctx, agent.id, spec, [run.id])

    assert skills == []
    assert [skill.id for skill in owners] == [returns.id]


async def test_the_estimate_prices_the_skill_bodies_the_improver_will_read(db: AsyncSession):
    ctx = await _owner(db)
    await _published(
        db,
        ctx,
        name="Authoring assistant",
        spec={"name": "Authoring assistant", "model_profile_id": str(uuid.uuid4())},
        kind="improver",
        system_key=IMPROVER.key,
    )
    agent = await _clerk(db, ctx)
    run = await _rated(db, ctx, agent)
    returns = await _skill(db, ctx, "returns-policy", RETURNS * 40)
    await _bound(db, agent, returns)
    service = AuthoringService(db)

    with patch(
        "app.services.authoring.price_request",
        side_effect=lambda usage, *_: usage.input_tokens / 10_000,
    ):
        unused = await service.estimate_agent(ctx, agent.id, AuthoringStart())
        await _used(db, ctx, run, _use(returns, agent))
        read = await service.estimate_agent(ctx, agent.id, AuthoringStart())

    assert float(read.estimate_usd - unused.estimate_usd) == pytest.approx(
        SKILL_BODY_CHARS / 4 / 10_000, abs=0.011
    )
