"""Resolve deployment defaults and tenant overrides without changing old money."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.currency import CurrencySettings
from app.core.exceptions import NotFoundError
from app.db.models.deployment_settings import DeploymentSettings
from app.repositories import deployment_settings_repo, organization_repo
from app.schemas.currency import CurrencyContext
from app.schemas.token_pricing import TokenPricing


class CurrencyService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def settings(self) -> CurrencySettings:
        return self.effective(await deployment_settings_repo.get(self.db))

    @staticmethod
    def effective(row: DeploymentSettings | None) -> CurrencySettings:
        if row is not None and row.currency_settings is not None:
            return CurrencySettings.model_validate(row.currency_settings)
        return CurrencyService.environment()

    @staticmethod
    def environment() -> CurrencySettings:
        return CurrencySettings(
            default_currency=settings.DEFAULT_ORG_CURRENCY, rates=settings.CURRENCY_RATES
        )

    async def rates_for(
        self, pricing: TokenPricing | None, *, include_provider_rates: bool = False
    ) -> dict[str, Decimal]:
        """Snapshot rates for custom pricing and any independently billed currency."""
        if not include_provider_rates and (pricing is None or pricing.currency == "USD"):
            return {"USD": Decimal(1)}
        return dict((await self.settings()).rates)

    async def context(self, organization_id: UUID) -> CurrencyContext:
        organization = await organization_repo.get_by_id(self.db, organization_id)
        if organization is None:
            raise NotFoundError(
                message="Organization not found", details={"organization_id": organization_id}
            )
        deployment = await self.settings()
        return CurrencyContext(
            currency=organization.currency or deployment.default_currency,
            default_currency=deployment.default_currency,
            inherited=organization.currency is None,
            rates=dict(deployment.rates),
        )
