"""Tests for the memory erasure service.

Erasure is the whole of what a person does to memory directly, so this file is
almost entirely refusals: who may erase whom, and what a "forgotten" answer is
allowed to claim.

The claim is the part worth guarding. A person told their memory is gone and
finding out later that mem0 still remembers has been told something false, so a
mem0 failure must reach them rather than be logged and counted as success.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.memory_keys import person_owner_key
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.core.secret_kinds import ApiKeySecret
from app.services.memory import MemoryService

pytestmark = pytest.mark.anyio

FACADE = "app.services.memory.facade"
REPO = "app.repositories.memory"
ORG = uuid.uuid4()
PERSON = uuid.uuid4()
ADMIN = uuid.uuid4()
SECRET = uuid.uuid4()


def _ctx(user_id: uuid.UUID, *, role: OrgRoleName = OrgRoleName.MEMBER) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=ORG, role=role)


def _agent(*, mem0: bool = True, secret_id: uuid.UUID | None = SECRET, base_url=None):
    agent = MagicMock()
    agent.id = uuid.uuid4()
    binding = {"id": "memory_mem0" if mem0 else "memory_files", "enabled": True}
    if secret_id is not None:
        binding["secret_id"] = str(secret_id)
    if base_url is not None:
        binding["config"] = {"base_url": base_url}
    agent.draft_spec = {"capabilities": [binding]}
    return agent


def _service(agents=()) -> MemoryService:
    db = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = list(agents)
    result = MagicMock()
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    return MemoryService(db)


class TestForgettingAPerson:
    async def test_anybody_may_erase_themselves(self):
        service = _service()
        with (
            patch(f"{REPO}.delete_for_person", new=AsyncMock(return_value=3)),
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
            patch(f"{FACADE}.record_audit", new=AsyncMock()) as audit,
        ):
            await service.forget_person(_ctx(PERSON), PERSON)

        assert audit.await_args.kwargs["action"] == "memory.person.forgotten"
        assert audit.await_args.kwargs["target_id"] == str(PERSON)
        assert audit.await_args.kwargs["details"]["notes"] == 2


class TestTheHalfMem0Holds:
    async def _forget(self, service, *, resolved):
        with (
            patch(f"{REPO}.delete_for_person", new=AsyncMock(return_value=0)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
            patch(f"{FACADE}.mem0_forget_person", new=AsyncMock()) as forget,
            patch.object(service.secrets, "resolve_for_bindings", AsyncMock(return_value=resolved)),
        ):
            return await service.forget_person(_ctx(PERSON), PERSON), forget

    async def test_every_agent_that_binds_mem0_is_reached(self):
        """Each agent has its own namespace and may have its own key, so this is
        one call per binding rather than one for the organization."""
        agents = [_agent(), _agent()]
        service = _service(agents)
        secret = ApiKeySecret(api_key=SecretStr("k-1-12345"))

        result, forget = await self._forget(service, resolved={SECRET: secret})

        assert result.mem0_agents_cleared == 2
        assert forget.await_count == 2
        assert forget.await_args.kwargs["owner_key"] == person_owner_key(PERSON)

    async def test_an_agent_without_mem0_is_left_alone(self):
        service = _service([_agent(mem0=False)])

        result, forget = await self._forget(service, resolved={})

        assert (result.mem0_agents_cleared, forget.await_count) == (0, 0)

    async def test_a_binding_with_no_key_is_left_alone(self):
        """It cannot reach mem0 either, so there is nothing of theirs out there."""
        service = _service([_agent(secret_id=None)])

        result, forget = await self._forget(service, resolved={})

        assert (result.mem0_agents_cleared, forget.await_count) == (0, 0)

    async def test_a_key_that_no_longer_resolves_is_skipped_rather_than_guessed_at(self):
        service = _service([_agent()])

        result, forget = await self._forget(service, resolved={SECRET: None})

        assert (result.mem0_agents_cleared, forget.await_count) == (0, 0)

    async def test_a_self_hosted_url_travels_with_the_delete(self):
        """A memory kept on somebody's own mem0 is not deleted by calling the cloud
        one, which would report success having removed nothing."""
        service = _service([_agent(base_url="https://mem0.internal")])

        _result, forget = await self._forget(
            service, resolved={SECRET: ApiKeySecret(api_key=SecretStr("k-1-12345"))}
        )

        assert forget.await_args.kwargs["base_url"] == "https://mem0.internal"

    async def test_the_url_is_found_past_the_other_capabilities_an_agent_binds(self):
        """A real spec lists mem0 among a dozen others, so the search for its
        `base_url` has to walk past them - a scan that stopped at the first
        binding would send every self-hosted delete to the cloud."""
        agent = _agent(base_url="https://mem0.internal")
        agent.draft_spec = {
            "capabilities": [
                {"id": "memory_files", "enabled": True},
                "not a binding at all",
                *agent.draft_spec["capabilities"],
            ]
        }
        service = _service([agent])

        _result, forget = await self._forget(
            service, resolved={SECRET: ApiKeySecret(api_key=SecretStr("k-1-12345"))}
        )

        assert forget.await_args.kwargs["base_url"] == "https://mem0.internal"

    async def test_a_binding_with_no_config_sends_no_url(self):
        service = _service([_agent()])

        _result, forget = await self._forget(
            service, resolved={SECRET: ApiKeySecret(api_key=SecretStr("k-1-12345"))}
        )

        assert forget.await_args.kwargs["base_url"] is None

    async def test_a_mem0_failure_reaches_the_person_rather_than_the_log(self):
        """The failure this whole feature exists to avoid is a partial wipe wearing
        a success: told their memory is gone, somebody stops asking."""
        service = _service([_agent()])
        with (
            patch(f"{REPO}.delete_for_person", new=AsyncMock(return_value=0)),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
            patch(f"{FACADE}.mem0_forget_person", new=AsyncMock(side_effect=RuntimeError("down"))),
            patch.object(
                service.secrets,
                "resolve_for_bindings",
                AsyncMock(return_value={SECRET: ApiKeySecret(api_key=SecretStr("k-1-12345"))}),
            ),
            pytest.raises(RuntimeError),
        ):
            await service.forget_person(_ctx(PERSON), PERSON)

    async def test_a_spec_whose_capabilities_are_not_a_list_is_simply_not_a_binding(self):
        """Stored JSON, so the shape is not guaranteed by anything; a malformed one
        must not take an erasure down."""
        agent = _agent()
        agent.draft_spec = {"capabilities": "everything"}
        service = _service([agent])

        result, forget = await self._forget(service, resolved={})

        assert (result.mem0_agents_cleared, forget.await_count) == (0, 0)


class TestClearingOneAgent:
    async def test_it_deletes_every_note_that_agent_holds(self):
        service = _service()
        agent = _agent()
        with (
            patch(f"{FACADE}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{FACADE}.resolve_access", new=AsyncMock(return_value=True)),
            patch(f"{REPO}.delete_all_for_agent", new=AsyncMock(return_value=7)) as deleted,
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
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            await service.clear_agent(_ctx(PERSON, role=OrgRoleName.VIEWER), agent.id)

        assert access.await_args.args[3] is Perm.AGENTS_EDIT
