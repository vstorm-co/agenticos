"""What a run handed its model, recorded from the wire rather than reconstructed.

The claim this module holds shut is that the record is *what was sent*. So the
tests drive a real agent against a `FunctionModel` and assert on what the
recorder wrote down - the instructions as composed, the tool definitions the
provider was handed, one entry per request - rather than on a hand-built
recorder that could agree with a wrong implementation.

Three things are worth failing loudly, and each has its own class below: a
credential must never reach the record, because `ModelSettings` carries provider
passthrough and passthrough is where a key rides; the record must survive a run
that ended badly, because that is the run somebody opens; and a record too large
to keep must say what it dropped, because a trimmed document that reads as a
complete one is worse than no document.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.tools import ToolDefinition
from sqlalchemy.dialects import postgresql

from app.agents.manifest import (
    MAX_PAYLOAD_BYTES,
    RecordedRequest,
    RecordingModel,
    RunRecorder,
    _size,
    as_payload,
    fit,
)
from app.db.models.agent_run import RunStatus
from app.db.models.run_manifest import RunManifest
from app.repositories import run_manifest_repo
from app.services.agent_runner import AgentRunnerService

pytestmark = pytest.mark.anyio

_RUN = uuid4()
_ORG = uuid4()
_MODULE = "app.services.agent_runner"


class _RecordingSession:
    """An `AsyncSession` stand-in that keeps the statements it was given."""

    def __init__(self, *results: object) -> None:
        self._results = list(results)
        self.statements: list[object] = []
        self.added: list[RunManifest] = []

    async def execute(self, statement: object) -> object:
        self.statements.append(statement)
        return self._results.pop(0)

    def add(self, instance: RunManifest) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None

    async def refresh(self, instance: RunManifest) -> None:
        return None


def _no_row():
    return SimpleNamespace(scalar_one_or_none=lambda: None)


def _one_row(row: RunManifest):
    return SimpleNamespace(scalar_one_or_none=lambda: row)


def _bound(session: _RecordingSession) -> dict[str, object]:
    """The values the last statement would send, by parameter name."""
    compiled = session.statements[-1].compile(dialect=postgresql.dialect())
    return dict(compiled.params)


def _recording(respond) -> tuple[RecordingModel, RunRecorder]:
    recorder = RunRecorder()
    return RecordingModel(FunctionModel(respond), recorder), recorder


async def _one_word(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[TextPart("Done.")])


class TestWhatTheProviderWasHanded:
    async def test_the_instructions_recorded_are_the_ones_sent(self):
        """Not the spec's text - the composed prompt, which is the spec's plus
        everything the builder appended. Nowhere else readable after the run."""
        model, recorder = _recording(_one_word)
        agent = Agent(model, instructions="You are a clerk. Be brief.")

        await agent.run("hello")

        assert recorder.instructions == "You are a clerk. Be brief."

    async def test_a_system_prompt_is_recorded_beside_the_instructions(self):
        """They are separate on the wire, so they are separate here: an agent
        built with `system_prompt=` sends one, a capability injecting a reminder
        sends another, and a reader comparing spec with reality needs both."""
        model, recorder = _recording(_one_word)
        agent = Agent(model, system_prompt="Answer in English.")

        await agent.run("hello")

        assert recorder.system_prompts == ["Answer in English."]

    async def test_every_tool_is_recorded_with_the_description_the_model_reads(self):
        """The description is the half that decides behaviour and the half no
        other surface shows: an agent that never calls a tool it has is usually
        an agent whose tool describes itself badly."""
        model, recorder = _recording(_one_word)
        agent = Agent(model)

        @agent.tool_plain
        def check_stock(sku: str) -> str:
            """Look up how many of one item are in the warehouse."""
            return "4"

        await agent.run("hello")

        recorded = {tool.name: tool for tool in recorder.tools}
        assert recorded["check_stock"].description == (
            "Look up how many of one item are in the warehouse."
        )
        assert "sku" in recorded["check_stock"].parameters_json_schema["properties"]
        assert recorded["check_stock"].kind == "function"

    async def test_a_request_is_recorded_for_each_time_the_model_was_asked(self):
        """A run is one row with one duration, and forty seconds is either one
        slow request or nine quick ones with tool calls between them."""

        async def call_then_answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            returned = any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
            if returned:
                return ModelResponse(parts=[TextPart("4 in stock.")])
            return ModelResponse(
                parts=[ToolCallPart(tool_name="check_stock", args={"sku": "x"}, tool_call_id="c1")]
            )

        model, recorder = _recording(call_then_answer)
        agent = Agent(model)

        @agent.tool_plain
        def check_stock(sku: str) -> str:
            """Look one up."""
            return "4"

        await agent.run("how many")

        assert [request.index for request in recorder.requests] == [0, 1]
        assert recorder.requests[0].tool_calls == ["check_stock"]
        # The request that answered called nothing, and carried more history
        # than the one before it - which is the cost a long run really pays.
        assert recorder.requests[1].tool_calls == []
        assert recorder.requests[1].message_count > recorder.requests[0].message_count

    async def test_the_messages_kept_are_the_last_request_s_whole_context(self):
        """The transcript says what was asked and answered; this says what the
        model was looking at when it answered - tool returns included."""

        async def call_then_answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            returned = any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
            if returned:
                return ModelResponse(parts=[TextPart("4 in stock.")])
            return ModelResponse(
                parts=[ToolCallPart(tool_name="check_stock", args={"sku": "x"}, tool_call_id="c1")]
            )

        model, recorder = _recording(call_then_answer)
        agent = Agent(model)

        @agent.tool_plain
        def check_stock(sku: str) -> str:
            """Look one up."""
            return "4"

        await agent.run("how many")

        kinds = [part["part_kind"] for message in recorder.messages for part in message["parts"]]
        assert "tool-return" in kinds


class TestAStreamedRun:
    async def test_a_streamed_response_is_recorded_once_it_is_complete(self):
        """Recorded after the stream closes, not when it opens: read before the
        caller has consumed it, the usage is zero and the finish reason is not
        yet known - so the waterfall would show every streamed request as free."""

        async def stream(messages: list[ModelMessage], info: AgentInfo):
            yield "It is "
            yield "done."

        recorder = RunRecorder()
        model = RecordingModel(FunctionModel(_one_word, stream_function=stream), recorder)
        agent = Agent(model, instructions="Be brief.")

        async with agent.run_stream("hello") as result:
            await result.get_output()

        assert len(recorder.requests) == 1
        assert recorder.instructions == "Be brief."

    async def test_a_stream_that_never_opened_is_recorded_as_a_failure(self):
        """The hole the guard closes. A manifest exists to say which request
        failed, and the streaming path is where a provider refusal usually
        surfaces - so a failed run whose waterfall omits exactly that request is
        the record missing the row it was written for."""

        async def refuse(messages: list[ModelMessage], info: AgentInfo):
            raise TimeoutError("the provider took too long")
            yield ""  # unreachable; what makes this an async generator

        recorder = RunRecorder()
        model = RecordingModel(FunctionModel(_one_word, stream_function=refuse), recorder)
        agent = Agent(model, instructions="Be brief.")

        with pytest.raises(TimeoutError):
            async with agent.run_stream("hello"):
                pass

        assert [request.failed for request in recorder.requests] == ["TimeoutError"]
        assert recorder.instructions == "Be brief."
        assert "took too long" not in str(as_payload(recorder))

    async def test_a_stream_that_broke_while_being_read_is_recorded_too(self):
        """The second half of the same guard: acquiring the response and consuming
        it are two exceptions, and both used to leave the run with no entry."""

        async def stream(messages: list[ModelMessage], info: AgentInfo):
            yield "It is "
            raise ConnectionError("the connection dropped")

        recorder = RunRecorder()
        model = RecordingModel(FunctionModel(_one_word, stream_function=stream), recorder)
        agent = Agent(model)

        with pytest.raises(ConnectionError):
            async with agent.run_stream("hello") as result:
                await result.get_output()

        assert [request.failed for request in recorder.requests] == ["ConnectionError"]


class TestARunThatEndedBadly:
    async def test_a_failed_request_is_recorded_as_one_that_failed(self):
        """The run somebody opens. A run that failed on its fourth request and
        one that failed on its first are the same red row otherwise."""

        async def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise TimeoutError("the provider took too long")

        model, recorder = _recording(refuse)
        agent = Agent(model)

        with pytest.raises(TimeoutError):
            await agent.run("hello")

        assert [request.failed for request in recorder.requests] == ["TimeoutError"]
        # The class, never the message: a provider SDK puts the failing URL - and
        # therefore a key in its query string - in that string.
        assert "took too long" not in str(as_payload(recorder))

    async def test_the_prompt_survives_a_run_that_never_answered(self):
        """Recorded before the request goes out, so a run that died mid-request
        still says what it was given."""

        async def refuse(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise RuntimeError("no")

        model, recorder = _recording(refuse)
        agent = Agent(model, instructions="Be brief.")

        with pytest.raises(RuntimeError):
            await agent.run("hello")

        assert recorder.instructions == "Be brief."


class TestWhatIsNeverRecorded:
    def test_provider_passthrough_is_dropped_from_the_settings(self):
        """`extra_headers` and `extra_body` are where a provider-specific
        credential rides. The vault is the only place a secret is kept, and a
        manifest that copied one would be the second."""
        recorder = RunRecorder()

        recorder.observe_request(
            [ModelRequest(parts=[SystemPromptPart(content="hi")])],
            {"temperature": 0.2, "extra_headers": {"x-api-key": "sk-live-not-a-real-key"}},
            ModelRequestParameters(),
        )

        assert recorder.settings == {"temperature": 0.2}
        assert "sk-live" not in str(as_payload(recorder))

    def test_no_settings_at_all_is_an_empty_record_rather_than_a_failure(self):
        recorder = RunRecorder()

        recorder.observe_request([], None, ModelRequestParameters())

        assert recorder.settings == {}


class TestARecordTooLargeToKeep:
    @staticmethod
    def _payload(**overrides) -> dict:
        recorder = RunRecorder()
        recorder.instructions = "Be brief."
        recorder.requests = [
            RecordedRequest(
                index=0,
                started_at=datetime.now(UTC),
                duration_ms=12,
                model="test",
                message_count=1,
                input_tokens=1,
                output_tokens=1,
                cache_read_tokens=0,
                tool_calls=[],
                finish_reason="stop",
            )
        ]
        return {**as_payload(recorder), **overrides}

    def test_a_record_that_fits_is_stored_whole(self):
        payload, truncated = fit(self._payload())

        assert truncated is False
        assert payload["instructions"] == "Be brief."

    def test_the_messages_are_what_goes_first(self):
        """Largest by far, and the transcript beside them already says what was
        asked and answered."""
        huge = [{"parts": [{"content": "x" * MAX_PAYLOAD_BYTES}]}]

        payload, truncated = fit(self._payload(messages=huge))

        assert truncated is True
        assert payload["messages"] == []
        assert payload["instructions"] == "Be brief."

    def test_a_schema_goes_before_the_sentence_that_explains_it(self):
        """What is left of a tool is its name and its description - the half that
        explains behaviour, and the half readable nowhere else."""
        tools = [
            {
                "name": "search",
                "description": "Search the web.",
                "parameters_json_schema": {"blob": "y" * MAX_PAYLOAD_BYTES},
                "kind": "function",
            }
        ]

        payload, truncated = fit(self._payload(tools=tools))

        assert truncated is True
        assert payload["tools"][0]["description"] == "Search the web."
        assert payload["tools"][0]["parameters_json_schema"] == {}

    def test_a_tool_description_is_clipped_when_the_schemas_were_not_the_problem(self):
        """An MCP server describing one tool in a manual. Nothing bounds a remote
        description, so with the messages and the schemas already gone it is what
        is left of the oversized half."""
        tools = [
            {
                "name": "search",
                "description": "z" * MAX_PAYLOAD_BYTES,
                "parameters_json_schema": {},
                "kind": "function",
            }
        ]

        payload, truncated = fit(self._payload(tools=tools))

        assert truncated is True
        assert len(payload) > 0
        assert payload["tools"][0]["description"].endswith("… [truncated]")
        assert _size(payload) <= MAX_PAYLOAD_BYTES

    def test_an_unbounded_prompt_is_clipped_last_rather_than_stored_whole(self):
        """The ceiling the advertised one was not. `instructions` is the agent's
        own text and nothing bounds its length, so a manifest was persisted over
        the limit on every run of an agent with a very long prompt."""
        payload, truncated = fit(
            self._payload(
                instructions="i" * MAX_PAYLOAD_BYTES,
                system_prompts=["s" * MAX_PAYLOAD_BYTES],
            )
        )

        assert truncated is True
        assert payload["instructions"].endswith("… [truncated]")
        assert payload["system_prompts"][0].endswith("… [truncated]")
        assert _size(payload) <= MAX_PAYLOAD_BYTES

    def test_the_waterfall_survives_every_cut(self):
        """What a reader is left with when everything else went: which requests
        were made, how long each took and what it cost."""
        payload, _ = fit(self._payload(instructions="i" * MAX_PAYLOAD_BYTES, messages=[{"x": "y"}]))

        assert [request["duration_ms"] for request in payload["requests"]] == [12]

    def test_nothing_is_clipped_where_a_field_is_short_or_not_prose(self):
        """The payload has been through JSON by the time it is trimmed, so a
        description may be null - and a clip that assumed a string would raise while
        writing a record nobody asked for. A short one is left whole for the plainer
        reason: there is nothing to gain by cutting it.

        The oversize is a system prompt, so both late stages run and neither the null
        description nor the short one is what fit had to give up."""
        tools = [
            {"name": "t", "description": None, "parameters_json_schema": {}, "kind": "function"},
            {
                "name": "u",
                "description": "Short.",
                "parameters_json_schema": {},
                "kind": "function",
            },
        ]

        payload, truncated = fit(
            self._payload(
                tools=tools,
                instructions=None,
                system_prompts=["s" * MAX_PAYLOAD_BYTES],
            )
        )

        assert truncated is True
        assert [tool["description"] for tool in payload["tools"]] == [None, "Short."]
        assert payload["instructions"] is None
        assert payload["system_prompts"][0].endswith("… [truncated]")


class TestTheOutputToolIsRecordedToo:
    def test_an_output_tool_is_marked_as_one(self):
        """It is a tool the provider was told about like any other, and a reader
        counting what the agent could call must not count it as a capability."""
        recorder = RunRecorder()

        recorder.observe_request(
            [],
            None,
            ModelRequestParameters(
                output_tools=[
                    ToolDefinition(name="final_result", parameters_json_schema={"type": "object"})
                ]
            ),
        )

        assert [(tool.name, tool.kind) for tool in recorder.tools] == [("final_result", "output")]


class TestTheRowItIsStoredIn:
    """Both halves of the read are scoped, and the write replaces rather than adds.

    A parked run is finished twice - once when it stops on an approval, once when
    it is resumed and ends - and `run_id` is unique. A blind insert would raise on
    precisely the runs somebody most wants to read.
    """

    async def test_the_read_filters_on_the_run_and_the_organization(self) -> None:
        session = _RecordingSession(_no_row())

        await run_manifest_repo.get_by_run(session, _RUN, _ORG)

        bound = set(_bound(session).values())
        # Dropping either half is a cross-tenant read.
        assert _RUN in bound
        assert _ORG in bound

    async def test_a_second_recording_replaces_the_first(self) -> None:
        existing = RunManifest(run_id=_RUN, organization_id=_ORG, payload={}, truncated=False)
        session = _RecordingSession(_one_row(existing))

        stored = await run_manifest_repo.record(
            session,
            run_id=_RUN,
            organization_id=_ORG,
            payload={"instructions": "Be brief."},
            truncated=True,
        )

        assert stored is existing
        assert stored.payload == {"instructions": "Be brief."}
        assert stored.truncated is True
        assert session.added == []

    async def test_a_first_recording_is_added(self) -> None:
        session = _RecordingSession(_no_row())

        stored = await run_manifest_repo.record(
            session, run_id=_RUN, organization_id=_ORG, payload={}, truncated=False
        )

        assert session.added == [stored]
        assert stored.run_id == _RUN


class TestTheRunnerWritesItHoweverTheRunEnded:
    """On every path out of `finish`, for the reason the run row is: the run
    somebody wants the prompt and the tools for is the one that failed."""

    @staticmethod
    def _prepared(recorder: RunRecorder) -> MagicMock:
        prepared = MagicMock()
        prepared.run = MagicMock(id=_RUN, organization_id=_ORG, conversation_id=None)
        prepared.built.ledger = MagicMock(
            input_tokens=10, output_tokens=2, total_usd=Decimal("0.01"), has_unpriced_models=False
        )
        prepared.built.recorder = recorder
        prepared.approvals.requested = []
        prepared.delegations = []
        return prepared

    @staticmethod
    def _service() -> AgentRunnerService:
        return AgentRunnerService(MagicMock(commit=AsyncMock()))

    @staticmethod
    def _quiet(service: AgentRunnerService, stack: ExitStack) -> None:
        """Everything else `finish` does, silenced - this is about one write."""
        for patched in (
            patch(f"{_MODULE}.agent_run_repo.finish_run", new=AsyncMock()),
            patch.object(service, "_collect_outbound", new=AsyncMock()),
            patch.object(service, "_propose_skill_changes", new=AsyncMock()),
            patch.object(service, "_write_approvals", new=AsyncMock()),
            patch.object(service, "_write_delegations", new=AsyncMock()),
            patch.object(service, "_notify", new=AsyncMock()),
            patch.object(service.workspaces, "close", new=AsyncMock()),
        ):
            stack.enter_context(patched)

    @pytest.mark.parametrize(
        "status",
        [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED],
        ids=lambda status: status.value,
    )
    async def test_every_ending_stores_what_the_model_was_given(self, status) -> None:
        recorder = RunRecorder()
        recorder.instructions = "Be brief."
        service = self._service()
        prepared = self._prepared(recorder)
        written = AsyncMock()

        with ExitStack() as stack:
            self._quiet(service, stack)
            stack.enter_context(patch(f"{_MODULE}.run_manifest_repo.record", new=written))
            await service.finish(prepared, status=status)

        assert written.await_args.kwargs["payload"]["instructions"] == "Be brief."
        assert written.await_args.kwargs["organization_id"] == _ORG

    async def test_a_run_that_never_reached_a_model_records_nothing(self) -> None:
        """A fact about the run - refused by a budget, blocked on the way in - and
        an empty row would read as a record that failed to capture."""
        service = self._service()
        prepared = self._prepared(RunRecorder())
        written = AsyncMock()

        with ExitStack() as stack:
            self._quiet(service, stack)
            stack.enter_context(patch(f"{_MODULE}.run_manifest_repo.record", new=written))
            await service.finish(prepared, status=RunStatus.BUDGET_EXCEEDED)

        written.assert_not_awaited()

    async def test_a_failed_write_does_not_replace_the_failure_it_was_recording(self) -> None:
        """Reached from a `finally`: an exception raised while recording a failed
        run would send an operator to debug the observability write."""
        recorder = RunRecorder()
        recorder.instructions = "Be brief."
        service = self._service()
        prepared = self._prepared(recorder)

        with ExitStack() as stack:
            self._quiet(service, stack)
            stack.enter_context(
                patch(
                    f"{_MODULE}.run_manifest_repo.record", new=AsyncMock(side_effect=OSError("no"))
                )
            )
            await service.finish(prepared, status=RunStatus.FAILED)
