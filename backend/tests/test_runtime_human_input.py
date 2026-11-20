"""Native questions use the initiating live socket and preserve vendor reply shapes."""

import pytest
from pydantic import ValidationError

from app.agents.capabilities.external_acp import _human
from app.agents.runtime_questions import (
    RuntimeAnswer,
    RuntimeChoice,
    RuntimeQuestion,
    RuntimeQuestionRequest,
    RuntimeQuestionResponse,
)

pytestmark = pytest.mark.anyio


class Human:
    def __init__(
        self, answers: list[RuntimeAnswer] | None = None, *, cancelled: bool = False
    ) -> None:
        self.answers = answers or []
        self.cancelled = cancelled
        self.seen: list[RuntimeQuestionRequest] = []

    async def __call__(self, request: RuntimeQuestionRequest) -> RuntimeQuestionResponse:
        self.seen.append(request)
        return RuntimeQuestionResponse(answers=self.answers, cancelled=self.cancelled)


async def test_cursor_multiple_choices_are_mapped_to_offered_ids() -> None:
    human = Human([RuntimeAnswer(selected=["First", "Second"])])
    params = {
        "questions": [
            {
                "id": "q",
                "prompt": "Which?",
                "allowMultiple": True,
                "options": [{"id": "one", "label": "First"}, {"id": "two", "label": "Second"}],
            }
        ]
    }
    result = await _human.cursor_questions(params, human)
    assert result == {
        "outcome": {
            "outcome": "answered",
            "answers": [{"questionId": "q", "selectedOptionIds": ["one", "two"]}],
        }
    }
    assert human.seen[0].questions[0].multi_select
    assert not human.seen[0].questions[0].allow_custom
    assert (await _human.cursor_questions(params, None)) == {"outcome": {"outcome": "cancelled"}}
    for answers in [[], [RuntimeAnswer(skipped=True)], [RuntimeAnswer(selected=["Forged"])]]:
        assert (await _human.cursor_questions(params, Human(answers)))["outcome"] == {
            "outcome": "cancelled"
        }


@pytest.mark.parametrize(
    "selected,expected",
    [(["Approve plan"], "accepted"), (["Reject plan"], "rejected"), (["Invented"], "rejected")],
)
@pytest.mark.security
async def test_cursor_plan_requires_the_users_exact_approval_after_showing_the_whole_plan(
    selected: list[str], expected: str
) -> None:
    human = Human([RuntimeAnswer(selected=selected)])
    result = await _human.cursor_plan(
        {
            "plan": "A complete plan\nSecond step",
            "todos": [{"content": "Structured task"}],
            "phases": [{"name": "Phase"}],
        },
        human,
    )
    assert result == {"outcome": {"outcome": expected}}
    shown = human.seen[0].questions[0].question
    assert all(
        part in shown for part in ["complete plan", "Second step", "Structured task", "Phase"]
    )
    assert (await _human.cursor_plan({"plan": "Read the whole plan"}, None)) == {
        "outcome": {"outcome": "cancelled"}
    }
    with pytest.raises(ValueError):
        await _human.cursor_plan({"plan": ""}, human)


@pytest.mark.parametrize(
    "method,answer,expected",
    [
        ("select", RuntimeAnswer(selected=["Choice"]), {"value": "Choice"}),
        ("confirm", RuntimeAnswer(selected=["Yes"]), {"confirmed": True}),
        ("confirm", RuntimeAnswer(selected=["No"]), {"confirmed": False}),
        ("input", RuntimeAnswer(answer="My answer"), {"value": "My answer"}),
        ("editor", RuntimeAnswer(answer="New\ntext"), {"value": "New\ntext"}),
    ],
)
async def test_pi_dialogs_return_only_a_humans_actual_answer(
    method: str, answer: RuntimeAnswer, expected: dict[str, object]
) -> None:
    human = Human([answer])
    params = {
        "method": method,
        "title": "Question",
        "options": ["Choice"],
        "prefill": "Original text",
        "message": "Explanation",
    }
    assert await _human.pi_dialog(params, human) == expected
    shown = human.seen[0].questions[0].question
    assert "Explanation" in shown
    assert human.seen[0].questions[0].initial_value == (
        "Original text" if method == "editor" else None
    )
    assert await _human.pi_dialog(params, None) == {"cancelled": True}


