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
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent
from pydantic_ai.messages import ToolCallPart, ToolReturnPart

from app.agents.mcp import fitted_tool_name, tool_prefix
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

    @pytest.mark.parametrize("zeros", ["0", "00"])
    def test_a_link_has_one_spelling(self, zeros: str) -> None:
        """`0<expiry>` signs the same `int`; accepted, each spelling would be its own
        rate-limit bucket, so one link would get its allowance once per zero."""
        token = media_token(KEY, "abc_image.png", now=NOW)

        assert not token_opens(KEY, "abc_image.png", f"{zeros}{token}", now=NOW)

    @pytest.mark.parametrize("token", [None, "", "abc", "1.2", f"x.{'a' * 64}"])
    def test_anything_else_opens_nothing(self, token: str | None) -> None:
        assert not token_opens(KEY, "abc_image.png", token, now=NOW)


STORED = frozenset({"abc123_image.png"})
"""What the run's own tools stored: the one file a result may be signed for."""


class TestWhichResultsAreSigned:
    @pytest.mark.parametrize(
        ("name", "fields"),
        [
            (
                "abc_image.png",
                {"kind": "generated_image", "media_type": "image/png", "prompt": "x"},
            ),
            (
                "abc_speech.mp3",
                {
                    "kind": "generated_speech",
                    "media_type": "audio/mpeg",
                    "voice": "alloy",
                    "characters": 5,
                },
            ),
            ("abc_video.mp4", {"kind": "generated_video", "prompt": "x"}),
        ],
        ids=["image", "speech", "video"],
    )
    def test_a_media_payload_naming_a_file_the_run_stored_carries_a_link(
        self, name: str, fields: dict[str, Any]
    ) -> None:
        content = json.dumps({**fields, "filename": name, "url": f"/api/v1/generated/{name}"})

        signed = json.loads(signed_media_result(KEY, content, stored={name}, now=NOW))

        assert token_opens(KEY, name, signed["token"], now=NOW)
        assert signed["url"] == media_path(KEY, name, signed["token"])
        assert signed["kind"] == fields["kind"]

    def test_the_rest_of_the_payload_is_kept(self) -> None:
        content = _image(provider_note="kept though no parser knows it")

        signed = json.loads(signed_media_result(KEY, content, stored=STORED, now=NOW))

        assert signed["prompt"] == "a lighthouse"
        assert signed["media_type"] == "image/png"
        assert signed["provider_note"] == "kept though no parser knows it"

    @pytest.mark.parametrize(
        ("content", "stored"),
        [
            # A payload naming a file this run never stored - whichever tool
            # returned it, and whatever that tool is called (#2395).
            (_image(filename="deadbeef0123_image.png"), STORED),
            (_image(), frozenset()),
            ("Image generation failed: the provider refused", STORED),
            ("[1, 2]", STORED),
            (_image(kind="generated_document"), STORED),
            # Generated but not stored: a run with no organization to scope it to.
            (_image(filename=None), STORED),
            (_image(filename=""), STORED),
        ],
        ids=[
            "unstored file",
            "nothing stored",
            "error text",
            "not an object",
            "not a media kind",
            "no filename",
            "empty name",
        ],
    )
    def test_anything_else_passes_through_untouched(
        self, content: str, stored: frozenset[str]
    ) -> None:
        assert signed_media_result(KEY, content, stored=stored, now=NOW) == content


def _session(*, show_results: bool = True, stored: frozenset[str] = STORED) -> EmbedSession:
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
    session = EmbedSession(sessions=sessions, embed=embed, visitor=None, websocket=websocket)
    session._stored = stored
    return session


async def _events(tool: str, content: str, *, call_id: str = "c1") -> AsyncIterator[Any]:
    yield FunctionToolCallEvent(
        part=ToolCallPart(tool_name=tool, args={"prompt": "x"}, tool_call_id=call_id)
    )
    yield FunctionToolResultEvent(
        ToolReturnPart(tool_name=tool, content=content, tool_call_id=call_id)
    )


async def _run_tool(session: EmbedSession, tool: str, content: str) -> None:
    await RunFrames(emit=session._emit).tools(_events(tool, content))


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

        await frames.tools(_events("generate_image", _image()))

        assert "token" not in frames.tool_calls[0]["result"]

    @pytest.mark.parametrize(
        "tool",
        # An MCP connection named `Generate` serving a tool `image`, and a rename:
        # both are a tool *called* generate_image that is not the image tool.
        [fitted_tool_name(f"{tool_prefix('Generate')}_image"), "generate_image", "fetch_url"],
    )
    async def test_a_tool_naming_a_file_this_run_did_not_store_gets_no_link(
        self, tool: str
    ) -> None:
        """The run's stored set is the authority, not the tool's name (#2395)."""
        session = _session()
        foreign = _image(filename="deadbeef0123_image.png")

        await _run_tool(session, tool, foreign)

        assert _results(session) == [foreign]

    async def test_a_page_that_hides_results_signs_nothing(self) -> None:
        session = _session(show_results=False)

        await _run_tool(session, "generate_image", _image())

        assert _results(session) == []

    async def test_a_result_that_is_not_text_is_passed_on(self) -> None:
        session = _session()

        await session._emit("tool_result", {"tool_call_id": "c1", "content": None})

        assert _results(session) == [None]

    async def test_a_turn_signs_against_the_set_its_own_run_stores_into(self) -> None:
        """`_stored` is the run's own `generated_files`, read off the run as it
        starts streaming - so a file a tool stores mid-turn is signable by the
        time its result is streamed, and a file from no tool of this run is not."""
        session = _session(stored=frozenset())
        session.conversation_id = uuid.uuid4()
        generated_files: set[str] = set()
        agent_run = MagicMock()
        agent_run.ctx.deps.user_deps.generated_files = generated_files

        async def drive(frames: RunFrames, _agent_run: Any) -> None:
            generated_files.add("abc123_image.png")
            await frames.tools(_events("generate_image", _image()))
            await frames.tools(
                _events("generate_image", _image(filename="deadbeef0123_image.png"), call_id="c2")
            )

        async def execute(*_args: Any, stream: Any, **_kwargs: Any) -> tuple[str, MagicMock]:
            await stream(agent_run)
            return "done", MagicMock()

        runner = MagicMock()
        runner.return_value.execute = execute
        with (
            patch.object(EmbedSession, "_context", AsyncMock(return_value=MagicMock())),
            patch.object(EmbedSession, "_history", AsyncMock(return_value=[])),
            patch.object(EmbedSession, "_files", AsyncMock(return_value=[])),
            patch("app.services.embed_session.AgentRunnerService", runner),
            patch.object(RunFrames, "drive", drive),
        ):
            await session._turn(MagicMock(), "draw a lighthouse")

        signed, foreign = (json.loads(sent) for sent in _results(session))
        assert token_opens(KEY, "abc123_image.png", signed["token"], now=datetime.now(UTC))
        assert "token" not in foreign
        assert session._stored is generated_files
