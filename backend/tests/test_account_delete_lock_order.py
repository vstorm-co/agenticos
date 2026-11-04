"""The order account deletion takes its locks in (#2638, #2682).

The deadlocks the order prevents are shown on Postgres in
`tests/integration/test_account_delete_spend_deadlock.py` and
`tests/integration/test_account_delete_writer_deadlock.py`.
"""

import itertools
import uuid
from collections.abc import Callable
from types import SimpleNamespace, TracebackType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import AuthorizationError, ConcurrentChangeError, NotFoundError
from app.services.rag_document import RAGDocumentService
from app.services.user import _ACCOUNT_LOCK_ATTEMPTS, UserService, _LockedAccount

pytestmark = pytest.mark.anyio

Step = tuple[str, object]


def _base(collection_name: str) -> SimpleNamespace:
    return SimpleNamespace(collection_name=collection_name)


def _db_error(sqlstate: str) -> DBAPIError:
    orig = Exception("lock")
    orig.sqlstate = sqlstate  # type: ignore[attr-defined] - asyncpg's error carries it
    return DBAPIError("SELECT", {}, orig)


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

    `busy` says, per call of the user-row lock, whether `NOWAIT` finds it taken.
    """

    def __init__(
        self,
        *,
        busy: Callable[[int], bool] = lambda _call: False,
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
        self.busy = busy
        self.personal = personal or []
        self.org_scoped = iter(org_scoped) if org_scoped else itertools.repeat([])
        self.heir = heir
        self.granted = granted
        self.user_calls = 0
        db = MagicMock()
        db.begin_nested = lambda: _Savepoint(self.order)
        self.service = UserService(db)

    def _step(self, name: str, result: object = None) -> AsyncMock:
        async def called(*args: object, **kwargs: object) -> object:
            self.order.append((name, kwargs.get("nowait", args[-1])))
            return result

        return AsyncMock(side_effect=called)

    async def _user(self, _db: object, user_id: uuid.UUID, *, nowait: bool = False) -> object:
        self.user_calls += 1
        if nowait and self.busy(self.user_calls):
            self.order.append(("user busy", user_id))
            raise _db_error("55P03")
        self.order.append(("user", nowait))
        return self.user

    async def lock(self, *, app_admins: bool = False) -> _LockedAccount:
        with (
            patch("app.services.user.knowledge_base_repo") as bases,
            patch("app.services.user.organization_repo") as organizations,
            patch("app.services.user.member_repo") as members,
            patch("app.services.user.user_repo") as users,
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
            users.get_by_id_for_no_key_update = self._step("heir")
            users.app_admin_ids_for_update = self._step("app admins", [self.user_id])
            return await self.service._lock_account(self.user_id, app_admins=app_admins)


async def test_names_then_organization_then_the_user_row_without_waiting() -> None:
    account = _Account(personal=[_base("delta"), _base("alpha")])

    locked = await account.lock()

    assert locked.user is account.user
    assert account.order == [
        ("savepoint", None),
        ("name", "alpha"),
        ("name", "delta"),
        ("organization", account.organization.id),
        ("user", True),
        ("release", None),
    ]


async def test_a_busy_user_row_lets_everything_go_waits_for_it_and_starts_again() -> None:
    """The writer holding the user row may be waiting for the organization this
    holds, so the phase rolls back and waits for the row holding nothing."""
    account = _Account(busy=lambda call: call == 1, personal=[_base("alpha")])

    await account.lock()

    assert account.order == [
        ("savepoint", None),
        ("name", "alpha"),
        ("organization", account.organization.id),
        ("user busy", account.user_id),
        ("rollback", None),
        ("savepoint", None),
        ("user", False),
        ("rollback", None),
        ("savepoint", None),
        ("name", "alpha"),
        ("organization", account.organization.id),
        ("user", True),
        ("release", None),
    ]


async def test_a_user_row_busy_at_every_attempt_refuses_and_deletes_nothing() -> None:
    account = _Account(busy=lambda _call: True)

    with pytest.raises(ConcurrentChangeError) as refused:
        await account.lock()

    assert refused.value.details == {
        "user_id": account.user_id,
        "attempts": _ACCOUNT_LOCK_ATTEMPTS,
    }
    assert account.order.count(("user busy", account.user_id)) == _ACCOUNT_LOCK_ATTEMPTS
    assert account.order[-1] == ("rollback", None)


async def test_a_database_error_other_than_a_busy_row_is_not_retried() -> None:
    account = _Account()
    serialization = _db_error("40001")

    async def failing(*_args: object, **_kwargs: object) -> object:
        raise serialization

    account._user = failing  # type: ignore[method-assign]

    with pytest.raises(DBAPIError) as raised:
        await account.lock()

    assert raised.value is serialization
    assert account.order[-1] == ("rollback", None)
    assert ("savepoint", None) not in account.order[1:]


async def test_heirs_and_the_app_admin_set_are_taken_without_waiting_after_the_organization() -> (
    None
):
    heir = uuid.uuid4()
    account = _Account(heir=heir)

    locked = await account.lock(app_admins=True)

    assert locked.heirs == frozenset({heir})
    assert locked.app_admins == (account.user_id,)
    rows = account.order[account.order.index(("organization", account.organization.id)) + 1 :]
    assert rows[0] == ("app admins", True)
    assert set(rows[1:3]) == {("user", True), ("heir", True)}
    assert rows[3] == ("release", None)


async def test_a_vanished_user_is_not_found_and_the_savepoint_is_rolled_back() -> None:
    account = _Account()

    async def gone(*_args: object, **_kwargs: object) -> None:
        account.order.append(("user", None))

    account._user = gone  # type: ignore[method-assign]

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
        ("user", True),
        ("try name", "late"),
        ("release", None),
    ]


async def test_a_base_found_under_the_locks_on_a_busy_name_refuses() -> None:
    account = _Account(org_scoped=[[_base("kept")], [_base("kept"), _base("late")]], granted=False)

    with pytest.raises(ConcurrentChangeError) as refused:
        await account.lock()

    assert refused.value.details == {"collection_name": "late"}
    assert account.order[-1] == ("rollback", None)


def _locked(user: object, *, app_admins: tuple[uuid.UUID, ...] = ()) -> _LockedAccount:
    return _LockedAccount(user=user, heirs=frozenset(), app_admins=app_admins)  # type: ignore[arg-type]


async def test_admin_delete_locks_the_admin_set_inside_the_phase_and_refuses_the_last() -> None:
    target = SimpleNamespace(id=uuid.uuid4(), is_app_admin=True)
    service = UserService(MagicMock())
    lock = AsyncMock(return_value=_locked(target, app_admins=(target.id,)))

    with (
        patch.object(service, "_lock_account", new=lock),
        patch.object(service, "_delete_locked", new=AsyncMock()) as deleted,
        pytest.raises(AuthorizationError),
    ):
        await service.admin_delete(target.id, acting_admin_id=uuid.uuid4())

    lock.assert_awaited_once_with(target.id, app_admins=True)
    deleted.assert_not_awaited()


async def test_delete_non_admins_skips_a_promoted_or_vanished_account_under_its_own_lock() -> None:
    """The flag is read under the deletion's lock rather than a row lock taken
    before it (#1139): a user row held across the lock phase is one it could not
    let go of while it waits for the organization (#2682)."""
    ordinary, promoted, vanished = (SimpleNamespace(id=uuid.uuid4()) for _ in range(3))
    outcomes = {
        ordinary.id: _locked(SimpleNamespace(id=ordinary.id, is_app_admin=False)),
        promoted.id: _locked(SimpleNamespace(id=promoted.id, is_app_admin=True)),
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
    users.get_by_id_for_update.assert_not_called()


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
        assert organizations.hold_key_share.await_args.args[1] == organization_id
    if uploader_id is not None:
        assert users.hold_key_share.await_args.args[1] == [uploader_id]
