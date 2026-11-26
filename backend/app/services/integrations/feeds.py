"""Cursor readers shared by integration watches and polled triggers."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, Field, JsonValue, SecretStr, TypeAdapter

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.services.integrations import client
from app.services.integrations.catalog import Operation
from app.services.portals import get_adapter

_JSON = TypeAdapter(dict[str, JsonValue])


class Change(BaseModel):
    id: str
    payload: dict[str, JsonValue]


class Changes(BaseModel):
    events: list[Change] = Field(default_factory=list)
    cursor: dict[str, JsonValue]


async def changes_since(
    product_id: str,
    token: SecretStr,
    *,
    cursor: dict[str, JsonValue] | None,
    channels: tuple[str, ...] = (),
    subject: str | None = None,
) -> Changes:
    """Read changes only; missing/expired cursors establish a quiet baseline.

    A caller owns its cursor and persists it only after consuming the batch. A
    watch and a trigger must never consume each other's position.
    """
    if product_id == "google_calendar":
        from app.services.integrations.delta import google_calendar

        return await google_calendar(token, cursor)
    if product_id == "outlook_calendar":
        from app.services.integrations.delta import graph_delta

        return await graph_delta(token, cursor, subject=subject, teams=False)
    if product_id == "teams":
        from app.services.integrations.teams_feed import changes

        return await changes(token, cursor, channels=channels)
    if product_id == "slack":
        return await _slack(token, cursor=cursor, channels=channels)
    key = {"gmail": "google", "outlook_mail": "microsoft"}.get(product_id)
    adapter = get_adapter(key) if key else None
    if adapter is None:
        raise BadRequestError(message="This product does not expose a watch change feed")
    if subject is not None and product_id == "outlook_mail":
        from app.services.portals.outlook import OutlookPortalAdapter

        adapter = OutlookPortalAdapter(subject=subject)
    read = await adapter.poll(
        access_token=token.get_secret_value(),
        cursor=cursor,
        places={"|inbox": datetime.min.replace(tzinfo=UTC)} if product_id == "outlook_mail" else {},
    )
    return Changes(
        events=[
            Change(id=event.delivery_id, payload=_JSON.validate_python(event.payload))
            for event in read.events
        ],
        cursor=_JSON.validate_python(read.cursor),
    )


async def _slack(
    token: SecretStr, *, cursor: dict[str, JsonValue] | None, channels: tuple[str, ...]
) -> Changes:
    if not channels or len(channels) > 20:
        raise BadRequestError(
            message="Choose between one and twenty Slack conversations for the feed"
        )
    now = str(datetime.now(UTC).timestamp())
    previous = cursor or {}
    positions = {channel: str(previous.get(channel) or now) for channel in channels}
    events: list[Change] = []
    operation = Operation(
        "changes",
        "Read new Slack messages",
        "GET",
        "https://slack.com/api/conversations.history",
        (),
        query=("channel", "oldest", "latest", "cursor", "limit"),
    )
    for channel in channels:
        if channel not in previous:
            continue
        try:
            watermark = Decimal(positions[channel])
        except InvalidOperation as exc:
            raise BadRequestError(message="Invalid Slack feed cursor") from exc
        page = ""
        for _ in range(10):
            query = {
                "channel": channel,
                "oldest": positions[channel],
                "latest": now,
                "limit": "200",
            }
            if page:
                query["cursor"] = page
            result = await client.execute(operation, token, parameters={}, query=query, body=None)
            messages = result.get("messages")
            if not isinstance(messages, list):
                raise ExternalServiceError(message="Slack did not return a message list")
            for message in messages:
                if isinstance(message, dict) and isinstance(message.get("ts"), str):
                    try:
                        watermark = max(watermark, Decimal(str(message["ts"])))
                    except InvalidOperation as exc:
                        raise ExternalServiceError(
                            message="Slack returned an invalid timestamp"
                        ) from exc
                    events.append(
                        Change(
                            id=f"slack:{channel}:{message['ts']}",
                            payload={"channel": channel, **message},
                        )
                    )
            metadata = result.get("response_metadata")
            page = str(metadata.get("next_cursor") or "") if isinstance(metadata, dict) else ""
            if not page:
                break
        else:
            raise ExternalServiceError(
                message="Too many Slack changes to consume safely; narrow the watched conversations"
            )
        positions[channel] = str(watermark)
    if not events:
        return Changes(events=[], cursor=_JSON.validate_python(positions))
    identity_op = Operation(
        "identity",
        "Read the connected Slack identity",
        "GET",
        "https://slack.com/api/auth.test",
        (),
    )
    identity = await client.execute(identity_op, token, parameters={}, query={}, body=None)
    user_id = identity.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        raise ExternalServiceError(message="Slack did not identify the connected member")
    bot_id = identity.get("bot_id")
    events = [
        event
        for event in events
        if event.payload.get("user") != user_id
        and not (isinstance(bot_id, str) and bot_id and event.payload.get("bot_id") == bot_id)
    ]
    for event in events:
        text = event.payload.get("text")
        event.payload["mentions_me"] = isinstance(text, str) and f"<@{user_id}>" in text
        channel = event.payload.get("channel")
        event.payload["direct_message"] = isinstance(channel, str) and channel.startswith("D")
    return Changes(events=events, cursor=_JSON.validate_python(positions))
