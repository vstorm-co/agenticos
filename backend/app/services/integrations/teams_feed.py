"""Delegated Teams reads use lastModifiedDateTime; application reads use Graph delta."""

from datetime import UTC, datetime
from urllib.parse import quote

from pydantic import JsonValue, SecretStr

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.integrations import client
from app.services.integrations.catalog import Operation
from app.services.integrations.feeds import Change, Changes


async def changes(
    token: SecretStr,
    cursor: dict[str, JsonValue] | None,
    *,
    channels: tuple[str, ...],
    application: bool = False,
    subject: str | None = None,
) -> Changes:
    if application and not channels:
        from app.services.integrations.delta import graph_delta

        read = await graph_delta(token, cursor, subject=subject, teams=True)
        for event in read.events:
            chat = event.payload.get("chatId")
            if not isinstance(chat, str) or not chat:
                raise ExternalServiceError(
                    message="Teams returned a message without its chat identity"
                )
            event.id = f"teams:{chat}:{event.id}"
            event.payload["channel"] = chat
        return await _annotate(token, read, subject=subject)
    if not channels or len(channels) > 20:
        raise BadRequestError(message="Choose between one and twenty Teams chats or channels")
    now = datetime.now(UTC).isoformat()
    old = cursor or {}
    positions: dict[str, JsonValue] = {}
    found: list[Change] = []
    for target in channels:
        if target.startswith("channel/"):
            parts = target.split("/")
            if len(parts) != 3:
                raise BadRequestError(message="A Teams channel uses channel/team-id/channel-id")
            path = f"/v1.0/teams/{quote(parts[1], safe='')}/channels/{quote(parts[2], safe='')}/messages"
        else:
            path = f"/v1.0/chats/{quote(target, safe='')}/messages"
        if target.startswith("channel/"):
            read = await _channel_delta(token, old.get(target), path)
            positions[target] = read.cursor
            found.extend(
                Change(
                    id=f"teams:{target}:{event.payload.get('replyToId') or ''}:{event.id}",
                    payload={**event.payload, "channel": target},
                )
                for event in read.events
            )
            continue
        if application:
            raise BadRequestError(
                message="Teams application feeds read all chats for the configured subject; leave conversations empty or select channel/team-id/channel-id"
            )
        prior = old.get(target)
        if not isinstance(prior, str):
            positions[target] = now
            continue
        try:
            previous = datetime.fromisoformat(prior)
        except ValueError:
            positions[target] = now
            continue
        if previous.tzinfo is None:
            positions[target] = now
            continue
        watermark = previous
        query = {
            "$filter": f"lastModifiedDateTime gt {previous.isoformat()}",
            "$orderby": "lastModifiedDateTime desc",
            "$top": "50",
        }
        url = "https://graph.microsoft.com" + path
        for _ in range(20):
            op = Operation(
                "teams_changes", "Read Teams changes", "GET", url, (), query=tuple(query)
            )
            result = await client.execute(op, token, parameters={}, query=query, body=None)
            values = result.get("value")
            if not isinstance(values, list):
                raise ExternalServiceError(message="Teams did not return a message list")
            for event in values:
                if isinstance(event, dict) and isinstance(event.get("id"), str):
                    stamp = event.get("lastModifiedDateTime")
                    if not isinstance(stamp, str):
                        raise ExternalServiceError(
                            message="Teams returned a message without a change timestamp"
                        )
                    try:
                        changed_at = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    except ValueError as exc:
                        raise ExternalServiceError(
                            message="Teams returned an invalid change timestamp"
                        ) from exc
                    if changed_at.tzinfo is None:
                        raise ExternalServiceError(
                            message="Teams returned a change timestamp without a timezone"
                        )
                    if previous < changed_at:
                        watermark = max(watermark, changed_at)
                        found.append(
                            Change(
                                id=f"teams:{target}:{event['id']}:{stamp}",
                                payload={**event, "channel": target},
                            )
                        )
            link = result.get("@odata.nextLink")
            if not isinstance(link, str) or not link:
                break
            from app.services.integrations.delta import _checked_link

            _checked_link(link, path)
            url, query = link, {}
        else:
            raise ExternalServiceError(
                message="Too many Teams changes to consume safely; narrow the selected conversations"
            )
        positions[target] = watermark.isoformat()
    return await _annotate(token, Changes(events=found, cursor=positions), subject=subject)


async def _channel_delta(token: SecretStr, cursor: JsonValue, path: str) -> Changes:
    from app.services.integrations.delta import read_graph_delta

    return await read_graph_delta(
        token, cursor if isinstance(cursor, dict) else None, path=path + "/delta"
    )


async def _annotate(token: SecretStr, read: Changes, *, subject: str | None) -> Changes:
    if not read.events:
        return read
    # Delegated identity is authoritative; application feeds are explicitly bound
    # to a directory object ID rather than requiring broad directory-read access.
    if subject is None:
        op = Operation(
            "identity",
            "Read the connected Microsoft identity",
            "GET",
            "https://graph.microsoft.com/v1.0/me",
            (),
            query=("$select",),
        )
        identity = await client.execute(
            op, token, parameters={}, query={"$select": "id"}, body=None
        )
        identity_id = identity.get("id")
    else:
        identity_id = subject
    if not isinstance(identity_id, str) or not identity_id:
        raise ExternalServiceError(message="Microsoft did not identify the connected member")
    for event in read.events:
        body = event.payload.get("body")
        event.payload["text"] = body.get("content", "") if isinstance(body, dict) else ""
        mentions = event.payload.get("mentions")
        event.payload["mentions_me"] = any(
            isinstance(mention, dict)
            and isinstance(mentioned := mention.get("mentioned"), dict)
            and isinstance(user := mentioned.get("user"), dict)
            and user.get("id") == identity_id
            for mention in (mentions if isinstance(mentions, list) else [])
        )
    return read
