"""Tests for the system-reminders capability.

What is guarded: a reminder fires on the cadence it was configured with and no
more than `max_fires` times; the cadence counter is durable, so it counts across
turns rather than resetting; the reminder reaches the request tail behind a cache
point but never accumulates; an LLM reminder is billed to the run that ran it and
falls back rather than failing the run; and an empty config contributes nothing.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic_ai._run_context import RunContext
from pydantic_ai.messages import (
    CachePoint,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextContent,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models import ModelRequestContext, ModelRequestParameters
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RequestUsage, RunUsage, UsageLimits

from app.agents.capabilities import CapabilityBinding, build, get
from app.agents.capabilities.budget import SpendLedger, metered_by
from app.agents.capabilities.system_reminders import (
    REMINDER_STATE_RESOURCE,
    ReminderState,
    SystemReminders,
    SystemRemindersConfig,
)
from app.agents.capabilities.system_reminders._capability import (
    CompiledReminder,
    _compact_transcript,
    _first_user_text,
    _has_user_content,
    _is_user_content_item,
    _LlmReminder,
    _prompt_text,
    _recent_texts,
    _reserved_limits,
    _should_fire,
    _wrap,
    goal_reanchor_producer,
    llm_reminder_producer,
    static_producer,
)

pytestmark = pytest.mark.anyio


def _user_request(text: str = "do the thing") -> ModelRequest:
    return ModelRequest(parts=[UserPromptPart(content=text)])


def _request_context(messages: list[ModelMessage], *, model: Any = None) -> ModelRequestContext:
    return ModelRequestContext(
        model=model if model is not None else TestModel(),
        messages=messages,
        model_settings=None,
        model_request_parameters=ModelRequestParameters(),
    )


def _response() -> ModelResponse:
    return ModelResponse(parts=[TextPart(content="ok")], usage=RequestUsage())


async def _no_usage_result(output: str) -> SimpleNamespace:
    """A run result that leaves the run's usage untouched."""
    return SimpleNamespace(output=output)


async def _run(
    capability: SystemReminders[Any],
    messages: list[ModelMessage],
    *,
    model: Any = None,
    usage: RunUsage | None = None,
    usage_limits: UsageLimits | None = None,
) -> ModelRequestContext:
    """Drive one `wrap_model_request` and return the (mutated) request context."""
    ctx: RunContext[None] = RunContext(
        deps=None,
        model=model if model is not None else TestModel(),
        usage=usage or RunUsage(),
        messages=messages,
        usage_limits=usage_limits,
    )
    request_context = _request_context(messages, model=model)

    async def handler(_rc: ModelRequestContext) -> ModelResponse:
        return _response()

    await capability.wrap_model_request(ctx, request_context=request_context, handler=handler)
    return request_context


def _tail_reminder(request_context: ModelRequestContext) -> UserPromptPart | None:
    """The reminder appended to the tail request, or `None` if none was.

    A reminder is always injected as a `UserPromptPart` whose content is a *list*
    (a cache point and/or the joined text); an original user prompt in these tests
    carries a plain string, so the two never confuse.
    """
    tail = request_context.messages[-1]
    if not isinstance(tail, ModelRequest):
        return None
    injected = [
        part
        for part in tail.parts
        if isinstance(part, UserPromptPart) and isinstance(part.content, list)
    ]
    return injected[-1] if injected else None


def _reminders(**config: Any) -> SystemReminders[Any]:
    built = build([CapabilityBinding(capability_id="system_reminders", config=config)])
    assert len(built) == 1
    capability = built[0]
    assert isinstance(capability, SystemReminders)
    return capability


