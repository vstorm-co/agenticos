"""The wire side of an event trigger - verify a delivery, match it, read it.

An event trigger fires when a signed webhook arrives (a GitHub issue, an inbound
email). Everything source-specific about that delivery lives here as pure
functions, so :class:`app.services.agent_trigger.AgentTriggerService` owns only the
decision to fire and the model owns only the row. Three questions, each dispatched
on the source:

* :func:`verify_signature` - is this delivery authentic? Every source signs the raw
  body with HMAC-SHA256 under the trigger's per-trigger secret; they differ only in
  the header the signature rides in (GitHub's own `X-Hub-Signature-256`, or the
  `X-Signature-256` a relay is configured to send). The comparison is
  constant-time, and an absent or malformed signature is a plain `False`, never an
  exception the caller must remember to catch.
* :func:`event_matches` - does this delivery pass the trigger's filter? A GitHub
  trigger fires only on an `issues` webhook whose action the filter lists (issue
  creation by default); an email trigger on a subject and sender the filter allows;
  the generic webhook always - the sender chose to deliver, so filtering is its job.
* :func:`render_context` - what does the agent need to see? The payload rendered to
  the plain-text block appended to the trigger's prompt, so a run knows which issue,
  email or delivery set it off.

Adding a source is a value in :class:`app.db.models.agent_trigger.EventSource`
and a branch in each of the three functions - nothing on the row and nothing in the
service.
"""

import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from typing import Any

from app.db.models.agent_trigger import EventSource
from app.schemas.agent_trigger import (
    GithubTriggerConfig,
    GmailTriggerConfig,
    OutlookTriggerConfig,
)
from app.services.portals import outlook_place

# Where each source's HMAC-SHA256 signature of the raw body rides. GitHub's is its
# own native header; the API source reuses the same scheme under a generic one.
#
# A source absent here has no inbound door and is refused at the webhook route
# before a signature is looked for: `gmail` and `outlook` are *polled* from a
# connected mailbox, so a signed POST claiming to be one is a delivery nobody
# registered (#1068).
_SIGNATURE_HEADER = {
    EventSource.GITHUB.value: "x-hub-signature-256",
    EventSource.WEBHOOK.value: "x-signature-256",
}

# The generic webhook's optional signed time, and how far it may be from ours.
_TIMESTAMP_HEADER = "x-signature-timestamp"
_TIMESTAMP_TOLERANCE_SECONDS = 300

# How much of a free-text field - a webhook payload, or an issue, email or post
# body - is forwarded to the agent. A model does not need forty kilobytes of
# somebody's text to know what arrived, and an unbounded paste would spend the
# run's budget on reading it.
_CONTEXT_LIMIT = 2000

# The one GitHub webhook this integration acts on. The event type is in the header,
# not the body, so a `pull_request` or a `push` delivery is refused before its
# action is ever considered.
_GITHUB_EVENT_HEADER = "x-github-event"
_GITHUB_ISSUE_EVENT = "issues"

# The provider's own id for one delivery, the key a duplicate is recognised by.
# GitHub reuses `X-GitHub-Delivery` when it re-sends the same delivery; a relay may
# set the generic header. A source that sends none simply is not deduplicated.
_DELIVERY_ID_HEADER = {
    EventSource.GITHUB.value: "x-github-delivery",
    EventSource.WEBHOOK.value: "x-delivery-id",
}


def delivery_id(source: str, headers: Mapping[str, str]) -> str | None:
    """The provider's id for this delivery, or `None` if it sent none.

    Stable across a provider's retries of one delivery - GitHub reuses the
    `X-GitHub-Delivery` UUID - so it is the key an idempotency claim dedups on. A
    source that sends no such header cannot be deduplicated and is fired every
    time; the claim degrades to firing rather than dropping a real event.
    """
    value = headers.get(_DELIVERY_ID_HEADER[source], "").strip()
    return value or None


def accepts_delivery(source: str) -> bool:
    """Whether this source is delivered by an inbound POST at all.

    `gmail` is polled from a connected mailbox, so it has no signed door and no
    per-trigger secret: a POST claiming to be one is a delivery nobody registered.
    Asked *before* a signature is looked for, because the tables above are keyed
    only by the sources that have a door and a bare lookup on one that does not
    would turn a refusal into a `KeyError` and a 500 (#1068).
    """
    return source in _SIGNATURE_HEADER


