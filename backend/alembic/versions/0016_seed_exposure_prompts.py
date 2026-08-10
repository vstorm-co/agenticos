"""Give bindings that already exist the style their platform needs.

`agent_exposures.prompt` opens holding what that chat client renders - Slack
draws no Markdown and writes a link as `<url|text>`, Mattermost renders
headings and tables, Telegram rejects an unclosed `*`. A binding made before
the column existed has nothing in it, so its agent writes GitHub Markdown
into a client that shows the asterisks.

Only where it is empty. The text is the row's own from the moment it is
created - editable, and deletable on purpose - so overwriting one somebody
has already changed would be this migration having an opinion about their
wording.

Revision ID: 0016_seed_exposure_prompts
Revises: 0015_exposure_prompt
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_seed_exposure_prompts"
down_revision: str | Sequence[str] | None = "0015_exposure_prompt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The same text `app/services/channels/formatting.py` holds as `HOUSE_STYLE`,
# spelled out here rather than imported - as `0019` does with its default, and
# for the same reason: a migration must not import application code, because
# `downgrade()` matches `prompt = :prompt` against this text, and a later edit
# to the constant would silently stop this migration clearing the rows it
# seeded. A migration that ran once has to keep meaning what it meant.
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

_SEED_PROMPTS: dict[str, str] = {
    "mattermost": _MATTERMOST.strip(),
    "slack": _SLACK.strip(),
    "telegram": _TELEGRAM.strip(),
}

_SEED = sa.text(
    "UPDATE agent_exposures SET prompt = :prompt "
    "WHERE surface = :surface AND (prompt IS NULL OR prompt = '')"
)


def upgrade() -> None:
    bind = op.get_bind()
    for surface, style in _SEED_PROMPTS.items():
        bind.execute(_SEED, {"prompt": style, "surface": surface})


def downgrade() -> None:
    """Clear only what this put there, and only if it is untouched.

    A binding whose text somebody edited is theirs, and a downgrade that
    deleted it would lose work to a schema change that never touched it.
    """
    bind = op.get_bind()
    for surface, style in _SEED_PROMPTS.items():
        bind.execute(
            sa.text(
                "UPDATE agent_exposures SET prompt = NULL "
                "WHERE surface = :surface AND prompt = :prompt"
            ),
            {"prompt": style, "surface": surface},
        )
