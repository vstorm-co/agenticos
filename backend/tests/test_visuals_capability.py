"""The `draw`, `revise_visual` and `read_visual` tools, and the capability around them.

A wrong call is steered and never ends the run on its last attempt; nothing the
model passes reaches past the run's own conversation; a picture comes only from
an attachment of the thread, the workspace, or - for an agent that already reads
the web - an address; and the person's browser's report reaches the model.
"""

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx2
import pytest
from pydantic_ai import ModelRetry
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities import _registry as registry
from app.agents.capabilities.artifacts._toolset import ArtifactEdit
from app.agents.capabilities.visuals import WEB_REACH_RESOURCE, Visuals, web_reach
from app.agents.capabilities.visuals._reach import WebReach
from app.agents.capabilities.visuals._toolset import (
    DELEGATED,
    READ_LIMIT,
    VisualImage,
    VisualsToolset,
    content_problem,
    image_problem,
    images_problem,
)
from app.agents.deps import AgentDeps
from app.agents.visual_reports import MAX_ERRORS, VisualReport, VisualReports
from app.repositories.conversation import ToolCallArgs
from app.services.visual import MAX_IMAGES, VisualSummary

pytestmark = pytest.mark.anyio

SERVICE = "app.agents.capabilities.visuals._toolset.visuals"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
SVG = '<svg viewBox="0 0 100 50"><rect width="100" height="50"/></svg>'