@pytest.mark.parametrize(
    "params",
    [
        {"method": "input", "title": "Secret", "isPassword": True},
        {"method": "input", "title": "Secret", "secret": True},
        {"method": "select", "title": "Q", "options": [1]},
        {"method": "select", "title": "Q", "options": []},
        {"method": "new-method", "title": "Q"},
        {"method": "input"},
    ],
)
@pytest.mark.security
async def test_unsupported_or_secret_dialogs_never_reach_the_question_card(
    params: dict[str, object],
) -> None:
    human = Human()
    with pytest.raises(ValueError):
        await _human.pi_dialog(params, human)
    assert not human.seen


@pytest.mark.parametrize(
    "method,answer",
    [
        ("confirm", RuntimeAnswer(selected=["Forged"])),
        ("select", RuntimeAnswer(selected=["Forged"])),
        ("input", RuntimeAnswer(skipped=True)),
        ("editor", RuntimeAnswer(skipped=True)),
    ],
)
async def test_missing_or_unoffered_pi_answers_are_cancellation(
    method: str, answer: RuntimeAnswer
) -> None:
    assert await _human.pi_dialog(
        {"method": method, "title": "Q", "options": ["Choice"]}, Human([answer])
    ) == {"cancelled": True}


@pytest.mark.security
async def test_kimi_permission_questions_are_answers_not_blanket_tool_permission() -> None:
    params = {
        "toolCall": {
            "title": "AskUserQuestion",
            "content": [{"type": "content", "content": {"type": "text", "text": "Which target?"}}],
        },
        "options": [
            {"optionId": "q0_opt_0", "name": "Target", "kind": "allow_once"},
            {"optionId": "skip", "name": "Skip", "kind": "reject_once"},
        ],
    }
    human = Human([RuntimeAnswer(selected=["Target"])])
    assert await _human.permission_question(params, human) == {
        "outcome": {"outcome": "selected", "optionId": "q0_opt_0"}
    }
    assert human.seen[0].questions[0].question == "Which target?"
    assert await _human.permission_question(params, None) == {"outcome": {"outcome": "cancelled"}}
    for answer in [RuntimeAnswer(skipped=True), RuntimeAnswer(selected=["Forged"])]:
        assert await _human.permission_question(params, Human([answer])) == {
            "outcome": {"outcome": "cancelled"}
        }


async def test_grok_free_text_and_previews_follow_its_annotated_answer_contract() -> None:
    params = {
        "questions": [
            {
                "question": "Which?",
                "options": [{"label": "A", "description": "Meaning", "preview": "Full preview"}],
            }
        ]
    }
    human = Human([RuntimeAnswer(answer="A custom answer")])
    assert await _human.grok_questions(params, human) == {
        "outcome": "accepted",
        "answers": {"Which?": ["Other"]},
        "annotations": {"Which?": {"notes": "A custom answer"}},
    }
    selected = await _human.grok_questions(params, Human([RuntimeAnswer(selected=["A"])]))
    assert selected["annotations"] == {"Which?": {"preview": "Full preview"}}
    assert "Full preview" in human.seen[0].questions[0].question
    assert await _human.grok_questions(params, None) == {"outcome": "cancelled"}
    for answer in [RuntimeAnswer(skipped=True), RuntimeAnswer(selected=["Forged"])]:
        assert await _human.grok_questions(params, Human([answer])) == {"outcome": "cancelled"}
    with pytest.raises(ValueError):
        await _human.grok_questions({"questions": params["questions"] * 2}, human)


