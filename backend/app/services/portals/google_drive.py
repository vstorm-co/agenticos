"""The Google Drive portal adapter - new and changed files, read on a schedule.

Drive's changes feed is Gmail's history in another shape: a page token is an
exact position in the account's log of changes, so "what since this token" has
no race with the clock. Drive can push changes to a channel too, which needs a
public HTTPS endpoint verified per domain and a registration that expires, so
this reads the feed once a minute like the mailboxes.

The feed covers every file the account can see, shared drives included; a
trigger narrows by folder and name in `trigger_events`. Only metadata is read -
the grant is `drive.metadata.readonly` - so the run is told which file and where
it is, and an agent that should read the file does so with its own tools.
"""

import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.portals import _files
from app.services.portals._api import TIMEOUT, get_json, nested
from app.services.portals.base import NOWHERE, PolledEvents, PortalAdapter
from app.services.portals.exceptions import PortalUnreachable

logger = logging.getLogger(__name__)

_API_BASE = "https://www.googleapis.com/drive/v3"
_FOLDER = "application/vnd.google-apps.folder"
_MAX_PAGES = 10
_FIELDS = (
    "nextPageToken,newStartPageToken,changes(changeType,removed,"
    "file(id,name,mimeType,createdTime,modifiedTime,parents,webViewLink,trashed,"
    "lastModifyingUser(displayName,emailAddress,me)))"
)
_ALL_DRIVES = {"supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}


class GoogleDrivePortalAdapter(PortalAdapter):
    portal_key = "google_drive"

    async def poll(
        self,
        *,
        access_token: str,
        cursor: dict[str, Any] | None,
        places: Mapping[str, datetime] = NOWHERE,
    ) -> PolledEvents:
        """Files created or changed since the stored page token, and the next one.

        With no cursor this takes the feed's current position and the account's
        address and returns nothing: connecting a drive fires nothing on the files
        already in it. A token Drive no longer accepts starts again from now.
        """
        now = datetime.now(UTC)
        async with httpx.AsyncClient(base_url=_API_BASE, timeout=TIMEOUT) as client:
            token = cursor.get("page_token") if cursor else None
            if not isinstance(token, str) or not token:
                about = await self._get(
                    client, access_token, "/about", {"fields": "user(emailAddress)"}
                )
                user = about.get("user")
                fresh: dict[str, Any] = {"page_token": await self._start(client, access_token)}
                if isinstance(user, dict) and isinstance(user.get("emailAddress"), str):
                    fresh["account"] = user["emailAddress"].casefold()
                return PolledEvents(events=(), cursor=fresh)
            assert cursor is not None
            changed, resume = await self._changed_since(client, access_token, token)
        events, announced = _files.news(changed, announced=cursor.get("announced") or {}, now=now)
        return PolledEvents(
            events=tuple(events),
            cursor={
                **{key: cursor[key] for key in ("account",) if key in cursor},
                "page_token": resume,
                "announced": announced,
            },
        )

    async def _start(self, client: httpx.AsyncClient, access_token: str) -> str:
        body = await self._get(
            client, access_token, "/changes/startPageToken", {"supportsAllDrives": "true"}
        )
        return str(body.get("startPageToken") or "")

    async def _changed_since(
        self, client: httpx.AsyncClient, access_token: str, token: str
    ) -> tuple[list[_files.ChangedFile], str]:
        """The files changed since `token`, and the token to store next.

        Bounded to `_MAX_PAGES`: past it the next page's token is stored, so a
        bulk upload is read over several ticks rather than in one long one.
        """
        changed: list[_files.ChangedFile] = []
        for _ in range(_MAX_PAGES):
            try:
                body = await self._get(
                    client,
                    access_token,
                    "/changes",
                    {"pageToken": token, "pageSize": "100", "fields": _FIELDS, **_ALL_DRIVES},
                )
            except PortalUnreachable as exc:
                if (exc.details or {}).get("status") not in {404, 410}:
                    raise
                logger.info("google_drive_token_expired")
                return [], await self._start(client, access_token)
            for change in body.get("changes") or []:
                item = _changed_file(change)
                if item is not None:
                    changed.append(item)
            following = body.get("nextPageToken")
            if not isinstance(following, str) or not following:
                return changed, str(body.get("newStartPageToken") or token)
            token = following
        return changed, token

    async def _get(
        self,
        client: httpx.AsyncClient,
        access_token: str,
        path: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        return await get_json(
            client,
            path,
            access_token=access_token,
            params=params,
            service="Google Drive",
            portal_key=self.portal_key,
        )


def _changed_file(change: Any) -> _files.ChangedFile | None:
    """A change that is a file still there, or `None` - a removal, a folder, a drive."""
    if not isinstance(change, dict) or change.get("removed") or change.get("changeType") != "file":
        return None
    file = change.get("file")
    if not isinstance(file, dict) or file.get("trashed") or file.get("mimeType") == _FOLDER:
        return None
    identifier = file.get("id")
    created = _files.parse_time(file.get("createdTime"))
    modified = _files.parse_time(file.get("modifiedTime"))
    if not isinstance(identifier, str) or created is None or modified is None:
        return None
    editor = nested(file, "lastModifyingUser")
    return _files.ChangedFile(
        provider="gdrive",
        file_id=identifier,
        name=str(file.get("name") or ""),
        mime_type=str(file.get("mimeType") or ""),
        created_at=created,
        modified_at=modified,
        url=str(file.get("webViewLink") or ""),
        modified_by=str(editor.get("emailAddress") or editor.get("displayName") or ""),
        by_account=editor.get("me") is True,
        location={"parents": [str(one) for one in file.get("parents") or []]},
    )
