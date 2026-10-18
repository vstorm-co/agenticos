"""Drawing a visual to a picture with the deployment's own browser.

The browser session itself is exercised against a live Chromium; what is pinned
here is everything around it that decides what the browser may reach: which
browser is allowed, what each of its requests is answered with, and which of a
turn's calls becomes the picture.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.repositories.conversation import ToolCallArgs
from app.services import visual_render
from app.services.visual_render import RenderUnavailableError

pytestmark = pytest.mark.anyio

SVG = '<svg viewBox="0 0 100 50"><rect/></svg>'


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(visual_render.settings, "VISUAL_RENDER_CDP_URL", "http://browser:9222")
    monkeypatch.setattr(visual_render.settings, "BROWSER_CDP_ALLOWED_HOSTS", ["Browser"])


class TestWhichBrowser:
    def test_none_is_configured_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(visual_render.settings, "VISUAL_RENDER_CDP_URL", "")
        assert visual_render.available() is False
        with pytest.raises(RenderUnavailableError, match="No browser"):
            visual_render.allowed_endpoint("")

    @pytest.mark.security
    def test_a_browser_off_the_allowlist_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(visual_render.settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
        with pytest.raises(RenderUnavailableError, match=r"'evil\.example\.com'"):
            visual_render.allowed_endpoint("http://evil.example.com:9222")

    def test_an_allowed_browser_is_used(self, browser: None) -> None:
        assert visual_render.available() is True
        assert visual_render.allowed_endpoint("http://browser:9222") == "http://browser:9222"


class TestWhatTheBrowserIsGiven:
    def test_the_drawing_gets_the_runtime_after_its_doctype(self) -> None:
        page = visual_render.rendered_document("html", "<!doctype html><p>x</p>", title="T")
        assert page.startswith('<!doctype html><script data-agenticos="visual">')
        assert page.endswith("<p>x</p>")

    async def test_the_page_address_is_answered_with_the_drawing_under_the_sandbox(self) -> None:
        reply = await visual_render.answer(visual_render.page_url(), b"<p>x</p>")
        assert reply.body == b"<p>x</p>"
        assert reply.policy is not None
        assert reply.policy.startswith("sandbox allow-scripts allow-modals;")

    async def test_a_library_file_is_served_from_disk(self) -> None:
        reply = await visual_render.answer(
            visual_render.library_prefix() + "d3-7.9.0.min.js?v=1", b""
        )
        assert reply.body is not None
        assert reply.content_type.startswith("text/javascript")

    @pytest.mark.security
    @pytest.mark.parametrize(
        "url",
        ["https://example.com/beacon?data=secret", "http://169.254.169.254/latest/meta-data"],
    )
    async def test_anything_else_is_refused(self, url: str) -> None:
        assert (await visual_render.answer(url, b"")).body is None

    async def test_a_name_outside_the_set_is_refused(self) -> None:
        reply = await visual_render.answer(visual_render.library_prefix() + "README.md", b"")
        assert reply.body is None

    async def test_a_drawing_is_photographed_at_its_width(self, browser: None) -> None:
        with patch(
            "app.services.visual_render._photograph", new=AsyncMock(return_value=b"png")
        ) as photograph:
            png = await visual_render.render_png("svg", SVG, title="T", width=640, aspect=0.5)
        assert png == b"png"
        assert photograph.await_args.args[0] == "http://browser:9222"
        assert photograph.await_args.kwargs == {"width": 640, "aspect": 0.5}


class TestTheTurnsPicture:
    def _calls(self) -> list[tuple[str, str, dict, str | None]]:
        return [
            ("d", "draw", {"title": "Flow", "kind": "svg", "content": SVG}, "Drew 'Flow' ..."),
            ("bad", "draw", {"kind": "html", "content": "<p>x"}, "Retry: the drawing loads..."),
            ("open", "draw", {"kind": "svg", "content": SVG}, None),
        ]

    async def test_the_last_drawing_that_made_a_visual_is_drawn(self, browser: None) -> None:
        with (
            patch(
                "app.services.visual_render.render_png", new=AsyncMock(return_value=b"png")
            ) as render,
            patch(
                "app.services.visual_render.visuals.inlined",
                new=AsyncMock(side_effect=lambda visual, *_: visual.content),
            ),
        ):
            png = await visual_render.picture_of_turn(
                self._calls(), organization_id=uuid.uuid4(), conversation_id=uuid.uuid4()
            )
        assert png == b"png"
        assert render.await_args.args[:2] == ("svg", SVG)
        assert render.await_args.kwargs["aspect"] == 0.5

    async def test_a_revision_finds_its_base_in_the_conversation(self, browser: None) -> None:
        calls = [
            (
                "r",
                "revise_visual",
                {"visual_id": "old", "edits": [{"old": "<rect/>", "new": "<g/>"}]},
                "Revised 'Flow' ...",
            )
        ]
        stored = ToolCallArgs(
            "old", "draw", {"title": "Flow", "kind": "html", "content": "<rect/>"}
        )
        with (
            patch(
                "app.services.visual_render.render_png", new=AsyncMock(return_value=b"png")
            ) as render,
            patch(
                "app.services.visual_render.visuals.stored_call", new=AsyncMock(return_value=stored)
            ),
            patch(
                "app.services.visual_render.visuals.inlined",
                new=AsyncMock(side_effect=lambda visual, *_: visual.content),
            ),
        ):
            await visual_render.picture_of_turn(
                calls, organization_id=uuid.uuid4(), conversation_id=uuid.uuid4()
            )
        assert render.await_args.args[:2] == ("html", "<g/>")
        assert render.await_args.kwargs["aspect"] is None

    async def test_outside_a_conversation_only_the_turn_s_own_calls_count(
        self, browser: None
    ) -> None:
        calls = [("r", "revise_visual", {"visual_id": "old", "edits": []}, "Revised ...")]
        with patch("app.services.visual_render.render_png", new=AsyncMock()) as render:
            assert (
                await visual_render.picture_of_turn(
                    calls, organization_id=uuid.uuid4(), conversation_id=None
                )
                is None
            )
        render.assert_not_awaited()

    async def test_a_drawing_outside_a_conversation_has_no_pictures_to_inline(
        self, browser: None
    ) -> None:
        with patch(
            "app.services.visual_render.render_png", new=AsyncMock(return_value=b"png")
        ) as render:
            await visual_render.picture_of_turn(
                self._calls()[:1], organization_id=uuid.uuid4(), conversation_id=None
            )
        assert render.await_args.args[1] == SVG

    async def test_nothing_drawn_or_no_browser_is_no_picture(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert (
            await visual_render.picture_of_turn(
                [("c", "create_chart", {}, "{}")],
                organization_id=uuid.uuid4(),
                conversation_id=None,
            )
            is None
        )
        monkeypatch.setattr(visual_render.settings, "VISUAL_RENDER_CDP_URL", "")
        assert (
            await visual_render.picture_of_turn(
                self._calls(), organization_id=uuid.uuid4(), conversation_id=None
            )
            is None
        )

    async def test_a_drawing_that_will_not_render_costs_only_the_picture(
        self, browser: None
    ) -> None:
        with patch(
            "app.services.visual_render.render_png", new=AsyncMock(side_effect=TimeoutError())
        ):
            assert (
                await visual_render.picture_of_turn(
                    self._calls()[:1], organization_id=uuid.uuid4(), conversation_id=None
                )
                is None
            )