@pytest.mark.parametrize(
    "question",
    [
        {"id": "q", "question": "Escape\x1b"},
        {"id": "q", "question": "Q", "options": [{"label": "Case"}, {"label": "CASE"}]},
        {"id": "q", "question": "Q", "options": [{"label": "A"}] * 129},
    ],
)
def test_unbounded_or_ambiguous_question_data_is_refused(question: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RuntimeQuestion.model_validate(question)


def test_duplicate_question_ids_and_oversized_answers_are_refused() -> None:
    question = RuntimeQuestion(id="one", question="Q", options=[RuntimeChoice(label="A")])
    with pytest.raises(ValidationError):
        RuntimeQuestionRequest(runtime_name="Runtime", questions=[question, question])
    with pytest.raises(ValidationError):
        RuntimeAnswer(answer="x" * 32001)


async def test_native_prompt_completion_cancels_an_unanswered_human_card_without_deadlock() -> None:
    import anyio

    from app.agents.capabilities.coding_agent._acp import Conversation, _Collector
    from tests.test_coding_agent_acp import _nothing

    asked = anyio.Event()
    cancelled = anyio.Event()
    writer, reader = anyio.create_memory_object_stream[dict[str, object]](16)

    class Pipe:
        async def send(self, message: dict[str, object]) -> None:
            if message.get("method") == "session/prompt":
                await writer.send(
                    {
                        "jsonrpc": "2.0",
                        "id": "question",
                        "method": "cursor/create_plan",
                        "params": {"plan": "Read the complete plan"},
                    }
                )

        async def receive(self) -> dict[str, object]:
            return await reader.receive()

        async def close(self) -> None:
            await writer.aclose()
            await reader.aclose()

    async def human(_request: RuntimeQuestionRequest) -> RuntimeQuestionResponse:
        asked.set()
        try:
            await anyio.sleep_forever()
        finally:
            cancelled.set()

    pipe = Pipe()
    conversation = Conversation(
        pipe, access="edit", collector=_Collector(), shown=_nothing, runtime_questions=human
    )

    async def native_finish() -> None:
        await asked.wait()
        await writer.send({"jsonrpc": "2.0", "id": 1, "result": {"stopReason": "end_turn"}})

    async with anyio.create_task_group() as group:
        group.start_soon(native_finish)
        with anyio.fail_after(1):
            result = await conversation.request(
                "session/prompt", {"sessionId": "owned", "prompt": []}
            )
        group.cancel_scope.cancel()
    assert result == {"stopReason": "end_turn"} and cancelled.is_set()
    assert not conversation._human_scopes
    await pipe.close()


async def test_runtime_socket_round_is_correlated_and_preserves_editor_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from app.services.chat_timeline import TurnTimeline
    from tests.test_agent_session import _next_frame, _sent_events, _session, _wait

    session = _session()
    session._current_timeline = TurnTimeline()
    monkeypatch.setattr(session, "_reauthorize_write", AsyncMock(return_value=True))
    request = RuntimeQuestionRequest(
        runtime_name="Pi",
        questions=[
            RuntimeQuestion(
                id="editor",
                question="Edit this",
                multiline=True,
                allow_empty=True,
                initial_value="old",
            )
        ],
    )
    visible = _next_frame(session)
    task = asyncio.create_task(session._runtime_questions(request))
    await _wait(visible)
    frame = next(data for kind, data in _sent_events(session) if kind == "ask_user")
    runtime_id = frame["runtime_question_id"]
    await session.handle_frame(
        {
            "type": "ask_user_response",
            "runtime_question_id": "stale",
            "answers": [{"answer": "Wrong", "skipped": False}],
        }
    )
    assert not task.done()
    text = "  indented\n\tcode\n"
    await session.handle_frame(
        {
            "type": "ask_user_response",
            "runtime_question_id": runtime_id,
            "answers": [{"answer": text, "skipped": False}],
        }
    )
    result = await task
    assert not result.cancelled and result.answers[0].answer == text
    stored = session._current_timeline.stored()
    assert stored is not None and stored[-1].answer == text and stored[-1].asked_by == "Pi"
    assert ("runtime_question_closed", {"runtime_question_id": runtime_id}) in _sent_events(session)
    assert session._runtime_question_id is None and session._runtime_request is None


async def test_cancelling_the_native_dialog_closes_the_live_card_and_releases_the_slot() -> None:
    import asyncio

    from tests.test_agent_session import _next_frame, _sent_events, _session, _wait

    session = _session()
    shown = _next_frame(session)
    request = RuntimeQuestionRequest(
        runtime_name="Cursor", questions=[RuntimeQuestion(id="q", question="Q")]
    )
    task = asyncio.create_task(session._runtime_questions(request))
    await _wait(shown)
    runtime_id = next(
        data["runtime_question_id"] for kind, data in _sent_events(session) if kind == "ask_user"
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert session._ask_user_future is None and session._pending_questions is None
    assert session._runtime_question_id is None
    assert not session._ask_lock.locked()
    assert ("runtime_question_closed", {"runtime_question_id": runtime_id}) in _sent_events(session)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        [{}] * 2,
        [{"skipped": "false"}],
        [{"selected": ["forged"], "answer": "forged text"}],
        [{"selected": ["A"]}],
        [{"selected": ["A", "B", "C"]}],
    ],
)
def test_runtime_answer_normalization_refuses_malformed_or_out_of_bounds_choices(
    raw: object,
) -> None:
    from app.agents.runtime_questions import normalize_runtime_answers

    request = RuntimeQuestionRequest(
        runtime_name="Muse",
        questions=[
            RuntimeQuestion(
                id="q",
                question="Choose two",
                options=[RuntimeChoice(label=label) for label in ["A", "B", "C"]],
                multi_select=True,
                min_selections=2,
                max_selections=2,
                allow_custom=False,
            )
        ],
    )
    assert normalize_runtime_answers(request, raw).cancelled


