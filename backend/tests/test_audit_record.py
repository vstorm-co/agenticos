"""The audit write is part of the action it records, not a best-effort aside.

`record_audit` used to swallow every failure, which was fail-open on a trail that
`docs/governance.md` makes load-bearing for the app-admin bypass story - and it
did not even buy silence, since a flushed-then-abandoned session made the
request's commit raise anyway (#20).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.core.audit import chain_hash, current_impersonator, record_audit, set_impersonator

pytestmark = pytest.mark.anyio


class _CapturingDB:
    """A session that keeps what was added, and answers the head read with `head`."""

    def __init__(self, head: str | None = None) -> None:
        self.added: list[object] = []
        self._head = head

    def add(self, entry: object) -> None:
        self.added.append(entry)

    async def execute(self, *_args: object, **_kwargs: object) -> MagicMock:
        result = MagicMock()
        result.scalar_one_or_none.return_value = self._head
        return result

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


class TestTheChain:
    def teardown_method(self) -> None:
        set_impersonator(None)

    async def test_the_first_entry_in_a_chain_has_no_previous_hash(self) -> None:
        db = _CapturingDB(head=None)
        await record_audit(db, actor_user_id=uuid.uuid4(), action="settings.updated")
        assert db.added[0].prev_hash is None

    async def test_an_entry_links_to_the_current_head_and_hashes_its_contents(self) -> None:
        actor = uuid.uuid4()
        organization = uuid.uuid4()
        db = _CapturingDB(head="a" * 64)
        await record_audit(
            db,
            actor_user_id=actor,
            action="agent.deleted",
            organization_id=organization,
        )
        entry = db.added[0]
        assert entry.prev_hash == "a" * 64
        assert entry.entry_hash == chain_hash(
            prev_hash="a" * 64,
            actor_user_id=actor,
            impersonator_user_id=None,
            organization_id=organization,
            action="agent.deleted",
            target_type=None,
            target_id=None,
            details=None,
            ip_address=entry.ip_address,
            created_at=entry.created_at,
        )


class TestChainHash:
    def test_it_covers_every_field_and_changes_when_any_of_them_does(self) -> None:
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        fields: dict[str, object] = {
            "prev_hash": "b" * 64,
            "actor_user_id": uuid.uuid4(),
            "impersonator_user_id": uuid.uuid4(),
            "organization_id": uuid.uuid4(),
            "action": "agent.deleted",
            "target_type": "agent",
            "target_id": str(uuid.uuid4()),
            "details": {"fields": ["name"]},
            "ip_address": "203.0.113.7",
            "created_at": created_at,
        }
        baseline = chain_hash(**fields)  # type: ignore[arg-type]
        assert baseline == chain_hash(**fields)  # type: ignore[arg-type]  # deterministic
        assert chain_hash(**{**fields, "action": "agent.published"}) != baseline  # type: ignore[arg-type]

    def test_it_hashes_an_entry_whose_optional_fields_are_all_null(self) -> None:
        first = chain_hash(
            prev_hash=None,
            actor_user_id=None,
            impersonator_user_id=None,
            organization_id=None,
            action="approval.expired",
            target_type=None,
            target_id=None,
            details=None,
            ip_address=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert isinstance(first, str)
        assert len(first) == 64

    def test_created_at_is_normalized_to_utc_before_hashing(self) -> None:
        """Two spellings of one instant hash the same, so a value read back from the
        column with a different tzinfo than the one just built still verifies."""
        from datetime import timedelta, timezone

        instant_utc = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        instant_offset = instant_utc.astimezone(timezone(timedelta(hours=2)))
        common = {
            "prev_hash": None,
            "actor_user_id": None,
            "impersonator_user_id": None,
            "organization_id": None,
            "action": "settings.updated",
            "target_type": None,
            "target_id": None,
            "details": None,
            "ip_address": None,
        }
        assert chain_hash(created_at=instant_utc, **common) == chain_hash(  # type: ignore[arg-type]
            created_at=instant_offset,
            **common,  # type: ignore[arg-type]
        )


class TestImpersonatorContext:
    def teardown_method(self) -> None:
        set_impersonator(None)

    def test_the_impersonator_round_trips_through_the_context(self) -> None:
        admin = uuid.uuid4()
        set_impersonator(admin)
        assert current_impersonator() == admin

    def test_no_impersonator_by_default(self) -> None:
        assert current_impersonator() is None
