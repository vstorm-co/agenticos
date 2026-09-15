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
