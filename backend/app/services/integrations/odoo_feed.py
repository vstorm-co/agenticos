"""Odoo write-date feeds retain a deduplicated overlap at the timestamp boundary."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.odoo_credential import OdooCredential
from app.services.integrations.catalog import ODOO_MODELS, PRODUCTS, Operation
from app.services.integrations.feeds import Change, Changes
from app.services.integrations.odoo import execute

_MAX_BOUNDARY = 2000


class _Position(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    stamp: str = Field(pattern=r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
    id: int = Field(ge=0)
    seen: (
        dict[
            Annotated[str, Field(pattern=r"^[1-9][0-9]*$")],
            Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")],
        ]
        | None
    ) = Field(default=None, max_length=_MAX_BOUNDARY)

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


def _marker(record: dict[str, JsonValue]) -> str:
    return hashlib.sha256(
        json.dumps(record, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()


async def _rows(
    credential: OdooCredential,
    operation: Operation,
    *,
    domain: list[JsonValue],
    limit: int,
    order: str,
) -> list[dict[str, JsonValue]]:
    result = await execute(
        credential,
        operation,
        parameters={},
        query={},
        body={
            "domain": domain,
            "fields": ["id", "display_name", "write_date"],
            "order": order,
            "limit": limit,
        },
    )
    values = result.get("result")
    if not isinstance(values, list) or len(values) > limit:
        raise ExternalServiceError(message="Odoo returned an invalid change feed")
    rows: list[dict[str, JsonValue]] = []
    for row in values:
        if not isinstance(row, dict):
            raise ExternalServiceError(message="Odoo returned an invalid changed record")
        _position(row)
        rows.append(row)
    return rows


async def _boundary(
    credential: OdooCredential, operation: Operation, stamp: str
) -> list[dict[str, JsonValue]]:
    rows: list[dict[str, JsonValue]] = []
    last_id = 0
    while True:
        page = await _rows(
            credential,
            operation,
            domain=[["write_date", "=", stamp], ["id", ">", last_id]],
            limit=100,
            order="id asc",
        )
        for row in page:
            position = _position(row)
            if position.stamp != stamp or position.id <= last_id:
                raise ExternalServiceError(message="Odoo returned an unordered change feed")
            last_id = position.id
        rows.extend(page)
        if len(rows) > _MAX_BOUNDARY:
            raise ExternalServiceError(
                message="Too many Odoo records share one change timestamp; split bulk updates into smaller batches"
            )
        if len(page) < 100:
            return rows


def _event(product_id: str, model: str, row: dict[str, JsonValue], marker: str) -> Change:
    position = _position(row)
    return Change(
        id=f"odoo:{model}:{position.id}:{position.stamp}:{marker}",
        payload={"product_id": product_id, "model": model, "record": row},
    )


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
        operation = next(op for op in PRODUCTS[product_id].operations if op.id == f"search_{noun}")
        if old is None:
            latest = await _rows(
                credential, operation, domain=[], limit=1, order="write_date desc,id desc"
            )
            last = _position(latest[0]) if latest else _Position(stamp="1970-01-01 00:00:00", id=0)
            snapshot = await _boundary(credential, operation, last.stamp) if latest else []
            seen = {str(_position(row).id): _marker(row) for row in snapshot}
        else:
            snapshot = await _boundary(credential, operation, old.stamp)
            seen = {
                str(_position(row).id): old.seen[str(_position(row).id)]
                for row in snapshot
                if old.seen is not None and str(_position(row).id) in old.seen
            }
            last = old
            emitted = 0
            for row in snapshot:
                position, marker = _position(row), _marker(row)
                identifier = str(position.id)
                if old.seen is None and position.id <= old.id:
                    # Older stored cursors had no snapshot; upgrade without replaying their baseline.
                    seen[identifier] = marker
                elif seen.get(identifier) != marker and emitted < 100:
                    events.append(_event(product_id, model, row, marker))
                    seen[identifier] = marker
                    emitted += 1
            if emitted < 100:
                newer = await _rows(
                    credential,
                    operation,
                    domain=[["write_date", ">", old.stamp]],
                    limit=100 - emitted,
                    order="write_date asc,id asc",
                )
                for row in newer:
                    position = _position(row)
                    if position.stamp <= old.stamp or (position.stamp, position.id) <= (
                        last.stamp,
                        last.id,
                    ):
                        raise ExternalServiceError(message="Odoo returned an unordered change feed")
                    if position.stamp != last.stamp:
                        seen = {}
                    marker = _marker(row)
                    seen[str(position.id)] = marker
                    events.append(_event(product_id, model, row, marker))
                    last = position
        state[model] = {"stamp": last.stamp, "id": last.id, "seen": dict(seen)}
    return Changes(events=events, cursor={"product_id": product_id, "models": state})
