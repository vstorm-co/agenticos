"""Sharing a conversation by email.

The dialog collects an email - people know each other by email, not by UUID -
and it used to send it in `shared_with`, a UUID field, which was a 422 before
the service ever ran. The email now travels in `shared_with_email` and the
server resolves it; these tests pin the resolution and its refusals.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AlreadyExistsError, NotFoundError
from app.services.conversation_share import ConversationShareService

MODULE = "app.services.conversation_share"


@pytest.fixture
def service() -> ConversationShareService:
    return ConversationShareService(AsyncMock())


ORG = uuid.uuid4()


def _conversation(owner: uuid.UUID) -> MagicMock:
    conv = MagicMock()
    conv.user_id = owner
    conv.organization_id = ORG
    return conv


def _user(user_id: uuid.UUID) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    return user


@pytest.mark.anyio
async def test_an_email_resolves_to_the_user_it_names(service: ConversationShareService):
    owner, target = uuid.uuid4(), uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.user_repo") as user_repo,
        patch(f"{MODULE}.member_repo") as member_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        user_repo.get_by_email = AsyncMock(return_value=_user(target))
        member_repo.get = AsyncMock(return_value=MagicMock())
        share_repo.get_share = AsyncMock(return_value=None)
        share_repo.create = AsyncMock(return_value=MagicMock())

        await service.share_conversation(uuid.uuid4(), owner, shared_with_email="nina@example.com")

        user_repo.get_by_email.assert_awaited_once_with(service.db, "nina@example.com")
        member_repo.get.assert_awaited_once_with(service.db, organization_id=ORG, user_id=target)
        assert share_repo.create.await_args.kwargs["shared_with"] == target


@pytest.mark.anyio
async def test_an_email_nobody_registered_is_refused(service: ConversationShareService):
    owner = uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.user_repo") as user_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        user_repo.get_by_email = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError):
            await service.share_conversation(
                uuid.uuid4(), owner, shared_with_email="ghost@example.com"
            )


@pytest.mark.anyio
async def test_sharing_with_your_own_email_is_refused(service: ConversationShareService):
    """The self-share check runs after resolution, so it catches the email
    spelling of yourself, not only your UUID."""
    owner = uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.user_repo") as user_repo,
        patch(f"{MODULE}.member_repo") as member_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        user_repo.get_by_email = AsyncMock(return_value=_user(owner))
        member_repo.get = AsyncMock(return_value=MagicMock())

        with pytest.raises(AlreadyExistsError):
            await service.share_conversation(
                uuid.uuid4(), owner, shared_with_email="me@example.com"
            )


@pytest.mark.anyio
async def test_neither_id_email_nor_link_is_refused(service: ConversationShareService):
    owner = uuid.uuid4()
    with patch(f"{MODULE}.conversation_repo") as conv_repo:
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))

        with pytest.raises(NotFoundError):
            await service.share_conversation(uuid.uuid4(), owner)


@pytest.mark.anyio
async def test_an_email_outside_the_organization_is_refused_as_not_found(
    service: ConversationShareService,
):
    """The account exists on the deployment but not in this tenant, so the read
    path would refuse it on the tenant and the share would be unreadable (#930).
    Refused at share time, and worded exactly like an address nobody registered -
    to name it a member of another org would be a cross-tenant existence probe."""
    owner, outsider = uuid.uuid4(), uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.user_repo") as user_repo,
        patch(f"{MODULE}.member_repo") as member_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        user_repo.get_by_email = AsyncMock(return_value=_user(outsider))
        member_repo.get = AsyncMock(return_value=None)
        share_repo.create = AsyncMock()

        with pytest.raises(NotFoundError, match="No user with that email"):
            await service.share_conversation(
                uuid.uuid4(), owner, shared_with_email="bob@other-company.com"
            )

        share_repo.create.assert_not_awaited()


@pytest.mark.anyio
async def test_an_id_outside_the_organization_is_refused_as_not_found(
    service: ConversationShareService,
):
    owner, outsider = uuid.uuid4(), uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.user_repo") as user_repo,
        patch(f"{MODULE}.member_repo") as member_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        user_repo.get_by_id = AsyncMock(return_value=_user(outsider))
        member_repo.get = AsyncMock(return_value=None)
        share_repo.create = AsyncMock()

        with pytest.raises(NotFoundError, match="User not found"):
            await service.share_conversation(uuid.uuid4(), owner, shared_with=outsider)

        share_repo.create.assert_not_awaited()
