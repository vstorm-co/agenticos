"""Tests for the wire side of an event trigger - verify, match, render.

Pure functions over a delivery's bytes, headers and payload, so these need no
database. The refusals are the point: a signature that does not verify, a GitHub
event that is not an issue, a payload the filter does not match. The signing is
real HMAC-SHA256 - a test that faked the signature would prove nothing about the
verifier.
"""

import hashlib
import hmac

import pytest

from app.services import trigger_events

pytestmark = pytest.mark.anyio

_SECRET = "a-signing-secret-long-enough"


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class TestVerifySignature:
    @pytest.mark.security
    def test_a_github_delivery_signed_with_the_secret_verifies(self):
        body = b'{"action": "opened"}'
        headers = {"x-hub-signature-256": _sign(_SECRET, body)}
        assert trigger_events.verify_signature("github", secret=_SECRET, body=body, headers=headers)

    @pytest.mark.security
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

    def test_a_polled_source_has_no_signed_door_at_all(self):
        """`gmail` is read from a connected mailbox, so nothing POSTs it here.

        Asked before a signature is looked for, because the header tables are keyed
        only by the sources that have a door: a bare lookup on one that does not
        would turn this refusal into a `KeyError` and a 500 (#1068).
        """
        assert trigger_events.accepts_delivery("github")
        assert trigger_events.accepts_delivery("webhook")
        assert not trigger_events.accepts_delivery("gmail")


_BY_MEMBER = {"author_association": "MEMBER"}


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
            payload={"action": "opened", "issue": _BY_MEMBER},
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
            payload={"action": "labeled", "issue": _BY_MEMBER},
            config={"actions": ["labeled"]},
        )


class TestGmailMatching:
    def test_no_filter_matches_any_message(self):
        assert trigger_events.event_matches(
            "gmail", headers={}, payload={"subject": "anything", "from": "a@b.co"}, config={}
        )

    def test_a_subject_substring_that_is_present_matches(self):
        assert trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "[URGENT] outage", "from": "a@b.co"},
            config={"subject_contains": "URGENT"},
        )

    def test_a_subject_substring_that_is_absent_does_not_match(self):
        assert not trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "hello", "from": "a@b.co"},
            config={"subject_contains": "URGENT"},
        )

    def test_a_sender_substring_that_is_absent_does_not_match(self):
        assert not trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "hi", "from": "spam@evil.co"},
            config={"sender_contains": "@trusted.co"},
        )

    def test_a_sender_substring_that_is_present_matches(self):
        assert trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "hi", "from": "boss@trusted.co", "authenticated": True},
            config={"sender_contains": "@trusted.co"},
        )

    def test_a_sender_filter_refuses_a_from_its_domain_did_not_vouch_for(self):
        """`From: boss@trusted.co` costs nothing to type. A filter on the sender is
        a trust decision, so by default it fires only on mail trusted.co signed."""
        assert not trigger_events.event_matches(
            "gmail",
            headers={},
            payload={
                "subject": "wire the money",
                "from": "boss@trusted.co",
                "authenticated": False,
            },
            config={"sender_contains": "@trusted.co"},
        )

    def test_the_authenticated_rule_can_be_turned_off_or_on_by_itself(self):
        unsigned = {"subject": "hi", "from": "relay@trusted.co"}
        # Off: an internal relay that signs nothing still fires a sender filter.
        assert trigger_events.event_matches(
            "gmail",
            headers={},
            payload=unsigned,
            config={"sender_contains": "@trusted.co", "authenticated_only": False},
        )
        # On with no sender filter: any unsigned message is refused.
        assert not trigger_events.event_matches(
            "gmail", headers={}, payload=unsigned, config={"authenticated_only": True}
        )
        # And no rule at all without a sender filter, as before.
        assert trigger_events.event_matches("gmail", headers={}, payload=unsigned, config={})

    def test_subject_and_sender_filters_match_regardless_of_case(self):
        # A domain is case-insensitive by spec and "invoice" should catch "Invoice";
        # a case-sensitive filter would never fire and never say why.
        assert trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "Invoice #12", "from": "billing@Vstorm.co", "authenticated": True},
            config={"subject_contains": "invoice", "sender_contains": "@vstorm.co"},
        )

    @pytest.mark.parametrize("label", ["SENT", "DRAFT", "SPAM", "TRASH"])
    def test_mail_that_did_not_arrive_for_the_agent_never_fires_it(self, label):
        """Gmail's history reports the account's own sends, its drafts and its spam
        as added messages. Fired on, an agent replying by email triggers itself -
        a loop - and spam hands anyone who can send an email a run."""
        assert not trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "Re: hi", "from": "me@corp.test", "labels": [label, "INBOX"]},
            config={},
        )

    def test_a_trigger_that_names_such_a_label_asks_for_it(self):
        assert trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "Hi", "from": "a@b.co", "labels": ["SENT"]},
            config={"label": "SENT"},
        )

    def test_a_label_filter_matches_the_labels_gmail_reported(self):
        assert trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "Hi", "from": "a@b.co", "labels": ["INBOX", "IMPORTANT"]},
            config={"label": "IMPORTANT"},
        )

    def test_a_label_the_message_does_not_carry_does_not_match(self):
        """Exactly, not as a substring: a label is an identifier the API answers
        with, so `Work` matching `Workshop` would fire on somebody else's mail."""
        assert not trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "Hi", "from": "a@b.co", "labels": ["Workshop"]},
            config={"label": "Work"},
        )

    def test_a_message_with_no_labels_at_all_does_not_match_a_label_filter(self):
        assert not trigger_events.event_matches(
            "gmail",
            headers={},
            payload={"subject": "Hi", "from": "a@b.co"},
            config={"label": "INBOX"},
        )


