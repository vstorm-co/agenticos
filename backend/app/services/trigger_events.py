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
  a LinkedIn trigger on an author and text the filter allows; the generic webhook
  always - the sender chose to deliver, so filtering is its job.
* :func:`render_context` - what does the agent need to see? The payload rendered to
  the plain-text block appended to the trigger's prompt, so a run knows which issue,
  email or post set it off.

Adding a third source is a value in :class:`app.db.models.agent_trigger.EventSource`
and a branch in each of the three functions - nothing on the row and nothing in the
service.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from app.db.models.agent_trigger import EventSource
from app.schemas.agent_trigger import (
    EmailTriggerConfig,
    GithubTriggerConfig,
    LinkedinTriggerConfig,
)

# Where each source's HMAC-SHA256 signature of the raw body rides. GitHub's is its
# own native header; every relay-delivered source reuses the same scheme under a
# header the relay sets.
_SIGNATURE_HEADER = {
    EventSource.GITHUB.value: "x-hub-signature-256",
    EventSource.EMAIL.value: "x-signature-256",
    EventSource.LINKEDIN.value: "x-signature-256",
    EventSource.WEBHOOK.value: "x-signature-256",
}

# How much of an arbitrary payload the generic webhook forwards to the agent. A
# model does not need forty kilobytes of somebody's JSON to know what arrived,
# and an unbounded paste would spend the run's budget on reading it.
_WEBHOOK_CONTEXT_LIMIT = 2000

# The one GitHub webhook this integration acts on. The event type is in the header,
# not the body, so a `pull_request` or a `push` delivery is refused before its
# action is ever considered.
_GITHUB_EVENT_HEADER = "x-github-event"
_GITHUB_ISSUE_EVENT = "issues"


def verify_signature(source: str, *, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    """Whether `body` was signed with `secret` for this source, in constant time.

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
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
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
    if source == EventSource.EMAIL.value:
        return _email_matches(payload, config)
    if source == EventSource.LINKEDIN.value:
        return _linkedin_matches(payload, config)
    # The generic webhook: the sender chose to deliver, so a verified delivery
    # is a match by definition.
    return True


def render_context(source: str, *, payload: Mapping[str, Any]) -> str:
    """The event, rendered to the block appended to the trigger's prompt."""
    if source == EventSource.GITHUB.value:
        return _github_context(payload)
    if source == EventSource.EMAIL.value:
        return _email_context(payload)
    if source == EventSource.LINKEDIN.value:
        return _linkedin_context(payload)
    return _webhook_context(payload)


def _github_matches(
    headers: Mapping[str, str], payload: Mapping[str, Any], config: Mapping[str, Any]
) -> bool:
    if headers.get(_GITHUB_EVENT_HEADER) != _GITHUB_ISSUE_EVENT:
        return False
    parsed = GithubTriggerConfig.model_validate(dict(config))
    return payload.get("action") in parsed.actions


def _email_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    parsed = EmailTriggerConfig.model_validate(dict(config))
    subject = str(payload.get("subject") or "")
    sender = str(payload.get("from") or "")
    if parsed.subject_contains is not None and parsed.subject_contains not in subject:
        return False
    return parsed.sender_contains is None or parsed.sender_contains in sender


def _github_context(payload: Mapping[str, Any]) -> str:
    issue = payload.get("issue") or {}
    repository = payload.get("repository") or {}
    return (
        f"A GitHub issue was {payload.get('action', 'updated')} "
        f"in {repository.get('full_name', 'a repository')}.\n"
        f"Issue #{issue.get('number', '?')}: {issue.get('title', '')}\n"
        f"{issue.get('html_url', '')}\n\n"
        f"{issue.get('body') or ''}"
    ).strip()


def _email_context(payload: Mapping[str, Any]) -> str:
    return (
        "An email arrived.\n"
        f"From: {payload.get('from', '')}\n"
        f"Subject: {payload.get('subject', '')}\n\n"
        f"{payload.get('body') or payload.get('text') or ''}"
    ).strip()


def _linkedin_matches(payload: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    parsed = LinkedinTriggerConfig.model_validate(dict(config))
    author = str(payload.get("author") or "")
    text = str(payload.get("text") or payload.get("body") or "")
    if parsed.author_contains is not None and parsed.author_contains not in author:
        return False
    return parsed.text_contains is None or parsed.text_contains in text


def _linkedin_context(payload: Mapping[str, Any]) -> str:
    return (
        "A LinkedIn post arrived.\n"
        f"Author: {payload.get('author', '')}\n"
        f"{payload.get('url', '')}\n\n"
        f"{payload.get('text') or payload.get('body') or ''}"
    ).strip()


def _webhook_context(payload: Mapping[str, Any]) -> str:
    rendered = json.dumps(dict(payload), indent=2, ensure_ascii=False, default=str)
    if len(rendered) > _WEBHOOK_CONTEXT_LIMIT:
        rendered = rendered[:_WEBHOOK_CONTEXT_LIMIT] + "\n… (truncated)"
    return f"A webhook delivery arrived.\n\n{rendered}"
