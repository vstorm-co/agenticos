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

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from app.services.portals.base import NOWHERE, PolledEvent, PolledEvents, PortalAdapter
from app.services.portals.exceptions import PortalUnreachable
from app.services.portals.mail_auth import authenticated

logger = logging.getLogger(__name__)

_API_BASE = "https://gmail.googleapis.com/gmail/v1"
_TIMEOUT = httpx.Timeout(15.0)
# How many messages one tick will read in full. A mailbox that took a mailing-list
# dump between two ticks must not turn one poll into four hundred `messages.get`
# calls and four hundred agent runs. The unread tail stays in the cursor for
# subsequent ticks, oldest first, so irrelevant mail cannot displace an arrival.
_MAX_MESSAGES_PER_POLL = 25
# Which parts of a message are read. `metadata` is headers only and cheap; the body
# needs `full`, and the body is the whole point of "draft a reply to this".
_MESSAGE_FORMAT = "full"
_MAX_BODY_CHARS = 20_000


def _headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _nested(value: Any, key: str) -> dict[str, Any]:
    """One nested object, or an empty one.

    `value.get(key, {})` is not this: a default applies when the key is *absent*,
    and JSON says `"body": null` as readily as it omits the field - so the chained
    `.get` on the answer is an `AttributeError` on `None`. Which matters more here
    than it reads: a raise out of a poll aborts the tick for every tenant, not
    only the mailbox that produced it.
    """
    nested = value.get(key) if isinstance(value, dict) else None
    return nested if isinstance(nested, dict) else {}


def _header(message: dict[str, Any], name: str) -> str:
    """One header of a Gmail message, by name, case-insensitively."""
    headers = _nested(message, "payload").get("headers") or []
    wanted = name.casefold()
    for entry in headers:
        if str(entry.get("name", "")).casefold() == wanted:
            return str(entry.get("value") or "")
    return ""


def _body_text(part: dict[str, Any]) -> str:
    """Decode the inline bytes of one textual MIME part."""
    mime = str(part.get("mimeType") or "")
    data = _nested(part, "body").get("data")
    if not isinstance(data, str) or not data or not mime.startswith("text/"):
        return ""
    import base64

    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    except ValueError, TypeError:
        return ""


