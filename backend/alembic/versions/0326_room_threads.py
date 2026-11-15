"""Keep message subthreads separate from quoted replies inside their original room.

Revision ID: 0326_room_threads
Revises: 0325_merge_t3_rooms_v173

Existing quote links stay in the main transcript. The new nullable root names a
top-level message in the same conversation; deleting that root removes its thread
rather than moving replies into the main room. No new audience or room is created.

Both indexes are built concurrently. A failed build can leave the nullable column
and an index behind while the revision remains pending. A retry reuses exact valid
indexes, rebuilds only an exact invalid index, and stops without changing an
unexpected object or a running build. The unique index is attached to its
constraint after the build.

Adding the nullable column and attaching the unique constraint need brief
ACCESS EXCLUSIVE locks; these steps can wait behind long transactions. Foreign-key
and check constraints are added NOT VALID, then validated while ordinary writes
continue. Rehearse on a production-sized copy and watch for lock waits. Once thread
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


def _ensure_thread_column() -> None:
    """Add the nullable root column, or accept the exact shape left by a retry."""
    connection = op.get_bind()
    column = connection.execute(
        sa.text(
            "SELECT format_type(a.atttypid, a.atttypmod) = 'uuid' "
            "AND NOT a.attnotnull "
            "AND NOT EXISTS (SELECT 1 FROM pg_attrdef d WHERE d.adrelid = a.attrelid AND d.adnum = a.attnum) "
            "FROM pg_attribute a WHERE a.attrelid = 'messages'::regclass "
            "AND a.attname = 'thread_root_message_id' AND NOT a.attisdropped"
        )
    ).scalar_one_or_none()
    if column is None:
        op.add_column("messages", sa.Column("thread_root_message_id", sa.UUID(), nullable=True))
        return
    if not column:
        raise RuntimeError(
            "Existing thread_root_message_id is not the expected nullable UUID column; "
            "reconcile the schema before retrying revision 0326."
        )


def _index_build_running() -> bool:
    """Refuse to interfere with any concurrent index build on messages."""
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_progress_create_index p "
                "JOIN pg_locks l ON l.pid = p.pid "
                "WHERE p.pid <> pg_backend_pid() AND l.locktype = 'relation' "
                "AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                "AND l.relation = 'messages'::regclass)"
            )
        )
    )


def _index_state(name: str) -> tuple[bool, bool] | None:
    """Return whether a named index has the expected shape and is usable."""
    if name == "uq_messages_conversation_id_id":
        expected = (
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
            "AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = c.oid)"
        )
    elif name == "messages_thread_ordinal_idx":
        expected = (
            "i.indrelid = 'messages'::regclass AND NOT i.indisunique "
            "AND NOT i.indisprimary AND NOT i.indisexclusion "
            "AND i.indnkeyatts = 3 AND i.indnatts = 3 "
            "AND i.indexprs IS NULL AND a.amname = 'btree' "
            "AND i.indoption[0] = 0 AND i.indoption[1] = 0 AND i.indoption[2] = 0 "
            "AND i.indcollation[0] = 0 AND i.indcollation[1] = 0 AND i.indcollation[2] = 0 "
            "AND pg_get_indexdef(c.oid, 1, false) = 'conversation_id' "
            "AND pg_get_indexdef(c.oid, 2, false) = 'thread_root_message_id' "
            "AND pg_get_indexdef(c.oid, 3, false) = 'ordinal' "
            "AND pg_get_expr(i.indpred, i.indrelid, false) = '(thread_root_message_id IS NOT NULL)' "
            "AND EXISTS (SELECT 1 FROM pg_opclass o WHERE o.oid = i.indclass[0] "
            "AND o.opcmethod = a.oid AND o.opcnamespace = 'pg_catalog'::regnamespace "
            "AND o.opcname = 'uuid_ops' AND o.opcintype = 'uuid'::regtype AND o.opcdefault) "
            "AND EXISTS (SELECT 1 FROM pg_opclass o WHERE o.oid = i.indclass[1] "
            "AND o.opcmethod = a.oid AND o.opcnamespace = 'pg_catalog'::regnamespace "
            "AND o.opcname = 'uuid_ops' AND o.opcintype = 'uuid'::regtype AND o.opcdefault) "
            "AND EXISTS (SELECT 1 FROM pg_opclass o WHERE o.oid = i.indclass[2] "
            "AND o.opcmethod = a.oid AND o.opcnamespace = 'pg_catalog'::regnamespace "
            "AND o.opcname = 'int8_ops' AND o.opcintype = 'bigint'::regtype AND o.opcdefault)"
        )
    else:
        raise ValueError(f"Unexpected room-thread index name: {name}")

    index = (
        op.get_bind()
        .execute(
            sa.text(
                f"SELECT CASE WHEN c.relkind = 'i' THEN {expected} ELSE false END AS expected_definition, "
                "i.indisvalid AND i.indisready AND i.indislive AS usable "
                "FROM pg_class c LEFT JOIN pg_index i ON i.indexrelid = c.oid "
                "LEFT JOIN pg_am a ON a.oid = c.relam "
                "WHERE c.oid = to_regclass(:name)"
            ),
            {"name": name},
        )
        .one_or_none()
    )
    if index is None:
        return None
    return bool(index.expected_definition), bool(index.usable)


def _ensure_index(
    name: str,
    columns: list[str],
    *,
    unique: bool = False,
    where: sa.TextClause | None = None,
) -> None:
    """Build or safely reuse one of this revision's exact concurrent indexes."""
    state = _index_state(name)
    if state is not None:
        expected, usable = state
        if not expected:
            raise RuntimeError(
                f"Existing {name} is not the expected standalone index on messages; "
                "reconcile its definition and ownership before retrying revision 0326."
            )
        if usable:
            return
        if _index_build_running():
            raise RuntimeError(
                f"An index on messages is being built concurrently. Let it finish before "
                f"retrying revision 0326; {name} was left untouched."
            )
        op.drop_index(name, table_name="messages", postgresql_concurrently=True)

    op.create_index(
        name,
        "messages",
        columns,
        unique=unique,
        postgresql_where=where,
        postgresql_concurrently=True,
    )