class TestReminderState:
    def test_snapshot_round_trips_through_seed(self):
        state = ReminderState(request_count=7, fire_counts={"0": 2, "llm": 1})
        assert ReminderState.seed(state.snapshot()) == state

    def test_a_null_column_seeds_a_fresh_state(self):
        assert ReminderState.seed(None) == ReminderState()

    def test_a_value_that_is_not_a_mapping_is_ignored(self):
        assert ReminderState.seed(["nonsense"]) == ReminderState()  # type: ignore[arg-type]

    def test_a_malformed_count_falls_back_to_zero(self):
        assert ReminderState.seed({"request_count": "five"}).request_count == 0
        assert ReminderState.seed({"request_count": -3}).request_count == 0

    def test_fire_counts_keep_only_integer_values(self):
        seeded = ReminderState.seed({"fire_counts": {"0": 2, "1": "no", "2": 4}})
        assert seeded.fire_counts == {"0": 2, "2": 4}

    def test_fire_counts_that_are_not_a_mapping_are_dropped(self):
        assert ReminderState.seed({"fire_counts": 9}).fire_counts == {}


class TestBuild:
    def test_an_empty_config_contributes_nothing(self):
        """Binding the capability without a reminder attaches nothing to the run."""
        assert build([CapabilityBinding(capability_id="system_reminders", config={})]) == []

    def test_a_missing_config_object_falls_back_to_defaults(self):
        """A build context with no parsed config still yields the empty default."""
        from app.agents.capabilities._registry import CapabilityBuildContext

        definition = get("system_reminders")
        result = definition.builder(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="system_reminders"),
                config=None,
            )
        )
        assert result is None

    def test_the_seeded_state_is_the_one_the_capability_mutates(self):
        state = ReminderState(request_count=3)
        from app.agents.capabilities._registry import CapabilityBuildContext

        definition = get("system_reminders")
        capability = definition.builder(
            CapabilityBuildContext(
                binding=CapabilityBinding(capability_id="system_reminders"),
                config=SystemRemindersConfig(goal_reanchor={}),  # type: ignore[arg-type]
                resources={REMINDER_STATE_RESOURCE: state},
            )
        )
        assert isinstance(capability, SystemReminders)
        assert capability.state is state

    def test_a_build_without_the_resource_gets_a_fresh_state(self):
        capability = _reminders(reminders=[{"content": "stay focused"}])
        assert capability.state == ReminderState()

    def test_an_empty_tag_emits_the_raw_line(self):
        capability = _reminders(reminders=[{"content": "raw", "tag": ""}])
        assert capability.reminders[0].tag is None


class TestCadence:
    async def test_a_reminder_fires_on_every_request_by_default(self):
        capability = _reminders(reminders=[{"content": "focus"}])
        request_context = await _run(capability, [_user_request()])
        reminder = _tail_reminder(request_context)
        assert reminder is not None
        assert capability.state.request_count == 1

    async def test_an_interval_skips_the_requests_between_fires(self):
        capability = _reminders(reminders=[{"content": "focus", "interval": 3}])
        fired = [_tail_reminder(await _run(capability, [_user_request()])) for _ in range(6)]
        assert [f is not None for f in fired] == [False, False, True, False, False, True]

    async def test_first_after_moves_the_first_fire_then_holds_the_interval(self):
        capability = _reminders(reminders=[{"content": "focus", "interval": 2, "first_after": 3}])
        fired = [_tail_reminder(await _run(capability, [_user_request()])) for _ in range(6)]
        assert [f is not None for f in fired] == [False, False, True, False, True, False]

    async def test_max_fires_caps_the_total_over_the_conversation(self):
        capability = _reminders(reminders=[{"content": "focus", "max_fires": 2}])
        fired = [_tail_reminder(await _run(capability, [_user_request()])) for _ in range(4)]
        assert [f is not None for f in fired] == [True, True, False, False]
        assert capability.state.fire_counts == {"0": 2}

    async def test_the_cadence_resumes_from_the_seeded_state(self):
        """A reminder every 3 requests fires next turn where the last left off."""
        seeded = ReminderState(request_count=2)
        capability = SystemReminders(
            reminders=[
                CompiledReminder(
                    key="0",
                    interval=3,
                    first_after=None,
                    max_fires=None,
                    tag="system-reminder",
                    produce=static_producer("focus"),
                )
            ],
            state=seeded,
        )
        # Seeded at 2, so the very first request of this turn is the 3rd overall.
        request_context = await _run(capability, [_user_request()])
        assert _tail_reminder(request_context) is not None
        assert capability.state.request_count == 3