def verify_signature(
    source: str,
    *,
    secret: str,
    body: bytes,
    headers: Mapping[str, str],
    now: float | None = None,
) -> bool:
    """Whether `body` was signed with `secret` for this source, in constant time.

    **A generic webhook may also sign the time.** With `X-Signature-Timestamp`
    (Unix seconds) the signature covers `{timestamp}.{body}`, and a timestamp more
    than five minutes from `now` fails - Stripe's and Slack's scheme. A body-only
    signature carries no time, so one captured delivery could be sent again for
    ever; with the timestamp it is good for minutes, and dropping the header to
    replay it fails too, since the signature no longer covers the bare body. A
    sender that sends no timestamp is verified as before.

    Both sources sign the exact request bytes with HMAC-SHA256 and send
    `sha256=<hex>`; only the header name differs. A missing or malformed signature
    is `False`, not an error - the caller turns a `False` into one 403 and does
    not otherwise distinguish "no signature" from "wrong signature", which would
    tell an attacker which of the two they achieved. The comparison is over bytes,
    not str: `hmac.compare_digest` raises `TypeError` on a str with a non-ASCII
    character, and a header value is latin-1, so anyone could turn a 403 into a
    500 with one high byte in the signature header. Encoding first makes a
    non-ASCII signature a plain non-match.
    """
    signature = headers.get(_SIGNATURE_HEADER[source], "")
    if not signature.startswith("sha256="):
        return False
    signed = body
    stamp = headers.get(_TIMESTAMP_HEADER, "").strip() if source == EventSource.WEBHOOK else ""
    if stamp:
        if not stamp.isdigit():
            return False
        if abs((time.time() if now is None else now) - int(stamp)) > _TIMESTAMP_TOLERANCE_SECONDS:
            return False
        signed = stamp.encode() + b"." + body
    expected = "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), signature.encode("latin-1", "ignore"))


def event_matches(
    source: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    config: Mapping[str, Any],
) -> bool:
    """Whether a verified delivery passes the trigger's per-source filter."""
    if source == EventSource.GITHUB.value:
        return _github_matches(headers, payload, config)
    if source == EventSource.GMAIL.value:
        return _gmail_matches(payload, config)
    if source == EventSource.OUTLOOK.value:
        return _outlook_matches(payload, config)
    # The generic webhook: the sender chose to deliver, so a verified delivery
    # is a match by definition.
    return True


def render_context(source: str, *, payload: Mapping[str, Any]) -> str:
    """The event, rendered to the block appended to the trigger's prompt."""
    if source == EventSource.GITHUB.value:
        return _github_context(payload)
    if source == EventSource.GMAIL.value:
        return _gmail_context(payload)
    if source == EventSource.OUTLOOK.value:
        return _outlook_context(payload)
    return _webhook_context(payload)


def polled_place(source: str, config: Mapping[str, Any]) -> str | None:
    """Where in the connected account the poller must look for this trigger.

    `None` for a source whose account is read whole (Gmail's history covers the
    mailbox). An Outlook trigger names a folder - in the account's own mailbox or a
    shared one - and Graph is read a folder at a time, so the poller reads exactly
    the places its triggers name.
    """
    if source != EventSource.OUTLOOK.value:
        return None
    parsed = OutlookTriggerConfig.model_validate(dict(config))
    return outlook_place(mailbox=parsed.mailbox, folder=parsed.folder)


def _github_matches(
    headers: Mapping[str, str], payload: Mapping[str, Any], config: Mapping[str, Any]
) -> bool:
    if headers.get(_GITHUB_EVENT_HEADER) != _GITHUB_ISSUE_EVENT:
        return False
    parsed = GithubTriggerConfig.model_validate(dict(config))
    return payload.get("action") in parsed.actions


