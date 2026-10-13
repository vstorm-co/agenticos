"""Approval capability - hold a side-effecting tool call until a human answers.

The decision types live in :mod:`app.agents.approval`, a layer below: they are
the contract between the gate, the surfaces and the approvals service, and only
one of those is this capability. Re-exported here so callers that think in
capabilities have one import.
"""

from app.agents.approval import (
    ApprovalDecision,
    ApprovalGranted,
    ApprovalMode,
    ApprovalPending,
    ApprovalRejected,
    ApprovalRequest,
    refusal,
)
from app.agents.capabilities.approval._capability import ApprovalGate
from app.agents.capabilities.approval._policy import (
    approval_required_tools,
    refuse_ungateable_approvals,
    tool_needs_approval,
    ungateable_tool_problems,
)

__all__ = [
    "ApprovalDecision",
    "ApprovalGate",
    "ApprovalGranted",
    "ApprovalMode",
    "ApprovalPending",
    "ApprovalRejected",
    "ApprovalRequest",
    "approval_required_tools",
    "refusal",
    "refuse_ungateable_approvals",
    "tool_needs_approval",
    "ungateable_tool_problems",
]
