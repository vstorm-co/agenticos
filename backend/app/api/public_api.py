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


PUBLIC_OPENAPI_PATH = "/public/openapi.json"
"""Where the public API's own document is served, under the API prefix."""

STABILITY = """\
The routes in this document are AgenticOS's public API: what an organization API
key may call, and what an integration may build on.

**Authentication.** Send an organization API key as `Authorization: Bearer aos_…`.
A key acts in its own organization, as the member who issued it, narrowed to the
permissions it was issued with and to that member's current role.

**Compatibility within v1.** A change to a route listed here is additive: a new
route, a new optional request field, a new response field, a new enum value. A
client must ignore response fields it does not know. Removing or renaming a field
or a route, or making an optional field required, only happens after it has been
marked `deprecated` here for at least 90 days and listed in the release notes.
A change that cannot be made that way goes into `/api/v2`, beside v1.

**Errors.** Every refusal answers the same envelope - `ErrorEnvelope` below - with
a stable `code`. `details.fields` names the request fields a 400 or 422 refused.
"""

_ERRORS = {
    "400": "The request was understood and refused - `details` says why.",
    "401": "No credential, or an invalid, expired or revoked API key.",
    "403": "The key or its issuer lacks the permission this route needs.",
    "404": "Not found, or not visible to this caller - the two are one answer.",
    "422": "The request body or parameters failed validation; `details.fields` names them.",
    "429": "Rate limited. `Retry-After` says when to try again.",
}

_ERROR_ENVELOPE: dict[str, Any] = {
    "title": "ErrorEnvelope",
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {"type": "string", "examples": ["NOT_FOUND"]},
                "message": {"type": "string"},
                "details": {"type": "object", "additionalProperties": True},
            },
        }
    },
}

_METHODS = ("get", "put", "post", "delete", "patch")


def _references(node: object, found: set[str]) -> None:
    """Every component schema name `node` refers to, at any depth."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            found.add(ref.removeprefix("#/components/schemas/"))
        for value in node.values():
            _references(value, found)
    elif isinstance(node, list):
        for value in node:
            _references(value, found)


def public_operations(routes: list[BaseRoute]) -> set[tuple[str, str]]:
    """`(method, full path)` for every public operation the app serves.

    Walks included routers through their effective contexts: since FastAPI 0.141
    `app.routes` holds one wrapper per `include_router` rather than the routes.
    """
    found: set[tuple[str, str]] = set()
    for entry in routes:
        contexts = getattr(entry, "effective_route_contexts", None)
        pairs = (
            [(context.original_route, context.path_format) for context in contexts()]
            if contexts is not None
            else [(entry, getattr(entry, "path_format", None))]
        )
        for route, path in pairs:
            if path is None or not is_public_route(route):
                continue
            for method in getattr(route, "methods", None) or ():
                found.add((method.lower(), path))
    return found


def public_openapi(full: dict[str, Any], public: set[tuple[str, str]]) -> dict[str, Any]:
    """The public API's document: `full` narrowed to `public`, and made true to it.

    Only public operations are kept, and only the component schemas they reach.
    Every operation is marked as needing a key and as answering the error
    envelope the API actually returns - FastAPI's default 422 schema describes a
    body this API never sends.
    """
    paths: dict[str, Any] = {}
    for path, operations in full.get("paths", {}).items():
        kept = {
            method: dict(operation)
            for method, operation in operations.items()
            if method in _METHODS and (method, path) in public
        }
        for operation in kept.values():
            responses = {
                code: answer
                for code, answer in operation.get("responses", {}).items()
                if code != "422"
            }
            for code, description in _ERRORS.items():
                responses.setdefault(
                    code,
                    {
                        "description": description,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ErrorEnvelope"}
                            }
                        },
                    },
                )
            operation["responses"] = responses
            operation["security"] = [{"ApiKey": []}]
        if kept:
            paths[path] = kept

    schemas: dict[str, Any] = full.get("components", {}).get("schemas", {})
    reached: set[str] = set()
    pending: set[str] = set()
    _references(paths, pending)
    while pending:
        name = pending.pop()
        if name in reached or name not in schemas:
            continue
        reached.add(name)
        _references(schemas[name], pending)

    return {
        "openapi": full.get("openapi", "3.1.0"),
        "info": {**full.get("info", {}), "description": STABILITY},
        "paths": paths,
        "components": {
            "schemas": {
                **{name: schemas[name] for name in sorted(reached)},
                "ErrorEnvelope": _ERROR_ENVELOPE,
            },
            "securitySchemes": {
                "ApiKey": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "An organization API key, `aos_…`.",
                }
            },
        },
    }
