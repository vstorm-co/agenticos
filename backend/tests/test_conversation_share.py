"""Sharing a conversation by email.

The dialog collects an email - people know each other by email, not by UUID -
and it used to send it in `shared_with`, a UUID field, which was a 422 before
the service ever ran. The email now travels in `shared_with_email` and the
server resolves it; these tests pin the resolution and its refusals.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.services.conversation_share import (
    SHARED_MAX_DRAFT_CHARS,
    SHARED_MAX_DRAFTS,
    ConversationShareService,
    shared_drafts,
)

MODULE = "app.services.conversation_share"


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> ConversationShareService:
    monkeypatch.setattr(f"{MODULE}.rate_limit.enforce_conversation_share", AsyncMock())
    return ConversationShareService(AsyncMock())


ORG = uuid.uuid4()


def _conversation(owner: uuid.UUID) -> MagicMock:
    conv = MagicMock()
    conv.user_id = owner
    conv.organization_id = ORG
    conv.project_id = None
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
        user_repo.get_by_id = AsyncMock(return_value=_user(owner))
        member_repo.get = AsyncMock(return_value=MagicMock())
        share_repo.get_share = AsyncMock(return_value=None)
        share_repo.create = AsyncMock(return_value=MagicMock())

        with patch(f"{MODULE}.NotificationService") as notifications:
            notifications.return_value.conversation_shared = AsyncMock()
            await service.share_conversation(
                uuid.uuid4(), owner, shared_with_email="nina@example.com"
            )

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


@pytest.mark.anyio
async def test_a_thread_shared_with_you_says_whether_you_starred_it(
    service: ConversationShareService,
):
    """The listing answered `false` for every row, on the surface where the star
    is most useful: a thread somebody sent you is exactly the kind you keep
    (#1254)."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    reader = uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
        patch(f"{MODULE}.conversation_repo") as conv_repo,
    ):
        share_repo.get_conversations_shared_with_user = AsyncMock(
            return_value=[MagicMock(id=mine), MagicMock(id=theirs)]
        )
        share_repo.count_conversations_shared_with_user = AsyncMock(return_value=2)
        share_repo.share_permissions = AsyncMock(return_value={mine: "view", theirs: "edit"})
        conv_repo.favourite_ids = AsyncMock(return_value={mine})
        named = AsyncMock()

        with patch(f"{MODULE}.ConversationService.attach_listing_state", new=named):
            items, total = await service.list_shared_with_me(reader, organization_id=ORG)

        # Each row reads as the reader's own list does: agents, a run at work, unseen answers.
        assert [item.id for item in named.await_args.args[0]] == [mine, theirs]
        assert named.await_args.kwargs == {"user_id": reader}
        # Only the active organization's shares.
        assert (
            share_repo.get_conversations_shared_with_user.await_args.kwargs["organization_id"]
            == ORG
        )
        assert share_repo.count_conversations_shared_with_user.await_args.kwargs == {
            "organization_id": ORG,
            "include_archived": True,
        }

        assert total == 2
        assert [item.is_favourite for item in items] == [True, False]
        # What the console reads to offer, or withhold, the message box.
        assert [item.share_permission for item in items] == ["view", "edit"]
        assert share_repo.share_permissions.await_args.kwargs["user_id"] == reader
        assert conv_repo.favourite_ids.await_args.kwargs["user_id"] == reader


@pytest.mark.anyio
@pytest.mark.security
@pytest.mark.parametrize("generate_link", [True, False], ids=["link", "person"])
async def test_a_projects_chat_is_never_shared_on_its_own(
    service: ConversationShareService, generate_link: bool
):
    """Who reads it is the project's to say; a link would outlive the starter's
    place in the project and keep showing teammates' later turns."""
    owner = uuid.uuid4()
    chat = _conversation(owner)
    chat.project_id = uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=chat)
        share_repo.create = AsyncMock()
        with pytest.raises(BadRequestError, match="share the project"):
            await service.share_conversation(
                uuid.uuid4(),
                owner,
                generate_link=generate_link,
                shared_with=None if generate_link else uuid.uuid4(),
            )
        share_repo.create.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.security
async def test_a_link_to_a_chat_now_in_a_project_opens_nothing(
    service: ConversationShareService,
):
    chat = _conversation(uuid.uuid4())
    chat.project_id = uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
        pytest.raises(NotFoundError),
    ):
        share_repo.get_by_token = AsyncMock(return_value=MagicMock())
        conv_repo.get_conversation_by_id = AsyncMock(return_value=chat)
        await service.get_by_token("tok")


