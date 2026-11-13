"""What a skill's page reads of the requests on it: quotes only for a reader of runs, from
agents they may see, and none of an Improve session's steps."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import AuthoringRequest
from app.db.models.skill import Skill
from app.repositories import skill_improvement_repo
from app.services.authoring import AuthoringService
from tests.integration.test_authoring import _member, _owner, _published
from tests.integration.test_authoring_skill_problems import _with_runs_view
from tests.integration.test_skill_bindings import _skill

pytestmark = pytest.mark.anyio


async def _run(db: AsyncSession, agent: Agent) -> AgentRun:
    run = AgentRun(
        id=uuid.uuid4(),
        organization_id=agent.organization_id,
        agent_id=agent.id,
        surface="web",
        status="completed",
        started_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return run


async def _request(
    db: AsyncSession,
    ctx: AuthContext,
    skill: Skill,
    report: dict[str, Any] | None,
    **values: Any,
) -> AuthoringRequest:
    request = AuthoringRequest(
        organization_id=ctx.organization_id,
        kind="improve",
        target="skill",
        skill_id=skill.id,
        created_by_user_id=ctx.user_id,
        status="completed",
        estimate_usd=Decimal(0),
        window_days=30,
        report=report,
        **values,
    )
    db.add(request)
    await db.flush()
    return request


def _quoted(*runs: AgentRun) -> dict[str, Any]:
    return {
        "findings": [
            {
                "title": "Refund window",
                "evidence": [{"run_id": str(run.id), "quote": f"said by {run.id}"} for run in runs],
            }
        ]
    }


class TestASkillsRequests:
    @pytest.mark.security
    async def test_a_reader_without_runs_view_reads_none_of_its_requests(self, db):
        owner = await _owner(db)
        viewer = await _member(db, owner, OrgRoleName.VIEWER)
        skill = await _skill(db, owner)
        run = await _run(db, await _published(db, owner, name="Desk", spec={"name": "Desk"}))
        await _request(db, owner, skill, _quoted(run))

        with pytest.raises(AuthorizationError, match="runs:view"):
            await AuthoringService(db).for_skill(viewer, skill.id)

    @pytest.mark.security
    async def test_a_hidden_agents_run_is_left_out_with_its_quote(self, db):
        owner = await _owner(db)
        builder = await _member(db, owner, OrgRoleName.MEMBER)
        skill = await _skill(db, owner)
        shared = await _published(db, owner, name="Desk", spec={"name": "Desk"})
        private = await _published(db, owner, name="Secret", spec={"name": "Secret"})
        private.visibility = "private"
        seen, unseen = await _run(db, shared), await _run(db, private)
        await _request(db, owner, skill, _quoted(seen, unseen))

        [as_owner] = await AuthoringService(db).for_skill(owner, skill.id)
        with _with_runs_view():
            [as_member] = await AuthoringService(db).for_skill(builder, skill.id)

        assert as_owner.report is not None and as_member.report is not None
        assert len(as_owner.report["findings"][0]["evidence"]) == 2
        assert [quote["run_id"] for quote in as_member.report["findings"][0]["evidence"]] == [
            str(seen.id)
        ]

    @pytest.mark.security
    async def test_an_improve_sessions_steps_are_read_through_the_session(self, db):
        owner = await _owner(db)
        skill = await _skill(db, owner)
        assert skill.latest_version_id is not None
        session = await skill_improvement_repo.create_run(
            db,
            organization_id=owner.organization_id,
            skill_id=skill.id,
            fork_id=None,
            base_version_id=skill.latest_version_id,
            created_by_user_id=owner.user_id,
            created_by_api_key_id=None,
            window_days=30,
            max_iterations=3,
            estimate_usd=Decimal(0),
            budget_usd=Decimal(1),
            seed=None,
        )
        run = await _run(db, await _published(db, owner, name="Desk", spec={"name": "Desk"}))
        await _request(db, owner, skill, _quoted(run), skill_improvement_run_id=session.id)
        plain = await _request(db, owner, skill, None)

        listed = await AuthoringService(db).for_skill(owner, skill.id)

        assert [read.id for read in listed] == [plain.id]