class GooglePortalAdapter(PortalAdapter):
    portal_key = "google"

    async def poll(
        self,
        *,
        access_token: str,
        cursor: dict[str, Any] | None,
        places: Mapping[str, datetime] = NOWHERE,
    ) -> PolledEvents:
        """New messages since the stored `historyId`, and the id to resume from.

        With no cursor this establishes the position and returns nothing: firing an
        agent once per message already sitting in a mailbox, the moment somebody
        connects it, is not what connecting means. `places` is ignored: the history
        covers the whole mailbox, and a trigger narrows by label instead.

        The cursor also names the account it was read from, the address Gmail's
        profile gives, so a consent that switches account can tell this position
        is not the new account's.
        """
        async with httpx.AsyncClient(base_url=_API_BASE, timeout=_TIMEOUT) as client:
            latest = cursor.get("history_id") if cursor else None
            if not isinstance(latest, str) or not latest:
                profile = await self._get(client, access_token, "/users/me/profile", params=None)
                return PolledEvents(
                    events=(),
                    cursor=_with_account(
                        {"history_id": str(profile.get("historyId") or "")},
                        profile.get("emailAddress"),
                    ),
                )
            account = cursor.get("account") if cursor else None
            added, resume = await self._added_since(client, access_token, latest)
            if not added and not (cursor or {}).get("pending_message_ids"):
                return PolledEvents(
                    events=(), cursor=_with_account({"history_id": resume}, account)
                )
            pending = cursor.get("pending_message_ids") if cursor else None
            backlog = (
                [one for one in pending if isinstance(one, str)]
                if isinstance(pending, list)
                else []
            )
            backlog = list(dict.fromkeys([*backlog, *added]))
            events = [
                event
                for message_id in backlog[:_MAX_MESSAGES_PER_POLL]
                if (event := await self._message(client, access_token, message_id)) is not None
            ]
            return PolledEvents(
                events=tuple(events),
                cursor=_with_account(
                    {
                        "history_id": resume,
                        **(
                            {"pending_message_ids": backlog[_MAX_MESSAGES_PER_POLL:]}
                            if len(backlog) > _MAX_MESSAGES_PER_POLL
                            else {}
                        ),
                    },
                    account,
                ),
            )

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
        consumed = history_id
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
                if (exc.details or {}).get("status") != 404:
                    raise
                logger.info("gmail_history_expired", extra={"from": history_id})
                return [], await self._now(client, access_token)
            newest = str(body.get("historyId") or newest)
            for record in body.get("history") or []:
                consumed = str(record.get("id") or consumed)
                for entry in record.get("messagesAdded") or []:
                    identifier = _nested(entry, "message").get("id")
                    if isinstance(identifier, str) and identifier:
                        added.append(identifier)
            page = body.get("nextPageToken")
            if not page:
                break
        return added, consumed if page else newest

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
            if (exc.details or {}).get("status") == 404:
                return None
            raise
        payload = body.get("payload")
        text = await self._body(
            client, access_token, message_id, payload if isinstance(payload, dict) else {}
        )
        sender = _header(body, "From")
        headers = [
            (str(entry.get("name") or ""), str(entry.get("value") or ""))
            for entry in _nested(body, "payload").get("headers") or []
            if isinstance(entry, dict)
        ]
        return PolledEvent(
            # Gmail's own id for the message: stable across polls, so the
            # idempotency claim recognises a message a retried tick reads twice.
            delivery_id=f"gmail:{message_id}",
            payload={
                "subject": _header(body, "Subject"),
                "from": sender,
                # Whether the sender's domain vouched for the `From`, so a filter
                # on the sender cannot be satisfied by an address anybody can type.
                "authenticated": authenticated(headers, sender),
                "to": _header(body, "To"),
                "labels": [str(one) for one in body.get("labelIds") or []],
                "text": text[:_MAX_BODY_CHARS],
                "snippet": str(body.get("snippet") or ""),
                "message_id": message_id,
            },
        )

    async def _body(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        message_id: str,
        part: dict[str, Any],
        depth: int = 0,
    ) -> str:
        """Read textual MIME parts even when Gmail stores their bytes separately."""
        if depth > 8 or part.get("filename"):
            return ""
        mime = str(part.get("mimeType") or "")
        body = _nested(part, "body")
        attachment_id = body.get("attachmentId")
        if mime in {"text/plain", "text/html"} and isinstance(attachment_id, str):
            attachment = await self._get(
                client,
                access_token,
                f"/users/me/messages/{quote(message_id, safe='')}/attachments/{quote(attachment_id, safe='')}",
                params=None,
            )
            return _body_text({**part, "body": attachment})[:_MAX_BODY_CHARS]
        if mime.startswith("text/"):
            return _body_text(part)[:_MAX_BODY_CHARS]
        plain = ""
        fallback = ""
        for child in part.get("parts") or []:
            if not isinstance(child, dict):
                continue
            found = await self._body(client, access_token, message_id, child, depth + 1)
            if str(child.get("mimeType") or "") == "text/plain":
                plain = plain or found
            else:
                fallback = fallback or found
        return plain or fallback

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
        try:
            parsed = response.json()
        except ValueError as exc:
            # An intermediary's HTML error page or a truncated body. Translated
            # into the error `poll_grant` already recovers per mailbox - raised
            # raw it aborted the whole tick and rolled back every other grant's
            # cursor with it.
            raise PortalUnreachable(
                message="Gmail answered with something unreadable",
                details={"portal_key": self.portal_key},
            ) from exc
        return parsed if isinstance(parsed, dict) else {}


def _with_account(cursor: dict[str, Any], account: Any) -> dict[str, Any]:
    """`cursor`, naming the account it was read from when that is known."""
    return (
        {**cursor, "account": account.casefold()}
        if isinstance(account, str) and account
        else cursor
    )
