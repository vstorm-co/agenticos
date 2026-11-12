"""Deleting an account clears both links on the person's runs, in either trigger order.

The erasure writes the person's runs before it deletes the account, so PostgreSQL
rechecks their foreign keys when the delete's SET NULL updates them. Which of the
account's delete actions runs first follows the RI trigger names, so each test
re-creates one constraint to force an order rather than relying on the one this
database happened to get.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.agent import Agent
from app.db.models.agent_run import AgentRun
from app.db.models.conversation import Conversation
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.user import User
from app.services.user import UserService

pytestmark = pytest.mark.anyio

# Re-creating a constraint gives its triggers a newer OID, so its action runs last.
CONVERSATIONS_LAST = (
    "ALTER TABLE conversations DROP CONSTRAINT conversations_user_id_fkey, "
    "ADD CONSTRAINT conversations_user_id_fkey FOREIGN KEY (user_id) "
    "REFERENCES users(id) ON DELETE CASCADE"
)
RUNS_LAST = (
    "ALTER TABLE agent_runs DROP CONSTRAINT agent_runs_user_id_fkey, "
    "ADD CONSTRAINT agent_runs_user_id_fkey FOREIGN KEY (user_id) "
    "REFERENCES users(id) ON DELETE SET NULL"
)


def _user() -> User:
    return User(email=f"{uuid.uuid4().hex}@example.com", hashed_password="x", is_active=True)


@pytest.mark.parametrize("reorder", [CONVERSATIONS_LAST, RUNS_LAST])
async def test_deleting_an_account_with_runs_in_its_chats_succeeds(
    db: AsyncSession, reorder: str
) -> None:
    await db.execute(text(reorder))
    owner, person = _user(), _user()
    db.add_all([owner, person])
    await db.flush()
    org = Organization(
        name="Acme",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
        is_personal=False,
        created_by_user_id=owner.id,
    )
    db.add(org)
    await db.flush()
    db.add_all(
        [
            OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"),
            OrganizationMember(organization_id=org.id, user_id=person.id, role="member"),
        ]
    )
    agent = Agent(organization_id=org.id, name="Helper", slug=f"helper-{uuid.uuid4().hex[:8]}")
    chat = Conversation(organization_id=org.id, user_id=person.id, title="Private")
    db.add_all([agent, chat])
    await db.flush()
    run = AgentRun(
        organization_id=org.id,
        agent_id=agent.id,
        started_at=datetime.now(UTC),
        user_id=person.id,
        conversation_id=chat.id,
        routine_policy={"approved_sources": []},
    )
    db.add(run)
    await db.flush()

    await UserService(db).delete(person.id)
    await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

    await db.refresh(run)
    assert run.user_id is None
    assert run.conversation_id is None
    assert await db.scalar(select(Conversation.id).where(Conversation.id == chat.id)) is None
