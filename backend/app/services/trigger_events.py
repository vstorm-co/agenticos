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

import base64
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Mapping
from datetime import datetime
from email.utils import parseaddr
from typing import Any

from app.db.models.agent_trigger import EventSource
from app.schemas.agent_trigger import (
    CalendarTriggerConfig,
    GithubTriggerConfig,
    GmailTriggerConfig,
    GoogleDriveTriggerConfig,
    HubspotTriggerConfig,
    MicrosoftFilesTriggerConfig,
    OutlookTriggerConfig,
    ZendeskTriggerConfig,
)
from app.services.portals import files_place, outlook_place
from app.services.portals.mail_thread import MAX_ID_CHARS, clean_text

logger = logging.getLogger(__name__)

# Where each source's signature rides. GitHub's is its own native header and the
# API source reuses that scheme under a generic one; HubSpot and Zendesk sign in
# schemes of their own, verified by `_hubspot_verified` and `_zendesk_verified`.
#
# A source absent here has no inbound door and is refused at the webhook route
# before a signature is looked for: `gmail` and `outlook` are *polled* from a
# connected mailbox, so a signed POST claiming to be one is a delivery nobody
# registered (#1068).
_SIGNATURE_HEADER = {
    EventSource.GITHUB.value: "x-hub-signature-256",
    EventSource.HUBSPOT.value: "x-hubspot-signature-v3",
    EventSource.WEBHOOK.value: "x-signature-256",
    EventSource.ZENDESK.value: "x-zendesk-webhook-signature",
}

# The generic webhook's optional signed time, and how far it may be from ours.
_TIMESTAMP_HEADER = "x-signature-timestamp"
_TIMESTAMP_TOLERANCE_SECONDS = 300

# How much of a free-text field - a webhook payload, or an issue, email or post
# body - is forwarded to the agent. A model does not need forty kilobytes of
# somebody's text to know what arrived, and an unbounded paste would spend the
# run's budget on reading it.
_CONTEXT_LIMIT = 2000

# GitHub names the webhook in a header, not the body, so a delivery of another
# event than the trigger's is refused before its action is ever considered.
_GITHUB_EVENT_HEADER = "x-github-event"
# The authors `authors: members` lets through: GitHub's own word for the
# repository's people, on the issue, pull request or comment.
_GITHUB_MEMBERS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
# Where each event keeps the thing somebody wrote - whose author is judged.
_GITHUB_AUTHORED = {"issues": "issue", "pull_request": "pull_request", "issue_comment": "comment"}

# The provider's own id for one delivery, the key a duplicate is recognised by.
# GitHub reuses `X-GitHub-Delivery` when it re-sends the same delivery, Zendesk
# its invocation id; a relay may set the generic header. HubSpot sends none and is
# keyed on its events instead (`_hubspot_delivery`). A source that sends none
# simply is not deduplicated.
_DELIVERY_ID_HEADER = {
    EventSource.GITHUB.value: "x-github-delivery",
    EventSource.WEBHOOK.value: "x-delivery-id",
    EventSource.ZENDESK.value: "x-zendesk-webhook-invocation-id",
}

# How many of a HubSpot batch's events the run is told about; HubSpot sends up to
# a hundred, and the agent can look the rest up.
_HUBSPOT_EVENTS_SHOWN = 20


def delivery_id(source: str, headers: Mapping[str, str], payload: Mapping[str, Any]) -> str | None:
    """The provider's id for this delivery, or `None` if it sent none.

    Stable across a provider's retries of one delivery - GitHub reuses the
    `X-GitHub-Delivery` UUID - so it is the key an idempotency claim dedups on. A
    source that sends no such header cannot be deduplicated and is fired every
    time; the claim degrades to firing rather than dropping a real event.
    """
    if source == EventSource.HUBSPOT.value:
        return _hubspot_delivery(payload)
    value = headers.get(_DELIVERY_ID_HEADER[source], "").strip()
    return value or None


