"""The harness capability's newer CLIs: OpenCode, Gemini CLI and Pi.

The same session shape as Claude Code and Codex, on each CLI's own
non-interactive mode. No CLI runs here: the streams are recorded from the
docs each CLI publishes (`opencode run --format json`, `gemini -p
--output-format stream-json`, `pi --mode json`), and the fake sandbox from
`test_harness_capability` plays them back, so the command line, the polling,
the parsing, the booking and the session run as they would.
"""

import json
from typing import Any, get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pydantic_ai.exceptions import UserError

from app.agents.capabilities.coding_agent._harness import (
    Harness,
    Said,
    StepEnded,
    StepStarted,
    gemini_report,
    invocation,
    live_items,
    opencode_report,
    pi_report,
)
from app.agents.capabilities.harness import HarnessConfig
from app.agents.capabilities.harness._report import HarnessReport
from app.agents.capabilities.harness._sessions import (
    forget_session,
    list_sessions,
    remember_session,
    session_path,
)
from app.agents.subagent_events import SubagentStarted
from tests.test_harness_capability import _call, _ctx, _lines, _Shell
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio


def test_the_subagent_frame_names_the_same_five_harnesses() -> None:
    """`SubagentStarted.harness` spells the literal out - see its comment."""
    field = SubagentStarted.model_fields["harness"].annotation
    literals = [arg for arg in get_args(field) if get_args(arg)]
    assert {value for literal in literals for value in get_args(literal)} == set(get_args(Harness))


def _opencode_stream() -> list[dict[str, Any]]:
    """An OpenCode 2 session as `run --format json` prints it."""
    return [
        {"type": "step_start", "sessionID": "ses_abc", "part": {}},
        {
            "type": "tool_use",
            "sessionID": "ses_abc",
            "part": {
                "tool": "read",
                "state": {"status": "completed", "input": {"filePath": "app.py"}},
            },
        },
        {
            "type": "step_finish",
            "sessionID": "ses_abc",
            "part": {
                "reason": "tool-calls",
                "cost": 0.00015025,
                "tokens": {
                    "input": 4,
                    "output": 120,
                    "reasoning": 0,
                    "cache": {"read": 10, "write": 2},
                },
            },
        },
        {
            "type": "tool_use",
            "sessionID": "ses_abc",
            "part": {
                "tool": "edit",
                "state": {"status": "completed", "input": {"filePath": "app.py"}},
            },
        },
        {"type": "text", "sessionID": "ses_abc", "part": {"text": "It adds."}},
    ]


def _gemini_stream() -> list[dict[str, Any]]:
    """A Gemini CLI session as `--output-format stream-json` prints it."""
    return [
        {"type": "init", "session_id": "s-9", "model": "gemini-2.5-flash"},
        {
            "type": "message",
            "message": {"role": "assistant", "content": "Looking."},
        },
        {
            "type": "tool_use",
            "tool": "read_file",
            "args": {"path": "app.py"},
        },
        {"type": "tool_result", "toolCallId": "c1", "is_error": False},
        {
            "type": "message",
            "message": {"role": "assistant", "content": "Done."},
        },
        {
            "type": "result",
            "stats": {"input_tokens": 10, "output_tokens": 5},
        },
    ]


def _pi_stream() -> list[dict[str, Any]]:
    """A Pi session as `--mode json` prints it."""
    return [
        {"type": "session", "id": "u-1", "version": 3, "cwd": "/work"},
        {
            "type": "tool_execution_start",
            "toolCallId": "c1",
            "toolName": "read",
            "args": {"path": "app.py"},
        },
        {
            "type": "tool_execution_end",
            "toolCallId": "c1",
            "toolName": "read",
            "isError": False,
        },
        {
            "type": "message_end",
            "message": {"role": "assistant", "content": "It adds."},
        },
        {"type": "agent_settled", "aborted": False},
    ]