@pytest.mark.parametrize("text", ["", "  keep indentation\n"])
def test_empty_and_multiline_editors_preserve_the_explicit_submission(text: str) -> None:
    from app.agents.runtime_questions import normalize_runtime_answers

    request = RuntimeQuestionRequest(
        runtime_name="Pi",
        questions=[RuntimeQuestion(id="q", question="Edit", allow_empty=True, multiline=True)],
    )
    response = normalize_runtime_answers(request, [{"answer": text, "skipped": False}])
    assert not response.cancelled and response.answers[0].answer == text


@pytest.mark.parametrize("label", [" ", "hidden\x00", "hidden\n"])
def test_native_choices_need_visible_nonempty_labels(label: str) -> None:
    with pytest.raises(ValueError):
        RuntimeChoice(label=label)


@pytest.mark.security
async def test_duplicate_native_choice_ids_and_missing_question_content_are_refused() -> None:
    with pytest.raises(ValueError):
        await _human.cursor_questions(
            {
                "questions": [
                    {
                        "id": "q",
                        "prompt": "Choose",
                        "options": [{"id": "same", "label": "A"}, {"id": "same", "label": "B"}],
                    }
                ]
            },
            None,
        )
    for params in [
        {},
        {"toolCall": {}},
        {
            "toolCall": {"content": [{"content": {"text": "Q"}}]},
            "options": [
                {"kind": "allow_once", "optionId": "same", "name": "A"},
                {"kind": "allow_once", "optionId": "same", "name": "B"},
            ],
        },
    ]:
        with pytest.raises((TypeError, ValueError)):
            await _human.permission_question(params, None)
    params = {
        "toolCall": {"content": [None, {}, {"content": {"text": "Q"}}]},
        "options": [{"kind": "allow_once", "optionId": "one", "name": "A"}],
    }
    assert await _human.permission_question(params, Human([RuntimeAnswer(selected=["A"])])) == {
        "outcome": {"outcome": "selected", "optionId": "one"}
    }


async def test_muse_questions_keep_native_bounds_and_grok_accepts_an_unannotated_option() -> None:
    human = Human([RuntimeAnswer(selected=["A"])])
    result = await _human.muse_questions(
        {
            "questions": [
                {
                    "id": "q",
                    "question": "Choose",
                    "options": [{"label": "A"}],
                    "multi_select": True,
                    "min_selections": 0,
                    "max_selections": 1,
                }
            ]
        },
        human,
    )
    assert result["answers"][0]["selected"] == ["A"]
    assert human.seen[0].runtime_name == "Muse" and human.seen[0].questions[0].min_selections == 0
    assert (
        await _human.grok_questions(
            {"questions": [{"question": "Q", "options": [{"label": "A"}]}]}, human
        )
    )["annotations"] == {}


def test_native_selection_bounds_and_custom_text_limits_are_enforced() -> None:
    from app.agents.runtime_questions import normalize_runtime_answers

    with pytest.raises(ValueError):
        RuntimeQuestion(id="q", question="Choose", min_selections=2, max_selections=1)
    request = RuntimeQuestionRequest(
        runtime_name="Muse",
        questions=[
            RuntimeQuestion(
                id="q", question="Choose", multi_select=True, options=[RuntimeChoice(label="A")]
            )
        ],
    )
    result = normalize_runtime_answers(request, [{"selected": ["A"]}])
    assert not result.cancelled and result.answers[0].selected == ["A"]
    request = RuntimeQuestionRequest(
        runtime_name="Muse",
        questions=[RuntimeQuestion(id="q", question="Write", max_answer_length=2)],
    )
    assert normalize_runtime_answers(request, [{"answer": "too long"}]).cancelled


