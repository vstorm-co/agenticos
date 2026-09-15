"""What a person may see of the memory kept about them, and who else may (#1594).

The product decision before this was erasure only: you could ask that everything
an agent knew about you be forgotten, and could see none of it. That is the wrong
shape for somebody who has found *one* note that is wrong, or too personal, and
is not yet sure they want it gone.

Three questions, and the refusals are the point of two of them:

- **Your own store** is yours without a permission, because the answer is the
  same for a Viewer and an Owner.
- **Somebody else's** is a deployment administrator's and nobody else's - not an
  Owner, not an Admin, not somebody holding a grant on the agent that wrote it.
- **A suppressed note stops reaching the model**, which is the whole of what
  "deactivated" has to mean to be worth offering.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, NotFoundError
from app.core.memory_keys import person_owner_key
from app.core.permissions import AuthContext, OrgRoleName
from app.services.memory import MemoryService

pytestmark = [pytest.mark.anyio, pytest.mark.security]

FACADE = "app.services.memory.facade"
ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
PERSON = uuid.uuid4()
COLLEAGUE = uuid.uuid4()
AGENT = uuid.uuid4()


def _ctx(
    user_id: uuid.UUID, *, role: OrgRoleName = OrgRoleName.MEMBER, app_admin: bool = False
) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=ORG, role=role, is_app_admin=app_admin)


def _note(**overrides):
    """A row, as a namespace rather than a mock.

    `MagicMock(name=...)` names the mock instead of setting the attribute, and a
    note's `name` is exactly the field this surface reads.
    """
    fields = {
        "id": uuid.uuid4(),
        "agent_id": AGENT,
        "name": "prefs",
        "description": "How they like things",
        "content": "Prefers short answers",
        "format": "md",
        "kind": "note",
        "created_at": datetime(2026, 8, 1, tzinfo=UTC),
        "updated_at": None,
        "deactivated_at": None,
    }
    return SimpleNamespace(**{**fields, **overrides})


def _service(*, notes=(), total=None, agents=()) -> MemoryService:
    db = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = list(agents)
    result = MagicMock()
    result.scalars.return_value = scalars
    result.all.return_value = [(AGENT, "Support")]
    db.execute = AsyncMock(return_value=result)
    service = MemoryService(db)
    service._listed = (list(notes), len(notes) if total is None else total)
    return service


def _listing(service: MemoryService):
    return patch(
        f"{FACADE}.memory_repo.list_for_person", new=AsyncMock(return_value=service._listed)
    )


class TestReadingYourOwn:
    async def test_a_person_reads_their_own_store_without_a_permission(self) -> None:
        """The answer is the same for a Viewer and an Owner: it is their own."""
        note = _note()
        service = _service(notes=[note])
        with _listing(service) as listed:
            page = await service.mine(_ctx(PERSON, role=OrgRoleName.VIEWER), skip=0, limit=50)

        assert listed.await_args.kwargs["owner_key"] == person_owner_key(PERSON)
        assert page.total == 1
        assert page.items[0].content == "Prefers short answers"

    async def test_each_note_says_which_agent_wrote_it(self) -> None:
        """ "This is wrong" is a different sentence from "this was true last
        March", and neither can be said without the provenance."""
        service = _service(notes=[_note()])
        with _listing(service):
            page = await service.mine(_ctx(PERSON), skip=0, limit=50)

        assert page.items[0].agent_name == "Support"
        assert page.items[0].created_at == datetime(2026, 8, 1, tzinfo=UTC)

    async def test_a_suppressed_note_is_still_shown_to_its_subject(self) -> None:
        """It is theirs, and a view that hid what they had suppressed would be one
        they could not restore anything from."""
        suppressed = _note(deactivated_at=datetime(2026, 9, 1, tzinfo=UTC))
        service = _service(notes=[suppressed])
        with _listing(service):
            page = await service.mine(_ctx(PERSON), skip=0, limit=50)

        assert page.items[0].deactivated_at is not None

    async def test_an_external_store_is_named_rather_than_silently_left_out(self) -> None:
        """Showing a page of native notes while calling it a complete inventory is
        worse than saying which stores are outside it."""
        agent = MagicMock(id=AGENT)
        agent.name = "Support"
        agent.draft_spec = {
            "capabilities": [{"id": "memory_mem0", "enabled": True, "secret_id": str(uuid.uuid4())}]
        }
        service = _service(notes=[], agents=[agent])
        with _listing(service):
            page = await service.mine(_ctx(PERSON), skip=0, limit=50)

        assert page.external_stores == ["Support"]

    async def test_the_page_is_asked_for_with_the_window_the_caller_gave(self) -> None:
        service = _service(notes=[])
        with _listing(service) as listed:
            await service.mine(_ctx(PERSON), skip=40, limit=20)

        assert (listed.await_args.kwargs["skip"], listed.await_args.kwargs["limit"]) == (40, 20)