def _gmail_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    # Substring filters are case-insensitive: an email domain is case-insensitive by
    # spec, so a `@Vstorm.co` filter that never matched `john@vstorm.co`, or a
    # `subject_contains` of "invoice" that missed "Invoice", would fail silently -
    # the trigger simply never fires, with nothing to tell the user why.
    parsed = GmailTriggerConfig.model_validate(dict(config))
    subject = str(payload.get("subject") or "").casefold()
    sender = str(payload.get("from") or "").casefold()
    if parsed.subject_contains is not None and parsed.subject_contains.casefold() not in subject:
        return False
    if parsed.sender_contains is not None and parsed.sender_contains.casefold() not in sender:
        return False
    labels = [str(one) for one in payload.get("labels") or []]
    # Gmail's history reports every message added to the mailbox, its own sends
    # and drafts and spam included. None of those is mail that arrived for the
    # agent: a reply the agent itself sends would fire the trigger again, a loop,
    # and spam would hand anyone who can send an email a run. Only a trigger that
    # names one of these labels asks for it.
    if parsed.label not in _GMAIL_NOT_ARRIVALS and _GMAIL_NOT_ARRIVALS.intersection(labels):
        return False
    # Gmail's own label, matched exactly rather than as a substring: they are
    # identifiers the API answers with (`INBOX`, `IMPORTANT`, `Label_8`), not prose,
    # so a substring would make `Work` match `Workshop`.
    if parsed.label is None:
        return True
    return parsed.label in labels


_GMAIL_NOT_ARRIVALS = frozenset({"SENT", "DRAFT", "SPAM", "TRASH"})


def _outlook_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    # The place first: a message read from one folder never fires a trigger that
    # watches another. The rest as Gmail's - substrings case-insensitive - plus
    # what Outlook itself sets, matched exactly.
    parsed = OutlookTriggerConfig.model_validate(dict(config))
    if payload.get("place") != outlook_place(mailbox=parsed.mailbox, folder=parsed.folder):
        return False
    subject = str(payload.get("subject") or "").casefold()
    sender = str(payload.get("from") or "").casefold()
    if parsed.subject_contains is not None and parsed.subject_contains.casefold() not in subject:
        return False
    if parsed.sender_contains is not None and parsed.sender_contains.casefold() not in sender:
        return False
    if (
        parsed.has_attachments is not None
        and bool(payload.get("has_attachments")) != parsed.has_attachments
    ):
        return False
    if parsed.importance is not None and payload.get("importance") != parsed.importance:
        return False
    if parsed.category is None:
        return True
    categories = [str(one).casefold() for one in payload.get("categories") or []]
    return parsed.category.casefold() in categories


def _clip(text: str) -> str:
    """A free-text field, truncated so one paste cannot dominate the run's message.

    A GitHub issue body runs to 65,536 characters and its author is anyone who can
    open an issue on the watched repo; an email body is whatever the relay
    forwards, also unbounded. The run's budget bounds the spend either way,
    but the cap keeps a single delivery from filling the fired run's prompt with
    text nobody chose to send - the same reason the generic webhook is clipped.
    """
    if len(text) > _CONTEXT_LIMIT:
        return text[:_CONTEXT_LIMIT] + "\n… (truncated)"
    return text


def _github_context(payload: Mapping[str, Any]) -> str:
    issue = payload.get("issue") or {}
    repository = payload.get("repository") or {}
    return (
        f"A GitHub issue was {payload.get('action', 'updated')} "
        f"in {repository.get('full_name', 'a repository')}.\n"
        f"Issue #{issue.get('number', '?')}: {issue.get('title', '')}\n"
        f"{issue.get('html_url', '')}\n\n"
        f"{_clip(str(issue.get('body') or ''))}"
    ).strip()


def _gmail_context(payload: Mapping[str, Any]) -> str:
    return (
        "An email arrived.\n"
        f"From: {payload.get('from', '')}\n"
        f"Subject: {payload.get('subject', '')}\n\n"
        f"{_clip(str(payload.get('body') or payload.get('text') or ''))}"
    ).strip()


def _outlook_context(payload: Mapping[str, Any]) -> str:
    folder = str(payload.get("folder") or "inbox")
    mailbox = payload.get("mailbox")
    where = f"{folder} in {mailbox}" if mailbox else folder
    attachments = [
        str(entry.get("name") or "")
        for entry in payload.get("attachments") or []
        if isinstance(entry, Mapping)
    ]
    lines = [
        "An email arrived in Outlook.",
        f"From: {payload.get('from', '')}",
        f"Subject: {payload.get('subject', '')}",
        f"Folder: {where}",
    ]
    if attachments:
        lines.append(f"Attachments: {', '.join(name for name in attachments if name)}")
    return ("\n".join(lines) + f"\n\n{_clip(str(payload.get('text') or ''))}").strip()


def _webhook_context(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(dict(payload), indent=2, ensure_ascii=False, default=str)
    return f"A webhook delivery arrived.\n\n{_clip(rendered)}"
