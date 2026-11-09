"""Forking a conversation at one of its answers (#2762): who may, from where, and who sees the origin."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.repositories import conversation_repo
from app.repositories.conversation import RunOutcome
from app.services import project as project_service
from app.services.conversation import ConversationService

pytestmark = pytest.mark.anyio

ORG_ID = uuid4()
OWNER_ID = uuid4()


def _conversation(
    *,
    user_id: UUID | None = OWNER_ID,
    project_id: UUID | None = None,
    forked_from: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        user_id=user_id,
        organization_id=ORG_ID,
        project_id=project_id,
        title="Source",
        plan_items=None,
        forked_from_conversation_id=forked_from,
        forked_from_message_id=uuid4() if forked_from else None,
    )


def _message(
    conversation: SimpleNamespace, *, role: str = "assistant", run_id: UUID | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), conversation_id=conversation.id, role=role, run_id=run_id, ordinal=7
    )


def _ctx(user_id: UUID = OWNER_ID) -> AuthContext:
    return AuthContext(user_id=user_id, organization_id=ORG_ID, role="member")


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> ConversationService:
    @asynccontextmanager
    async def no_lock_wait(_db: object, **_options: object) -> AsyncGenerator[None]:
        yield

    monkeypatch.setattr("app.services.conversation.lock_wait_within", no_lock_wait)
    service = ConversationService(AsyncMock())
    monkeypatch.setattr(conversation_repo, "owned_titles", AsyncMock(return_value={}))
    monkeypatch.setattr(conversation_repo, "run_ids_through", AsyncMock(return_value=set()))
    monkeypatch.setattr(conversation_repo, "run_outcomes", AsyncMock(return_value={}))
    monkeypatch.setattr(conversation_repo, "mark_read", AsyncMock())
    monkeypatch.setattr(
        conversation_repo,
        "lock_fork_history",
        AsyncMock(return_value=conversation_repo.ForkRowCounts(1, 0)),
    )
    monkeypatch.setattr(conversation_repo, "fork_payload_bytes", AsyncMock(return_value=0))
    monkeypatch.setattr(conversation_repo, "fork_summary", AsyncMock(return_value=None))
    return service


def _forkable(
    monkeypatch: pytest.MonkeyPatch,
    service: ConversationService,
    source: SimpleNamespace,
    answer: SimpleNamespace | None,
) -> AsyncMock:
    """The source opens for the caller and `answer` is what the message lookup finds."""
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=source))
    monkeypatch.setattr(conversation_repo, "get_fork_point", AsyncMock(return_value=answer))
    fork = _conversation(forked_from=source.id)
    copy = AsyncMock(return_value=fork)
    monkeypatch.setattr(conversation_repo, "fork_conversation", copy)
    return copy


async def _fork(
    service: ConversationService,
    source: SimpleNamespace,
    message_id: UUID,
    *,
    user_id: UUID = OWNER_ID,
):
    return await service.fork(
        source.id,
        message_id=message_id,
        organization_id=ORG_ID,
        user_id=user_id,
        ctx=_ctx(user_id),
    )


class TestTheOwnerForks:
    async def test_the_copy_ends_at_the_chosen_answer_and_names_its_source(
        self, service, monkeypatch
    ):
        source = _conversation()
        answer = _message(source)
        copy = _forkable(monkeypatch, service, source, answer)
        monkeypatch.setattr(
            conversation_repo, "owned_titles", AsyncMock(return_value={source.id: "Source"})
        )

        fork = await _fork(service, source, answer.id)

        assert copy.await_args.kwargs == {
            "source": source,
            "through": answer,
            "restored_summary": None,
        }
        assert fork.forked_from.conversation_id == source.id
        assert fork.forked_from.title == "Source"

    async def test_a_history_whose_runs_all_finished_may_be_forked(self, service, monkeypatch):
        source = _conversation()
        answer = _message(source, run_id=uuid4())
        copy = _forkable(monkeypatch, service, source, answer)
        runs = AsyncMock(return_value={answer.run_id})
        monkeypatch.setattr(conversation_repo, "run_ids_through", runs)
        monkeypatch.setattr(
            conversation_repo,
            "run_outcomes",
            AsyncMock(return_value={answer.run_id: RunOutcome(status="completed", duration_ms=5)}),
        )

        await _fork(service, source, answer.id)

        assert runs.await_args.kwargs == {"conversation_id": source.id, "ordinal": answer.ordinal}
        assert copy.await_count == 1

    async def test_the_owner_has_already_read_the_fork_they_made(self, service, monkeypatch):
        """Every copied answer is one they saw in the source: the fork must not arrive unread."""
        source = _conversation()
        answer = _message(source)
        _forkable(monkeypatch, service, source, answer)
        marked = AsyncMock()
        monkeypatch.setattr(conversation_repo, "mark_read", marked)

        fork = await _fork(service, source, answer.id)

        assert marked.await_args.kwargs == {"user_id": OWNER_ID, "conversation_id": fork.id}

    async def test_a_project_chat_is_forked_only_by_whom_may_start_chats_there(
        self, service, monkeypatch
    ):
        project_id = uuid4()
        source = _conversation(project_id=project_id)
        answer = _message(source)
        copy = _forkable(monkeypatch, service, source, answer)
        check = AsyncMock(side_effect=AuthorizationError(message="no", details={}))
        monkeypatch.setattr(project_service.ProjectService, "check_can_start", check)

        with pytest.raises(AuthorizationError):
            await _fork(service, source, answer.id)

        assert check.await_args.args[-1] == project_id
        assert copy.await_count == 0

    async def test_a_project_chat_forks_into_the_project_when_allowed(self, service, monkeypatch):
        source = _conversation(project_id=uuid4())
        answer = _message(source)
        copy = _forkable(monkeypatch, service, source, answer)
        monkeypatch.setattr(project_service.ProjectService, "check_can_start", AsyncMock())

        await _fork(service, source, answer.id)

        assert copy.await_count == 1


class TestForkingIsRefused:
    async def test_a_reader_who_does_not_own_the_conversation_is_told_it_does_not_exist(
        self, service, monkeypatch
    ):
        """An edit share lets somebody write into the thread; it does not make it theirs to fork."""
        source = _conversation()
        answer = _message(source)
        copy = _forkable(monkeypatch, service, source, answer)

        with pytest.raises(NotFoundError):
            await _fork(service, source, answer.id, user_id=uuid4())

        assert copy.await_count == 0

    async def test_a_thread_nobody_owns_is_not_forked(self, service, monkeypatch):
        source = _conversation(user_id=None)
        answer = _message(source)
        copy = _forkable(monkeypatch, service, source, answer)

        with pytest.raises(NotFoundError):
            await _fork(service, source, answer.id)

        assert copy.await_count == 0

    @pytest.mark.parametrize("found", ["missing", "elsewhere", "user"])
    async def test_only_an_answer_of_this_conversation_is_a_fork_point(
        self, service, monkeypatch, found
    ):
        source = _conversation()
        answer = {
            "missing": None,
            "elsewhere": _message(_conversation()),
            "user": _message(source, role="user"),
        }[found]
        copy = _forkable(monkeypatch, service, source, answer)

        with pytest.raises(NotFoundError):
            await _fork(service, source, uuid4())

        assert copy.await_count == 0

    @pytest.mark.parametrize("status", ["running", "awaiting_approval", "awaiting_answer"])
    async def test_a_history_a_run_is_still_writing_or_waiting_on_is_refused(
        self, service, monkeypatch, status
    ):
        """Including an earlier turn's run: its parked call would wait in the fork for ever."""
        source = _conversation()
        answer = _message(source)
        earlier_run = uuid4()
        copy = _forkable(monkeypatch, service, source, answer)
        monkeypatch.setattr(
            conversation_repo, "run_ids_through", AsyncMock(return_value={earlier_run})
        )
        monkeypatch.setattr(
            conversation_repo,
            "run_outcomes",
            AsyncMock(return_value={earlier_run: RunOutcome(status=status, duration_ms=None)}),
        )

        with pytest.raises(BadRequestError) as refused:
            await _fork(service, source, answer.id)

        assert refused.value.details["run_status"] == status
        assert copy.await_count == 0