class TestInjection:
    async def test_a_provider_resume_tail_is_left_untouched(self):
        """A suspended `ModelResponse` tail is echoed verbatim, so nothing is added."""
        capability = _reminders(reminders=[{"content": "focus"}])
        paused = ModelResponse(parts=[TextPart(content="paused")])
        request_context = await _run(capability, [paused])
        assert request_context.messages[-1] is paused
        assert capability.state.request_count == 0

    async def test_the_reminder_leads_with_a_cache_point_when_it_can(self):
        capability = _reminders(reminders=[{"content": "focus"}])
        request_context = await _run(capability, [_user_request()])
        reminder = _tail_reminder(request_context)
        assert reminder is not None
        assert isinstance(reminder.content, list)
        assert isinstance(reminder.content[0], CachePoint)
        assert reminder.content[1] == "<system-reminder>\nfocus\n</system-reminder>"

    async def test_no_cache_point_without_a_user_block_to_attach_to(self):
        """A request that carries no user content cannot lead with a cache point."""
        capability = _reminders(reminders=[{"content": "focus"}])
        messages: list[ModelMessage] = [ModelRequest(parts=[SystemPromptPart(content="be nice")])]
        request_context = await _run(capability, messages)
        reminder = _tail_reminder(request_context)
        assert reminder is not None
        assert reminder.content == ["<system-reminder>\nfocus\n</system-reminder>"]

    async def test_several_reminders_are_joined_into_one_block(self):
        capability = _reminders(reminders=[{"content": "first"}, {"content": "second", "tag": ""}])
        request_context = await _run(capability, [_user_request()])
        reminder = _tail_reminder(request_context)
        assert reminder is not None
        assert reminder.content[1] == "<system-reminder>\nfirst\n</system-reminder>\n\nsecond"

    async def test_a_reminder_does_not_accumulate_across_requests(self):
        """Each request is rebuilt, so a fired reminder never piles up in history."""
        capability = _reminders(reminders=[{"content": "focus"}])
        first = await _run(capability, [_user_request()])
        second = await _run(capability, [_user_request()])
        assert len(first.messages[-1].parts) == 2
        assert len(second.messages[-1].parts) == 2


class TestGoalReanchor:
    async def test_it_restates_the_first_user_request(self):
        capability = _reminders(goal_reanchor={})
        request_context = await _run(capability, [_user_request("book me a flight")])
        reminder = _tail_reminder(request_context)
        assert reminder is not None
        assert "book me a flight" in reminder.content[1]

    async def test_it_falls_back_when_there_is_no_user_message_yet(self):
        capability = _reminders(goal_reanchor={"fallback": "keep going"})
        messages: list[ModelMessage] = [
            ModelRequest(parts=[ToolReturnPart(tool_name="t", content="r", tool_call_id="c")])
        ]
        request_context = await _run(capability, messages)
        reminder = _tail_reminder(request_context)
        assert reminder is not None
        assert "keep going" in reminder.content[1]


