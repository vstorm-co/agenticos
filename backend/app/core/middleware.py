"""Application middleware."""

from typing import ClassVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that adds a unique request ID to each request.

    The request ID is taken from the X-Request-ID header if present,
    otherwise a new UUID is generated. The ID is added to the response
    headers and is available in request.state.request_id.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add request ID to request state and response headers."""
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to all responses.

    This includes:
    - Content-Security-Policy (CSP)
    - X-Content-Type-Options
    - X-Frame-Options
    - X-XSS-Protection
    - Referrer-Policy
    - Permissions-Policy

    Usage:
        app.add_middleware(SecurityHeadersMiddleware)

        # Or with custom CSP:
        app.add_middleware(
            SecurityHeadersMiddleware,
            csp_directives={
                "default-src": "'self'",
                "script-src": "'self' 'unsafe-inline'",
            }
        )
    """

    DEFAULT_CSP_DIRECTIVES: ClassVar[dict[str, str]] = {
        "default-src": "'self'",
        "script-src": "'self'",
        "style-src": "'self' 'unsafe-inline'",  # Allow inline styles for some UI libs
        "img-src": "'self' data: https:",
        "font-src": "'self' data:",
        "connect-src": "'self'",
        "frame-ancestors": "'none'",
        "base-uri": "'self'",
        "form-action": "'self'",
    }

    def __init__(
        self,
        app: ASGIApp,
        csp_directives: dict[str, str] | None = None,
        exclude_paths: set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.csp_directives = csp_directives or self.DEFAULT_CSP_DIRECTIVES
        self.exclude_paths = exclude_paths or {"/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add security headers to the response.

        `exclude_paths` drops only the Content-Security-Policy, never the rest of
        the set: the CSP is what breaks Swagger and ReDoc, which pull assets a
        strict policy forbids, but those pages still need their framing and MIME
        protections - excluding them wholesale would leave /docs embeddable by any
        origin while an operator uses its authenticated controls.
        """
        response = await call_next(request)

        if request.url.path not in self.exclude_paths:
            csp_value = "; ".join(
                f"{directive} {value}" for directive, value in self.csp_directives.items()
            )
            # Respect an already-set header so an endpoint can opt into a looser
            # policy (e.g. user-content files in the chat preview panel).
            response.headers.setdefault("Content-Security-Policy", csp_value)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # 0, not "1; mode=block": the legacy auditor is deprecated and its
        # blocking mode opens XS-Leak vectors in the browsers that still have it,
        # so OWASP is to disable it and rely on the CSP above.
        response.headers.setdefault("X-XSS-Protection", "0")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), payment=(), usb=()"
        )

        return response
