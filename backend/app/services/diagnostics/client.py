"""Bounded, best-effort collector transport; never forwards session credentials."""

from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.schemas.diagnostics import ProtocolModel

type Delivery = Literal["sent", "transport", "rejected"]


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    accepted: Literal[True]
    duplicate: bool = False


async def deliver(client: httpx.AsyncClient, endpoint: str, event: ProtocolModel) -> Delivery:
    try:
        async with client.stream("POST", endpoint, json=event.model_dump(mode="json")) as response:
            if response.status_code != 200:
                return "rejected"
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 4096:
                    return "rejected"
            Receipt.model_validate_json(bytes(body))
    except httpx.HTTPError:
        return "transport"
    except ValidationError:
        return "rejected"
    return "sent"