def _assert_existing_index_expected(name: str) -> None:
    """Reject an occupied index name before committing the new thread column."""
    state = _index_state(name)
    if state is not None and not state[0]:
        actual = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT c.relkind, pg_get_indexdef(c.oid), "
                    "pg_get_expr(i.indpred, i.indrelid, false) "
                    "FROM pg_class c LEFT JOIN pg_index i ON i.indexrelid = c.oid "
                    "WHERE c.oid = to_regclass(:name)"
                ),
                {"name": name},
            )
            .one()
        )
        raise RuntimeError(
            f"Existing {name} is not the expected standalone index on messages; "
            f"found {actual!r}. Reconcile its definition and ownership before retrying revision 0326."
        )


def upgrade() -> None:
    if _index_build_running():
        raise RuntimeError(
            "An index on messages is being built concurrently; let it finish before retrying revision 0326."
        )
    _assert_existing_index_expected("uq_messages_conversation_id_id")
    _assert_existing_index_expected("messages_thread_ordinal_idx")
    _ensure_thread_column()
    with op.get_context().autocommit_block():
        if _index_build_running():
            raise RuntimeError(
                "An index on messages is being built concurrently; let it finish before retrying revision 0326."
            )
        _ensure_index(
            "uq_messages_conversation_id_id",
            ["conversation_id", "id"],
            unique=True,
        )
        _ensure_index(
            "messages_thread_ordinal_idx",
            ["conversation_id", "thread_root_message_id", "ordinal"],
            where=sa.text("thread_root_message_id IS NOT NULL"),
        )
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT uq_messages_conversation_id_id "
        "UNIQUE USING INDEX uq_messages_conversation_id_id"
    )
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT fk_messages_thread_root "
        "FOREIGN KEY (conversation_id, thread_root_message_id) "
        "REFERENCES messages (conversation_id, id) ON DELETE CASCADE NOT VALID"
    )
    op.execute("ALTER TABLE messages VALIDATE CONSTRAINT fk_messages_thread_root")
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT messages_thread_root_not_self_check "
        "CHECK (thread_root_message_id <> id) NOT VALID"
    )
    op.execute("ALTER TABLE messages VALIDATE CONSTRAINT messages_thread_root_not_self_check")


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM messages WHERE thread_root_message_id IS NOT NULL)")
    ):
        raise RuntimeError(
            "Cannot remove room thread scopes while replies exist; retain a thread-aware app "
            "or restore a matching pre-upgrade backup"
        )
    op.drop_index("messages_thread_ordinal_idx", table_name="messages")
    op.execute("ALTER TABLE messages DROP CONSTRAINT messages_thread_root_not_self_check")
    op.drop_constraint("fk_messages_thread_root", "messages", type_="foreignkey")
    op.drop_constraint("uq_messages_conversation_id_id", "messages", type_="unique")
    op.drop_column("messages", "thread_root_message_id")
