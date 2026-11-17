"""Calendar sync tokens and Graph cursors, with quiet baselines and bounded pages."""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote, unquote, urlsplit

from pydantic import JsonValue, SecretStr

from app.core.exceptions import ExternalServiceError
from app.services.integrations import client
from app.services.integrations.catalog import Operation
from app.services.integrations.feeds import Change, Changes


async def google_calendar(token: SecretStr, cursor: dict[str, JsonValue] | None) -> Changes:
    old = cursor or {}
    sync = old.get("sync_token")
    page = old.get("page_token")
    baseline = not isinstance(sync, str) or not sync
    query = {"maxResults": "100", "showDeleted": "true"}
    if isinstance(sync, str) and sync:
        query["syncToken"] = sync
    if isinstance(page, str) and page:
        query["pageToken"] = page
    operation = Operation(
        "calendar_changes",
        "Read calendar changes",
        "GET",
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        (),
        query=tuple(query),
    )
    try:
        result = await client.execute(operation, token, parameters={}, query=query, body=None)
    except ExternalServiceError as exc:
        if (exc.details or {}).get("status") != 410:
            raise
        return await google_calendar(token, None)
    events = result.get("items")
    if not isinstance(events, list):
        raise ExternalServiceError(message="Google Calendar did not return an event list")
    following = result.get("nextPageToken")
    final = result.get("nextSyncToken")
    if isinstance(following, str) and following:
        next_cursor: dict[str, JsonValue] = {
            "sync_token": sync if isinstance(sync, str) else "",
            "page_token": following,
        }
    elif isinstance(final, str) and final:
        next_cursor = {"sync_token": final}
    else:
        raise ExternalServiceError(message="Google Calendar did not return a resume cursor")
    return Changes(
        events=[]
        if baseline
        else [
            Change(id=f"calendar:{event['id']}:{event.get('updated', '')}", payload=event)
            for event in events
            if isinstance(event, dict) and isinstance(event.get("id"), str)
        ],
        cursor=next_cursor,
    )


def _checked_link(link: str, path: str) -> str:
    parsed = urlsplit(link)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "graph.microsoft.com"
        or tuple(map(unquote, parsed.path.split("/"))) != tuple(map(unquote, path.split("/")))
    ):
        raise ExternalServiceError(
            message="Microsoft Graph returned a cursor outside this integration source"
        )
    return link


async def graph_delta(
    token: SecretStr, cursor: dict[str, JsonValue] | None, *, subject: str | None, teams: bool
) -> Changes:
    now = datetime.now(UTC)
    old = cursor or {}
    if teams:
        if not subject:
            raise ExternalServiceError(message="A Teams application feed needs the user it reads")
        path = f"/v1.0/users/{quote(subject, safe='')}/chats/getAllMessages/delta"
        first = "https://graph.microsoft.com" + path
    else:
        path = (
            f"/v1.0/users/{quote(subject, safe='')}/calendarView/delta"
            if subject
            else "/v1.0/me/calendarView/delta"
        )
        first = (
            "https://graph.microsoft.com"
            + path
            + f"?startDateTime={quote(now.isoformat())}&endDateTime={quote((now + timedelta(days=365)).isoformat())}"
        )
    window_end = old.get("window_end")
    if not teams and isinstance(window_end, str):
        try:
            if datetime.fromisoformat(window_end) <= now + timedelta(days=1):
                old = {}
        except ValueError, TypeError:
            old = {}
    read = await read_graph_delta(token, old, path=path, first=first)
    if not teams:
        read.cursor["window_end"] = (
            window_end
            if old and isinstance(window_end, str)
            else (now + timedelta(days=365)).isoformat()
        )
    return read


async def read_graph_delta(
    token: SecretStr, cursor: dict[str, JsonValue] | None, *, path: str, first: str | None = None
) -> Changes:
    old = cursor or {}
    stored = old.get("link")
    baseline = not isinstance(stored, str) or not stored or old.get("baseline") is True
    url = (
        _checked_link(stored, path)
        if isinstance(stored, str) and stored
        else (first or "https://graph.microsoft.com" + path)
    )
    operation = Operation("graph_changes", "Read Microsoft changes", "GET", url, ())
    try:
        result = await client.execute(operation, token, parameters={}, query={}, body=None)
    except ExternalServiceError as exc:
        if (exc.details or {}).get("status") not in {404, 410} or not stored:
            raise
        return await read_graph_delta(token, None, path=path, first=first)
    following = result.get("@odata.nextLink")
    final = result.get("@odata.deltaLink")
    events = result.get("value")
    if not isinstance(events, list):
        raise ExternalServiceError(message="Microsoft Graph did not return a changes list")
    link = following if isinstance(following, str) and following else final
    if not isinstance(link, str) or not link:
        raise ExternalServiceError(message="Microsoft Graph did not return a resume cursor")
    next_cursor = {"link": _checked_link(link, path), "baseline": baseline and bool(following)}
    return Changes(
        events=[]
        if baseline
        else [
            Change(id=f"graph:{event['id']}:{event.get('lastModifiedDateTime', '')}", payload=event)
            for event in events
            if isinstance(event, dict) and isinstance(event.get("id"), str)
        ],
        cursor=next_cursor,
    )
