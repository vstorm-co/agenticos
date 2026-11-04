"""Terminal trace metadata survives the content budget against real Redis."""

import json
from uuid import uuid4

import pytest

from app.clients.redis import RedisClient
from app.services import live_turn

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("saved", [True, False])
async def test_a_full_trace_retains_its_outcome_without_replaying_a_saved_answer(
    saved: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = RedisClient()
    await client.connect()
    turn: live_turn.Turn | None = None
    try:
        if not await client.ping():
            pytest.skip("No Redis reachable")
        monkeypatch.setattr(live_turn, "_redis", client)
        conversation_id = str(uuid4())
        turn = await live_turn.begin(conversation_id)
        assert turn is not None
        await live_turn.publish(turn, "text_delta", {"content": "kept answer"})
        await client.set(turn.key("kept"), str(live_turn.MAX_TRACE_BYTES))
        await live_turn.publish(turn, "text_delta", {"content": "over budget"})
        outcome = "message_saved" if saved else "error"
        await live_turn.publish(
            turn, outcome, {"message_id": str(uuid4())} if saved else {"message": "not saved"}
        )
        await live_turn.publish(turn, "complete", {})
        await live_turn.end(turn)
        kept = [json.loads(raw)["type"] for raw in await client.list_range(turn.key("trace"))]
        assert kept == ["text_delta", outcome, "complete", live_turn.END]
        followed = [frame["type"] async for frame in live_turn.follow(conversation_id, turn.token)]
        assert followed == ([live_turn.END] if saved else kept)
    finally:
        if turn is not None:
            if turn.beat is not None:
                await live_turn.end(turn)
            await client.raw.delete(
                f"turn:{turn.conversation_id}:live",
                *(turn.key(part) for part in ("trace", "events", "alive", "seq", "kept")),
            )
        await client.close()
