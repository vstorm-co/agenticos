"""The OneDrive and SharePoint portal adapter - new and changed files, read on a schedule.

Graph reports a drive's changes through `delta`, one drive at a time, so like
Outlook's folders the poller reads exactly the *places* the organization's
triggers name: the account's own OneDrive, or a SharePoint site's document
library by the site's address. Each place keeps its delta link in the cursor.

A new place starts from its trigger's creation timestamp, so the first tick
includes changes since the trigger was saved without walking earlier history. A link Graph has dropped (410, or a lost-sync code)
starts again the same way. A site that does not exist or that the account
cannot read is unreadable, and the triggers on it are turned off with a reason.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import httpx

from app.services.portals import _files
from app.services.portals._api import TIMEOUT, get_json, nested
from app.services.portals.base import NOWHERE, PolledEvents, PortalAdapter
from app.services.portals.exceptions import PortalUnreachable

logger = logging.getLogger(__name__)

_API_BASE = "https://graph.microsoft.com/v1.0"
_MAX_PAGES = 10
_SYNC_LOST = frozenset({"syncstatenotfound", "syncstateinvalid", "resyncrequired"})


def place_key(site_url: str | None) -> str:
    """The one spelling of a place: empty for the own OneDrive, else the site's address.

    Case-folded and without a trailing slash, so two triggers naming one site
    spell it alike and it is read once.
    """
    return (site_url or "").strip().rstrip("/").casefold()


class _PlaceUnreadable(Exception):
    """The account cannot read this site or library - gone, renamed or not shared."""


class MicrosoftFilesPortalAdapter(PortalAdapter):
    portal_key = "microsoft_files"

    async def poll(
        self,
        *,
        access_token: str,
        cursor: dict[str, Any] | None,
        places: Mapping[str, datetime] = NOWHERE,
    ) -> PolledEvents:
        """Files created or changed in each watched place, and the cursor to resume from.

        With no cursor this records the consenting user's id and returns nothing.
        Identifying the account does not require a personal OneDrive.
        """
        now = datetime.now(UTC)
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if not cursor or not isinstance(cursor.get("account"), str):
                user = await self._get(client, access_token, f"{_API_BASE}/me", {"$select": "id"})
                identifier = user.get("id")
                if not isinstance(identifier, str) or not identifier:
                    raise PortalUnreachable(message="Microsoft Graph did not identify the account")
                return PolledEvents(
                    events=(), cursor={"account": identifier, "user_id": identifier, "places": {}}
                )
            previous = cursor.get("places")
            states: dict[str, Any] = previous if isinstance(previous, dict) else {}
            next_states: dict[str, Any] = {}
            changed: list[_files.ChangedFile] = []
            unreadable: set[str] = set()
            for key, watched_since in places.items():
                state = states.get(key)
                try:
                    found, next_states[key] = await self._read_place(
                        client,
                        access_token,
                        key,
                        state=state if isinstance(state, dict) else {},
                        user_id=cursor.get("user_id"),
                        watched_since=watched_since,
                        now=now,
                    )
                except _PlaceUnreadable:
                    logger.info("microsoft_files_place_unreadable", extra={"place": key})
                    unreadable.add(key)
                    continue
                changed += found
        events, _ = _files.news(changed, announced={}, now=now)
        return PolledEvents(
            events=tuple(events),
            cursor={
                **{key: cursor[key] for key in ("account", "user_id") if key in cursor},
                "places": next_states,
            },
            unreadable=frozenset(unreadable),
        )

    async def _read_place(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        key: str,
        *,
        state: dict[str, Any],
        user_id: Any,
        watched_since: datetime,
        now: datetime,
    ) -> tuple[list[_files.ChangedFile], dict[str, Any]]:
        """The files changed in one place since its stored link, and its new state."""
        drive_id = state.get("drive_id")
        if not isinstance(drive_id, str) or not drive_id:
            drive_id = await self._drive_id(client, access_token, key)
        stored = state.get("link")
        # The link is ours, but it carries the bearer token's destination: only
        # Graph's own address is ever asked.
        link = stored if isinstance(stored, str) and stored.startswith(_API_BASE + "/") else None
        changed: list[_files.ChangedFile] = []
        following: object = None
        for _ in range(_MAX_PAGES):
            if link is None:
                # Begin at the watch boundary; expired sync states reset it below.
                stamp = quote(watched_since.isoformat(), safe="")
                link = f"{_API_BASE}/drives/{quote(drive_id, safe='')}/root/delta?token={stamp}"
            try:
                body = await self._get(client, access_token, link, None)
            except PortalUnreachable as exc:
                details = exc.details or {}
                if details.get("status") == 410 or _SYNC_LOST.intersection(
                    details.get("codes", ())
                ):
                    logger.info("microsoft_files_delta_expired", extra={"place": key})
                    link = None
                    watched_since = now
                    continue
                if details.get("status") in {403, 404}:
                    raise _PlaceUnreadable from exc
                raise
            for item in body.get("value") or []:
                if (
                    isinstance(item, dict)
                    and isinstance(item.get("file"), dict)
                    and "deleted" not in item
                ):
                    identifier = item.get("id")
                    parent = nested(item, "parentReference")
                    if isinstance(identifier, str) and not isinstance(parent.get("path"), str):
                        try:
                            item = await self._get(
                                client,
                                access_token,
                                f"{_API_BASE}/drives/{quote(drive_id, safe='')}/items/{quote(identifier, safe='')}",
                                {
                                    "$select": "id,name,file,createdDateTime,lastModifiedDateTime,lastModifiedBy,parentReference,webUrl"
                                },
                            )
                        except PortalUnreachable as exc:
                            if (exc.details or {}).get("status") == 404:
                                continue
                            raise
                found = _changed_file(item, key=key, user_id=user_id)
                if found is not None:
                    changed.append(found)
            following = body.get("@odata.nextLink")
            final = body.get("@odata.deltaLink")
            link = following if isinstance(following, str) else final
            if not isinstance(following, str):
                break
        if link is None:
            raise PortalUnreachable(message="Microsoft Graph repeatedly rejected the sync state")
        complete = not isinstance(following, str)
        since = _files.parse_time(state.get("created_since")) or (now if stored else watched_since)
        seen = state.get("seen_files")
        known = (
            {key: value for key, value in seen.items() if isinstance(value, str)}
            if isinstance(seen, dict)
            else {}
        )
        changed, known = _files.classify(
            changed, since=since, seen=known, now=now, complete=complete
        )
        return changed, {
            "drive_id": drive_id,
            "link": link if isinstance(link, str) else None,
            "created_since": (now if complete else since).isoformat(),
            "seen_files": known,
        }

    async def _drive_id(self, client: httpx.AsyncClient, access_token: str, key: str) -> str:
        """The id of the drive a place reads: the own OneDrive, or a site's library.

        Raises:
            _PlaceUnreadable: No such site, or one the account cannot read.
        """
        if key:
            parts = urlsplit(key)
            path = parts.path.strip("/")
            site = f"{_API_BASE}/sites/{parts.hostname}" + (
                f":/{quote(unquote(path))}:" if path else ""
            )
            url = f"{site}/drive"
        else:
            url = f"{_API_BASE}/me/drive"
        try:
            drive = await self._get(client, access_token, url, {"$select": "id"})
        except PortalUnreachable as exc:
            if (exc.details or {}).get("status") in {400, 403, 404}:
                raise _PlaceUnreadable from exc
            raise
        identifier = drive.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise _PlaceUnreadable
        return identifier

    async def _get(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        url: str,
        params: dict[str, str] | None,
    ) -> dict[str, Any]:
        return await get_json(
            client,
            url,
            access_token=access_token,
            params=params,
            service="Microsoft Graph",
            portal_key=self.portal_key,
        )


def _changed_file(item: Any, *, key: str, user_id: Any) -> _files.ChangedFile | None:
    """A delta item that is a file still there, or `None` - a deletion or a folder."""
    if not isinstance(item, dict) or "deleted" in item or not isinstance(item.get("file"), dict):
        return None
    identifier = item.get("id")
    created = _files.parse_time(item.get("createdDateTime"))
    modified = _files.parse_time(item.get("lastModifiedDateTime"))
    if not isinstance(identifier, str) or created is None or modified is None:
        return None
    editor = nested(nested(item, "lastModifiedBy"), "user")
    parent = item.get("parentReference")
    raw_path = parent.get("path") if isinstance(parent, dict) else None
    path = raw_path.partition(":")[2] if isinstance(raw_path, str) and ":" in raw_path else ""
    return _files.ChangedFile(
        provider="msfiles",
        file_id=identifier,
        name=str(item.get("name") or ""),
        mime_type=str(item["file"].get("mimeType") or ""),
        created_at=created,
        modified_at=modified,
        url=str(item.get("webUrl") or ""),
        modified_by=str(editor.get("email") or editor.get("displayName") or ""),
        by_account=isinstance(user_id, str) and editor.get("id") == user_id,
        location={"place": key, "site_url": key or None, "folder": unquote(path).strip("/")},
    )