class TestTheOriginIsTheOwnersAlone:
    async def test_the_owner_of_both_sees_where_a_fork_came_from(self, service, monkeypatch):
        source_id = uuid4()
        fork = _conversation(forked_from=source_id)
        titles = AsyncMock(return_value={source_id: "Plan"})
        monkeypatch.setattr(conversation_repo, "owned_titles", titles)

        await service._attach_fork_origins([fork], user_id=OWNER_ID)

        assert titles.await_args.kwargs == {"owner_id": OWNER_ID, "conversation_ids": {source_id}}
        assert fork.forked_from.conversation_id == source_id
        assert fork.forked_from.message_id == fork.forked_from_message_id
        assert fork.forked_from.title == "Plan"

    async def test_somebody_a_fork_is_shared_with_sees_no_origin(self, service, monkeypatch):
        fork = _conversation(forked_from=uuid4())
        titles = AsyncMock(return_value={})
        monkeypatch.setattr(conversation_repo, "owned_titles", titles)

        await service._attach_fork_origins([fork], user_id=uuid4())

        assert fork.forked_from is None
        assert titles.await_count == 0

    async def test_a_source_the_owner_no_longer_owns_is_not_named(self, service, monkeypatch):
        """`owned_titles` answers only for sources the reader owns; anything else stays unnamed."""
        fork = _conversation(forked_from=uuid4())
        monkeypatch.setattr(conversation_repo, "owned_titles", AsyncMock(return_value={}))

        await service._attach_fork_origins([fork], user_id=OWNER_ID)

        assert fork.forked_from is None

    async def test_a_read_with_no_reader_or_no_fork_asks_nothing(self, service, monkeypatch):
        titles = AsyncMock(return_value={})
        monkeypatch.setattr(conversation_repo, "owned_titles", titles)
        fork = _conversation(forked_from=uuid4())
        plain = _conversation()

        await service._attach_fork_origins([fork], user_id=None)
        await service._attach_fork_origins([plain], user_id=OWNER_ID)

        assert fork.forked_from is None
        assert plain.forked_from is None
        assert titles.await_count == 0


