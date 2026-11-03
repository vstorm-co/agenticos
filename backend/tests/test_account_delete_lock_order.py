"""Account deletion locks the personal organization before deleting under it (#2638).

An ingest's spend locks the organization and then the document. Deleting the
personal bases' documents before the organization's `FOR UPDATE` inverted that
order and deadlocked the two; `tests/integration/test_account_delete_spend_deadlock.py`
shows the deadlock on Postgres. These pin the order the deletion now takes its
locks in: the teardown names, sorted, then the organization, then the deletes.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


async def test_the_personal_organization_is_locked_before_its_documents_are_deleted() -> None:
    """The personal teardown deletes documents, bases and sources; the organization
    row is held `FOR UPDATE` before any of it, not first at the purge."""
    calls = _Calls()
    user_id = uuid.uuid4()
    personal = SimpleNamespace(id=uuid.uuid4(), is_personal=True)
    service = UserService(MagicMock(), vector_store=MagicMock())

    with (
        patch("app.services.user.organization_repo") as organizations,
        patch("app.services.user.member_repo") as members,
        patch("app.services.user.organization_secret_repo") as secrets,
        patch("app.services.user.conversation_repo") as conversations,
        patch("app.services.user.knowledge_base_repo") as bases,
        patch("app.services.user.hold_name", new=calls.step("name")),
        patch("app.services.user.OrganizationService") as organization_service,
        patch.object(service, "_purge_personal_collections", new=calls.step("purge personal")),
    ):
        organizations.list_created_by = AsyncMock(return_value=[personal])
        organizations.list_owned_by = AsyncMock(return_value=[personal])
        organizations.get_by_id_for_update = calls.step("organization")
        members.other_owner_id = AsyncMock(return_value=None)
        secrets.promote_owned_private_to_org = AsyncMock()
        conversations.release_project_chats = AsyncMock()
        bases.list_personal_by_owner = AsyncMock(return_value=[_base("mine")])
        bases.list_org_scoped = AsyncMock(return_value=[])
        organization_service.return_value.purge = calls.step("purge organization")

        await service._release_owned_rows(user_id, locked_heirs=frozenset())

    assert calls.order == [
        ("name", "mine"),
        ("organization", personal.id),
        ("purge personal", user_id),
        ("purge organization", personal),
    ]
