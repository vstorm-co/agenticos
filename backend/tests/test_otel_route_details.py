"""Why a wrong-method request used to answer 500, and what stops it now.

`GET /api/v1/auth/login` - or any method a route does not declare - returned **500
Internal Server Error** on every route in this API. Not from our code: OpenTelemetry's
FastAPI instrumentation derives a span name by walking `app.routes`, and its
`Match.PARTIAL` branch reads `.path` unguarded. `Match.PARTIAL` *is* "the path
matches and the method does not", and FastAPI 0.141 puts `_IncludedRouter` objects in
that list, which carry no `.path`. The exception escaped in the ASGI middleware above
this app, so the caller got Starlette's plain-text `Internal Server Error` instead of
a refusal, and an unauthenticated caller could make the server log a traceback on any
path.

Two things are pinned here: the shim's own behaviour, and that the upstream defect is
still there - when it is fixed, the last test in this file fails and the module goes
away. What a client actually receives is `tests/api/test_method_not_allowed.py`.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import otel_compat


class TestTheWrapper:
    def test_it_answers_what_upstream_answers(self, monkeypatch):
        """A wrapper, not a fork: when upstream can name the route, that is the answer."""
        monkeypatch.setattr(
            otel_compat, "_upstream_route_details", lambda scope: "/api/v1/agents/{agent_id}"
        )

        assert (
            otel_compat.route_details({"path": "/api/v1/agents/x"}) == "/api/v1/agents/{agent_id}"
        )

    def test_a_route_object_with_no_path_falls_back_to_the_request_s_own(self, monkeypatch):
        """`scope["path"]` is the fallback upstream already uses in the branch it did
        guard, so this widens their handling rather than inventing a policy."""

        def raises(_scope: Any) -> Any:
            raise AttributeError("'_IncludedRouter' object has no attribute 'path'")

        monkeypatch.setattr(otel_compat, "_upstream_route_details", raises)

        assert otel_compat.route_details({"path": "/api/v1/auth/login"}) == "/api/v1/auth/login"

    def test_a_scope_with_no_path_is_still_answered(self, monkeypatch):
        def raises(_scope: Any) -> Any:
            raise AttributeError("no path")

        monkeypatch.setattr(otel_compat, "_upstream_route_details", raises)

        assert otel_compat.route_details({}) is None

    def test_anything_that_is_not_an_attribute_error_propagates(self, monkeypatch):
        """A span name is not worth swallowing an unrelated failure for."""

        def raises(_scope: Any) -> Any:
            raise RuntimeError("something else entirely")

        monkeypatch.setattr(otel_compat, "_upstream_route_details", raises)

        with pytest.raises(RuntimeError):
            otel_compat.route_details({"path": "/x"})


class TestInstallingIt:
    def test_it_replaces_the_helper_that_raises(self):
        import opentelemetry.instrumentation.fastapi as instrumentation

        otel_compat.patch_route_details()

        assert instrumentation._get_route_details.__module__ == otel_compat.__name__

    def test_patching_twice_does_not_wrap_the_wrapper(self):
        """The lifespan and the import-time test client both instrument, and a
        non-idempotent patch would nest one call per instrumentation."""
        import opentelemetry.instrumentation.fastapi as instrumentation

        otel_compat.patch_route_details()
        first = instrumentation._get_route_details
        otel_compat.patch_route_details()

        assert instrumentation._get_route_details is first


class TestTheRouteObjectThatHasNoPath:
    def test_a_405_still_matches_a_router_that_cannot_name_itself(self):
        """The mechanism, against the real app rather than a description of it.

        If FastAPI stops putting `_IncludedRouter` in `app.routes`, or gives it a
        `.path`, this fails and the shim is no longer load-bearing.
        """
        from starlette.routing import Match

        from app.main import create_app

        app = create_app()
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/login",
            "path_params": {},
            "app": app,
            "headers": [],
            "route_root_path": "",
        }

        partial_without_path = [
            route
            for route in app.routes
            if route.matches(scope)[0] == Match.PARTIAL and not hasattr(route, "path")
        ]

        assert partial_without_path, "nothing matches PARTIAL without a path any more"
