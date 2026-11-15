"""Keep message subthreads separate from quoted replies inside their original room.

Revision ID: 0326_room_threads
Revises: 0325_merge_t3_rooms_v173

Existing quote links stay in the main transcript. The new nullable root names a
top-level message in the same conversation; deleting that root removes its thread
rather than moving replies into the main room. No new audience or room is created.

The upgrade stays in Alembic's transaction: a failure leaves neither a partial
thread column nor a stamped revision. An operator may prebuild the composite
unique index concurrently before upgrading; only its exact valid, standalone
definition is adopted. A conflicting or unfinished index is left for explicit
reconciliation, not dropped or silently accepted.

The remaining DDL takes an ACCESS EXCLUSIVE lock on messages and builds the
thread lookup index. Schedule a room read/write maintenance window, drain active
turn workers, and measure the upgrade on a production-sized copy. Once thread
replies exist, rollback requires a thread-aware application or a matching
pre-upgrade backup; downgrade refuses to flatten their scopes.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0326_room_threads"
down_revision: str | None = "0325_merge_t3_rooms_v173"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _prebuilt_root_index() -> bool:
    """Adopt only the exact index prepared outside the migration transaction."""
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_attribute "
            "WHERE attrelid = 'messages'::regclass "
            "AND attname = 'thread_root_message_id' AND NOT attisdropped)"
        )
    ):
        raise RuntimeError(
            "Room thread column already exists while revision 0326 is pending; "
            "reconcile the partial schema before retrying. Preserve any thread replies "
            "and do not automatically drop the column."
        )
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM pg_stat_progress_create_index p "
            "JOIN pg_locks l ON l.pid = p.pid "
            "WHERE p.pid <> pg_backend_pid() AND l.locktype = 'relation' "
            "AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
            "AND l.relation = 'messages'::regclass)"
        )
    ):
        raise RuntimeError(
            "An index on messages is being built concurrently; let it finish or cancel "
            "and reconcile the build before retrying revision 0326."
        )
    # The column form of pg_get_indexdef omits ordering and operator classes.
    # Check their catalog values before adopting an operator-prepared index.
    index = connection.execute(
        sa.text(
            "SELECT CASE WHEN c.relkind = 'i' THEN "
            "i.indrelid = 'messages'::regclass AND i.indisunique AND i.indimmediate "
            "AND NOT i.indisprimary AND NOT i.indisexclusion AND NOT i.indnullsnotdistinct "
            "AND i.indnkeyatts = 2 AND i.indnatts = 2 "
            "AND i.indexprs IS NULL AND i.indpred IS NULL AND a.amname = 'btree' "
            "AND i.indoption[0] = 0 AND i.indoption[1] = 0 "
            "AND i.indcollation[0] = 0 AND i.indcollation[1] = 0 "
            "AND i.indclass[0] = i.indclass[1] "
            "AND EXISTS (SELECT 1 FROM pg_opclass o WHERE o.oid = i.indclass[0] "
            "AND o.opcmethod = a.oid AND o.opcnamespace = 'pg_catalog'::regnamespace "
            "AND o.opcname = 'uuid_ops' AND o.opcintype = 'uuid'::regtype AND o.opcdefault) "
            "AND pg_get_indexdef(c.oid, 1, false) = 'conversation_id' "
            "AND pg_get_indexdef(c.oid, 2, false) = 'id' "
            "AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = c.oid) "
            "ELSE false END AS expected_definition, "
            "i.indisvalid AND i.indisready AND i.indislive AS usable "
            "FROM pg_class c LEFT JOIN pg_index i ON i.indexrelid = c.oid "
            "LEFT JOIN pg_am a ON a.oid = c.relam "
            "WHERE c.oid = to_regclass('uq_messages_conversation_id_id')"
        )
    ).one_or_none()
    if index is None:
        return False
    if not index.expected_definition:
        raise RuntimeError(
            "Existing uq_messages_conversation_id_id is not the expected standalone "
            "unique btree index on messages (conversation_id, id); reconcile its "
            "definition and constraint ownership before retrying revision 0326."
        )
    if not index.usable:
        raise RuntimeError(
            "Existing uq_messages_conversation_id_id is not valid and ready; reconcile "
            "any interrupted concurrent build, then rebuild the exact index before "
            "retrying revision 0326. The migration will not drop it."
        )
    return True


def upgrade() -> None:
    prebuilt = _prebuilt_root_index()
    op.add_column("messages", sa.Column("thread_root_message_id", sa.UUID(), nullable=True))
    if prebuilt:
        op.execute(
            "ALTER TABLE messages ADD CONSTRAINT uq_messages_conversation_id_id "
            "UNIQUE USING INDEX uq_messages_conversation_id_id"
        )
    else:
        op.create_unique_constraint(
            "uq_messages_conversation_id_id", "messages", ["conversation_id", "id"]
        )
    op.create_foreign_key(
        "fk_messages_thread_root",
        "messages",
        "messages",
        ["conversation_id", "thread_root_message_id"],
        ["conversation_id", "id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint("thread_root_not_self", "messages", "thread_root_message_id <> id")
    op.create_index(
        "messages_thread_ordinal_idx",
        "messages",
        ["conversation_id", "thread_root_message_id", "ordinal"],
        postgresql_where=sa.text("thread_root_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM messages WHERE thread_root_message_id IS NOT NULL)")
    ):
        raise RuntimeError(
            "Cannot remove room thread scopes while replies exist; retain a thread-aware app "
            "or restore a matching pre-upgrade backup"
        )
    op.drop_index("messages_thread_ordinal_idx", table_name="messages")
    op.drop_constraint("thread_root_not_self", "messages", type_="check")
    op.drop_constraint("fk_messages_thread_root", "messages", type_="foreignkey")
    op.drop_constraint("uq_messages_conversation_id_id", "messages", type_="unique")
    op.drop_column("messages", "thread_root_message_id")