def _outlook(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "place": "|inbox",
        "mailbox": None,
        "folder": "inbox",
        "subject": "Invoice 42 overdue",
        "from": "Billing <billing@Acme.test>",
        "categories": ["Finance"],
        "importance": "high",
        "has_attachments": True,
        "attachments": [{"name": "invoice.pdf"}, {"name": ""}, "not an object"],
        "text": "Please pay.",
        "authenticated": True,
    }
    payload.update(overrides)
    return payload


class TestOutlookMatching:
    """An Outlook trigger reads one place, then narrows like Gmail (#1984)."""

    @staticmethod
    def _matches(config: dict[str, object], **payload: object) -> bool:
        return trigger_events.event_matches(
            "outlook", headers={}, payload=_outlook(**payload), config=config
        )

    def test_no_filter_fires_on_any_message_in_the_inbox(self):
        assert self._matches({})

    def test_a_message_from_another_place_never_fires(self):
        """Even with no other filter: the folder is where the trigger looks."""
        assert not self._matches({}, place="|archive")
        assert not self._matches({"folder": "Inbox/Invoices"}, place="|inbox")
        assert self._matches({"folder": "Inbox/Invoices"}, place="|inbox/invoices")
        assert self._matches({"mailbox": "Ops@Corp.test"}, place="ops@corp.test|inbox")

    def test_subject_and_sender_are_case_insensitive_substrings(self):
        assert self._matches({"subject_contains": "INVOICE", "sender_contains": "@acme.TEST"})
        assert not self._matches({"subject_contains": "receipt"})
        assert not self._matches({"sender_contains": "@other.test"})

    def test_a_sender_filter_needs_a_vouched_for_sender_here_too(self):
        assert not self._matches({"sender_contains": "@acme.test"}, authenticated=False)
        assert self._matches(
            {"sender_contains": "@acme.test", "authenticated_only": False}, authenticated=False
        )

    def test_attachments_importance_and_category_are_exact(self):
        assert self._matches({"has_attachments": True, "importance": "high", "category": "finance"})
        assert not self._matches({"has_attachments": False})
        assert not self._matches({"importance": "low"})
        assert not self._matches({"category": "Fin"})

    def test_the_place_a_trigger_reads(self):
        assert trigger_events.polled_place("outlook", {"folder": "Archive"}) == "|archive"
        assert trigger_events.polled_place("gmail", {"label": "INBOX"}) is None

    def test_an_unknown_key_or_a_malformed_mailbox_is_refused(self):
        from pydantic import ValidationError

        from app.schemas.agent_trigger import OutlookTriggerConfig

        for config in ({"labels": "x"}, {"mailbox": "not-an-address"}, {"importance": "urgent"}):
            with pytest.raises(ValidationError):
                OutlookTriggerConfig.model_validate(config)


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
            "gmail",
            payload={"from": "a@b.co", "subject": "Hello", "body": "the message"},
        )
        assert "From: a@b.co" in context
        assert "Subject: Hello" in context
        assert "the message" in context

    def test_an_email_falls_back_to_the_text_field_for_its_body(self):
        context = trigger_events.render_context(
            "gmail", payload={"from": "a@b.co", "subject": "Hi", "text": "plain text body"}
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
            "gmail",
            payload={"from": "a@b.co", "subject": "Hello", "body": "y" * 10000},
        )
        assert "From: a@b.co" in context
        assert "Subject: Hello" in context
        assert "truncated" in context
        assert len(context) < 3000


