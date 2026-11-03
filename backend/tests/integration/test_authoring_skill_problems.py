"""Agent Improve reports a skill's problems for the skill and never writes the skill into the agent."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.skill import Skill
from app.repositories import skill_usage_repo
from app.schemas.skill_usage import SkillUseRecord
from tests.integration.test_authoring import COMMENT, Improver, _clerk, _improve, _rated, _setup
from tests.integration.test_authoring import _environment as _environment

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("_environment")]

RETURNS = (
    "When a customer asks to return an item, ask for the order number first. Explain that "
    "returns are accepted for ninety days from delivery, that the item must be unused, and "
    "that the refund reaches the original payment method within five working days."
)


async def _skill(db: AsyncSession, ctx: AuthContext, name: str, content: str) -> Skill:
    skill = Skill(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        name=name,
        description=f"How {name} works",
        content=content,
        visibility="org",
    )
    db.add(skill)
    await db.flush()
    return skill


async def _bound(db: AsyncSession, agent: Agent, *skills: Skill) -> None:
    agent.draft_spec = {**agent.draft_spec, "skill_ids": [str(skill.id) for skill in skills]}
    await db.flush()


def _use(skill: Skill, agent: Agent) -> SkillUseRecord:
    return SkillUseRecord(agent_id=agent.id, skill_id=skill.id, loaded=True)


def _improve_prompt(model: Improver) -> str:
    return next(prompt for prompt in model.prompts if prompt.startswith("Propose improvements"))


async def test_a_problem_is_kept_only_for_a_bound_skill_the_cited_runs_used(db: AsyncSession):
    ctx, agent, run = await _setup(db)
    returns = await _skill(db, ctx, "returns-policy", RETURNS)
    shipping = await _skill(db, ctx, "shipping", "Ship within two days.")
    await _bound(db, agent, returns, shipping)
    # A delegate opened shipping in the same run: that is the delegate's use, not the agent's.
    delegate = await _clerk(db, ctx)
    await skill_usage_repo.record_uses(
        db,
        [_use(returns, agent), _use(shipping, delegate)],
        organization_id=ctx.organization_id,
        run_id=run.id,
        started_at=run.started_at,
    )
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
