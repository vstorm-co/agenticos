"""Consent for triggers that retain a member's authority beyond their request."""

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext


def require_human_publisher(ctx: AuthContext) -> None:
    """A key cannot be persisted as a user-only unattended principal."""
    if ctx.api_key_id is not None:
        raise AuthorizationError(
            message="Configuring unattended workflow authority requires a member session",
            details={"authentication": "session_required"},
        )
