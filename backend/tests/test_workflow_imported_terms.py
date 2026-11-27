"""Importing workflow settings preserves verified frozen quotes, not a new exchange rate."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.db.models.workflow import Workflow
from app.schemas.workflow import WorkflowSettings
from app.services.workflow_registry import WorkflowRegistryService
from tests.test_workflow_registry_service import _ctx, _db, _workflow

pytestmark = [pytest.mark.anyio, pytest.mark.security]

TERM = {"amount": "100", "currency": "PLN", "units_per_usd": "4", "cost_usd": "25.000000"}


@pytest.mark.parametrize("field,amount", [("run_budget_usd", 25), ("monthly_budget_usd", 25)])
async def test_import_preserves_original_valid_currency_terms(field: str, amount: float) -> None:
    ctx = _ctx()
    workflow = _workflow(ctx)
    data = WorkflowSettings.model_validate({field: amount, "monetary_terms": {field: TERM}})

    async def save(
        db: AsyncSession, *, workflow: Workflow, update_data: dict[str, JsonValue]
    ) -> Workflow:
        stored = update_data["settings"]
        assert isinstance(stored, dict)
        workflow.settings = stored
        return workflow

    with (
        patch("app.services.workflow_registry.hold_subject", AsyncMock()),
        patch(
            "app.services.workflow_registry.workflow_repo.get_for_update",
            AsyncMock(return_value=workflow),
        ),
        patch("app.services.workflow_registry.workflow_repo.update", AsyncMock(side_effect=save)),
        patch("app.services.workflow_registry.record_audit", AsyncMock()),
        patch(
            "app.services.workflow_registry.WorkflowTriggerSync.states", AsyncMock(return_value={})
        ),
        patch(
            "app.services.monetary.CurrencyService.context",
            AsyncMock(side_effect=AssertionError("Do not reprice a frozen import")),
        ),
    ):
        result = await WorkflowRegistryService(_db()).update_settings(
            ctx, workflow.id, data, preserve_monetary_terms=True
        )
    assert result.settings.monetary_terms == {field: TERM}
    assert workflow.settings["monetary_terms"] == {field: TERM}


@pytest.mark.parametrize(
    "terms,amount",
    [
        ({"not_a_budget": TERM}, 25),
        ({"run_budget_usd": TERM}, 24),
        ({"run_budget_usd": TERM}, None),
    ],
)
async def test_unknown_or_mismatched_imported_terms_are_refused_before_write(
    terms: dict[str, JsonValue], amount: float | None
) -> None:
    ctx = _ctx()
    workflow = _workflow(ctx)
    with (
        patch("app.services.workflow_registry.hold_subject", AsyncMock()),
        patch(
            "app.services.workflow_registry.workflow_repo.get_for_update",
            AsyncMock(return_value=workflow),
        ),
        patch("app.services.workflow_registry.workflow_repo.update", AsyncMock()) as write,
        pytest.raises(BadRequestError),
    ):
        await WorkflowRegistryService(_db()).update_settings(
            ctx,
            workflow.id,
            WorkflowSettings(run_budget_usd=amount, monetary_terms=terms),
            preserve_monetary_terms=True,
        )
    write.assert_not_awaited()