@pytest.fixture(autouse=True)
def _no_index(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """No database here: a run's conversation is unknown unless a test says, and
    indexing a drawing is recorded rather than written."""
    monkeypatch.setattr(f"{SERVICE}.conversation_of_run", AsyncMock(return_value=None))
    record = AsyncMock()
    monkeypatch.setattr(f"{SERVICE}.record_visual", record)
    return record


def _deps(**overrides: Any) -> AgentDeps:
    values: dict[str, Any] = {
        "organization_id": uuid.uuid4(),
        "agent_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
    }
    values.update(overrides)
    return AgentDeps(**values)


def _ctx(
    deps: AgentDeps | None = None,
    *,
    retry: int = 0,
    call_id: str = "call-1",
    messages: list[Any] | None = None,
    workspace: Any = None,
) -> RunContext[AgentDeps]:
    ctx = RunContext(
        deps=deps or _deps(),
        model=TestModel(),
        usage=RunUsage(),
        retry=retry,
        max_retries=1,
        tool_call_id=call_id,
        messages=messages or [],
    )
    if workspace is not None:
        ctx.workspace = workspace
    return ctx


def _drawn_in_run(tools: VisualsToolset, call_id: str, **args: Any) -> ModelResponse:
    """A `draw` call this run made, as its messages hold it."""
    tools.drawn.add(call_id)
    return ModelResponse(parts=[ToolCallPart(tool_name="draw", args=args, tool_call_id=call_id)])


def _reports(errors: list[str] | None) -> VisualReports:
    """Reports whose browser has already said how `call-1` went - or never will."""
    reports = VisualReports(send_images=AsyncMock())
    if errors is not None:
        reports.resolve("call-1", errors)
    return reports


async def _resolved(reports: VisualReports, call_id: str, errors: list[str]) -> None:
    reports.resolve(call_id, errors)


class TestADelegatedRun:
    """Its tool calls stay in its own run, so nothing it draws is shown in the
    conversation; claiming otherwise left the person with nothing on screen."""

    async def test_a_drawing_says_it_would_not_be_seen_and_keeps_nothing(self) -> None:
        tools = VisualsToolset()
        result = await tools.draw(
            _ctx(_deps(delegated=True)), title="Flow", kind="svg", height=480, content=SVG
        )

        assert result == DELEGATED
        assert tools.drawn == set()

    async def test_a_revision_says_the_same(self) -> None:
        tools = VisualsToolset()
        result = await tools.revise_visual(
            _ctx(_deps(delegated=True)), visual_id="v", edits=[], title=None
        )

        assert result == DELEGATED

    def test_every_delegation_is_marked_whatever_its_parent_is(self) -> None:
        assert _deps().clone_for_subagent().delegated is True
        assert _deps(delegated=True).clone_for_subagent(max_depth=1).delegated is True


class TestDraw:
    async def test_a_drawing_names_its_visual_id_and_is_remembered(self) -> None:
        tools = VisualsToolset()
        result = await tools.draw(_ctx(), title="Flow", kind="svg", height=480, content=SVG)

        assert "Drew 'Flow' as visual `call-1`" in result
        assert "Refer to it, do not repeat it." in result
        assert "kept with the conversation" in result
        assert tools.drawn == {"call-1"}

    @pytest.mark.parametrize(
        ("kwargs", "said"),
        [
            ({"kind": "png"}, "`kind` must be"),
            ({"title": "  "}, "`title` is empty"),
            ({"content": "   "}, "`content` is empty"),
            ({"content": "<div>no svg</div>"}, "one `<svg>` element"),
            (
                {"kind": "html", "content": '<script src="https://cdn.example.com/a.js"></script>'},
                "no network",
            ),
            ({"kind": "html", "content": '<img src="{{image:logo}}">'}, "{{image:logo}}"),
        ],
    )
    async def test_a_drawing_that_would_not_draw_is_steered(
        self, kwargs: dict[str, Any], said: str
    ) -> None:
        call: dict[str, Any] = {"title": "T", "kind": "svg", "height": 480, "content": SVG}
        call.update(kwargs)
        with pytest.raises(ModelRetry, match=said.replace("{", r"\{").replace("}", r"\}")):
            await VisualsToolset().draw(_ctx(), **call)

    async def test_the_last_attempt_is_answered_rather_than_retried(self) -> None:
        result = await VisualsToolset().draw(
            _ctx(retry=1), title="T", kind="mermaid", height=480, content=""
        )
        assert result == "`content` is empty. Pass the whole drawing."

    async def test_a_drawing_over_the_app_limit_is_steered(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.agents.capabilities.visuals._toolset.settings.ARTIFACT_MAX_BYTES", 10
        )
        with pytest.raises(ModelRetry, match="over the 10-byte limit"):
            await VisualsToolset().draw(_ctx(), title="T", kind="svg", height=1, content=SVG)

    async def test_a_drawing_waits_for_the_browser_and_says_it_rendered(self) -> None:
        deps = _deps(visual_reports=_reports([]))
        result = await VisualsToolset().draw(
            _ctx(deps), title="Flow", kind="svg", height=480, content=SVG
        )
        assert "rendered in the person's browser without errors" in result

    async def test_the_browser_s_errors_reach_the_model_with_what_to_do(self) -> None:
        deps = _deps(visual_reports=_reports(["Blocked: https://x (connect-src)", "boom"]))
        result = await VisualsToolset().draw(
            _ctx(deps), title="Flow", kind="html", height=480, content="<p>x</p>"
        )
        assert "- Blocked: https://x (connect-src)\n- boom" in result
        assert "`revise_visual`" in result

    async def test_a_drawing_nobody_reported_on_says_it_was_not_checked(self, monkeypatch) -> None:
        monkeypatch.setattr("app.agents.capabilities.visuals._toolset.REPORT_TIMEOUT", 0.01)
        deps = _deps(visual_reports=_reports(None))
        result = await VisualsToolset().draw(
            _ctx(deps), title="Flow", kind="svg", height=480, content=SVG
        )
        assert "no browser reported how it rendered" in result


class TestIndexing:
    async def test_a_drawing_is_listed_for_the_person_it_was_made_for(
        self, _no_index: AsyncMock
    ) -> None:
        person = uuid.uuid4()
        conversation = uuid.uuid4()
        deps = _deps(user_id=str(person))
        with patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=conversation)):
            await VisualsToolset().draw(
                _ctx(deps), title=" Flow ", kind="svg", height=1, content=SVG
            )
        assert _no_index.await_args.kwargs == {
            "organization_id": deps.organization_id,
            "conversation_id": conversation,
            "tool_call_id": "call-1",
            "agent_id": deps.agent_id,
            "user_id": person,
            "title": "Flow",
            "kind": "svg",
            "revision_of": None,
        }

    async def test_a_revision_is_listed_as_one(self, _no_index: AsyncMock) -> None:
        tools = VisualsToolset()
        messages = [_drawn_in_run(tools, "base", title="Flow", kind="svg", height=1, content=SVG)]
        with patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())):
            await tools.revise_visual(
                _ctx(messages=messages, call_id="rev"),
                visual_id="base",
                edits=[ArtifactEdit(old="<rect", new="<g")],
            )
        assert _no_index.await_args.kwargs["revision_of"] == "base"
        assert _no_index.await_args.kwargs["user_id"] is None

    async def test_a_drawing_stopped_before_its_check_is_not_listed(
        self, _no_index: AsyncMock
    ) -> None:
        """A run stopped while the browser was still reporting never finished the
        call; a row for it would be a visual nothing can rebuild."""
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(
                "app.agents.capabilities.visuals._toolset._checked",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
            pytest.raises(asyncio.CancelledError),
        ):
            await VisualsToolset().draw(
                _ctx(_deps(user_id=str(uuid.uuid4()))),
                title="Flow",
                kind="svg",
                height=480,
                content=SVG,
            )
        _no_index.assert_not_awaited()

    async def test_a_run_outside_a_thread_lists_nothing(self, _no_index: AsyncMock) -> None:
        await VisualsToolset().draw(_ctx(), title="Flow", kind="svg", height=1, content=SVG)
        _no_index.assert_not_awaited()