class TestReadingSomebodyElses:
    async def test_an_org_owner_may_not_read_a_colleagues_memory(self) -> None:
        """Reading what every agent has learned about a named colleague is a
        surveillance affordance, and an organization role is not the party a
        subject-access request reaches."""
        service = _service()
        with pytest.raises(AuthorizationError):
            await service.for_person(_ctx(PERSON, role=OrgRoleName.OWNER), ORG, COLLEAGUE)

    async def test_an_app_admin_may_naming_the_tenant_and_the_person(self) -> None:
        service = _service(notes=[_note()])
        with _listing(service) as listed, patch(f"{FACADE}.record_audit", new=AsyncMock()):
            page = await service.for_person(
                _ctx(PERSON, app_admin=True), OTHER_ORG, COLLEAGUE, reason="DSAR 41"
            )

        # The tenant is the one named, not whichever the admin had selected.
        assert listed.await_args.kwargs["organization_id"] == OTHER_ORG
        assert listed.await_args.kwargs["owner_key"] == person_owner_key(COLLEAGUE)
        assert page.total == 1

    async def test_the_privileged_read_is_audited_with_its_reason_and_no_content(self) -> None:
        """An audit entry holding what it looked at is a second copy of the thing
        being protected."""
        service = _service(notes=[_note()])
        audited = AsyncMock()
        with _listing(service), patch(f"{FACADE}.record_audit", audited):
            await service.for_person(
                _ctx(PERSON, app_admin=True), OTHER_ORG, COLLEAGUE, reason="DSAR 41"
            )

        entry = audited.await_args.kwargs
        assert entry["action"] == "memory.person.inspected"
        assert entry["organization_id"] == OTHER_ORG
        assert entry["target_id"] == str(COLLEAGUE)
        assert entry["details"] == {"notes": 1, "reason": "DSAR 41"}


class TestSuppressingAndDeleting:
    @staticmethod
    def _owned(row):
        return patch(f"{FACADE}.memory_repo.get_owned", new=AsyncMock(return_value=row))

    async def test_suppressing_a_note_stamps_the_moment(self) -> None:
        service = _service()
        row = _note()
        updated = AsyncMock()
        with (
            self._owned(row),
            patch(f"{FACADE}.memory_repo.update", updated),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            await service.set_active(_ctx(PERSON), row.id, active=False)

        assert updated.await_args.kwargs["update_data"]["deactivated_at"] is not None

    async def test_restoring_clears_it(self) -> None:
        service = _service()
        row = _note(deactivated_at=datetime(2026, 9, 1, tzinfo=UTC))
        updated = AsyncMock()
        with (
            self._owned(row),
            patch(f"{FACADE}.memory_repo.update", updated),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            await service.set_active(_ctx(PERSON), row.id, active=True)

        assert updated.await_args.kwargs["update_data"]["deactivated_at"] is None

    async def test_a_note_in_somebody_elses_store_is_not_found_rather_than_refused(self) -> None:
        """Whether a note exists in somebody else's store is itself something the
        caller may not learn - and owning a conversation or being able to edit the
        agent reaches nothing here."""
        service = _service()
        with (
            patch(f"{FACADE}.memory_repo.get_owned", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await service.set_active(_ctx(PERSON), uuid.uuid4(), active=False)

    async def test_the_lookup_is_scoped_to_the_callers_own_store(self) -> None:
        """The owner is part of the lookup rather than checked afterwards: a
        lookup by id alone with a check bolted on is the shape that loses it."""
        service = _service()
        row = _note()
        owned = AsyncMock(return_value=row)
        with (
            patch(f"{FACADE}.memory_repo.get_owned", owned),
            patch(f"{FACADE}.memory_repo.delete", new=AsyncMock()),
            patch(f"{FACADE}.record_audit", new=AsyncMock()),
        ):
            await service.delete_note(_ctx(PERSON), row.id)

        assert owned.await_args.kwargs["owner_key"] == person_owner_key(PERSON)

    async def test_a_deletion_is_audited_by_name_and_never_by_content(self) -> None:
        service = _service()
        row = _note()
        audited = AsyncMock()
        with (
            patch(f"{FACADE}.memory_repo.get_owned", new=AsyncMock(return_value=row)),
            patch(f"{FACADE}.memory_repo.delete", new=AsyncMock()),
            patch(f"{FACADE}.record_audit", audited),
        ):
            await service.delete_note(_ctx(PERSON), row.id)

        assert audited.await_args.kwargs["details"] == {"agent_id": str(AGENT), "name": "prefs"}
        assert "content" not in audited.await_args.kwargs["details"]
