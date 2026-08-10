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

from __future__ import annotations

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

HOUSE_STYLE: dict[str, str] = {
    "mattermost": _MATTERMOST.strip(),
    "slack": _SLACK.strip(),
    "telegram": _TELEGRAM.strip(),
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
    return HOUSE_STYLE.get(surface, "")