class TestInvocation:
    def test_opencode_runs_standalone_with_its_model_as_vendor_slash_model(self) -> None:
        command = invocation(
            "opencode",
            "edit",
            "Fix it",
            session_id=None,
            base_url=None,
            api_key="sk-x",
            model="claude-sonnet-5-5",
            model_vendor="anthropic",
        )
        assert command.argv == [
            "opencode",
            "--standalone",
            "run",
            "--format",
            "json",
            "--dangerously-skip-permissions",
            "-m",
            "anthropic/claude-sonnet-5-5",
            "Fix it",
        ]
        assert command.env["ANTHROPIC_API_KEY"] == "sk-x"

    @pytest.mark.security
    def test_opencode_read_only_uses_the_plan_agent_not_a_permission_flag(self) -> None:
        command = invocation(
            "opencode",
            "read_only",
            "Explain",
            session_id=None,
            base_url=None,
            api_key="sk-x",
            model="claude-sonnet-5-5",
            model_vendor="anthropic",
        )
        assert "--agent" in command.argv and "plan" in command.argv
        assert "--dangerously-skip-permissions" not in command.argv
        assert command.argv[-1].startswith("You are running read-only:")

    def test_opencode_resumes_with_dash_s(self) -> None:
        command = invocation(
            "opencode",
            "edit",
            "Fix it",
            api_key="sk-x",
            model="claude-sonnet-5-5",
            session_id="ses_abc",
            base_url=None,
            model_vendor="anthropic",
        )
        assert "-s" in command.argv and "ses_abc" in command.argv

    def test_gemini_streams_json_and_resumes_with_dash_r(self) -> None:
        command = invocation(
            "gemini",
            "read_only",
            "Explain",
            api_key="AIza-x",
            model="gemini-2.5-flash",
            session_id="abc-1",
            base_url=None,
        )
        assert command.argv[:-1] == [
            "gemini",
            "--output-format",
            "stream-json",
            "--skip-trust",
            "--approval-mode",
            "plan",
            "-m",
            "gemini-2.5-flash",
            "-r",
            "abc-1",
            "-p",
        ]
        assert command.argv[-1].startswith("You are running read-only:")
        assert command.argv[-1].endswith("Explain")
        assert command.env["GEMINI_API_KEY"] == "AIza-x"

    def test_gemini_edit_uses_yolo_and_no_model_takes_the_cli_default(self) -> None:
        command = invocation(
            "gemini", "edit", "Fix it", api_key="AIza-x", model=None, session_id=None, base_url=None
        )
        assert "--approval-mode" in command.argv and "yolo" in command.argv
        assert "-m" not in command.argv

    def test_pi_prints_json_with_its_model_as_vendor_slash_model(self) -> None:
        command = invocation(
            "pi",
            "edit",
            "Fix it",
            session_id=None,
            base_url=None,
            api_key="sk-x",
            model="gpt-5.6-sol",
            model_vendor="openai",
        )
        assert command.argv == [
            "pi",
            "--mode",
            "json",
            "-m",
            "openai/gpt-5.6-sol",
            "Fix it",
        ]
        assert command.env["OPENAI_API_KEY"] == "sk-x"

    def test_pi_read_only_cuts_the_tool_list_to_the_read_only_helpers(self) -> None:
        command = invocation(
            "pi",
            "read_only",
            "Explain",
            session_id=None,
            base_url=None,
            api_key="AIza-x",
            model="gemini-2.5-flash",
            model_vendor="google",
        )
        assert "--tools" in command.argv
        assert command.argv[command.argv.index("--tools") + 1] == "read,grep,find,ls"

    def test_pi_resumes_with_dash_dash_session(self) -> None:
        command = invocation(
            "pi",
            "edit",
            "Fix it",
            api_key="sk-x",
            model="gpt-5.6-sol",
            session_id="u-1",
            base_url=None,
            model_vendor="openai",
        )
        assert "--session" in command.argv and "u-1" in command.argv

    def test_a_harness_with_no_key_is_refused_before_it_runs(self) -> None:
        with pytest.raises(UserError, match="needs a Gemini API key"):
            invocation(
                "gemini", "edit", "Fix it", api_key=None, model=None, session_id=None, base_url=None
            )
        with pytest.raises(UserError, match="needs an API key"):
            invocation(
                "opencode",
                "edit",
                "Fix it",
                session_id=None,
                base_url=None,
                api_key=None,
                model="claude-sonnet-5-5",
                model_vendor="anthropic",
            )

    def test_an_unknown_harness_is_refused_rather_than_run_as_codex(self) -> None:
        with pytest.raises(UserError, match="Unknown harness"):
            invocation(
                "aider",
                "edit",
                "Fix it",
                api_key="sk-x",
                model=None,
                session_id=None,
                base_url=None,
            )  # type: ignore[arg-type]


