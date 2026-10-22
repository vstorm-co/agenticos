"""Who a dataset case's words belong to, and when an erasure anonymised them (#2373).

Erasing a person replaces the text of every case taken from their conversations
or runs, in every revision that held it, so a revision is no longer immutable in
that one respect. `anonymised_at` marks what happened, so the case reads as
anonymised rather than as a case somebody wrote that way, and an eval run leaves
it out until its curator rewrites it.

An erasure has to find those cases after the conversation or run they came from
is gone, so authorship is kept on the case itself: who asked its question, who
wrote each turn of its history, and whose rating comment became its note. The
existing rows are backfilled from the links they still hold. A turn that matches
two messages of its thread is left without an author rather than guessed, and a
case whose source was deleted before this revision has none to backfill from;
the counts are logged.

A downgrade drops the columns, and the placeholder text stays.

Revision ID: 0177_dataset_case_anonymised_at
Revises: 0173_eval_job_pool
Create Date: 2026-10-22
"""

import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0177_dataset_case_anonymised_at"
down_revision: str | None = "0173_eval_job_pool"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

# Turns from before authors were kept fall back to the thread's owner, which only
# a console thread outside a project can vouch for.
_SPEAKER = """
    COALESCE(
        m.author_user_id,
        ci.user_id,
        CASE WHEN m.channel_identity_id IS NULL AND c.project_id IS NULL THEN c.user_id END
    )
"""


def _asked_by(bind: sa.Connection) -> None:
    bind.execute(
        sa.text(
            """
            UPDATE dataset_cases AS dc
            SET asked_by_user_id = COALESCE(
                CASE WHEN r.initiated_by_publisher_fallback THEN NULL ELSE r.user_id END,
                ci.user_id
            )
            FROM agent_runs AS r
            LEFT JOIN channel_identities AS ci ON ci.id = r.channel_identity_id
            WHERE dc.source_run_id = r.id
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            UPDATE dataset_cases AS dc
            SET asked_by_user_id = asked.speaker
            FROM messages AS source
            CROSS JOIN LATERAL (
                SELECT {_SPEAKER} AS speaker
                FROM messages AS m
                JOIN conversations AS c ON c.id = m.conversation_id
                LEFT JOIN channel_identities AS ci ON ci.id = m.channel_identity_id
                WHERE m.conversation_id = source.conversation_id
                  AND m.role = 'user'
                  AND m.ordinal <= source.ordinal
                ORDER BY m.ordinal DESC
                LIMIT 1
            ) AS asked
            WHERE dc.asked_by_user_id IS NULL AND dc.source_message_id = source.id
            """
        )
    )


def _history_authors(bind: sa.Connection) -> None:
    bind.execute(
        sa.text(
            "UPDATE dataset_cases "
            "SET history_author_ids = array_fill(NULL::uuid, ARRAY[jsonb_array_length(history)])"
        )
    )
    cases = bind.execute(
        sa.text(
            "SELECT id, source_conversation_id, history FROM dataset_cases "
            "WHERE jsonb_array_length(history) > 0"
        )
    ).all()
    matched = ambiguous = unmatched = without_source = 0
    turns_by_thread: dict[UUID, list[tuple[str, UUID | None]]] = {}
    for case_id, conversation_id, history in cases:
        if conversation_id is None:
            without_source += 1
            continue
        if conversation_id not in turns_by_thread:
            turns_by_thread[conversation_id] = [
                (" ".join(content.split()), speaker)
                for content, speaker in bind.execute(
                    sa.text(
                        f"""
                        SELECT m.content, {_SPEAKER}
                        FROM messages AS m
                        JOIN conversations AS c ON c.id = m.conversation_id
                        LEFT JOIN channel_identities AS ci ON ci.id = m.channel_identity_id
                        WHERE m.conversation_id = :conversation AND m.role = 'user'
                        """
                    ),
                    {"conversation": conversation_id},
                ).all()
            ]
        written = turns_by_thread[conversation_id]
        authors: list[Any] = []
        for turn in history:
            if turn.get("role") != "user":
                authors.append(None)
                continue
            said = " ".join(str(turn.get("content", "")).split())
            found = [speaker for content, speaker in written if content == said]
            if len(found) == 1:
                matched += 1
            elif found:
                ambiguous += 1
            else:
                unmatched += 1
            authors.append(found[0] if len(found) == 1 else None)
        if any(authors):
            bind.execute(
                sa.text("UPDATE dataset_cases SET history_author_ids = :authors WHERE id = :id"),
                {"authors": authors, "id": case_id},
            ).close()
    logger.info(
        "dataset case history authors: %d turns matched, %d ambiguous, %d unmatched; "
        "%d cases with a history but no source thread",
        matched,
        ambiguous,
        unmatched,
        without_source,
    )


