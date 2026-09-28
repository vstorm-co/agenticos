"""The workflow admission quota: bound queued/running node work per org and caller.

What is defended: a start reserves its graph's node count against the
organization's ceiling first and the caller's second, the reservation is what
makes a wide graph cost more than a narrow one, the boundary is inclusive
(outstanding + requested may equal the ceiling but not exceed it), and a start
with no principal is bounded by the organization alone.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import settings
from app.services.workflow_execution.admission import enforce_admission_quota
from app.services.workflow_execution.exceptions import WorkflowAdmissionQuotaError

MODULE = "app.services.workflow_execution.admission"

pytestmark = pytest.mark.anyio

_ORG = uuid.uuid4()
_PRINCIPAL = uuid.uuid4()


def _counts(*, org: int, principal: int = 0) -> AsyncMock:
    """A `count_active_node_runs` that answers per-org then per-principal.

    The quota calls it with no `principal_user_id` first (the org count) and
    with one second (the caller count), so the two return values arrive in that
    order.
    """
    return AsyncMock(side_effect=[org, principal])


async def test_a_start_within_both_ceilings_is_admitted():
    with patch(f"{MODULE}.workflow_run_repo.count_active_node_runs", _counts(org=10, principal=5)):
        await enforce_admission_quota(
            AsyncMock(),
            organization_id=_ORG,
            principal_user_id=_PRINCIPAL,
            requested_node_count=3,
        )


async def test_the_boundary_is_inclusive():
    # outstanding + requested == ceiling is allowed; only strictly over is refused.
    org_ceiling = settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_ORG
    principal_ceiling = settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_PRINCIPAL
    with patch(
        f"{MODULE}.workflow_run_repo.count_active_node_runs",
        _counts(org=org_ceiling - 4, principal=principal_ceiling - 4),
    ):
        await enforce_admission_quota(
            AsyncMock(),
            organization_id=_ORG,
            principal_user_id=_PRINCIPAL,
            requested_node_count=4,
        )


async def test_a_start_over_the_org_ceiling_is_refused_before_the_caller_is_counted():
    count = _counts(org=settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_ORG)
    with (
        patch(f"{MODULE}.workflow_run_repo.count_active_node_runs", count),
        pytest.raises(WorkflowAdmissionQuotaError) as refused,
    ):
        await enforce_admission_quota(
            AsyncMock(),
            organization_id=_ORG,
            principal_user_id=_PRINCIPAL,
            requested_node_count=1,
        )
    assert refused.value.details["scope"] == "organization"
    assert refused.value.status_code == 429
    # The caller count is never reached once the org ceiling refuses.
    assert count.await_count == 1


async def test_a_start_over_the_caller_ceiling_is_refused():
    with (
        patch(
            f"{MODULE}.workflow_run_repo.count_active_node_runs",
            _counts(org=0, principal=settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_PRINCIPAL),
        ),
        pytest.raises(WorkflowAdmissionQuotaError) as refused,
    ):
        await enforce_admission_quota(
            AsyncMock(),
            organization_id=_ORG,
            principal_user_id=_PRINCIPAL,
            requested_node_count=1,
        )
    assert refused.value.details["scope"] == "principal"
    assert refused.value.details["requested"] == 1


async def test_the_graph_node_count_is_reserved_not_just_one():
    # A wide graph is refused even when a single node would fit: the whole graph
    # is charged, which is the point of charging by node work rather than starts.
    org_ceiling = settings.WORKFLOW_MAX_ACTIVE_NODE_RUNS_PER_ORG
    with (
        patch(f"{MODULE}.workflow_run_repo.count_active_node_runs", _counts(org=org_ceiling - 1)),
        pytest.raises(WorkflowAdmissionQuotaError),
    ):
        await enforce_admission_quota(
            AsyncMock(),
            organization_id=_ORG,
            principal_user_id=_PRINCIPAL,
            requested_node_count=2,
        )


async def test_a_start_with_no_principal_is_bounded_by_the_org_alone():
    count = _counts(org=0)
    with patch(f"{MODULE}.workflow_run_repo.count_active_node_runs", count):
        await enforce_admission_quota(
            AsyncMock(),
            organization_id=_ORG,
            principal_user_id=None,
            requested_node_count=1,
        )
    # Only the org count runs; there is no caller to count.
    assert count.await_count == 1
