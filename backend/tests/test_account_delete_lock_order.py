"""The order account deletion takes its locks in (#2638).

The deadlocks the order prevents are shown on Postgres in
`tests/integration/test_account_delete_spend_deadlock.py`.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConcurrentChangeError
from app.services.user import UserService

pytestmark = pytest.mark.anyio


def _base(collection_name: str) -> SimpleNamespace:
    return SimpleNamespace(collection_name=collection_name)


class _Calls:
    """The lock and delete steps in the order the deletion took them."""

    def __init__(self) -> None:
        self.order: list[tuple[str, object]] = []

    def step(self, name: str, result: object = None) -> AsyncMock:
        async def called(*args: object, **_: object) -> object:
            self.order.append((name, args[-1]))
            return result

        return AsyncMock(side_effect=called)


async def test_teardown_names_are_held_sorted_and_once_before_the_organization_rows() -> None:
    calls = _Calls()
    user_id = uuid.uuid4()
    first, second = sorted([uuid.uuid4(), uuid.uuid4()])
    personal = [SimpleNamespace(id=second), SimpleNamespace(id=first)]
    org_scoped = {first: [_base("beta")], second: [_base("alpha"), _base("delta")]}

    with (
        patch("app.services.user.knowledge_base_repo") as bases,
        patch("app.services.user.organization_repo") as organizations,
        patch("app.services.user.hold_name", new=calls.step("name")),
        patch("app.services.user.try_hold_name", new=calls.step("try name", True)),
    ):
        bases.list_personal_by_owner = AsyncMock(return_value=[_base("delta"), _base("gamma")])
        bases.list_org_scoped = AsyncMock(side_effect=lambda _db, org_id: org_scoped[org_id])
        organizations.get_by_id_for_update = calls.step("organization")

        await UserService(MagicMock())._lock_personal_organizations(user_id, personal)

    assert calls.order == [
        ("name", "alpha"),
        ("name", "beta"),
        ("name", "delta"),
        ("name", "gamma"),
        ("organization", first),
        ("organization", second),
    ]


class _LateBase:
    """The second read, under the organization lock, finds a base the first missed."""

    def __init__(self, *, granted: bool) -> None:
        self.calls = _Calls()
        self.organization = SimpleNamespace(id=uuid.uuid4())
        self.granted = granted

    async def lock(self) -> None:
        reads = iter([[_base("kept")], [_base("kept"), _base("late")]])
        with (
            patch("app.services.user.knowledge_base_repo") as bases,
            patch("app.services.user.organization_repo") as organizations,
            patch("app.services.user.hold_name", new=self.calls.step("name")),
            patch("app.services.user.try_hold_name", new=self.calls.step("try name", self.granted)),
        ):
            bases.list_personal_by_owner = AsyncMock(return_value=[])
            bases.list_org_scoped = AsyncMock(side_effect=lambda *_: next(reads))
            organizations.get_by_id_for_update = self.calls.step("organization")

            await UserService(MagicMock())._lock_personal_organizations(
                uuid.uuid4(), [self.organization]
            )


async def test_a_base_found_only_under_the_organization_lock_is_taken_without_waiting() -> None:
    late = _LateBase(granted=True)

    await late.lock()

    assert late.calls.order == [
        ("name", "kept"),
        ("organization", late.organization.id),
        ("try name", "late"),
    ]


async def test_a_base_found_under_the_organization_lock_on_a_busy_name_refuses() -> None:
    late = _LateBase(granted=False)

    with pytest.raises(ConcurrentChangeError) as refused:
        await late.lock()

    assert refused.value.details == {"collection_name": "late"}