def _noted_by(bind: sa.Connection) -> None:
    bind.execute(
        sa.text(
            """
            UPDATE dataset_cases AS dc
            SET noted_by_user_id = noter.user_id
            FROM (
                SELECT dc2.id AS case_id, min(mr.user_id::text)::uuid AS user_id
                FROM dataset_cases AS dc2
                JOIN messages AS m ON m.run_id = dc2.source_run_id
                JOIN message_ratings AS mr ON mr.message_id = m.id
                WHERE dc2.note IS NOT NULL AND btrim(mr.comment) = btrim(dc2.note)
                GROUP BY dc2.id
                HAVING count(DISTINCT mr.user_id) = 1
            ) AS noter
            WHERE dc.id = noter.case_id
            """
        )
    )


def upgrade() -> None:
    op.add_column(
        "dataset_cases",
        sa.Column("anonymised_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("asked_by_user_id", "noted_by_user_id"):
        op.add_column(
            "dataset_cases",
            sa.Column(column, postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            op.f(f"dataset_cases_{column}_fkey"),
            "dataset_cases",
            "users",
            [column],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"dataset_cases_{column}_idx", "dataset_cases", [column])
    op.add_column(
        "dataset_cases",
        sa.Column(
            "history_author_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
            nullable=False,
        ),
    )

    bind = op.get_bind()
    _asked_by(bind)
    _history_authors(bind)
    _noted_by(bind)
    counts = bind.execute(
        sa.text(
            "SELECT count(*) FILTER (WHERE asked_by_user_id IS NOT NULL), "
            "count(*) FILTER (WHERE asked_by_user_id IS NULL AND source IN ('conversation', "
            "'synthetic') AND source_run_id IS NULL AND source_message_id IS NULL), "
            "count(*) FILTER (WHERE noted_by_user_id IS NOT NULL) FROM dataset_cases"
        )
    ).one()
    logger.info(
        "dataset case authors: %d asked by a known person, %d taken from a conversation "
        "whose source is gone, %d notes attributed",
        *counts,
    )

    # Named as the model names them, so `alembic check` sees one object, not two.
    op.create_check_constraint(
        "ck_dataset_case_history_authors",
        "dataset_cases",
        "cardinality(history_author_ids) = jsonb_array_length(history)",
    )
    op.create_index(
        "ix_dataset_cases_history_author_ids",
        "dataset_cases",
        ["history_author_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_cases_history_author_ids", table_name="dataset_cases")
    op.drop_constraint("ck_dataset_case_history_authors", "dataset_cases", type_="check")
    op.drop_column("dataset_cases", "history_author_ids")
    for column in ("noted_by_user_id", "asked_by_user_id"):
        op.drop_index(f"dataset_cases_{column}_idx", table_name="dataset_cases")
        op.drop_constraint(
            op.f(f"dataset_cases_{column}_fkey"), "dataset_cases", type_="foreignkey"
        )
        op.drop_column("dataset_cases", column)
    op.drop_column("dataset_cases", "anonymised_at")
