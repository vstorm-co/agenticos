"""The browser_choice capability: the table, the loop, the seams and the outcomes.

Every test runs with the `browser` extra absent - the CI state - which is the
point: the capability must register, validate, build and enumerate its tool
without `cdp-use` or `typesafe-sdk`, reaching either only when `browse_page` is
called. Both engines are substituted through `PageFactory` and `DecisionFactory`,
so nothing here opens a browser or calls TypeSafe.

The split matters and it is deliberate: the modules that decide anything - which
elements may be chosen, which operation, when to stop, where the agent may go -
are exercised directly, and the module that needs a browser (`_page.py`) is
reduced to the one pure function that parses what a browser answered.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from pydantic_ai._run_context import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.browser_events import BrowserEvent
from app.agents.capabilities import CapabilityBinding, CapabilityBuildContext, get
from app.agents.capabilities.browser_choice import (
    BrowserChoice,
    BrowserChoiceConfig,
    validate_cdp_url,
)
from app.agents.capabilities.browser_choice._elements import (
    HARD_CANDIDATE_CAP,
    MAX_LABEL,
    Element,
    Snapshot,
    candidates,
    clean_label,
    render_table,
)
from app.agents.capabilities.browser_choice._endpoint import (
    EndpointError,
    domain_allowed,
    version_url,
    websocket_url,
)
from app.agents.capabilities.browser_choice._loop import (
    REPEAT_LIMIT,
    Choice,
    LoopPolicy,
    run_browse,
)
from app.agents.capabilities.browser_choice._page import (
    MISSING_EXTRA,
    READ_LIMIT,
    CdpPage,
    DomainRefused,
    PagePolicy,
    parse_snapshot,
)
from app.agents.capabilities.browser_choice._questions import (
    OPERATIONS,
    decision_type,
    index_of,
    observation,
    option_for,
    value_prompt,
)
from app.agents.capabilities.browser_choice._toolset import (
    build_toolset,
    confidence_of,
    last_response,
)
from app.agents.deps import AgentDeps
from app.core.sanitize import SSRFBlockedError, UrlRefusedError
from app.core.secret_kinds import ApiKeySecret
from app.services.agent_registry import DEFAULT_GRANTED_SCOPES

pytestmark = pytest.mark.anyio


def _element(index: int = 0, **kwargs: Any) -> Element:
    fields: dict[str, Any] = {"role": "button", "label": f"Button {index}", "x": 10.0, "y": 20.0}
    fields.update(kwargs)
    return Element(index=index, **fields)


def _snapshot(*elements: Element, **kwargs: Any) -> Snapshot:
    fields: dict[str, Any] = {
        "url": "https://example.test/page",
        "title": "A page",
        "scroll_y": 0.0,
        "scroll_height": 2000.0,
        "viewport_height": 800.0,
    }
    fields.update(kwargs)
    return Snapshot(elements=tuple(elements), **fields)


class TestTheElementTable:
    """What the model may pick, and the bounds on it.

    The table is the capability's security property: an option the page did not
    put in it is an action the model cannot choose. So its bounds are tested as
    behaviour rather than trusted as constants.
    """

    def test_a_label_keeps_one_line_and_loses_the_pages_whitespace(self):
        assert clean_label("  Accept \n  all\tcookies ") == "Accept all cookies"

    def test_a_short_label_is_left_alone(self):
        assert clean_label("Sign in") == "Sign in"

    def test_a_long_label_is_cut_at_a_word_boundary_when_one_is_near_the_end(self):
        label = clean_label(
            "Subscribe to our newsletter and receive weekly updates about "
            "everything we are building this year"
        )
        assert label.endswith("…")
        assert len(label) <= MAX_LABEL + 1
        assert not label.rstrip("…").endswith(" ")

    def test_a_long_label_with_no_late_boundary_is_cut_mid_word(self):
        # One space, at character three: honouring it would truncate a
        # seventy-character label to "A".
        raw = "A " + "x" * 200
        assert clean_label(raw) == ("A " + "x" * 200)[:MAX_LABEL] + "…"

    def test_the_candidate_set_is_truncated_in_document_order(self):
        elements = tuple(_element(i) for i in range(10))
        assert candidates(elements, 3) == elements[:3]

    def test_the_hard_cap_wins_over_a_larger_configured_one(self):
        elements = tuple(_element(i) for i in range(HARD_CANDIDATE_CAP + 50))
        assert len(candidates(elements, HARD_CANDIDATE_CAP + 50)) == HARD_CANDIDATE_CAP

    def test_an_empty_table_says_so_rather_than_rendering_nothing(self):
        assert render_table(()) == "(no interactive elements in view)"

    def test_a_field_with_a_value_shows_it(self):
        rendered = render_table((_element(0, role="textbox", label="Search", value="paris"),))
        assert rendered == "0. textbox: Search [currently: paris]"

    def test_a_page_scrolled_to_the_end_reports_it(self):
        assert _snapshot(scroll_y=1200.0, scroll_height=2000.0, viewport_height=800.0).at_bottom
        assert not _snapshot(scroll_y=0.0).at_bottom


class TestTheEndpointAndTheAllowlist:
    """Where the browser is, and where the agent may go."""

    def test_a_websocket_endpoint_is_used_as_given(self):
        assert websocket_url("ws://browser.test:9222/x", None) == "ws://browser.test:9222/x"

    def test_an_http_endpoint_is_resolved_through_json_version(self):
        payload = {"webSocketDebuggerUrl": "ws://browser.test:9222/devtools/browser/abc"}
        assert websocket_url("http://browser.test:9222", payload) == payload["webSocketDebuggerUrl"]

    def test_the_version_path_is_appended_once(self):
        assert version_url("http://browser.test:9222/") == "http://browser.test:9222/json/version"

    @pytest.mark.parametrize(
        "payload",
        [None, {}, {"webSocketDebuggerUrl": 7}, {"webSocketDebuggerUrl": "http://not-a-socket"}],
        ids=["nothing", "empty", "not-a-string", "not-a-socket"],
    )
    def test_a_payload_with_no_usable_socket_is_refused(self, payload: object):
        with pytest.raises(EndpointError, match="webSocketDebuggerUrl"):
            websocket_url("http://browser.test:9222", payload)

    def test_no_allowlist_allows_everything(self):
        assert domain_allowed("https://anything.test/a", None)

    def test_an_empty_allowlist_allows_nothing(self):
        # Not the same as `None`: an author who deleted the last entry asked for
        # nothing to be allowed, and reading that as "everything" inverts it.
        assert not domain_allowed("https://anything.test/a", [])

    def test_a_glob_matches_a_subdomain_and_nothing_else(self):
        assert domain_allowed("https://docs.example.com/x", ["*.example.com"])
        assert not domain_allowed("https://example.com.evil.test/x", ["*.example.com"])

    def test_the_host_is_matched_case_insensitively_and_the_port_is_ignored(self):
        assert domain_allowed("https://EXAMPLE.test:8443/x", ["example.test"])

    def test_a_url_with_no_host_is_refused_under_any_allowlist(self):
        assert not domain_allowed("about:blank", ["example.test"])


class TestTheTwoQuestions:
    """The output type that asks them, and the pick that comes back."""

    def test_an_option_repeats_the_table_row_so_a_pick_and_a_row_are_one_thing(self):
        element = _element(3, role="link", label="Pricing")
        assert option_for(element) == "3. link: Pricing"
        assert option_for(element) in render_table((element,))

    def test_an_options_index_leads_so_two_identical_labels_stay_distinct(self):
        first, second = _element(0, label="Next"), _element(1, label="Next")
        assert option_for(first) != option_for(second)

    def test_a_pick_resolves_to_the_element_it_named(self):
        elements = (_element(0), _element(1, role="link", label="Pricing"))
        assert index_of(option_for(elements[1]), elements) == 1

    def test_a_pick_that_names_nothing_here_resolves_to_nothing(self):
        assert index_of("99. button: Invented", (_element(0),)) is None

    def test_both_questions_are_asked_when_there_is_something_to_choose(self):
        model = decision_type((_element(0), _element(1)))
        assert set(model.model_fields) == {"operation", "target"}
        schema = model.model_json_schema()["properties"]["operation"]
        assert schema["enum"] == list(OPERATIONS)

    def test_the_target_question_is_not_asked_when_there_is_no_choice(self):
        # A pick-one needs two options, and padding the list would offer the page
        # an action the page does not have.
        assert set(decision_type((_element(0),)).model_fields) == {"operation"}
        assert set(decision_type(()).model_fields) == {"operation"}

    def test_the_observation_carries_the_goal_the_page_and_what_was_done(self):
        text = observation("find the price", _snapshot(_element(0)), ("clicked button: Accept",))
        assert "GOAL: find the price" in text
        assert "https://example.test/page" in text
        assert "clicked button: Accept" in text
        assert "untrusted page content" in text

    def test_the_observation_omits_the_history_section_when_there_is_none(self):
        assert "ALREADY DONE" not in observation("g", _snapshot(_element(0)), ())

    def test_an_untitled_page_is_named_rather_than_left_blank(self):
        assert "(untitled)" in observation("g", _snapshot(_element(0), title=""), ())

    def test_a_scrolled_page_says_which_end_it_is_at(self):
        at_end = _snapshot(_element(0), scroll_y=1200.0)
        assert "at the bottom" in observation("g", at_end, ())
        assert "more below" in observation("g", _snapshot(_element(0)), ())

    def test_the_value_prompt_is_scoped_to_one_field(self):
        prompt = value_prompt("book a flight", _element(0, role="textbox", label="From"), ("x",))
        assert "FIELD: textbox labelled 'From'" in prompt
        assert "ALREADY DONE" in prompt
        assert "nothing else" in prompt

    def test_the_value_prompt_shows_what_the_field_already_holds(self):
        prompt = value_prompt("g", _element(0, role="textbox", label="From", value="Paris"), ())
        assert "CURRENT VALUE: Paris" in prompt
        assert "ALREADY DONE" not in prompt


class TestParsingWhatABrowserAnswered:
    """The one function in `_page.py` that does not need a browser."""

    def test_a_snapshot_is_numbered_cleaned_and_truncated(self):
        raw = (
            '{"url":"https://x.test/a","title":"T","scrollY":10,"scrollHeight":900,'
            '"viewportHeight":800,"elements":['
            '{"role":"button","label":"  Accept   all ","x":1,"y":2,"value":""},'
            '{"role":"input","label":"Search","x":3,"y":4,"value":" paris "}]}'
        )
        snapshot = parse_snapshot(raw, 10)
        assert snapshot.url == "https://x.test/a"
        assert snapshot.elements[0] == Element(0, "button", "Accept all", 1.0, 2.0, None)
        assert snapshot.elements[1].value == "paris"

    def test_the_cap_is_applied_while_parsing_not_after(self):
        items = ",".join(
            f'{{"role":"button","label":"B{i}","x":1,"y":2,"value":""}}' for i in range(20)
        )
        assert len(parse_snapshot(f'{{"elements":[{items}]}}', 5).elements) == 5

    def test_a_payload_with_nothing_in_it_parses_to_an_empty_page(self):
        snapshot = parse_snapshot("{}", 10)
        assert snapshot.elements == ()
        assert snapshot.url == ""

    @pytest.mark.parametrize("raw", [None, '"a string"', "[1, 2]"], ids=["none", "string", "list"])
    def test_a_page_that_answered_something_else_is_refused_loudly(self, raw: object):
        # Valid JSON of the wrong shape included: it means the collector did not
        # run, and an AttributeError three lines later says that far worse.
        with pytest.raises(EndpointError, match="collector did not run"):
            parse_snapshot(raw, 10)

    def test_the_read_limit_is_a_bound_the_calling_model_can_rely_on(self):
        assert READ_LIMIT > 0


class _FakePage:
    """A page the loop can be driven against, with no browser behind it.

    Answers a scripted list of snapshots, one per `snapshot()` call, repeating the
    last for ever - so a test says what the page looks like as the loop works and
    does not have to say it again for every guard that reads the page one more
    time on the way out.
    """

    def __init__(self, *snapshots: Snapshot, text: str = "the page text") -> None:
        self._snapshots = list(snapshots) or [_snapshot()]
        self._text = text
        self.done: list[str] = []
        self.shots = 0

    async def snapshot(self) -> Snapshot:
        taken = self._snapshots[0]
        if len(self._snapshots) > 1:
            self._snapshots.pop(0)
        return taken

    async def click(self, element: Element) -> None:
        self.done.append(f"click:{element.index}")

    async def type_text(self, element: Element, text: str) -> None:
        self.done.append(f"type:{element.index}:{text}")

    async def select(self, element: Element) -> None:
        self.done.append(f"select:{element.index}")

    async def scroll(self) -> None:
        self.done.append("scroll")

    async def settle(self) -> None:
        self.done.append("settle")

    async def screenshot(self) -> str | None:
        self.shots += 1
        return "data:image/jpeg;base64,AAAA"

    async def read(self) -> str:
        return self._text


def _decider(*choices: Choice):
    """A decision function answering a scripted list, repeating the last."""
    remaining = list(choices)

    async def decide(goal: str, snapshot: Snapshot, history: tuple[str, ...]) -> Choice:
        taken = remaining[0]
        if len(remaining) > 1:
            remaining.pop(0)
        return taken

    return decide


async def _generate(goal: str, element: Element, history: tuple[str, ...]) -> str:
    return "typed value"


def _policy(**kwargs: Any) -> LoopPolicy:
    fields: dict[str, Any] = {"max_steps": 5, "min_confidence": 0.0, "preview": False}
    fields.update(kwargs)
    return LoopPolicy(**fields)


class _Frames:
    """Collects what a surface would have been shown."""

    def __init__(self) -> None:
        self.frames: list[BrowserEvent] = []

    async def __call__(self, event: BrowserEvent) -> None:
        self.frames.append(event)

    def kinds(self) -> list[str]:
        return [frame.kind for frame in self.frames]

    def of(self, kind: str) -> list[BrowserEvent]:
        return [frame for frame in self.frames if frame.kind == kind]


async def _browse(page: _FakePage, decide: Any, sink: Any = None, **policy: Any):
    return await run_browse(
        goal="find the price",
        page=page,
        decide=decide,
        generate=_generate,
        policy=_policy(**policy),
        call_id="call-1",
        sink=sink,
    )


class TestTheLoopStopsForAReason:
    """Four outcomes and no fifth, each reached and each narrated."""

    async def test_done_answers_with_the_page(self):
        result = await _browse(
            _FakePage(_snapshot(_element(0))), _decider(Choice("DONE", None, 0.9))
        )
        assert (result.outcome, result.text, result.steps) == ("done", "the page text", 1)

    async def test_blocked_is_an_answer_and_still_returns_what_was_read(self):
        result = await _browse(
            _FakePage(_snapshot(_element(0)), text="Please sign in"),
            _decider(Choice("BLOCKED", None, 0.8)),
        )
        assert result.outcome == "blocked"
        assert result.text == "Please sign in"

    async def test_the_step_ceiling_ends_the_browse_as_exhausted(self):
        # Each snapshot is further down the page, so this is a browse making
        # progress and running out of steps - not one going round in a circle.
        page = _FakePage(*(_snapshot(_element(0), _element(1), scroll_y=y) for y in (0, 700, 1400)))
        result = await _browse(page, _decider(Choice("SCROLL", None, 0.9)), max_steps=3)
        assert (result.outcome, result.steps) == ("exhausted", 3)

    async def test_scrolling_that_moves_nothing_is_caught_as_a_loop(self):
        page = _FakePage(_snapshot(_element(0), _element(1), scroll_y=1200.0))
        result = await _browse(page, _decider(Choice("SCROLL", None, 0.9)), max_steps=20)
        assert (result.outcome, result.steps) == ("blocked", REPEAT_LIMIT)

    async def test_the_same_action_three_times_running_ends_it_rather_than_looping(self):
        page = _FakePage(_snapshot(_element(0), _element(1)))
        result = await _browse(page, _decider(Choice("CLICK", 0, 0.9)), max_steps=20)
        assert result.outcome == "blocked"
        assert result.steps == REPEAT_LIMIT
        assert page.done.count("click:0") == REPEAT_LIMIT - 1

    async def test_a_pick_below_the_floor_is_refused_with_both_numbers(self):
        frames = _Frames()
        result = await _browse(
            _FakePage(_snapshot(_element(0), _element(1))),
            _decider(Choice("CLICK", 0, 0.22)),
            frames,
            min_confidence=0.5,
        )
        assert result.outcome == "blocked"
        detail = frames.of("browser_finished")[0].detail or ""
        assert "0.22" in detail and "0.50" in detail

    async def test_an_element_operation_with_no_element_is_refused_not_guessed(self):
        frames = _Frames()
        result = await _browse(
            _FakePage(_snapshot(_element(0), _element(1))),
            _decider(Choice("CLICK", None, 0.9)),
            frames,
        )
        assert result.outcome == "blocked"
        assert "without an element" in (frames.of("browser_finished")[0].detail or "")

    async def test_a_pick_naming_an_element_the_snapshot_does_not_hold_is_refused(self):
        result = await _browse(
            _FakePage(_snapshot(_element(0), _element(1))), _decider(Choice("CLICK", 99, 0.9))
        )
        assert result.outcome == "blocked"


class TestTheLoopCarriesOutWhatWasChosen:
    """Each operation, and the history line it leaves for the next decision."""

    async def test_a_click_uses_the_coordinates_the_snapshot_offered(self):
        page = _FakePage(_snapshot(_element(0), _element(1)))
        await _browse(page, _decider(Choice("CLICK", 1, 0.9), Choice("DONE", None, 0.9)))
        assert page.done[:2] == ["click:1", "settle"]

    async def test_typing_asks_a_language_model_for_the_value(self):
        page = _FakePage(_snapshot(_element(0, role="textbox", label="Search"), _element(1)))
        await _browse(page, _decider(Choice("TYPE_TEXT", 0, 0.9), Choice("DONE", None, 0.9)))
        assert page.done[0] == "type:0:typed value"

    async def test_select_opens_the_dropdown_rather_than_picking_blind(self):
        page = _FakePage(_snapshot(_element(0, role="dropdown"), _element(1)))
        await _browse(page, _decider(Choice("SELECT", 0, 0.9), Choice("DONE", None, 0.9)))
        assert page.done[0] == "select:0"

    async def test_scroll_and_wait_address_the_page_not_an_element(self):
        page = _FakePage(_snapshot(_element(0), _element(1)))
        await _browse(
            page,
            _decider(
                Choice("SCROLL", None, 0.9), Choice("WAIT", None, 0.9), Choice("DONE", None, 0.9)
            ),
        )
        assert page.done[0] == "scroll"
        assert page.done[2:4] == ["settle", "settle"]

    async def test_a_scroll_that_also_names_a_target_still_scrolls(self):
        # Dispatch is on the operation. Routing by the target's presence would
        # send this down the typing path.
        page = _FakePage(_snapshot(_element(0), _element(1)))
        await _browse(page, _decider(Choice("SCROLL", 0, 0.9), Choice("DONE", None, 0.9)))
        assert page.done[0] == "scroll"

    async def test_the_history_names_what_was_acted_on(self):
        seen: list[tuple[str, ...]] = []

        async def decide(goal: str, snapshot: Snapshot, history: tuple[str, ...]) -> Choice:
            seen.append(history)
            return Choice("CLICK", 0, 0.9) if not history else Choice("DONE", None, 0.9)

        await _browse(_FakePage(_snapshot(_element(0, label="Accept all"), _element(1))), decide)
        assert seen[1] == ("clicked button: Accept all",)


class TestWhatASurfaceIsShown:
    """The frames, and the guarantee that a finish always arrives."""

    async def test_a_browse_opens_with_its_goal_and_its_ceiling(self):
        frames = _Frames()
        await _browse(
            _FakePage(_snapshot(_element(0))), _decider(Choice("DONE", None, 0.9)), frames
        )
        opened = frames.of("browser_opened")[0]
        assert (opened.goal, opened.max_steps, opened.step) == ("find the price", 5, 0)

    async def test_every_step_carries_its_number_its_pick_and_its_confidence(self):
        frames = _Frames()
        await _browse(
            _FakePage(_snapshot(_element(0, label="Accept all"), _element(1))),
            _decider(Choice("CLICK", 0, 0.77), Choice("DONE", None, 0.9)),
            frames,
        )
        step = frames.of("browser_step")[0]
        assert (step.step, step.operation, step.target, step.confidence) == (
            1,
            "CLICK",
            "Accept all",
            0.77,
        )

    async def test_every_outcome_sends_a_finish_frame(self):
        for choice, outcome in (
            (Choice("DONE", None, 0.9), "done"),
            (Choice("BLOCKED", None, 0.9), "blocked"),
            (Choice("CLICK", None, 0.9), "blocked"),
        ):
            frames = _Frames()
            await _browse(_FakePage(_snapshot(_element(0), _element(1))), _decider(choice), frames)
            assert frames.of("browser_finished")[0].outcome == outcome

    async def test_the_ceiling_also_sends_one(self):
        frames = _Frames()
        await _browse(
            _FakePage(_snapshot(_element(0), _element(1))),
            _decider(Choice("SCROLL", None, 0.9)),
            frames,
            max_steps=2,
        )
        assert frames.of("browser_finished")[0].outcome == "exhausted"

    async def test_previews_are_a_separate_frame_from_the_narration(self):
        frames = _Frames()
        page = _FakePage(_snapshot(_element(0)))
        await _browse(page, _decider(Choice("DONE", None, 0.9)), frames, preview=True)
        assert frames.kinds() == [
            "browser_opened",
            "browser_frame",
            "browser_step",
            "browser_finished",
        ]
        assert frames.of("browser_frame")[0].image == "data:image/jpeg;base64,AAAA"

    async def test_previews_off_takes_no_screenshot_at_all(self):
        page = _FakePage(_snapshot(_element(0)))
        frames = _Frames()
        await _browse(page, _decider(Choice("DONE", None, 0.9)), frames, preview=False)
        assert page.shots == 0
        assert frames.of("browser_frame") == []

    async def test_a_page_with_no_picture_to_send_sends_no_frame(self):
        class _Blind(_FakePage):
            async def screenshot(self) -> str | None:
                return None

        frames = _Frames()
        await _browse(
            _Blind(_snapshot(_element(0))),
            _decider(Choice("DONE", None, 0.9)),
            frames,
            preview=True,
        )
        assert frames.of("browser_frame") == []

    async def test_a_surface_that_cannot_narrate_still_runs_the_browse(self):
        result = await _browse(
            _FakePage(_snapshot(_element(0))), _decider(Choice("DONE", None, 0.9))
        )
        assert result.outcome == "done"

    async def test_a_model_that_reports_no_confidence_sends_none_rather_than_a_number(self):
        frames = _Frames()
        await _browse(
            _FakePage(_snapshot(_element(0))), _decider(Choice("DONE", None, None)), frames
        )
        assert frames.of("browser_step")[0].confidence is None


def _decision_model(operation: str, target: str | None, confidence: dict[str, float] | None):
    """A decision model answering one fixed pick, with its confidences.

    A `FunctionModel` rather than a `TestModel` because the number this capability
    exists to surface - how sure the pick was - arrives in `provider_details`, and
    only a model that writes one can be used to check that it is read.
    """

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        args: dict[str, Any] = {"operation": operation}
        if target is not None:
            args["target"] = target
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, args)],
            provider_details={"confidence": confidence} if confidence is not None else None,
        )

    return FunctionModel(answer)


@asynccontextmanager
async def _fake_browser(page: _FakePage, **_: Any) -> AsyncIterator[_FakePage]:
    yield page


def _tool_context(sink: Any = None) -> RunContext[AgentDeps]:
    return RunContext(
        deps=AgentDeps(browser_events=sink),
        model=TestModel(custom_output_text="typed value"),
        usage=RunUsage(),
        tool_call_id="call-42",
    )


async def _call(
    page: _FakePage | None = None,
    *,
    sink: Any = None,
    cdp_url: str = "http://8.8.8.8:9222",
    api_key: str | None = "key",
    decision: Any = None,
    page_factory: Any = None,
    **policy: Any,
) -> str:
    """Call `browse_page` through the toolset, as the runner would."""
    target = page if page is not None else _FakePage(_snapshot(_element(0), _element(1)))
    model = decision if decision is not None else _decision_model("DONE", None, {"operation": 0.9})

    def _factory(*_: Any) -> Any:
        return model

    toolset = build_toolset(
        cdp_url=cdp_url,
        api_key=api_key,
        decision_model="jev-latest",
        decision_base_url=None,
        page_policy=PagePolicy(
            allowed_domains=None, candidate_cap=60, preview=False, preview_width=1024
        ),
        loop_policy=_policy(**policy),
        page_factory=page_factory or (lambda **kwargs: _fake_browser(target, **kwargs)),
        decision_factory=_factory,
    )
    ctx = _tool_context(sink)
    tools = await toolset.get_tools(ctx)
    return str(
        await toolset.call_tool(
            "browse_page",
            {"goal": "find the price", "start_url": "https://example.test/page"},
            ctx,
            tools["browse_page"],
        )
    )


class TestHowSureTheStepWas:
    """The number this capability exists to surface, and how it is taken."""

    def test_the_lowest_of_the_two_answers_is_what_travels(self):
        # A confident CLICK on an element picked at 0.2 is not a confident step,
        # and reporting 0.9 for it is the one number a reviewer needs not told.
        response = ModelResponse(
            parts=[], provider_details={"confidence": {"operation": 0.9, "target": 0.2}}
        )
        assert confidence_of(response) == 0.2

    @pytest.mark.parametrize(
        "details",
        [None, {}, {"confidence": None}, {"confidence": {}}, {"confidence": {"a": "high"}}],
        ids=["none", "empty", "null", "no-fields", "not-a-number"],
    )
    def test_a_model_that_reports_nothing_usable_reports_nothing(self, details: Any):
        assert confidence_of(ModelResponse(parts=[], provider_details=details)) is None

    def test_no_response_at_all_reports_nothing(self):
        assert confidence_of(None) is None

    def test_the_last_response_is_what_is_read(self):
        first = ModelResponse(parts=[TextPart("a")], provider_details={"confidence": {"x": 0.1}})
        second = ModelResponse(parts=[TextPart("b")], provider_details={"confidence": {"x": 0.9}})
        assert last_response([first, second]) is second
        assert last_response([]) is None


class TestTheToolRefusesBeforeItOpensAnything:
    """Both halves of the configuration, each refused in a sentence."""

    async def test_no_endpoint_is_said_rather_than_dialled(self):
        assert "no browser endpoint" in await _call(cdp_url="")

    async def test_no_key_is_said_rather_than_authenticated_as_nobody(self):
        assert "no decision-model" in await _call(api_key=None)


class TestTheToolEndToEnd:
    """The whole body, with both engines substituted."""

    async def test_a_finished_browse_answers_with_the_outcome_and_the_page(self):
        answer = await _call(_FakePage(_snapshot(_element(0), _element(1)), text="EUR 29"))
        assert answer.startswith("Finished: find the price")
        assert "untrusted" in answer
        assert "EUR 29" in answer

    async def test_a_pick_is_resolved_back_to_the_element_it_named(self):
        page = _FakePage(_snapshot(_element(0, label="Accept all"), _element(1)))
        target = option_for(_element(0, label="Accept all"))
        frames = _Frames()
        await _call(
            page,
            sink=frames,
            decision=_decision_model("CLICK", target, {"operation": 0.9, "target": 0.8}),
            max_steps=1,
        )
        assert page.done[0] == "click:0"
        assert frames.of("browser_step")[0].confidence == 0.8

    async def test_one_element_in_view_needs_no_pick_and_is_resolved_here(self):
        # With a single candidate there is no pick-one to answer, so the target
        # question is not asked - and the loop must still act on the one element.
        page = _FakePage(_snapshot(_element(0, label="Only button")))
        await _call(page, decision=_decision_model("CLICK", None, None), max_steps=1)
        assert page.done[0] == "click:0"

    async def test_a_blocked_browse_says_so_and_still_returns_what_it_read(self):
        answer = await _call(
            _FakePage(_snapshot(_element(0), _element(1)), text="Please sign in"),
            decision=_decision_model("BLOCKED", None, {"operation": 0.95}),
        )
        assert answer.startswith("Blocked after 1 steps")
        assert "Please sign in" in answer

    async def test_the_ceiling_is_reported_as_a_stop_not_as_a_failure(self):
        page = _FakePage(*(_snapshot(_element(0), _element(1), scroll_y=y) for y in (0, 700, 1400)))
        answer = await _call(
            page, decision=_decision_model("SCROLL", None, {"operation": 0.9}), max_steps=2
        )
        assert answer.startswith("Stopped at the step ceiling after 2 steps")

    async def test_typing_a_field_asks_the_runs_own_model_for_the_value(self):
        page = _FakePage(_snapshot(_element(0, role="textbox", label="Search"), _element(1)))
        target = option_for(_element(0, role="textbox", label="Search"))
        await _call(page, decision=_decision_model("TYPE_TEXT", target, None), max_steps=1)
        assert page.done[0] == "type:0:typed value"

    async def test_a_url_outside_the_allowlist_is_refused_with_a_finish_frame(self):
        @asynccontextmanager
        async def refusing(**_: Any) -> AsyncIterator[_FakePage]:
            raise DomainRefused("https://elsewhere.test is outside this agent's allowed domains.")
            yield  # pragma: no cover - unreachable, and the generator needs it

        frames = _Frames()
        answer = await _call(sink=frames, page_factory=refusing)
        assert "outside this agent's allowed domains" in answer
        assert frames.of("browser_finished")[0].outcome == "failed"

    async def test_an_endpoint_that_is_not_a_browser_is_reported_not_raised(self):
        @asynccontextmanager
        async def not_a_browser(**_: Any) -> AsyncIterator[_FakePage]:
            raise EndpointError("did not answer with a webSocketDebuggerUrl")
            yield  # pragma: no cover - unreachable, and the generator needs it

        assert "webSocketDebuggerUrl" in await _call(page_factory=not_a_browser)

    async def test_a_missing_extra_answers_with_the_install_line(self):
        @asynccontextmanager
        async def uninstalled(**_: Any) -> AsyncIterator[_FakePage]:
            raise RuntimeError(MISSING_EXTRA)
            yield  # pragma: no cover - unreachable, and the generator needs it

        assert "agenticos[browser]" in await _call(page_factory=uninstalled)

    async def test_any_other_runtime_failure_stays_a_failure(self):
        # A bug must not be laundered into a sentence the model reads as an answer.
        @asynccontextmanager
        async def broken(**_: Any) -> AsyncIterator[_FakePage]:
            raise RuntimeError("something else entirely")
            yield  # pragma: no cover - unreachable, and the generator needs it

        with pytest.raises(RuntimeError, match="something else entirely"):
            await _call(page_factory=broken)

    async def test_a_surface_with_no_sink_still_completes(self):
        assert (await _call(sink=None)).startswith("Finished")


class TestRegistrationAndPublish:
    """What the Builder offers, and what publishing refuses."""

    def test_the_tool_is_declared_side_effecting_on_both(self):
        definition = get("browser_choice")
        assert definition.side_effecting
        assert [tool.id for tool in definition.tools] == ["browse_page"]
        assert definition.tools[0].side_effecting

    def test_the_scope_it_needs_is_one_a_deployment_grants_by_default(self):
        assert set(get("browser_choice").scopes) <= set(DEFAULT_GRANTED_SCOPES)

    def test_it_requires_a_key_so_no_browse_runs_without_an_operator_adding_one(self):
        # The requirement is the opt-in: page content leaves the deployment, and
        # nothing here reads an ambient TYPESAFE_API_KEY.
        assert get("browser_choice").secret is not None

    def test_the_defaults_are_the_ones_the_capability_documents(self):
        config = BrowserChoiceConfig()
        assert (config.max_steps, config.candidate_cap, config.min_confidence) == (25, 60, 0.0)
        assert config.preview
        assert config.cdp_url == ""

    def test_a_candidate_cap_past_the_pick_one_ceiling_is_refused(self):
        with pytest.raises(ValueError, match="candidate_cap"):
            BrowserChoiceConfig(cdp_url="http://x.test:9222", candidate_cap=HARD_CANDIDATE_CAP + 1)

    def test_publishing_without_an_endpoint_is_refused_in_words(self):
        with pytest.raises(UrlRefusedError, match="needs a cdp_url"):
            validate_cdp_url(BrowserChoiceConfig())

    def test_publishing_a_loopback_debugger_is_refused(self):
        with pytest.raises(SSRFBlockedError):
            validate_cdp_url(BrowserChoiceConfig(cdp_url="http://127.0.0.1:9222"))

    def test_a_public_websocket_endpoint_is_accepted(self):
        validate_cdp_url(BrowserChoiceConfig(cdp_url="ws://8.8.8.8:9222/devtools/browser/x"))

    def test_the_builder_carries_the_vault_key_and_never_the_model_facing_config(self):
        built = _build_capability(
            {"cdp_url": "http://8.8.8.8:9222", "max_steps": 9}, key="sk-test-12345"
        )
        assert isinstance(built, BrowserChoice)
        assert built.api_key == "sk-test-12345"
        assert built.max_steps == 9
        assert "sk-test-12345" not in repr(built)

    def test_the_builder_still_builds_with_nothing_configured(self):
        # A builder that returns `None` is a capability the registry's drift check
        # cannot enumerate, and that check is what catches an undeclared
        # side-effecting tool.
        assert isinstance(_build_capability({}, key=None), BrowserChoice)


def _build_capability(config: dict[str, Any], *, key: str | None) -> Any:
    """Assemble the capability through its registered builder, as the runner would."""
    definition = get("browser_choice")
    return definition.builder(
        CapabilityBuildContext(
            binding=CapabilityBinding(capability_id="browser_choice", config=config),
            config=definition.validate_config(config),
            resources={},
            secret=ApiKeySecret(api_key=key) if key else None,
        )
    )


class TestTheCapabilityItself:
    """What an agent is handed, assembled the way the runner assembles it."""

    def test_the_instructions_say_when_to_use_it_and_to_distrust_what_it_returns(self):
        instructions = BrowserChoice().get_instructions()
        assert "browse_page" in instructions
        assert "untrusted data" in instructions
        assert "blocked" in instructions

    def test_the_toolset_offers_exactly_the_declared_tool(self):
        toolset = BrowserChoice(cdp_url="http://8.8.8.8:9222", api_key="k").get_toolset()
        assert set(toolset.tools) == {"browse_page"}

    def test_the_toolset_is_built_once_and_reused(self):
        # Rebuilt per call it would be a new closure - and a new browser session
        # factory - on every step of every run.
        built = BrowserChoice(cdp_url="http://8.8.8.8:9222", api_key="k")
        assert built.get_toolset() is built.get_toolset()


def _configured_capability() -> tuple[BrowserChoice, dict[str, Any]]:
    """A capability with every limit set, and the dict its page factory records into."""
    seen: dict[str, Any] = {}

    @asynccontextmanager
    async def capturing(**kwargs: Any) -> AsyncIterator[_FakePage]:
        seen.update(kwargs)
        yield _FakePage(_snapshot(_element(0), _element(1)))

    built: BrowserChoice = BrowserChoice(
        cdp_url="http://8.8.8.8:9222",
        api_key="k",
        allowed_domains=["*.example.com"],
        candidate_cap=12,
        max_steps=3,
        min_confidence=0.4,
        preview=False,
        preview_width=800,
        page_factory=capturing,
        decision_factory=lambda *_: _decision_model("DONE", None, {"operation": 0.9}),
    )
    return built, seen


async def test_the_capability_hands_its_configuration_to_both_engines():
    """The config an author filled in is what the browse actually runs under."""
    built, seen = _configured_capability()
    toolset = built.get_toolset()
    ctx = _tool_context()
    tools = await toolset.get_tools(ctx)
    await toolset.call_tool(
        "browse_page",
        {"goal": "g", "start_url": "https://example.test/page"},
        ctx,
        tools["browse_page"],
    )

    assert seen["cdp_url"] == "http://8.8.8.8:9222"
    assert seen["start_url"] == "https://example.test/page"
    assert seen["policy"] == PagePolicy(
        allowed_domains=["*.example.com"], candidate_cap=12, preview=False, preview_width=800
    )


def test_a_cdp_page_holds_the_policy_it_was_opened_with():
    """The one part of the CDP layer that is not I/O.

    Everything else in `CdpPage` is a protocol command and is pragma'd; this is
    the constructor the opener calls, and a page built without its policy is a
    page with no allowlist.
    """
    policy = PagePolicy(
        allowed_domains=["x.test"], candidate_cap=5, preview=True, preview_width=640
    )
    page = CdpPage(client=object(), session_id="s-1", policy=policy)
    assert page._policy is policy