class TestPictures:
    def _content(self) -> str:
        return '<img src="{{image:photo}}">'

    async def test_an_attached_picture_is_kept_and_handed_to_the_console(self) -> None:
        conversation = uuid.uuid4()
        reports = _reports([])
        deps = _deps(visual_reports=reports)
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=conversation)),
            patch(f"{SERVICE}.attachment_bytes", new=AsyncMock(return_value=PNG)) as attached,
            patch(f"{SERVICE}.save_image", new=AsyncMock()) as save,
        ):
            result = await VisualsToolset().draw(
                _ctx(deps),
                title="Poster",
                kind="html",
                height=600,
                content=self._content(),
                images=[VisualImage(name="photo", source="beach.png")],
            )

        assert "without errors" in result
        attached.assert_awaited_once_with(conversation, "beach.png")
        save.assert_awaited_once_with(deps.organization_id, conversation, "call-1", "photo", PNG)
        sent_id, uris = reports.send_images.await_args.args
        assert sent_id == "call-1"
        assert uris["photo"].startswith("data:image/png;base64,")

    async def test_a_picture_without_a_watching_console_is_still_kept(self) -> None:
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(f"{SERVICE}.attachment_bytes", new=AsyncMock(return_value=PNG)),
            patch(f"{SERVICE}.save_image", new=AsyncMock()) as save,
        ):
            await VisualsToolset().draw(
                _ctx(),
                title="Poster",
                kind="html",
                height=600,
                content=self._content(),
                images=[VisualImage(name="photo", source="beach.png")],
            )
        save.assert_awaited_once()

    @pytest.mark.parametrize(
        ("images", "said"),
        [
            ([VisualImage(name=f"i{n}", source="a.png") for n in range(7)], "at most 6"),
            ([VisualImage(name="Bad Name", source="a.png")], "is not valid"),
            (
                [VisualImage(name="photo", source="a.png"), VisualImage(name="photo", source="b")],
                "share a name",
            ),
            ([VisualImage(name="photo", source="  ")], "has no `source`"),
        ],
    )
    async def test_a_wrong_list_is_steered_before_anything_is_fetched(
        self, images: list[VisualImage], said: str
    ) -> None:
        with (
            patch(f"{SERVICE}.attachment_bytes", new=AsyncMock()) as attached,
            pytest.raises(ModelRetry, match=said),
        ):
            await VisualsToolset().draw(
                _ctx(), title="T", kind="html", height=1, content="<p>x</p>", images=images
            )
        attached.assert_not_awaited()

    async def test_a_run_with_no_conversation_cannot_keep_pictures(self) -> None:
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=None)),
            pytest.raises(ModelRetry, match="need a conversation"),
        ):
            await VisualsToolset().draw(
                _ctx(),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="a.png")],
            )

    async def test_an_organization_less_run_has_no_conversation_to_keep_them_in(self) -> None:
        with pytest.raises(ModelRetry, match="need a conversation"):
            await VisualsToolset().draw(
                _ctx(_deps(run_id=None)),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="a.png")],
            )

    @pytest.mark.parametrize(
        ("data", "said"),
        [(b"<html>not a picture</html>", "is not an image"), (PNG * 200_000, "over the")],
    )
    async def test_what_is_not_a_small_picture_is_refused(self, data: bytes, said: str) -> None:
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(f"{SERVICE}.attachment_bytes", new=AsyncMock(return_value=data)),
            patch(f"{SERVICE}.save_image", new=AsyncMock()) as save,
            pytest.raises(ModelRetry, match=said),
        ):
            await VisualsToolset().draw(
                _ctx(),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="a.png")],
            )
        save.assert_not_awaited()

    @pytest.mark.security
    async def test_an_agent_that_cannot_read_the_web_cannot_fetch_a_picture(self) -> None:
        """A picture's address is a request the agent chooses, so drawing must not
        give an agent with no web access a way to send one."""
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch("app.agents.capabilities.visuals._toolset.safe_download") as download,
            pytest.raises(ModelRetry, match="cannot read the web"),
        ):
            await VisualsToolset().draw(
                _ctx(),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="https://example.com/a.png")],
            )
        download.assert_not_called()

    async def test_an_agent_that_reads_the_web_fetches_through_the_ssrf_guard(self) -> None:
        response = MagicMock(status_code=200, content=PNG)
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(
                "app.agents.capabilities.visuals._toolset.safe_download",
                new=AsyncMock(return_value=response),
            ) as download,
            patch(f"{SERVICE}.save_image", new=AsyncMock()) as save,
        ):
            await VisualsToolset(web_reach=(WebReach(allowed=None),)).draw(
                _ctx(),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="https://example.com/a.png")],
            )
        assert download.await_args.args == ("https://example.com/a.png",)
        assert download.await_args.kwargs["max_bytes"] == 2 * 1024 * 1024
        # Pinned to the host, so a redirect cannot take the request elsewhere.
        assert download.await_args.kwargs["allowed_domains"] == ["example.com"]
        save.assert_awaited_once()

    async def test_a_host_the_agents_readers_may_not_reach_is_refused_before_any_request(
        self,
    ) -> None:
        """An author's `allowed_domains` bounds the pictures too: a prompt-injected
        address must not reach a host the agent's own `web_fetch` would refuse."""
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch("app.agents.capabilities.visuals._toolset.safe_download") as download,
            pytest.raises(ModelRetry, match=r"may not read 'evil\.example'"),
        ):
            await VisualsToolset(web_reach=(WebReach(allowed=("docs.acme.com",)),)).draw(
                _ctx(),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="https://evil.example/a.png?q=secret")],
            )
        download.assert_not_called()

    @pytest.mark.parametrize(
        ("outcome", "said"),
        [
            (MagicMock(status_code=404, content=b""), "answered 404"),
            (ValueError("private address"), "could not be downloaded: private address"),
            (httpx2.ConnectError("refused"), "could not be downloaded"),
        ],
    )
    async def test_a_picture_the_web_will_not_give_is_steered(
        self, outcome: Any, said: str
    ) -> None:
        download = (
            AsyncMock(side_effect=outcome)
            if isinstance(outcome, Exception)
            else AsyncMock(return_value=outcome)
        )
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch("app.agents.capabilities.visuals._toolset.safe_download", new=download),
            pytest.raises(ModelRetry, match=said),
        ):
            await VisualsToolset(web_reach=(WebReach(allowed=None),)).draw(
                _ctx(),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="https://example.com/a.png")],
            )

    async def test_a_workspace_file_is_read_when_no_attachment_has_the_name(self) -> None:
        workspace = MagicMock(attached=True, read_bytes=AsyncMock(return_value=PNG))
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(f"{SERVICE}.attachment_bytes", new=AsyncMock(return_value=None)),
            patch(f"{SERVICE}.save_image", new=AsyncMock()) as save,
        ):
            await VisualsToolset().draw(
                _ctx(workspace=workspace),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="out/chart.png")],
            )
        workspace.read_bytes.assert_awaited_once_with("out/chart.png")
        assert save.await_args.args[-1] == PNG

    @pytest.mark.parametrize(
        ("failure", "said"),
        [
            (FileNotFoundError("gone"), "or in your workspace"),
            (PermissionError("denied by rule"), "was refused: denied by rule"),
            (WorkspaceError("session lost"), "failed: session lost"),
        ],
    )
    async def test_a_workspace_that_cannot_give_the_file_says_why(
        self, failure: Exception, said: str
    ) -> None:
        workspace = MagicMock(attached=True, read_bytes=AsyncMock(side_effect=failure))
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(f"{SERVICE}.attachment_bytes", new=AsyncMock(return_value=None)),
            pytest.raises(ModelRetry, match=said),
        ):
            await VisualsToolset().draw(
                _ctx(workspace=workspace),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="a.png")],
            )

    async def test_with_no_workspace_only_attachments_are_offered(self) -> None:
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(f"{SERVICE}.attachment_bytes", new=AsyncMock(return_value=None)),
            pytest.raises(ModelRetry, match=r"attached to this conversation\. Use the file name"),
        ):
            await VisualsToolset().draw(
                _ctx(),
                title="T",
                kind="html",
                height=1,
                content=self._content(),
                images=[VisualImage(name="photo", source="a.png")],
            )


