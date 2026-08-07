"""Every mounted route gets a session that commits before the response is sent.

The ordering itself is proved against a real database in
`tests/integration/test_commit_before_response.py`. This file guards the wiring
that ordering depends on, because the wiring is one keyword argument on one
`Depends` and losing it is silent: the suite stays green, every route keeps
answering 2xx, and the only symptom is that a client acting on its own 2xx is
sometimes answered from a database the write has not reached (#353).

A new route reintroduces the defect by asking for a session any way other than
through `DBSession` - a bare `Depends(get_db_session)`, or a new alias that
forgets the scope. That is what this walks the routing table for.
"""

from collections.abc import Callable, Iterator
from typing import Protocol

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute, APIWebSocketRoute

from app.db.session import get_db_session
from app.main import app

# Endpoints allowed a `scope="request"` session, and the reason each one is.
# A body produced while the response is being sent needs the session to outlive
# the response start; the price is that its transaction resolves after the
# client has been answered, so an endpoint may only be added here if it writes
# nothing. See `app.api.deps.StreamingDBSession`.
_STREAMING_ENDPOINTS = {
    # Pages through the ratings table as it writes CSV rows.
    ("GET", "/api/v1/admin/ratings/export"),
}

# What `test_the_walk_reached_the_routing_table` insists on finding. Well under
# the ~200 session-taking endpoints mounted today, so ordinary growth and
# ordinary deletion both leave it alone; it exists to fail when the walk itself
# stops working rather than to count routes.
_A_ROUTING_TABLE = 100


class _MountedEndpoint(Protocol):
    """One endpoint as FastAPI's router resolves it, with its path already joined.

    Structural, because the class behind it is `fastapi.routing.
    _EffectiveRouteContext` and private. `dependant` is optional: a plain
    Starlette route mounted on the router - a redirect, a static mount - has no
    dependency tree.
    """

    path: str
    methods: set[str] | None
    dependant: Dependant | None


# How a mounted `include_router` hands over its routes. Since FastAPI 0.141
# `app.routes` no longer holds a flat list of `APIRoute`: `include_router` leaves
# one `_IncludedRouter` behind and the routes hang off it, reachable only through
# this method. Unversioned surface, so the walk below is written to notice when
# it stops answering rather than to quietly return nothing - which is what
# `_A_ROUTING_TABLE` is for.
_RouteGroup = Callable[[], Iterator[_MountedEndpoint]]


def _every_dependant(dependant: Dependant) -> Iterator[Dependant]:
    yield dependant
    for sub_dependant in dependant.dependencies:
        yield from _every_dependant(sub_dependant)


def _session_scopes(dependant: Dependant) -> list[str | None]:
    return [sub.scope for sub in _every_dependant(dependant) if sub.call is get_db_session]


def _endpoints() -> Iterator[tuple[str, str, Dependant]]:
    """Every mounted endpoint as (method, full path, its dependency tree)."""
    for route in app.routes:
        group: _RouteGroup | None = getattr(route, "effective_route_contexts", None)
        if group is not None:
            for endpoint in group():
                if endpoint.dependant is None:
                    continue
                for method in sorted(endpoint.methods or ["WEBSOCKET"]):
                    yield method, endpoint.path, endpoint.dependant
        elif isinstance(route, APIRoute):
            for method in sorted(route.methods):
                yield method, route.path, route.dependant
        elif isinstance(route, APIWebSocketRoute):
            yield "WEBSOCKET", route.path, route.dependant


def test_every_route_commits_its_transaction_before_answering() -> None:
    """No route may take a session whose commit lands after the response."""
    late = [
        (method, path)
        for method, path, dependant in _endpoints()
        for scope in _session_scopes(dependant)
        if scope != "function" and (method, path) not in _STREAMING_ENDPOINTS
    ]
    assert not late, (
        "these routes hold a session whose transaction resolves after the response "
        "has been sent, so a 2xx from them does not mean the write is readable "
        f"(#353). Depend on `app.api.deps.DBSession`: {late}"
    )


def test_the_streaming_session_is_confined_to_the_endpoints_that_declare_it() -> None:
    """A request-scoped session is an exception, and the list of them is closed.

    Without this, `StreamingDBSession` is a way to opt out of the fix that costs
    one import and explains itself to nobody.
    """
    streaming = {
        (method, path)
        for method, path, dependant in _endpoints()
        for scope in _session_scopes(dependant)
        if scope == "request"
    }
    assert streaming == _STREAMING_ENDPOINTS, (
        "an endpoint took a request-scoped session without being listed in "
        "_STREAMING_ENDPOINTS, or one listed there no longer takes one. A body "
        "produced after the response starts is the only reason to have one, and "
        "it may not write."
    )


def test_the_walk_reached_the_routing_table() -> None:
    """The two assertions above pass vacuously if the walk finds nothing.

    They did, the first time this file was written: `app.routes` holds one
    `_IncludedRouter` rather than 264 `APIRoute`s, so a walk that only knew
    about `APIRoute` reported a clean routing table it had never looked at.
    """
    with_a_session = [
        (method, path) for method, path, dependant in _endpoints() if _session_scopes(dependant)
    ]
    assert len(with_a_session) > _A_ROUTING_TABLE, (
        "the walk found almost no endpoint holding a database session, which "
        "means FastAPI changed how a mounted router exposes its routes and the "
        f"two assertions above stopped checking anything: {len(with_a_session)}"
    )
