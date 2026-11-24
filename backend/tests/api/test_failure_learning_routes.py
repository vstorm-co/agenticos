"""The failure-learning routes, through the app: the wire contract.

The service is stood in for - what it does is proven in
`tests/test_failure_learning.py`. What is left is the handler itself:
status codes, the `RUNS_VIEW` gate on the org-wide list, the rate-limit
dep on the try route, and the error envelope a client branches on.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.api import deps
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.permissions import AuthContext
from app.main import app
from app.schemas.failure_learning import (
    EvalCaseList,
    EvalCaseRead,
    EvalTryRead,
    FailurePatternList,
    LedgerEntryList,
    LedgerEntryRead,
    ProposalList,
    ProposalRead,
)
from app.services.rate_limit import Decision

pytestmark = pytest.mark.anyio

_NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
_ORG = uuid4()


def _auth(role: str) -> AuthContext:
    return AuthContext(user_id=uuid4(), organization_id=_ORG, role=role)


def _service() -> MagicMock:
    service = MagicMock()
    service.list_org_patterns = AsyncMock(
        return_value=FailurePatternList(items=[], total=0, notes=[])
    )
    service.list_agent_patterns = AsyncMock(
        return_value=FailurePatternList(items=[], total=0, notes=[])
    )
    service.list_ledger = AsyncMock(return_value=LedgerEntryList(items=[], total=0))
    service.create_ledger = AsyncMock(
        return_value=LedgerEntryRead(
            id=uuid4(),
            organization_id=_ORG,
            agent_id=None,
            scope="agent",
            pattern_key="failed:ModelHTTPError:400",
            title="400s",
            summary="Keeps failing.",
            evidence={},
            status="draft",
            created_at=_NOW,
            updated_at=None,
        )
    )
    service.get_ledger = AsyncMock(
        return_value=LedgerEntryRead(
            id=uuid4(),
            organization_id=_ORG,
            agent_id=None,
            scope="agent",
            pattern_key="failed:ModelHTTPError:400",
            title="400s",
            summary="Keeps failing.",
            evidence={},
            status="draft",
            created_at=_NOW,
            updated_at=None,
        )
    )
    service.update_ledger = AsyncMock(
        return_value=LedgerEntryRead(
            id=uuid4(),
            organization_id=_ORG,
            agent_id=None,
            scope="agent",
            pattern_key="failed:ModelHTTPError:400",
            title="400s",
            summary="Keeps failing.",
            evidence={},
            status="open",
            created_at=_NOW,
            updated_at=None,
        )
    )
    service.delete_ledger = AsyncMock()
    service.list_cases = AsyncMock(return_value=EvalCaseList(items=[], total=0))
    service.create_case = AsyncMock(
        return_value=EvalCaseRead(
            id=uuid4(),
            agent_id=uuid4(),
            name="Refund loop",
            position=1,
            input={"message": "Refund me"},
            expectation={"kind": "not_contains", "field": "text", "value": "draft"},
            created_at=_NOW,
            updated_at=None,
        )
    )
    service.delete_case = AsyncMock()
    service.start_try = AsyncMock(
        return_value=EvalTryRead(
            id=uuid4(),
            agent_id=uuid4(),
            cases=[],
            passed=0,
            failed=0,
            pending=0,
            created_at=_NOW,
        )
    )
    service.get_try = AsyncMock(
        return_value=EvalTryRead(
            id=uuid4(),
            agent_id=uuid4(),
            cases=[],
            passed=0,
            failed=0,
            pending=0,
            created_at=_NOW,
        )
    )
    service.list_proposals = AsyncMock(return_value=ProposalList(items=[], total=0))
    service.create_proposal = AsyncMock(
        return_value=ProposalRead(
            id=uuid4(),
            organization_id=_ORG,
            agent_id=uuid4(),
            target_type="instructions",
            old_text="Draft a PR.",
            new_text="Never draft a PR.",
            rationale="The agent drafts when told to publish.",
            status="draft",
            eval_gated=True,
            created_at=_NOW,
            updated_at=None,
        )
    )
    service.get_proposal = AsyncMock(
        return_value=ProposalRead(
            id=uuid4(),
            organization_id=_ORG,
            agent_id=uuid4(),
            target_type="instructions",
            old_text="Draft a PR.",
            new_text="Never draft a PR.",
            rationale="The agent drafts when told to publish.",
            status="draft",
            eval_gated=True,
            created_at=_NOW,
            updated_at=None,
        )
    )
    service.reject_proposal = AsyncMock(
        return_value=ProposalRead(
            id=uuid4(),
            organization_id=_ORG,
            agent_id=uuid4(),
            target_type="instructions",
            old_text="Draft a PR.",
            new_text="Never draft a PR.",
            rationale="The agent drafts when told to publish.",
            status="rejected",
            eval_gated=True,
            created_at=_NOW,
            updated_at=None,
        )
    )
    service.apply_proposal = AsyncMock(
        return_value=ProposalRead(
            id=uuid4(),
            organization_id=_ORG,
            agent_id=uuid4(),
            target_type="instructions",
            old_text="Draft a PR.",
            new_text="Never draft a PR.",
            rationale="The agent drafts when told to publish.",
            status="applied",
            applied_version_id=uuid4(),
            eval_gated=True,
            created_at=_NOW,
            updated_at=None,
        )
    )
    return service


def _override(role: str = "owner") -> MagicMock:
    app.dependency_overrides[deps.get_auth_context] = lambda: _auth(role)
    service = _service()
    app.dependency_overrides[deps.get_failure_learning_service] = lambda: service
    return service


async def test_the_org_patterns_list_reaches_the_service(client: AsyncClient):
    service = _override()
    response = await client.get(
        "/api/v1/failure-learning/patterns?from=2026-11-03&to=2026-11-10&min_count=5"
    )

    assert response.status_code == 200
    assert response.json()["total"] == 0
    call = service.list_org_patterns.await_args
    assert call.kwargs["min_count"] == 5
    assert str(call.kwargs["from_date"]) == "2026-11-03"


async def test_a_member_without_runs_view_is_refused_the_org_list(client: AsyncClient):
    _override(role="member")
    response = await client.get("/api/v1/failure-learning/patterns")

    assert response.status_code == 403


async def test_the_per_agent_routes_reach_the_service(client: AsyncClient):
    service = _override()
    agent_id, entry_id, case_id, try_id, proposal_id = (uuid4() for _ in range(5))
    base = f"/api/v1/agents/{agent_id}/failure-learning"
    case = {
        "name": "Refund loop",
        "input": {"message": "Refund me"},
        "expectation": {"kind": "not_contains", "field": "text", "value": "draft"},
    }
    entry = {
        "scope": "agent",
        "pattern_key": "failed:ModelHTTPError:400",
        "title": "400s",
        "summary": "Keeps failing.",
    }
    proposal = {
        "target": {"type": "instructions"},
        "old_text": "Draft a PR.",
        "new_text": "Never draft a PR.",
        "rationale": "The agent drafts when told to publish.",
    }

    listed = await client.get(f"{base}/patterns")
    entries = await client.get(f"{base}/ledger")
    created_entry = await client.post(f"{base}/ledger", json=entry)
    read_entry = await client.get(f"{base}/ledger/{entry_id}")
    updated_entry = await client.patch(f"{base}/ledger/{entry_id}", json={"status": "open"})
    deleted_entry = await client.delete(f"{base}/ledger/{entry_id}")
    cases = await client.get(f"{base}/eval-cases")
    created_case = await client.post(f"{base}/eval-cases", json=case)
    deleted_case = await client.delete(f"{base}/eval-cases/{case_id}")
    started = await client.post(
        f"{base}/eval-runs",
        json={"case_ids": [str(case_id)], "instructions_override": "Never draft."},
    )
    read_try = await client.get(f"{base}/eval-runs/{try_id}")
    proposals = await client.get(f"{base}/proposals")
    created_proposal = await client.post(f"{base}/proposals", json=proposal)
    read_proposal = await client.get(f"{base}/proposals/{proposal_id}")
    applied_proposal = await client.post(f"{base}/proposals/{proposal_id}/apply")
    rejected_proposal = await client.post(
        f"{base}/proposals/{proposal_id}/reject", json={"reason": "Too broad."}
    )

    assert (listed.status_code, entries.status_code) == (200, 200)
    assert (created_entry.status_code, read_entry.status_code) == (201, 200)
    assert (updated_entry.status_code, deleted_entry.status_code) == (200, 204)
    assert (cases.status_code, created_case.status_code) == (200, 201)
    assert (deleted_case.status_code, started.status_code) == (204, 201)
    assert read_try.status_code == 200
    assert (proposals.status_code, created_proposal.status_code) == (200, 201)
    assert (read_proposal.status_code, rejected_proposal.status_code) == (200, 200)
    assert applied_proposal.status_code == 200
    assert service.list_agent_patterns.await_args.args[1] == agent_id
    assert service.create_ledger.await_args.args[1] == agent_id
    assert service.get_ledger.await_args.args[1:] == (agent_id, entry_id)
    assert service.delete_ledger.await_args.args[1:] == (agent_id, entry_id)
    assert service.create_case.await_args.args[1] == agent_id
    assert service.delete_case.await_args.args[1:] == (agent_id, case_id)
    assert service.start_try.await_args.args[1] == agent_id
    assert service.get_try.await_args.args[1:] == (agent_id, try_id)
    assert service.create_proposal.await_args.args[1] == agent_id
    assert service.get_proposal.await_args.args[1:] == (agent_id, proposal_id)
    assert service.apply_proposal.await_args.args[1:] == (agent_id, proposal_id)
    assert service.reject_proposal.await_args.args[1:3] == (agent_id, proposal_id)


async def test_a_try_over_the_rate_limit_is_refused_as_a_429(client: AsyncClient):
    service = _override()
    agent_id = uuid4()
    consume = AsyncMock(return_value=Decision(allowed=False, retry_after_seconds=60))
    with patch("app.api.deps.rate_limit.consume", consume):
        response = await client.post(
            f"/api/v1/agents/{agent_id}/failure-learning/eval-runs",
            json={"case_ids": [str(uuid4())], "instructions_override": "Never draft."},
        )

    assert response.status_code == 429
    service.start_try.assert_not_awaited()


async def test_a_missing_agent_reads_as_not_found(client: AsyncClient):
    service = _override()
    service.list_agent_patterns = AsyncMock(
        side_effect=NotFoundError(message="Agent not found", details={"agent_id": "x"})
    )
    response = await client.get(f"/api/v1/agents/{uuid4()}/failure-learning/patterns")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_a_try_with_too_many_samples_is_refused_as_a_422(client: AsyncClient):
    _override()
    response = await client.post(
        f"/api/v1/agents/{uuid4()}/failure-learning/eval-runs",
        json={"case_ids": [str(uuid4())], "instructions_override": "Never draft.", "samples": 6},
    )

    assert response.status_code == 422


async def test_a_try_naming_a_decided_proposal_is_refused_by_the_service(
    client: AsyncClient,
):
    service = _override()
    service.start_try = AsyncMock(
        side_effect=BadRequestError(message="Only a draft proposal can be tried")
    )
    response = await client.post(
        f"/api/v1/agents/{uuid4()}/failure-learning/eval-runs",
        json={"case_ids": [str(uuid4())], "proposal_id": str(uuid4())},
    )

    assert response.status_code == 400


@pytest.mark.parametrize("changed_since_apply", [False, True])
async def test_skill_rollback_returns_the_restore_record_or_the_services_conflict(
    client: AsyncClient, changed_since_apply: bool
) -> None:
    service = _override()
    agent_id, proposal_id, skill_id = uuid4(), uuid4(), uuid4()
    restored = ProposalRead(
        id=proposal_id,
        organization_id=_ORG,
        agent_id=agent_id,
        target_type="skill",
        skill_id=skill_id,
        old_text="Original procedure.",
        new_text="Reviewed procedure.",
        rationale="An operator approved the change.",
        status="applied",
        eval_gated=True,
        created_at=_NOW,
        reverted_at=_NOW,
        rollback_available=False,
    )
    service.revert_proposal = AsyncMock(
        return_value=restored,
        side_effect=ConflictError(message="The skill changed after this proposal applied")
        if changed_since_apply
        else None,
    )

    response = await client.post(
        f"/api/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}/revert"
    )

    service.revert_proposal.assert_awaited_once()
    assert service.revert_proposal.await_args.args[1:] == (agent_id, proposal_id)
    if changed_since_apply:
        assert response.status_code == 409
        assert "changed" in response.json()["error"]["message"]
    else:
        assert response.status_code == 200
        assert response.json() == restored.model_dump(mode="json")