def _hubspot_delivery(payload: Mapping[str, Any]) -> str | None:
    """A HubSpot batch's identity: its events, which a retry re-sends unchanged.

    The body itself is not it - each retry bumps every event's `attemptNumber` -
    and `eventId` alone is documented as not unique, so each event is named by its
    subscription, id and time together.
    """
    events = [
        [event.get("subscriptionId"), event.get("eventId"), event.get("occurredAt")]
        for event in _hubspot_events(payload)
    ]
    if not events:
        return None
    digest = hashlib.sha256(json.dumps(events, default=str).encode()).hexdigest()
    return f"hubspot:{digest[:40]}"


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
    url: str | None = None,
    now: float | None = None,
) -> bool:
    """Whether `body` was signed with `secret` for this source, in constant time.

    `url` is the address the provider was given, which HubSpot's signature
    covers; behind a proxy the request's own URL is not it, so the caller passes
    the public one it handed out.

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
    moment = time.time() if now is None else now
    if source == EventSource.HUBSPOT.value:
        return _hubspot_verified(secret, body=body, headers=headers, url=url, now=moment)
    if source == EventSource.ZENDESK.value:
        return _zendesk_verified(secret, body=body, headers=headers, now=moment)
    signature = headers.get(_SIGNATURE_HEADER[source], "")
    if not signature.startswith("sha256="):
        return False
    signed = body
    stamp = headers.get(_TIMESTAMP_HEADER, "").strip() if source == EventSource.WEBHOOK else ""
    if stamp:
        if not stamp.isdigit():
            return False
        if abs(moment - int(stamp)) > _TIMESTAMP_TOLERANCE_SECONDS:
            return False
        signed = stamp.encode() + b"." + body
    expected = "sha256=" + hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return _same(expected, signature)


def _same(expected: str, received: str) -> bool:
    """A constant-time comparison a non-ASCII header turns into a plain mismatch."""
    return hmac.compare_digest(expected.encode(), received.encode("latin-1", "ignore"))


def _hmac_b64(secret: str, signed: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), signed, hashlib.sha256).digest()).decode()


def _hubspot_verified(
    secret: str, *, body: bytes, headers: Mapping[str, str], url: str | None, now: float
) -> bool:
    """HubSpot's v3 signature, or its v1 one where that is all it sends.

    v3 is an HMAC over the method, the URL HubSpot called, the body and a
    millisecond timestamp, which must be within five minutes. HubSpot still signs
    CRM object subscriptions with v1 - a SHA-256 of the secret and the body, no
    time - and refusing it would refuse the deliveries most apps get. A v1
    delivery replayed later is caught by the claim on its events
    (`_hubspot_delivery`), and its known weakness, appending to the hashed bytes,
    cannot produce a body that still parses as JSON.
    """
    v3 = headers.get("x-hubspot-signature-v3", "").strip()
    if v3:
        stamp = headers.get("x-hubspot-request-timestamp", "").strip()
        if url is None or not stamp.isdigit():
            return False
        if abs(now * 1000 - int(stamp)) > _TIMESTAMP_TOLERANCE_SECONDS * 1000:
            return False
        return _same(_hmac_b64(secret, b"POST" + url.encode() + body + stamp.encode()), v3)
    if headers.get("x-hubspot-signature-version", "").strip().casefold() != "v1":
        return False
    expected = hashlib.sha256(secret.encode() + body).hexdigest()
    return _same(expected, headers.get("x-hubspot-signature", "").strip())


def _zendesk_verified(secret: str, *, body: bytes, headers: Mapping[str, str], now: float) -> bool:
    """Zendesk's signature: an HMAC over its ISO timestamp and the body.

    Zendesk sets no window of its own; five minutes is the one the generic
    webhook keeps, and it is what makes the signed time worth having.
    """
    stamp = headers.get("x-zendesk-webhook-signature-timestamp", "").strip()
    try:
        signed_at = datetime.fromisoformat(stamp)
    except ValueError:
        return False
    if signed_at.tzinfo is None or abs(now - signed_at.timestamp()) > _TIMESTAMP_TOLERANCE_SECONDS:
        return False
    signature = headers.get("x-zendesk-webhook-signature", "").strip()
    return _same(_hmac_b64(secret, stamp.encode() + body), signature)


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
    if source == EventSource.HUBSPOT.value:
        return _hubspot_matches(payload, config)
    if source == EventSource.ZENDESK.value:
        parsed = ZendeskTriggerConfig.model_validate(dict(config))
        return parsed.event_types is None or payload.get("type") in parsed.event_types
    if source == EventSource.GOOGLE_DRIVE.value:
        return _google_drive_matches(payload, config)
    if source == EventSource.MICROSOFT_FILES.value:
        return _microsoft_files_matches(payload, config)
    if source in _CALENDARS:
        return _calendar_matches(payload, config)
    # The generic webhook: the sender chose to deliver, so a verified delivery
    # is a match by definition.
    return True


def render_context(source: str, *, payload: Mapping[str, Any]) -> str:
    """The event, rendered to the block appended to the trigger's prompt."""
    if source == EventSource.GITHUB.value:
        return _github_context(payload)
    if source == EventSource.GMAIL.value:
        return clean_text(_gmail_context(payload))
    if source == EventSource.OUTLOOK.value:
        return clean_text(_outlook_context(payload))
    if source == EventSource.HUBSPOT.value:
        return _hubspot_context(payload)
    if source == EventSource.ZENDESK.value:
        return _zendesk_context(payload)
    if source in _FILE_PROVIDERS:
        return _file_context(_FILE_PROVIDERS[source], payload)
    if source in _CALENDARS:
        return _calendar_context(_CALENDARS[source], payload)
    return _webhook_context(payload)