class TestRevise:
    async def test_a_revision_applies_its_edits_to_this_run_s_drawing(self) -> None:
        tools = VisualsToolset()
        messages = [
            ModelRequest.user_text_prompt("draw"),
            _drawn_in_run(tools, "base", title="Flow", kind="svg", height=400, content=SVG),
        ]
        result = await tools.revise_visual(
            _ctx(messages=messages, call_id="rev"),
            visual_id="base",
            edits=[ArtifactEdit(old='width="100"', new='width="90"')],
        )

        assert result.startswith("Revised 'Flow' as visual `rev` (a revision of `base`).")
        assert "rev" in tools.drawn

    async def test_a_new_title_is_the_revision_s(self) -> None:
        tools = VisualsToolset()
        messages = [_drawn_in_run(tools, "base", title="Flow", kind="svg", height=1, content=SVG)]
        result = await tools.revise_visual(
            _ctx(messages=messages, call_id="rev"),
            visual_id="base",
            edits=[ArtifactEdit(old="<rect", new="<rect rx='2'")],
            title="Rounded flow",
        )
        assert "Revised 'Rounded flow'" in result

    async def test_no_edits_is_steered(self) -> None:
        with pytest.raises(ModelRetry, match="`edits` is empty"):
            await VisualsToolset().revise_visual(_ctx(), visual_id="x", edits=[])

    async def test_an_edit_that_names_no_place_is_steered_to_read_it_first(self) -> None:
        tools = VisualsToolset()
        messages = [_drawn_in_run(tools, "base", title="F", kind="svg", height=1, content=SVG)]
        with pytest.raises(ModelRetry, match="Read it with `read_visual`"):
            await tools.revise_visual(
                _ctx(messages=messages, call_id="rev"),
                visual_id="base",
                edits=[ArtifactEdit(old="nowhere", new="x")],
            )

    async def test_an_edit_that_breaks_the_drawing_is_steered(self) -> None:
        tools = VisualsToolset()
        messages = [_drawn_in_run(tools, "base", title="F", kind="svg", height=1, content=SVG)]
        with pytest.raises(ModelRetry, match="one `<svg>` element"):
            await tools.revise_visual(
                _ctx(messages=messages, call_id="rev"),
                visual_id="base",
                edits=[ArtifactEdit(old="<svg", new="<div><svg")],
            )

    async def test_a_revision_keeps_its_base_s_pictures_and_adds_its_own(self) -> None:
        tools = VisualsToolset()
        base = _drawn_in_run(
            tools,
            "base",
            title="F",
            kind="html",
            height=1,
            content='<img src="{{image:logo}}">',
            images=[{"name": "logo", "source": "logo.png"}],
        )
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(f"{SERVICE}.attachment_bytes", new=AsyncMock(return_value=PNG)),
            patch(f"{SERVICE}.save_image", new=AsyncMock()) as save,
        ):
            result = await tools.revise_visual(
                _ctx(messages=[base], call_id="rev"),
                visual_id="base",
                edits=[ArtifactEdit(old=">", new='><img src="{{image:team}}">')],
                images=[VisualImage(name="team", source="team.png")],
            )
        assert "Revised" in result
        assert save.await_args.args[2:4] == ("rev", "team")

    async def test_a_revision_may_not_use_more_pictures_than_a_drawing(self) -> None:
        """Each revision may add pictures; the visual they make still carries at
        most as many as one drawing may."""
        tools = VisualsToolset()
        names = [f"p{i}" for i in range(MAX_IMAGES + 1)]
        base = _drawn_in_run(
            tools,
            "base",
            title="F",
            kind="html",
            height=1,
            content="<p>x</p>" + "".join(f"{{{{image:{n}}}}}" for n in names[:3]),
            images=[{"name": n, "source": "a.png"} for n in names[:3]],
        )
        with pytest.raises(ModelRetry, match=f"at most {MAX_IMAGES} images"):
            await tools.revise_visual(
                _ctx(messages=[base], call_id="rev"),
                visual_id="base",
                edits=[ArtifactEdit(old="x", new="".join(f"{{{{image:{n}}}}}" for n in names[3:]))],
                images=[VisualImage(name=n, source="a.png") for n in names[3:]],
            )
        assert "rev" not in tools.drawn

    async def test_a_revision_whose_picture_is_refused_keeps_nothing(self) -> None:
        tools = VisualsToolset()
        base = _drawn_in_run(tools, "base", title="F", kind="html", height=1, content="<p>x</p>")
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=None)),
            pytest.raises(ModelRetry, match="need a conversation"),
        ):
            await tools.revise_visual(
                _ctx(messages=[base], call_id="rev"),
                visual_id="base",
                edits=[ArtifactEdit(old="x", new="y")],
                images=[VisualImage(name="team", source="team.png")],
            )
        assert "rev" not in tools.drawn

    async def test_an_earlier_turn_s_drawing_is_found_in_the_conversation(self) -> None:
        conversation = uuid.uuid4()
        stored = ToolCallArgs("old", "draw", {"title": "Old", "kind": "svg", "content": SVG})
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=conversation)),
            patch(f"{SERVICE}.stored_call", new=AsyncMock(return_value=stored)) as lookup,
        ):
            result = await VisualsToolset().revise_visual(
                _ctx(call_id="rev"), visual_id="old", edits=[ArtifactEdit(old="<rect", new="<g")]
            )
        assert lookup.await_args.kwargs == {"conversation_id": conversation, "tool_call_id": "old"}
        assert "a revision of `old`" in result

    async def test_a_chain_of_earlier_revisions_is_followed_in_one_conversation(self) -> None:
        conversation = uuid.uuid4()
        calls = {
            "rev1": ToolCallArgs(
                "rev1",
                "revise_visual",
                {"visual_id": "old", "edits": [{"old": "<rect", "new": "<g"}]},
            ),
            "old": ToolCallArgs("old", "draw", {"title": "Old", "kind": "svg", "content": SVG}),
        }
        with (
            patch(
                f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=conversation)
            ) as found,
            patch(
                f"{SERVICE}.stored_call",
                new=AsyncMock(side_effect=lambda **kw: calls[kw["tool_call_id"]]),
            ),
        ):
            result = await VisualsToolset().read_visual(_ctx(), visual_id="rev1")
        assert "<g width" in result
        found.assert_awaited_once()

    @pytest.mark.security
    async def test_a_run_with_no_conversation_reaches_no_earlier_visual(self) -> None:
        with (
            patch(f"{SERVICE}.stored_call", new=AsyncMock()) as lookup,
            pytest.raises(ModelRetry, match="not part of a conversation"),
        ):
            await VisualsToolset().revise_visual(
                _ctx(_deps(run_id=None)), visual_id="old", edits=[ArtifactEdit(old="a", new="b")]
            )
        lookup.assert_not_awaited()

    async def test_a_steered_drawing_of_this_run_is_not_a_visual(self) -> None:
        """Only a call that returned a visual is one - a refused `draw` is in the
        messages too, and revising it would build on something nobody saw."""
        tools = VisualsToolset()
        refused = ModelResponse(
            parts=[
                TextPart(content="drawing"),
                ToolCallPart(tool_name="draw", args={"content": SVG}, tool_call_id="refused"),
            ]
        )
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(f"{SERVICE}.stored_call", new=AsyncMock(return_value=None)),
            pytest.raises(ModelRetry, match="no visual `refused`"),
        ):
            await tools.revise_visual(
                _ctx(messages=[refused]),
                visual_id="refused",
                edits=[ArtifactEdit(old="a", new="b")],
            )


