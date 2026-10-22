"""Links to generated media for a visitor: minted on their socket, for their files only.

The serving route is `tests/api/test_embed_generated_media_routes.py`. This file is
the other half - which results a visitor's socket signs, and what it leaves alone -
because a link is only as narrow as the place that hands it out (#2309).
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from app.services.embed_generated_media import (
    LINK_TTL,
    media_path,
    media_token,
    signed_media_result,
    token_opens,
)
from app.services.embed_session import EmbedSession
from app.services.run_stream import RunFrames

pytestmark = pytest.mark.anyio

KEY = "pk_hosted-page-key"
NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


def _image(**fields: Any) -> str:
    return json.dumps(
        {
            "kind": "generated_image",
            "filename": "abc123_image.png",
            "url": "/api/v1/generated/abc123_image.png",
            "media_type": "image/png",
            "prompt": "a lighthouse",
            **fields,
        }
    )


class TestALinkOpensOneFileOnOneEmbedForAWhile:
    def test_a_fresh_link_opens_its_file(self) -> None:
        token = media_token(KEY, "abc_image.png", now=NOW)

        assert token_opens(KEY, "abc_image.png", token, now=NOW + LINK_TTL - timedelta(seconds=1))

    def test_it_does_not_open_another_file(self) -> None:
        token = media_token(KEY, "abc_image.png", now=NOW)

        assert not token_opens(KEY, "def_image.png", token, now=NOW)

    def test_it_does_not_open_the_same_file_on_another_embed(self) -> None:
        token = media_token(KEY, "abc_image.png", now=NOW)

        assert not token_opens("pk_other", "abc_image.png", token, now=NOW)

    def test_it_lapses(self) -> None:
        token = media_token(KEY, "abc_image.png", now=NOW)

        assert not token_opens(KEY, "abc_image.png", token, now=NOW + LINK_TTL)

    def test_a_later_expiry_cannot_be_written_onto_it(self) -> None:
        expires, signature = media_token(KEY, "abc_image.png", now=NOW).split(".")

        assert not token_opens(KEY, "abc_image.png", f"{int(expires) + 86400}.{signature}", now=NOW)

    @pytest.mark.parametrize("token", [None, "", "abc", "1.2", f"x.{'a' * 64}"])
    def test_anything_else_opens_nothing(self, token: str | None) -> None:
        assert not token_opens(KEY, "abc_image.png", token, now=NOW)


class TestWhichResultsAreSigned:
    @pytest.mark.parametrize(
        ("tool", "kind", "name"),
        [
            ("generate_image", "generated_image", "abc_image.png"),
            ("generate_speech", "generated_speech", "abc_speech.mp3"),
            ("generate_video", "generated_video", "abc_video.mp4"),
        ],
    )
    def test_a_media_tools_own_payload_carries_a_link(
        self, tool: str, kind: str, name: str
    ) -> None:
        content = json.dumps({"kind": kind, "filename": name, "url": f"/api/v1/generated/{name}"})

        signed = json.loads(signed_media_result(KEY, tool, content, now=NOW))

        assert token_opens(KEY, name, signed["token"], now=NOW)
        assert signed["url"] == media_path(KEY, name, signed["token"])
        assert signed["kind"] == kind

    def test_the_rest_of_the_payload_is_kept(self) -> None:
        signed = json.loads(signed_media_result(KEY, "generate_image", _image(), now=NOW))

        assert signed["prompt"] == "a lighthouse"
        assert signed["media_type"] == "image/png"

    @pytest.mark.parametrize(
        ("tool", "content"),
        [
            # Another tool returning text shaped like a media payload - a page the
            # agent fetched, an MCP server - names a file it did not make.
            ("fetch_url", _image()),
            ("generate_image", "Image generation failed: the provider refused"),
            ("generate_image", "[1, 2]"),
            ("generate_image", _image(kind="generated_video")),
            # Generated but not stored: a run with no organization to scope it to.
            ("generate_image", _image(filename=None)),
            ("generate_image", _image(filename="")),
        ],
        ids=["other tool", "error text", "not an object", "wrong kind", "unstored", "empty name"],
    )
    def test_anything_else_passes_through_untouched(self, tool: str, content: str) -> None:
        assert signed_media_result(KEY, tool, content, now=NOW) == content


def _session(*, show_results: bool = True) -> EmbedSession:
    @asynccontextmanager
    async def sessions() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    embed = MagicMock(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        public_key=KEY,
        kind="page",
        config={"kind": "page", "show_tool_steps": True, "show_tool_results": show_results},
    )
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    return EmbedSession(sessions=sessions, embed=embed, visitor=None, websocket=websocket)


async def _run_tool(session: EmbedSession, tool: str, content: str, *, call_id: str = "c1") -> None:
    async def events() -> AsyncIterator[Any]:
        yield FunctionToolCallEvent(
            part=ToolCallPart(tool_name=tool, args={"prompt": "x"}, tool_call_id=call_id)
        )
        yield FunctionToolResultEvent(
            ToolReturnPart(tool_name=tool, content=content, tool_call_id=call_id)
        )

    await RunFrames(emit=session._emit).tools(events())


def _results(session: EmbedSession) -> list[str]:
    return [
        call.args[0]["data"]["content"]
        for call in session.websocket.send_json.await_args_list
        if call.args[0]["type"] == "tool_result"
    ]


class TestTheVisitorsSocketHandsOutTheLink:
    async def test_a_generated_image_reaches_the_page_with_a_link(self) -> None:
        session = _session()

        await _run_tool(session, "generate_image", _image())

        (sent,) = _results(session)
        payload = json.loads(sent)
        assert token_opens(KEY, "abc123_image.png", payload["token"], now=datetime.now(UTC))
        assert payload["url"].startswith(f"/api/v1/embed/{KEY}/generated/abc123_image.png?token=")

    async def test_the_recorded_result_keeps_no_link(self) -> None:
        """Signed as the frame leaves, so the transcript holds no credential."""
        session = _session()
        frames = RunFrames(emit=session._emit)

        async def events() -> AsyncIterator[Any]:
            yield FunctionToolCallEvent(
                part=ToolCallPart(tool_name="generate_image", args={}, tool_call_id="c1")
            )
            yield FunctionToolResultEvent(
                ToolReturnPart(tool_name="generate_image", content=_image(), tool_call_id="c1")
            )

        await frames.tools(events())

        assert "token" not in frames.tool_calls[0]["result"]

    async def test_a_result_shaped_like_media_from_another_tool_gets_no_link(self) -> None:
        session = _session()

        await _run_tool(session, "fetch_url", _image())

        assert _results(session) == [_image()]

    async def test_a_page_that_hides_results_sends_none_and_forgets_the_call(self) -> None:
        session = _session(show_results=False)

        await _run_tool(session, "generate_image", _image())

        assert _results(session) == []
        assert session._media_calls == {}

    async def test_a_result_that_is_not_text_is_passed_on(self) -> None:
        session = _session()
        await session._emit("tool_call", {"tool_call_id": "c1", "tool_name": "generate_image"})

        await session._emit("tool_result", {"tool_call_id": "c1", "content": None})

        assert _results(session) == [None]
