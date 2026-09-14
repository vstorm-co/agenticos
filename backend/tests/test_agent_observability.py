"""Per-agent Logfire: whose project a run's traces land in.

The property worth pinning is not that Logfire works - that is Logfire's
problem. It is that an agent with no observability block is left alone, that a
token which has gone missing does not stop the agent running, and that the
write token never leaves the vault path it came in on.
"""

import uuid
from unittest.mock import MagicMock, patch

import logfire
from logfire.testing import TestExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from app.agents.factory import _instrument
from app.agents.observability import (
    _RedactingSpanProcessor,
    instrument_agent,
    suppress_content,
)
from app.agents.spec import AgentSpec, ObservabilitySpec
from app.core.secret_kinds import ApiKeySecret

MODULE = "app.agents.factory"


def _secret(token: str = "pylf_v1_eu_secret") -> ApiKeySecret:
    return ApiKeySecret(api_key=token)


class TestInstrumentation:
    def test_an_agent_that_asked_for_nothing_is_left_on_the_deployment_config(self):
        """The default, and the one that must stay free: no per-agent exporter."""
        agent = MagicMock()
        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(agent, AgentSpec(name="a"), {}, agent_id=None)

        instrument.assert_not_called()

    def test_the_agents_own_token_and_environment_are_used(self):
        secret_id = uuid.uuid4()
        spec = AgentSpec(
            name="Support",
            observability=ObservabilitySpec(
                token_secret_id=secret_id, service_name="acme-support", environment="production"
            ),
        )
        agent = MagicMock()

        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(agent, spec, {secret_id: _secret()}, agent_id=uuid.uuid4())

        kwargs = instrument.call_args.kwargs
        assert kwargs["token"] == "pylf_v1_eu_secret"
        assert kwargs["service_name"] == "acme-support"
        assert kwargs["environment"] == "production"

    def test_full_content_is_the_default_and_records_everything(self):
        """An agent that says nothing about content traces as it always did."""
        secret_id = uuid.uuid4()
        spec = AgentSpec(name="Support", observability=ObservabilitySpec(token_secret_id=secret_id))

        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(MagicMock(), spec, {secret_id: _secret()}, agent_id=None)

        assert instrument.call_args.kwargs["content"] == "full"

    def test_none_content_instruments_without_message_text(self):
        """`none` is the switch a deployment over health, legal or HR data needs:
        the run still traces its timing and cost, but no prompt, output or tool
        argument reaches the Logfire project (#1413)."""
        secret_id = uuid.uuid4()
        spec = AgentSpec(
            name="Support",
            observability=ObservabilitySpec(token_secret_id=secret_id, content="none"),
        )

        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(MagicMock(), spec, {secret_id: _secret()}, agent_id=None)

        assert instrument.call_args.kwargs["content"] == "none"

    def test_redacted_content_reaches_the_instrumentation(self):
        """`redacted` is the middle ground the security programme asked for: the
        content is traced but its PII is scrubbed before export, so the mode has
        to reach the instrumentation the same way `none` does (#1616)."""
        secret_id = uuid.uuid4()
        spec = AgentSpec(
            name="Support",
            observability=ObservabilitySpec(token_secret_id=secret_id, content="redacted"),
        )

        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(MagicMock(), spec, {secret_id: _secret()}, agent_id=None)

        assert instrument.call_args.kwargs["content"] == "redacted"

    def test_the_agent_names_itself_when_no_service_name_was_given(self):
        """A blank service name in Logfire is a project nobody can read."""
        secret_id = uuid.uuid4()
        spec = AgentSpec(name="Support", observability=ObservabilitySpec(token_secret_id=secret_id))

        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(MagicMock(), spec, {secret_id: _secret()}, agent_id=None)

        assert instrument.call_args.kwargs["service_name"] == "Support"

    def test_a_secret_deleted_after_publish_leaves_the_agent_running(self):
        """The alternative is an agent that stops answering because a trace
        destination went away, which is the observability tail wagging the dog."""
        spec = AgentSpec(name="a", observability=ObservabilitySpec(token_secret_id=uuid.uuid4()))

        with patch(f"{MODULE}.instrument_agent") as instrument:
            _instrument(MagicMock(), spec, {}, agent_id=None)

        instrument.assert_not_called()

    def test_none_without_a_token_suppresses_content_on_the_default_tracer(self):
        """The P1 gap: no per-agent token, so no exporter attaches - but the
        deployment instruments Pydantic AI globally with content on, so the run's
        prompts would still reach the operator's project. `none` must pin the
        agent content-free regardless (#1413). This is also the environment-routed
        case, where the token lives on the environment, not the agent."""
        spec = AgentSpec(name="a", observability=ObservabilitySpec(content="none"))

        with (
            patch(f"{MODULE}.instrument_agent") as instrument,
            patch(f"{MODULE}.suppress_content") as suppress,
        ):
            _instrument(MagicMock(), spec, {}, agent_id=None)

        instrument.assert_not_called()
        suppress.assert_called_once()

    def test_none_with_a_deleted_token_still_suppresses_content(self):
        """A token removed after publish leaves no exporter; the agent must not
        fall back to full-content deployment traces."""
        spec = AgentSpec(
            name="a",
            observability=ObservabilitySpec(token_secret_id=uuid.uuid4(), content="none"),
        )

        with (
            patch(f"{MODULE}.instrument_agent") as instrument,
            patch(f"{MODULE}.suppress_content") as suppress,
        ):
            _instrument(MagicMock(), spec, {}, agent_id=None)

        instrument.assert_not_called()
        suppress.assert_called_once()

    def test_none_falls_back_to_suppression_when_the_exporter_fails(self):
        """The per-agent exporter can fail to attach - a bad token, a Logfire
        outage - and content must still be suppressed rather than left to the
        global default."""
        secret_id = uuid.uuid4()
        spec = AgentSpec(
            name="a",
            observability=ObservabilitySpec(token_secret_id=secret_id, content="none"),
        )

        with (
            patch(f"{MODULE}.instrument_agent", return_value=False) as instrument,
            patch(f"{MODULE}.suppress_content") as suppress,
        ):
            _instrument(MagicMock(), spec, {secret_id: _secret()}, agent_id=None)

        instrument.assert_called_once()
        suppress.assert_called_once()

    def test_none_with_a_working_exporter_does_not_also_suppress(self):
        """A per-agent exporter that attaches content-free already overrides the
        global default for this agent, so no second instrumentation is needed."""
        secret_id = uuid.uuid4()
        spec = AgentSpec(
            name="a",
            observability=ObservabilitySpec(token_secret_id=secret_id, content="none"),
        )

        with (
            patch(f"{MODULE}.instrument_agent", return_value=True) as instrument,
            patch(f"{MODULE}.suppress_content") as suppress,
        ):
            _instrument(MagicMock(), spec, {secret_id: _secret()}, agent_id=None)

        instrument.assert_called_once()
        suppress.assert_not_called()

    def test_full_without_a_token_is_left_on_the_deployment_default(self):
        """`full` with no per-agent token is the ordinary agent: the global
        instrumentation handles it, and neither path here fires."""
        spec = AgentSpec(name="a", observability=ObservabilitySpec(content="full"))

        with (
            patch(f"{MODULE}.instrument_agent") as instrument,
            patch(f"{MODULE}.suppress_content") as suppress,
        ):
            _instrument(MagicMock(), spec, {}, agent_id=None)

        instrument.assert_not_called()
        suppress.assert_not_called()

    def test_redacted_without_a_token_suppresses_rather_than_leaks(self):
        """Redaction rides on a per-agent tracer provider, so with no token there
        is nowhere to attach it - and exporting content unscrubbed to the
        operator's project is the leak `redacted` exists to prevent. It degrades to
        `none`: content is suppressed on the deployment's own instrumentation."""
        spec = AgentSpec(name="a", observability=ObservabilitySpec(content="redacted"))

        with (
            patch(f"{MODULE}.instrument_agent") as instrument,
            patch(f"{MODULE}.suppress_content") as suppress,
        ):
            _instrument(MagicMock(), spec, {}, agent_id=None)

        instrument.assert_not_called()
        suppress.assert_called_once()


