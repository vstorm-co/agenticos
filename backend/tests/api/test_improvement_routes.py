"""Improvement routes preserve the actor, resource path and service refusals."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from pydantic import BaseModel

from app.api import deps
from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.services.improvement_pipeline import ImprovementPipelineService

pytestmark = pytest.mark.anyio

_AGENT, _RUN, _DATASET, _TOPIC, _CASE, _HUNK = (UUID(int=n) for n in range(1, 7))
_ROOT = f"/agents/{_AGENT}/improvements"
_ONE = f"{_ROOT}/{_RUN}"
_TARGET = {"dataset_id": str(_DATASET)}
_KNOWLEDGE = {"topic_id": str(_TOPIC), "round": 1, "case_ids": [str(_CASE)]}
_CONSENT = {"confirmed": True, "estimate_usd": "0.01"}
_HASH = "a" * 64


@pytest.mark.parametrize(
    ("method", "path", "operation", "body", "round_number"),
    [
        ("POST", f"{_ONE}/knowledge/estimate", "estimate_knowledge", _KNOWLEDGE, False),
        (
            "POST",
            f"{_ONE}/knowledge",
            "start_knowledge",
            {**_KNOWLEDGE, **_CONSENT, "draft_hash": _HASH},
            False,
        ),
        ("POST", f"{_ROOT}/estimate", "estimate", _TARGET, False),
        ("POST", _ROOT, "start", {**_TARGET, "budget_usd": "5"}, False),
        ("GET", _ROOT, "list_for_agent", None, False),
        ("GET", f"{_ROOT}/preview?dataset_id={_DATASET}", "evidence", None, False),
        ("GET", f"{_ONE}/evidence", "evidence", None, False),
        ("PUT", f"{_ONE}/evidence/{_CASE}", "decide_evidence", {"decision": "ignored"}, False),
        ("PUT", f"{_ONE}/topics/{_TOPIC}/later", "defer_topic", {"later": True}, False),
        ("GET", _ONE, "read", None, False),
        ("POST", f"{_ONE}/cancel", "cancel", None, False),
        (
            "POST",
            f"{_ONE}/rounds/1/selection/estimate",
            "estimate_selection",
            {"hunk_ids": [str(_HUNK)]},
            True,
        ),
        (
            "POST",
            f"{_ONE}/rounds/1/selection",
            "check_selection",
            {**_CONSENT, "hunk_ids": [str(_HUNK)], "candidate_hash": _HASH},
            True,
        ),
        ("POST", f"{_ONE}/rounds/1/select", "select_round", None, True),
        ("POST", f"{_ONE}/rounds/1/attribution/estimate", "estimate_attribution", None, True),
        ("POST", f"{_ONE}/rounds/1/attribution", "start_attribution", _CONSENT, True),
        ("POST", f"{_ONE}/retry", "retry", None, False),
        ("POST", f"{_ONE}/finish", "finish", {"confirmed": True}, False),
        ("POST", f"{_ONE}/continue/estimate", "estimate_continuation", {"budget_usd": "5"}, False),
        (
            "POST",
            f"{_ONE}/continue",
            "continue_run",
            {**_CONSENT, "budget_usd": "5", "candidate_hash": _HASH},
            False,
        ),
        ("POST", f"{_ONE}/discard", "discard", {"confirmed": True}, False),
    ],
)
async def test_service_refusals_keep_the_actor_and_frozen_resource_path(
    client: AsyncClient,
    mock_db_session: MagicMock,
    method: str,
    path: str,
    operation: str,
    body: dict[str, object] | None,
    round_number: bool,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.VIEWER)
    service = ImprovementPipelineService(mock_db_session)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    app.dependency_overrides[deps.get_improvement_service] = lambda: service
    refusal = AsyncMock(side_effect=NotFoundError(message="Pinned resource unavailable"))
    with patch.object(service, operation, refusal):
        response = await client.request(method, f"{settings.API_V1_STR}{path}", json=body)
    assert response.status_code == 404, response.text
    assert "Pinned resource unavailable" in response.text
    call = refusal.await_args
    assert call is not None and call.args[:2] == (ctx, _AGENT)
    if path.startswith(_ONE):
        if path.endswith("/evidence"):
            assert call.kwargs == {"run_id": _RUN}
        else:
            assert call.args[2] == _RUN
    if "/preview" in path:
        assert call.kwargs == {"dataset_id": _DATASET}
    if round_number:
        assert call.args[3] == 1
    if body is not None:
        payload = call.args[-1]
        assert isinstance(payload, BaseModel)
        supplied = payload.model_dump(mode="json", include=set(body))
        for key, value in body.items():
            assert supplied[key] == value


@pytest.mark.parametrize("target", [{}, {"dataset_id": str(_DATASET), "suite_id": str(uuid4())}])
async def test_an_ambiguous_question_source_is_rejected_before_the_service(
    client: AsyncClient, mock_db_session: MagicMock, target: dict[str, str]
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role=OrgRoleName.OWNER)
    app.dependency_overrides[deps.get_auth_context] = lambda: ctx
    service = ImprovementPipelineService(mock_db_session)
    app.dependency_overrides[deps.get_improvement_service] = lambda: service
    with patch.object(service, "estimate", AsyncMock()) as estimate:
        response = await client.post(f"{settings.API_V1_STR}{_ROOT}/estimate", json=target)
    assert response.status_code == 422
    assert "Choose one dataset or one suite" in response.text
    estimate.assert_not_awaited()
