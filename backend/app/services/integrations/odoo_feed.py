"""Independent Odoo write-date cursors; a new source establishes a quiet baseline."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.odoo_credential import OdooCredential
from app.services.integrations.catalog import ODOO_MODELS, PRODUCTS
from app.services.integrations.feeds import Change, Changes
from app.services.integrations.odoo import execute


class _Position(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    id: int = Field(ge=0)

    @field_validator("stamp")
    @classmethod
    def _valid_date(cls, value: str) -> str:
        datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return value


def _position(record: dict[str, JsonValue]) -> _Position:
    try:
        return _Position.model_validate({"stamp": record.get("write_date"), "id": record.get("id")})
    except ValidationError:
        raise ExternalServiceError(
            message="Odoo returned an invalid record change position"
        ) from None


async def changes(
    credential: OdooCredential, product_id: str, cursor: dict[str, JsonValue] | None
) -> Changes:
    if product_id not in ODOO_MODELS:
        raise BadRequestError(message="Choose an Odoo business area for this change feed")
    if cursor is not None and cursor.get("product_id") != product_id:
        raise BadRequestError(message="This Odoo cursor belongs to another business area")
    positions = cursor.get("models") if cursor else {}
    if not isinstance(positions, dict):
        raise BadRequestError(message="The Odoo change cursor is invalid")
    state: dict[str, JsonValue] = {}
    events: list[Change] = []
    for noun, model in ODOO_MODELS[product_id]:
        previous = positions.get(model)
        try:
            old = _Position.model_validate(previous) if previous is not None else None
        except ValidationError:
            raise BadRequestError(message="The Odoo change cursor is invalid") from None
        domain: list[JsonValue] = []
        if old is not None:
            domain = [
                "|",
                ["write_date", ">", old.stamp],
                "&",
                ["write_date", "=", old.stamp],
                ["id", ">", old.id],
            ]
        operation = next(op for op in PRODUCTS[product_id].operations if op.id == f"search_{noun}")
        result = await execute(
            credential,
            operation,
            parameters={},
            query={},
            body={
                "domain": domain,
                "fields": ["id", "display_name", "write_date"],
                "order": "write_date asc,id asc" if old else "write_date desc,id desc",
                "limit": 100 if old else 1,
            },
        )
        rows = result.get("result")
        if not isinstance(rows, list):
            raise ExternalServiceError(message="Odoo returned an invalid change feed")
        last = old or _Position(stamp="1970-01-01 00:00:00", id=0)
        for row in rows:
            if not isinstance(row, dict):
                raise ExternalServiceError(message="Odoo returned an invalid changed record")
            position = _position(row)
            if old is not None:
                if (position.stamp, position.id) <= (last.stamp, last.id):
                    raise ExternalServiceError(message="Odoo returned an unordered change feed")
                events.append(
                    Change(
                        id=f"odoo:{model}:{position.id}:{position.stamp}",
                        payload={"product_id": product_id, "model": model, "record": row},
                    )
                )
            last = position
        state[model] = {"stamp": last.stamp, "id": last.id}
    return Changes(events=events, cursor={"product_id": product_id, "models": state})