class TestOutlookContext:
    def test_it_names_the_sender_subject_folder_and_files(self):
        context = trigger_events.render_context("outlook", payload=_outlook())

        assert context.startswith("An email arrived in Outlook.")
        assert "From: Billing <billing@Acme.test>" in context
        assert "Subject: Invoice 42 overdue" in context
        assert "Folder: inbox\n" in context
        assert "Attachments: invoice.pdf\n" in context
        assert context.endswith("Please pay.")

    def test_a_shared_mailbox_is_named_and_no_files_means_no_line(self):
        context = trigger_events.render_context(
            "outlook",
            payload=_outlook(mailbox="ops@corp.test", attachments=[], text="x" * 5000),
        )

        assert "Folder: inbox in ops@corp.test" in context
        assert "Attachments" not in context
        assert context.endswith("(truncated)")


class TestGenericWebhook:
    def test_a_webhook_delivery_uses_the_relay_signature_header(self):
        body = b'{"ticket": 7}'
        headers = {"x-signature-256": _sign(_SECRET, body)}
        assert trigger_events.verify_signature(
            "webhook", secret=_SECRET, body=body, headers=headers
        )

    @staticmethod
    def _stamped(stamp: str, body: bytes) -> dict[str, str]:
        return {
            "x-signature-timestamp": stamp,
            "x-signature-256": _sign(_SECRET, stamp.encode() + b"." + body),
        }

    def test_a_timestamped_delivery_inside_the_window_verifies(self):
        body = b'{"ticket": 7}'
        assert trigger_events.verify_signature(
            "webhook", secret=_SECRET, body=body, headers=self._stamped("1000", body), now=1200
        )

    @pytest.mark.security
    @pytest.mark.parametrize("now", [1000 + 301, 1000 - 301], ids=["late", "early"])
    def test_a_timestamped_delivery_outside_the_window_is_a_replay(self, now):
        """A body-only signature carries no time, so a captured delivery could be
        sent again for ever; a signed timestamp makes it good for minutes."""
        body = b'{"ticket": 7}'
        assert not trigger_events.verify_signature(
            "webhook", secret=_SECRET, body=body, headers=self._stamped("1000", body), now=now
        )

    @pytest.mark.security
    def test_dropping_the_timestamp_to_replay_it_fails_too(self):
        body = b'{"ticket": 7}'
        headers = self._stamped("1000", body)
        del headers["x-signature-timestamp"]
        assert not trigger_events.verify_signature(
            "webhook", secret=_SECRET, body=body, headers=headers, now=1000
        )

    def test_a_timestamp_that_is_not_a_number_fails(self):
        body = b"{}"
        assert not trigger_events.verify_signature(
            "webhook", secret=_SECRET, body=body, headers=self._stamped("soon", body), now=1000
        )

    def test_a_github_delivery_ignores_the_header(self):
        """GitHub signs the body alone; the header means nothing on its door."""
        body = b'{"action": "opened"}'
        headers = {"x-hub-signature-256": _sign(_SECRET, body), "x-signature-timestamp": "1"}
        assert trigger_events.verify_signature(
            "github", secret=_SECRET, body=body, headers=headers, now=10**9
        )

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