@pytest.mark.parametrize(
    "method",
    [
        "cursor/ask_question",
        "x.ai/ask_user_question",
        "_agenticos/request_questions",
        "session/request_permission",
    ],
)
async def test_malformed_native_questions_are_cancelled_before_any_answer_is_invented(
    method: str,
) -> None:
    from app.agents.capabilities.coding_agent._acp import AcpError, Conversation, _Collector
    from tests.test_coding_agent_acp import ScriptedAgent, ScriptedPipe, _nothing

    pipe = ScriptedPipe(ScriptedAgent())
    conversation = Conversation(
        pipe, access="edit", collector=_Collector(), shown=_nothing, runtime_questions=Human()
    )
    params: dict[str, object] = {"questions": []}
    if method == "session/request_permission":
        params = {"toolCall": {"title": "AskUserQuestion", "content": []}}
    with pytest.raises(AcpError, match="human-input"):
        await conversation._handle({"id": "question", "method": method, "params": params})
    reply = pipe.agent.seen[-1]["result"]
    assert reply in (
        {"cancelled": True, "answers": []},
        {"outcome": "cancelled"},
        {"outcome": {"outcome": "cancelled"}},
    )


@pytest.mark.parametrize("identifier", [True, "x" * 257, "duplicate"])
async def test_duplex_acp_refuses_invalid_or_reused_pending_dialog_ids(identifier: object) -> None:
    import anyio

    from app.agents.capabilities.coding_agent._acp import AcpError, Conversation, _Collector
    from tests.test_coding_agent_acp import ScriptedAgent, ScriptedPipe, _nothing

    pipe = ScriptedPipe(ScriptedAgent())
    pipe.agent.out = [
        {"id": identifier, "method": "cursor/create_plan", "params": {"plan": "Read"}}
    ]
    conversation = Conversation(
        pipe, access="edit", collector=_Collector(), shown=_nothing, runtime_questions=Human()
    )
    if identifier == "duplicate":
        conversation._human_scopes["duplicate"] = anyio.CancelScope()
    async with anyio.create_task_group() as group:
        with pytest.raises(AcpError, match="human-input"):
            await conversation._receive_result(1, group)
        group.cancel_scope.cancel()
    assert not any("result" in message for message in pipe.agent.seen)


async def test_duplex_acp_cancellation_releases_only_the_identified_dialog() -> None:
    import anyio

    from app.agents.capabilities.coding_agent._acp import Conversation, _Collector
    from tests.test_coding_agent_acp import ScriptedAgent, ScriptedPipe, _nothing

    pipe = ScriptedPipe(ScriptedAgent())
    own, other = anyio.CancelScope(), anyio.CancelScope()
    conversation = Conversation(
        pipe, access="edit", collector=_Collector(), shown=_nothing, runtime_questions=Human()
    )
    conversation._human_scopes = {"own": own, "other": other}
    pipe.agent.out = [
        {"method": "_agenticos/cancel_request", "params": {"id": "missing"}},
        {"method": "_agenticos/cancel_request", "params": {"id": "own"}},
        {"id": 1, "result": {}},
    ]
    async with anyio.create_task_group() as group:
        assert await conversation._receive_result(1, group) == {}
        group.cancel_scope.cancel()
    assert own.cancel_called and not other.cancel_called


async def test_pi_malformed_dialog_sends_cancellation_and_releases_its_pending_slot() -> None:
    from app.agents.capabilities.coding_agent._acp import AcpError
    from app.agents.capabilities.external_acp._pi import _Record, _Session
    from tests.test_pi_rpc import Pi, ignore

    pi = Pi()
    session = _Session(pi, ignore, runtime_questions=Human())
    session.pending_questions.add("q")
    with pytest.raises(AcpError, match="human-input"):
        await session.answer_dialog(
            _Record(type="extension_ui_request", id="q", method="select", options=[])
        )
    assert pi.seen[-1] == {"type": "extension_ui_response", "id": "q", "cancelled": True}
    assert not session.pending_questions


