"""Reading the receiving server's SPF/DKIM/DMARC verdict for a sender filter."""

import pytest

from app.services.portals.mail_auth import authenticated

# What Gmail writes: its own name first, the signer as `header.i`.
_GMAIL = (
    "mx.google.com;\r\n       dkim=pass header.i=@acme.com header.s=google header.b=Ab12;"
    "\r\n       spf=pass (google.com: domain of x@acme.com designates 1.2.3.4) "
    "smtp.mailfrom=x@acme.com;\r\n       dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=acme.com"
)
# What Exchange Online writes: no server name, the signer as `header.d`.
_EXCHANGE = (
    "spf=pass (sender IP is 1.2.3.4) smtp.mailfrom=acme.com; dkim=pass (signature was "
    "verified) header.d=acme.com;dmarc=pass action=none header.from=acme.com;compauth=pass reason=100"
)


class TestAuthenticated:
    @pytest.mark.parametrize(
        "verdict",
        [
            _GMAIL,
            _EXCHANGE,
            # Signed by a mailing service, aligned through SPF: DMARC is the verdict.
            "mx.google.com; dkim=pass header.i=@esp.example; dmarc=pass header.from=acme.com",
        ],
    )
    def test_a_dmarc_pass_vouches_for_the_sender(self, verdict):
        assert authenticated([("Authentication-Results", verdict)], "Ann <ann@acme.com>")

    def test_without_dmarc_a_dkim_pass_for_the_from_domain_or_its_parent_is_enough(self):
        """A domain with no DMARC policy still signs: the signature has to be its own."""
        verdict = "mx.google.com; dkim=pass header.i=@acme.com; dmarc=none"
        assert authenticated([("authentication-results", verdict)], "ann@acme.com")
        assert authenticated([("Authentication-Results", verdict)], "ann@mail.acme.com")
        # A signature from somebody else's domain says nothing about acme's.
        assert not authenticated([("Authentication-Results", verdict)], "ann@acme.co")
        assert not authenticated([("Authentication-Results", verdict)], "ann@notacme.com")

    def test_spf_alone_does_not_vouch_for_the_from(self):
        """SPF checks the envelope sender, which nobody sees and need not match `From`."""
        verdict = "mx.google.com; spf=pass smtp.mailfrom=bulk@mailer.example; dmarc=fail"
        assert not authenticated([("Authentication-Results", verdict)], "ceo@acme.com")

    def test_only_the_topmost_verdict_counts(self):
        """Our provider prepends its verdict; a copy the sender pasted lies below it."""
        headers = [
            ("Authentication-Results", "mx.google.com; dmarc=fail header.from=acme.com"),
            ("Authentication-Results", "forged.example; dmarc=pass header.from=acme.com"),
        ]
        assert not authenticated(headers, "ceo@acme.com")

    def test_no_verdict_or_no_sender_address_is_not_authenticated(self):
        assert not authenticated([("Subject", "hi")], "ann@acme.com")
        assert not authenticated([("Authentication-Results", _GMAIL)], "Ann")
