"""Two-factor authentication schemas.

The secret and the recovery codes are shown once, at the step that creates
them, and never again: `MfaSetupRead` carries the provisioning URI and the
secret for an authenticator that cannot scan, `MfaRecoveryCodesRead` carries
the ten codes at enablement and at regeneration. Nothing else in this module
carries either value.
"""

from pydantic import Field

from app.schemas.base import BaseSchema


class MfaStatusRead(BaseSchema):
    """Whether this account's sign-in stops at a second factor."""

    enabled: bool


class MfaSetupRead(BaseSchema):
    """The enrolment just started: what the authenticator needs, shown once."""

    provisioning_uri: str
    secret: str


class MfaCodeRequest(BaseSchema):
    """A code from the authenticator, or a recovery code where one is accepted."""

    code: str = Field(min_length=6, max_length=9)


class MfaRecoveryCodesRead(BaseSchema):
    """The recovery codes, shown once - the way back in if the authenticator
    is lost. Stored only as digests, so this response is the only copy."""

    recovery_codes: list[str]


class MfaRequired(BaseSchema):
    """The password checked out, and the sign-in is waiting on the second factor.

    The client posts `mfa_token` with the code to `/auth/mfa/verify` within
    `expires_in` seconds. The token proves the password step and nothing
    else: it is not a session, and it cannot call the API as one.

    `return_to` is set only when the challenge came from a magic link: the
    link's destination was validated at mint, and the second step must not
    be what drops it. A password login has no destination to carry.
    """

    mfa_required: bool = True
    mfa_token: str
    expires_in: int = 300
    return_to: str | None = None


class MfaVerifyRequest(BaseSchema):
    """The second step: the challenge token from the password step, plus the code."""

    mfa_token: str
    code: str = Field(min_length=6, max_length=9)
