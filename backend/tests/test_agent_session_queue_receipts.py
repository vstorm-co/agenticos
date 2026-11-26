"""Receipt-backed queue frames and their durable chat-session outcomes."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from app.agents.steering import SteeringInbox
from app.core.exceptions import AlreadyExistsError, AuthorizationError, NotFoundError
from app.schemas.conversation import ChatPageContext, MessagePart
from app.schemas.local_target import LocalTarget
from app.schemas.mention import Mentionable, MentionRef
from app.services import agent_session as agent_session_module
from app.services.agent_chat import OpenedRun
from app.services.agent_session import AgentSession
from app.services.mentions import ResolvedMentions
from tests.test_agent_session import (
    _CONVERSATION,
    _chat,
    _fake_db_context,
    _finished_turn,
    _sent_events,
    _session,
)

pytestmark = pytest.mark.anyio


@asynccontextmanager
async def _running_turn(
    session: AgentSession,
    *,
    conversation_id: UUID | None = None,
    agent_id: UUID | None = None,
    run_id: UUID | None = None,
) -> AsyncIterator[SteeringInbox]:
    """Make a live turn that can receive a frame without starting a runner."""
    conversation = conversation_id or uuid4()
    agent = agent_id or uuid4()
    run = run_id or uuid4()
    inbox = SteeringInbox()
    finished = asyncio.Event()
    task = asyncio.create_task(finished.wait())
    session.current_conversation_id = str(conversation)
    session._turn_agent_id = agent
    session._turn_runs = [OpenedRun(run_id=run, model_label="test", agent_version_id=None)]
    session._steering = inbox
    session._turn_task = task
    try:
        yield inbox
    finally:
        finished.set()
        await task


def _accepted_receipt(
    *,
    conversation_id: UUID | None = None,
    agent_id: UUID | None = None,
    receipt_id: UUID | None = None,
    state: str = "pending",
    **overrides: Any,
) -> SimpleNamespace:
    """The frozen server-side payload returned after owner-scoped lookup."""
    values: dict[str, Any] = {
        "id": receipt_id or uuid4(),
        "conversation_id": conversation_id or UUID(_CONVERSATION),
        "agent_id": agent_id or uuid4(),
        "state": state,
        "content": "the accepted question",
        "file_ids": [],
        "mentions": [],
        "reply_to_message_id": None,
        "reply_to_excerpt": None,
        "page_context": None,
        "local_target": None,
        "message_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class TestReceiptSteerFrames:
    @pytest.mark.security
    async def test_a_malformed_receipt_id_is_refused_before_database_access(self) -> None:
        session = _session()

        await session.handle_frame({"type": "steer", "accepted_queue_id": "not-a-uuid"})

        assert _sent_events(session) == [
            ("error", {"message": "That is not a valid accepted queue id"})
        ]

    @pytest.mark.security
    async def test_a_revoked_socket_does_not_reconcile_a_late_receipt(self) -> None:
        session = _session()
        receipt_id = uuid4()

        with patch.object(session, "_reauthorize", new=AsyncMock(return_value=False)):
            await session.handle_frame(
                {"type": "steer", "accepted_queue_id": str(receipt_id), "text": "ignored"}
            )

        assert _sent_events(session) == []

    @pytest.mark.security
    async def test_a_revoked_live_turn_does_not_claim_a_receipt(self) -> None:
        session = _session()
        receipt_id = uuid4()

        async with _running_turn(session):
            with patch.object(session, "_reauthorize_write", new=AsyncMock(return_value=False)):
                await session.handle_frame(
                    {"type": "steer", "accepted_queue_id": str(receipt_id), "text": "ignored"}
                )

        assert _sent_events(session) == []

    async def test_a_plain_steer_that_loses_its_turn_is_handed_back(self) -> None:
        session = _session()

        async with _running_turn(session):

            async def turn_ended_during_authorization() -> bool:
                session._steering = None
                return True

            with patch.object(
                session,
                "_reauthorize_write",
                new=AsyncMock(side_effect=turn_ended_during_authorization),
            ):
                await session.handle_frame({"type": "steer", "text": "use the latest totals"})

        assert _sent_events(session) == [("steer_unapplied", {"texts": ["use the latest totals"]})]

    async def test_a_live_receipt_without_a_run_reconciles_its_durable_status(self) -> None:
        session = _session()
        conversation_id = uuid4()
        receipt_id = uuid4()
        async with _running_turn(session, conversation_id=conversation_id):
            session._turn_runs = []
            service = MagicMock()
            service.get_for_owner = AsyncMock(
                return_value=SimpleNamespace(state="pending", steering_run_id=None)
            )
            with (
                patch("app.services.agent_session.get_db_context", side_effect=_fake_db_context),
                patch.object(session, "_chat_context", new=AsyncMock(return_value=MagicMock())),
                patch.object(session, "_reauthorize_write", new=AsyncMock(return_value=True)),
                patch(
                    "app.services.agent_session.AcceptedQueuedMessageService", return_value=service
                ),
            ):
                await session.handle_frame({"type": "steer", "accepted_queue_id": str(receipt_id)})

        assert _sent_events(session) == [
            ("steer_unapplied", {"accepted_queue_id": str(receipt_id), "run_id": None})
        ]
        service.claim_for_steer.assert_not_called()

    @pytest.mark.security
    async def test_an_unavailable_receipt_does_not_enter_the_live_inbox(self) -> None:
        session = _session()
        receipt_id = uuid4()
        refusal = NotFoundError(message="Accepted message is unavailable")
        async with _running_turn(session) as inbox:
            service = MagicMock()
            service.get_for_owner = AsyncMock(side_effect=refusal)
            with (
                patch("app.services.agent_session.get_db_context", side_effect=_fake_db_context),
                patch.object(session, "_chat_context", new=AsyncMock(return_value=MagicMock())),
                patch.object(session, "_reauthorize_write", new=AsyncMock(return_value=True)),
                patch(
                    "app.services.agent_session.AcceptedQueuedMessageService", return_value=service
                ),
            ):
                await session.handle_frame({"type": "steer", "accepted_queue_id": str(receipt_id)})

        assert inbox.receipt(receipt_id) is None
        assert _sent_events(session) == [
            (
                "error",
                {"message": refusal.message, "accepted_queue_id": str(receipt_id)},
            )
        ]

    async def test_a_newly_claimed_receipt_is_added_to_the_live_inbox(self) -> None:
        session = _session()
        receipt_id = uuid4()
        async with _running_turn(session) as inbox:
            service = MagicMock()
            service.get_for_owner = AsyncMock(
                return_value=SimpleNamespace(content="frozen question")
            )
            service.claim_for_steer = AsyncMock(return_value="claimed")
            with (
                patch("app.services.agent_session.get_db_context", side_effect=_fake_db_context),
                patch.object(session, "_chat_context", new=AsyncMock(return_value=MagicMock())),
                patch.object(session, "_reauthorize_write", new=AsyncMock(return_value=True)),
                patch(
                    "app.services.agent_session.AcceptedQueuedMessageService", return_value=service
                ),
            ):
                await session.handle_frame({"type": "steer", "accepted_queue_id": str(receipt_id)})

        steer = inbox.receipt(receipt_id)
        assert steer is not None
        assert steer.text == "frozen question"
        assert _sent_events(session) == [
            (
                "steer_claimed",
                {
                    "accepted_queue_id": str(receipt_id),
                    "run_id": str(session._turn_runs[0].run_id),
                },
            )
        ]

    async def test_a_claim_race_with_unknown_release_stays_reconcilable(self) -> None:
        session = _session()
        receipt_id = uuid4()
        async with _running_turn(session) as inbox:
            run_id = session._turn_runs[0].run_id
            service = MagicMock()
            service.get_for_owner = AsyncMock(
                return_value=SimpleNamespace(
                    state="pending", steering_run_id=None, content="queued"
                )
            )

            async def lose_the_inbox(*_args: Any, **_kwargs: Any) -> str:
                session._steering = None
                return "claimed"

            service.claim_for_steer = AsyncMock(side_effect=lose_the_inbox)
            service.release_unconsumed_steer = AsyncMock(
                side_effect=RuntimeError("uncertain commit")
            )
            with (
                patch("app.services.agent_session.get_db_context", side_effect=_fake_db_context),
                patch.object(session, "_chat_context", new=AsyncMock(return_value=MagicMock())),
                patch.object(session, "_reauthorize_write", new=AsyncMock(return_value=True)),
                patch(
                    "app.services.agent_session.AcceptedQueuedMessageService", return_value=service
                ),
            ):
                await session.handle_frame({"type": "steer", "accepted_queue_id": str(receipt_id)})

        assert inbox.receipt(receipt_id) is None
        assert _sent_events(session) == [
            (
                "steer_claimed",
                {"accepted_queue_id": str(receipt_id), "run_id": str(run_id)},
            )
        ]


class TestReconcilingLateReceiptFrames:
    @pytest.mark.parametrize(
        ("state", "steering_run_id", "expected"),
        [
            ("pending", None, "steer_unapplied"),
            ("steering", None, "steer_claimed"),
            ("steering", uuid4(), "steer_claimed"),
            ("steered", None, "steer_applied"),
            ("steered", uuid4(), "steer_applied"),
            ("cancelled", None, "error"),
        ],
    )
    async def test_a_late_receipt_frame_reports_its_durable_state(
        self, state: str, steering_run_id: UUID | None, expected: str
    ) -> None:
        session = _session()
        session.current_conversation_id = _CONVERSATION
        receipt_id = uuid4()
        service = MagicMock()
        service.get_for_owner = AsyncMock(
            return_value=SimpleNamespace(state=state, steering_run_id=steering_run_id)
        )

        with (
            patch("app.services.agent_session.get_db_context", side_effect=_fake_db_context),
            patch.object(session, "_chat_context", new=AsyncMock(return_value=MagicMock())),
            patch("app.services.agent_session.AcceptedQueuedMessageService", return_value=service),
        ):
            await session._reconcile_accepted_steer(receipt_id)

        assert len(_sent_events(session)) == 1
        event, data = _sent_events(session)[0]
        assert event == expected
        assert data["accepted_queue_id"] == str(receipt_id)
        if state in {"steering", "steered"}:
            assert data["run_id"] == (None if steering_run_id is None else str(steering_run_id))

    @pytest.mark.security
    async def test_a_receipt_cannot_be_reconciled_without_its_conversation(self) -> None:
        session = _session()
        receipt_id = uuid4()

        await session._reconcile_accepted_steer(receipt_id)

        assert _sent_events(session) == [
            (
                "error",
                {
                    "message": "The accepted message cannot be reconciled in this conversation",
                    "accepted_queue_id": str(receipt_id),
                },
            )
        ]

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("failure", "expected"),
        [
            (AuthorizationError(message="Membership ended"), "Membership ended"),
            (
                RuntimeError("database unavailable"),
                "The accepted message could not be reconciled; check its queue status",
            ),
        ],
    )
    async def test_a_receipt_lookup_failure_is_reported_without_echoing_details(
        self, failure: Exception, expected: str
    ) -> None:
        session = _session()
        session.current_conversation_id = _CONVERSATION
        receipt_id = uuid4()
        service = MagicMock()
        service.get_for_owner = AsyncMock(side_effect=failure)

        with (
            patch("app.services.agent_session.get_db_context", side_effect=_fake_db_context),
            patch.object(session, "_chat_context", new=AsyncMock(return_value=MagicMock())),
            patch("app.services.agent_session.AcceptedQueuedMessageService", return_value=service),
        ):
            await session._reconcile_accepted_steer(receipt_id)

        assert _sent_events(session) == [
            ("error", {"message": expected, "accepted_queue_id": str(receipt_id)})
        ]


class TestFinishingAcceptedSteers:
    async def test_a_receipt_fenced_by_another_turn_is_still_recorded_once_if_consumed_here(
        self,
    ) -> None:
        session = _session()
        receipt_id = uuid4()
        run_id = uuid4()

        async def apply_already_fenced_receipt(**kwargs: Any) -> Any:
            kwargs["on_run_open"](
                OpenedRun(run_id=run_id, model_label="test", agent_version_id=None)
            )
            inbox: SteeringInbox = kwargs["steering"]
            steer = inbox.add("accepted correction", accepted_queue_id=receipt_id)
            assert inbox.on_receipt_applied is not None
            await inbox.on_receipt_applied(receipt_id, "accepted correction")
            assert inbox.on_applied is not None
            await inbox.on_applied(steer, "accepted correction")
            await inbox.on_applied(steer, "accepted correction")
            return replace(_finished_turn(), run_id=run_id)

        service = MagicMock()
        service.finish_steer = AsyncMock(return_value=False)
        with (
            _chat(AsyncMock(side_effect=apply_already_fenced_receipt)) as chat,
            patch("app.services.agent_session.AcceptedQueuedMessageService", return_value=service),
        ):
            await session.process_message(
                {"message": "go", "agent_id": str(uuid4()), "conversation_id": _CONVERSATION}
            )

        parts = chat.answer.await_args.kwargs["parts"]
        assert parts.count(MessagePart(type="steer", text="accepted correction")) == 1
        assert not [event for event in _sent_events(session) if event[0] == "steer_applied"]

    @pytest.mark.security
    async def test_a_receipt_cannot_be_fenced_before_the_turn_opens_a_run(self) -> None:
        session = _session()
        receipt_id = uuid4()

        async def try_before_run_open(**kwargs: Any) -> Any:
            inbox: SteeringInbox = kwargs["steering"]
            assert inbox.on_receipt_applied is not None
            with pytest.raises(AlreadyExistsError, match="active chat run is no longer available"):
                await inbox.on_receipt_applied(receipt_id, "accepted correction")
            return _finished_turn()

        service = MagicMock()
        service.finish_steer = AsyncMock()
        with (
            _chat(AsyncMock(side_effect=try_before_run_open)) as chat,
            patch("app.services.agent_session.AcceptedQueuedMessageService", return_value=service),
        ):
            await session.process_message(
                {"message": "go", "agent_id": str(uuid4()), "conversation_id": _CONVERSATION}
            )

        assert "complete" in [event for event, _payload in _sent_events(session)]
        assert not [event for event in _sent_events(session) if event[0] == "steer_applied"]
        service.finish_steer.assert_not_awaited()
        assert chat.answer.await_count == 1

    async def test_a_receipt_is_written_to_the_transcript_once_after_the_durable_fence(
        self,
    ) -> None:
        session = _session()
        receipt_id = uuid4()
        run_id = uuid4()

        async def apply_receipt(**kwargs: Any) -> Any:
            kwargs["on_run_open"](
                OpenedRun(run_id=run_id, model_label="test", agent_version_id=None)
            )
            inbox: SteeringInbox = kwargs["steering"]
            inbox.add("accepted correction", accepted_queue_id=receipt_id)
            [(steer, screened)] = await inbox.take_screened()
            assert steer.accepted_queue_id == receipt_id
            assert screened == "accepted correction"
            assert inbox.on_applied is not None
            await inbox.on_applied(steer, screened)
            assert inbox.on_receipt_applied is not None
            await inbox.on_receipt_applied(receipt_id, screened)
            return replace(_finished_turn(), run_id=run_id)

        service = MagicMock()
        service.finish_steer = AsyncMock(side_effect=[True, False])
        with (
            _chat(AsyncMock(side_effect=apply_receipt)) as chat,
            patch("app.services.agent_session.AcceptedQueuedMessageService", return_value=service),
        ):
            await session.process_message(
                {"message": "go", "agent_id": str(uuid4()), "conversation_id": _CONVERSATION}
            )

        parts = chat.answer.await_args.kwargs["parts"]
        assert parts.count(MessagePart(type="steer", text="accepted correction")) == 1
        assert [event for event in _sent_events(session) if event[0] == "steer_applied"] == [
            (
                "steer_applied",
                {
                    "accepted_queue_id": str(receipt_id),
                    "run_id": str(run_id),
                    "text": "accepted correction",
                },
            )
        ]
        assert service.finish_steer.await_count == 2


class TestReleasingUnappliedReceipts:
    async def test_a_child_that_consumed_a_receipt_prevents_early_release(self) -> None:
        session = _session()
        conversation_id = uuid4()
        run_id = uuid4()
        receipt_ids = [uuid4(), uuid4()]
        inbox = SteeringInbox()
        session.current_conversation_id = str(conversation_id)
        session._turn_runs = [OpenedRun(run_id=run_id, model_label="test", agent_version_id=None)]
        session._steering = inbox
        service_factory = MagicMock()

        with inbox.listen("child") as child:
            inbox.add("child already consumed this", accepted_queue_id=receipt_ids[0])
            child.take()
            inbox.add("child may still consume this", accepted_queue_id=receipt_ids[1])
            with patch(
                "app.services.agent_session.AcceptedQueuedMessageService",
                service_factory,
            ):
                await session._end_live_turn(inbox)

        assert [steer.accepted_queue_id for steer in inbox.unapplied_steers()] == receipt_ids
        service_factory.assert_not_called()

    @pytest.mark.security
    async def test_a_turn_that_no_longer_owns_the_inbox_cannot_release_its_receipt(self) -> None:
        session = _session()
        inbox = SteeringInbox()
        inbox.add("receipt from an earlier turn", accepted_queue_id=uuid4())
        session.current_conversation_id = str(uuid4())
        session._turn_runs = [OpenedRun(run_id=uuid4(), model_label="test", agent_version_id=None)]
        session._steering = None
        service_factory = MagicMock()

        with patch(
            "app.services.agent_session.AcceptedQueuedMessageService",
            service_factory,
        ):
            await session._end_live_turn(inbox)

        service_factory.assert_not_called()

    @pytest.mark.parametrize("release_result", [True, False, "raises"])
    async def test_an_unconsumed_receipt_is_only_returned_when_release_is_confirmed(
        self, release_result: bool | str
    ) -> None:
        session = _session()
        conversation_id = uuid4()
        receipt_id = uuid4()
        run_id = uuid4()
        inbox = SteeringInbox()
        inbox.add("unused accepted message", accepted_queue_id=receipt_id)
        session.current_conversation_id = str(conversation_id)
        session._turn_runs = [OpenedRun(run_id=run_id, model_label="test", agent_version_id=None)]
        session._steering = inbox
        service = MagicMock()
        service.release_unconsumed_steer = AsyncMock(
            side_effect=RuntimeError("release outcome unknown")
            if release_result == "raises"
            else None,
            return_value=release_result if isinstance(release_result, bool) else None,
        )

        with (
            patch("app.services.agent_session.get_db_context", side_effect=_fake_db_context),
            patch.object(session, "_chat_context", new=AsyncMock(return_value=MagicMock())),
            patch("app.services.agent_session.AcceptedQueuedMessageService", return_value=service),
        ):
            await session._end_live_turn(inbox)

        expected = (
            [
                (
                    "steer_unapplied",
                    {"accepted_queue_id": str(receipt_id), "run_id": str(run_id)},
                )
            ]
            if release_result is True
            else []
        )
        assert _sent_events(session) == expected
        service.release_unconsumed_steer.assert_awaited_once()
        release_args, release_kwargs = service.release_unconsumed_steer.await_args
        assert release_args[1:] == (conversation_id, receipt_id)
        assert release_kwargs == {"run_id": run_id}


class TestAcceptedQueueMessageFrames:
    @pytest.mark.security
    @pytest.mark.parametrize(
        "overrides",
        [
            {"approval_mode": "manual"},
            {"testing": {"draft": True}},
        ],
    )
    async def test_an_accepted_queue_frame_cannot_change_run_settings(
        self, overrides: dict[str, Any]
    ) -> None:
        session = _session()
        frame = {
            "message": "client text is ignored",
            "accepted_queue_id": str(uuid4()),
            "conversation_id": _CONVERSATION,
            **overrides,
        }

        await session.process_message(frame)

        assert _sent_events(session) == [
            ("error", {"message": "An accepted queued message cannot change its run settings"})
        ]

    @pytest.mark.security
    @pytest.mark.parametrize(
        ("frame", "message"),
        [
            (
                {"accepted_queue_id": "not-a-uuid", "conversation_id": _CONVERSATION},
                "That is not a valid accepted queue id",
            ),
            (
                {"accepted_queue_id": str(uuid4())},
                "An accepted queued message needs its original conversation",
            ),
            (
                {"accepted_queue_id": str(uuid4()), "conversation_id": "not-a-uuid"},
                "That is not a valid conversation id",
            ),
        ],
    )
    async def test_an_accepted_queue_frame_needs_valid_server_receipt_ids(
        self, frame: dict[str, str], message: str
    ) -> None:
        session = _session()

        await session.process_message(frame)

        assert _sent_events(session) == [("error", {"message": message})]

    @pytest.mark.security
    async def test_an_unavailable_accepted_receipt_stops_before_the_turn(self) -> None:
        session = _session()
        receipt_id = uuid4()
        refusal = AuthorizationError(message="Accepted message is unavailable")
        service = MagicMock()
        service.get_for_owner = AsyncMock(side_effect=refusal)

        with (
            _chat(AsyncMock()) as chat,
            patch(
                "app.services.agent_session.AcceptedQueuedMessageService",
                return_value=service,
            ),
        ):
            await session.process_message(
                {
                    "accepted_queue_id": str(receipt_id),
                    "conversation_id": _CONVERSATION,
                    "message": "untrusted client text",
                }
            )

        assert _sent_events(session) == [("error", {"message": refusal.message})]
        chat.prompt.assert_not_awaited()
        chat.runner.run.assert_not_awaited()

    @pytest.mark.security
    async def test_a_receipt_already_claimed_or_cancelled_is_refused(self) -> None:
        session = _session()
        receipt = _accepted_receipt(state="steering")
        service = MagicMock()
        service.get_for_owner = AsyncMock(return_value=receipt)

        with (
            _chat(AsyncMock()) as chat,
            patch(
                "app.services.agent_session.AcceptedQueuedMessageService",
                return_value=service,
            ),
        ):
            await session.process_message(
                {
                    "accepted_queue_id": str(receipt.id),
                    "conversation_id": str(receipt.conversation_id),
                }
            )

        assert _sent_events(session) == [
            ("error", {"message": "This queued message was already claimed or cancelled"})
        ]
        chat.prompt.assert_not_awaited()

    @pytest.mark.security
    @pytest.mark.parametrize("matches", [False, True])
    async def test_an_existing_run_is_reconciled_only_when_it_matches_the_receipt(
        self, matches: bool
    ) -> None:
        session = _session()
        conversation_id = UUID(_CONVERSATION)
        receipt = _accepted_receipt(conversation_id=conversation_id)
        run = SimpleNamespace(
            id=uuid4(),
            status="running",
            user_id=session.user.id if matches else uuid4(),
            conversation_id=conversation_id,
            agent_id=receipt.agent_id,
        )
        service = MagicMock()
        service.get_for_owner = AsyncMock(return_value=receipt)

        with (
            _chat(AsyncMock()) as chat,
            patch("app.services.agent_session.AcceptedQueuedMessageService", return_value=service),
            patch.object(
                agent_session_module.agent_run_repo,
                "for_accepted_queue",
                new=AsyncMock(return_value=run),
            ),
        ):
            await session.process_message(
                {
                    "accepted_queue_id": str(receipt.id),
                    "conversation_id": str(conversation_id),
                    "message": "untrusted client text",
                }
            )

        if matches:
            assert _sent_events(session) == [
                (
                    "accepted_queue_run_exists",
                    {
                        "accepted_queue_id": str(receipt.id),
                        "conversation_id": str(conversation_id),
                        "message_id": None,
                        "run_id": str(run.id),
                        "run_status": "running",
                    },
                )
            ]
        else:
            assert _sent_events(session) == [
                ("error", {"message": "The accepted queue run does not match its receipt"})
            ]
        chat.prompt.assert_not_awaited()

    async def test_an_accepted_receipt_uses_its_frozen_prompt_and_context(self) -> None:
        session = _session()
        conversation_id = UUID(_CONVERSATION)
        file_id = uuid4()
        reply_to = uuid4()
        receipt = _accepted_receipt(
            conversation_id=conversation_id,
            content="frozen server question",
            file_ids=[file_id],
            mentions=[MentionRef(kind="mcp", id="drive")],
            reply_to_message_id=reply_to,
            reply_to_excerpt="the selected paragraph",
            page_context=ChatPageContext(
                path="/projects/brief",
                title="Project brief",
                captured_at="2026-11-26T00:00:00Z",
            ),
            local_target=LocalTarget(folder="C:/work"),
        )
        service = MagicMock()
        service.get_for_owner = AsyncMock(return_value=receipt)
        run = AsyncMock(return_value=_finished_turn())

        with _chat(run) as chat:
            chat.runner.mentions = AsyncMock(
                return_value=ResolvedMentions(
                    mentions=[Mentionable(kind="mcp", id="drive", name="Drive")],
                    note="Use the shared drive.",
                )
            )
            with (
                patch(
                    "app.services.agent_session.AcceptedQueuedMessageService", return_value=service
                ),
                patch.object(
                    agent_session_module.agent_run_repo,
                    "for_accepted_queue",
                    new=AsyncMock(return_value=None),
                ),
            ):
                attached_files = AsyncMock(return_value=[])
                with patch.object(session, "_attached_files", new=attached_files):
                    await session.process_message(
                        {
                            "accepted_queue_id": str(receipt.id),
                            "conversation_id": str(conversation_id),
                            "message": "untrusted client question",
                            "model_profile_id": None,
                            "environment_id": None,
                            "approval_mode": None,
                            "project_id": None,
                            "testing": {"draft": False},
                            "allow_setup_reply": False,
                        }
                    )

        prompt_args = chat.prompt.await_args
        assert prompt_args.args[1:3] == ("frozen server question", [file_id])
        assert prompt_args.kwargs["accepted_queue_id"] == receipt.id
        assert prompt_args.kwargs["reply_to"] == str(reply_to)
        assert prompt_args.kwargs["reply_to_excerpt"] == "the selected paragraph"
        assert prompt_args.kwargs["mentions"] == [Mentionable(kind="mcp", id="drive", name="Drive")]
        attached_files.assert_awaited_once()
        assert attached_files.await_args.args[0] is not None
        assert attached_files.await_args.args[1:] == (None, [file_id])
        run_kwargs = run.await_args.kwargs
        assert run_kwargs["accepted_queue_id"] == receipt.id
        assert run_kwargs["local"] == receipt.local_target
        assert "Use the shared drive." in run_kwargs["user_input"]
        assert "Project brief" in run_kwargs["user_input"]
        assert _sent_events(session)[0][0] == "user_prompt"