class TestRead:
    async def test_a_visual_is_read_with_a_header(self) -> None:
        tools = VisualsToolset()
        messages = [_drawn_in_run(tools, "base", title="Flow", kind="svg", height=1, content=SVG)]
        result = await tools.read_visual(_ctx(messages=messages), visual_id="base")
        assert result.startswith(f"Visual `base` - 'Flow', svg, {len(SVG):,} characters.\n\n")
        assert result.endswith(SVG)

    async def test_a_long_visual_is_cut_and_says_so(self) -> None:
        tools = VisualsToolset()
        long = "<p>" + "x" * (READ_LIMIT + 10) + "</p>"
        messages = [_drawn_in_run(tools, "big", title="B", kind="html", height=1, content=long)]
        result = await tools.read_visual(_ctx(messages=messages), visual_id="big")
        assert f"Showing the first {READ_LIMIT:,}" in result

    async def test_an_unknown_id_is_steered(self) -> None:
        with (
            patch(f"{SERVICE}.conversation_of_run", new=AsyncMock(return_value=uuid.uuid4())),
            patch(f"{SERVICE}.stored_call", new=AsyncMock(return_value=None)),
            pytest.raises(ModelRetry, match="There is no visual `nope`"),
        ):
            await VisualsToolset().read_visual(_ctx(), visual_id="nope")