class TestReports:
    def test_opencode_completes_when_it_said_something(self) -> None:
        report, usage = opencode_report(
            _opencode_stream(), access="edit", model="claude-sonnet-5-5"
        )
        assert report.harness == "opencode"
        assert report.outcome == "completed"
        assert report.answer == "It adds."
        assert report.session_id == "ses_abc"
        assert report.files_changed == ["app.py"]
        assert [step.kind for step in report.steps] == ["read", "edit"]
        spent = usage.by_model["claude-sonnet-5-5"]
        # The docs count cached tokens apart from fresh input.
        assert spent.input_tokens == 16
        assert spent.cache_read_tokens == 10
        assert spent.cache_write_tokens == 2
        assert spent.output_tokens == 120

    def test_opencode_read_only_reports_no_files_changed(self) -> None:
        report, _ = opencode_report(
            _opencode_stream(), access="read_only", model="claude-sonnet-5-5"
        )
        assert report.outcome == "completed"
        assert report.files_changed == []

    def test_opencode_with_no_text_is_a_session_that_stopped(self) -> None:
        report, _ = opencode_report(
            _opencode_stream()[:3], access="edit", model="claude-sonnet-5-5"
        )
        assert report.outcome == "failed"
        assert "stopped before it finished" in report.answer

    def test_gemini_completes_on_its_result_event(self) -> None:
        report, usage = gemini_report(
            _gemini_stream(), access="read_only", model="gemini-2.5-flash"
        )
        assert report.harness == "gemini"
        assert report.outcome == "completed"
        assert report.answer == "Looking.\n\nDone."
        assert report.session_id == "s-9"
        spent = usage.by_model["gemini-2.5-flash"]
        assert spent.input_tokens == 10
        assert spent.output_tokens == 5

    def test_gemini_with_no_result_event_fails_with_its_last_error(self) -> None:
        events = [
            *_gemini_stream()[:-1],
            {"type": "error", "message": "Quota exceeded."},
        ]
        report, _ = gemini_report(events, access="read_only", model="gemini-2.5-flash")
        assert report.outcome == "failed"
        assert "Quota exceeded." in report.answer

    def test_pi_completes_when_it_settles_without_aborting(self) -> None:
        report, _ = pi_report(_pi_stream(), access="edit", model="claude-sonnet-5-5")
        assert report.harness == "pi"
        assert report.outcome == "completed"
        assert report.answer == "It adds."
        assert report.session_id == "u-1"
        assert [step.kind for step in report.steps] == ["read"]

    def test_pi_that_aborts_is_a_session_that_stopped(self) -> None:
        events = [dict(event) for event in _pi_stream()]
        events[-1] = {"type": "agent_settled", "aborted": True}
        report, _ = pi_report(events, access="edit", model="claude-sonnet-5-5")
        assert report.outcome == "failed"
        assert "stopped before it finished" in report.answer