def _draft_call(call_id: str, args: object, result: str = "Drafted Reply to Marta.") -> MagicMock:
    call = MagicMock()
    call.tool_call_id = call_id
    call.tool_name = "write_draft"
    call.presentation_kind = "draft"
    call.status = "completed"
    call.result = result
    call.args = args
    return call


def _card(text: str = "Hi Marta", title: str = "Reply to Marta") -> dict:
    return {
        "title": title,
        "kind": "email",
        "versions": [{"fields": [{"name": "Body", "text": text, "format": "text"}]}],
    }


def _thread(*calls: MagicMock) -> tuple[MagicMock, MagicMock]:
    message = MagicMock()
    message.id = uuid.uuid4()
    message.tool_calls = list(calls)
    message.parts = None
    conv = MagicMock()
    conv.messages = [message]
    return conv, message


def test_a_shared_conversation_carries_the_drafts_its_turns_wrote() -> None:
    args = _card()
    args["versions"][0]["fields"].insert(0, {"name": "Subject", "text": "Hello"})
    conv, message = _thread(_draft_call("c1", args))

    drafts = shared_drafts(conv)[message.id]

    assert drafts[0].id == "c1"
    assert drafts[0].title == "Reply to Marta"
    assert [f.name for f in drafts[0].versions[0].fields] == ["Subject", "Body"]


def test_a_refused_draft_is_not_shared() -> None:
    conv, _ = _thread(_draft_call("c1", _card(), result="Each version needs a label."))

    assert shared_drafts(conv) == {}


def test_a_call_to_another_tool_is_not_shared_as_a_draft() -> None:
    call = _draft_call("c1", _card())
    call.tool_name = "draw"
    call.presentation_kind = None
    conv, _ = _thread(call)

    assert shared_drafts(conv) == {}


def test_a_draft_whose_call_has_not_completed_is_not_shared() -> None:
    call = _draft_call("c1", _card())
    call.status = "running"
    conv, _ = _thread(call)

    assert shared_drafts(conv) == {}


def test_a_shared_draft_field_keeps_its_indentation() -> None:
    text = "  - item\n    - nested\n"
    conv, message = _thread(_draft_call("c1", _card(text)))

    shared = shared_drafts(conv)[message.id][0]

    assert shared.versions[0].fields[0].text == text


def test_a_stored_draft_that_no_longer_parses_is_left_out() -> None:
    conv, _ = _thread(_draft_call("c1", {"title": "x"}), _draft_call("c2", None))

    assert shared_drafts(conv) == {}


@pytest.mark.security
def test_only_the_newest_fifty_drafts_are_shared() -> None:
    calls = [_draft_call(f"c{i}", _card(title=f"t{i}")) for i in range(SHARED_MAX_DRAFTS + 1)]
    conv, message = _thread(*calls)

    kept = shared_drafts(conv)[message.id]

    assert [d.id for d in kept] == [f"c{i}" for i in range(1, SHARED_MAX_DRAFTS + 1)]


@pytest.mark.security
def test_a_draft_past_the_text_limit_is_left_out() -> None:
    big = _card("x" * 20_000)
    conv, message = _thread(
        _draft_call("small", _card()), *[_draft_call(f"b{i}", big) for i in range(26)]
    )

    kept = shared_drafts(conv)[message.id]

    assert [d.id for d in kept] == [f"b{i}" for i in range(1, 26)]
    assert (
        sum(len(f.text) for d in kept for v in d.versions for f in v.fields)
        <= SHARED_MAX_DRAFT_CHARS
    )


def test_drafts_of_one_turn_follow_the_order_the_turn_wrote_them() -> None:
    first, second = (
        _draft_call("c1", _card(title="first")),
        _draft_call("c2", _card(title="second")),
    )
    conv, message = _thread(second, first)
    message.parts = [
        {"type": "tool", "tool_call_id": "c1"},
        {"type": "text", "content": "and then"},
        {"type": "tool", "tool_call_id": "c2"},
    ]

    assert [d.id for d in shared_drafts(conv)[message.id]] == ["c1", "c2"]