class TestChecks:
    def test_image_problem_names_every_unknown_picture(self) -> None:
        said = image_problem("{{image:b}} {{image:a}} {{image:a}}", {"c"})
        assert said is not None
        assert "{{image:a}}, {{image:b}}" in said

    def test_image_problem_is_quiet_when_every_picture_is_known(self) -> None:
        assert image_problem("{{image:a}}", {"a"}) is None

    def test_a_well_formed_list_has_no_problem(self) -> None:
        assert images_problem([VisualImage(name="logo", source="logo.png")]) is None

    def test_an_svg_may_lead_with_a_declaration_and_comments(self) -> None:
        assert content_problem("svg", '<?xml version="1.0"?>\n<!-- x -->\n' + SVG) is None

    def test_a_run_of_comment_closers_is_refused_without_backtracking(self) -> None:
        """`<!--.*?-->` repeated could split `--><!--` between repetitions in
        exponentially many ways, so a model's malformed lead stalled the worker
        (CodeQL). The comment body now matches one way only."""
        assert content_problem("svg", "<!--" + "--><!--" * 60) is not None


class TestCapability:
    def test_the_toolset_is_built_once(self) -> None:
        capability = Visuals()
        assert capability.get_toolset() is capability.get_toolset()

    @pytest.mark.parametrize("reach", [(WebReach(allowed=None),), ()])
    def test_the_builder_hands_the_toolset_the_agents_web_reach(
        self, reach: tuple[WebReach, ...]
    ) -> None:
        registry.load_builtins()
        resources = {WEB_REACH_RESOURCE: reach} if reach else {}
        built = registry.REGISTRY["visuals"].builder(
            registry.CapabilityBuildContext(
                binding=registry.CapabilityBinding(capability_id="visuals"),
                config=None,
                resources=resources,
            )
        )
        assert isinstance(built, Visuals)
        assert built.web_reach == reach


