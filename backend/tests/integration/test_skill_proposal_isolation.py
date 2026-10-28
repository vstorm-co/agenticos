"""Optional skill proposals cannot roll back a completed run (#2516)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.core.permissions import AuthContext
from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.organization import Organization
from app.db.models.user import User
from app.services.agent_runner import AgentRunnerService
from app.services.skill_workspace import SkillChange

pytestmark = pytest.mark.anyio


async def test_failed_proposal_flush_leaves_terminal_run_and_session_usable(db):
    user = User(id=uuid4(), email=f"{uuid4().hex}@example.com", hashed_password="x", is_active=True)
    db.add(user)
    await db.flush()
    org = Organization(
        id=uuid4(), name="Skill isolation", slug=uuid4().hex, created_by_user_id=user.id
    )
    db.add(org)
    await db.flush()
    agent = Agent(id=uuid4(), organization_id=org.id, name="Test", slug="test")
    db.add(agent)
    await db.flush()
    run = AgentRun(
        id=uuid4(), organization_id=org.id, agent_id=agent.id, status="running", input_tokens=123
    )
    db.add(run)
    await db.flush()
    run_id = run.id
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    prepared = SimpleNamespace(
        workspace=MagicMock(), materialised_skills=MagicMock(), ctx=ctx, agent=agent, run=run
    )
    # Bypass collection deliberately: a future caller can still violate the DB
    # contract, and the savepoint must protect the run independently of validation.
    invalid = SkillChange(
        name="invalid", skill_id=None, description="x" * 501, content="Body", resources={}
    )
    with patch("app.services.agent_runner.collect_changes", AsyncMock(return_value=[invalid])):
        await AgentRunnerService(db)._propose_skill_changes(prepared)
    assert db.is_active
    assert run.id == run_id
    run.status = "completed"
    await db.flush()
    stored = await db.scalar(select(AgentRun).where(AgentRun.id == run_id))
    assert stored.status == "completed" and stored.input_tokens == 123
