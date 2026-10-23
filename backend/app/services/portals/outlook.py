"""The Outlook portal adapter - Microsoft 365 mail read on a schedule, like Gmail.

Polled for the reason Gmail is: Graph change notifications would cut the minute
of latency, but a message subscription lives at most 10,080 minutes and has to be
renewed, validated and watched through lifecycle notifications. Polling costs a
request per watched folder per tick and needs nothing outside this deployment.

**Graph reports new mail one folder at a time.** There is no mailbox-wide log like
Gmail's history, so the poller reads exactly the folders the organization's
Outlook triggers name - a *place*, the pair of a mailbox (the account's own, or a
shared one it can read) and a folder in it - and keeps one delta link per place in
the cursor. A place nobody watches any more drops out of the cursor; one a new
trigger names is started on the next tick.

**A delta reports changes, not arrivals.** A message marked read comes back as
readily as one that just landed, so each place also records when it was last read,
and only a message received after that (less a few minutes for clock skew) is an
event. What the slack lets through twice, the delivery-id claim suppresses.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, unquote

import httpx

from app.services.portals.base import NOWHERE, PolledEvent, PolledEvents, PortalAdapter
from app.services.portals.exceptions import PortalUnreachable

logger = logging.getLogger(__name__)

_API_BASE = "https://graph.microsoft.com/v1.0"
_TIMEOUT = httpx.Timeout(15.0)
# The same bounds as Gmail's, for the same reasons: a mailing-list dump between two
# ticks must not become hundreds of reads and runs, and a body is clipped before it
# is stored in an event.
_MAX_MESSAGES_PER_POLL = 25
_MAX_BODY_CHARS = 20_000
_MAX_ATTACHMENTS = 20
# How many delta pages one place may take per tick. Past it the next link is kept
# as the cursor and the next tick carries on from there.
_MAX_PAGES = 10
# How far before the previous read a message may have been received and still be
# news. Covers the skew between this clock and Exchange's; well inside the
# delivery-id claim's own window, so what it lets through twice fires once.
_SKEW = timedelta(minutes=5)
# Every folder Graph addresses by name, whatever the mailbox's language - the
# `mailFolder` resource's table of well-known names. Anything else is a path of
# display names.
_WELL_KNOWN_FOLDERS = frozenset(
    {
        "archive",
        "clutter",
        "conflicts",
        "conversationhistory",
        "deleteditems",
        "drafts",
        "inbox",
        "junkemail",
        "localfailures",
        "msgfolderroot",
        "outbox",
        "recoverableitemsdeletions",
        "scheduled",
        "searchfolders",
        "sentitems",
        "serverfailures",
        "syncissues",
    }
)
# What Graph answers for a delta link whose sync state it dropped. Outlook keeps
# its delta tokens in a cache of no fixed lifetime, and the answer is a 40X
# carrying one of these codes - sometimes a 410, not always.
_SYNC_LOST = frozenset({"syncstatenotfound", "syncstateinvalid", "resyncrequired"})
# Immutable ids, so a message keeps its id - and its delivery id - when it moves.
_PREFER_IDS = 'IdType="ImmutableId"'
_MESSAGE_FIELDS = (
    "id,subject,from,toRecipients,receivedDateTime,hasAttachments,importance,"
    "categories,body,bodyPreview,isDraft"
)


def place_key(*, mailbox: str | None, folder: str) -> str:
    """The one spelling of a place, shared by the trigger that names it and the poller.

    Case-folded, because neither an address nor a folder's display name is
    case-sensitive in Exchange, and two triggers spelling `Inbox` and `inbox` are
    the same folder to read once. Each half is escaped, because `|` is allowed in
    an address's local part and in a folder's name.
    """
    return f"{_escape((mailbox or '').casefold())}|{_escape(folder.strip().strip('/').casefold())}"


def _escape(part: str) -> str:
    # `%` first, so every `%XX` in a key is one written here and `unquote` reverses
    # exactly this.
    return part.replace("%", "%25").replace("|", "%7C")


def _place(key: str) -> tuple[str | None, str]:
    mailbox, _, folder = key.partition("|")
    return unquote(mailbox) or None, unquote(folder)


def _mailbox_path(mailbox: str | None) -> str:
    return "/me" if mailbox is None else f"/users/{quote(mailbox, safe='@')}"


def _odata_literal(value: str) -> str:
    """A string inside an OData filter, quoted the one way OData escapes a quote."""
    return "'" + value.replace("'", "''") + "'"


def _received(item: Mapping[str, Any]) -> datetime | None:
    raw = item.get("receivedDateTime")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _address(entry: Any) -> str:
    """`Name <address>`, the shape Gmail's `From` header has, from a Graph recipient."""
    email = entry.get("emailAddress") if isinstance(entry, dict) else None
    if not isinstance(email, dict):
        return ""
    name = str(email.get("name") or "")
    address = str(email.get("address") or "")
    if name and address and name != address:
        return f"{name} <{address}>"
    return address or name


