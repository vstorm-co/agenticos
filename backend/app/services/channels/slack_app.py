"""What makes a Slack bot a Slack *app* (#2067).

The bot answers mentions and direct messages through the shared router like any
channel. Everything here is Slack's own surface around that:

- **Buttons** - an approval or an `ask_user` question pressed in Slack arrives as
  a `block_actions` payload, read into an :class:`IncomingPress`.
- **The assistant pane** - Slack's split view for AI apps: a new thread there is
  offered suggested prompts, and while the agent works the thread says so.
- **App Home** - the bot's own tab: which agent it is, what is waiting on the
  person, and the way to the console.
- **`/agent` and the "Ask the agent" message shortcut** - two more ways in, read
  into the same :class:`IncomingMessage` a mention is, so they are admitted,
  linked, rate limited and run exactly like one.
- **Unfurls** - a console link to an agent posted in Slack shows its name.
- **The manifest** - in :mod:`app.services.channels.slack_manifest`.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.channel_bot import ChannelBot
from app.repositories import (
    agent_exposure_repo,
    agent_repo,
    agent_run_repo,
    channel_identity_repo,
    channel_session_repo,
)
from app.services.channel_bot import unseal_bot_token
from app.services.channels.base import (
    FeedbackComment,
    IncomingMessage,
    IncomingPress,
    split_thread,
    thread_key,
)
from app.services.channels.slack_manifest import SHORTCUT_ID

logger = logging.getLogger(__name__)

SURFACE_EVENTS = frozenset({"app_home_opened", "assistant_thread_started", "link_shared"})
"""Events that are about the app rather than a message to the agent."""

SUGGESTED_PROMPTS = (
    ("What can you do?", "What can you help me with? Give me three examples."),
    ("Summarise a thread", "Summarise the thread I share with you next."),
    ("Draft a reply", "Help me draft a reply to the message I share next."),
)
"""What a new assistant-pane thread offers: a title and the prompt it sends."""

_AGENT_LINK = re.compile(r"/agents/([0-9a-fA-F-]{36})")


def parse_press(payload: dict[str, Any], bot_id: str) -> IncomingPress | None:
    """A button pressed on one of the bot's messages, or `None` for anything else."""
    if payload.get("type") != "block_actions":
        return None
    actions = payload.get("actions") or []
    value = actions[0].get("value") if actions else None
    if not isinstance(value, str):
        return None
    channel = (payload.get("channel") or {}).get("id", "")
    message = payload.get("message") or {}
    container = payload.get("container") or {}
    user = payload.get("user") or {}
    thread = message.get("thread_ts") or container.get("thread_ts") or ""
    return IncomingPress(
        platform="slack",
        bot_id=bot_id,
        platform_user_id=user.get("id", ""),
        platform_chat_id=f"{channel}:{thread}" if thread else channel,
        value=value,
        platform_username=user.get("username"),
        message_id=message.get("ts") or container.get("message_ts"),
        prompt_text=message.get("text"),
        trigger_id=payload.get("trigger_id"),
    )


FEEDBACK_COMMENT = "aos_feedback_comment"
"""The `callback_id` of the "what was wrong?" modal (#2084)."""

_COMMENT_BLOCK = "comment"


def feedback_comment_view(run_id: str) -> dict[str, Any]:
    """The modal a thumbs-down opens, carrying the run it is about."""
    return {
        "type": "modal",
        "callback_id": FEEDBACK_COMMENT,
        "private_metadata": run_id,
        "title": {"type": "plain_text", "text": "What was wrong?"},
        "submit": {"type": "plain_text", "text": "Send"},
        "close": {"type": "plain_text", "text": "Skip"},
        "blocks": [
            {
                "type": "input",
                "block_id": _COMMENT_BLOCK,
                "label": {"type": "plain_text", "text": "Tell the agent's builders"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": _COMMENT_BLOCK,
                    "multiline": True,
                    "max_length": 2000,
                },
            }
        ],
    }


def parse_feedback_comment(payload: dict[str, Any], bot_id: str) -> FeedbackComment | None:
    """The "what was wrong?" modal, submitted - or `None` for any other view."""
    view = payload.get("view") or {}
    if payload.get("type") != "view_submission" or view.get("callback_id") != FEEDBACK_COMMENT:
        return None
    values = (view.get("state") or {}).get("values") or {}
    text = ((values.get(_COMMENT_BLOCK) or {}).get(_COMMENT_BLOCK) or {}).get("value") or ""
    run_id = view.get("private_metadata") or ""
    if not text.strip() or not run_id:
        return None
    return FeedbackComment(
        platform="slack",
        bot_id=bot_id,
        platform_user_id=(payload.get("user") or {}).get("id", ""),
        run_id=run_id,
        text=text.strip(),
    )


def parse_shortcut(payload: dict[str, Any], bot_id: str) -> IncomingMessage | None:
    """ "Ask the agent about this" on a message: a question about it, in its thread."""
    if payload.get("type") != "message_action" or payload.get("callback_id") != SHORTCUT_ID:
        return None
    message = payload.get("message") or {}
    channel = (payload.get("channel") or {}).get("id", "")
    quoted = "\n".join(f"> {line}" for line in (message.get("text") or "").splitlines())
    ts = message.get("ts")
    return IncomingMessage(
        platform="slack",
        bot_id=bot_id,
        platform_user_id=(payload.get("user") or {}).get("id", ""),
        platform_chat_id=thread_key(
            channel, thread_id=message.get("thread_ts") or "", message_id=ts
        ),
        chat_type="private" if channel.startswith("D") else "group",
        text=f"Help me with this message:\n{quoted}",
        raw=payload,
        message_id=payload.get("trigger_id"),
        addressed=True,
    )


