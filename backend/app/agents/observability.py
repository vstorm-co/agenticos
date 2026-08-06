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

The other half of this module is the *return* trip: recording where a run's
trace went, so somebody reading run history can open it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import logfire
from opentelemetry import trace
from pydantic_ai import Agent as PydanticAgent

from app.core.config import settings

if TYPE_CHECKING:
    from app.agents.spec import AgentSpec

logger = logging.getLogger(__name__)

_instances: dict[tuple[str, str, str], logfire.Logfire] = {}


@dataclass(frozen=True)
class TraceLocation:
    """Where one run's trace went, as far as this process can know.

    Both halves are needed to open it and neither implies the other: an id
    without a project is a trace nobody can find, and a project without an id is
    a link to a search. Stored together on the run for the same reason `provider`
    and `model_label` are - they record where the run *actually* went, and
    re-deriving them later would relabel history the day a setting changes.
    """

    trace_id: str | None
    project: str | None


def trace_location(spec: AgentSpec) -> TraceLocation:
    """The trace id and project to record for a run of this spec.

    **The id is `None` unless the trace is actually going somewhere.** Spans
    exist whether or not Logfire has a token - `send_to_logfire="if-token-present"`
    builds them locally and drops them - so an id read off the span is a
    syntactically valid identifier that resolves to nothing on a deployment with
    no Logfire at all. That is the same lie as the `null` column this replaces,
    written the other way round.

    The project follows **the token**, never the other way about. An agent whose
    spec or environment redirects its traces exports them to that token's
    project, so falling back to the deployment's slug there would build a link
    into a project the trace never reached. A redirected agent whose spec names
    no project therefore gets no project - the id is still recorded, and whoever
    holds that token can find it.

    Four outcomes, and each is somebody's real deployment: an agent redirected to
    a client's project, an agent tracing to the operator's, a deployment with a
    token and no slug configured (id, no link), and a deployment with no Logfire
    at all (neither).
    """
    observability = spec.observability
    if observability is not None and observability.token_secret_id is not None:
        return TraceLocation(trace_id=current_trace_id(), project=observability.project)
    if not settings.LOGFIRE_TOKEN:
        return TraceLocation(trace_id=None, project=None)
    return TraceLocation(trace_id=current_trace_id(), project=settings.LOGFIRE_PROJECT)


def current_trace_id() -> str | None:
    """The trace this code is running inside, as 32 hex characters, or `None`.

    Taken from the active OpenTelemetry span rather than through a Logfire API,
    because the id a Logfire URL wants is the OTel trace id and Logfire is one of
    several things that may have started it.

    `None` where there is no span at all - a CLI command, a test, a worker path
    nothing instruments. OpenTelemetry answers those with an invalid context
    whose trace id is zero, and `"000...0"` in the column would be an id that
    resolves to nothing.
    """
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")


def instrument_agent(
    agent: PydanticAgent[Any, Any],
    *,
    token: str,
    service_name: str,
    environment: str | None,
) -> bool:
    """Point one agent's traces at the Logfire project the token belongs to.

    Returns whether instrumentation was attached. A failure is reported and
    swallowed: an agent that cannot export traces still answers questions, and
    refusing to build it would turn an observability misconfiguration into an
    outage.
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
        instance.instrument_pydantic_ai(agent)
    except Exception:
        logger.exception("agent_logfire_instrument_failed", extra={"service_name": service_name})
        return False
    return True
