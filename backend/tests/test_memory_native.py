"""Tests for the agent's runtime memory store (`_native`).

Each function opens its own session, because a run must not touch memory on the
session it runs on; here that session is faked and the repository mocked, so what
is under test is the orchestration.

Every function takes exactly one `owner_key`. Which store that is, is decided in
`app.agents.memory_scope` from who is listening, and this layer neither knows nor
asks - which is the point of the reshape, and why there is no longer a scope
argument to get wrong (#1470).
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.memory import _native

pytestmark = pytest.mark.anyio

NATIVE = "app.services.memory._native"
REPO = "app.repositories.memory"
ORG, AGENT = uuid4(), uuid4()
OWNER = f"person:{uuid4()}"


@asynccontextmanager
async def _fake_session():
    session = MagicMock()
    session.rollback = AsyncMock()
    yield session


@pytest.fixture(autouse=True)
def _own_session(monkeypatch):
    """Every `_native` call opens its own session; fake it for all of them."""
    monkeypatch.setattr(f"{NATIVE}.get_db_context", _fake_session)


def _row(*, content="body", name="prefs"):
    row = MagicMock()
    row.content = content
    row.name = name
    row.description = "d"
    row.kind = "note"
    row.owner_key = OWNER
    return row


class TestListFiles:
    async def test_it_returns_detached_index_entries(self):
        """Detached, because the session they were read on is closed by the time
        the caller has them - an ORM row would raise on its first attribute."""
        with patch(f"{REPO}.list_for_owner", new=AsyncMock(return_value=[_row()])):
            entries = await _native.list_files(organization_id=ORG, agent_id=AGENT, owner_key=OWNER)

        assert [(entry.name, entry.kind, entry.description) for entry in entries] == [
            ("prefs", "note", "d")
        ]

    async def test_an_empty_store_lists_nothing(self):
        with patch(f"{REPO}.list_for_owner", new=AsyncMock(return_value=[])):
            assert (
                await _native.list_files(organization_id=ORG, agent_id=AGENT, owner_key=OWNER) == []
            )

    async def test_it_asks_for_one_store_and_only_one(self):
        """A run reads exactly the store it writes. The union this replaced is what
        let a note taken alone with somebody be read back in a channel (#788)."""
        with patch(f"{REPO}.list_for_owner", new=AsyncMock(return_value=[])) as listed:
            await _native.list_files(organization_id=ORG, agent_id=AGENT, owner_key=OWNER)

        assert listed.await_args.kwargs["owner_key"] == OWNER


class TestReadFile:
    async def test_it_returns_the_body(self):
        with patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=_row(content="hello"))):
            body = await _native.read_file(
                organization_id=ORG, agent_id=AGENT, owner_key=OWNER, name="prefs"
            )

        assert body == "hello"

    async def test_a_name_this_store_does_not_hold_is_none(self):
        with patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)):
            assert (
                await _native.read_file(
                    organization_id=ORG, agent_id=AGENT, owner_key=OWNER, name="prefs"
                )
                is None
            )


class TestWriteFile:
    async def _write(self, **overrides):
        return await _native.write_file(
            **{
                "organization_id": ORG,
                "agent_id": AGENT,
                "owner_key": OWNER,
                "name": "prefs",
                "content": "body",
                "description": "d",
                "kind": "note",
                **overrides,
            }
        )

    async def test_a_new_name_is_created(self):
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{REPO}.create", new=AsyncMock()) as create,
        ):
            assert await self._write() is True

        assert create.await_args.kwargs["owner_key"] == OWNER
        assert create.await_args.kwargs["content_format"] == "md"

    async def test_a_taken_name_is_reported_rather_than_overwritten(self):
        """Overwriting is `edit_file`, a deliberately separate act, so the model
        cannot lose a note by reaching for the wrong verb."""
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=_row())),
            patch(f"{REPO}.create", new=AsyncMock()) as create,
        ):
            assert await self._write() is False

        assert not create.await_count

    async def test_a_name_taken_between_the_check_and_the_insert_is_the_same_answer(self):
        """The unique index is the real guard, and a concurrent write is not a
        different outcome to the caller - two turns of one run racing is exactly
        how this happens."""
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                f"{REPO}.create",
                new=AsyncMock(side_effect=IntegrityError("insert", {}, Exception())),
            ),
        ):
            assert await self._write() is False


class TestEditFile:
    async def test_an_existing_note_is_replaced_whole(self):
        row = _row()
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=row)),
            patch(f"{REPO}.update", new=AsyncMock()) as update,
        ):
            assert (
                await _native.edit_file(
                    organization_id=ORG,
                    agent_id=AGENT,
                    owner_key=OWNER,
                    name="prefs",
                    content="new",
                )
                is True
            )

        assert update.await_args.kwargs == {"file": row, "update_data": {"content": "new"}}

    async def test_nothing_of_that_name_edits_nothing(self):
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{REPO}.update", new=AsyncMock()) as update,
        ):
            assert (
                await _native.edit_file(
                    organization_id=ORG,
                    agent_id=AGENT,
                    owner_key=OWNER,
                    name="prefs",
                    content="new",
                )
                is False
            )

        assert not update.await_count


class TestDeleteFile:
    async def test_an_existing_note_is_removed(self):
        row = _row()
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=row)),
            patch(f"{REPO}.delete", new=AsyncMock()) as delete,
        ):
            assert (
                await _native.delete_file(
                    organization_id=ORG, agent_id=AGENT, owner_key=OWNER, name="prefs"
                )
                is True
            )

        assert delete.await_args.args[1] is row

    async def test_nothing_of_that_name_deletes_nothing(self):
        with (
            patch(f"{REPO}.get_by_name", new=AsyncMock(return_value=None)),
            patch(f"{REPO}.delete", new=AsyncMock()) as delete,
        ):
            assert (
                await _native.delete_file(
                    organization_id=ORG, agent_id=AGENT, owner_key=OWNER, name="prefs"
                )
                is False
            )

        assert not delete.await_count