class TestLlmReminder:
    async def test_it_writes_a_reminder_and_bills_the_run(self):
        capability = _reminders(llm_reminder={"interval": 1})
        ledger = SpendLedger()
        with metered_by(ledger):
            request_context = await _run(
                capability,
                [_user_request("write the report")],
                model=TestModel(custom_output_text="refocus on the report"),
                usage_limits=UsageLimits(request_limit=5),
            )
        reminder = _tail_reminder(request_context)
        assert reminder is not None
        assert reminder.content[1] == "<system-reminder>\nrefocus on the report\n</system-reminder>"
        assert len(ledger.entries) == 1
        assert ledger.input_tokens > 0

    async def test_a_non_request_response_model_falls_back_to_the_reanchor(self):
        capability = _reminders(llm_reminder={"interval": 1, "fallback": "stay on task"})
        request_context = await _run(capability, [_user_request("the goal")], model=object())
        reminder = _tail_reminder(request_context)
        assert reminder is not None
        assert "the goal" in reminder.content[1]

    async def test_an_empty_generation_injects_nothing(self):
        capability = _reminders(llm_reminder={"interval": 1})
        request_context = await _run(
            capability,
            [_user_request()],
            model=TestModel(custom_output_text="   "),
        )
        assert _tail_reminder(request_context) is None
        assert capability.state.fire_counts == {}

    async def test_the_generation_agent_is_built_once_and_reused(self):
        reminder = _LlmReminder(instructions="x", max_context_messages=5, fallback="f")
        ctx: RunContext[None] = RunContext(
            deps=None,
            model=TestModel(custom_output_text="a"),
            usage=RunUsage(),
            messages=[_user_request()],
        )
        await reminder(ctx)
        first = reminder._agent
        await reminder(ctx)
        assert reminder._agent is first is not None

    async def test_a_generation_that_spends_nothing_books_nothing(self):
        """A call that leaves usage untouched books no cost - the defensive path."""
        reminder = _LlmReminder(instructions="x", max_context_messages=5, fallback="f")
        reminder._agent = SimpleNamespace(  # type: ignore[assignment]
            run=lambda *a, **k: _no_usage_result("focus")
        )
        ctx: RunContext[None] = RunContext(
            deps=None, model=TestModel(), usage=RunUsage(), messages=[_user_request()]
        )
        ledger = SpendLedger()
        with metered_by(ledger):
            assert await reminder(ctx) == "focus"
        assert ledger.entries == []


class TestReservedLimits:
    def test_none_limits_stay_none(self):
        assert _reserved_limits(None) is None

    def test_an_unset_request_limit_is_left_alone(self):
        limits = UsageLimits(request_limit=None)
        assert _reserved_limits(limits) is limits

    def test_one_request_is_held_back(self):
        assert _reserved_limits(UsageLimits(request_limit=4)).request_limit == 3

    def test_it_never_goes_below_zero(self):
        assert _reserved_limits(UsageLimits(request_limit=0)).request_limit == 0


class TestShouldFire:
    @pytest.mark.parametrize(
        ("interval", "first_after", "count", "expected"),
        [
            (1, None, 1, True),
            (3, None, 2, False),
            (3, None, 3, True),
            (3, None, 6, True),
            (2, 3, 3, True),
            (2, 3, 4, False),
            (2, 3, 5, True),
            (2, 3, 2, False),
        ],
    )
    def test_cadence(self, interval: int, first_after: int | None, count: int, expected: bool):
        reminder = CompiledReminder(
            key="k",
            interval=interval,
            first_after=first_after,
            max_fires=None,
            tag=None,
            produce=static_producer("x"),
        )
        assert _should_fire(reminder, count) is expected


class TestWrap:
    def test_a_tag_wraps_the_text(self):
        assert _wrap("hi", "system-reminder") == "<system-reminder>\nhi\n</system-reminder>"

    def test_no_tag_returns_the_raw_text(self):
        assert _wrap("hi", None) == "hi"


class TestHasUserContent:
    def test_a_tool_return_counts(self):
        assert _has_user_content([ToolReturnPart(tool_name="t", content="r", tool_call_id="c")])

    def test_a_retry_prompt_counts(self):
        assert _has_user_content([RetryPromptPart(content="try again")])

    def test_a_non_empty_string_prompt_counts(self):
        assert _has_user_content([UserPromptPart(content="hello")])

    def test_an_empty_string_prompt_does_not(self):
        assert not _has_user_content([UserPromptPart(content="")])

    def test_a_list_with_real_content_counts(self):
        assert _has_user_content([UserPromptPart(content=["hello"])])

    def test_a_list_of_only_a_cache_point_does_not(self):
        assert not _has_user_content([UserPromptPart(content=[CachePoint()])])

    def test_a_system_prompt_does_not_count(self):
        assert not _has_user_content([SystemPromptPart(content="be nice")])