class TestLiveItems:
    def test_opencode_and_gemini_close_a_tool_call_on_its_use_event(self) -> None:
        opencode = live_items(
            "opencode",
            {
                "type": "tool_use",
                "part": {
                    "tool": "read",
                    "state": {"status": "running", "input": {"filePath": "app.py"}},
                },
            },
        )
        assert [type(item) for item in opencode] == [StepStarted, StepEnded]
        assert isinstance(opencode[0], StepStarted)
        assert opencode[0].step.kind == "read"
        assert opencode[0].step.title == "app.py"

        gemini = live_items(
            "gemini",
            {"type": "tool_use", "tool": "read_file", "args": {"path": "app.py"}},
        )
        assert [type(item) for item in gemini] == [StepStarted, StepEnded]

    def test_gemini_shows_what_it_says_but_not_what_it_was_told(self) -> None:
        said = live_items(
            "gemini",
            {"type": "message", "message": {"role": "assistant", "content": "Done."}},
        )
        assert said == [Said("Done.")]
        assert (
            live_items(
                "gemini",
                {"type": "message", "message": {"role": "user", "content": "Do it."}},
            )
            == []
        )

    def test_pi_opens_and_closes_a_tool_call_by_its_id(self) -> None:
        opened = live_items(
            "pi",
            {
                "type": "tool_execution_start",
                "toolCallId": "c1",
                "toolName": "read",
                "args": {"path": "app.py"},
            },
        )
        assert len(opened) == 1 and isinstance(opened[0], StepStarted)
        assert opened[0].key == "c1"
        closed = live_items(
            "pi",
            {"type": "tool_execution_end", "toolCallId": "c1", "isError": False},
        )
        assert len(closed) == 1 and isinstance(closed[0], StepEnded)
        assert closed[0].key == "c1" and closed[0].failed is False

    def test_pi_shows_only_the_final_message_not_its_deltas(self) -> None:
        assert (
            live_items(
                "pi",
                {"type": "message_update", "usage": {"input": 100, "output": 1}},
            )
            == []
        )
        assert live_items(
            "pi",
            {
                "type": "message_end",
                "message": {"role": "assistant", "content": "It adds."},
            },
        ) == [Said("It adds.")]


class TestConfig:
    def test_the_new_harnesses_may_read_only(self) -> None:
        for harness, model in (
            ("opencode", "anthropic:claude-sonnet-5-5"),
            ("gemini", "google:gemini-2.5-flash"),
            ("pi", "openai:gpt-5.6-sol"),
        ):
            assert (
                HarnessConfig(harness=harness, access="read_only", model=model).access
                == "read_only"
            )

    def test_a_model_of_another_vendor_is_refused_for_the_new_harnesses(self) -> None:
        with pytest.raises(ValidationError, match="Gemini CLI runs Gemini models"):
            HarnessConfig(harness="gemini", model="anthropic:claude-sonnet-5-5")

    def test_opencode_and_pi_must_pick_a_model(self) -> None:
        with pytest.raises(ValidationError, match="pick one"):
            HarnessConfig(harness="opencode")
        with pytest.raises(ValidationError, match="pick one"):
            HarnessConfig(harness="pi")

    def test_gemini_may_take_the_cli_default(self) -> None:
        assert HarnessConfig(harness="gemini").model is None

    def test_the_model_vendor_is_the_key_the_cli_runs_on(self) -> None:
        assert (
            HarnessConfig(harness="opencode", model="google:gemini-2.5-flash").model_vendor
            == "google"
        )
        assert HarnessConfig(harness="gemini").model_vendor is None