def test_a_draft_no_part_names_keeps_its_place_after_the_ones_that_are_named() -> None:
    named, unnamed = _draft_call("c1", _card()), _draft_call("c2", _card())
    conv, message = _thread(unnamed, named)
    message.parts = [{"type": "tool", "tool_call_id": "c1"}]

    assert [d.id for d in shared_drafts(conv)[message.id]] == ["c1", "c2"]


def test_the_order_is_applied_before_the_newest_fifty_are_kept() -> None:
    calls = [_draft_call(f"c{i}", _card(title=f"t{i}")) for i in range(SHARED_MAX_DRAFTS + 1)]
    conv, message = _thread(*reversed(calls))
    message.parts = [{"type": "tool", "tool_call_id": c.tool_call_id} for c in calls]

    kept = shared_drafts(conv)[message.id]

    assert [d.id for d in kept] == [f"c{i}" for i in range(1, SHARED_MAX_DRAFTS + 1)]


@pytest.mark.anyio
async def test_the_person_a_conversation_is_shared_with_is_told(
    service: ConversationShareService,
):
    """Shared threads are not in the recipient's own list: without a notice they never learn of one."""
    owner, target, conversation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conversation = _conversation(owner)
    conversation.title = "Pricing"
    sharer = _user(owner)
    sharer.full_name = "Kacper"
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.user_repo") as user_repo,
        patch(f"{MODULE}.member_repo") as member_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
        patch(f"{MODULE}.NotificationService") as notifications,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=conversation)
        user_repo.get_by_id = AsyncMock(side_effect=[_user(target), sharer])
        member_repo.get = AsyncMock(return_value=MagicMock())
        share_repo.get_share = AsyncMock(return_value=None)
        share_repo.create = AsyncMock(return_value=MagicMock())
        told = AsyncMock()
        notifications.return_value.conversation_shared = told

        await service.share_conversation(conversation_id, owner, shared_with=target)

    assert told.await_args.kwargs == {
        "recipient": target,
        "organization_id": ORG,
        "conversation_id": conversation_id,
        "title": "Pricing",
        "sharer": "Kacper",
        "actor_user_id": owner,
    }


@pytest.mark.anyio
async def test_a_link_tells_nobody(service: ConversationShareService):
    owner = uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
        patch(f"{MODULE}.NotificationService") as notifications,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        share_repo.create = AsyncMock(return_value=MagicMock())

        await service.share_conversation(uuid.uuid4(), owner, generate_link=True)

    assert notifications.call_count == 0


@pytest.mark.anyio
@pytest.mark.parametrize(("title", "named"), [("Pricing", "'Pricing'"), (None, "'A conversation'")])
async def test_the_notice_names_the_sharer_and_opens_the_conversation(title, named):
    from app.db.models.notification import NotificationEventType
    from app.services.notifications import NotificationService

    recipient, organization_id, conversation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    write = AsyncMock()
    with patch("app.services.notification_center.NotificationCenterService.write", new=write):
        await NotificationService(MagicMock()).conversation_shared(
            recipient=recipient,
            organization_id=organization_id,
            conversation_id=conversation_id,
            title=title,
            sharer="Kacper",
            actor_user_id=uuid.uuid4(),
        )

    kwargs = write.await_args.kwargs
    assert kwargs["recipients"] == [recipient]
    assert kwargs["event_type"] is NotificationEventType.RESOURCE_SHARED
    assert kwargs["occurrence_id"] == f"conversation:{conversation_id}:{recipient}"
    assert kwargs["summary"] == f"Kacper shared {named} with you."
    assert kwargs["context_url"] == f"/chat?id={conversation_id}&org={organization_id}"


@pytest.mark.anyio
async def test_leaving_ends_only_the_readers_own_share(service: ConversationShareService):
    reader, conversation_id = uuid.uuid4(), uuid.uuid4()
    share = MagicMock()
    share.id = uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
        patch(f"{MODULE}.conversation_repo") as conv_repo,
    ):
        share_repo.get_share = AsyncMock(return_value=share)
        share_repo.delete = AsyncMock(return_value=True)
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(uuid.uuid4()))
        conv_repo.set_favourite = AsyncMock()

        await service.leave(conversation_id, reader, organization_id=ORG)

    share_repo.get_share.assert_awaited_once_with(service.db, conversation_id, reader)
    share_repo.delete.assert_awaited_once_with(service.db, share.id)
    assert conv_repo.set_favourite.await_args.kwargs == {
        "user_id": reader,
        "conversation_id": conversation_id,
        "favourite": False,
    }


