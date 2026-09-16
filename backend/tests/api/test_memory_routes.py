"""The self-service memory surface, wired (#1594).

What the service decides is in `tests/test_memory_self_service.py`. What is here
is the wiring: which path, which caller the service is handed, and that a refusal
reaches the browser as a refusal.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.memory import MemoryErasureResult, MemoryNoteList, MemoryNoteRead

pytestmark = [pytest.mark.anyio, pytest.mark.security]

ROOT = f"{settings.API_V1_STR}/memory"
PERSON = uuid4()
ORG = uuid4()
NOTE = uuid4()

_NOTE = MemoryNoteRead(
    id=NOTE,
    agent_id=uuid4(),
    agent_name="Support",
    name="prefs",
    content="Prefers short answers",
    format="md",
    kind="note",
)
_PAGE = MemoryNoteList(items=[_NOTE], total=1, external_stores=["Support"])


@asynccontextmanager
async def _client(*, app_admin: bool = False) -> AsyncIterator[AsyncClient]:
    ctx = AuthContext(
        user_id=PERSON, organization_id=ORG, role=OrgRoleName.VIEWER, is_app_admin=app_admin
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_db_session] = lambda: MagicMock()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


async def test_a_member_reads_their_own_store() -> None:
    """No permission to ask for: the answer is the same for a Viewer and an Owner."""
    with patch("app.services.memory.MemoryService.mine", new=AsyncMock(return_value=_PAGE)):
        async with _client() as client:
            response = await client.get(f"{ROOT}/mine")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["agent_name"] == "Support"
    assert body["external_stores"] == ["Support"]


async def test_the_window_the_caller_asked_for_reaches_the_service() -> None:
    mine = AsyncMock(return_value=_PAGE)
    with patch("app.services.memory.MemoryService.mine", mine):
        async with _client() as client:
            await client.get(f"{ROOT}/mine?skip=40&limit=20")

    assert (mine.await_args.kwargs["skip"], mine.await_args.kwargs["limit"]) == (40, 20)


async def test_suppressing_a_note_goes_through_as_inactive() -> None:
    set_active = AsyncMock(return_value=_NOTE)
    with patch("app.services.memory.MemoryService.set_active", set_active):
        async with _client() as client:
            response = await client.patch(f"{ROOT}/mine/{NOTE}", json={"active": False})

    assert response.status_code == 200
    assert set_active.await_args.kwargs["active"] is False


async def test_deleting_a_note_answers_no_content() -> None:
    with patch("app.services.memory.MemoryService.delete_note", new=AsyncMock()):
        async with _client() as client:
            response = await client.delete(f"{ROOT}/mine/{NOTE}")

    assert response.status_code == 204


async def test_an_app_admin_names_the_tenant_and_the_reason() -> None:
    """The tenant is a parameter rather than whichever the admin had selected: a
    read that used the active organization silently is one nobody could audit."""
    for_person = AsyncMock(return_value=_PAGE)
    with patch("app.services.memory.MemoryService.for_person", for_person):
        async with _client(app_admin=True) as client:
            response = await client.get(
                f"{ROOT}/person/{PERSON}?organization_id={ORG}&reason=DSAR+41"
            )

    assert response.status_code == 200
    assert for_person.await_args.kwargs["reason"] == "DSAR 41"
    assert for_person.await_args.args[1] == ORG


async def test_an_organization_role_is_refused_rather_than_500() -> None:
    with patch(
        "app.services.memory.MemoryService.for_person",
        new=AsyncMock(side_effect=AuthorizationError(message="nope")),
    ):
        async with _client() as client:
            response = await client.get(f"{ROOT}/person/{PERSON}?organization_id={ORG}")

    assert response.status_code == 403


async def test_forgetting_a_person_answers_what_each_half_removed() -> None:
    """Not 204: the mem0 half is somebody else's service, and a caller has to be
    able to say which parts of "forgotten" actually happened."""
    result = MemoryErasureResult(notes_deleted=3, mem0_agents_cleared=1)
    with patch(
        "app.services.memory.MemoryService.forget_person", new=AsyncMock(return_value=result)
    ):
        async with _client() as client:
            response = await client.delete(f"{ROOT}/person/{PERSON}")

    assert response.status_code == 200
    assert response.json() == {"notes_deleted": 3, "mem0_agents_cleared": 1}


async def test_clearing_one_agents_store_names_the_agent_in_the_query() -> None:
    """A memory store nobody can clear is a liability (#788)."""
    agent_id = uuid4()
    clear = AsyncMock(return_value=MemoryErasureResult(notes_deleted=2, mem0_agents_cleared=0))
    with patch("app.services.memory.MemoryService.clear_agent", clear):
        async with _client() as client:
            response = await client.delete(f"{ROOT}?agent_id={agent_id}")

    assert response.status_code == 200
    assert clear.await_args.args[1] == agent_id
