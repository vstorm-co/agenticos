"""What is asked of a human, and what they can answer.

Deliberately *outside* the capability that enforces them. These types are the
contract between four parties: the gate raises the question, a surface carries
it to a person, the approvals service records what they said, and
``AgentDeps`` carries the callback that joins them. Only one of those four is
the capability.

They lived in the gate's own module, which made ``app/agents/deps.py`` - the
module every capability imports - depend on a capability that imports it back.
The cycle survived only because the annotation hid behind ``TYPE_CHECKING`` and
a lazily-evaluated alias, with a comment apologising for it. Moving the types
down a layer, below both, removes the cycle rather than tiptoeing around it.

This module imports nothing from ``app``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApprovalRequest:
    """One tool call put to a human.

    Carries the tool call id because that is what identifies the parked call
    when the run is resumed - the tool name is not unique within a run, and the
    arguments are not either.
    """

    capability_id: str
    tool_name: str
    tool_call_id: str
    tool_args: dict[str, Any]


@dataclass(frozen=True)
class ApprovalGranted:
    """A human authorised the call, against these arguments."""

    tool_args: dict[str, Any]


@dataclass(frozen=True)
class ApprovalRejected:
    """A human refused the call."""

    note: str | None = None


@dataclass(frozen=True)
class ApprovalPending:
    """Nobody has decided yet, so the run cannot continue."""


# A union rather than one class with a status field: "granted without arguments"
# and "rejected with arguments" are states that should not be expressible.
ApprovalDecision = ApprovalGranted | ApprovalRejected | ApprovalPending


def refusal(tool_name: str, reason: str) -> str:
    """What the model reads when a gated call does not happen.

    Phrased as a final outcome rather than an error: a model that reads "failed"
    retries, and retrying a rejected side effect is how an agent sends the email
    a person just said no to.
    """
    return (
        f"'{tool_name}' was not performed: {reason}. "
        "This is final - do not call it again. "
        "Tell the user what you were about to do and that it needs a person to approve it."
    )