class TestTheDeliveryIdIsWhatDedupKeysOn:
    def test_githubs_native_delivery_header_is_read(self):
        assert trigger_events.delivery_id("github", {"x-github-delivery": "uuid-1"}) == "uuid-1"

    def test_a_relay_uses_the_generic_header(self):
        assert trigger_events.delivery_id("webhook", {"x-delivery-id": "abc"}) == "abc"

    def test_no_header_means_no_id_so_the_source_is_not_deduplicated(self):
        assert trigger_events.delivery_id("github", {}) is None

    def test_a_blank_header_is_treated_as_absent(self):
        assert trigger_events.delivery_id("webhook", {"x-delivery-id": "   "}) is None


def _github(event: str, payload: dict, config: dict) -> bool:
    return trigger_events.event_matches(
        "github", headers={"x-github-event": event}, payload=payload, config=config
    )


class TestWhoMayFireAGithubTrigger:
    """On a public repository anyone can open an issue; each would be a run, and a
    page of somebody's text in it. And a bot - the agent's own account among
    them - would fire the trigger it answers through."""

    @pytest.mark.security
    @pytest.mark.parametrize("association", ["NONE", "CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", None])
    def test_an_outsiders_issue_does_not_fire_by_default(self, association):
        payload = {"action": "opened", "issue": {"author_association": association}}
        assert not _github("issues", payload, {})

    def test_anyone_lets_them_through(self):
        payload = {"action": "opened", "issue": {"author_association": "NONE"}}
        assert _github("issues", payload, {"authors": "anyone"})

    @pytest.mark.security
    @pytest.mark.parametrize(
        "sender", [{"type": "Bot", "login": "ci"}, {"type": "User", "login": "dependabot[bot]"}]
    )
    def test_a_bot_never_fires_it(self, sender):
        payload = {"action": "opened", "issue": _BY_MEMBER, "sender": sender}
        assert not _github("issues", payload, {"authors": "anyone"})

    @pytest.mark.security
    def test_the_connected_account_never_fires_it(self):
        payload = {"action": "created", "comment": _BY_MEMBER, "sender": {"login": "Octo-Agent"}}
        assert not _github(
            "issue_comment", payload, {"event": "issue_comment", "ignore_login": "octo-agent"}
        )


class TestGithubEvents:
    def test_another_event_than_the_triggers_never_matches(self):
        payload = {"action": "opened", "pull_request": _BY_MEMBER}
        assert not _github("issues", payload, {"event": "pull_request"})

    def test_a_pull_request_ready_for_review_fires(self):
        payload = {
            "action": "ready_for_review",
            "pull_request": {**_BY_MEMBER, "base": {"ref": "main"}},
        }
        assert _github("pull_request", payload, {"event": "pull_request"})

    def test_a_draft_pull_request_waits_until_it_is_ready(self):
        payload = {"action": "opened", "pull_request": {**_BY_MEMBER, "draft": True}}
        assert not _github("pull_request", payload, {"event": "pull_request"})

    def test_a_pull_request_into_another_branch_does_not_fire(self):
        payload = {"action": "opened", "pull_request": {**_BY_MEMBER, "base": {"ref": "dev"}}}
        assert not _github("pull_request", payload, {"event": "pull_request", "branches": ["main"]})

    @pytest.mark.parametrize(("body", "fires"), [("Hey @Agent, look", True), ("no mention", False)])
    def test_a_comment_fires_only_with_its_mention(self, body, fires):
        payload = {"action": "created", "comment": {**_BY_MEMBER, "body": body}}
        config = {"event": "issue_comment", "mention": "@agent"}
        assert _github("issue_comment", payload, config) is fires

    @pytest.mark.parametrize(
        ("conclusion", "branch", "fires"),
        [("failure", "main", True), ("success", "main", False), ("failure", "dev", False)],
    )
    def test_a_finished_workflow_run_fires_on_its_conclusion_and_branch(
        self, conclusion, branch, fires
    ):
        payload = {
            "action": "completed",
            "workflow_run": {"conclusion": conclusion, "head_branch": branch},
            # A failed check is news whoever pushed - a bot included.
            "sender": {"type": "Bot", "login": "dependabot[bot]"},
        }
        config = {"event": "workflow_run", "branches": ["main"]}
        assert _github("workflow_run", payload, config) is fires

    def test_a_release_published_fires(self):
        assert _github("release", {"action": "published"}, {"event": "release"})

    @pytest.mark.parametrize(
        ("payload", "fires"),
        [
            ({"ref": "refs/heads/main"}, True),
            ({"ref": "refs/heads/dev"}, False),
            ({"ref": "refs/tags/v1"}, False),
            ({"ref": "refs/heads/main", "deleted": True}, False),
        ],
        ids=["main", "other-branch", "tag", "deleted"],
    )
    def test_a_push_fires_on_its_branches_only(self, payload, fires):
        assert _github("push", payload, {"event": "push", "branches": ["main"]}) is fires


