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
from pydantic_ai import Agent as PydanticAgent

logger = logging.getLogger(__name__)

_instances: dict[tuple[str, str, str], logfire.Logfire] = {}


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
