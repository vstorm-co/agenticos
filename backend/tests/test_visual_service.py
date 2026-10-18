"""Visuals in the service layer: rebuilding one, its pictures, and saving it as an app.

The bytes an app is saved with are rebuilt from the transcript, never taken from
the browser; a picture is read only for a member who may read its thread, and
only when the visual's own call declared it; and the documents the frame and an
app are built from are the same ones.
"""

from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.repositories.conversation import ToolCallArgs
from app.schemas.visual import VisualPublish
from app.services import visual as visuals
from app.services.artifact import PublishedArtifact
from app.services.visual import (
    MAX_CHAIN,
    MAX_IMAGES,
    SHARED_MAX_BYTES,
    SHARED_MAX_VISUALS,
    VisualError,
    VisualService,
)

pytestmark = pytest.mark.anyio

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
SVG = '<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


def _ctx(*, user: bool = True) -> AuthContext:
    return AuthContext(
        user_id=uuid.uuid4() if user else None, organization_id=uuid.uuid4(), role="member"
    )


def _db_context(db: Any) -> Any:
    @asynccontextmanager
    async def session():
        yield db

    return session


def _lookup(calls: dict[str, ToolCallArgs]):
    async def lookup(call_id: str) -> ToolCallArgs | None:
        return calls.get(call_id)

    return lookup