async def test_pi_dialog_timeout_cancels_without_fabricating_a_reply() -> None:
    import anyio

    from app.agents.capabilities.external_acp._pi import _Record, _Session
    from tests.test_pi_rpc import Pi, ignore

    async def pending(_request: RuntimeQuestionRequest) -> RuntimeQuestionResponse:
        await anyio.sleep_forever()

    pi = Pi()
    session = _Session(pi, ignore, runtime_questions=pending)
    await session.answer_dialog(
        _Record(type="extension_ui_request", id="q", method="input", title="Answer", timeout=1)
    )
    assert pi.seen[-1] == {"type": "extension_ui_response", "id": "q", "cancelled": True}


@pytest.mark.parametrize("pending_id", [None, "duplicate"])
async def test_pi_refuses_missing_or_reused_dialog_identity(pending_id: str | None) -> None:
    import anyio

    from app.agents.capabilities.coding_agent._acp import AcpError
    from app.agents.capabilities.external_acp._pi import _Session
    from tests.test_pi_rpc import Pi, ignore

    pi = Pi()
    pi.messages.append({"type": "extension_ui_request", "method": "input", "id": pending_id})
    session = _Session(pi, ignore, runtime_questions=Human())
    session.pending_questions.add("duplicate")
    async with anyio.create_task_group() as group:
        session.question_group = group
        with pytest.raises(AcpError):
            await session.receive()
        group.cancel_scope.cancel()
    assert not pi.seen


@pytest.mark.parametrize("replacement", ["future", "nonce", "completed"])
async def test_runtime_answers_are_discarded_if_the_waiter_changes_during_authorization(
    monkeypatch: pytest.MonkeyPatch, replacement: str
) -> None:
    import asyncio

    from tests.test_agent_session import _session

    session = _session()
    original = asyncio.get_running_loop().create_future()
    session._ask_user_future = original
    session._runtime_question_id = "owned"

    async def authorize() -> bool:
        if replacement == "future":
            session._ask_user_future = asyncio.get_running_loop().create_future()
        elif replacement == "nonce":
            session._runtime_question_id = "successor"
        else:
            original.set_result([])
        return True

    monkeypatch.setattr(session, "_reauthorize_write", authorize)
    await session.handle_frame(
        {
            "type": "ask_user_response",
            "runtime_question_id": "owned",
            "answers": [{"answer": "obsolete"}],
        }
    )
    assert not original.done() or original.result() == []
    if session._ask_user_future is not original:
        assert not session._ask_user_future.done()


async def test_an_empty_native_input_is_recorded_as_an_intentional_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from app.services.chat_timeline import TurnTimeline
    from tests.test_agent_session import _next_frame, _sent_events, _session, _wait

    session = _session()
    session._current_timeline = TurnTimeline()
    monkeypatch.setattr(session, "_reauthorize_write", AsyncMock(return_value=True))
    request = RuntimeQuestionRequest(
        runtime_name="Pi",
        questions=[RuntimeQuestion(id="q", question="Optional input", allow_empty=True)],
    )
    visible = _next_frame(session)
    task = asyncio.create_task(session._runtime_questions(request))
    await _wait(visible)
    frame = next(data for kind, data in _sent_events(session) if kind == "ask_user")
    await session.handle_frame(
        {
            "type": "ask_user_response",
            "runtime_question_id": frame["runtime_question_id"],
            "answers": [{"answer": ""}],
        }
    )
    result = await task
    assert not result.cancelled and result.answers[0].answer == ""
    timeline = session._current_timeline.stored()
    assert timeline is not None and timeline[-1].answer == "(empty text)"


async def test_a_well_formed_native_question_is_answered_on_the_same_request_id() -> None:
    from app.agents.capabilities.coding_agent._acp import Conversation, _Collector
    from tests.test_coding_agent_acp import ScriptedAgent, ScriptedPipe, _nothing

    pipe = ScriptedPipe(ScriptedAgent())
    human = Human([RuntimeAnswer(selected=["A"])])
    conversation = Conversation(
        pipe, access="edit", collector=_Collector(), shown=_nothing, runtime_questions=human
    )
    await conversation._handle(
        {
            "id": "question",
            "method": "_agenticos/request_questions",
            "params": {"questions": [{"id": "q", "question": "Pick", "options": [{"label": "A"}]}]},
        }
    )
    reply = pipe.agent.seen[-1]
    assert reply["id"] == "question" and reply["result"]["answers"][0]["selected"] == ["A"]
    assert human.seen[0].runtime_name == "Muse"


