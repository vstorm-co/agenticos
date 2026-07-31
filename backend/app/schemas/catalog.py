"""What the deployment catalog exposes over the API."""

from app.schemas.base import BaseSchema


class CatalogIconList(BaseSchema):
    """The custom brand marks this deployment ships, by name."""

    items: list[str]
    total: int