def polled_place(source: str, config: Mapping[str, Any]) -> str | None:
    """Where in the connected account the poller must look for this trigger.

    `None` for a source whose account is read whole (Gmail's history, Drive's
    changes). An Outlook trigger names a folder - in the account's own mailbox or a
    shared one - and Graph is read a folder at a time, so the poller reads exactly
    the places its triggers name; a OneDrive/SharePoint one names a drive the same
    way. A calendar trigger's place is its lead in minutes, which is how the
    adapter knows when before each meeting to announce it (`portals._calendar`).
    """
    if source == EventSource.OUTLOOK.value:
        parsed = OutlookTriggerConfig.model_validate(dict(config))
        return outlook_place(mailbox=parsed.mailbox, folder=parsed.folder)
    if source == EventSource.MICROSOFT_FILES.value:
        return files_place(MicrosoftFilesTriggerConfig.model_validate(dict(config)).site_url)
    if source in _CALENDARS:
        return str(CalendarTriggerConfig.model_validate(dict(config)).minutes_before)
    return None


def _github_matches(
    headers: Mapping[str, str], payload: Mapping[str, Any], config: Mapping[str, Any]
) -> bool:
    parsed = GithubTriggerConfig.model_validate(dict(config))
    event = parsed.event
    if headers.get(_GITHUB_EVENT_HEADER) != event:
        return False
    if event != "push" and payload.get("action") not in (parsed.actions or ()):
        return False
    sender = _mapping(payload.get("sender"))
    login = str(sender.get("login") or "")
    # A bot - an App, Dependabot, the agent's own GitHub App - never sets a
    # trigger off, or an agent that opens issues or comments would fire itself.
    # A workflow run is the exception: a failed check is news whoever pushed.
    if event != "workflow_run" and (sender.get("type") == "Bot" or login.endswith("[bot]")):
        return False
    if parsed.ignore_login and login.casefold() == parsed.ignore_login.casefold():
        return False
    authored = _mapping(payload.get(_GITHUB_AUTHORED.get(event, "")))
    if (
        event in _GITHUB_AUTHORED
        and parsed.authors == "members"
        and authored.get("author_association") not in _GITHUB_MEMBERS
    ):
        return False
    if event == "pull_request":
        # A draft is not ready for anybody; it fires when marked ready instead.
        if payload.get("action") == "opened" and authored.get("draft"):
            return False
        return _on_branch(parsed.branches, _mapping(authored.get("base")).get("ref"))
    if event == "issue_comment":
        body = str(authored.get("body") or "").casefold()
        return parsed.mention is None or parsed.mention.casefold() in body
    if event == "workflow_run":
        run = _mapping(payload.get("workflow_run"))
        if payload.get("action") == "completed" and run.get("conclusion") not in (
            parsed.conclusions or ()
        ):
            return False
        return _on_branch(parsed.branches, run.get("head_branch"))
    if event == "push":
        ref = str(payload.get("ref") or "")
        # A deleted branch is a push with nothing in it, and a tag is not a branch.
        if payload.get("deleted") or not ref.startswith("refs/heads/"):
            return False
        return _on_branch(parsed.branches, ref.removeprefix("refs/heads/"))
    return True


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _on_branch(branches: list[str] | None, branch: Any) -> bool:
    """Whether `branch` is one the filter names - any, when it names none."""
    return branches is None or branch in branches


def _sender_matches(address: str, wanted: str | None) -> bool:
    """Match an address or domain exactly; plain text narrows the real address."""
    if wanted is None:
        return True
    wanted = wanted.strip().casefold()
    if wanted.startswith("@"):
        return address.rpartition("@")[2] == wanted[1:]
    if "@" in wanted:
        return address == wanted
    return wanted in address