class TestGithubConfigRefusals:
    @pytest.mark.parametrize(
        "config",
        [
            {"event": "pull_request", "actions": ["published"]},
            {"event": "push", "actions": ["opened"]},
            {"event": "issues", "mention": "@agent"},
            {"event": "release", "branches": ["main"]},
            {"event": "issues", "conclusions": ["failure"]},
        ],
        ids=[
            "foreign-action",
            "push-action",
            "mention-on-issues",
            "branches-on-release",
            "conclusion-on-issues",
        ],
    )
    def test_a_filter_that_could_never_apply_is_refused(self, config):
        from pydantic import ValidationError as PydanticValidationError

        from app.schemas.agent_trigger import GithubTriggerConfig

        with pytest.raises(PydanticValidationError):
            GithubTriggerConfig.model_validate(config)

    def test_a_workflow_trigger_defaults_to_failures(self):
        from app.schemas.agent_trigger import GithubTriggerConfig

        assert GithubTriggerConfig.model_validate({"event": "workflow_run"}).conclusions == [
            "failure"
        ]


class TestGithubContext:
    @pytest.mark.parametrize(
        ("payload", "expected"),
        [
            (
                {
                    "action": "opened",
                    "repository": {"full_name": "a/b"},
                    "pull_request": {
                        "number": 3,
                        "title": "Fix",
                        "head": {"ref": "f"},
                        "base": {"ref": "main"},
                    },
                },
                "Pull request #3: Fix",
            ),
            (
                {
                    "action": "created",
                    "repository": {"full_name": "a/b"},
                    "issue": {"number": 4, "title": "Bug", "pull_request": {}},
                    "comment": {"body": "@agent help", "user": {"login": "ada"}},
                },
                "From @ada",
            ),
            (
                {
                    "action": "completed",
                    "repository": {"full_name": "a/b"},
                    "workflow_run": {
                        "name": "CI",
                        "conclusion": "failure",
                        "head_branch": "main",
                        "head_sha": "abcdef123",
                    },
                },
                "CI: failure on main (abcdef1)",
            ),
            (
                {
                    "action": "published",
                    "repository": {"full_name": "a/b"},
                    "release": {"tag_name": "v1.2", "name": "One two"},
                },
                "v1.2: One two",
            ),
            (
                {
                    "ref": "refs/heads/main",
                    "repository": {"full_name": "a/b"},
                    "pusher": {"name": "ada"},
                    "commits": [{"id": "1234567890", "message": "Add x\n\nbody"}],
                },
                "- 1234567 Add x",
            ),
        ],
        ids=["pull-request", "comment", "workflow-run", "release", "push"],
    )
    def test_each_event_says_what_happened(self, payload, expected):
        assert expected in trigger_events.render_context("github", payload=payload)
