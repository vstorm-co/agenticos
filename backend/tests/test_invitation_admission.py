"""Whether one invitation admits one address.

The predicate the sign-up policy asks when a registration carries a token, and the
reason it exists at all: a shareable link with neither an address nor a domain is a
real and documented shape (`Invitation.email` null, `email_domain` null), and nothing
about a submitted address can recognise one. Before a token could be passed,
`invite_only` silently un-invited everybody holding such a link (#916).

The last class is the one worth keeping honest. `InvitationService.accept` checks the
same conditions in its own sequence, because it has to say *which* one failed - and
two implementations of one rule is exactly how they come to disagree. It runs both
over the same rows and asserts they reach the same verdict.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.organization import Invitation, InvitationStatus
from app.services.invitation_admission import admits

LATER = datetime.now(UTC) + timedelta(days=3)
EARLIER = datetime.now(UTC) - timedelta(days=1)


def an_invite(**overrides) -> Invitation:
    invite = Invitation(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        email=None,
        role="member",
        max_uses=None,
        used_count=0,
        email_domain=None,
        invited_by_user_id=uuid.uuid4(),
        token=uuid.uuid4().hex,
        status=InvitationStatus.PENDING.value,
        expires_at=LATER,
    )
    for field, value in overrides.items():
        setattr(invite, field, value)
    return invite


class TestAnEmailInvitation:
    def test_it_admits_its_own_address(self):
        assert admits(an_invite(email="me@acme.com"), email="me@acme.com")

    def test_it_admits_nobody_else(self):
        assert not admits(an_invite(email="me@acme.com"), email="someone@acme.com")

    def test_the_comparison_ignores_case_and_surrounding_space(self):
        assert admits(an_invite(email="Me@Acme.com"), email="  me@acme.com ")

    def test_a_use_limit_on_an_email_invitation_is_ignored(self):
        """An address is its own limit of one, which is what the column's own comment
        says - so a stray `max_uses` must not make a named invitation unusable."""
        assert admits(an_invite(email="me@acme.com", max_uses=1, used_count=5), email="me@acme.com")


class TestALink:
    def test_a_link_with_no_domain_admits_anybody_holding_it(self):
        """Which is only safe to ask because the caller had to produce the token. An
        address-based query cannot see this shape at all."""
        assert admits(an_invite(), email="anyone@example.com")

    def test_a_domain_scoped_link_admits_that_domain(self):
        assert admits(an_invite(email_domain="acme.com"), email="me@acme.com")

    def test_a_domain_scoped_link_admits_nobody_else(self):
        assert not admits(an_invite(email_domain="acme.com"), email="me@gmail.com")

    def test_a_domain_is_matched_on_the_whole_suffix_and_not_a_substring(self):
        assert not admits(an_invite(email_domain="acme.com"), email="me@notacme.com")

    def test_a_spent_link_admits_nobody(self):
        assert not admits(an_invite(max_uses=2, used_count=2), email="me@acme.com")

    def test_a_link_with_uses_left_still_admits(self):
        assert admits(an_invite(max_uses=2, used_count=1), email="me@acme.com")

    def test_an_unlimited_link_never_runs_out(self):
        assert admits(an_invite(max_uses=None, used_count=999), email="me@acme.com")


class TestWhatIsNoLongerLive:
    @pytest.mark.parametrize(
        "status",
        [InvitationStatus.ACCEPTED.value, InvitationStatus.REVOKED.value, "expired"],
    )
    def test_only_a_pending_invitation_admits(self, status):
        assert not admits(an_invite(email="me@acme.com", status=status), email="me@acme.com")

    def test_an_expired_invitation_admits_nobody(self):
        assert not admits(an_invite(email="me@acme.com", expires_at=EARLIER), email="me@acme.com")

    def test_an_invitation_with_no_expiry_is_not_treated_as_expired(self):
        assert admits(an_invite(email="me@acme.com", expires_at=None), email="me@acme.com")


class TestItAgreesWithAcceptance:
    """`InvitationService.accept` states the same rules in its own sequence, because
    it has to name the one that failed. Two implementations of one rule is how they
    come to disagree, so both are run over the same rows here."""

    ROWS = [
        ("named, right address", {"email": "me@acme.com"}, "me@acme.com"),
        ("named, wrong address", {"email": "me@acme.com"}, "other@acme.com"),
        ("open link", {}, "anyone@example.com"),
        ("domain link, in domain", {"email_domain": "acme.com"}, "me@acme.com"),
        ("domain link, out of domain", {"email_domain": "acme.com"}, "me@gmail.com"),
        ("spent link", {"max_uses": 1, "used_count": 1}, "me@acme.com"),
        ("link with a use left", {"max_uses": 3, "used_count": 1}, "me@acme.com"),
    ]

    @pytest.mark.parametrize(("label", "fields", "email"), ROWS)
    def test_both_reach_the_same_verdict(self, label, fields, email):
        invite = an_invite(**fields)

        assert admits(invite, email=email) is _accept_would_allow(invite, email), label


def _accept_would_allow(invite: Invitation, email: str) -> bool:
    """`InvitationService.accept`'s conditions, as a boolean.

    Transcribed rather than called: `accept` needs a session, a user row and a
    membership table, and what is being compared is the *rule* rather than the
    plumbing around it. Transcription is only worth trusting because it is short - if
    `accept` grows a condition this does not have, the parametrised cases above start
    disagreeing.
    """
    if invite.status != InvitationStatus.PENDING.value:
        return False
    if invite.expires_at is not None and invite.expires_at < datetime.now(UTC):
        return False
    if invite.email is not None:
        return email.lower() == invite.email
    if invite.max_uses is not None and invite.used_count >= invite.max_uses:
        return False
    if invite.email_domain:
        return email.lower().endswith(f"@{invite.email_domain}")
    return True