class _PlaceUnreadable(Exception):
    """The account cannot read this mailbox or folder - gone, renamed or not shared."""


class OutlookPortalAdapter(PortalAdapter):
    portal_key = "microsoft"

    async def poll(
        self,
        *,
        access_token: str,
        cursor: dict[str, Any] | None,
        places: Mapping[str, datetime] = NOWHERE,
    ) -> PolledEvents:
        """New messages in each watched place, and the cursor to resume from.

        With no cursor this records when the account was connected and returns
        nothing - the base contract: connecting a mailbox fires nothing on the mail
        already in it. A place first read later starts from the later of that
        moment and when its earliest trigger was made, so a trigger created a
        minute before the tick still sees the message that arrived in that minute.

        The cursor names the account it was read from by its Inbox's id - constant
        for a mailbox, different in every other, and readable with `Mail.Read`
        alone where `/me` needs `User.Read` - so a consent that switches account
        can tell the folder ids and delta links here are not the new account's.
        """
        now = datetime.now(UTC)
        connected = _connected_at(cursor)
        if connected is None:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                inbox = await self._get(
                    client,
                    access_token,
                    f"{_API_BASE}/me/mailFolders/inbox",
                    params={"$select": "id"},
                )
            fresh: dict[str, Any] = {"connected_at": now.isoformat(), "places": {}}
            if isinstance(inbox.get("id"), str) and inbox["id"]:
                fresh["account"] = inbox["id"]
            return PolledEvents(events=(), cursor=fresh)
        account = cursor.get("account") if isinstance(cursor, dict) else None
        previous = cursor.get("places") if isinstance(cursor, dict) else None
        states: dict[str, Any] = previous if isinstance(previous, dict) else {}
        found: list[tuple[datetime, str, str]] = []
        next_states: dict[str, Any] = {}
        unreadable: set[str] = set()
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for key, watched_since in places.items():
                state = states.get(key)
                try:
                    ids, next_states[key] = await self._read_place(
                        client,
                        access_token,
                        key,
                        state=state if isinstance(state, dict) else None,
                        floor=max(watched_since, connected),
                        now=now,
                    )
                except _PlaceUnreadable:
                    logger.info("outlook_place_unreadable", extra={"place": key})
                    unreadable.add(key)
                    continue
                found += [(received, key, message_id) for received, message_id in ids]
            found.sort()
            if len(found) > _MAX_MESSAGES_PER_POLL:
                logger.warning(
                    "outlook_poll_truncated",
                    extra={"found": len(found), "read": _MAX_MESSAGES_PER_POLL},
                )
            events = [
                event
                for _received_at, key, message_id in found[-_MAX_MESSAGES_PER_POLL:]
                if (event := await self._message(client, access_token, key, message_id)) is not None
            ]
        return PolledEvents(
            events=tuple(events),
            cursor={
                "connected_at": connected.isoformat(),
                "places": next_states,
                **({"account": account} if isinstance(account, str) else {}),
            },
            unreadable=frozenset(unreadable),
        )

    async def _read_place(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        key: str,
        *,
        state: dict[str, Any] | None,
        floor: datetime,
        now: datetime,
    ) -> tuple[list[tuple[datetime, str]], dict[str, Any]]:
        """The ids of messages received in one place since its floor, and its new state.

        A place with a stored link resumes from it, and anything received before
        the previous read (less the skew) is a change to old mail, not an arrival.
        A new place - or one whose link Graph has expired, which answers 410 - is
        started with a delta filtered to what was received since the floor, so the
        first read is the mail that is news and not the whole folder.
        """
        mailbox, folder = _place(key)
        folder_id = state.get("folder_id") if state else None
        if not isinstance(folder_id, str) or not folder_id:
            folder_id = await self._folder_id(client, access_token, mailbox, folder)
        read_at = _parse(state.get("read_at")) if state else None
        unfinished = _parse(state.get("floor")) if state else None
        if unfinished is not None:
            # A round stopped at the page bound carries on with the floor it began
            # with: the rest of that snapshot is as old as the part already read,
            # and the later read time would drop it.
            floor = unfinished
        elif read_at is not None:
            floor = read_at - _SKEW
        stored = state.get("link") if state else None
        # The link is ours, but it carries the bearer token's destination: only
        # Graph's own address is ever asked.
        link = stored if isinstance(stored, str) and stored.startswith(_API_BASE + "/") else None
        ids: list[tuple[datetime, str]] = []
        found_again = state is None or state.get("folder_id") != folder_id
        for _ in range(_MAX_PAGES):
            if link is None:
                link = _first_delta(mailbox, folder_id, floor)
            try:
                body = await self._get(client, access_token, link, params=None)
            except PortalUnreachable as exc:
                details = exc.details or {}
                if details.get("status") == 410 or _SYNC_LOST.intersection(
                    details.get("codes", ())
                ):
                    logger.info("outlook_delta_expired", extra={"place": key})
                    link = None
                    continue
                if details.get("status") not in {403, 404}:
                    raise
                if found_again:
                    raise _PlaceUnreadable from exc
                # The folder id this place kept no longer opens: the folder was
                # deleted and made again, or renamed. Its path is looked up once
                # more before the place counts as unreadable.
                logger.info("outlook_folder_moved", extra={"place": key})
                folder_id = await self._folder_id(client, access_token, mailbox, folder)
                found_again = True
                link = None
                continue
            for item in body.get("value") or []:
                if not isinstance(item, dict) or "@removed" in item or item.get("isDraft"):
                    continue
                received = _received(item)
                identifier = item.get("id")
                if received is None or not isinstance(identifier, str) or received < floor:
                    continue
                ids.append((received, identifier))
            following = body.get("@odata.nextLink")
            final = body.get("@odata.deltaLink")
            link = following if isinstance(following, str) else final
            if not isinstance(following, str):
                break
        else:
            return ids, {
                "folder_id": folder_id,
                "link": link,
                "read_at": read_at.isoformat() if read_at else None,
                "floor": floor.isoformat(),
            }
        state_link = link if isinstance(link, str) else None
        return ids, {"folder_id": folder_id, "link": state_link, "read_at": now.isoformat()}

    async def _folder_id(
        self, client: httpx.AsyncClient, access_token: str, mailbox: str | None, folder: str
    ) -> str:
        """The id of a folder named by a well-known name or a path of display names.

        `Inbox/Invoices` is the common case: a mail rule files a slice of the inbox
        into a subfolder, and that subfolder is what somebody wants an agent to read.

        Raises:
            _PlaceUnreadable: No such folder, or a mailbox the account cannot read.
        """
        segments = [segment for segment in folder.split("/") if segment]
        if not segments:
            segments = ["inbox"]
        base = f"{_API_BASE}{_mailbox_path(mailbox)}"
        current: str | None = None
        for index, segment in enumerate(segments):
            if index == 0 and segment in _WELL_KNOWN_FOLDERS:
                path = f"{base}/mailFolders/{segment}"
                found = await self._readable(client, access_token, path, params={"$select": "id"})
            else:
                parent = (
                    f"{base}/mailFolders"
                    if current is None
                    else f"{base}/mailFolders/{quote(current, safe='')}/childFolders"
                )
                listing = await self._readable(
                    client,
                    access_token,
                    parent,
                    params={
                        "$filter": f"displayName eq {_odata_literal(segment)}",
                        "$select": "id",
                    },
                )
                matches = listing.get("value") or []
                found = matches[0] if matches and isinstance(matches[0], dict) else {}
            identifier = found.get("id")
            if not isinstance(identifier, str) or not identifier:
                raise _PlaceUnreadable
            current = identifier
        assert current is not None
        return current

    async def _readable(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        url: str,
        *,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """A GET whose 403 or 404 means the place, not the grant, is the problem."""
        try:
            return await self._get(client, access_token, url, params=params)
        except PortalUnreachable as exc:
            if (exc.details or {}).get("status") in {403, 404}:
                raise _PlaceUnreadable from exc
            raise

    async def _message(
        self, client: httpx.AsyncClient, access_token: str, key: str, message_id: str
    ) -> PolledEvent | None:
        """One message, as the payload an Outlook trigger's filter reads.

        The body is asked for as text - Exchange converts an HTML message itself -
        so the run reads what a person would rather than markup. A message deleted
        between the delta and this read is skipped rather than failing the batch.
        """
        mailbox, folder = _place(key)
        base = f"{_API_BASE}{_mailbox_path(mailbox)}/messages/{quote(message_id, safe='')}"
        try:
            message = await self._get(
                client,
                access_token,
                base,
                params={"$select": _MESSAGE_FIELDS},
                prefer=f'outlook.body-content-type="text", {_PREFER_IDS}',
            )
        except PortalUnreachable as exc:
            if (exc.details or {}).get("status") == 404:
                return None
            raise
        attachments: list[dict[str, Any]] = []
        if message.get("hasAttachments"):
            listing = await self._get(
                client,
                access_token,
                f"{base}/attachments",
                params={"$select": "name,contentType,size,isInline"},
            )
            attachments = [
                {
                    "name": str(entry.get("name") or ""),
                    "content_type": str(entry.get("contentType") or ""),
                    "size": entry.get("size") if isinstance(entry.get("size"), int) else None,
                }
                for entry in listing.get("value") or []
                if isinstance(entry, dict) and not entry.get("isInline")
            ][:_MAX_ATTACHMENTS]
        body = message.get("body")
        text = str(body.get("content") or "") if isinstance(body, dict) else ""
        return PolledEvent(
            # Immutable, so a retried tick that reads the message twice - or a
            # move between two watched folders - is recognised by the claim.
            delivery_id=f"outlook:{message_id}",
            payload={
                "place": key,
                "mailbox": mailbox,
                "folder": folder,
                "subject": str(message.get("subject") or ""),
                "from": _address(message.get("from")),
                "to": ", ".join(
                    address
                    for entry in message.get("toRecipients") or []
                    if (address := _address(entry))
                ),
                "categories": [str(one) for one in message.get("categories") or []],
                "importance": str(message.get("importance") or "normal"),
                "has_attachments": bool(message.get("hasAttachments")),
                "attachments": attachments,
                "text": text[:_MAX_BODY_CHARS],
                "snippet": str(message.get("bodyPreview") or ""),
                "message_id": message_id,
                "received_at": str(message.get("receivedDateTime") or ""),
            },
        )

    async def _get(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        url: str,
        *,
        params: dict[str, str] | None,
        prefer: str = f"odata.maxpagesize=50, {_PREFER_IDS}",
    ) -> dict[str, Any]:
        """One authenticated GET against Microsoft Graph.

        Raises:
            PortalUnreachable: Anything non-2xx, carrying the status and Graph's
                error codes so a caller can tell an expired delta (410, or a
                `syncStateNotFound`) and a folder it may not read (403, 404) from a
                refused grant (401) - and nothing of Graph's own error text, which
                can echo the request. The code is machine-readable and documented
                as the one part of an error to depend on.
        """
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            # Listed as required on the delta request, harmless on the rest.
            "Content-Type": "application/json",
            "Prefer": prefer,
        }
        try:
            response = await client.get(url, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise PortalUnreachable(
                message="Microsoft Graph could not be reached",
                details={"portal_key": self.portal_key, "error": exc.__class__.__name__},
            ) from exc
        if response.status_code >= 400:
            details: dict[str, Any] = {
                "portal_key": self.portal_key,
                "status": response.status_code,
            }
            codes = _error_codes(response)
            if codes:
                details["codes"] = codes
            raise PortalUnreachable(message="Microsoft Graph refused the request", details=details)
        try:
            parsed = response.json()
        except ValueError as exc:
            raise PortalUnreachable(
                message="Microsoft Graph answered with something unreadable",
                details={"portal_key": self.portal_key},
            ) from exc
        return parsed if isinstance(parsed, dict) else {}


def _error_codes(response: httpx.Response) -> list[str]:
    """Graph's error codes, case-folded, outermost first - `error.code` and each nested one.

    Only the codes: the `message` beside them can echo the request and is no part
    of the contract. All of them, because which level carries the specific one
    (`syncStateNotFound` under a generic `invalidRequest`, or on its own) is not
    fixed.
    """
    try:
        body = response.json()
    except ValueError:
        return []
    error = body.get("error") if isinstance(body, dict) else None
    codes: list[str] = []
    while isinstance(error, dict):
        if isinstance(error.get("code"), str):
            codes.append(error["code"].casefold())
        error = error.get("innerError") or error.get("innererror")
    return codes


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _connected_at(cursor: Mapping[str, Any] | None) -> datetime | None:
    return _parse(cursor.get("connected_at")) if cursor else None


def _first_delta(mailbox: str | None, folder_id: str, floor: datetime) -> str:
    """The first delta request for a place, filtered to mail received since `floor`.

    `receivedDateTime ge` is the one filter a message delta accepts, and it is what
    keeps a first read from walking every message the folder holds.
    """
    stamp = floor.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = httpx.QueryParams(
        {"$select": "id,receivedDateTime,isDraft", "$filter": f"receivedDateTime ge {stamp}"}
    )
    return (
        f"{_API_BASE}{_mailbox_path(mailbox)}/mailFolders/{quote(folder_id, safe='')}"
        f"/messages/delta?{params}"
    )