def parse_command(form: dict[str, str], bot_id: str) -> IncomingMessage | None:
    """`/agent <question>`, asked where it was typed."""
    text = (form.get("text") or "").strip()
    channel = form.get("channel_id", "")
    if not text or not channel:
        return None
    return IncomingMessage(
        platform="slack",
        bot_id=bot_id,
        platform_user_id=form.get("user_id", ""),
        platform_chat_id=channel,
        chat_type="private" if channel.startswith("D") else "group",
        text=text,
        raw=dict(form),
        platform_username=form.get("user_name"),
        message_id=form.get("trigger_id"),
        addressed=True,
    )


class SlackSurfaces:
    """Slack's own surfaces around the bot: App Home, the assistant pane, unfurls."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def handle(self, payload: dict[str, Any], bot: ChannelBot) -> None:
        """One surface event. Never raises: Slack has had its 200 already."""
        event = payload.get("event") or {}
        kind = event.get("type")
        try:
            client = _client(unseal_bot_token(bot))
            if kind == "app_home_opened" and event.get("tab") == "home":
                await client.views_publish(
                    user_id=event.get("user", ""),
                    view=await self._home(bot, event.get("user", ""), client),
                )
            elif kind == "assistant_thread_started":
                thread = event.get("assistant_thread") or {}
                await client.assistant_threads_setSuggestedPrompts(
                    channel_id=thread.get("channel_id", ""),
                    thread_ts=thread.get("thread_ts", ""),
                    prompts=[
                        {"title": title, "message": message} for title, message in SUGGESTED_PROMPTS
                    ],
                )
            elif kind == "link_shared":
                unfurls = await self._unfurls(bot, event.get("links") or [])
                if unfurls:
                    await client.chat_unfurl(
                        channel=event.get("channel", ""),
                        ts=event.get("message_ts", ""),
                        unfurls=unfurls,
                    )
        except Exception:
            logger.exception("Slack %s for bot %s failed", kind, bot.id)

    async def _recent(
        self, bot: ChannelBot, identity_id: UUID, client: Any
    ) -> list[dict[str, Any]]:
        """This person's latest conversations with the bot, each a link to its thread (#2084).

        Linked to the Slack thread rather than the console: a channel conversation
        belongs to the chat it happened in, not to anybody's console history. A
        thread Slack will not give a permalink for is listed without one.
        """
        recent = await channel_session_repo.recent_for_identity(
            self.db, bot_id=bot.id, identity_id=identity_id
        )
        if not recent:
            return []
        lines: list[str] = []
        for session, title in recent:
            channel, thread_ts = split_thread(session.platform_chat_id)
            name = (title or "Untitled conversation").replace(">", "")
            try:
                link = await client.chat_getPermalink(channel=channel, message_ts=thread_ts)
                lines.append(f"• <{link['permalink']}|{name}>")
            except Exception:
                lines.append(f"• {name}")
        return [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Your recent conversations*\n" + "\n".join(lines),
                },
            }
        ]

    async def _home(self, bot: ChannelBot, slack_user: str, client: Any) -> dict[str, Any]:
        """The App Home tab: the agent, this person's recent conversations, what waits
        on them, and the console."""
        console = settings.FRONTEND_URL.rstrip("/")
        blocks: list[dict[str, Any]] = []
        binding = await agent_exposure_repo.bound_to_bot(self.db, channel_bot_id=bot.id)
        agent = (
            await agent_repo.get(self.db, binding.agent_id, organization_id=bot.organization_id)
            if binding is not None
            else None
        )
        if agent is not None:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*{agent.name}*\n{agent.description or ''}".rstrip(),
                    },
                }
            )
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Message me, mention me in a channel, or use `/agent`.",
                        }
                    ],
                }
            )
        identity = await channel_identity_repo.get_by_platform_user(self.db, "slack", slack_user)
        if identity is None or identity.user_id is None:
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "Send me `/link` to connect your AgenticOS account, so I act as you.",
                    },
                }
            )
        else:
            blocks.extend(await self._recent(bot, identity.id, client))
            waiting = await agent_run_repo.count_pending_approval_runs(
                self.db, organization_id=bot.organization_id, user_id=identity.user_id
            )
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*{waiting}* of your runs wait for an approval: <{console}/runs|open them>."
                            if waiting
                            else "Nothing of yours is waiting for an approval."
                        ),
                    },
                }
            )
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "open_console",
                        "text": {"type": "plain_text", "text": "Open AgenticOS"},
                        "url": f"{console}/dashboard",
                    },
                    {
                        "type": "button",
                        "action_id": "open_architect",
                        "text": {"type": "plain_text", "text": "Ask the AI Architect"},
                        "url": f"{console}/chat",
                    },
                ],
            }
        )
        return {"type": "home", "blocks": blocks}

    async def _unfurls(self, bot: ChannelBot, links: list[dict[str, Any]]) -> dict[str, Any]:
        """A console link to an agent of this organization, shown with its name."""
        console_host = urlparse(settings.FRONTEND_URL).netloc
        unfurls: dict[str, Any] = {}
        for link in links:
            url = link.get("url", "")
            match = _AGENT_LINK.search(url)
            if match is None or urlparse(url).netloc != console_host:
                continue
            agent = await agent_repo.get(
                self.db, UUID(match.group(1)), organization_id=bot.organization_id
            )
            if agent is not None:
                unfurls[url] = {
                    "title": agent.name,
                    "text": agent.description or "An agent in AgenticOS",
                }
        return unfurls


def _client(bot_token: str) -> Any:
    from slack_sdk.web.async_client import AsyncWebClient

    return AsyncWebClient(token=bot_token)
