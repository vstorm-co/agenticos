"""The Gmail portal adapter - a mailbox read on a schedule, never pushed to.

Gmail has a push mechanism (`users.watch` into a Cloud Pub/Sub topic) and this
does not use it, deliberately. Push costs a Google Cloud topic and subscription as
*deployment prerequisites*, which for a self-hosted product is real setup burden,
and the `watch` registration expires every seven days and needs something to renew
it. Polling `users.history.list` costs one request per connected mailbox per tick,
needs no infrastructure, and reuses the heartbeat this feature already has. The
latency is one minute, which for "an email arrived, have an agent read it" is
nothing. Push stays an optimisation for a deployment that measures a need for it.

**`historyId` is the cursor, not a timestamp.** Gmail's history is a log of
changes, so asking "what since 12345" is exact where "what since 09:31" is a race
with clock skew and with a message that arrives during the request. The one thing
the log cannot do is answer for a cursor Google has expired - it keeps roughly a
week - and that answers 404, which this treats as "resynchronise from now" rather
than as an error: the alternative is a mailbox that stops firing for ever because
nobody looked at it for eight days.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.portals.base import PolledEvent, PolledEvents, PortalAdapter
from app.services.portals.exceptions import PortalUnreachable

logger = logging.getLogger(__name__)

_API_BASE = "https://gmail.googleapis.com/gmail/v1"
_TIMEOUT = httpx.Timeout(15.0)
# How many messages one tick will read in full. A mailbox that took a mailing-list
# dump between two ticks must not turn one poll into four hundred `messages.get`
# calls and four hundred agent runs; past this the newest are taken and the cursor
# still advances, because the alternative is reading the same backlog for ever.
_MAX_MESSAGES_PER_POLL = 25
# Which parts of a message are read. `metadata` is headers only and cheap; the body
# needs `full`, and the body is the whole point of "draft a reply to this".
_MESSAGE_FORMAT = "full"
_MAX_BODY_CHARS = 20_000


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _header(message: dict[str, Any], name: str) -> str:
    """One header of a Gmail message, by name, case-insensitively."""
    headers = message.get("payload", {}).get("headers") or []
    wanted = name.casefold()
    for entry in headers:
        if str(entry.get("name", "")).casefold() == wanted:
            return str(entry.get("value") or "")
    return ""


def _body_text(part: dict[str, Any], depth: int = 0) -> str:
    """The plain-text body of a message, walking the MIME tree for it.

    `text/plain` is preferred and HTML is the fallback, because what reaches the
    agent should be what a person would read rather than markup it has to strip.
    Bounded by depth: a MIME tree is attacker-shaped input - anybody who can email
    this mailbox chooses it - and a deeply nested one is a stack, not a message.
    """
    if depth > 8:
        return ""
    mime = str(part.get("mimeType") or "")
    data = part.get("body", {}).get("data")
    if isinstance(data, str) and data and mime.startswith("text/"):
        import base64

        try:
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", "replace"
            )
        except (ValueError, TypeError):
            return ""
        return decoded
    plain = ""
    html = ""
    for child in part.get("parts") or []:
        found = _body_text(child, depth + 1)
        if not found:
            continue
        if str(child.get("mimeType") or "").startswith("text/plain"):
            plain = plain or found
        else:
            html = html or found
    return plain or html


class GooglePortalAdapter(PortalAdapter):
    portal_key = "google"

    async def poll(self, *, access_token: str, cursor: dict[str, Any] | None) -> PolledEvents:
        """New messages since the stored `historyId`, and the id to resume from.

        With no cursor this establishes the position and returns nothing: firing an
        agent once per message already sitting in a mailbox, the moment somebody
        connects it, is not what connecting means.
        """
        async with httpx.AsyncClient(base_url=_API_BASE, timeout=_TIMEOUT) as client:
            latest = cursor.get("history_id") if cursor else None
            if not isinstance(latest, str) or not latest:
                return PolledEvents(
                    events=(), cursor={"history_id": await self._now(client, access_token)}
                )
            added, resume = await self._added_since(client, access_token, latest)
            if not added:
                return PolledEvents(events=(), cursor={"history_id": resume})
            events = [
                event
                for message_id in added[-_MAX_MESSAGES_PER_POLL:]
                if (event := await self._message(client, access_token, message_id)) is not None
            ]
            if len(added) > _MAX_MESSAGES_PER_POLL:
                logger.warning(
                    "gmail_poll_truncated",
                    extra={"found": len(added), "read": _MAX_MESSAGES_PER_POLL},
                )
            return PolledEvents(events=tuple(events), cursor={"history_id": resume})

    async def _now(self, client: httpx.AsyncClient, access_token: str) -> str:
        """The mailbox's current `historyId` - where a first poll starts from."""
        profile = await self._get(client, access_token, "/users/me/profile", params=None)
        return str(profile.get("historyId") or "")

    async def _added_since(
        self, client: httpx.AsyncClient, access_token: str, history_id: str
    ) -> tuple[list[str], str]:
        """Message ids added since `history_id`, and the id to store next.

        `historyTypes=messageAdded` narrows the log to arrivals: a label change or
        a read receipt is a history entry too, and firing an agent because somebody
        archived something is not what "a new email" means.

        A 404 means Google has expired that cursor - it keeps about a week - so
        this resynchronises from the mailbox's current position and returns
        nothing. Treating it as an error would leave a mailbox that went unread for
        eight days never firing again.
        """
        added: list[str] = []
        page: str | None = None
        newest = history_id
        for _ in range(10):
            params: dict[str, str] = {
                "startHistoryId": history_id,
                "historyTypes": "messageAdded",
                "maxResults": "100",
            }
            if page:
                params["pageToken"] = page
            try:
                body = await self._get(client, access_token, "/users/me/history", params=params)
            except PortalUnreachable as exc:
                if exc.details.get("status") != 404:
                    raise
                logger.info("gmail_history_expired", extra={"from": history_id})
                return [], await self._now(client, access_token)
            newest = str(body.get("historyId") or newest)
            for record in body.get("history") or []:
                for entry in record.get("messagesAdded") or []:
                    identifier = entry.get("message", {}).get("id")
                    if isinstance(identifier, str) and identifier:
                        added.append(identifier)
            page = body.get("nextPageToken")
            if not page:
                break
        return added, newest

    async def _message(
        self, client: httpx.AsyncClient, access_token: str, message_id: str
    ) -> PolledEvent | None:
        """One message, as the payload the trigger filters already read.

        The keys are the ones `trigger_events` matches on - `subject`, `from`,
        `labels`, `text` - so a polled Gmail event and a posted one are the same
        shape by the time a trigger is chosen. A message that has gone (deleted
        between the history read and this one) is skipped rather than failing the
        batch.
        """
        try:
            body = await self._get(
                client,
                access_token,
                f"/users/me/messages/{message_id}",
                params={"format": _MESSAGE_FORMAT},
            )
        except PortalUnreachable as exc:
            if exc.details.get("status") == 404:
                return None
            raise
        text = _body_text(body.get("payload") or {})
        return PolledEvent(
            # Gmail's own id for the message: stable across polls, so the
            # idempotency claim recognises a message a retried tick reads twice.
            delivery_id=f"gmail:{message_id}",
            payload={
                "subject": _header(body, "Subject"),
                "from": _header(body, "From"),
                "to": _header(body, "To"),
                "labels": [str(one) for one in body.get("labelIds") or []],
                "text": text[:_MAX_BODY_CHARS],
                "snippet": str(body.get("snippet") or ""),
                "message_id": message_id,
            },
        )

    async def _get(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        path: str,
        *,
        params: dict[str, str] | None,
    ) -> dict[str, Any]:
        """One authenticated GET against the Gmail API.

        Raises:
            PortalUnreachable: Anything non-2xx, carrying the status so a caller
                can tell an expired cursor (404) from a revoked grant (401) - and
                nothing of Google's own error text, which echoes the request.
        """
        try:
            response = await client.get(path, headers=_headers(access_token), params=params)
        except httpx.HTTPError as exc:
            raise PortalUnreachable(
                message="Gmail could not be reached",
                details={"portal_key": self.portal_key, "error": exc.__class__.__name__},
            ) from exc
        if response.status_code >= 400:
            raise PortalUnreachable(
                message="Gmail refused the request",
                details={"portal_key": self.portal_key, "status": response.status_code},
            )
        parsed = response.json()
        return parsed if isinstance(parsed, dict) else {}
