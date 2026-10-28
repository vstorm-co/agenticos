"""What each chat platform actually renders, told to the agent.

An agent writes for a screen it cannot see. The dashboard renders full Markdown;
Slack renders almost none of it and has its own syntax for a link; Telegram
renders a subset and rejects a message whose formatting is malformed. Left to
guess, a model writes GitHub-flavoured Markdown everywhere - so an answer that
looks right in the Builder arrives in Slack as `**bold**` with the asterisks
showing and `[text](url)` as literal brackets, which is the single most visible
way a channel integration looks unfinished.

None of this is a different agent, so none of it belongs in the spec. It is a
property of the *surface*, known here, and appended to the instructions for a run
that goes out on one. A binding's own prompt is appended after it, so an operator
can say something more specific without having to restate any of this.
"""

from app.services.channels.prompt_variables import CHANNEL_CONTEXT

LINK_ACCOUNT_INSTRUCTION = (
    "To connect your account, open a direct message with this bot and send `link` (without a slash). "
    "Open the private connection link while signed in to AgenticOS, then return "
    "here and ask again. Do not post the connection link in a channel."
)


CHANNEL_BEHAVIOR = """Channel conversation guidance:
- Answer in the sender's language. Be concise and give the concrete result first.
- Act on clear requests with available tools. Ask only for missing information or a required approval; do not offer a menu of work you can already do.
- Only claim an action succeeded after its tool confirms it. Distinguish unavailable tools, missing authentication, network failures and policy refusals.
- Organization MCP connections may work in channels. Personal services require the sender's linked AgenticOS identity and their own authorized connection to that service. Follow this run's service-specific availability briefing; linking alone does not connect every service. Never borrow the publisher's personal account.
- If identity linking is needed, tell the person to open a direct message with this bot and send plain `link` without a slash, sign in using the private connection link, then return here. Keep personal connection links out of group conversations.
- Channel and group replies are visible to their participants. Explain the next required step plainly, without exposing credentials or internal implementation details.
- Use read_channel_history for earlier channel messages, or scope="thread" for this thread. A bounded result or missing history tool does not prove older messages do not exist.
- An unavailable attachment is not an empty message. Use attachment notices to explain how to make it available; do not invent what an unseen image contains.
- Creating, reading or editing a workspace file does not send it. Use send_channel_file only when the user asks to receive or download that file and the tool is available. Report delivery failures honestly.
- Prefer balanced diagrams with readable labels over long horizontal chains."""


def runtime_context(surface: str, *, console_url: str, linked_sender: bool) -> str:
    """Facts the deployment knows, independent of an editable binding prompt."""
    names = {
        "mattermost": "Mattermost",
        "slack": "Slack",
        "teams": "Microsoft Teams",
        "telegram": "Telegram",
    }
    platform = names.get(surface)
    if platform is None:
        return ""
    identity = (
        "A linked sender identity is available to this run. Personal services still need their own connection."
        if linked_sender
        else "No linked sender identity is available to this run. Personal MCP services are unavailable; organization connections can still be available."
    )
    return (
        f"You are answering through {platform}, connected to the AgenticOS deployment at {console_url.rstrip('/')}. "
        "Your tools run in its managed workspace. Files on the person's own device are available only when attached or reached through an authorized connection. "
        + identity
    )


_MATTERMOST = """
You are answering in Mattermost. It renders Markdown, including headings, tables,
fenced code blocks and task lists.

- Links: `[what it is](https://example.com)` - never a bare URL on its own line,
  and never the URL as its own link text.
- Lead a link with an emoji when it is an action or a destination, e.g.
  📄 [the invoice](https://example.com/invoice) or
  🔗 [the run that needs approval](https://example.com/runs).
- Emoji shortcodes work (`:tada:`) and so do Unicode emoji. Use them to mark
  what a line is, not for decoration.
- Mention a person as `@username` and a channel as `~channel-name`.
- Keep paragraphs short. A wall of text in a chat window is skimmed and lost.
"""

_SLACK = """
You are answering in Slack, which does **not** render Markdown. It has its own
syntax, and standard Markdown arrives with the punctuation showing.

- Bold is `*one asterisk*`, italic is `_underscores_`, strikethrough is `~tildes~`.
- Links are `<https://example.com|what it is>`. Markdown link syntax renders as
  literal brackets.
- There are no headings. Use a bold line where you would have used one.
- Bullets are `•` at the start of a line; `-` is not a list to Slack.
- Fenced code blocks work. Tables do not - use a short list instead.
- Lead a link with an emoji when it is an action or a destination, e.g.
  📄 <https://example.com/invoice|the invoice>.
"""

_TELEGRAM = """
You are answering in Telegram, which renders a subset of Markdown.

- Links: `[what it is](https://example.com)`.
- Bold `*like this*` and italic `_like this_`. No headings, no tables.
- Every `*` and `_` must be closed. A malformed message is rejected outright, so
  when in doubt write plain text.
- Lead a link with an emoji when it is an action or a destination, e.g.
  📄 [the invoice](https://example.com/invoice).
- Keep answers short. Telegram splits a long message and the split is arbitrary.
"""

_TEAMS = """
You are answering in Microsoft Teams, which renders a subset of Markdown.

- Bold `**like this**`, italic `_like this_`, inline code and fenced code blocks.
- Links: `[what it is](https://example.com)`.
- Bulleted and numbered lists work. Headings and tables render poorly - use a
  bold line and a short list instead.
- Lead a link with an emoji when it is an action or a destination, e.g.
  📄 [the invoice](https://example.com/invoice).
- Keep paragraphs short. A chat pane is narrow, and a wall of text is skimmed.
"""

HOUSE_STYLE: dict[str, str] = {
    "mattermost": _MATTERMOST.strip(),
    "slack": _SLACK.strip(),
    "telegram": _TELEGRAM.strip(),
    "teams": _TEAMS.strip(),
}
"""Per platform, because the differences are not preferences - they are what the
client will and will not draw.

Keyed on `RunSurface` / `ChannelBot.platform`, which are the same vocabulary. A
surface with no entry - the dashboard, the API, an embedded widget - adds
nothing: those render what the Builder previews, which is what the agent was
written against.
"""


def house_style(surface: str) -> str:
    """What to tell an agent about the surface it is answering on."""
    style = HOUSE_STYLE.get(surface, "")
    if not style:
        return ""
    return f"{style}\n\n{CHANNEL_CONTEXT}\n\n{CHANNEL_BEHAVIOR}"
