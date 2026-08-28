"""Password-reset and magic-link request/confirm schemas."""

import re

from pydantic import EmailStr, Field, field_validator

from app.schemas.base import BaseSchema

# Where a magic link may land: a path on this deployment, and nothing else. A
# value with a scheme ("https://evil.example"), a protocol-relative one
# ("//evil.example"), a backslash variant ("/\evil.example", which browsers
# normalise to "//") or a control character ("/\t/evil.example", which the URL
# parser strips before parsing) would each turn the link into an open redirect -
# and this one is *signed into a token* and followed from an email, so it must
# not be storable in the first place. `frontend/src/lib/auth-landing.ts` refuses
# the same shapes again at the landing; this is what keeps them out of the token.
_SAFE_RETURN_PATH = re.compile(r"^/(?![/\\])[^\s\\\x00-\x1f\x7f]*$")


class PasswordResetRequest(BaseSchema):
    """Step 1 - user submits their email; we email a reset link."""

    email: EmailStr


class PasswordResetConfirm(BaseSchema):
    """Step 2 - user clicks link, posts new password with token."""

    token: str = Field(..., min_length=10)
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordResetResponse(BaseSchema):
    """Symmetric response for both request + confirm to avoid email enumeration."""

    sent: bool = True
    message: str = "If an account exists for that email, you'll get a reset link shortly."


class PasswordResetConfirmResponse(BaseSchema):
    """Returned after a successful confirm - front-end then redirects to login."""

    success: bool = True
    message: str = "Password updated. You can now sign in."


class MagicLinkRequest(BaseSchema):
    """Email, and where the link should land.

    `return_to` is the path the visitor was headed to when they were asked to
    sign in. It travels *in the token* rather than in a session store, because a
    magic link is followed from an email: a different tab, often a different
    application, sometimes a different browser, where `sessionStorage` is empty
    by construction (#1214).
    """

    email: EmailStr
    return_to: str | None = Field(default=None, max_length=512)

    @field_validator("return_to")
    @classmethod
    def _only_a_path_on_this_deployment(cls, value: str | None) -> str | None:
        if value is not None and not _SAFE_RETURN_PATH.match(value):
            raise ValueError("must be a path on this deployment, beginning with a single '/'")
        return value


class MagicLinkVerifyRequest(BaseSchema):
    """Step 2 - user clicked email link, exchange token for session."""

    token: str = Field(..., min_length=10)
