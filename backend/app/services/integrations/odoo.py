"""Odoo 19+ JSON-2, bounded to approved hosts and catalogued business models."""

import json
import re
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from app.core.config import settings
from app.core.exceptions import AuthorizationError, BadRequestError, ExternalServiceError
from app.core.odoo_credential import OdooCredential
from app.services.integrations.catalog import PRODUCTS, Operation

_JSON = TypeAdapter(JsonValue)
type RecordId = Annotated[int, Field(strict=True, gt=0)]

_FIELD = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[RecordId] = Field(min_length=1, max_length=100)


class _Read(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[RecordId] = Field(min_length=1, max_length=100)
    fields: list[str] = Field(default_factory=lambda: ["id", "display_name"], max_length=100)


class _Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: list[JsonValue] = Field(default_factory=list, max_length=100)
    fields: list[str] = Field(default_factory=lambda: ["id", "display_name"], max_length=100)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=100_000)
    order: str = Field(
        default="id asc",
        max_length=255,
        pattern=r"^[a-z_][a-z0-9_]*(?: (?:asc|desc))?(?:, ?[a-z_][a-z0-9_]*(?: (?:asc|desc))?)*$",
    )


class _Create(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: dict[str, JsonValue] = Field(min_length=1, max_length=100)


class _Write(_Create):
    ids: list[RecordId] = Field(min_length=1, max_length=100)


async def _request(
    credential: OdooCredential, model: str, method: str, body: dict[str, JsonValue]
) -> JsonValue:
    host = urlsplit(credential.origin).hostname
    if host is None or host.casefold() not in {
        item.casefold() for item in settings.ODOO_ALLOWED_HOSTS
    }:
        raise AuthorizationError(
            message="Add the Odoo hostname to ODOO_ALLOWED_HOSTS before connecting it"
        )
    try:
        encoded = json.dumps(body, allow_nan=False).encode()
    except ValueError:
        raise BadRequestError(message="Use finite JSON numbers in Odoo requests") from None
    if len(encoded) > 1_000_000:
        raise BadRequestError(message="The Odoo request is too large")
    try:
        async with (
            httpx.AsyncClient(timeout=20, follow_redirects=False) as client,
            client.stream(
                "POST",
                f"{credential.origin}/json/2/{model}/{method}",
                json=body,
                headers={
                    "Authorization": f"bearer {credential.api_key.get_secret_value()}",
                    "X-Odoo-Database": credential.database,
                    "Accept": "application/json",
                },
            ) as response,
        ):
            if not 200 <= response.status_code < 300:
                raise ExternalServiceError(
                    message="Odoo refused the operation; check the API key, database, installed module and access rights",
                    details={"status": response.status_code},
                )
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 2_000_000:
                    raise ExternalServiceError(
                        message="Narrow the Odoo request; the response is too large"
                    )
    except httpx.HTTPError:
        raise ExternalServiceError(
            message="Odoo could not be reached; a write may already have completed"
        ) from None
    try:
        return _JSON.validate_json(content)
    except ValidationError:
        raise ExternalServiceError(message="Odoo returned an unreadable response") from None


async def identify(credential: OdooCredential) -> None:
    result = await _request(credential, "res.users", "context_get", {})
    if not isinstance(result, dict) or not isinstance(result.get("uid"), int):
        raise ExternalServiceError(
            message="The Odoo endpoint did not return an authenticated user context"
        )


async def execute(
    credential: OdooCredential,
    operation: Operation,
    *,
    parameters: dict[str, str],
    query: dict[str, str],
    body: dict[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    """Run a catalogued method once; never replay a possibly committed write."""
    if (
        parameters
        or query
        or operation
        not in tuple(op for p in PRODUCTS.values() if p.provider == "odoo" for op in p.operations)
    ):
        raise BadRequestError(message="Use an operation from the Odoo integration catalog")
    parts = urlsplit(operation.url)
    model, method = parts.netloc, parts.path.removeprefix("/")
    values = (body or {}).get("values")
    invoice_kind = values.get("move_type") if isinstance(values, dict) else None
    if operation.id == "create_invoices" and (
        not isinstance(invoice_kind, str)
        or invoice_kind
        not in {"out_invoice", "in_invoice", "out_refund", "in_refund", "out_receipt", "in_receipt"}
    ):
        raise BadRequestError(
            message="Choose an invoice move_type: out_invoice, in_invoice, out_refund, in_refund, out_receipt or in_receipt"
        )
    if (
        model in {"sale.order", "account.move", "stock.picking", "stock.move"}
        and isinstance(values, dict)
        and "state" in values
    ):
        raise BadRequestError(message="Use the business action tool to change this record's state")
    return {"result": await _request(credential, model, method, _payload(method, body))}


def _relation_link(value: JsonValue) -> bool:
    if not isinstance(value, list) or not value or type(value[0]) is not int:
        return False
    command = value[0]
    if command == 5:
        return value in ([5], [5, 0, 0])
    if command == 4:
        return (
            len(value) in {2, 3}
            and type(value[1]) is int
            and value[1] > 0
            and (len(value) == 2 or value[2] == 0)
        )
    if command == 6:
        return (
            len(value) == 3
            and value[1] == 0
            and isinstance(value[2], list)
            and len(value[2]) <= 100
            and all(type(identifier) is int and identifier > 0 for identifier in value[2])
        )
    return False


def _business_value(value: JsonValue) -> bool:
    if isinstance(value, dict):
        return False
    if isinstance(value, list):
        return len(value) <= 100 and all(_relation_link(command) for command in value)
    return True


def _payload(method: str, body: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
    if method == "fields_get":
        if body:
            raise BadRequestError(message="Field inspection takes no arguments")
        return {"attributes": ["string", "type", "required", "readonly", "relation"]}
    try:
        schema = {
            "search_read": _Search,
            "read": _Read,
            "create": _Create,
            "write": _Write,
            "action_confirm": _Action,
            "action_post": _Action,
            "action_assign": _Action,
            "button_validate": _Action,
        }[method]
        data = schema.model_validate(body or {})
    except ValidationError:
        raise BadRequestError(message="Use the body documented by this Odoo operation") from None
    if isinstance(data, (_Read, _Search)) and any(
        not _FIELD.fullmatch(field) for field in data.fields
    ):
        raise BadRequestError(message="Use valid Odoo field names")
    if isinstance(data, _Create) and any(
        not _FIELD.fullmatch(field) or "." in field or field in {"id", "create_uid", "write_uid"}
        for field in data.values
    ):
        raise BadRequestError(message="Use writable Odoo business field names")
    if isinstance(data, _Create) and not all(
        _business_value(value) for value in data.values.values()
    ):
        raise BadRequestError(
            message="Use scalar business fields or link/set/clear relation IDs; create and update related records with their own named tools"
        )
    if isinstance(data, _Write):
        return {"ids": list(data.ids), "vals": data.values}
    if isinstance(data, _Create):
        return {"vals_list": [data.values]}
    return TypeAdapter(dict[str, JsonValue]).validate_json(data.model_dump_json())