class TestImageType:
    @pytest.mark.parametrize(
        ("data", "kind"),
        [
            (PNG, "image/png"),
            (b"\xff\xd8\xff\xe0rest", "image/jpeg"),
            (b"GIF89a....", "image/gif"),
            (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
            (b"\x00\x00\x00\x1cftypavif", "image/avif"),
            (b"\xef\xbb\xbf  <svg viewBox='0 0 1 1'/>", "image/svg+xml"),
            (b'<?xml version="1.0"?>\n<svg/>', "image/svg+xml"),
            (b'<?xml version="1.0"?>\n<html/>', None),
            (b"<html><script>x</script></html>", None),
        ],
    )
    def test_an_image_is_known_by_its_bytes(self, data: bytes, kind: str | None) -> None:
        assert visuals.image_type(data) == kind


class TestPictures:
    def test_pictures_live_under_the_thread_s_media_prefix(self) -> None:
        org, conversation = uuid.uuid4(), uuid.uuid4()
        path = visuals.image_path(org, conversation, "call-1", "logo")
        folder = hashlib.sha256(b"call-1").hexdigest()[:32]
        assert path == f"media/{org}/{conversation}/visuals/{folder}/logo"

    @pytest.mark.security
    def test_a_provider_s_call_id_cannot_climb_out_of_the_thread(self) -> None:
        """The id is the model provider's to choose, and on local storage a `..`
        written into the path would leave the conversation's prefix."""
        org, conversation = uuid.uuid4(), uuid.uuid4()
        path = visuals.image_path(org, conversation, "../../other/visuals/x", "logo")
        assert path.startswith(f"media/{org}/{conversation}/visuals/")
        assert ".." not in path
        assert path.count("/") == 5

    async def test_a_picture_is_saved_and_read_back_with_its_type(self) -> None:
        storage = MagicMock(
            save_at=AsyncMock(),
            exists=AsyncMock(return_value=True),
            load=AsyncMock(return_value=PNG),
        )
        org, conversation = uuid.uuid4(), uuid.uuid4()
        with patch("app.services.visual.get_file_storage", return_value=storage):
            await visuals.save_image(org, conversation, "c", "logo", PNG)
            kept = await visuals.load_image(org, conversation, "c", "logo")
        assert storage.save_at.await_args.args == (
            visuals.image_path(org, conversation, "c", "logo"),
            PNG,
        )
        assert kept == (PNG, "image/png")

    @pytest.mark.parametrize(("exists", "data"), [(False, PNG), (True, b"<html>")])
    async def test_a_picture_that_is_gone_or_not_a_picture_is_none(
        self, exists: bool, data: bytes
    ) -> None:
        storage = MagicMock(
            exists=AsyncMock(return_value=exists), load=AsyncMock(return_value=data)
        )
        with patch("app.services.visual.get_file_storage", return_value=storage):
            assert await visuals.load_image(uuid.uuid4(), uuid.uuid4(), "c", "logo") is None

    def test_image_names_reads_only_well_formed_entries(self) -> None:
        args = {"images": [{"name": "a", "source": "a.png"}, {"source": "x"}, "b", {"name": 3}]}
        assert visuals.image_names(args) == ["a"]
        assert visuals.image_names({"images": "nope"}) == []

    def test_a_known_picture_is_inlined_and_an_unknown_one_left_alone(self) -> None:
        content = '<img src="{{image:a}}"><img src="{{image:b}}">'
        assert visuals.inline_images(content, {"a": "data:x"}) == (
            '<img src="data:x"><img src="{{image:b}}">'
        )

    def test_a_data_uri_carries_the_type_and_the_bytes(self) -> None:
        assert visuals.data_uri(b"hi", "image/png") == "data:image/png;base64,aGk="


class TestRebuild:
    async def test_revisions_are_applied_in_order_with_their_titles_and_pictures(self) -> None:
        calls = {
            "r2": ToolCallArgs(
                "r2",
                "revise_visual",
                {
                    "visual_id": "r1",
                    "edits": [{"old": "two", "new": "three"}],
                    "images": [{"name": "logo", "source": "new.png"}],
                },
                uuid.uuid4(),
            ),
            "r1": ToolCallArgs(
                "r1",
                "revise_visual",
                {"visual_id": "d", "title": "Renamed", "edits": [{"old": "one", "new": "two"}]},
            ),
            "d": ToolCallArgs(
                "d",
                "draw",
                {
                    "title": "Flow",
                    "kind": "html",
                    "content": "<p>one</p>{{image:logo}}{{image:bg}}",
                    "images": [
                        {"name": "logo", "source": "old.png"},
                        {"name": "bg", "source": "b"},
                        {"name": "unused", "source": "c"},
                    ],
                },
                uuid.uuid4(),
            ),
        }
        visual = await visuals.rebuild("r2", _lookup(calls))

        assert visual.id == "r2"
        assert visual.title == "Renamed"
        assert visual.content == "<p>three</p>{{image:logo}}{{image:bg}}"
        # The agent that first drew it, not the one that revised it last: its app
        # lives in that agent's namespace, and a revision updates that app.
        assert visual.agent_id == calls["d"].agent_id
        assert visual.images == {"logo": "r2", "bg": "d"}

    @pytest.mark.parametrize(
        ("calls", "said"),
        [
            ({}, "There is no visual `x`"),
            (
                {"x": ToolCallArgs("x", "revise_visual", {"visual_id": "gone", "edits": []})},
                "revises `gone`, which is gone",
            ),
            ({"x": ToolCallArgs("x", "draw", {"kind": "pdf", "content": "c"})}, "has no kind"),
            (
                {
                    "x": ToolCallArgs(
                        "x",
                        "revise_visual",
                        {"visual_id": "d", "edits": [{"old": "zz", "new": "y"}]},
                    ),
                    "d": ToolCallArgs("d", "draw", {"kind": "svg", "content": SVG}),
                },
                "no longer applies",
            ),
        ],
    )
    async def test_what_cannot_be_rebuilt_says_why(
        self, calls: dict[str, ToolCallArgs], said: str
    ) -> None:
        with pytest.raises(VisualError, match=said):
            await visuals.rebuild("x", _lookup(calls))

    async def test_a_chain_cannot_gather_more_pictures_than_one_drawing_may_use(self) -> None:
        """Each revision may add pictures, so without this a long chain gathered
        hundreds - and every view read and inlined all of them."""
        names = [f"p{i}" for i in range(MAX_IMAGES + 1)]
        calls = {
            "r": ToolCallArgs(
                "r",
                "revise_visual",
                {
                    "visual_id": "d",
                    "edits": [{"old": "x", "new": "".join(f"{{{{image:{n}}}}}" for n in names)}],
                    "images": [{"name": n, "source": "a.png"} for n in names[3:]],
                },
            ),
            "d": ToolCallArgs(
                "d",
                "draw",
                {
                    "kind": "html",
                    "content": "x",
                    "images": [{"name": n, "source": "a.png"} for n in names[:3]],
                },
            ),
        }
        with pytest.raises(VisualError, match=f"more than {MAX_IMAGES} pictures"):
            await visuals.rebuild("r", _lookup(calls))

    async def test_a_chain_that_does_not_end_is_cut_off(self) -> None:
        """The ids are the model's, so a revision that names itself must not loop."""
        loop = {"x": ToolCallArgs("x", "revise_visual", {"visual_id": "x", "edits": []})}
        with pytest.raises(VisualError, match="too many revisions"):
            await visuals.rebuild("x", _lookup(loop))
        assert MAX_CHAIN == 50

    async def test_a_malformed_edit_list_changes_nothing(self) -> None:
        calls = {
            "x": ToolCallArgs(
                "x", "revise_visual", {"visual_id": "d", "edits": [{"old": 1}, "bad", None]}
            ),
            "d": ToolCallArgs("d", "draw", {"kind": "svg", "content": SVG}),
        }
        assert (await visuals.rebuild("x", _lookup(calls))).content == SVG
        calls["x"] = ToolCallArgs("x", "revise_visual", {"visual_id": "d", "edits": "nope"})
        assert (await visuals.rebuild("x", _lookup(calls))).content == SVG

    def test_a_revision_with_no_base_named_is_a_drawing(self) -> None:
        assert visuals.revised_id(ToolCallArgs("x", "revise_visual", {"visual_id": ""})) is None
        assert visuals.revised_id(ToolCallArgs("x", "draw", {"visual_id": "y"})) is None


class TestReads:
    async def test_the_run_s_conversation_is_read_off_its_row(self) -> None:
        conversation = uuid.uuid4()
        with (
            patch("app.services.visual.get_db_context", _db_context(MagicMock())),
            patch(
                "app.services.visual.agent_run_repo.get_run",
                new=AsyncMock(side_effect=[SimpleNamespace(conversation_id=conversation), None]),
            ),
        ):
            assert (
                await visuals.conversation_of_run(run_id=uuid.uuid4(), organization_id=uuid.uuid4())
                == conversation
            )
            assert (
                await visuals.conversation_of_run(run_id=uuid.uuid4(), organization_id=uuid.uuid4())
                is None
            )

    async def test_a_stored_call_is_looked_up_within_its_conversation(self) -> None:
        conversation = uuid.uuid4()
        call = ToolCallArgs("c", "draw", {})
        with (
            patch("app.services.visual.get_db_context", _db_context(MagicMock())),
            patch(
                "app.services.visual.conversation_repo.tool_call_in_conversation",
                new=AsyncMock(return_value=call),
            ) as lookup,
        ):
            assert await visuals.stored_call(conversation_id=conversation, tool_call_id="c") == call
        assert lookup.await_args.kwargs["conversation_id"] == conversation
        assert lookup.await_args.kwargs["names"] == ("draw", "revise_visual")

    async def test_an_attachment_is_read_by_its_name_in_the_thread(self) -> None:
        storage = MagicMock(load=AsyncMock(return_value=PNG))
        with (
            patch("app.services.visual.get_db_context", _db_context(MagicMock())),
            patch(
                "app.services.visual.chat_file_repo.latest_named_in_conversation",
                new=AsyncMock(side_effect=[SimpleNamespace(storage_path="p"), None]),
            ),
            patch("app.services.visual.get_file_storage", return_value=storage),
        ):
            assert await visuals.attachment_bytes(uuid.uuid4(), "a.png") == PNG
            assert await visuals.attachment_bytes(uuid.uuid4(), "b.png") is None
        storage.load.assert_awaited_once_with("p")

    async def test_earlier_visuals_carry_their_base_s_title_and_kind(self) -> None:
        calls = [
            ToolCallArgs("d", "draw", {"title": "Flow", "kind": "svg", "content": SVG}),
            ToolCallArgs("r", "revise_visual", {"visual_id": "d", "edits": []}),
            ToolCallArgs("x", "draw", {}),
        ]
        with (
            patch("app.services.visual.get_db_context", _db_context(MagicMock())),
            patch(
                "app.services.visual.conversation_repo.tool_calls_named",
                new=AsyncMock(return_value=calls),
            ),
        ):
            listed = await visuals.earlier_visuals(conversation_id=uuid.uuid4(), limit=20)

        assert [(item.id, item.title, item.kind, item.revision_of) for item in listed] == [
            ("d", "Flow", "svg", None),
            ("r", "Flow", "svg", "d"),
            ("x", "Untitled", "visual", None),
        ]
        assert listed[0].characters == len(SVG)


class TestPublish:
    @pytest.fixture(autouse=True)
    def _not_indexed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A visual drawn before the index existed has no row, and saves all the same -
        for a member who may run the agent that drew it."""
        monkeypatch.setattr(
            "app.services.visual.visual_repo.get_by_call", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            "app.services.visual.agent_repo.get", AsyncMock(return_value=MagicMock())
        )
        monkeypatch.setattr("app.services.visual.resolve_access", AsyncMock(return_value=True))

    def _published(self, **overrides: Any) -> PublishedArtifact:
        values: dict[str, Any] = {
            "artifact_id": uuid.uuid4(),
            "organization_id": uuid.uuid4(),
            "version_id": uuid.uuid4(),
            "version_number": 2,
            "name": "flow",
            "title": "Flow",
            "created": False,
            "unchanged": False,
            "visibility": "private",
            "public": False,
        }
        values.update(overrides)
        return PublishedArtifact(**values)

    def _patches(self, calls: dict[str, ToolCallArgs]) -> Any:
        async def lookup(
            _db: Any, *, conversation_id: Any, tool_call_id: str, names: Any, result_prefixes: Any
        ):
            return calls.get(tool_call_id)

        return (
            patch("app.services.visual.ConversationService.get_conversation", new=AsyncMock()),
            patch(
                "app.services.visual.conversation_repo.tool_call_in_conversation",
                new=AsyncMock(side_effect=lookup),
            ),
        )

    @pytest.mark.security
    async def test_a_reader_who_may_not_run_its_agent_cannot_save_it(self) -> None:
        """Reading the conversation is not enough: the app goes in the agent's
        namespace, where a name taken by a reader is one its next run finds taken."""
        calls = {
            "d": ToolCallArgs(
                "d", "draw", {"title": "Flow", "kind": "html", "content": "<p>x</p>"}, uuid.uuid4()
            )
        }
        conversation_read, repo = self._patches(calls)
        with (
            conversation_read,
            repo,
            patch("app.services.visual.resolve_access", new=AsyncMock(return_value=False)),
            patch("app.services.visual.artifacts.publish_with", new=AsyncMock()) as publish,
            pytest.raises(AuthorizationError),
        ):
            await VisualService(MagicMock()).publish(
                _ctx(), uuid.uuid4(), "d", VisualPublish(name="flow")
            )
        publish.assert_not_awaited()

    async def test_a_visual_is_published_from_the_transcript_with_its_pictures_inlined(
        self,
    ) -> None:
        agent = uuid.uuid4()
        drawn_in = uuid.uuid4()
        calls = {
            "d": ToolCallArgs(
                "d",
                "draw",
                {
                    "title": "Flow",
                    "kind": "html",
                    "content": '<img src="{{image:logo}}"><img src="{{image:gone}}">',
                    "images": [{"name": "logo", "source": "l"}, {"name": "gone", "source": "g"}],
                },
                agent,
                drawn_in,
            )
        }
        ctx = _ctx()
        published = self._published()
        conversation_read, repo = self._patches(calls)
        with (
            conversation_read as read,
            repo,
            patch(
                "app.services.visual.load_image",
                new=AsyncMock(side_effect=[(PNG, "image/png"), None]),
            ),
            patch(
                "app.services.visual.artifacts.publish_with", new=AsyncMock(return_value=published)
            ) as publish,
            patch(
                "app.services.visual.visual_repo.get_by_call",
                new=AsyncMock(return_value=SimpleNamespace()),
            ),
            patch("app.services.visual.visual_repo.update", new=AsyncMock()) as linked,
        ):
            result = await VisualService(MagicMock()).publish(
                ctx, uuid.uuid4(), "d", VisualPublish(name="flow")
            )
        assert linked.await_args.kwargs["artifact_id"] == published.artifact_id

        assert read.await_args.kwargs["user_id"] == ctx.user_id
        kwargs = publish.await_args.kwargs
        assert kwargs["agent_id"] == agent
        assert kwargs["owner_user_id"] == ctx.user_id
        # The run that drew it: `publish_with` reads its environment off that run,
        # so a drawing made in staging never updates the default app.
        assert kwargs["run_id"] == drawn_in
        assert kwargs["title"] == "Flow"
        assert b"data:image/png;base64," in kwargs["data"]
        assert b"{{image:gone}}" in kwargs["data"]
        assert result.version == 2
        assert result.url == f"/apps/{published.artifact_id}?org={published.organization_id}"

    async def test_a_title_given_wins_over_the_visual_s(self) -> None:
        calls = {"d": ToolCallArgs("d", "draw", {"kind": "svg", "content": SVG}, uuid.uuid4())}
        conversation_read, repo = self._patches(calls)
        with (
            conversation_read,
            repo,
            patch(
                "app.services.visual.artifacts.publish_with",
                new=AsyncMock(return_value=self._published()),
            ) as publish,
        ):
            await VisualService(MagicMock()).publish(
                _ctx(), uuid.uuid4(), "d", VisualPublish(name="flow", title="  Our flow ")
            )
        assert publish.await_args.kwargs["title"] == "Our flow"
        assert b"<title>Our flow</title>" in publish.await_args.kwargs["data"]

    async def test_a_key_with_no_person_is_refused(self) -> None:
        with pytest.raises(AuthorizationError):
            await VisualService(MagicMock()).publish(
                _ctx(user=False), uuid.uuid4(), "d", VisualPublish(name="flow")
            )

    async def test_no_such_visual_is_not_found(self) -> None:
        conversation_read, repo = self._patches({})
        with conversation_read, repo, pytest.raises(NotFoundError):
            await VisualService(MagicMock()).publish(
                _ctx(), uuid.uuid4(), "d", VisualPublish(name="flow")
            )

    async def test_a_visual_that_cannot_be_rebuilt_is_a_bad_request(self) -> None:
        calls = {"d": ToolCallArgs("d", "draw", {"kind": "pdf"}, uuid.uuid4())}
        conversation_read, repo = self._patches(calls)
        with conversation_read, repo, pytest.raises(BadRequestError, match="no kind"):
            await VisualService(MagicMock()).publish(
                _ctx(), uuid.uuid4(), "d", VisualPublish(name="flow")
            )

    async def test_a_visual_with_no_agent_is_a_bad_request(self) -> None:
        calls = {"d": ToolCallArgs("d", "draw", {"kind": "svg", "content": SVG}, None)}
        conversation_read, repo = self._patches(calls)
        with conversation_read, repo, pytest.raises(BadRequestError, match="no agent"):
            await VisualService(MagicMock()).publish(
                _ctx(), uuid.uuid4(), "d", VisualPublish(name="flow")
            )

    async def test_a_bad_name_is_refused_on_the_field(self) -> None:
        calls = {"d": ToolCallArgs("d", "draw", {"kind": "svg", "content": SVG}, uuid.uuid4())}
        conversation_read, repo = self._patches(calls)
        with conversation_read, repo, pytest.raises(BadRequestError) as refused:
            await VisualService(MagicMock()).publish(
                _ctx(), uuid.uuid4(), "d", VisualPublish(name="Not A Name")
            )
        assert refused.value.details["fields"][0]["field"] == "name"

    async def test_a_visual_too_large_for_an_app_is_refused(self, monkeypatch) -> None:
        monkeypatch.setattr("app.services.artifact.settings.ARTIFACT_MAX_BYTES", 10)
        calls = {"d": ToolCallArgs("d", "draw", {"kind": "svg", "content": SVG}, uuid.uuid4())}
        conversation_read, repo = self._patches(calls)
        with conversation_read, repo, pytest.raises(BadRequestError, match="limit"):
            await VisualService(MagicMock()).publish(
                _ctx(), uuid.uuid4(), "d", VisualPublish(name="flow")
            )


class TestImageRead:
    def _call(self, *names: str) -> ToolCallArgs:
        return ToolCallArgs("d", "draw", {"images": [{"name": n, "source": "s"} for n in names]})

    @pytest.mark.security
    async def test_only_a_picture_its_visual_declared_is_read(self) -> None:
        """The name is the caller's, so it never reaches storage unless the
        visual's own call named it - no path of the caller's choosing is read."""
        with (
            patch("app.services.visual.ConversationService.get_conversation", new=AsyncMock()),
            patch(
                "app.services.visual.conversation_repo.tool_call_in_conversation",
                new=AsyncMock(return_value=self._call("logo")),
            ),
            patch("app.services.visual.load_image", new=AsyncMock()) as load,
            pytest.raises(NotFoundError),
        ):
            await VisualService(MagicMock()).image(_ctx(), uuid.uuid4(), "d", "../../secret")
        load.assert_not_awaited()

    async def test_a_declared_picture_is_returned(self) -> None:
        with (
            patch("app.services.visual.ConversationService.get_conversation", new=AsyncMock()),
            patch(
                "app.services.visual.conversation_repo.tool_call_in_conversation",
                new=AsyncMock(return_value=self._call("logo")),
            ),
            patch("app.services.visual.load_image", new=AsyncMock(return_value=(PNG, "image/png"))),
        ):
            assert await VisualService(MagicMock()).image(_ctx(), uuid.uuid4(), "d", "logo") == (
                PNG,
                "image/png",
            )

    @pytest.mark.parametrize(("call", "kept"), [(None, None), ("logo", None)])
    async def test_a_missing_visual_or_picture_is_not_found(
        self, call: str | None, kept: Any
    ) -> None:
        with (
            patch("app.services.visual.ConversationService.get_conversation", new=AsyncMock()),
            patch(
                "app.services.visual.conversation_repo.tool_call_in_conversation",
                new=AsyncMock(return_value=None if call is None else self._call(call)),
            ),
            patch("app.services.visual.load_image", new=AsyncMock(return_value=kept)),
            pytest.raises(NotFoundError),
        ):
            await VisualService(MagicMock()).image(_ctx(), uuid.uuid4(), "d", "logo")

    async def test_a_key_with_no_person_reads_nothing(self) -> None:
        with pytest.raises(NotFoundError):
            await VisualService(MagicMock()).image(_ctx(user=False), uuid.uuid4(), "d", "logo")


class TestDocuments:
    def test_an_html_visual_is_its_own_document(self) -> None:
        assert visuals.visual_document("html", "<p>x</p>", title="T") == "<p>x</p>"

    def test_an_svg_visual_is_wrapped_with_its_title_escaped(self) -> None:
        page = visuals.visual_document("svg", SVG, title="A & B")
        assert "<title>A &amp; B</title>" in page
        assert SVG in page

    def test_mermaid_source_is_escaped_into_the_page(self) -> None:
        page = visuals.visual_document("mermaid", "A --> B<br>", title="T")
        assert "A --&gt; B&lt;br&gt;" in page
        assert "lib/mermaid-12.1.0.min.js" in page

    async def test_the_frame_carries_the_templates_and_is_read_once(self, monkeypatch) -> None:
        monkeypatch.setattr(visuals, "_frame", None)
        first = await visuals.frame_document()
        second = await visuals.frame_document()
        assert first is second
        text = first.decode()
        assert "__agenticosVisualDocument" in text
        # A template's own `</script>` would end the script that carries it.
        composer = text[text.index("var T = ") :]
        assert "</script>" not in composer.split("};\n")[0]
        assert "lib/idiomorph-0.8.0.min.js" in text


class TestSharedThread:
    def _thread(self, *calls: SimpleNamespace) -> SimpleNamespace:
        drew = SimpleNamespace(id=uuid.uuid4(), tool_calls=list(calls))
        said = SimpleNamespace(id=uuid.uuid4(), tool_calls=None)
        return SimpleNamespace(
            id=uuid.uuid4(), organization_id=uuid.uuid4(), messages=[said, drew]
        ), drew

    def _call(
        self,
        call_id: str,
        name: str,
        args: dict[str, Any],
        status: str = "completed",
        result: str | None = "Drew it as visual.",
    ):
        return SimpleNamespace(
            tool_call_id=call_id, tool_name=name, args=args, status=status, result=result
        )

    async def test_each_visual_is_sent_finished_with_its_pictures_inlined(self) -> None:
        conversation, drew = self._thread(
            self._call(
                "d",
                "draw",
                {
                    "title": "Poster",
                    "kind": "html",
                    "content": '<img src="{{image:bg}}"><img src="{{image:gone}}">',
                    "images": [{"name": "bg", "source": "a"}, {"name": "gone", "source": "b"}],
                },
            ),
            self._call(
                "r",
                "revise_visual",
                {"visual_id": "d", "edits": [{"old": '<img src="{{image:gone}}">', "new": "<hr>"}]},
            ),
            self._call("w", "web_fetch", {"url": "https://example.com"}),
            self._call("f", "draw", {"kind": "svg", "content": SVG}, status="failed"),
            self._call("b", "draw", {"kind": "pdf", "content": "x"}),
        )
        with patch(
            "app.services.visual.load_image",
            new=AsyncMock(side_effect=lambda *a: (PNG, "image/png") if a[-1] == "bg" else None),
        ):
            shared = await visuals.shared_visuals(conversation)

        assert list(shared) == [drew.id]
        first, revised = shared[drew.id]
        assert first["id"] == "d"
        assert first["title"] == "Poster"
        assert first["content"].startswith('<img src="data:image/png;base64,')
        assert "{{image:gone}}" in first["content"]
        assert revised["id"] == "r"
        assert revised["content"].endswith("<hr>")
        assert revised["content"].startswith('<img src="data:image/png;base64,')

    @pytest.mark.security
    async def test_a_drawing_that_was_refused_is_not_shown(self) -> None:
        """A call refused with a retry prompt is stored completed too; showing it
        would publish a drawing that never passed the checks."""
        conversation, _ = self._thread(
            self._call(
                "d",
                "draw",
                {"kind": "html", "content": '<script src="https://evil.example/x.js"></script>'},
                result="A drawing may not load a script from another site.",
            )
        )
        assert await visuals.shared_visuals(conversation) == {}

    @pytest.mark.security
    async def test_a_shared_thread_shows_only_its_newest_visuals(self) -> None:
        """Anybody holding the link can ask for it, so one view is bounded."""
        calls = [
            self._call(f"d{i}", "draw", {"kind": "svg", "content": SVG})
            for i in range(SHARED_MAX_VISUALS + 3)
        ]
        conversation, drew = self._thread(*calls)

        shared = await visuals.shared_visuals(conversation)

        ids = [visual["id"] for visual in shared[drew.id]]
        assert ids == [f"d{i}" for i in range(3, SHARED_MAX_VISUALS + 3)]

    @pytest.mark.security
    async def test_a_visual_past_the_byte_budget_is_left_out_unread(self) -> None:
        big = "<svg>" + "x" * SHARED_MAX_BYTES + "</svg>"
        conversation, drew = self._thread(
            self._call("older", "draw", {"kind": "svg", "content": SVG}),
            self._call("big", "draw", {"kind": "svg", "content": big}),
            self._call(
                "pictures",
                "draw",
                {
                    "kind": "html",
                    "content": "{{image:a}}",
                    "images": [{"name": "a", "source": "a.png"}],
                },
            ),
        )
        load = AsyncMock(return_value=(PNG, "image/png"))
        with patch("app.services.visual.load_image", new=load):
            shared = await visuals.shared_visuals(conversation)

        # The newest fits, the big one does not, and the oldest still does.
        assert [visual["id"] for visual in shared[drew.id]] == ["older", "pictures"]
        load.assert_awaited_once()

    async def test_a_thread_with_no_messages_shares_no_visuals(self) -> None:
        conversation = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4(), messages=None)
        assert await visuals.shared_visuals(conversation) == {}


class TestTheIndex:
    async def test_a_drawing_is_indexed_on_a_session_of_its_own(self) -> None:
        db = MagicMock()
        with (
            patch("app.services.visual.get_db_context", _db_context(db)),
            patch("app.services.visual.visual_repo.record", new=AsyncMock()) as record,
        ):
            await visuals.record_visual(
                organization_id=uuid.uuid4(),
                conversation_id=uuid.uuid4(),
                tool_call_id="c",
                agent_id=None,
                user_id=None,
                title="Flow",
                kind="svg",
                revision_of=None,
            )
        assert record.await_args.args == (db,)
        assert record.await_args.kwargs["title"] == "Flow"

    async def test_recent_lists_the_caller_s_own_drawings(self) -> None:
        from datetime import UTC, datetime

        ctx = _ctx()
        row = SimpleNamespace(
            id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            tool_call_id="c",
            agent_id=None,
            title="Flow",
            kind="svg",
            revision_of=None,
            artifact_id=None,
            thumbnail_path="media/x",
            created_at=datetime(2026, 10, 16, tzinfo=UTC),
        )
        with patch(
            "app.services.visual.visual_repo.recent", new=AsyncMock(return_value=[row])
        ) as recent:
            listed = await VisualService(MagicMock()).recent(ctx, limit=6)
        assert recent.await_args.kwargs == {
            "organization_id": ctx.organization_id,
            "user_id": ctx.user_id,
            "limit": 6,
        }
        assert listed.items[0].has_thumbnail is True

    async def test_a_key_with_no_person_has_no_recent_drawings(self) -> None:
        assert (await VisualService(MagicMock()).recent(_ctx(user=False), limit=6)).items == []

    async def test_a_thumbnail_is_read_only_by_its_person(self) -> None:
        ctx = _ctx()
        mine = SimpleNamespace(user_id=ctx.user_id, thumbnail_path="media/t")
        theirs = SimpleNamespace(user_id=uuid.uuid4(), thumbnail_path="media/t")
        storage = MagicMock(load=AsyncMock(return_value=PNG))
        with (
            patch("app.services.visual.get_file_storage", return_value=storage),
            patch("app.services.visual.visual_repo.get", new=AsyncMock(side_effect=[mine, theirs])),
        ):
            assert await VisualService(MagicMock()).thumbnail(ctx, uuid.uuid4()) == PNG
            with pytest.raises(NotFoundError):
                await VisualService(MagicMock()).thumbnail(ctx, uuid.uuid4())

    async def test_a_drawing_without_a_thumbnail_has_none_to_give(self) -> None:
        ctx = _ctx()
        with (
            patch(
                "app.services.visual.visual_repo.get",
                new=AsyncMock(
                    return_value=SimpleNamespace(user_id=ctx.user_id, thumbnail_path=None)
                ),
            ),
            pytest.raises(NotFoundError),
        ):
            await VisualService(MagicMock()).thumbnail(ctx, uuid.uuid4())

    async def test_the_person_s_thumbnail_is_kept_beside_the_pictures(self) -> None:
        ctx = _ctx()
        conversation = uuid.uuid4()
        row = SimpleNamespace(organization_id=ctx.organization_id, user_id=ctx.user_id)
        storage = MagicMock(save_at=AsyncMock())
        with (
            patch("app.services.visual.get_file_storage", return_value=storage),
            patch("app.services.visual.visual_repo.get_by_call", new=AsyncMock(return_value=row)),
            patch("app.services.visual.visual_repo.update", new=AsyncMock()) as update,
        ):
            await VisualService(MagicMock()).save_thumbnail(ctx, conversation, "c", PNG)
        path = visuals.image_path(ctx.organization_id, conversation, "c", "_thumbnail")
        storage.save_at.assert_awaited_once_with(path, PNG)
        assert update.await_args.kwargs["thumbnail_path"] == path

    @pytest.mark.security
    @pytest.mark.parametrize("whose", ["nobody", "other-person", "other-org"])
    async def test_only_the_person_sets_their_thumbnail(self, whose: str) -> None:
        ctx = _ctx()
        row = {
            "nobody": None,
            "other-person": SimpleNamespace(
                organization_id=ctx.organization_id, user_id=uuid.uuid4()
            ),
            "other-org": SimpleNamespace(organization_id=uuid.uuid4(), user_id=ctx.user_id),
        }[whose]
        with (
            patch("app.services.visual.visual_repo.get_by_call", new=AsyncMock(return_value=row)),
            pytest.raises(NotFoundError),
        ):
            await VisualService(MagicMock()).save_thumbnail(ctx, uuid.uuid4(), "c", PNG)

    @pytest.mark.parametrize("data", [b"<svg/>", PNG + b"\x00" * (513 * 1024)])
    async def test_a_thumbnail_is_a_small_png(self, data: bytes) -> None:
        ctx = _ctx()
        row = SimpleNamespace(organization_id=ctx.organization_id, user_id=ctx.user_id)
        with (
            patch("app.services.visual.visual_repo.get_by_call", new=AsyncMock(return_value=row)),
            pytest.raises(BadRequestError, match="PNG"),
        ):
            await VisualService(MagicMock()).save_thumbnail(ctx, uuid.uuid4(), "c", data)

    async def test_saving_a_drawing_as_an_app_records_the_app_only(self) -> None:
        from app.repositories import visual as visual_repo

        db = MagicMock(flush=AsyncMock(), refresh=AsyncMock())
        row = SimpleNamespace(artifact_id=None, thumbnail_path="media/t")
        artifact = uuid.uuid4()
        await visual_repo.update(db, db_visual=row, artifact_id=artifact)
        assert (row.artifact_id, row.thumbnail_path) == (artifact, "media/t")


class TestThumbnailDrawnOnDemand:
    def _row(self, ctx: AuthContext) -> SimpleNamespace:
        return SimpleNamespace(
            user_id=ctx.user_id,
            thumbnail_path=None,
            organization_id=ctx.organization_id,
            conversation_id=uuid.uuid4(),
            tool_call_id="d",
        )

    async def test_a_page_is_drawn_by_the_browser_once_and_kept(self) -> None:
        ctx = _ctx()
        row = self._row(ctx)
        call = ToolCallArgs("d", "draw", {"title": "P", "kind": "svg", "content": SVG})
        storage = MagicMock(save_at=AsyncMock())
        with (
            patch("app.services.visual.visual_repo.get", new=AsyncMock(return_value=row)),
            patch(
                "app.services.visual.conversation_repo.tool_call_in_conversation",
                new=AsyncMock(return_value=call),
            ),
            patch("app.services.visual_render.available", return_value=True),
            patch(
                "app.services.visual_render.render_png", new=AsyncMock(return_value=PNG)
            ) as render,
            patch("app.services.visual.get_file_storage", return_value=storage),
            patch("app.services.visual.visual_repo.update", new=AsyncMock()) as update,
        ):
            assert await VisualService(MagicMock()).thumbnail(ctx, uuid.uuid4()) == PNG
        assert render.await_args.kwargs["width"] == 640
        assert render.await_args.kwargs["aspect"] == 1.0
        folder = hashlib.sha256(b"d").hexdigest()[:32]
        assert update.await_args.kwargs["thumbnail_path"].endswith(f"/visuals/{folder}/_thumbnail")

    async def test_no_browser_means_no_thumbnail(self) -> None:
        ctx = _ctx()
        with (
            patch(
                "app.services.visual.visual_repo.get", new=AsyncMock(return_value=self._row(ctx))
            ),
            patch("app.services.visual_render.available", return_value=False),
            pytest.raises(NotFoundError),
        ):
            await VisualService(MagicMock()).thumbnail(ctx, uuid.uuid4())

    async def test_a_drawing_that_will_not_render_has_no_thumbnail(self) -> None:
        ctx = _ctx()
        with (
            patch(
                "app.services.visual.visual_repo.get", new=AsyncMock(return_value=self._row(ctx))
            ),
            patch(
                "app.services.visual.conversation_repo.tool_call_in_conversation",
                new=AsyncMock(return_value=None),
            ),
            patch("app.services.visual_render.available", return_value=True),
            pytest.raises(NotFoundError),
        ):
            await VisualService(MagicMock()).thumbnail(ctx, uuid.uuid4())

    def test_svg_aspect_reads_the_view_box(self) -> None:
        assert visuals.svg_aspect('<svg viewBox="0 0 200 100">') == 0.5
        assert visuals.svg_aspect("<svg>") is None
        assert visuals.svg_aspect('<svg viewBox="0 0 0 1">') is None
