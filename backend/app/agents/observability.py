"""Sending one agent's traces to a Logfire project of its own.

The deployment configures Logfire once at startup and everything goes there.
That is right for the operator and wrong for the case this exists for: an agent
built for a client, whose runs belong in the client's project - with the
client's retention, the client's alerting, and nobody else's traffic in it.

`logfire.configure(local=True)` returns an instance that is not the global one,
and `instrument_pydantic_ai(agent)` attaches it to a single agent. Instances are
cached per (token, service, environment) because configuring one starts an
exporter and a background flush thread: doing that per run would leak a thread
per conversation, and the symptom - a process that slowly stops responding - is
a long way from the code that caused it.

The token is unsealed from the vault by the caller and passed in. Nothing here
reads a secret, logs one, or puts one in a span attribute.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import logfire
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from pydantic_ai import Agent as PydanticAgent

from app.core.logging import PiiRedactionFilter

if TYPE_CHECKING:
    from opentelemetry.context import Context

    from app.agents.spec import TraceContent

logger = logging.getLogger(__name__)

# Keyed on (token, service, environment, redact): a redacted run needs its own
# Logfire instance because the scrubbing rides on that instance's tracer
# provider, and a `full` or `none` agent sharing the (token, service,
# environment) triple must not have its content scrubbed with it. `full` and
# `none` still share one instance and differ only by the per-agent
# `include_content` flag.
_instances: dict[tuple[str, str, str, bool], logfire.Logfire] = {}


class _RedactingSpanProcessor(SpanProcessor):
    """Scrub message content out of a span before it is exported to Logfire.

    The `redacted` trace-content mode records content and then removes the PII
    from it, rather than dropping content wholesale the way `none` does. Pydantic
    AI writes the message text, the model's output and every tool argument and
    result into the span attributes below; this runs each through the same filter
    the log pipeline uses (`PiiRedactionFilter`).

    Scrubbing happens at **both** ends of a span's life. Most content is written
    when the model responds and is caught at `on_end`. But a tool span carries
    `gen_ai.tool.call.arguments` from the moment it starts, and Logfire emits a
    *pending* span from those start-time attributes to show the call in flight -
    so an `on_end`-only scrub would let a tool argument's PII reach Logfire in the
    pending span before the run finished. `on_start` scrubs the live span first,
    ahead of Logfire's own pending-span processor (this processor is registered
    before it), so the pending export is already clean.

    `_CONTENT_ATTRIBUTES` is the fragile seam: the names are the ones Pydantic AI's
    instrumentation emits at its pinned version, and a release that renames one
    would silently start exporting the raw content again. `tests/test_agent_observability.py`
    feeds a real run through this processor - final spans and pending ones - and
    asserts a planted email and token are gone, so such a rename fails the build
    rather than leaking.
    """

    # Version 5 of Pydantic AI's instrumentation (the current default) carries a
    # run's content in these attributes: the input/output messages and system
    # instructions on model-request spans, the tool call arguments and result on
    # tool spans, and the whole history on the agent-run span.
    _CONTENT_ATTRIBUTES = (
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "pydantic_ai.all_messages",
    )

    def __init__(self) -> None:
        self._filter = PiiRedactionFilter()

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        """Scrub the content a span carries at start, before its pending export.

        The span is still recording, so each attribute is overwritten in place
        through the public API - which Logfire's pending-span processor, running
        after this one, then reads in its scrubbed form.
        """
        del parent_context  # part of the SpanProcessor.on_start signature; unused here
        attributes = span.attributes
        if not attributes:
            return
        for name in self._CONTENT_ATTRIBUTES:
            value = attributes.get(name)
            if isinstance(value, str):
                scrubbed = self._filter.redact(value)
                if scrubbed != value:
                    span.set_attribute(name, scrubbed)

    def on_end(self, span: ReadableSpan) -> None:
        """Replace each content attribute with its scrubbed form as the span ends.

        A finished span's attributes are a read-only mapping and its backing store
        refuses in-place assignment, so a changed set is written back as a fresh
        mapping - the same object Logfire's exporter reads later, since the batch
        processor only holds a reference to it.
        """
        attributes = span.attributes
        if not attributes:
            return
        redacted: dict[str, Any] | None = None
        for name in self._CONTENT_ATTRIBUTES:
            value = attributes.get(name)
            if not isinstance(value, str):
                continue
            scrubbed = self._filter.redact(value)
            if scrubbed != value:
                if redacted is None:
                    redacted = dict(attributes)
                redacted[name] = scrubbed
        if redacted is not None:
            span._attributes = redacted


# What OpenTelemetry answers when nothing is tracing: a span whose context is all
# zeroes. Formatting it would store `000…0` as a trace id and every link built
# from it would resolve to nothing, which is worse than an empty column.
_NO_TRACE = 0


def current_trace_id() -> str | None:
    """The trace this run is executing inside, as Logfire spells it.

    Read here rather than passed in by each surface, for the reason
    `PreparedRun.stash` gives about the run's budget caps: a thing every caller
    has to remember is a thing the next caller will not. `finish()` accepted a
    `logfire_trace_id` from the day the column existed and **no caller ever
    passed one**, so the write was guarded by a condition that was always false
    and the field the public API documents as a deep link was always null.

    32 lowercase hex characters, which is the W3C trace-id format and what
    Logfire puts in a URL. `None` when nothing is tracing - a deployment with no
    `LOGFIRE_TOKEN`, or a unit test - because a column of zeroes is a link that
    resolves to nothing.
    """
    context = trace.get_current_span().get_span_context()
    if context.trace_id == _NO_TRACE:
        return None
    return format(context.trace_id, "032x")


def instrument_agent(
    agent: PydanticAgent[Any, Any],
    *,
    token: str,
    service_name: str,
    environment: str | None,
    content: TraceContent = "full",
) -> bool:
    """Point one agent's traces at the Logfire project the token belongs to.

    Returns whether instrumentation was attached. A failure is reported and
    swallowed: an agent that cannot export traces still answers questions, and
    refusing to build it would turn an observability misconfiguration into an
    outage.

    `content` is the spec's trace-content mode. `none` records spans with timing,
    tokens, cost and tool names but no message text or tool arguments, so a run
    over protected data leaves no copy of it in the Logfire project. `redacted`
    keeps the content but scrubs its PII on the way out, through a span processor
    on this instance's tracer provider. The difference `include_content` cannot
    express - a bool on `instrument_pydantic_ai` - is why the processor exists.

    A redacted run needs its own Logfire instance: the scrubbing rides on the
    instance's tracer provider, so it is keyed apart from the `full`/`none`
    instance for the same (token, service, environment) triple, which would
    otherwise scrub their content too.
    """
    redact = content == "redacted"
    key = (token, service_name, environment or "", redact)
    instance = _instances.get(key)
    if instance is None:
        try:
            instance = logfire.configure(
                local=True,
                token=token,
                service_name=service_name,
                environment=environment or "",
                send_to_logfire=True,
                console=False,
                additional_span_processors=[_RedactingSpanProcessor()] if redact else None,
            )
        except Exception:
            logger.exception("agent_logfire_configure_failed", extra={"service_name": service_name})
            return False
        _instances[key] = instance

    try:
        instance.instrument_pydantic_ai(agent, include_content=content != "none")
    except Exception:
        logger.exception("agent_logfire_instrument_failed", extra={"service_name": service_name})
        return False
    return True


def suppress_content(agent: PydanticAgent[Any, Any]) -> None:
    """Trace this agent to the deployment's own project, but without its content.

    The deployment enables Pydantic AI instrumentation globally at startup
    (`app/main.py`), content on by default, so an agent that asked for
    `content="none"` but has no per-agent exporter - no token, an environment that
    carries the token instead, or a token that has gone missing since publish -
    would otherwise fall back to that global default and export its prompts and
    tool arguments to the operator's project. Pinning the agent to a content-free
    instrumentation on the same default tracer keeps the timing, tokens and cost
    and drops the content, so `none` holds wherever the run's spans land. Swallows
    a failure for the same reason `instrument_agent` does: an agent that cannot be
    instrumented still answers.
    """
    try:
        logfire.instrument_pydantic_ai(agent, include_content=False)
    except Exception:
        logger.exception("agent_content_suppress_failed")