async def test_platform_tool_requests_are_refused_when_the_run_did_not_enable_them() -> None:
    from app.agents.capabilities.coding_agent._acp import AcpError, Conversation, _Collector
    from tests.test_coding_agent_acp import ScriptedAgent, ScriptedPipe, _nothing

    conversation = Conversation(
        ScriptedPipe(ScriptedAgent()), access="edit", collector=_Collector(), shown=_nothing
    )
    with pytest.raises(AcpError, match="not enabled platform tools"):
        await conversation._handle(
            {"id": "tool", "method": "_agenticos/tools/call", "params": {"name": "x"}}
        )


async def test_the_device_pipe_requires_desktops_platform_bridge_acknowledgement() -> None:
    from app.agents.capabilities.coding_agent._acp import AcpError, DevicePipe
    from tests.test_coding_agent_acp import FakeDevice

    old = FakeDevice([], opened={"id": "proc"})
    with pytest.raises(AcpError, match="Update Desktop"):
        await DevicePipe(old, "codex", platform_tools=True).open()
    assert old.calls[0][1]["platform_tools"] is True and old.calls[-1][0] == "agent.close"
    current = FakeDevice([], opened={"id": "proc", "platform_tools_version": 1})
    await DevicePipe(current, "codex", platform_tools=True).open()


async def test_a_duplex_request_surfaces_its_own_failure_and_keeps_several_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from app.agents.capabilities.coding_agent import _acp
    from app.agents.capabilities.coding_agent._acp import AcpError, Conversation, _Collector
    from tests.test_coding_agent_acp import ScriptedAgent, ScriptedPipe, _nothing

    class Broken(ScriptedPipe):
        async def receive(self) -> dict[str, object]:
            raise AcpError("the agent went away")

    conversation = Conversation(
        Broken(ScriptedAgent()),
        access="edit",
        collector=_Collector(),
        shown=_nothing,
        runtime_questions=Human(),
    )
    with pytest.raises(AcpError, match="went away"):
        await conversation.request("session/prompt", {"sessionId": "s", "prompt": []})

    class Group:
        cancel_scope = MagicMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:
            raise BaseExceptionGroup("both", [ValueError("one"), KeyError("two")])

    async def answered(_identifier, _group):
        return {"ok": True}

    monkeypatch.setattr(_acp.anyio, "create_task_group", Group)
    monkeypatch.setattr(conversation, "_receive_result", answered)
    with pytest.raises(BaseExceptionGroup):
        await conversation.request("session/new", {})


async def test_runtime_choices_and_short_text_are_recorded_as_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from app.services.chat_timeline import TurnTimeline
    from tests.test_agent_session import _next_frame, _sent_events, _session, _wait

    session = _session()
    session._current_timeline = TurnTimeline()
    monkeypatch.setattr(session, "_reauthorize_write", AsyncMock(return_value=True))
    request = RuntimeQuestionRequest(
        runtime_name="Muse",
        questions=[
            RuntimeQuestion(id="pick", question="Pick one", options=[RuntimeChoice(label="A")]),
            RuntimeQuestion(id="name", question="Name it"),
        ],
    )
    visible = _next_frame(session)
    task = asyncio.create_task(session._runtime_questions(request))
    await _wait(visible)
    frame = next(data for kind, data in _sent_events(session) if kind == "ask_user")
    await session.handle_frame(
        {
            "type": "ask_user_response",
            "runtime_question_id": frame["runtime_question_id"],
            "answers": [
                {"selected": ["A"], "skipped": False},
                {"answer": "Report", "skipped": False},
            ],
        }
    )
    result = await task
    assert not result.cancelled and result.answers[0].selected == ["A"]
    stored = session._current_timeline.stored()
    assert stored is not None and [entry.asked_by for entry in stored[-2:]] == ["Muse", "Muse"]
