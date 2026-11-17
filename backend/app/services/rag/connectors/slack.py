"""Chosen Slack conversations as knowledge, through an organization connected account."""

from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, ValidationError

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.secret_kinds import StorableSecret
from app.services.integrations import AccountToken, Operation
from app.services.integrations import execute_operation as execute
from app.services.rag.connectors import (
    BaseSyncConnector,
    ConfigRefusal,
    ConnectorConfig,
    RemoteFile,
    RemoteListing,
)


class SlackKnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: UUID = Field(
        title="Connected Slack account",
        description="An organization Slack account connected in Vault.",
    )
    channels: list[str] = Field(
        min_length=1,
        max_length=20,
        title="Slack conversations",
        description="Only these conversation IDs are indexed. The account must be able to read them.",
    )


class SlackEdit(BaseModel):
    ts: str = Field(pattern=r"^[0-9]+\.[0-9]+$")


class SlackMessage(BaseModel):
    ts: str = Field(pattern=r"^[0-9]+\.[0-9]+$")
    text: str = ""
    user: str = ""
    thread_ts: str | None = Field(default=None, pattern=r"^[0-9]+\.[0-9]+$")
    latest_reply: str | None = Field(default=None, pattern=r"^[0-9]+\.[0-9]+$")
    edited: SlackEdit | None = None


class SlackPage(BaseModel):
    messages: list[SlackMessage]
    response_metadata: dict[str, str] = Field(default_factory=dict)


def _page(result: dict[str, JsonValue]) -> SlackPage:
    try:
        return SlackPage.model_validate(result)
    except ValidationError:
        raise ExternalServiceError(message="Slack returned an invalid conversation page") from None


_HISTORY = Operation(
    "knowledge_history",
    "Read selected conversation history",
    "GET",
    "https://slack.com/api/conversations.history",
    (),
    query=("channel", "cursor", "limit"),
)
_REPLIES = Operation(
    "knowledge_thread",
    "Read a selected conversation thread",
    "GET",
    "https://slack.com/api/conversations.replies",
    (),
    query=("channel", "ts", "cursor", "limit"),
)
_MAX_PAGES = 50
_MAX_TEXT_BYTES = 20_000_000


async def _token(credential: StorableSecret | None) -> SecretStr:
    if not isinstance(credential, AccountToken) or credential.provider != "slack":
        raise BadRequestError(
            message="Choose an organization connected Slack account for this knowledge source"
        )
    return await credential.current_token()


class SlackConnector(BaseSyncConnector):
    CONNECTOR_TYPE: ClassVar[str] = "slack"
    DISPLAY_NAME: ClassVar[str] = "Slack conversations"
    CONFIG_MODEL: ClassVar[type[BaseModel]] = SlackKnowledgeConfig

    async def validate_config(self, config: ConnectorConfig) -> ConfigRefusal | None:
        try:
            SlackKnowledgeConfig.model_validate(config)
        except ValidationError as exc:
            error = exc.errors(include_url=False, include_input=False)[0]
            return ConfigRefusal(
                message="Choose a connected account and between one and twenty Slack conversations",
                field=str(error["loc"][0]),
            )
        return None

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> RemoteListing:
        selected = SlackKnowledgeConfig.model_validate(config)
        await _token(credential)
        files: list[RemoteFile] = []
        complete = True
        for channel in dict.fromkeys(selected.channels):
            cursor = ""
            threads: set[str] = set()
            for _ in range(_MAX_PAGES):
                query = {"channel": channel, "limit": "200"}
                if cursor:
                    query["cursor"] = cursor
                result = await execute(
                    _HISTORY, await _token(credential), parameters={}, query=query, body=None
                )
                page = _page(result)
                for message in page.messages:
                    thread = message.thread_ts or message.ts
                    if thread in threads:
                        continue
                    threads.add(thread)
                    files.append(
                        RemoteFile(
                            id=f"{channel}:{thread}",
                            name=f"{channel}-{thread}.md",
                            mime_type="text/markdown",
                            modified_at=datetime.fromtimestamp(
                                max(
                                    float(message.ts),
                                    float(message.latest_reply or message.ts),
                                    float(message.edited.ts if message.edited else message.ts),
                                ),
                                tz=UTC,
                            ),
                            source_path=f"slack://{channel}/{thread}",
                        )
                    )
                cursor = page.response_metadata.get("next_cursor", "")
                if not cursor:
                    break
            else:
                complete = False
        return RemoteListing(
            files=files,
            complete=complete,
            problems=[]
            if complete
            else ["The Slack listing reached its page limit; removals were skipped"],
        )

    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        selected = SlackKnowledgeConfig.model_validate(config)
        channel, _, timestamp = file.id.partition(":")
        if channel not in selected.channels or not timestamp:
            raise BadRequestError(
                message="This Slack thread is outside the source's selected conversations"
            )
        await _token(credential)
        cursor = ""
        parts = [f"# Slack conversation {channel}, thread {timestamp}\n"]
        size = len(parts[0].encode())
        for _ in range(_MAX_PAGES):
            query = {"channel": channel, "ts": timestamp, "limit": "200"}
            if cursor:
                query["cursor"] = cursor
            result = await execute(
                _REPLIES, await _token(credential), parameters={}, query=query, body=None
            )
            page = _page(result)
            additions = [
                f"## {message.user} · {message.ts}\n\n{message.text}\n" for message in page.messages
            ]
            size += sum(len(part.encode()) + 1 for part in additions)
            if size > _MAX_TEXT_BYTES:
                raise ExternalServiceError(message="The Slack thread is too large to index")
            parts.extend(additions)
            cursor = page.response_metadata.get("next_cursor", "")
            if not cursor:
                break
        else:
            raise ExternalServiceError(message="The Slack thread exceeds the source's page limit")
        text = "\n".join(parts)
        dest_path.write_text(text, encoding="utf-8")
