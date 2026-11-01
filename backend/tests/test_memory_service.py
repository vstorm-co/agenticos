"""Tests for the memory erasure service.

Erasure is the whole of what a person does to memory directly, so this file is
almost entirely refusals: who may erase whom, and what a "forgotten" answer is
allowed to claim.

Native memory is the only store, so one delete is the whole erasure (#2090).
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.memory_keys import person_owner_key
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.services.memory import MemoryService

pytestmark = pytest.mark.anyio

FACADE = "app.services.memory.facade"
CLAIMS = "app.repositories.memory_claim"
REPO = "app.repositories.memory"
ORG = uuid.uuid4()
PERSON = uuid.uuid4()
ADMIN = uuid.uuid4()


def _ctx(user_id: uuid.UUID, *, role: OrgRoleName = OrgRoleName.MEMBER) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=ORG, role=role)


def _agent():
    agent = MagicMock()
    agent.id = uuid.uuid4()
    return agent


def _service() -> MemoryService:
    return MemoryService(MagicMock())


class TestForgettingAPerson:
    async def test_anybody_may_erase_themselves(self):
        service = _service()
        with (
            patch(f"{REPO}.delete_for_person", new=AsyncMock(return_value=3)),
            patch(f"{CLAIMS}.delete_for_scope", new=AsyncMock(return_value=0)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            result = await service.forget_person(_ctx(PERSON), PERSON)

        assert result.notes_deleted == 3

    async def test_erasing_somebody_else_needs_members_manage(self):
        """Deliberately not an agent permission. This is about a human being, and
        somebody who may edit one agent should not thereby be able to reach into
        what every other agent learned about a colleague."""
        service = _service()
        with (
            patch(f"{REPO}.delete_for_person", new=AsyncMock()) as deleted,
            patch(f"{CLAIMS}.delete_for_scope", new=AsyncMock(return_value=0)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
            pytest.raises(AuthorizationError),
        ):
            await service.forget_person(_ctx(ADMIN), PERSON)

        assert not deleted.await_count

    async def test_a_member_manager_may_erase_a_colleague(self):
        service = _service()
        ctx = _ctx(ADMIN, role=OrgRoleName.ADMIN)
        assert ctx.has(Perm.MEMBERS_MANAGE), "the fixture must actually hold it"

        with (
            patch(f"{REPO}.delete_for_person", new=AsyncMock(return_value=1)) as deleted,
            patch(f"{CLAIMS}.delete_for_scope", new=AsyncMock(return_value=0)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            await service.forget_person(ctx, PERSON)

        assert deleted.await_args.kwargs["owner_key"] == person_owner_key(PERSON)

    async def test_it_erases_one_person_and_never_a_room(self):
        """A room's notes are a colleague's as much as they are this person's, so
        "forget me" must not empty a channel. The repository asserts the prefix;
        this is the caller half of the same rule."""
        service = _service()
        with (
            patch(f"{REPO}.delete_for_person", new=AsyncMock(return_value=0)) as deleted,
            patch(f"{CLAIMS}.delete_for_scope", new=AsyncMock(return_value=0)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            await service.forget_person(_ctx(PERSON), PERSON)

        assert deleted.await_args.kwargs["owner_key"].startswith("person:")

    async def test_it_is_recorded_in_the_audit_log(self):
        """A deletion nobody can evidence is a deletion nobody can prove happened,
        which is the whole point of asking for one."""
        service = _service()
        with (
            patch(f"{REPO}.delete_for_person", new=AsyncMock(return_value=2)),
            patch(f"{CLAIMS}.delete_for_scope", new=AsyncMock(return_value=0)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.forget_person(_ctx(PERSON), PERSON)

        assert audit.await_args.kwargs["action"] == "memory.person.forgotten"
        assert audit.await_args.kwargs["target_id"] == str(PERSON)
        assert audit.await_args.kwargs["details"]["notes"] == 2


class TestClearingOneAgent:
    async def test_it_deletes_every_note_that_agent_holds(self):
        service = _service()
        agent = _agent()
        with (
            patch(f"{FACADE}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{FACADE}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{REPO}.delete_all_for_agent", new=AsyncMock(return_value=7)) as deleted,
            patch(f"{CLAIMS}.delete_for_agent", new=AsyncMock(return_value=0)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()) as audit,
        ):
            result = await service.clear_agent(_ctx(PERSON), agent.id)

        assert result.notes_deleted == 7
        assert deleted.await_args.kwargs["agent_id"] == agent.id
        assert audit.await_args.kwargs["action"] == "memory.agent.cleared"

    async def test_an_agent_in_another_organization_is_not_found(self):
        service = _service()
        with (
            patch(f"{FACADE}.agent_repo.get", new=AsyncMock(return_value=None)),
            patch(f"{REPO}.delete_all_for_agent", new=AsyncMock()) as deleted,
            patch(f"{CLAIMS}.delete_for_agent", new=AsyncMock(return_value=0)),
            pytest.raises(NotFoundError),
        ):
            await service.clear_agent(_ctx(PERSON), uuid.uuid4())

        assert not deleted.await_count

    async def test_a_caller_who_may_not_edit_the_agent_is_told_it_does_not_exist(self):
        """Whether an agent exists is itself something a caller may not learn, so
        the denial and the miss are the same answer."""
        service = _service()
        with (
            patch(f"{FACADE}.agent_repo.get", new=AsyncMock(return_value=_agent())),
            patch(f"{FACADE}.resolve_access", new=AsyncMock(return_value=False)),
            patch(f"{REPO}.delete_all_for_agent", new=AsyncMock()) as deleted,
            patch(f"{CLAIMS}.delete_for_agent", new=AsyncMock(return_value=0)),
            pytest.raises(NotFoundError),
        ):
            await service.clear_agent(_ctx(PERSON), uuid.uuid4())

        assert not deleted.await_count

    async def test_the_gate_is_per_row_so_a_grant_can_widen_it(self):
        """A route-level `require(...)` would refuse a viewer holding an explicit
        edit grant on this agent before `resolve_access` ever ran."""
        service = _service()
        agent = _agent()
        with (
            patch(f"{FACADE}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{FACADE}.resolve_access", new=AsyncMock(return_value=True)) as access,
            patch(f"{REPO}.delete_all_for_agent", new=AsyncMock(return_value=0)),
            patch(f"{CLAIMS}.delete_for_agent", new=AsyncMock(return_value=0)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            await service.clear_agent(_ctx(PERSON, role=OrgRoleName.VIEWER), agent.id)

        assert access.await_args.args[3] is Perm.AGENTS_EDIT