class TestSessions:
    def test_session_files_are_named_for_the_new_harnesses(self) -> None:
        conversation = uuid4()
        assert session_path("opencode", conversation) == (
            f".agenticos/harness/opencode-{conversation}.session"
        )
        assert session_path("gemini", conversation, "api") == (
            f".agenticos/harness/gemini-{conversation}-api.session"
        )
        assert session_path("pi", conversation) == f".agenticos/harness/pi-{conversation}.session"

    async def test_listing_and_forgetting_cover_the_new_harnesses(self) -> None:
        workspace = document_workspace()
        conversation = uuid4()
        ctx = _ctx(workspace)
        ctx.deps.conversation_id = conversation
        await remember_session(ctx, "opencode", "ses_abc")
        await remember_session(ctx, "gemini", "s-9", "api")
        await remember_session(ctx, "pi", "u-1", "docs")

        found = await list_sessions(ctx)
        assert {(session.name, session.harness) for session in found} == {
            ("main", "opencode"),
            ("api", "gemini"),
            ("docs", "pi"),
        }
        assert await forget_session(ctx, "docs") == "pi"
        assert await forget_session(ctx) == "opencode"


class TestASession:
    async def test_start_opens_an_opencode_session_and_a_follow_up_resumes_it(self) -> None:
        shell = _Shell(events=_lines(_opencode_stream()))
        raw = await _call(
            shell,
            "harness_start",
            harness="opencode",
            model="claude-sonnet-5-5",
            model_vendor="anthropic",
        )
        report = HarnessReport.model_validate_json(raw)
        assert report.kind == "harness"
        assert report.outcome == "completed"
        assert report.answer == "It adds."
        assert report.session_id == "ses_abc"
        assert report.files_changed == ["app.py"]
        assert json.loads(raw)["session"] == "main"

        raw = await _call(
            shell,
            "harness_prompt",
            prompt="And the tests?",
            harness="opencode",
            model="claude-sonnet-5-5",
            model_vendor="anthropic",
        )
        assert HarnessReport.model_validate_json(raw).outcome == "completed"
        assert "-s ses_abc" in shell.started[1]

    async def test_start_opens_a_gemini_session(self) -> None:
        shell = _Shell(events=_lines(_gemini_stream()))
        raw = await _call(shell, "harness_start", harness="gemini", model="gemini-2.5-flash")
        report = HarnessReport.model_validate_json(raw)
        assert report.outcome == "completed"
        assert report.session_id == "s-9"
        assert report.answer == "Looking.\n\nDone."

    async def test_start_opens_a_pi_session(self) -> None:
        shell = _Shell(events=_lines(_pi_stream()))
        raw = await _call(
            shell,
            "harness_start",
            harness="pi",
            model="claude-sonnet-5-5",
            model_vendor="anthropic",
        )
        report = HarnessReport.model_validate_json(raw)
        assert report.outcome == "completed"
        assert report.session_id == "u-1"


