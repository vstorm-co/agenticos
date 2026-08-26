"""The audit write is part of the action it records, not a best-effort aside.

`record_audit` used to swallow every failure, which was fail-open on a trail that
`docs/governance.md` makes load-bearing for the app-admin bypass story - and it
did not even buy silence, since a flushed-then-abandoned session made the
request's commit raise anyway (#20).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.audit import current_impersonator, record_audit, set_impersonator

pytestmark = pytest.mark.anyio


class _CapturingDB:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, entry: object) -> None:
        self.added.append(entry)

    async def flush(self) -> None:
        pass


class _FlushRaisesDB(_CapturingDB):
    async def flush(self) -> None:
        raise RuntimeError("connection reset")


class TestFailsClosed:
    def teardown_method(self) -> None:
        set_impersonator(None)

    async def test_a_failed_audit_write_propagates_rather_than_being_swallowed(self) -> None:
        with pytest.raises(RuntimeError):
            await record_audit(_FlushRaisesDB(), actor_user_id=uuid.uuid4(), action="agent.deleted")


class TestTheEntry:
    def teardown_method(self) -> None:
        set_impersonator(None)

    async def test_a_non_string_target_id_is_stringified_onto_the_entry(self) -> None:
        target = uuid.uuid4()
        db = _CapturingDB()
        await record_audit(
            db,
            actor_user_id=uuid.uuid4(),
            action="skill.deleted",
            target_id=target,  # type: ignore[arg-type]  # exercise the defensive str()
        )
        assert db.added[0].target_id == str(target)

    async def test_no_target_leaves_the_column_null(self) -> None:
        db = _CapturingDB()
        await record_audit(db, actor_user_id=uuid.uuid4(), action="settings.updated")
        assert db.added[0].target_id is None


class TestImpersonatorContext:
    def teardown_method(self) -> None:
        set_impersonator(None)

    def test_the_impersonator_round_trips_through_the_context(self) -> None:
        admin = uuid.uuid4()
        set_impersonator(admin)
        assert current_impersonator() == admin

    def test_no_impersonator_by_default(self) -> None:
        assert current_impersonator() is None
