"""Sharing a conversation by email.

The dialog collects an email - people know each other by email, not by UUID -
and it used to send it in `shared_with`, a UUID field, which was a 422 before
the service ever ran. The email now travels in `shared_with_email` and the
server resolves it; these tests pin the resolution and its refusals.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.services.conversation_share import (
    SHARED_MAX_DRAFT_CHARS,
    SHARED_MAX_DRAFTS,
    ConversationShareService,
    shared_drafts,
)

MODULE = "app.services.conversation_share"


@pytest.fixture
def service() -> ConversationShareService:
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
        conv_repo.favourite_ids = AsyncMock(return_value={mine})

        items, total = await service.list_shared_with_me(reader)

        assert total == 2
        assert [item.is_favourite for item in items] == [True, False]
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


def test_a_renamed_draft_is_shared_using_its_stable_result_identity() -> None:
    from app.agents.capabilities.drafts._spec import DRAFT_IDENTITY

    call = _draft_call("renamed", _card())
    call.tool_name = "prepare_reply"
    call.result += f" {DRAFT_IDENTITY}"
    conversation, message = _thread(call)
    drafts = shared_drafts(conversation)
    assert drafts[message.id][0].title == "Reply to Marta"
