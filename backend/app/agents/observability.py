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
from typing import Any

import logfire
from opentelemetry import trace
from pydantic_ai import Agent as PydanticAgent
from pydantic_ai.models import AbstractModel, Model
from pydantic_ai.models.instrumented import InstrumentationSettings, instrument_model
from pydantic_ai.tools import RunContext

logger = logging.getLogger(__name__)

_instances: dict[tuple[str, str, str], logfire.Logfire] = {}

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
    include_content: bool = True,
) -> bool:
    """Point one agent's traces at the Logfire project the token belongs to.

    Returns whether instrumentation was attached. A failure is reported and
    swallowed: an agent that cannot export traces still answers questions, and
    refusing to build it would turn an observability misconfiguration into an
    outage.

    `include_content` is the spec's `content` mode made concrete: `False` (the
    spec's `none`) records spans with timing, tokens, cost and tool names but no
    message text or tool arguments, so a run over protected data leaves no copy
    of it in the Logfire project. It is applied on the per-agent
    `instrument_pydantic_ai` call rather than on the cached instance, because the
    instance is shared across agents keyed on (token, service, environment) and
    the content decision is one agent's.
    """
    key = (token, service_name, environment or "")
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
            )
        except Exception:
            logger.exception("agent_logfire_configure_failed", extra={"service_name": service_name})
            return False
        _instances[key] = instance

    try:
        instance.instrument_pydantic_ai(agent, include_content=include_content)
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


def inherited_instrumentation(
    host: PydanticAgent[Any, Any] | None,
) -> InstrumentationSettings | bool | None:
    """The trace policy for an auxiliary agent a tool runs inside `host`'s run.

    A tool that makes its own model call through a fresh `Agent` - query
    expansion, for one - would otherwise take the deployment's global
    instrumentation, content on, whatever the host was set to: the prompt it
    builds from the caller's question would reach the operator's project past an
    agent whose spec says `content: none`, or miss the client project its traces
    are routed to. Passing the host's own setting keeps both the destination and
    the content decision `_instrument` made for it; `None` there means the global
    default, the same as the host gets.

    With no host to read (`RunContext.agent` unset) the policy is unknown, so the
    answer is the one that cannot leak: the default tracer, without content.
    """
    if host is None:
        return InstrumentationSettings(include_content=False)
    return host.instrument


def auxiliary_model(ctx: RunContext[Any]) -> AbstractModel:
    """The run's model for an auxiliary call, traced the way the run is.

    A capability that writes through an `Agent` it builds itself - a system
    reminder, a compaction summary - inherits the run's model. `ctx.model` is the
    bare model (the run's own instrumentation is a capability on the host, not a
    wrapper on the model), so an agent built on it falls back to the deployment's
    global instrumentation: content on and the operator's project, whatever the
    host was set to. An agent published with `content="none"` would leak the
    auxiliary call's text (agenticos#1809), and an agent whose traces go to a
    client's project would send that text to the operator's instead.

    So the model is wrapped in the host's own policy, read by
    :func:`inherited_instrumentation`: an `InstrumentedModel` passed to an `Agent`
    wins over its instrumentation settings, which is what makes this reach even
    an agent a library builds from nothing but the model. A host on the global
    default gets the model unchanged - the auxiliary agent takes the same default.
    A realtime model (not a request-response :class:`Model`) is returned unchanged
    too, since it cannot be wrapped and does not run an auxiliary agent.
    """
    settings = inherited_instrumentation(ctx.agent)
    if not isinstance(settings, InstrumentationSettings) or not isinstance(ctx.model, Model):
        return ctx.model
    return instrument_model(ctx.model, settings)
