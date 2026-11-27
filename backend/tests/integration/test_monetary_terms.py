"""Original budget terms and reporting snapshots survive real database writes."""

from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization, OrganizationMember
from app.schemas.organization import OrganizationUpdate
from app.services.currency import CurrencyService
from app.services.organization import OrganizationService
from tests.integration.test_profile_pricing import tenant

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def test_frozen_quote_and_original_limit_terms_are_not_revalued_by_rate_edits(
    db: AsyncSession,
) -> None:
    ctx = await tenant(db)
    assert ctx.user_id is not None
    db.add(
        OrganizationMember(organization_id=ctx.organization_id, user_id=ctx.user_id, role="owner")
    )
    deployment = DeploymentSettings(
        currency_settings={
            "default_currency": "PLN",
            "rates": {"USD": "1", "PLN": "4", "EUR": "0.9"},
        }
    )
    db.add(deployment)
    await db.flush()
    currencies = CurrencyService(db)
    assert await currencies.inherited_quotes() == 1
    service = OrganizationService(db)
    await service.update(
        ctx.organization_id,
        OrganizationUpdate(
            monthly_budget_usd="25",
            monetary_inputs={"monthly_budget_usd": {"amount": "100", "currency": "PLN"}},
        ),
        requester_id=ctx.user_id,
    )
    organization = await db.get(Organization, ctx.organization_id)
    assert organization is not None
    original = dict(organization.monetary_terms)
    assert original["monthly_budget_usd"]["currency"] == "PLN"
    deployment.currency_settings = {
        "default_currency": "PLN",
        "rates": {"USD": "1", "PLN": "9", "EUR": "0.5"},
    }
    await db.flush()
    assert await currencies.inherited_quotes() == 0
    assert (await currencies.context(ctx.organization_id)).reporting_units_per_usd == Decimal(4)
    await service.update(
        ctx.organization_id, OrganizationUpdate(name="Renamed"), requester_id=ctx.user_id
    )
    assert organization.monetary_terms == original
    await service.update(
        ctx.organization_id, OrganizationUpdate(currency="EUR"), requester_id=ctx.user_id
    )
    assert (await currencies.context(ctx.organization_id)).reporting_units_per_usd == Decimal("0.5")
    assert organization.monthly_budget_usd == Decimal(25)
    assert organization.monetary_terms == original
    # A legacy API edit remains USD, even with EUR selected for the UI.
    await service.update(
        ctx.organization_id, OrganizationUpdate(monthly_budget_usd="25"), requester_id=ctx.user_id
    )
    assert organization.monetary_terms["monthly_budget_usd"]["currency"] == "USD"


async def test_forged_or_unavailable_currency_input_cannot_change_the_existing_budget(
    db: AsyncSession,
) -> None:
    ctx = await tenant(db)
    assert ctx.user_id is not None
    db.add(
        OrganizationMember(organization_id=ctx.organization_id, user_id=ctx.user_id, role="owner")
    )
    org = await db.get(Organization, ctx.organization_id)
    assert org is not None
    org.monthly_budget_usd = Decimal(7)
    org.reporting_quote = {"currency": "PLN", "units_per_usd": "4"}
    db.add(DeploymentSettings(currency_settings={"rates": {"USD": "1", "PLN": "9"}}))
    await db.flush()
    service = OrganizationService(db)
    for field, amount, currency in [
        ("monthly_budget_usd", "100", "PLN"),
        ("monthly_budget_usd", "8", "EUR"),
        ("unowned_limit", "8", "USD"),
    ]:
        with pytest.raises(BadRequestError):
            await service.update(
                ctx.organization_id,
                OrganizationUpdate(
                    monthly_budget_usd="8",
                    monetary_inputs={field: {"amount": amount, "currency": currency}},
                ),
                requester_id=ctx.user_id,
            )
        assert org.monthly_budget_usd == Decimal(7)
    org.reporting_quote = {"currency": "PLN", "units_per_usd": None}
    await db.flush()
    with pytest.raises(BadRequestError):
        await service.update(
            ctx.organization_id,
            OrganizationUpdate(
                monthly_budget_usd="8",
                monetary_inputs={"monthly_budget_usd": {"amount": "32", "currency": "PLN"}},
            ),
            requester_id=ctx.user_id,
        )
    assert org.monthly_budget_usd == Decimal(7)


async def test_case_and_default_cost_thresholds_keep_units_through_edits_and_jsonl_import(
    db: AsyncSession,
) -> None:
    from app.schemas.dataset import DatasetCaseContent, DatasetCaseUpdate, DatasetCreate
    from app.schemas.scoring import DatasetScoringUpdate
    from app.services.dataset import DatasetService
    from app.services.scoring import ScoringService
    from tests.integration.test_dataset_versions import _owner

    ctx = await _owner(db)
    organization = await db.get(Organization, ctx.organization_id)
    assert organization is not None
    organization.reporting_quote = {"currency": "PLN", "units_per_usd": "4"}
    await db.flush()
    service = DatasetService(db)
    dataset = await service.create(ctx, DatasetCreate(name="Currency criteria"))
    first = await service.add_case(
        ctx,
        dataset.id,
        DatasetCaseContent(
            input="Question",
            checks=[
                {
                    "type": "max_cost_usd",
                    "value": 0.25,
                    "monetary_input": {"amount": "1", "currency": "PLN"},
                }
            ],
        ),
    )
    original = first.checks[0].model_dump(mode="json")
    assert original["monetary_term"]["currency"] == "PLN"
    assert "monetary_input" not in original
    organization.reporting_quote = {"currency": "EUR", "units_per_usd": "0.5"}
    await db.flush()
    edited = await service.update_case(
        ctx, dataset.id, first.case_id, DatasetCaseUpdate(note="Only the note")
    )
    assert edited.checks[0].model_dump(mode="json") == original
    copied = await service.create(ctx, DatasetCreate(name="Imported criteria"))
    portable = await service.export(ctx, dataset.id, version=None, fmt="jsonl")
    await service.import_cases(
        ctx, copied.id, content=portable.content.encode(), filename="criteria.jsonl", fmt="jsonl"
    )
    cases = await service.list_cases(ctx, copied.id)
    assert cases.items[0].checks[0].model_dump(mode="json") == original
    changed = await ScoringService(db).set_scoring(
        ctx,
        copied.id,
        DatasetScoringUpdate.model_validate(
            {
                "checks": {
                    "defaults": [
                        {
                            "type": "max_cost_usd",
                            "value": 0.25,
                            "monetary_input": {"amount": "0.125", "currency": "EUR"},
                        }
                    ]
                }
            }
        ),
    )
    assert changed.scoring.checks.defaults[0].monetary_term.currency == "EUR"
    assert changed.scoring.checks.defaults[0].monetary_input is None