class TestContentReachesLogfire:
    """The content decision has to reach the instrumentation call, not stop at
    the spec: a `none` that the factory reads but never passes on is a promise
    the schema makes and the exporter breaks (#1413)."""

    def test_none_turns_off_content_on_the_instrumentation(self):
        instance = MagicMock()
        # A token unique to this test: the module caches instances per
        # (token, service, environment, redact), so a shared one would reuse a
        # prior test's configure() and never call this mock.
        with patch("app.agents.observability.logfire.configure", return_value=instance):
            attached = instrument_agent(
                MagicMock(),
                token="pylf_v1_eu_none_case",
                service_name="acme",
                environment="prod",
                content="none",
            )

        assert attached is True
        assert instance.instrument_pydantic_ai.call_args.kwargs["include_content"] is False

    def test_full_leaves_content_on(self):
        instance = MagicMock()
        with patch("app.agents.observability.logfire.configure", return_value=instance):
            instrument_agent(
                MagicMock(),
                token="pylf_v1_eu_full_case",
                service_name="acme",
                environment="prod",
            )

        assert instance.instrument_pydantic_ai.call_args.kwargs["include_content"] is True

    def test_redacted_keeps_content_on_but_attaches_the_scrubbing_processor(self):
        """`redacted` traces the content - `include_content` stays on - and adds
        the span processor that removes its PII before export. `full` and `none`
        add no processor."""
        instance = MagicMock()
        with patch(
            "app.agents.observability.logfire.configure", return_value=instance
        ) as configure:
            instrument_agent(
                MagicMock(),
                token="pylf_v1_eu_redacted_case",
                service_name="acme",
                environment="prod",
                content="redacted",
            )

        assert instance.instrument_pydantic_ai.call_args.kwargs["include_content"] is True
        processors = configure.call_args.kwargs["additional_span_processors"]
        assert len(processors) == 1
        assert isinstance(processors[0], _RedactingSpanProcessor)

    def test_full_attaches_no_span_processor(self):
        """The scrubbing rides only on a redacted instance; a `full` run must not
        pay for a processor it does not need, and must not be keyed together with
        a redacted one."""
        instance = MagicMock()
        with patch(
            "app.agents.observability.logfire.configure", return_value=instance
        ) as configure:
            instrument_agent(
                MagicMock(),
                token="pylf_v1_eu_full_noproc",
                service_name="acme",
                environment="prod",
                content="full",
            )

        assert configure.call_args.kwargs["additional_span_processors"] is None

    def test_suppress_content_pins_the_agent_to_content_free_default_tracing(self):
        """Uses the default (deployment) instance, so timing and cost still land
        in the operator's project - only the content is dropped."""
        with patch("app.agents.observability.logfire.instrument_pydantic_ai") as instrument:
            suppress_content(MagicMock())

        assert instrument.call_args.kwargs["include_content"] is False

    def test_suppress_content_swallows_a_failure(self):
        """An agent whose instrumentation cannot attach still answers questions."""
        with patch(
            "app.agents.observability.logfire.instrument_pydantic_ai",
            side_effect=RuntimeError("boom"),
        ):
            suppress_content(MagicMock())  # must not raise


