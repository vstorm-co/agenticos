"""An organization's effective reporting currency and available manual rates."""

from decimal import Decimal

from app.core.currency import CurrencyCode
from app.schemas.base import BaseSchema


class CurrencyContext(BaseSchema):
    currency: CurrencyCode
    default_currency: CurrencyCode
    inherited: bool
    rates: dict[str, Decimal]
