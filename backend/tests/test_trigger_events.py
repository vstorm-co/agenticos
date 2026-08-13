"""Tests for the wire side of an event trigger - verify, match, render.

Pure functions over a delivery's bytes, headers and payload, so these need no
database. The refusals are the point: a signature that does not verify, a GitHub
event that is not an issue, a payload the filter does not match. The signing is
real HMAC-SHA256 - a test that faked the signature would prove nothing about the
verifier.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.services import trigger_events

pytestmark = pytest.mark.anyio

_SECRET = "a-signing-secret-long-enough"


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestVerifySignature:
    def test_a_github_delivery_signed_with_the_secret_verifies(self):
        body = b'{"action": "opened"}'
        headers = {"x-hub-signature-256": _sign(_SECRET, body)}
        assert trigger_events.verify_signature("github", secret=_SECRET, body=body, headers=headers)

    def test_a_github_delivery_signed_with_another_secret_is_refused(self):
        body = b'{"action": "opened"}'
        headers = {"x-hub-signature-256": _sign("wrong-secret-entirely", body)}
        assert not trigger_events.verify_signature(
            "github", secret=_SECRET, body=body, headers=headers
        )

    def test_a_tampered_body_is_refused(self):
        headers = {"x-hub-signature-256": _sign(_SECRET, b'{"action": "opened"}')}
        assert not trigger_events.verify_signature(
            "github", secret=_SECRET, body=b'{"action": "closed"}', headers=headers
        )

    def test_a_missing_signature_header_is_refused(self):
        assert not trigger_events.verify_signature("github", secret=_SECRET, body=b"{}", headers={})

    def test_a_signature_without_the_sha256_prefix_is_refused(self):
        headers = {"x-hub-signature-256": "deadbeef"}
        assert not trigger_events.verify_signature(
            "github", secret=_SECRET, body=b"{}", headers=headers
        )

    def test_an_email_delivery_uses_its_own_signature_header(self):
        body = b'{"subject": "hi"}'
        headers = {"x-signature-256": _sign(_SECRET, body)}
        assert trigger_events.verify_signature("email", secret=_SECRET, body=body, headers=headers)


class TestGithubMatching:
    def test_a_non_issues_event_never_matches(self):
        assert not trigger_events.event_matches(
            "github",
            headers={"x-github-event": "push"},
            payload={"action": "opened"},
            config={},
        )

    def test_an_issue_opened_matches_the_default_filter(self):
        assert trigger_events.event_matches(
            "github",
            headers={"x-github-event": "issues"},
            payload={"action": "opened"},
            config={},
        )

    def test_an_action_outside_the_filter_does_not_match(self):
        assert not trigger_events.event_matches(
            "github",
            headers={"x-github-event": "issues"},
            payload={"action": "closed"},
            config={},
        )

    def test_a_configured_action_matches(self):
        assert trigger_events.event_matches(
            "github",
            headers={"x-github-event": "issues"},
            payload={"action": "labeled"},
            config={"actions": ["labeled"]},
        )


class TestEmailMatching:
    def test_no_filter_matches_any_message(self):
        assert trigger_events.event_matches(
            "email", headers={}, payload={"subject": "anything", "from": "a@b.co"}, config={}
        )

    def test_a_subject_substring_that_is_present_matches(self):
        assert trigger_events.event_matches(
            "email",
            headers={},
            payload={"subject": "[URGENT] outage", "from": "a@b.co"},
            config={"subject_contains": "URGENT"},
        )

    def test_a_subject_substring_that_is_absent_does_not_match(self):
        assert not trigger_events.event_matches(
            "email",
            headers={},
            payload={"subject": "hello", "from": "a@b.co"},
            config={"subject_contains": "URGENT"},
        )

    def test_a_sender_substring_that_is_absent_does_not_match(self):
        assert not trigger_events.event_matches(
            "email",
            headers={},
            payload={"subject": "hi", "from": "spam@evil.co"},
            config={"sender_contains": "@trusted.co"},
        )

    def test_a_sender_substring_that_is_present_matches(self):
        assert trigger_events.event_matches(
            "email",
            headers={},
            payload={"subject": "hi", "from": "boss@trusted.co"},
            config={"sender_contains": "@trusted.co"},
        )

    def test_subject_and_sender_filters_match_regardless_of_case(self):
        # A domain is case-insensitive by spec and "invoice" should catch "Invoice";
        # a case-sensitive filter would never fire and never say why.
        assert trigger_events.event_matches(
            "email",
            headers={},
            payload={"subject": "Invoice #12", "from": "billing@Vstorm.co"},
            config={"subject_contains": "invoice", "sender_contains": "@vstorm.co"},
        )


class TestRenderContext:
    def test_a_github_issue_renders_its_number_title_and_body(self):
        context = trigger_events.render_context(
            "github",
            payload={
                "action": "opened",
                "repository": {"full_name": "acme/widgets"},
                "issue": {
                    "number": 7,
                    "title": "It broke",
                    "body": "steps to reproduce",
                    "html_url": "https://github.com/acme/widgets/issues/7",
                },
            },
        )
        assert "acme/widgets" in context
        assert "#7: It broke" in context
        assert "steps to reproduce" in context

    def test_a_github_payload_missing_fields_renders_without_raising(self):
        context = trigger_events.render_context("github", payload={})
        assert "a repository" in context

    def test_an_email_renders_its_sender_subject_and_body(self):
        context = trigger_events.render_context(
            "email",
            payload={"from": "a@b.co", "subject": "Hello", "body": "the message"},
        )
        assert "From: a@b.co" in context
        assert "Subject: Hello" in context
        assert "the message" in context

    def test_an_email_falls_back_to_the_text_field_for_its_body(self):
        context = trigger_events.render_context(
            "email", payload={"from": "a@b.co", "subject": "Hi", "text": "plain text body"}
        )
        assert "plain text body" in context

    def test_a_giant_github_issue_body_is_clipped_and_its_header_survives(self):
        context = trigger_events.render_context(
            "github",
            payload={
                "action": "opened",
                "repository": {"full_name": "acme/widgets"},
                "issue": {"number": 7, "title": "It broke", "body": "x" * 10000},
            },
        )
        assert "#7: It broke" in context
        assert "truncated" in context
        assert len(context) < 3000

    def test_a_giant_email_body_is_clipped_and_its_header_survives(self):
        context = trigger_events.render_context(
            "email",
            payload={"from": "a@b.co", "subject": "Hello", "body": "y" * 10000},
        )
        assert "From: a@b.co" in context
        assert "Subject: Hello" in context
        assert "truncated" in context
        assert len(context) < 3000


class TestLinkedinAndWebhook:
    def test_a_linkedin_delivery_uses_the_relay_signature_header(self):
        body = b'{"author": "Jane"}'
        headers = {"x-signature-256": _sign(_SECRET, body)}
        assert trigger_events.verify_signature(
            "linkedin", secret=_SECRET, body=body, headers=headers
        )

    def test_a_linkedin_post_with_no_filter_matches(self):
        assert trigger_events.event_matches(
            "linkedin", headers={}, payload={"author": "Jane", "text": "hello"}, config={}
        )

    def test_a_linkedin_author_filter_is_applied(self):
        assert not trigger_events.event_matches(
            "linkedin",
            headers={},
            payload={"author": "Someone Else", "text": "hello"},
            config={"author_contains": "Jane"},
        )
        assert trigger_events.event_matches(
            "linkedin",
            headers={},
            payload={"author": "Jane Doe", "text": "hello"},
            config={"author_contains": "Jane"},
        )

    def test_a_linkedin_text_filter_falls_back_to_the_body_field(self):
        assert trigger_events.event_matches(
            "linkedin",
            headers={},
            payload={"author": "Jane", "body": "launch day"},
            config={"text_contains": "launch"},
        )
        assert not trigger_events.event_matches(
            "linkedin",
            headers={},
            payload={"author": "Jane", "body": "quiet day"},
            config={"text_contains": "launch"},
        )

    def test_a_linkedin_author_and_text_filter_match_regardless_of_case(self):
        assert trigger_events.event_matches(
            "linkedin",
            headers={},
            payload={"author": "Jane DOE", "text": "We SHIPPED it"},
            config={"author_contains": "doe", "text_contains": "shipped"},
        )

    def test_a_linkedin_post_renders_its_author_and_text(self):
        context = trigger_events.render_context(
            "linkedin",
            payload={"author": "Jane", "url": "https://li/x", "text": "We shipped it"},
        )
        assert "Author: Jane" in context
        assert "We shipped it" in context

    def test_a_giant_linkedin_body_is_clipped_and_its_header_survives(self):
        context = trigger_events.render_context(
            "linkedin",
            payload={"author": "Jane", "url": "https://li/x", "text": "z" * 10000},
        )
        assert "Author: Jane" in context
        assert "truncated" in context
        assert len(context) < 3000

    def test_a_generic_webhook_always_matches_once_verified(self):
        # The sender chose to deliver; filtering is its job, not the trigger's.
        assert trigger_events.event_matches(
            "webhook", headers={}, payload={"anything": True}, config={}
        )

    def test_a_generic_webhook_renders_its_payload_as_json(self):
        context = trigger_events.render_context("webhook", payload={"ticket": 7, "state": "open"})
        assert "webhook delivery" in context
        assert '"ticket": 7' in context

    def test_a_huge_webhook_payload_is_truncated_not_pasted_whole(self):
        context = trigger_events.render_context("webhook", payload={"blob": "x" * 10000})
        assert len(context) < 3000
        assert "truncated" in context


class TestSignatureVerificationIsRobust:
    def test_a_non_ascii_signature_header_is_refused_not_a_500(self):
        # Header values are latin-1; hmac.compare_digest raises TypeError on a
        # str with a non-ASCII char, so this must be a plain False, not a crash.
        headers = {"x-hub-signature-256": "sha256=ÿþ"}
        assert not trigger_events.verify_signature(
            "github", secret=_SECRET, body=b"{}", headers=headers
        )