class TestSpec:
    def test_content_defaults_to_full_so_a_stored_spec_is_unchanged(self):
        """Additive with a default: a spec written before the field loads with
        `full` and traces exactly as it did, so no migration is owed."""
        assert ObservabilitySpec().content == "full"
        loaded = AgentSpec.from_yaml("name: Support\nobservability:\n  token_secret_id: null\n")
        assert loaded.observability is not None
        assert loaded.observability.content == "full"

    def test_the_token_is_stored_as_a_reference_never_a_value(self):
        """A spec is exported as YAML into somebody's repository. A write token
        in a checked-in file is a token that has to be rotated."""
        assert "token" not in {
            field for field in ObservabilitySpec.model_fields if field != "token_secret_id"
        }

    def test_an_unknown_key_is_refused(self):
        # `extra="forbid"`, like every other block: a misspelled field that is
        # silently accepted is a setting somebody believes is on.
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            # `project` used to stand in for an unknown key here and is now a real
            # field - where a client's traces can be *read*, which a write token
            # does not say (#206). A plausible wrong name for it is the better
            # example anyway: that is what somebody actually types.
            ObservabilitySpec(project_slug="acme")  # ty: ignore[unknown-argument]

    def test_a_slug_that_would_escape_the_url_is_refused(self):
        """`organization` and `project` are interpolated into a Logfire URL path
        when a run's trace link is built, so a value with a slash or a query
        character would point the link somewhere other than the project. A length
        bound does not stop that; the slug pattern does."""
        import pytest
        from pydantic import ValidationError

        for bad in ["../evil", "acme/prod", "acme?x=1", "Acme Corp", "acme_prod"]:
            with pytest.raises(ValidationError):
                ObservabilitySpec(organization=bad)
            with pytest.raises(ValidationError):
                ObservabilitySpec(project=bad)

    def test_an_ordinary_slug_is_accepted(self):
        spec = ObservabilitySpec(organization="vstorm", project="agenticos-eu")
        assert (spec.organization, spec.project) == ("vstorm", "agenticos-eu")

    def test_redacted_is_an_additive_third_mode(self):
        """Widening the Literal is additive, so a stored `full`/`none` spec still
        loads and no migration is owed - and `redacted` round-trips through YAML."""
        assert ObservabilitySpec(content="redacted").content == "redacted"
        loaded = AgentSpec.from_yaml(
            "name: Support\nobservability:\n  token_secret_id: null\n  content: redacted\n"
        )
        assert loaded.observability is not None
        assert loaded.observability.content == "redacted"
        assert loaded == AgentSpec.from_yaml(loaded.to_yaml())