class TestWebReach:
    """Where a picture may come from is where the agent's readers may go."""

    def test_an_agent_with_no_web_reader_reaches_nowhere(self) -> None:
        assert web_reach([registry.CapabilityBinding(capability_id="artifacts")]) == ()

    def test_web_fetch_keeps_its_allow_and_block_lists(self) -> None:
        (reach,) = web_reach(
            [
                registry.CapabilityBinding(
                    capability_id="web_fetch",
                    config={"allowed_domains": ["Docs.Acme.com"], "blocked_domains": None},
                )
            ]
        )
        assert reach.admits("docs.acme.com.")
        assert not reach.admits("acme.com")
        (blocking,) = web_reach(
            [
                registry.CapabilityBinding(
                    capability_id="web_fetch", config={"blocked_domains": ["evil.example"]}
                )
            ]
        )
        assert blocking.admits("example.com")
        assert not blocking.admits("EVIL.example")

    def test_browser_use_matches_its_patterns(self) -> None:
        (reach,) = web_reach(
            [
                registry.CapabilityBinding(
                    capability_id="browser_use", config={"allowed_domains": ["*.Acme.com"]}
                )
            ]
        )
        assert reach.admits("shop.acme.com")
        assert not reach.admits("acme.org")
        (anywhere,) = web_reach([registry.CapabilityBinding(capability_id="browser_use")])
        assert anywhere.admits("example.com")

    def test_a_switched_off_reader_reaches_nowhere(self) -> None:
        assert (
            web_reach([registry.CapabilityBinding(capability_id="web_fetch", enabled=False)]) == ()
        )

    def test_a_host_with_no_idna_form_is_admitted_by_no_list(self) -> None:
        assert not WebReach(allowed=None).admits("a" * 64 + ".com")

    async def test_a_run_outside_a_conversation_is_told_of_no_earlier_visuals(self) -> None:
        instructions = Visuals().get_instructions()
        assert await instructions(_ctx(_deps(run_id=None))) == ""

    async def test_earlier_visuals_are_named_once_per_run(self) -> None:
        earlier = [
            VisualSummary(id="a", title="Flow", kind="svg", characters=10, revision_of=None),
            VisualSummary(id="b", title="Flow", kind="svg", characters=0, revision_of="a"),
        ]
        capability = Visuals()
        ctx = _ctx()
        with (
            patch(
                "app.agents.capabilities.visuals._capability.visuals.conversation_of_run",
                new=AsyncMock(return_value=uuid.uuid4()),
            ),
            patch(
                "app.agents.capabilities.visuals._capability.visuals.earlier_visuals",
                new=AsyncMock(return_value=earlier),
            ) as listed,
        ):
            first = await capability.get_instructions()(ctx)
            second = await capability.get_instructions()(ctx)

        assert "- `a` - Flow (svg)" in first
        assert "- `b` - Flow (svg, a revision of `a`)" in first
        assert second == first
        listed.assert_awaited_once()

    async def test_a_conversation_with_no_visuals_adds_nothing(self) -> None:
        with patch(
            "app.agents.capabilities.visuals._capability.visuals.conversation_of_run",
            new=AsyncMock(return_value=None),
        ):
            assert await Visuals().get_instructions()(_ctx()) == ""


class TestReports:
    async def test_a_report_that_arrives_first_is_waiting_for_the_tool(self) -> None:
        reports = VisualReports()
        reports.resolve("c", ["e"] * (MAX_ERRORS + 3))
        report = await reports.wait("c", 1)
        assert report == VisualReport(errors=("e",) * MAX_ERRORS)

    async def test_the_first_report_stands(self) -> None:
        reports = VisualReports()
        reports.resolve("c", [])
        reports.resolve("c", ["late"])
        assert await reports.wait("c", 1) == VisualReport(errors=())

    async def test_no_report_in_time_is_none(self) -> None:
        assert await VisualReports().wait("c", 0.01) is None

    async def test_reports_for_calls_nobody_waits_on_are_bounded(self) -> None:
        reports = VisualReports()
        for index in range(40):
            reports.resolve(f"c{index}", [])
        assert len(reports._futures) == 32

    async def test_a_long_error_is_cut(self) -> None:
        reports = VisualReports()
        reports.resolve("c", ["x" * 900])
        report = await reports.wait("c", 1)
        assert report is not None
        assert len(report.errors[0]) == 500