class TestProtocolBoundaries:
    @pytest.mark.parametrize("harness", ["opencode", "pi"])
    def test_a_direct_default_model_invocation_does_not_invent_a_model_selector(
        self,
        harness,
    ) -> None:
        command = invocation(
            harness,
            "edit",
            "Explain",
            api_key="test-only",
            model=None,
            model_vendor=None,
            session_id=None,
            base_url=None,
        )
        assert "-m" not in command.argv
        assert command.env == {
            "ANTHROPIC_API_KEY": "test-only",
            "OPENAI_API_KEY": "test-only",
            "GEMINI_API_KEY": "test-only",
            "GOOGLE_GENERATIVE_AI_API_KEY": "test-only",
        }

    @pytest.mark.parametrize("access", ["edit", "read_only"])
    @pytest.mark.parametrize(
        "error,answer",
        [
            ({"message": "Quota reached"}, "Quota reached"),
            ({"text": "Key refused"}, "Key refused"),
            ({}, "OpenCode stopped with an error."),
        ],
    )
    def test_opencode_errors_win_over_partial_text_and_repeated_tool_frames(
        self,
        access,
        error,
        answer,
    ) -> None:
        edit = {
            "type": "tool_use",
            "part": {
                "id": "edit-1",
                "tool": "edit",
                "state": {"input": {"filePath": "app.py"}},
            },
        }
        report, usage = opencode_report(
            [
                edit,
                edit,
                {"type": "text", "part": {"text": ""}},
                {"type": "step_finish", "part": {"tokens": {}}},
                {"type": "text", "part": {"text": "Still working"}},
                {"type": "error", "part": error},
            ],
            access=access,
            model=None,
        )
        assert report.outcome == "failed"
        assert report.answer == answer
        assert len(report.steps) == 1
        assert report.files_changed == (["app.py"] if access == "edit" else [])
        assert usage.by_model == {}

    @pytest.mark.parametrize(
        "event,answer",
        [
            ({"role": "assistant", "message": "One"}, "One"),
            (
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"text": "One"},
                            {},
                            17,
                            {"text": "Two"},
                        ],
                    }
                },
                "One\n\nTwo",
            ),
            ({"message": {"role": "assistant", "text": "One"}}, "One"),
            ({"role": "assistant", "text": "One"}, "One"),
            ({"role": "assistant", "delta": "One"}, "One"),
            ({"message": ""}, None),
            ({"message": {"content": ""}}, None),
            ({"message": {"content": []}}, None),
            ({"message": {"content": [{}]}}, None),
            ({"message": {}}, None),
        ],
    )
    def test_gemini_accepts_text_shapes_without_echoing_user_or_empty_frames(
        self,
        event,
        answer,
    ) -> None:
        event = {"type": "message", **event}
        report, usage = gemini_report(
            [
                {"type": "message", "role": "user", "message": "private prompt"},
                {"type": "tool_result", "is_error": True},
                {"type": "heartbeat"},
                event,
                {"type": "result"},
            ],
            access="read_only",
            model=None,
        )
        assert report.outcome == "completed"
        assert report.answer == (answer or "(Gemini CLI sent no answer.)")
        assert "private prompt" not in report.answer
        assert live_items("gemini", event) == ([Said(answer)] if answer else [])
        assert usage.by_model == {}

    def test_gemini_keeps_failed_edits_once_when_a_run_ends_with_an_error(self) -> None:
        edit = {"type": "tool_use", "tool": "write_file", "args": {"path": "app.py"}}
        report, _ = gemini_report(
            [
                edit,
                edit,
                {"type": "tool_result", "is_error": True},
                {"type": "error", "message": "Quota reached"},
            ],
            access="edit",
            model=None,
        )
        assert report.outcome == "failed"
        assert report.answer == "Quota reached"
        assert report.files_changed == ["app.py"]
        assert [step.failed for step in report.steps] == [False, True]

    def test_gemini_without_a_result_or_error_is_still_unfinished(self) -> None:
        report, _ = gemini_report(
            [{"type": "init", "session_id": "s-1"}], access="read_only", model=None
        )
        assert report.outcome == "failed"
        assert "stopped before it finished" in report.answer

    @pytest.mark.parametrize(
        "tokens",
        [
            {
                "input_tokens": 4,
                "cached_input_tokens": 2,
                "cache_creation_input_tokens": 3,
                "output_tokens": 5,
            },
            {"inputTokens": 4, "cache_read_tokens": 2, "cache_write_tokens": 3, "outputTokens": 5},
            {"input": 4, "cacheRead": 2, "cacheWrite": 3, "output": 5},
        ],
    )
    def test_gemini_token_spellings_keep_fresh_cached_and_output_counts(self, tokens) -> None:
        _, usage = gemini_report(
            [{"type": "result", "stats": tokens}], access="read_only", model=None
        )
        spent = usage.by_model["gemini"]
        assert (
            spent.input_tokens,
            spent.cache_read_tokens,
            spent.cache_write_tokens,
            spent.output_tokens,
        ) == (9, 2, 3, 5)

    @pytest.mark.parametrize("field", ["models", "per_model"])
    def test_gemini_books_only_real_per_model_statistics(self, field) -> None:
        _, usage = gemini_report(
            [
                {
                    "type": "result",
                    "stats": {
                        field: {
                            "used-model": {"input_tokens": 4, "output_tokens": 5},
                            "empty": {},
                            "malformed": "not usage",
                        }
                    },
                }
            ],
            access="read_only",
            model="configured-model",
        )
        assert set(usage.by_model) == {"used-model"}
        assert (
            usage.by_model["used-model"].input_tokens,
            usage.by_model["used-model"].output_tokens,
        ) == (4, 5)

    def test_gemini_non_token_statistics_do_not_invent_usage(self) -> None:
        _, usage = gemini_report(
            [{"type": "result", "stats": {"duration_ms": 20}}], access="read_only", model=None
        )
        assert usage.by_model == {}

    @pytest.mark.parametrize("settled", [False, True])
    def test_pi_uses_latest_usage_and_waits_for_settled_after_agent_end(self, settled) -> None:
        events = [
            {"type": "message_update", "usage": {"input": 4, "output": 1}},
            {"type": "message_update", "usage": {"input": 9, "output": 5}},
            {"type": "message_update", "usage": {}},
            {"type": "message_end", "message": {"role": "user", "content": "private prompt"}},
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "text": "private thinking"},
                        17,
                        {"type": "text", "text": ""},
                        {"type": "text", "text": "Done."},
                    ],
                },
            },
            {"type": "agent_end"},
        ]
        if settled:
            events.append({"type": "agent_settled", "aborted": False})
        report, usage = pi_report(events, access="read_only", model=None)
        assert report.outcome == ("completed" if settled else "failed")
        assert "private" not in report.answer
        if settled:
            assert report.answer == "Done."
        else:
            assert "stopped before it finished" in report.answer
        assert (usage.by_model["pi"].input_tokens, usage.by_model["pi"].output_tokens) == (9, 5)

    @pytest.mark.parametrize("access", ["edit", "read_only"])
    @pytest.mark.parametrize(
        "failure,answer",
        [
            (
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": "Rate limited",
                        "stopReason": "error",
                    },
                },
                "Rate limited",
            ),
            (
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "stopReason": "aborted",
                    },
                },
                "Pi stopped with an error.",
            ),
            (
                {"type": "auto_retry_end", "success": False, "finalError": "Retries exhausted"},
                "Retries exhausted",
            ),
            ({"type": "auto_retry_end", "success": False}, "Pi stopped with an error."),
        ],
    )
    def test_pi_keeps_the_failure_and_deduplicates_repeated_tool_ids(
        self,
        access,
        failure,
        answer,
    ) -> None:
        edit = {
            "type": "tool_execution_start",
            "toolCallId": "c-1",
            "toolName": "edit",
            "args": {"path": "app.py"},
        }
        report, _ = pi_report(
            [
                edit,
                edit,
                {"type": "tool_execution_end", "toolCallId": "unknown", "isError": True},
                {"type": "tool_execution_end", "toolCallId": "c-1", "isError": True},
                {"type": "auto_retry_end", "success": True},
                failure,
                {"type": "agent_settled", "aborted": False},
            ],
            access=access,
            model=None,
        )
        assert (report.outcome, report.answer) == ("failed", answer)
        assert len(report.steps) == 1 and report.steps[0].failed
        assert report.files_changed == (["app.py"] if access == "edit" else [])

    @pytest.mark.parametrize(
        "message",
        [
            {"role": "user", "content": "private prompt"},
            {"role": "assistant", "content": []},
            {"role": "assistant", "content": [{"type": "text", "text": ""}]},
            {"role": "assistant", "content": None},
        ],
    )
    def test_pi_does_not_display_non_assistant_or_empty_final_messages(self, message) -> None:
        event = {"type": "message_end", "message": message}
        assert live_items("pi", event) == []
        report, _ = pi_report(
            [event, {"type": "agent_settled", "aborted": False}], access="read_only", model=None
        )
        assert report.outcome == "completed"
        assert report.answer == "(Pi sent no answer.)"