@pytest.mark.anyio
@pytest.mark.security
@pytest.mark.parametrize("found", ["no share", "another organization"])
async def test_leaving_a_conversation_never_shared_with_you_here_is_refused(
    service: ConversationShareService, found: str
):
    """The leave route acts in the active organization, as the list it was picked from."""
    conversation = _conversation(uuid.uuid4())
    if found == "another organization":
        conversation.organization_id = uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
        patch(f"{MODULE}.conversation_repo") as conv_repo,
    ):
        share_repo.get_share = AsyncMock(return_value=None if found == "no share" else MagicMock())
        share_repo.delete = AsyncMock()
        conv_repo.get_conversation_by_id = AsyncMock(return_value=conversation)

        with pytest.raises(NotFoundError):
            await service.leave(uuid.uuid4(), uuid.uuid4(), organization_id=ORG)

    share_repo.delete.assert_not_awaited()


def _share(conversation_id: uuid.UUID, *, token: str | None = None) -> MagicMock:
    share = MagicMock()
    share.id = uuid.uuid4()
    share.conversation_id = conversation_id
    share.share_token = token
    return share


@pytest.mark.anyio
async def test_the_owner_turns_a_view_share_into_an_edit_one(service: ConversationShareService):
    owner, conversation_id = uuid.uuid4(), uuid.uuid4()
    share = _share(conversation_id)
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        share_repo.get_by_id = AsyncMock(return_value=share)
        share_repo.set_permission = AsyncMock(return_value=share)
        share_repo.lock_private_publication = AsyncMock(return_value=True)

        await service.change_permission(
            conversation_id, share.id, owner, permission="edit", organization_id=ORG
        )

    assert share_repo.set_permission.await_args.kwargs == {"share": share, "permission": "edit"}


@pytest.mark.security
@pytest.mark.anyio
async def test_only_the_owner_changes_a_share(service: ConversationShareService):
    """The person a view share names must not be able to widen it to edit for themselves."""
    conversation_id = uuid.uuid4()
    share = _share(conversation_id)
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(uuid.uuid4()))
        share_repo.get_by_id = AsyncMock(return_value=share)
        share_repo.set_permission = AsyncMock()

        with pytest.raises(AuthorizationError):
            await service.change_permission(
                conversation_id, share.id, uuid.uuid4(), permission="edit", organization_id=ORG
            )

    share_repo.set_permission.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("found", ["no share", "another conversation's"])
async def test_a_share_that_is_not_this_conversations_is_missing(
    service: ConversationShareService, found: str
):
    owner, conversation_id = uuid.uuid4(), uuid.uuid4()
    share = None if found == "no share" else _share(uuid.uuid4())
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        share_repo.get_by_id = AsyncMock(return_value=share)
        share_repo.set_permission = AsyncMock()

        with pytest.raises(NotFoundError):
            await service.change_permission(
                conversation_id, uuid.uuid4(), owner, permission="edit", organization_id=ORG
            )

    share_repo.set_permission.assert_not_awaited()


@pytest.mark.security
@pytest.mark.anyio
async def test_a_share_link_stays_view_only(service: ConversationShareService):
    owner, conversation_id = uuid.uuid4(), uuid.uuid4()
    share = _share(conversation_id, token="tok")
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        share_repo.get_by_id = AsyncMock(return_value=share)
        share_repo.set_permission = AsyncMock()

        with pytest.raises(BadRequestError):
            await service.change_permission(
                conversation_id, share.id, owner, permission="edit", organization_id=ORG
            )

    share_repo.set_permission.assert_not_awaited()


def test_a_renamed_draft_is_shared_using_its_stable_result_identity() -> None:
    call = _draft_call("renamed", _card())
    call.tool_name = "prepare_reply"
    conversation, message = _thread(call)
    drafts = shared_drafts(conversation)
    assert drafts[message.id][0].title == "Reply to Marta"


def test_untrusted_tool_output_cannot_spoof_a_shared_draft() -> None:
    call = _draft_call(
        "spoof", _card("private arguments"), result="Drafted fake. [agenticos:draft:v1]"
    )
    call.presentation_kind = None
    conversation, _ = _thread(call)
    assert shared_drafts(conversation) == {}


