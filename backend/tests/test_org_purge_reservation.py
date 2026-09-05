"""Every collection an organization purge drops is reserved before it commits.

A reservation is what stops another organization claiming the name in the
commit-to-drop window and adopting a table that still holds the deleted
organization's vectors - which the deferred cleanup would then *preserve*, on
seeing the new reference. The names the purge's snapshot saw are locked before
the organization row is, so they reserve without ceremony; one created between
that snapshot and the row lock is found only by the authoritative scan, and is
the case these tests are about (#1389).
"""

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import ConcurrentChangeError
from app.db.locks import LockScope
from app.services.organization import OrganizationService

pytestmark = pytest.mark.anyio

SERVICE = "app.services.organization"


def _kb(collection_name: str) -> MagicMock:
    return MagicMock(id=uuid4(), collection_name=collection_name)


def _purge(*, snapshot: list[str], authoritative: list[str], lock_free: bool = True):
    """Run a purge over two readings of the organization's collections.

    `snapshot` is what the first read - the one taken before the organization row
    is locked - returns, and `authoritative` what the read under that lock finds.
    A name in the second and not the first is one created in between.

    The mocks are handed back as a dict rather than read off `patch.multiple`,
    which returns one only for the attributes it was asked to fill in itself.
    """
    org = MagicMock(id=uuid4())
    db = MagicMock()
    db.flush = AsyncMock()
    reads = [[_kb(name) for name in snapshot], [_kb(name) for name in authoritative]]
    mocks = {
        "knowledge_base_repo": MagicMock(
            list_org_scoped=AsyncMock(side_effect=reads),
            list_by_collection_name=AsyncMock(return_value=[]),
            delete=AsyncMock(),
        ),
        "rag_document_repo": MagicMock(delete_by_knowledge_base=AsyncMock(return_value=[])),
        "organization_repo": MagicMock(get_by_id_for_update=AsyncMock(), delete=AsyncMock()),
        "collection_teardown_repo": MagicMock(reserve=AsyncMock()),
        "hold_name": AsyncMock(),
        "try_hold_name": AsyncMock(return_value=lock_free),
    }
    return org, db, mocks


@contextlib.contextmanager
def _patched(mocks: dict):
    # `spawn_after_commit` is imported inside the method, so it is patched where
    # it is defined rather than on the service module.
    with (
        patch.multiple(SERVICE, **mocks),
        patch("app.core.background.spawn_after_commit") as spawned,
    ):
        mocks["spawned"] = spawned
        yield mocks


async def _run(org, db, mocks) -> dict:
    with _patched(mocks):
        await OrganizationService(db, vector_store=MagicMock()).purge(org)
    return mocks


class TestACollectionCreatedWhileThePurgeRuns:
    async def test_it_is_locked_without_waiting_and_reserved(self):
        """Locked with `try_hold_name` rather than `hold_name`: the organization
        row is already held, and a claim takes the name's lock *then* the row -
        so waiting here is the ABBA deadlock the order exists to avoid."""
        org, db, mocks = _purge(snapshot=["seen"], authoritative=["seen", "late"])

        await _run(org, db, mocks)

        mocks["try_hold_name"].assert_awaited_once_with(db, LockScope.COLLECTION_TEARDOWN, "late")
        reserved = {
            call.args[1] for call in mocks["collection_teardown_repo"].reserve.await_args_list
        }
        assert reserved == {"seen", "late"}

    async def test_a_name_the_snapshot_saw_is_not_locked_twice(self):
        org, db, mocks = _purge(snapshot=["seen"], authoritative=["seen"])

        await _run(org, db, mocks)

        mocks["try_hold_name"].assert_not_awaited()
        mocks["hold_name"].assert_awaited_once_with(db, LockScope.COLLECTION_TEARDOWN, "seen")

    async def test_a_name_something_else_holds_refuses_rather_than_dropping_it(self):
        """The claim holding that lock is about to adopt the name. Dropping the
        table unreserved hands it the deleted organization's vectors; nothing
        this transaction can still do makes that safe, so it does not commit."""
        org, db, mocks = _purge(snapshot=[], authoritative=["late"], lock_free=False)

        with pytest.raises(ConcurrentChangeError) as refused:
            await _run(org, db, mocks)

        assert refused.value.details == {"collection_name": "late"}

    async def test_nothing_is_dispatched_when_it_refuses(self):
        org, db, mocks = _purge(snapshot=[], authoritative=["late"], lock_free=False)

        with _patched(mocks), pytest.raises(ConcurrentChangeError):
            await OrganizationService(db, vector_store=MagicMock()).purge(org)

        mocks["spawned"].assert_not_called()
        mocks["collection_teardown_repo"].reserve.assert_not_awaited()


class TestACollectionAnotherOrganizationStillReferences:
    async def test_it_is_neither_dropped_nor_reserved(self):
        """The name is not tenant-unique (#913), so a table somebody else still
        points at is not this purge's to take away."""
        org, db, mocks = _purge(snapshot=["shared"], authoritative=["shared"])

        mocks["knowledge_base_repo"].list_by_collection_name = AsyncMock(return_value=[MagicMock()])

        await _run(org, db, mocks)

        mocks["collection_teardown_repo"].reserve.assert_not_awaited()
        mocks["spawned"].assert_not_called()


class TestWithNoVectorStoreWired:
    async def test_no_name_is_locked_or_reserved(self):
        """Ordinary organization work does not pay for a teardown it is not doing."""
        org, db, mocks = _purge(snapshot=["seen"], authoritative=["seen"])

        with _patched(mocks):
            await OrganizationService(db).purge(org)

        mocks["hold_name"].assert_not_awaited()
        mocks["try_hold_name"].assert_not_awaited()
        mocks["collection_teardown_repo"].reserve.assert_not_awaited()