def _gmail_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    # Substring filters are case-insensitive: an email domain is case-insensitive by
    # spec, so a `@Vstorm.co` filter that never matched `john@vstorm.co`, or a
    # `subject_contains` of "invoice" that missed "Invoice", would fail silently -
    # the trigger simply never fires, with nothing to tell the user why.
    parsed = GmailTriggerConfig.model_validate(dict(config))
    subject = str(payload.get("subject") or "").casefold()
    sender = parseaddr(str(payload.get("from") or ""))[1].casefold()
    if parsed.subject_contains is not None and parsed.subject_contains.casefold() not in subject:
        return False
    if not _sender_matches(sender, parsed.sender_contains):
        return False
    if not _vouched_for(payload, parsed.authenticated_only, parsed.sender_contains):
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


def _vouched_for(
    payload: Mapping[str, Any], authenticated_only: bool | None, sender_contains: str | None
) -> bool:
    """Whether a message passes the authenticated-sender rule its trigger asks for.

    Unset, the rule is on exactly when the trigger filters on the sender: "mail
    from @acme.com" means mail Acme sent, and the `From` alone is whatever anyone
    typed - a spoofed sender would hand a stranger a run under that filter. A
    message the rule refuses is logged, because a filter that silently never
    fires - an internal relay that signs nothing, say - is otherwise invisible.
    """
    required = authenticated_only if authenticated_only is not None else sender_contains is not None
    if not required or payload.get("authenticated") is True:
        return True
    # The domain, not the address: enough to see which sender is being refused.
    domain = parseaddr(str(payload.get("from") or ""))[1].rpartition("@")[2]
    logger.info("trigger_mail_unauthenticated", extra={"sender_domain": domain})
    return False


def _outlook_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    # The place first: a message read from one folder never fires a trigger that
    # watches another. The rest as Gmail's - substrings case-insensitive - plus
    # what Outlook itself sets, matched exactly.
    parsed = OutlookTriggerConfig.model_validate(dict(config))
    if payload.get("place") != outlook_place(mailbox=parsed.mailbox, folder=parsed.folder):
        return False
    subject = str(payload.get("subject") or "").casefold()
    sender = parseaddr(str(payload.get("from") or ""))[1].casefold()
    if parsed.subject_contains is not None and parsed.subject_contains.casefold() not in subject:
        return False
    if not _sender_matches(sender, parsed.sender_contains):
        return False
    if not _vouched_for(payload, parsed.authenticated_only, parsed.sender_contains):
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
    repository = str(_mapping(payload.get("repository")).get("full_name") or "a repository")
    action = str(payload.get("action") or "updated")
    if "pull_request" in payload:
        pull = _mapping(payload.get("pull_request"))
        return (
            f"A GitHub pull request was {action} in {repository}.\n"
            f"Pull request #{pull.get('number', '?')}: {pull.get('title', '')}\n"
            f"{_mapping(pull.get('head')).get('ref', '?')} -> "
            f"{_mapping(pull.get('base')).get('ref', '?')}\n"
            f"{pull.get('html_url', '')}\n\n"
            f"{_clip(str(pull.get('body') or ''))}"
        ).strip()
    if "comment" in payload:
        comment = _mapping(payload.get("comment"))
        issue = _mapping(payload.get("issue"))
        kind = "pull request" if issue.get("pull_request") else "issue"
        return (
            f"A comment on a GitHub {kind} in {repository}.\n"
            f"{kind.capitalize()} #{issue.get('number', '?')}: {issue.get('title', '')}\n"
            f"From @{_mapping(comment.get('user')).get('login', '?')}: "
            f"{comment.get('html_url', '')}\n\n"
            f"{_clip(str(comment.get('body') or ''))}"
        ).strip()
    if "workflow_run" in payload:
        run = _mapping(payload.get("workflow_run"))
        return (
            f"A GitHub Actions workflow finished in {repository}.\n"
            f"{run.get('name', 'Workflow')}: {run.get('conclusion', '?')} "
            f"on {run.get('head_branch', '?')} ({str(run.get('head_sha') or '')[:7]})\n"
            f"{run.get('html_url', '')}"
        ).strip()
    if "release" in payload:
        release = _mapping(payload.get("release"))
        return (
            f"A GitHub release was {action} in {repository}.\n"
            f"{release.get('tag_name', '?')}: {release.get('name') or ''}\n"
            f"{release.get('html_url', '')}\n\n"
            f"{_clip(str(release.get('body') or ''))}"
        ).strip()
    if "commits" in payload:
        commits = [_mapping(one) for one in payload.get("commits") or []]
        lines = [
            f"- {str(one.get('id') or '')[:7]} {str(one.get('message') or '').splitlines()[0]}"
            for one in commits[:20]
            if str(one.get("message") or "")
        ]
        return (
            f"{len(commits)} commit(s) pushed to "
            f"{str(payload.get('ref') or '').removeprefix('refs/heads/')} in {repository} "
            f"by {_mapping(payload.get('pusher')).get('name', '?')}.\n"
            f"{payload.get('compare', '')}\n\n" + _clip("\n".join(lines))
        ).strip()
    issue = _mapping(payload.get("issue"))
    return (
        f"A GitHub issue was {action} in {repository}.\n"
        f"Issue #{issue.get('number', '?')}: {issue.get('title', '')}\n"
        f"{issue.get('html_url', '')}\n\n"
        f"{_clip(str(issue.get('body') or ''))}"
    ).strip()


