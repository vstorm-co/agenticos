"""Every path the frontend's BFF forwards to, against the route table it forwards to.

`frontend/src/app/api/**/route.ts` is hand-written, one file per proxied route,
and every one of them builds a `/api/v1/...` string by hand. Their own tests mock
`backendFetch`, so a mocked call cannot know whether the path it was handed
exists - which is how `/api/v1/admin/conversations/users` survived: no such route
was ever declared, the request matched `GET /admin/conversations/{conversation_id}`
instead, and the backend answered

    422 conversation_id: Input should be a valid UUID,
        invalid character: found `u` at 1

for every load of the admin conversations screen. The Owner filter was empty for
as long as it had existed.

A 404 is not the failure mode to look for, and that is the whole reason this file
is here rather than a `assert path in openapi["paths"]` somewhere: the broken path
*matched a route*. What it did not do is parse, because the segment it hard-codes
lands on a parameter the backend declares as a `UUID`. So the check runs the
literal through the very field FastAPI would validate it with.

It lives in the backend suite because this is where the route table is. The cost
is that `scripts/ci_changed_scope.py` can no longer call `frontend/**` irrelevant
to the backend job in full - `frontend/src/app/api/**` is the one path both halves
share, and it is exempted there for this test.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# `_compat` because that is where FastAPI keeps the field it validates a path
# parameter with; `Dependant.path_params` is a list of exactly these.
from fastapi._compat import ModelField
from fastapi.routing import APIRoute, iter_route_contexts

from app.main import app

BFF = Path(__file__).resolve().parents[3] / "frontend" / "src" / "app" / "api"

# What an interpolation in a forwarded template literal is replaced with. A
# single segment of anything, which is what `${id}` puts on the wire.
WILDCARD = "\x00"


def _literals(source: str) -> list[str]:
    """Every `/api/v1/...` string or template literal in one route handler.

    Interpolations collapse to :data:`WILDCARD`, nesting and all - a
    ``${qs ? `?${qs}` : ""}`` is one hole in the path, not three.
    """
    found = []
    for match in re.finditer(r"[`\"']/api/v1/", source):
        quote = source[match.start()]
        index, depth, out = match.start() + 1, 0, []
        while index < len(source):
            char = source[index]
            if depth:
                depth += {"{": 1, "}": -1}.get(char, 0)
                index += 1
                continue
            if char == quote:
                break
            if source.startswith("${", index):
                depth, index = 1, index + 2
                out.append(WILDCARD)
                continue
            out.append(char)
            index += 1
        found.append("".join(out))
    return found


def _requested_path(literal: str) -> str:
    """The path a literal addresses: no query string, `{}` for each parameter."""
    path = literal.split("?")[0].replace(WILDCARD, "{}")
    # A trailing interpolation that is not a segment of its own is the optional
    # query string - `${qs ? `?${qs}` : ""}` - rather than a path parameter.
    return path[:-2] if path.endswith("{}") and not path.endswith("/{}") else path


def _forwarded() -> dict[str, set[str]]:
    """Each distinct path the BFF forwards to, and the handlers that forward it."""
    assert BFF.is_dir(), f"the frontend's BFF is not where this test looks for it: {BFF}"
    paths: dict[str, set[str]] = {}
    for file in sorted(BFF.rglob("route.ts")):
        for literal in _literals(file.read_text()):
            paths.setdefault(_requested_path(literal), set()).add(
                str(file.relative_to(BFF.parents[3]))
            )
    return paths


def _routes() -> list[tuple[str, dict[str, ModelField]]]:
    """Every API route, in the order Starlette will try to match them.

    Order matters and sorting would hide the bug: `/me/slash-commands/builtin` is
    only reachable because it is declared before `/me/slash-commands/{command_id}`.
    """
    routes: list[tuple[str, dict[str, ModelField]]] = []
    seen = set()
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if not isinstance(route, APIRoute) or context.path in seen:
            continue
        seen.add(context.path)
        routes.append((context.path, {field.name: field for field in route.dependant.path_params}))
    return routes


def _match(requested: str) -> tuple[str, dict[str, ModelField]] | None:
    """The first declared route that would take this request, or nothing."""
    probe = requested.replace("{}", "\x01")
    for path, params in _routes():
        pattern = re.escape(path)
        for name in params:
            pattern = pattern.replace(re.escape("{" + name + "}"), "[^/]+")
        if re.fullmatch(pattern, probe):
            return path, params
    return None


FORWARDED = sorted(_forwarded().items())


@pytest.mark.parametrize(("requested", "handlers"), FORWARDED, ids=[path for path, _ in FORWARDED])
def test_a_forwarded_path_reaches_a_route_that_can_answer_it(
    requested: str, handlers: set[str]
) -> None:
    """A BFF handler forwards to a route that exists and parses what it hard-codes.

    Both halves are the same defect seen from either end: a path with no route
    behind it answers 404, and a path whose literal segment lands on a typed
    parameter answers 422. Neither is visible to a test that mocks the fetch.
    """
    where = ", ".join(sorted(handlers))
    matched = _match(requested)
    assert matched is not None, f"{where} forwards to {requested}, which no route declares"

    path, params = matched
    for mine, theirs in zip(requested.split("/"), path.split("/"), strict=True):
        if mine == "{}" or not (theirs.startswith("{") and theirs.endswith("}")):
            continue
        field = params[theirs[1:-1]]
        # The backend's own field, so this asks the question the request will:
        # `list_users` accepts `users` for a `str` parameter and refuses it for
        # a `UUID` one, and nothing here has to know which is which.
        _, errors = field.validate(mine, {}, loc=("path", theirs[1:-1]))
        assert not errors, (
            f"{where} forwards to {requested}, which matches {path} - "
            f"and {theirs} cannot parse '{mine}', so the request answers 422"
        )
