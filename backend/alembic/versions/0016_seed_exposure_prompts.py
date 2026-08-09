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
from app.services.channels.formatting import HOUSE_STYLE

revision: str = "0016_seed_exposure_prompts"
down_revision: str | Sequence[str] | None = "0015_exposure_prompt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SEED = sa.text(
    "UPDATE agent_exposures SET prompt = :prompt "
    "WHERE surface = :surface AND (prompt IS NULL OR prompt = '')"
)


def upgrade() -> None:
    bind = op.get_bind()
    for surface, style in HOUSE_STYLE.items():
        bind.execute(_SEED, {"prompt": style, "surface": surface})


def downgrade() -> None:
    """Clear only what this put there, and only if it is untouched.

    A binding whose text somebody edited is theirs, and a downgrade that
    deleted it would lose work to a schema change that never touched it.
    """
    bind = op.get_bind()
    for surface, style in HOUSE_STYLE.items():
        bind.execute(
            sa.text(
                "UPDATE agent_exposures SET prompt = NULL "
                "WHERE surface = :surface AND prompt = :prompt"
            ),
            {"prompt": style, "surface": surface},
        )
