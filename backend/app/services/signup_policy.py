"""Whether this deployment lets a given address create an account.

Three rules and one invariant, applied in `UserService.register` - the single
place an account is minted from an unauthenticated request.

The invariant first, because it is the one that ends a deployment if it is wrong:
**the first user is always admitted.** A fresh installation has no accounts, so
its administrator does not exist yet; a closed deployment that also refuses the
person who would open it is a deployment nobody can enter, with no console to fix
it from. `register` already promotes that first account to `is_app_admin`, and
this defers to the same fact.

Then the mode:

- `open` - anybody may register. The default, and what every deployment before
  this feature was.
- `invite_only` - only an address some organization has actually invited, which is
  `invitation_repo.any_pending_admitting`. This exists because closing
  registration would otherwise break invitations outright: an invited person has
  no account, and `InvitationService.accept` requires one.
- `closed` - nobody registers. Accounts arrive by an administrator creating them.

And, across all three, the domain allow-list: a non-empty
`allowed_email_domains` narrows who may register at all. An **invitation
overrides it** - somebody holding `members:invite` named that address on purpose,
and a list of domains is deployment policy for strangers rather than a veto over a
deliberate act. `closed` is not overridden by anything, because "closed" that
lets some registrations through is not closed.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError
from app.repositories import deployment_settings_repo, invitation_repo


async def check_may_register(db: AsyncSession, *, email: str, is_first_user: bool) -> None:
    """Raise unless this deployment admits an account for `email`.

    Args:
        db: The request's session.
        email: The address being registered, as submitted.
        is_first_user: Whether this would be the deployment's first account, in
            which case nothing refuses it - see the module docstring.

    Raises:
        AuthorizationError: With the sentence the sign-up form shows. The refusal
            names no organization and no invitation: the form is public, and
            "you were not invited" must not become a way to enumerate tenants.
    """
    if is_first_user:
        return

    row = await deployment_settings_repo.get(db)
    if row is None:
        return

    mode = row.signup_mode
    if mode == "closed":
        raise AuthorizationError(
            message="This deployment is not accepting new accounts. Ask an administrator for one."
        )

    invited = False
    if mode == "invite_only":
        invited = await invitation_repo.any_pending_admitting(db, email=email)
        if not invited:
            raise AuthorizationError(
                message="This deployment is invite-only. Ask an administrator to invite you."
            )

    domains = row.allowed_email_domains
    if domains and not invited and email.strip().lower().rpartition("@")[2] not in domains:
        raise AuthorizationError(
            message="That email domain cannot register on this deployment.",
            details={"allowed_domains": sorted(domains)},
        )