@pytest.mark.anyio
async def test_edit_access_uses_the_workspace_publication_fence(
    service: ConversationShareService,
) -> None:
    owner, conversation_id = uuid.uuid4(), uuid.uuid4()
    share = _share(conversation_id)
    with (
        patch(f"{MODULE}.conversation_repo") as conversations,
        patch(f"{MODULE}.conversation_share_repo") as shares,
    ):
        conversations.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        shares.get_by_id = AsyncMock(return_value=share)
        shares.lock_private_publication = AsyncMock(return_value=False)
        shares.set_permission = AsyncMock()
        with pytest.raises(NotFoundError):
            await service.change_permission(
                conversation_id, share.id, owner, permission="edit", organization_id=ORG
            )
        shares.set_permission.assert_not_awaited()


@pytest.mark.anyio
async def test_a_project_chat_does_not_gain_an_individual_edit_share(
    service: ConversationShareService,
) -> None:
    owner, conversation_id = uuid.uuid4(), uuid.uuid4()
    conversation = _conversation(owner)
    conversation.project_id = uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conversations,
        patch(f"{MODULE}.conversation_share_repo") as shares,
    ):
        conversations.get_conversation_by_id = AsyncMock(return_value=conversation)
        shares.get_by_id = AsyncMock(return_value=_share(conversation_id))
        shares.set_permission = AsyncMock()
        with pytest.raises(BadRequestError):
            await service.change_permission(
                conversation_id, uuid.uuid4(), owner, permission="edit", organization_id=ORG
            )
        shares.set_permission.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.security
async def test_a_limited_share_persists_nothing_and_sends_no_notification(
    service: ConversationShareService, monkeypatch: pytest.MonkeyPatch
):
    from app.core.exceptions import RateLimitError

    owner, target = uuid.uuid4(), uuid.uuid4()
    with (
        patch(f"{MODULE}.conversation_repo") as conv_repo,
        patch(f"{MODULE}.user_repo") as user_repo,
        patch(f"{MODULE}.member_repo") as member_repo,
        patch(f"{MODULE}.conversation_share_repo") as share_repo,
        patch(f"{MODULE}.NotificationService") as notifications,
    ):
        conv_repo.get_conversation_by_id = AsyncMock(return_value=_conversation(owner))
        user_repo.get_by_id = AsyncMock(return_value=_user(target))
        member_repo.get = AsyncMock(return_value=MagicMock())
        share_repo.get_share = AsyncMock(return_value=None)
        share_repo.create = AsyncMock()
        notification = AsyncMock()
        notifications.return_value.conversation_shared = notification
        monkeypatch.setattr(
            f"{MODULE}.rate_limit.enforce_conversation_share",
            AsyncMock(
                side_effect=RateLimitError(
                    message="Too many shares", details={"retry_after_seconds": 60}
                )
            ),
        )
        with pytest.raises(RateLimitError):
            await service.share_conversation(uuid.uuid4(), owner, shared_with=target)
        share_repo.create.assert_not_awaited()
        notification.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("enabled", [True, False])
async def test_public_chat_footer_uses_its_organization(
    service: ConversationShareService, enabled: bool
) -> None:
    from app.db.models.organization import Organization

    chat = _conversation(uuid.uuid4())
    chat.id, chat.title, chat.messages = uuid.uuid4(), "Shared report", []
    share = MagicMock(id=uuid.uuid4(), permission="view")
    lookup = AsyncMock(return_value=Organization(public_agenticos_attribution=enabled))
    with (
        patch(f"{MODULE}.conversation_share_repo.get_by_token", new=AsyncMock(return_value=share)),
        patch(
            f"{MODULE}.conversation_repo.get_conversation_by_id", new=AsyncMock(return_value=chat)
        ),
        patch(f"{MODULE}.organization_repo.get_by_id", new=lookup),
    ):
        result = await service.get_by_token("token")
    assert result.show_agenticos_attribution is enabled
    lookup.assert_awaited_once_with(service.db, ORG)


@pytest.mark.anyio
async def test_public_chat_without_its_organization_is_not_served(
    service: ConversationShareService,
) -> None:
    with (
        patch(
            f"{MODULE}.conversation_share_repo.get_by_token",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            f"{MODULE}.conversation_repo.get_conversation_by_id",
            new=AsyncMock(return_value=_conversation(uuid.uuid4())),
        ),
        patch(f"{MODULE}.organization_repo.get_by_id", new=AsyncMock(return_value=None)),
        pytest.raises(NotFoundError),
    ):
        await service.get_by_token("token")