class TestIsUserContentItem:
    def test_a_cache_point_is_not_content(self):
        assert not _is_user_content_item(CachePoint())

    def test_an_empty_string_is_not_content(self):
        assert not _is_user_content_item("")

    def test_a_non_empty_string_is_content(self):
        assert _is_user_content_item("x")

    def test_empty_text_content_is_not_content(self):
        assert not _is_user_content_item(TextContent(content=""))

    def test_non_empty_text_content_is_content(self):
        assert _is_user_content_item(TextContent(content="hi"))

    def test_anything_else_is_content(self):
        assert _is_user_content_item(object())


class TestTranscriptHelpers:
    def test_prompt_text_reads_a_list_of_strings_and_text_content(self):
        assert _prompt_text(["a", TextContent(content="b"), object()]) == "a b"

    def test_first_user_text_skips_a_response(self):
        messages: list[ModelMessage] = [
            ModelResponse(parts=[TextPart(content="hi")]),
            _user_request("the goal"),
        ]
        assert _first_user_text(messages) == "the goal"

    def test_first_user_text_skips_non_user_parts_and_empty_prompts(self):
        messages: list[ModelMessage] = [
            ModelRequest(parts=[ToolReturnPart(tool_name="t", content="r", tool_call_id="c")]),
            ModelRequest(
                parts=[
                    SystemPromptPart(content="be nice"),
                    UserPromptPart(content=""),
                    UserPromptPart(content="the real goal"),
                ]
            ),
        ]
        assert _first_user_text(messages) == "the real goal"

    def test_first_user_text_is_none_without_a_user_message(self):
        assert _first_user_text([ModelResponse(parts=[TextPart(content="hi")])]) is None

    def test_a_compact_transcript_has_the_goal_and_recent_turns(self):
        messages: list[ModelMessage] = [
            _user_request("the goal"),
            ModelResponse(parts=[TextPart(content="working")]),
        ]
        transcript = _compact_transcript(messages, 10)
        assert "Original goal: the goal" in transcript
        assert "assistant: working" in transcript

    def test_an_empty_transcript_says_so(self):
        assert _compact_transcript([], 10) == "No activity yet."

    def test_recent_texts_keeps_only_the_last_few(self):
        messages: list[ModelMessage] = [_user_request(f"m{i}") for i in range(5)]
        assert _recent_texts(messages, 2) == ["user: m3", "user: m4"]

    def test_recent_texts_names_users_and_assistants_and_skips_the_rest(self):
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[
                    UserPromptPart(content=""),
                    UserPromptPart(content="ask"),
                    ToolReturnPart(tool_name="t", content="r", tool_call_id="c"),
                ]
            ),
            ModelResponse(parts=[TextPart(content="answer"), TextPart(content="")]),
        ]
        assert _recent_texts(messages, 10) == ["user: ask", "assistant: answer"]


class TestProducers:
    async def test_static_producer_ignores_the_context(self):
        ctx: RunContext[None] = RunContext(deps=None, model=TestModel(), usage=RunUsage())
        assert await static_producer("fixed")(ctx) == "fixed"

    async def test_goal_reanchor_producer_uses_the_goal(self):
        ctx: RunContext[None] = RunContext(
            deps=None, model=TestModel(), usage=RunUsage(), messages=[_user_request("ship it")]
        )
        text = await goal_reanchor_producer("fallback")(ctx)
        assert text is not None and "ship it" in text

    async def test_llm_reminder_producer_returns_a_callable(self):
        producer = llm_reminder_producer(instructions="x", max_context_messages=3, fallback="f")
        assert isinstance(producer, _LlmReminder)
