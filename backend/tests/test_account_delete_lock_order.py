"""The order account deletion takes its locks in (#2638, #2682).

The deadlocks the order prevents are shown on Postgres in
`tests/integration/test_account_delete_spend_deadlock.py` and
`tests/integration/test_account_delete_writer_deadlock.py`.
"""

import itertools
import uuid
from collections.abc import Callable
from types import SimpleNamespace, TracebackType
from typing import cast
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import ConcurrentChangeError, NotFoundError
from app.db.models.user import User
from app.services.rag_document import RAGDocumentService
from app.services.user import UserService, _LockedAccount

pytestmark = pytest.mark.anyio

Step = tuple[str, object]

_BUSY = "55P03"
_DEADLOCK = "40P01"


class _PostgresError(Exception):
    """The driver error a `DBAPIError` wraps; asyncpg's carries the SQLSTATE."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("SELECT", {}, _PostgresError(sqlstate))


def _base(collection_name: str) -> SimpleNamespace:
    return SimpleNamespace(collection_name=collection_name)


class _Savepoint:
    """`begin_nested()`: released on a clean exit, rolled back on an exception."""

    def __init__(self, order: list[Step]) -> None:
        self.order = order
        self.open = True

    async def __aenter__(self) -> _Savepoint:
        self.order.append(("savepoint", None))
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.open:
            self.order.append(("rollback" if exc_type else "release", None))

    async def rollback(self) -> None:
        self.open = False
        self.order.append(("rollback", None))


class _Account:
    """A deletion's lock phase against mocked repositories, recording each step.

    `user_row` answers each call of the user's own row lock, numbered from 1,
    given whether it waits: `None` grants it, `"gone"` finds no row, and any
    other string is the SQLSTATE of the error it raises.
    """

    def __init__(
        self,
        *,
        user_row: Callable[[int, bool], str | None] = lambda _call, _nowait: None,
        personal: list[SimpleNamespace] | None = None,
        org_scoped: list[list[SimpleNamespace]] | None = None,
        heir: uuid.UUID | None = None,
        granted: bool = True,
    ) -> None:
        self.order: list[Step] = []
        self.user_id = uuid.uuid4()
        self.user = SimpleNamespace(id=self.user_id, is_app_admin=False)
        self.organization = SimpleNamespace(id=uuid.uuid4(), is_personal=True)
        self.shared = SimpleNamespace(id=uuid.uuid4(), is_personal=False)
        self.user_row = user_row
        self.personal = personal or []
        self.org_scoped = iter(org_scoped) if org_scoped else itertools.repeat([])
        self.heir = heir
        self.granted = granted
        self.user_calls = 0
        db = MagicMock()
        db.begin_nested = lambda: _Savepoint(self.order)
        self.service = UserService(db)

    def _step(self, name: str, result: object = None) -> AsyncMock:
        """A lock on a name or an organization, recorded with what it locks."""

        async def called(*args: object, **_: object) -> object:
            self.order.append((name, args[-1]))
            return result

        return AsyncMock(side_effect=called)

    def _row_step(self, name: str, result: object = None) -> AsyncMock:
        """A user-row lock, recorded with whether it waits."""

        async def called(*_: object, nowait: bool) -> object:
            self.order.append((name, "nowait" if nowait else "wait"))
            return result

        return AsyncMock(side_effect=called)

    async def _user(self, _db: object, _user_id: uuid.UUID, *, nowait: bool) -> object:
        self.user_calls += 1
        outcome = self.user_row(self.user_calls, nowait)
        self.order.append(("user", outcome or ("nowait" if nowait else "wait")))
        if outcome == "gone":
            return None
        if outcome is not None:
            raise _db_error(outcome)
        return self.user

    async def lock(self, *, app_admins: bool = False) -> _LockedAccount:
        with (
            patch("app.services.user.knowledge_base_repo") as bases,
            patch("app.services.user.organization_repo") as organizations,
            patch("app.services.user.member_repo") as members,
            patch("app.services.user.user_repo") as users,
            patch("app.services.user.try_hold_subject", new=AsyncMock(return_value=True)),
            patch(
                "app.repositories.telephony.user_has_unfinished_calls",
                new=AsyncMock(return_value=False),
            ),
            patch("app.services.user.hold_name", new=self._step("name")),
            patch("app.services.user.try_hold_name", new=self._step("try name", self.granted)),
        ):
            bases.list_personal_by_owner = AsyncMock(return_value=self.personal)
            bases.list_org_scoped = AsyncMock(side_effect=lambda *_: next(self.org_scoped))
            organizations.list_created_by = AsyncMock(
                return_value=[self.organization, *([self.shared] if self.heir else [])]
            )
            organizations.get_by_id_for_update = self._step("organization")
            members.other_owner_id = AsyncMock(return_value=self.heir)
            users.get_by_id_for_update = AsyncMock(side_effect=self._user)
            users.get_by_id_for_no_key_update = self._row_step("heir")
            users.app_admin_ids_for_no_key_update = self._row_step("app admins", [self.user_id])
            return await self.service._lock_account(self.user_id, app_admins=app_admins)

    def user_steps(self) -> list[Step]:
        return [step for step in self.order if step[0] == "user"]


async def test_names_then_organization_then_the_user_row_without_waiting() -> None:
    account = _Account(personal=[_base("delta"), _base("alpha")])

    locked = await account.lock()

    assert locked.user is account.user
    assert account.order == [
        ("savepoint", None),
        ("name", "alpha"),
        ("name", "delta"),
        ("organization", account.organization.id),
        ("user", "nowait"),
        ("release", None),
    ]


async def test_a_busy_user_row_lets_everything_go_waits_for_it_and_starts_again() -> None:
    """The writer holding the user row may be waiting for the organization this
    holds, so the phase rolls back and waits for the row in a savepoint that
    holds nothing else."""
    account = _Account(
        user_row=lambda call, _nowait: _BUSY if call == 1 else None, personal=[_base("alpha")]
    )

    await account.lock()

    assert account.order == [
        ("savepoint", None),
        ("name", "alpha"),
        ("organization", account.organization.id),
        ("user", _BUSY),
        ("rollback", None),
        ("savepoint", None),
        ("user", "wait"),
        ("rollback", None),
        ("savepoint", None),
        ("name", "alpha"),
        ("organization", account.organization.id),
        ("user", "nowait"),
        ("release", None),
    ]


async def test_rows_still_busy_when_the_time_is_up_refuse_without_waiting_again() -> None:
    """Busy at every attempt: once the time is up the deletion refuses at once,
    rather than waiting for a row it would not use."""
    account = _Account(user_row=lambda _call, nowait: _BUSY if nowait else None)
    # Read for the deadline, then after each busy attempt; the time stays up.
    clock = iter([0.0, 1.0])

    with (
        patch("app.services.user.time.monotonic", side_effect=lambda: next(clock, 11.0)),
        pytest.raises(ConcurrentChangeError) as refused,
    ):
        await account.lock()

    assert refused.value.details == {"user_id": account.user_id}
    assert account.user_steps() == [("user", _BUSY), ("user", "wait"), ("user", _BUSY)]
    assert account.order[-1] == ("rollback", None)


async def test_a_deadlock_while_waiting_for_the_rows_is_one_more_round() -> None:
    """The wait takes the rows one after another and can meet a writer taking
    two of them the other way round; Postgres aborts the wait, not the deletion."""
    outcomes = iter([_BUSY, _DEADLOCK, None])
    account = _Account(user_row=lambda _call, _nowait: next(outcomes))

    locked = await account.lock()

    assert locked.user is account.user
    assert account.user_steps() == [("user", _BUSY), ("user", _DEADLOCK), ("user", "nowait")]


async def test_a_database_error_other_than_a_busy_row_is_not_retried() -> None:
    account = _Account(user_row=lambda _call, _nowait: "40001")

    with pytest.raises(DBAPIError) as raised:
        await account.lock()

    assert getattr(raised.value.orig, "sqlstate", None) == "40001"
    assert account.order.count(("savepoint", None)) == 1


async def test_a_database_error_while_waiting_other_than_a_deadlock_is_raised() -> None:
    account = _Account(user_row=lambda call, _nowait: _BUSY if call == 1 else "40001")

    with pytest.raises(DBAPIError) as raised:
        await account.lock()

    assert getattr(raised.value.orig, "sqlstate", None) == "40001"
    assert account.user_steps() == [("user", _BUSY), ("user", "40001")]


async def test_heirs_and_the_app_admin_set_are_taken_without_waiting_after_the_organization() -> (
    None
):
    heir = uuid.uuid4()
    account = _Account(heir=heir)

    locked = await account.lock(app_admins=True)

    assert locked.heirs == frozenset({heir})
    assert locked.app_admins == (account.user_id,)
    rows = account.order[account.order.index(("organization", account.organization.id)) + 1 :]
    assert rows[0] == ("app admins", "nowait")
    assert set(rows[1:3]) == {("user", "nowait"), ("heir", "nowait")}
    assert rows[3] == ("release", None)


async def test_a_vanished_user_is_not_found_and_the_savepoint_is_rolled_back() -> None:
    account = _Account(user_row=lambda _call, _nowait: "gone")

    with pytest.raises(NotFoundError):
        await account.lock()

    assert account.order[-1] == ("rollback", None)


async def test_a_base_found_only_under_the_locks_is_taken_without_waiting() -> None:
    account = _Account(org_scoped=[[_base("kept")], [_base("kept"), _base("late")]])

    await account.lock()

    assert account.order == [
        ("savepoint", None),
        ("name", "kept"),
        ("organization", account.organization.id),
        ("user", "nowait"),
        ("try name", "late"),
        ("release", None),
    ]


async def test_a_base_found_under_the_locks_on_a_busy_name_refuses() -> None:
    account = _Account(org_scoped=[[_base("kept")], [_base("kept"), _base("late")]], granted=False)

    with pytest.raises(ConcurrentChangeError) as refused:
        await account.lock()

    assert refused.value.details == {"collection_name": "late"}
    assert account.order[-1] == ("rollback", None)


def _locked(user_id: uuid.UUID, *, is_app_admin: bool) -> _LockedAccount:
    user = cast(User, SimpleNamespace(id=user_id, is_app_admin=is_app_admin))
    return _LockedAccount(user=user, heirs=frozenset(), app_admins=())


async def test_delete_non_admins_skips_a_promoted_or_vanished_account_under_its_own_lock() -> None:
    """The flag is read under the deletion's lock rather than a row lock taken
    before it (#1139): a user row held across the lock phase is one it could not
    let go of while it waits for the organization (#2682)."""
    ordinary, promoted, vanished = (SimpleNamespace(id=uuid.uuid4()) for _ in range(3))
    outcomes = {
        ordinary.id: _locked(ordinary.id, is_app_admin=False),
        promoted.id: _locked(promoted.id, is_app_admin=True),
    }

    async def lock(user_id: uuid.UUID) -> _LockedAccount:
        if user_id not in outcomes:
            raise NotFoundError(message="User not found")
        return outcomes[user_id]

    service = UserService(MagicMock())
    with (
        patch("app.services.user.user_repo") as users,
        patch.object(service, "_lock_account", new=AsyncMock(side_effect=lock)),
        patch.object(service, "_delete_locked", new=AsyncMock()) as deleted,
    ):
        users.list_non_admins = AsyncMock(return_value=[ordinary, promoted, vanished])

        removed = await service.delete_non_admins()

    assert removed == 1
    deleted.assert_awaited_once_with(outcomes[ordinary.id])


@pytest.mark.parametrize(
    ("organization_id", "uploader_id", "expected"),
    [
        (uuid.uuid4(), uuid.uuid4(), ["organization", "uploader", "status"]),
        (uuid.uuid4(), None, ["organization", "status"]),
        (None, None, ["status"]),
    ],
    ids=["uploaded", "synced", "no-organization"],
)
async def test_a_failed_ingest_holds_its_organization_and_uploader_before_its_status(
    organization_id: uuid.UUID | None, uploader_id: uuid.UUID | None, expected: list[str]
) -> None:
    """The notification after the status write takes both through its keys; an
    account deletion holding them may be waiting for this document's row, so they
    come first (#2682)."""
    order: list[str] = []
    doc = SimpleNamespace(
        id=uuid.uuid4(), organization_id=organization_id, initiated_by_user_id=uploader_id
    )

    def step(name: str) -> AsyncMock:
        return AsyncMock(side_effect=lambda *_a, **_k: order.append(name))

    with (
        patch("app.services.rag_document.rag_document_repo") as documents,
        patch("app.services.rag_document.organization_repo") as organizations,
        patch("app.services.rag_document.user_repo") as users,
        patch("app.services.rag_document.NotificationService") as notifications,
    ):
        documents.get_by_id = AsyncMock(return_value=doc)
        documents.update_status = step("status")
        organizations.hold_key_share = step("organization")
        users.hold_key_share = step("uploader")
        notifications.return_value.ingestion_failed = AsyncMock()

        await RAGDocumentService(MagicMock()).fail_ingestion(str(doc.id), "boom", attempt=1)

    assert order == expected
    if organization_id is not None:
        organizations.hold_key_share.assert_awaited_once_with(ANY, organization_id)
    if uploader_id is not None:
        users.hold_key_share.assert_awaited_once_with(ANY, [uploader_id])


async def test_busy_personal_data_scope_refuses_before_account_teardown() -> None:
    service = UserService(MagicMock())
    with (
        patch("app.services.user.try_hold_subject", new=AsyncMock(return_value=False)),
        patch("app.services.user.organization_repo.list_created_by", new=AsyncMock()) as listing,
        pytest.raises(ConcurrentChangeError, match="account is busy"),
    ):
        await service._lock_account(uuid.uuid4())
    listing.assert_not_awaited()
