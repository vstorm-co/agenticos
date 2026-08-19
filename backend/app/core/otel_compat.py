"""Making OpenTelemetry's FastAPI instrumentation survive a 405.

Every request to an existing path with a method it does not declare answered
**500** instead of 405, on every route in this API, and the cause is one
unguarded attribute in a dependency:

```python
# opentelemetry/instrumentation/fastapi/__init__.py, _get_route_details
if match == Match.FULL:
    try:
        route = starlette_route.path
    except AttributeError:
        route = scope.get("path")     # guarded
    break
if match == Match.PARTIAL:
    route = starlette_route.path      # not guarded
```

`Match.PARTIAL` is precisely "the path matches and the method does not", which is
what a 405 is. FastAPI 0.141 puts `_IncludedRouter` objects in `app.routes` - one
per `include_router` call - and they carry no `.path`, so on any wrong-method
request the span-name helper raised before a response was written. The exception
escapes in the ASGI middleware *above* this app, so the caller got Starlette's
plain `Internal Server Error` rather than this API's error envelope, and the
server logged a traceback for a request that was simply malformed.

Not fixed upstream as of 0.65b0, the latest published version, so a bump is not
the answer; it is checked rather than assumed, and this module goes away when it
is.

**A wrapper, not a fork.** It calls upstream and supplies, for the branch they
missed, the same fallback they already use in the branch they guarded. Copying
their loop would leave us owning route-matching logic that changes underneath us;
this owns one `except`.
"""

from __future__ import annotations

import logging
from typing import Any

from opentelemetry.instrumentation.fastapi import (
    _get_route_details as _upstream_route_details,
)

logger = logging.getLogger(__name__)


def route_details(scope: dict[str, Any]) -> Any:
    """Upstream's answer, or the request's own path when it cannot produce one.

    `AttributeError` is what upstream's own guarded branch catches, and
    `scope["path"]` is what it falls back to - so this widens their handling to the
    branch they missed rather than inventing a policy. Anything else propagates: a
    span name is not worth swallowing an unrelated failure for.
    """
    try:
        return _upstream_route_details(scope)
    except AttributeError:
        return scope.get("path")


def patch_route_details() -> None:
    """Install `route_details` in place of the helper that raises.

    Patched on the module rather than passed as an argument because there is no
    argument: `FastAPIInstrumentor.instrument_app` hardcodes
    `_get_default_span_details`, which reads `_get_route_details` as a module
    global - so replacing that global before instrumenting is the whole of it.

    Idempotent, because the lifespan and the import-time test client both
    instrument.
    """
    import opentelemetry.instrumentation.fastapi as instrumentation

    if getattr(instrumentation._get_route_details, "__module__", None) == __name__:
        return
    # Upstream types the global as its own `def _get_route_details(scope)`, and
    # replacing it is the whole point - there is no argument to pass a replacement in
    # through. `route_details` above takes and returns what that one does.
    instrumentation._get_route_details = route_details  # ty: ignore[invalid-assignment]
    logger.debug("otel_route_details_patched")
