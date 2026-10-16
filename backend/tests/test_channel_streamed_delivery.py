"""How the router ends a streamed answer, rates an edited one and reacts (#2084)."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.agent_run import RunStatus
from app.services.channels.router import ChannelMessageRouter

pytestmark = pytest.mark.anyio

ROUTER = "app.services.channels.router"
RUN_ID = uuid.uuid4()


def _answered(**overrides: Any) -> MagicMock:
    answered = MagicMock()
    answered.run_id = overrides.get("run_id", RUN_ID)
    answered.status = overrides.get("status", RunStatus.COMPLETED)
    answered.image_png = overrides.get("image_png")
    answered.attachments = overrides.get("attachments", [])
    return answered


def _router() -> tuple[ChannelMessageRouter, AsyncMock]:
    router = ChannelMessageRouter()
    router._send_reply = AsyncMock()  # type: ignore[method-assign]
    return router, router._send_reply


def _streamed(*, continues: Any = True) -> MagicMock:
    streamed = MagicMock(handle="222.2")
    streamed.finish = AsyncMock(
        side_effect=continues if isinstance(continues, Exception) else None,
        return_value=None if isinstance(continues, Exception) else continues,
    )
    return streamed


async def _deliver(
    router: ChannelMessageRouter,
    adapter: MagicMock,
    answered: MagicMock,
    *,
    handle: str | None = None,
    streamed: Any = None,
    rate_answers: bool = True,
) -> None:
    with (
        patch(f"{ROUTER}.get_adapter", return_value=adapter),
        patch(f"{ROUTER}.unseal_bot_token", return_value="tok"),
    ):
        await router._deliver(
            MagicMock(id="bot-1", api_base_url=None, rate_answers=rate_answers),
            MagicMock(platform="slack", platform_chat_id="C1:1.1"),
            "the answer",
            answered,
            handle,
            streamed,
        )


class TestAStreamedAnswerEnds:
    async def test_it_ends_with_the_thumbs_for_its_run(self) -> None:
        router, send_reply = _router()
        streamed = _streamed()

        await _deliver(router, MagicMock(), _answered(), streamed=streamed)

        assert streamed.finish.await_args.kwargs == {
            "failed": False,
            "feedback_run_id": str(RUN_ID),
        }
        send_reply.assert_not_awaited()

    async def test_an_answer_that_is_not_what_was_streamed_rewrites_it(self) -> None:
        router, _send = _router()
        adapter = MagicMock(update_reply=AsyncMock())

        await _deliver(router, adapter, _answered(), streamed=_streamed(continues=False))

        assert adapter.update_reply.await_args.args[1].text == "the answer"
        assert adapter.update_reply.await_args.args[2] == "222.2"

    async def test_a_stream_that_would_not_end_has_its_answer_posted_whole(self) -> None:
        router, send_reply = _router()
        files = [MagicMock()]

        await _deliver(
            router,
            MagicMock(),
            _answered(attachments=files),
            streamed=_streamed(continues=RuntimeError("gone")),
        )

        assert send_reply.await_args.args[2] == "the answer"
        assert send_reply.await_args.args[3] == files

    async def test_files_still_follow_a_streamed_answer(self) -> None:
        router, send_reply = _router()

        await _deliver(router, MagicMock(), _answered(image_png=b"png"), streamed=_streamed())

        assert send_reply.await_args.args[2] == ""
        assert send_reply.await_args.kwargs["image_png"] == b"png"

    async def test_an_unfinished_run_offers_nothing_to_rate(self) -> None:
        router, _send = _router()
        streamed = _streamed()

        await _deliver(
            router, MagicMock(), _answered(status=RunStatus.BUDGET_EXCEEDED), streamed=streamed
        )

        assert streamed.finish.await_args.kwargs["feedback_run_id"] is None


class TestABotThatDoesNotAskForRatings:
    async def test_offers_no_thumbs_either_way(self) -> None:
        router, _send = _router()
        streamed = _streamed()
        adapter = MagicMock(update_reply=AsyncMock(), offer_feedback=AsyncMock())

        await _deliver(router, adapter, _answered(), streamed=streamed, rate_answers=False)
        await _deliver(router, adapter, _answered(), handle="h1", rate_answers=False)

        assert streamed.finish.await_args.kwargs["feedback_run_id"] is None
        adapter.offer_feedback.assert_not_awaited()


class TestAnEditedAnswerIsRated:
    async def test_the_thumbs_follow_the_final_edit(self) -> None:
        router, _send = _router()
        adapter = MagicMock(update_reply=AsyncMock(), offer_feedback=AsyncMock())

        await _deliver(router, adapter, _answered(), handle="h1")

        assert adapter.offer_feedback.await_args.args[2:] == ("h1", str(RUN_ID))
        assert adapter.offer_feedback.await_args.kwargs == {"bot_id": "bot-1"}

    async def test_thumbs_a_platform_refuses_cost_the_answer_nothing(self) -> None:
        router, send_reply = _router()
        adapter = MagicMock(
            update_reply=AsyncMock(), offer_feedback=AsyncMock(side_effect=RuntimeError("no"))
        )

        await _deliver(router, adapter, _answered(), handle="h1")

        send_reply.assert_not_awaited()


class TestAFailureInAStream:
    async def _fail(self, streamed: MagicMock, adapter: MagicMock) -> AsyncMock:
        router, send_reply = _router()
        with (
            patch(f"{ROUTER}.get_adapter", return_value=adapter),
            patch(f"{ROUTER}.unseal_bot_token", return_value="tok"),
        ):
            await router._post_failure(
                MagicMock(api_base_url=None),
                MagicMock(platform="slack", platform_chat_id="C1:1.1"),
                "222.2",
                "Sorry, something went wrong.",
                streamed,
            )
        return send_reply

    async def test_it_is_ended_as_failed_and_rewritten_as_the_apology(self) -> None:
        streamed = _streamed(continues=False)
        adapter = MagicMock(update_reply=AsyncMock())

        send_reply = await self._fail(streamed, adapter)

        assert streamed.finish.await_args.kwargs == {"failed": True, "feedback_run_id": None}
        assert adapter.update_reply.await_args.args[1].text == "Sorry, something went wrong."
        send_reply.assert_not_awaited()

    async def test_one_that_would_not_end_posts_the_apology(self) -> None:
        send_reply = await self._fail(_streamed(continues=RuntimeError("x")), MagicMock())

        assert send_reply.await_args.args[2] == "Sorry, something went wrong."


class TestTheReaction:
    async def _acknowledge(self, reaction: str | None, adapter: MagicMock) -> None:
        with (
            patch(f"{ROUTER}.get_adapter", return_value=adapter),
            patch(f"{ROUTER}.unseal_bot_token", return_value="tok"),
        ):
            await ChannelMessageRouter()._acknowledge(
                MagicMock(ack_reaction=reaction), MagicMock(platform="slack")
            )

    async def test_a_bot_with_an_emoji_reacts(self) -> None:
        adapter = MagicMock(acknowledge_message=AsyncMock())
        await self._acknowledge("eyes", adapter)
        assert adapter.acknowledge_message.await_args.args[2] == "eyes"

    async def test_a_bot_without_one_does_not(self) -> None:
        adapter = MagicMock(acknowledge_message=AsyncMock())
        await self._acknowledge(None, adapter)
        adapter.acknowledge_message.assert_not_awaited()

    async def test_a_refused_reaction_is_only_logged(self) -> None:
        adapter = MagicMock(acknowledge_message=AsyncMock(side_effect=RuntimeError("no emoji")))
        await self._acknowledge("eyes", adapter)


class TestOpeningAStream:
    async def test_a_platform_that_streams_gets_a_streamed_reply(self) -> None:
        native = MagicMock(handle="222.2")
        adapter = MagicMock(open_answer=AsyncMock(return_value=native))
        with (
            patch(f"{ROUTER}.get_adapter", return_value=adapter),
            patch(f"{ROUTER}.unseal_bot_token", return_value="tok"),
        ):
            streamed = await ChannelMessageRouter()._open_streamed(MagicMock(), MagicMock())
        assert streamed is not None and streamed.handle == "222.2"

    async def test_one_that_does_not_gets_none(self) -> None:
        adapter = MagicMock(open_answer=AsyncMock(return_value=None))
        with (
            patch(f"{ROUTER}.get_adapter", return_value=adapter),
            patch(f"{ROUTER}.unseal_bot_token", return_value="tok"),
        ):
            assert await ChannelMessageRouter()._open_streamed(MagicMock(), MagicMock()) is None
