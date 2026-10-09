"""Which routes form the public API - the ones an organization key may call (#150).

The public API is the same `/api/v1` the console uses, so the line between "a
contract an integrator may build on" and "a route the console happens to call" is
drawn here, not by a second set of routes. A module's router built with
`APIRouter(dependencies=[PUBLIC])` is public; one of its routes opts back out
with `openapi_extra=INTERNAL`. Keys are refused everywhere else, before they are
looked up.

A dependency rather than a tag, because it is copied onto every route the moment
the route is declared - so the route object a request matched answers the
question itself, wherever and however its router was included.
"""

from typing import Any

from fastapi import Depends
from starlette.routing import BaseRoute


def public_api() -> None:
    """Marks a router's routes as part of the public API. Does nothing at runtime."""


PUBLIC = Depends(public_api)
"""Put in a module router's `dependencies` to make its routes public."""

INTERNAL: dict[str, Any] = {"x-agenticos-internal": True}
"""`openapi_extra` for a route in a public router that is not part of the contract."""


def is_public_route(route: BaseRoute | None) -> bool:
    """Whether an organization key may call this route."""
    if route is None:
        return False
    extra = getattr(route, "openapi_extra", None) or {}
    if extra.get("x-agenticos-internal", False):
        return False
    return any(
        getattr(dependency, "dependency", None) is public_api
        for dependency in getattr(route, "dependencies", None) or []
    )
