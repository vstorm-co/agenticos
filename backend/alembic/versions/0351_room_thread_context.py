"""Keep room context exact while message placement changes.

A saved range needs the source conversation, its normalized ordinal boundaries,
the explicit exclusions and the exact included IDs. Bounds alone would recalculate
an overlapping range differently after a later move; the snapshot is what makes a
return or a subsequent edit refer to the same rows. The arrays are bounded in the
database, and composite boundary FKs prove both endpoints still belong to the
recorded source conversation.

`RoomSubmission` also needs a physical `thread_root_message_id`. Its accepted
request scope is immutable, while `Message.thread_root_message_id` becomes mutable
when selected context moves. Keeping a computed join would make queue history and
resumed work silently adopt a later placement. The new column is nullable because
top-level posts have no thread root, and existing rows are backfilled from their
message: releases before this migration cannot move ranges, so current placement is
the only accepted scope they could have recorded.

The alternative is to keep deriving accepted scope from the message and add a
second snapshot only when a worker starts. That leaves the gap between acceptance
and worker execution exposed to a move, so it cannot preserve the original request.
This migration closes that gap at acceptance time and adds `transcript_revision`
for summaries built before a context or topology change. Downgrade checks both
saved context evidence and changed accepted scopes before removing the columns.

`context_used` retains the source boundary after replies or requests are deleted.
Once the context has been used, deleting the marker or replacing its source must
not detach earlier answers or quotes from the source room's access rules.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0351_room_thread_context"
down_revision: str | None = "0350_room_thread_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("transcript_revision", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "room_submissions",
        sa.Column("thread_root_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE room_submissions AS submission "
            "SET thread_root_message_id = message.thread_root_message_id "
            "FROM messages AS message "
            "WHERE submission.message_id = message.id "
            "AND submission.conversation_id = message.conversation_id"
        )
    )

    op.add_column(
        "room_threads",
        sa.Column("context_source_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "room_threads",
        sa.Column("context_start_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "room_threads",
        sa.Column("context_end_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "room_threads", sa.Column("context_first_ordinal", sa.BigInteger(), nullable=True)
    )
    op.add_column("room_threads", sa.Column("context_last_ordinal", sa.BigInteger(), nullable=True))
    op.add_column(
        "room_threads",
        sa.Column(
            "context_excluded_message_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
    )
    op.add_column(
        "room_threads",
        sa.Column(
            "context_message_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default=sa.text("'{}'::uuid[]"),
            nullable=False,
        ),
    )
    op.add_column(
        "room_threads",
        sa.Column("context_moved", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "room_threads",
        sa.Column("context_used", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "room_threads",
        sa.Column("context_revision", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_foreign_key(
        "fk_room_thread_context_source",
        "room_threads",
        "conversations",
        ["organization_id", "context_source_conversation_id"],
        ["organization_id", "id"],
    )
    op.create_foreign_key(
        "fk_room_thread_context_start_message",
        "room_threads",
        "messages",
        ["context_source_conversation_id", "context_start_message_id"],
        ["conversation_id", "id"],
    )
    op.create_foreign_key(
        "fk_room_thread_context_end_message",
        "room_threads",
        "messages",
        ["context_source_conversation_id", "context_end_message_id"],
        ["conversation_id", "id"],
    )
    op.create_check_constraint(
        op.f("room_threads_ck_room_thread_context_revision_check"),
        "room_threads",
        "context_revision >= 0",
    )
    op.create_check_constraint(
        op.f("room_threads_ck_room_thread_context_shape_check"),
        "room_threads",
        "(context_source_conversation_id IS NULL "
        "AND context_start_message_id IS NULL "
        "AND context_end_message_id IS NULL "
        "AND context_first_ordinal IS NULL "
        "AND context_last_ordinal IS NULL "
        "AND cardinality(context_excluded_message_ids) = 0 "
        "AND cardinality(context_message_ids) = 0 "
        "AND context_moved IS FALSE "
        "AND context_used IS FALSE "
        "AND context_revision = 0) OR "
        "(context_source_conversation_id IS NOT NULL "
        "AND context_start_message_id IS NOT NULL "
        "AND context_end_message_id IS NOT NULL "
        "AND context_first_ordinal IS NOT NULL "
        "AND context_last_ordinal IS NOT NULL "
        "AND context_first_ordinal >= 0 "
        "AND context_last_ordinal >= context_first_ordinal "
        "AND cardinality(context_excluded_message_ids) <= 500 "
        "AND cardinality(context_message_ids) BETWEEN 1 AND 500 "
        "AND context_revision > 0 "
        "AND (context_moved IS FALSE OR context_source_conversation_id = conversation_id))",
    )
    op.create_index(
        "ix_room_threads_context_source_range",
        "room_threads",
        [
            "organization_id",
            "context_source_conversation_id",
            "context_first_ordinal",
            "context_last_ordinal",
        ],
        postgresql_where=sa.text("context_source_conversation_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE conversations, room_submissions, room_threads IN ACCESS EXCLUSIVE MODE")
    evidence = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM room_threads WHERE "
            "context_source_conversation_id IS NOT NULL "
            "OR cardinality(context_excluded_message_ids) > 0 "
            "OR cardinality(context_message_ids) > 0 "
            "OR context_moved IS TRUE "
            "OR context_used IS TRUE "
            "OR context_revision <> 0) "
            "OR EXISTS (SELECT 1 FROM conversations WHERE transcript_revision <> 0)"
        )
    )
    if evidence:
        raise RuntimeError("Cannot discard saved room thread context or transcript revisions")

    scope_changed = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM room_submissions AS submission "
            "JOIN messages AS message ON message.id = submission.message_id "
            "AND message.conversation_id = submission.conversation_id "
            "WHERE submission.thread_root_message_id IS DISTINCT FROM "
            "message.thread_root_message_id)"
        )
    )
    if scope_changed:
        raise RuntimeError(
            "Cannot discard accepted room submission scopes after message placement changed"
        )

    op.drop_index("ix_room_threads_context_source_range", table_name="room_threads")
    op.drop_constraint("fk_room_thread_context_end_message", "room_threads", type_="foreignkey")
    op.drop_constraint("fk_room_thread_context_start_message", "room_threads", type_="foreignkey")
    op.drop_constraint("fk_room_thread_context_source", "room_threads", type_="foreignkey")
    op.drop_constraint(
        op.f("room_threads_ck_room_thread_context_shape_check"), "room_threads", type_="check"
    )
    op.drop_constraint(
        op.f("room_threads_ck_room_thread_context_revision_check"), "room_threads", type_="check"
    )
    op.drop_column("room_threads", "context_revision")
    op.drop_column("room_threads", "context_used")
    op.drop_column("room_threads", "context_moved")
    op.drop_column("room_threads", "context_message_ids")
    op.drop_column("room_threads", "context_excluded_message_ids")
    op.drop_column("room_threads", "context_last_ordinal")
    op.drop_column("room_threads", "context_first_ordinal")
    op.drop_column("room_threads", "context_end_message_id")
    op.drop_column("room_threads", "context_start_message_id")
    op.drop_column("room_threads", "context_source_conversation_id")
    op.drop_column("room_submissions", "thread_root_message_id")
    op.drop_column("conversations", "transcript_revision")