def _thread_lines(payload: Mapping[str, Any]) -> list[str]:
    """`Message-ID:` and `Thread:` lines, each only when the mail carried one.

    The Message-ID is the sender's and the thread key the provider's, so each is
    collapsed onto one line - no CR, LF or Unicode line break can start a line of
    the prompt. A value longer than `MAX_ID_CHARS` is dropped, never cut: a clipped
    id would name no message. `references` and `html` stay out of the prompt on
    purpose.
    """
    lines: list[str] = []
    for label, key in (("Message-ID", "rfc_message_id"), ("Thread", "thread_id")):
        value = " ".join(str(payload.get(key) or "").split())
        if value and len(value) <= MAX_ID_CHARS:
            lines.append(f"{label}: {value}")
    return lines


def _gmail_context(payload: Mapping[str, Any]) -> str:
    lines = [
        "An email arrived.",
        f"From: {payload.get('from', '')}",
        f"Subject: {payload.get('subject', '')}",
        *_thread_lines(payload),
    ]
    body = _clip(str(payload.get("body") or payload.get("text") or ""))
    return ("\n".join(lines) + f"\n\n{body}").strip()


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
    lines.extend(_thread_lines(payload))
    return ("\n".join(lines) + f"\n\n{_clip(str(payload.get('text') or ''))}").strip()