async def test_a_disappearing_source_does_not_leave_a_partial_copy(service, monkeypatch):
    source = _conversation()
    answer = _message(source)
    copy = _forkable(monkeypatch, service, source, answer)
    monkeypatch.setattr(conversation_repo, "lock_fork_history", AsyncMock(return_value=None))
    with pytest.raises(NotFoundError):
        await _fork(service, source, answer.id)
    copy.assert_not_awaited()


@pytest.mark.parametrize("sqlstate", ["55P03", "40P01", "XX000"])
async def test_lock_conflicts_are_retryable_but_database_bugs_remain_errors(
    service, monkeypatch, sqlstate
):
    from sqlalchemy.exc import DBAPIError

    from app.core.exceptions import ConcurrentChangeError

    class DatabaseFailure(Exception):
        def __init__(self, state: str) -> None:
            self.sqlstate = state

    source = _conversation()
    answer = _message(source)
    copy = _forkable(monkeypatch, service, source, answer)
    failure = DBAPIError("select", {}, DatabaseFailure(sqlstate))
    monkeypatch.setattr(conversation_repo, "lock_fork_history", AsyncMock(side_effect=failure))
    expected = DBAPIError if sqlstate == "XX000" else ConcurrentChangeError
    with pytest.raises(expected):
        await _fork(service, source, answer.id)
    copy.assert_not_awaited()


@pytest.mark.parametrize("permission", ["view", "edit"])
async def test_project_metadata_ignores_legacy_direct_share(service, monkeypatch, permission):
    from app.repositories import conversation_share_repo

    source = _conversation(user_id=uuid4(), project_id=uuid4())
    source.share_permission = permission
    share = AsyncMock(return_value=SimpleNamespace(permission=permission))
    monkeypatch.setattr(conversation_share_repo, "get_share", share)
    await service._attach_share_permission(source, user_id=OWNER_ID)
    assert source.share_permission is None
    share.assert_not_awaited()


async def test_metadata_attaches_recovered_agents_without_loading_history(service, monkeypatch):
    source = _conversation()
    read = AsyncMock(return_value=source)
    monkeypatch.setattr(service, "get_conversation", read)
    attach = AsyncMock()
    monkeypatch.setattr(service, "attach_agents", attach)
    assert (
        await service.get_metadata(source.id, organization_id=ORG_ID, user_id=OWNER_ID, ctx=_ctx())
        is source
    )
    attach.assert_awaited_once_with([source])
    assert "include_messages" not in read.await_args.kwargs


@pytest.mark.parametrize(
    "failure", ["missing", "size", "serialized_size", "count", "timeout", "shape"]
)
async def test_externalized_summary_failure_refuses_before_creating_rows(
    service, monkeypatch, tmp_path, failure
):
    import asyncio

    from pydantic_ai_harness.media import externalize_media

    from app.agents.capabilities.media import OrganizationMediaStore
    from app.core.config import settings
    from app.services import conversation as conversation_service
    from app.services.file_storage import LocalFileStorage

    monkeypatch.setattr(settings, "MEDIA_DIR", tmp_path)
    source = _conversation()
    answer = _message(source)
    copy = _forkable(monkeypatch, service, source, answer)
    store = OrganizationMediaStore(ORG_ID, source.id)
    original = [{"part_kind": "text", "content": "x" * 200}]
    summary = await externalize_media(original, media_store=store, threshold_bytes=100)
    monkeypatch.setattr(
        conversation_repo,
        "fork_summary",
        AsyncMock(return_value=conversation_repo.ForkSummary(summary, 50)),
    )
    if failure == "missing":
        await LocalFileStorage(base_dir=tmp_path).delete_prefix(f"media/{ORG_ID}/{source.id}")
    elif failure == "size":
        monkeypatch.setattr(conversation_service, "MAX_FORK_BYTES", 100)
    elif failure == "serialized_size":
        monkeypatch.setattr(conversation_service, "MAX_FORK_BYTES", 155)
    elif failure == "count":
        monkeypatch.setattr(conversation_service, "MAX_FORK_MEDIA_READS", 0)
    elif failure == "timeout":

        async def slow(*args, **kwargs):
            await asyncio.sleep(10)

        monkeypatch.setattr(LocalFileStorage, "size", slow)
        monkeypatch.setattr(conversation_service, "FORK_MEDIA_TIMEOUT", 0.001)
    else:
        monkeypatch.setattr(
            conversation_repo,
            "fork_summary",
            AsyncMock(return_value=conversation_repo.ForkSummary({"invalid": "shape"}, 50)),
        )
    with pytest.raises(BadRequestError, match="summary cannot be copied"):
        await _fork(service, source, answer.id)
    copy.assert_not_awaited()
