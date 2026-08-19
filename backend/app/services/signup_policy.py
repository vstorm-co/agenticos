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
- `invite_only` - only somebody an organization has actually invited. This exists
  because closing registration would otherwise break invitations outright: an
  invited person has no account, and `InvitationService.accept` requires one.

  Two ways to be invited, and they answer different questions. A **token** the
  registration carries is proof on its own - it is the only thing that can admit a
  shareable link with no address and no domain, which nothing about the submitted
  address could recognise (#916). Without one, the fallback is
  `invitation_repo.first_pending_admitting`: is there a live invitation *for this
  address*, by name or by a link scoped to its domain.

  Either way, a link with a `max_uses` has a use **reserved** for the address
  before it is admitted. Acceptance needs a session and registration does not, so a
  ceiling read off `used_count` alone bounded joins and not accounts - one one-use
  link posted anywhere admitted as many registrations as somebody cared to make.
- `closed` - nobody registers, by any route. There is deliberately no
  administrator-creates-an-account path: an account needs a password its owner
  chose, so adding somebody means opening registration to them, which is what
  `invite_only` is. A mode that let an administrator mint accounts anyway would be
  a second account-creation path to gate, and the two that exist are already the
  reason this module does.

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
from app.db.models.organization import Invitation
from app.repositories import deployment_settings_repo, invitation_repo
from app.services.invitation_admission import admits


async def check_may_register(
    db: AsyncSession,
    *,
    email: str,
    is_first_user: bool,
    invitation_token: str | None = None,
) -> None:
    """Raise unless this deployment admits an account for `email`.

    Args:
        db: The request's session.
        email: The address being registered, as submitted.
        is_first_user: Whether this would be the deployment's first account, in
            which case nothing refuses it - see the module docstring.
        invitation_token: The invitation the registration is arriving through, if
            any. Consulted only where the policy has narrowed registration, and it
            grants nothing beyond being allowed to create the account.

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
            message="This deployment is not accepting new accounts. Ask an administrator to invite you."
        )

    domains = row.allowed_email_domains
    # Only asked where the answer can change the outcome. An `open` deployment with no
    # domain list refuses nobody, so looking for an invitation there would be a query
    # per registration for a verdict nothing reads.
    invited = (
        await _is_invited(db, email=email, invitation_token=invitation_token)
        if mode == "invite_only" or bool(domains)
        else False
    )
    if mode == "invite_only" and not invited:
        raise AuthorizationError(
            message="This deployment is invite-only. Ask an administrator to invite you."
        )

    if domains and not invited and email.strip().lower().rpartition("@")[2] not in domains:
        raise AuthorizationError(
            message="That email domain cannot register on this deployment.",
            details={"allowed_domains": sorted(domains)},
        )


async def _is_invited(db: AsyncSession, *, email: str, invitation_token: str | None) -> bool:
    """Whether somebody with `members:invite` has asked for this person.

    The token first, because it is the stronger answer and the only one that can
    recognise a link carrying neither an address nor a domain. `admits` is where the
    conditions live; a token that names no live invitation simply falls through to
    the address-based question rather than refusing, so a stale link in a bookmark
    does not turn a registration that would otherwise be allowed into an error about
    something the person cannot fix.

    A token whose link lost the last use to a concurrent registration falls through
    to the address question as well, for the same reason a stale one does: the
    person may also have been invited by name, and refusing without asking would be
    an error about something they cannot fix.

    Either way, an admitting **link with a `max_uses`** has a use reserved before
    this answers yes. That is the whole of #914's finding: `used_count` counts
    acceptances, acceptance needs a session, and registration does not - so a
    one-use link admitted an unbounded number of accounts, each one checking a
    count nothing had yet moved. The reservation is what makes the ceiling mean
    registrations too, and `reserve_use` is atomic so two registrations racing on
    the last use cannot both take it.

    `open` with no domain list never reaches here at all - the caller decides that,
    because it is the one that knows whether the verdict is read.
    """
    if invitation_token is not None:
        invite = await invitation_repo.get_by_token(db, invitation_token)
        if (
            invite is not None
            and admits(invite, email=email)
            and await _reserved(db, invite, email=email)
        ):
            return True
    found = await invitation_repo.first_pending_admitting(db, email=email)
    return found is not None and await _reserved(db, found, email=email)


async def _reserved(db: AsyncSession, invite: Invitation, *, email: str) -> bool:
    """Hold one of this invitation's uses for `email`, where it has a ceiling.

    An email invitation and an unlimited link bound nothing, so there is nothing to
    hold and nothing to fail: they admit outright. A capped link answers whether the
    address got a use, which is a second, atomic reading of the same condition
    `admits` checked - and the one that survives a race, because `admits` read a row
    this session loaded.
    """
    if invite.email is not None or invite.max_uses is None:
        return True
    return await invitation_repo.reserve_use(db, invitation_id=invite.id, email=email)