class TestRedactionReachesTheExporter:
    """The property that matters for `redacted`: a planted email or token is gone
    from a span's content by the time it is exported, while the shape of the
    exchange survives. Pinned against the real Pydantic AI + Logfire pipeline so a
    version that renames the content attributes fails here rather than leaking
    silently (#1616)."""

    @staticmethod
    def _run_and_capture(content: str, prompt: str) -> InMemorySpanExporter:
        real_configure = logfire.configure
        capture = InMemorySpanExporter()

        def configure(**kwargs: object) -> logfire.Logfire:
            # Attach the real redaction processor exactly as instrument_agent asks
            # for it, then capture in memory instead of shipping to Logfire.
            processors = list(kwargs.get("additional_span_processors") or [])
            return real_configure(
                local=True,
                send_to_logfire=False,
                console=False,
                additional_span_processors=[*processors, SimpleSpanProcessor(capture)],
            )

        agent: Agent[None, str] = Agent(TestModel(custom_output_text="acknowledged"))
        with patch("app.agents.observability.logfire.configure", side_effect=configure):
            # A token unique per content mode: the module caches instances, and a
            # shared key would reuse another test's real configure.
            attached = instrument_agent(
                agent,
                token=f"pylf_v1_eu_capture_{content}",
                service_name="capture",
                environment="prod",
                content=content,
            )
        assert attached is True
        agent.run_sync(prompt)
        return capture

    def test_a_redacted_run_carries_the_shape_but_not_the_pii(self):
        prompt = "email planted@example.com, key sk-abcdef0123456789ABCDEF, thanks"
        capture = self._run_and_capture("redacted", prompt)

        content_values = [
            value
            for span in capture.get_finished_spans()
            for name, value in (span.attributes or {}).items()
            if name in _RedactingSpanProcessor._CONTENT_ATTRIBUTES and isinstance(value, str)
        ]
        # The content attributes are still present - the trace keeps its shape...
        assert content_values
        blob = "\n".join(content_values)
        # ...but the planted PII has been scrubbed out of every one of them.
        assert "planted@example.com" not in blob
        assert "sk-abcdef0123456789ABCDEF" not in blob
        assert "[EMAIL_REDACTED]" in blob
        assert "[API_KEY_REDACTED]" in blob
        # The ordinary words survive, so the trace is still debuggable - the whole
        # point of `redacted` over `none`.
        assert "thanks" in blob

    def test_a_full_run_carries_the_pii_unchanged(self):
        """The control: without redaction the same planted values reach the
        exporter, which is what `redacted` and `none` exist to stop."""
        prompt = "email planted@example.com please"
        capture = self._run_and_capture("full", prompt)

        blob = "\n".join(
            value
            for span in capture.get_finished_spans()
            for value in (span.attributes or {}).values()
            if isinstance(value, str)
        )
        assert "planted@example.com" in blob

    def test_a_none_run_carries_neither(self):
        """`none` strips the message text out of the content attributes, so a span
        keeps the shape of the exchange but neither the PII nor the ordinary words
        - the distinction from `redacted`, which keeps the scrubbed words."""
        prompt = "email planted@example.com kindly"
        capture = self._run_and_capture("none", prompt)

        blob = "\n".join(
            value
            for span in capture.get_finished_spans()
            for value in (span.attributes or {}).values()
            if isinstance(value, str)
        )
        assert "planted@example.com" not in blob
        # Even the ordinary prompt word is gone: `none` drops the text entirely,
        # where `redacted` would keep "kindly" beside the scrubbed email.
        assert "kindly" not in blob

    @staticmethod
    def _run_tool_and_capture_pending(tag: str, tool_args: dict[str, str]) -> TestExporter:
        """Run a redacted agent that calls a tool with `tool_args`, capturing every
        exported span including Logfire's pending spans.

        `TestExporter` is one of the exporters Logfire generates pending spans for,
        so wiring it in reproduces the production path where a tool span's
        arguments are exported at start, before the run finishes. `tag` keeps the
        cached Logfire instance unique per test, or a later call reuses an earlier
        exporter and captures nothing.
        """
        real_configure = logfire.configure
        capture = TestExporter()

        def configure(**kwargs: object) -> logfire.Logfire:
            processors = list(kwargs.get("additional_span_processors") or [])
            return real_configure(
                local=True,
                send_to_logfire=False,
                console=False,
                additional_span_processors=[*processors, SimpleSpanProcessor(capture)],
            )

        state = {"first": True}

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if state["first"]:
                state["first"] = False
                return ModelResponse(parts=[ToolCallPart(tool_name="lookup", args=tool_args)])
            return ModelResponse(parts=[TextPart(content="done")])

        agent: Agent[None, str] = Agent(FunctionModel(respond))

        @agent.tool_plain
        def lookup(**kwargs: str) -> str:
            return "ok"

        with patch("app.agents.observability.logfire.configure", side_effect=configure):
            attached = instrument_agent(
                agent,
                token=f"pylf_v1_eu_pending_{tag}",
                service_name="pending",
                environment="prod",
                content="redacted",
            )
        assert attached is True
        agent.run_sync("go")
        return capture

    def test_a_tool_argument_is_scrubbed_in_the_pending_span_too(self):
        """The pending-span leak: a tool span carries its arguments from the moment
        it starts, and Logfire exports a pending copy before the run ends. An
        on_end-only scrub would let the raw argument reach Logfire; this asserts the
        planted email is gone from every exported span, pending ones included."""
        capture = self._run_tool_and_capture_pending("email", {"email": "planted@example.com"})

        pending = [
            s
            for s in capture.exported_spans
            if (s.attributes or {}).get("logfire.span_type") == "pending_span"
        ]
        tool_args = [
            value
            for s in capture.exported_spans
            for name, value in (s.attributes or {}).items()
            if name == "gen_ai.tool.call.arguments" and isinstance(value, str)
        ]
        # A pending span was emitted, and the tool arguments appear on it...
        assert pending
        assert any('"email"' in value for value in tool_args)
        # ...but the planted email is gone from every span, pending or final.
        blob = "\n".join(
            value
            for s in capture.exported_spans
            for value in (s.attributes or {}).values()
            if isinstance(value, str)
        )
        assert "planted@example.com" not in blob
        assert "[EMAIL_REDACTED]" in blob

    def test_a_json_credential_in_a_tool_argument_is_scrubbed(self):
        """A password serialized as a tool argument - `{"password": "..."}` - is
        the credential shape the log filter's key=value pattern misses. Redacted
        mode must still keep it out of the export."""
        capture = self._run_tool_and_capture_pending(
            "json", {"password": "hunter2", "city": "Paris"}
        )

        blob = "\n".join(
            value
            for s in capture.exported_spans
            for value in (s.attributes or {}).values()
            if isinstance(value, str)
        )
        assert "hunter2" not in blob
        # A non-credential argument survives, so the trace stays debuggable.
        assert "Paris" in blob

    def test_a_span_with_no_content_attributes_is_left_untouched(self):
        """The processor only rewrites the attributes it recognises; a span that
        carries none of them - or none at all - keeps its backing store."""
        processor = _RedactingSpanProcessor()

        blank = _FakeSpan(None)
        processor.on_end(blank)  # must not raise

        unrelated = _FakeSpan({"gen_ai.usage.input_tokens": 12, "http.method": "POST"})
        before = unrelated._attributes
        processor.on_end(unrelated)
        assert unrelated._attributes is before

    def test_matching_attributes_are_replaced_with_their_scrubbed_form(self):
        """The write path directly: content attributes holding PII are swapped for
        a fresh mapping carrying the scrubbed text, since the backing store refuses
        in-place assignment. Two of them, so the second reuses the mapping the
        first built rather than starting another."""
        processor = _RedactingSpanProcessor()
        span = _FakeSpan(
            {
                "gen_ai.input.messages": "reach me at planted@example.com",
                "gen_ai.output.messages": "sure, sk-abcdef0123456789ABCDEF works",
                "gen_ai.usage.input_tokens": 7,
            }
        )
        before = span._attributes

        processor.on_end(span)

        result = span._attributes
        assert result is not before
        assert isinstance(result, dict)
        assert result["gen_ai.input.messages"] == "reach me at [EMAIL_REDACTED]"
        assert result["gen_ai.output.messages"] == "sure, [API_KEY_REDACTED] works"
        # An unrelated attribute is carried across unchanged.
        assert result["gen_ai.usage.input_tokens"] == 7

    def test_on_start_scrubs_a_recording_span_in_place(self):
        """At start the span is still recording, so a matching content attribute is
        overwritten through `set_attribute` rather than by replacing the store -
        which is what keeps Logfire's pending span, built right after, clean."""
        processor = _RedactingSpanProcessor()
        span = _FakeSpan(
            {
                "gen_ai.tool.call.arguments": '{"email":"planted@example.com"}',
                "gen_ai.tool.name": "lookup",
            }
        )

        processor.on_start(span)

        assert span.set_attribute_calls == {
            "gen_ai.tool.call.arguments": '{"email":"[EMAIL_REDACTED]"}'
        }
        # A non-content attribute is never touched.
        assert "gen_ai.tool.name" not in span.set_attribute_calls

    def test_on_start_leaves_a_span_without_content_untouched(self):
        """A model-request span carries no message content at start, and a span
        with no attributes at all must not raise."""
        processor = _RedactingSpanProcessor()

        empty = _FakeSpan(None)
        processor.on_start(empty)
        assert empty.set_attribute_calls == {}

        clean = _FakeSpan({"gen_ai.tool.call.arguments": '{"city":"Paris"}', "http.method": 1})
        processor.on_start(clean)
        assert clean.set_attribute_calls == {}


class _FakeSpan:
    """A stand-in for a `ReadableSpan`: `attributes` is what the processor reads,
    `_attributes` the backing store it writes at end. A `MappingProxyType` would
    refuse the write path a real span takes, so the two are kept as plain
    references. `set_attribute` records the overwrites `on_start` makes on a
    still-recording span."""

    def __init__(self, attributes: dict[str, object] | None) -> None:
        self.attributes = attributes
        self._attributes = attributes
        self.set_attribute_calls: dict[str, object] = {}

    def set_attribute(self, key: str, value: object) -> None:
        self.set_attribute_calls[key] = value