def _hubspot_events(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The events of a HubSpot batch, which arrives as `{"events": [...]}`."""
    return [event for event in payload.get("events") or [] if isinstance(event, Mapping)]


def _hubspot_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    parsed = HubspotTriggerConfig.model_validate(dict(config))
    return any(
        (
            parsed.subscription_types is None
            or event.get("subscriptionType") in parsed.subscription_types
        )
        and (parsed.property_names is None or event.get("propertyName") in parsed.property_names)
        for event in _hubspot_events(payload)
    )


def _hubspot_context(payload: Mapping[str, Any]) -> str:
    events = _hubspot_events(payload)
    lines = [f"Events from HubSpot ({len(events)}):"]
    for event in events[:_HUBSPOT_EVENTS_SHOWN]:
        line = f"- {event.get('subscriptionType', 'event')} on object {event.get('objectId', '?')}"
        if event.get("propertyName") is not None:
            line += f": {event.get('propertyName')} = {_clip(str(event.get('propertyValue', '')))}"
        lines.append(
            f"{line} (portal {event.get('portalId', '?')}, at {event.get('occurredAt', '?')})"
        )
    if len(events) > _HUBSPOT_EVENTS_SHOWN:
        lines.append(f"...and {len(events) - _HUBSPOT_EVENTS_SHOWN} more.")
    return "\n".join(lines)


def _zendesk_context(payload: Mapping[str, Any]) -> str:
    # An event-subscribed webhook names its event; one a Zendesk rule calls is
    # whatever JSON its admin wrote, so it is shown whole, like a generic webhook.
    kind = payload.get("type")
    title = f"A Zendesk event arrived: {kind}." if kind else "A Zendesk webhook arrived."
    rendered = json.dumps(dict(payload), indent=2, ensure_ascii=False, default=str)
    return f"{title}\n\n{_clip(rendered)}"


_FILE_PROVIDERS = {
    EventSource.GOOGLE_DRIVE.value: "Google Drive",
    EventSource.MICROSOFT_FILES.value: "OneDrive/SharePoint",
}
_CALENDARS = {
    EventSource.GOOGLE_CALENDAR.value: "Google Calendar",
    EventSource.OUTLOOK_CALENDAR.value: "Outlook",
}


def _file_passes(
    payload: Mapping[str, Any],
    *,
    change: str,
    name_contains: str | None,
    include_own_changes: bool,
) -> bool:
    """The filters both file sources share: which change, which name, whose edit."""
    if change != "any" and payload.get("change") != change:
        return False
    if (
        name_contains is not None
        and name_contains.casefold() not in str(payload.get("name") or "").casefold()
    ):
        return False
    # The account's own edits are an agent writing through the same grant as often
    # as a person: counted, the agent would set itself off.
    return include_own_changes or payload.get("by_account") is not True


def _google_drive_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    parsed = GoogleDriveTriggerConfig.model_validate(dict(config))
    if parsed.folder_id is not None and parsed.folder_id not in (payload.get("parents") or []):
        return False
    return _file_passes(
        payload,
        change=parsed.change,
        name_contains=parsed.name_contains,
        include_own_changes=parsed.include_own_changes,
    )


def _microsoft_files_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    # The place first, as Outlook's: a file read in one library never fires a
    # trigger that watches another.
    parsed = MicrosoftFilesTriggerConfig.model_validate(dict(config))
    if payload.get("place") != files_place(parsed.site_url):
        return False
    if parsed.folder_path is not None:
        wanted = parsed.folder_path.strip("/").casefold()
        folder = str(payload.get("folder") or "").casefold()
        if folder != wanted and not folder.startswith(f"{wanted}/"):
            return False
    return _file_passes(
        payload,
        change=parsed.change,
        name_contains=parsed.name_contains,
        include_own_changes=parsed.include_own_changes,
    )


def _calendar_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    # Announced once per lead (`portals._calendar`), so a trigger takes the
    # announcement made for its own lead and no other.
    parsed = CalendarTriggerConfig.model_validate(dict(config))
    if payload.get("lead_minutes") != parsed.minutes_before:
        return False
    if parsed.external_only and not payload.get("external_attendees"):
        return False
    subject = str(payload.get("subject") or "").casefold()
    if parsed.subject_contains is not None and parsed.subject_contains.casefold() not in subject:
        return False
    if parsed.attendee_contains is None:
        return True
    wanted = parsed.attendee_contains.casefold()
    return any(wanted in str(address) for address in payload.get("attendees") or [])


def _file_context(provider: str, payload: Mapping[str, Any]) -> str:
    verb = "added" if payload.get("change") == "created" else "changed"
    lines = [
        f"A file was {verb} in {provider}.",
        f"Name: {payload.get('name', '')}",
        f"Type: {payload.get('mime_type', '')}",
        f"Changed by: {payload.get('modified_by', '')}",
        f"Link: {payload.get('url', '')}",
    ]
    if payload.get("folder"):
        lines.append(f"Folder: {payload['folder']}")
    if payload.get("site_url"):
        lines.append(f"Site: {payload['site_url']}")
    return "\n".join(lines)


def _calendar_context(provider: str, payload: Mapping[str, Any]) -> str:
    attendees = ", ".join(str(one) for one in payload.get("attendees") or [])
    external = ", ".join(str(one) for one in payload.get("external_attendees") or [])
    lines = [
        f"A meeting in {provider} starts in {payload.get('minutes_until_start', '?')} minutes.",
        f"Subject: {payload.get('subject', '')}",
        f"Starts: {payload.get('starts_at', '')}",
        f"Ends: {payload.get('ends_at') or ''}",
        f"Organizer: {payload.get('organizer', '')}",
        f"Attendees: {attendees}",
    ]
    if external:
        lines.append(f"From outside the organization: {external}")
    for label, key in (("Join", "join_url"), ("Location", "location"), ("Link", "url")):
        if payload.get(key):
            lines.append(f"{label}: {payload[key]}")
    return ("\n".join(lines) + f"\n\n{_clip(str(payload.get('description') or ''))}").strip()


def _webhook_context(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(dict(payload), indent=2, ensure_ascii=False, default=str)
    return f"A webhook delivery arrived.\n\n{_clip(rendered)}"
