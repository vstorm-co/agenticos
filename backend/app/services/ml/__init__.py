"""The standalone ML service surface: the facade, and the coverage matrix behind it."""

from app.services.ml.catalog import SERVICE_CATALOG, DeliveryState, MLServiceEntry
from app.services.ml.facade import MLService

__all__ = ["SERVICE_CATALOG", "DeliveryState", "MLService", "MLServiceEntry"]
