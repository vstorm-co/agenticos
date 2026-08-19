"""Whether one invitation admits one address.

The conditions an invitation carries, as a single predicate: is it still live, does
it still have a use left, and is this the person it was for. Written once because two
callers ask it - the sign-up policy, deciding whether an address may create an
account at all, and `InvitationService.accept`, deciding whether a signed-in user may
join the organization.

Only the first uses this. `accept` deliberately keeps its own sequence of checks,
because it has to say *which* condition failed - "this invitation was sent to a
different email address" and "this link is only for @acme.com addresses" are
different things for the person reading them, and a boolean cannot tell them apart.
What it must not do is disagree with this module about the answer, which is what
`tests/test_invitation_admission.py` pins by running both over the same rows.

The sign-up policy needs the boolean rather than the reasons: its refusal is public,
and "you were not invited" must not become a way to enumerate a deployment's tenants.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.db.models.organization import Invitation, InvitationStatus


def admits(invite: Invitation, *, email: str) -> bool:
    """Whether `invite` is a live invitation for `email`.

    An **email invitation** admits exactly its own address. A **link** - `email` is
    null - admits anybody whose address is at its `email_domain`, or anybody at all
    when it names no domain, for as many uses as it has left.

    That last case is why a caller has to be holding the token to ask: an
    address-based query cannot recognise a link that constrains no address, so
    honouring one without proof of possession would turn a single open link anywhere
    in the deployment into open registration.
    """
    if invite.status != InvitationStatus.PENDING.value:
        return False
    if invite.expires_at is not None and invite.expires_at < datetime.now(UTC):
        return False

    candidate = email.strip().lower()
    if invite.email is not None:
        return candidate == invite.email.strip().lower()

    if invite.max_uses is not None and invite.used_count >= invite.max_uses:
        return False
    if invite.email_domain:
        return candidate.endswith(f"@{invite.email_domain.strip().lower()}")
    return True
