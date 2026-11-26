"""Store a code and its numbers beside the English failure of a session and a request.

`improvement_runs.error` and `authoring_requests.error` hold a sentence the
backend wrote in English, and the console printed it as sent, so a reader in any
other language read it in English. `error_code` names the failure from a closed
set (`ImprovementFailure`, `AuthoringFailure`) and `error_params` holds the only
values a sentence interpolates - counts and minimums, never text - so the console
words it in the reader's language. The sentence stays for API clients and the
platform's own tools.

Rows written before this revision are given a code only where their sentence is
one the backend writes word for word, or one of the three that carry a number; a
refusal's own message (a failure mid-step) is open text and stays without a code,
which the console shows as stored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0369_run_error_code"
down_revision: str | None = "0370_console_role_presentation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("improvement_runs", "authoring_requests")

_SESSION_SENTENCES = {
    "No rated chat runs or training failures are available yet": "no_evidence",
}

_SESSION_COUNTED = (
    (
        "too_few_held_out",
        "missing",
        r"^Add ([0-9]{1,9}) more held-out test questions to measure a change$",
    ),
    (
        "search_too_few_training",
        "minimum",
        r"^A search needs at least ([0-9]{1,9}) training questions for this attempt$",
    ),
)

_REQUEST_SENTENCES = {
    "Whoever started this may no longer read runs.": "no_runs_view",
    "An evidence source was erased while the assistant worked. Start again with current evidence.": (
        "evidence_erased"
    ),
    "Whoever started this may no longer edit the agent.": "no_edit_agent",
    "The agent is gone.": "agent_gone",
    "The agent has no published version to compare with.": "no_published_version",
    "The skill is gone.": "skill_gone",
    "Whoever started this may no longer edit the skill.": "no_edit_skill",
    "The improvement session moved on.": "session_moved_on",
    "The assistant did not answer every conflict; settle them at Changes.": "conflicts_unanswered",
    "The improvement session stopped.": "session_stopped",
    "The context file is gone.": "context_gone",
    "Whoever started this may no longer edit the context file.": "no_edit_context",
    "Nothing to learn from yet: no run in this window was rated or failed. Widen the window, "
    "or come back once people have rated some answers.": "no_evidence",
    "The API key that started this was revoked or no longer exists, so it was stopped.": "key_revoked",
    "Whoever started this is no longer a member.": "not_a_member",
    "The assistant stopped unexpectedly. Try again.": "unexpected",
    "The assistant stopped without finishing. Try again.": "stalled",
    "The request was cancelled before it started. Try again.": "withdrawn",
}

_REQUEST_COUNTED = (
    (
        "unknown_skill_use",
        "runs",
        r"^No run in this window is known to have used the skill\. ([0-9]{1,9}) rated-down or "
        r"failed runs are from before uses were recorded, so whether they used it is unknown\.$",
    ),
)


def _backfill(
    table: str, sentences: dict[str, str], counted: tuple[tuple[str, str, str], ...]
) -> None:
    bind = op.get_bind()
    for sentence, code in sentences.items():
        bind.execute(
            sa.text(
                f"UPDATE {table} SET error_code = :code "
                "WHERE error_code IS NULL AND error = :sentence"
            ),
            {"code": code, "sentence": sentence},
        )
    for code, name, pattern in counted:
        bind.execute(
            sa.text(
                f"UPDATE {table} SET error_code = :code, "
                "error_params = jsonb_build_object(:name, substring(error from :pattern)::int) "
                "WHERE error_code IS NULL AND error ~ :pattern"
            ),
            {"code": code, "name": name, "pattern": pattern},
        )


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("error_code", sa.String(length=64), nullable=True))
        op.add_column(
            table,
            sa.Column("error_params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    _backfill("improvement_runs", _SESSION_SENTENCES, _SESSION_COUNTED)
    _backfill("authoring_requests", _REQUEST_SENTENCES, _REQUEST_COUNTED)


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, "error_params")
        op.drop_column(table, "error_code")
