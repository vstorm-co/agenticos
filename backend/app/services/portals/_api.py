"""One authenticated GET against a provider's JSON API, for the polled portals.

The file and calendar adapters each read Google's or Microsoft's API the way the
mail adapters do, and fail the way `poll_grant` already recovers from: anything
non-2xx, or a 2xx that is not JSON, is a `PortalUnreachable` carrying the status
and the provider's machine-readable error codes - and never the provider's own
words, which can echo the request and the request carries a bearer token.
"""

from collections.abc import Mapping
from typing import Any

import httpx

from app.services.portals.exceptions import PortalUnreachable

TIMEOUT = httpx.Timeout(15.0)


async def get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    access_token: str,
    params: Mapping[str, str] | None,
    service: str,
    portal_key: str,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The JSON object at `url`, or an empty one for a body that is not an object.

    `service` names the API in the refusal - "Google Drive", "Microsoft Graph" -
    so a poll failure in the log says which provider it was.

    Raises:
        PortalUnreachable: The provider could not be reached, refused the
            request (with `status` and any error `codes` in its details), or
            answered with something that is not JSON.
    """
    try:
        response = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                **(headers or {}),
            },
            params=params,
        )
    except httpx.HTTPError as exc:
        raise PortalUnreachable(
            message=f"{service} could not be reached",
            details={"portal_key": portal_key, "error": exc.__class__.__name__},
        ) from exc
    if response.status_code >= 400:
        details: dict[str, Any] = {"portal_key": portal_key, "status": response.status_code}
        codes = error_codes(response)
        if codes:
            details["codes"] = codes
        raise PortalUnreachable(message=f"{service} refused the request", details=details)
    try:
        parsed = response.json()
    except ValueError as exc:
        raise PortalUnreachable(
            message=f"{service} answered with something unreadable",
            details={"portal_key": portal_key},
        ) from exc
    return parsed if isinstance(parsed, dict) else {}


def nested(value: Any, key: str) -> dict[str, Any]:
    """One nested object of a provider's answer, or an empty one.

    Not `value.get(key, {})`: JSON says `"owner": null` as readily as it omits
    the field, and a raise out of a poll aborts the read of every place in it.
    """
    found = value.get(key) if isinstance(value, dict) else None
    return found if isinstance(found, dict) else {}


def error_codes(response: httpx.Response) -> list[str]:
    """The error codes in a refusal, case-folded, outermost first.

    Graph nests them (`error.code`, then each `innerError.code`), Google puts a
    status beside its numeric code (`error.status`). Only the codes: the message
    beside them can echo the request and is no part of either contract.
    """
    try:
        body = response.json()
    except ValueError:
        return []
    error = body.get("error") if isinstance(body, dict) else None
    codes: list[str] = []
    while isinstance(error, dict):
        for key in ("code", "status"):
            if isinstance(error.get(key), str):
                codes.append(error[key].casefold())
        error = error.get("innerError") or error.get("innererror")
    return codes
