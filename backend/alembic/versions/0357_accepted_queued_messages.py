"""Add durable personal queue receipts without blocking chat-history scans.

Revision ID: 0357_accepted_queued_messages
Revises: 0356_trigger_webhook_receipts
Create Date: 2026-11-25

Nullable columns and constraint attachment need brief catalog locks, limited to
five seconds. Three full unique indexes build concurrently before the receipt
table and provenance constraints are committed; existing rows are then validated
without retaining those catalog locks. API, worker and console activation must
wait for the complete revision.

An interrupted build may leave nullable columns and standalone indexes. Retry
accepts only their exact definitions, rebuilds an exact invalid standalone index,
and refuses an active build or conflicting object. If validation was interrupted,
the complete committed schema is checked before validation resumes. Downgrade
refuses every retained receipt rather than discarding execution ownership.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0357_accepted_queued_messages"
down_revision: str | None = "0356_trigger_webhook_receipts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_QUEUE_COLUMNS = (
    ("chat_files", "queue_receipt_id"),
    ("messages", "accepted_queue_id"),
    ("agent_runs", "accepted_queue_id"),
    ("conversation_tasks", "queue_receipt_id"),
)
_QUEUE_UNIQUE = (
    ("messages", "accepted_queue_id", "uq_message_accepted_queue"),
    ("agent_runs", "accepted_queue_id", "uq_agent_run_accepted_queue"),
    ("conversation_tasks", "queue_receipt_id", "uq_conversation_task_queue_receipt"),
)
_QUEUE_FKS = (
    ("chat_files", "queue_receipt_id", "fk_chat_files_queue_receipt", "SET NULL"),
    ("messages", "accepted_queue_id", "fk_message_accepted_queue", "SET NULL"),
    ("agent_runs", "accepted_queue_id", "fk_agent_run_accepted_queue", "SET NULL"),
    ("conversation_tasks", "queue_receipt_id", "fk_conversation_task_queue_receipt", "CASCADE"),
)
_FILE_CHECK = "chat_files_ck_chat_file_message_or_queue_check"
_TASK_CHECK = "conversation_tasks_ck_conversation_task_provenance_check"
_CHECKS = (
    (
        "chat_files",
        _FILE_CHECK,
        "((message_id IS NULL) OR (queue_receipt_id IS NULL))",
    ),
    (
        "conversation_tasks",
        _TASK_CHECK,
        "(((source_run_id IS NOT NULL) AND (tool_call_id IS NOT NULL) "
        "AND (queue_receipt_id IS NULL)) OR ((source_run_id IS NULL) "
        "AND (tool_call_id IS NULL) AND (queue_receipt_id IS NOT NULL)))",
    ),
)
_RECEIPT_CHECKS = (
    (
        "accepted_queued_messages",
        "accepted_queued_messages_ck_accepted_queue_state_check",
        "((state)::text = ANY ((ARRAY['pending'::character varying, "
        "'steering'::character varying, 'steered'::character varying, "
        "'sent'::character varying, 'task'::character varying, "
        "'cancelled'::character varying])::text[]))",
    ),
    (
        "accepted_queued_messages",
        "accepted_queued_messages_ck_accepted_queue_payload_hash_check",
        "(char_length((payload_hash)::text) = 64)",
    ),
)


def _refuse(detail: str) -> None:
    raise RuntimeError(
        f"Cannot resume revision 0357: {detail}. "
        "Reconcile the unexpected object before retrying; it was left untouched."
    )


def _ensure_column(table: str, name: str, *, add: bool) -> None:
    column = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT format_type(a.atttypid, a.atttypmod) = 'uuid' "
                "AND NOT a.attnotnull AND NOT EXISTS "
                "(SELECT 1 FROM pg_attrdef d WHERE d.adrelid = a.attrelid AND d.adnum = a.attnum) "
                "FROM pg_attribute a WHERE a.attrelid = to_regclass(:table) "
                "AND a.attname = :name AND NOT a.attisdropped"
            ),
            {"table": table, "name": name},
        )
        .scalar_one_or_none()
    )
    if column is None and add:
        op.add_column(table, sa.Column(name, postgresql.UUID(as_uuid=True), nullable=True))
    elif column is not True:
        _refuse(f"{table}.{name} is not the expected nullable UUID column")


def _index_build_running(table: str) -> bool:
    return bool(
        op.get_bind().scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_progress_create_index p "
                "JOIN pg_locks l ON l.pid = p.pid "
                "WHERE p.pid <> pg_backend_pid() AND l.locktype = 'relation' "
                "AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                "AND l.relation = to_regclass(:table))"
            ),
            {"table": table},
        )
    )


def _index_state(table: str, column: str, name: str) -> tuple[bool, bool, bool] | None:
    """Recognize only this revision's exact UUID uniqueness, attached or standalone."""
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT CASE WHEN c.relkind = 'i' THEN "
                "i.indrelid = to_regclass(:table) AND i.indisunique AND i.indimmediate "
                "AND NOT i.indisprimary AND NOT i.indisexclusion AND NOT i.indnullsnotdistinct "
                "AND i.indnkeyatts = 1 AND i.indnatts = 1 "
                "AND i.indexprs IS NULL AND i.indpred IS NULL AND a.amname = 'btree' "
                "AND i.indoption[0] = 0 AND i.indcollation[0] = 0 "
                "AND pg_get_indexdef(c.oid, 1, false) = :column "
                "AND EXISTS (SELECT 1 FROM pg_opclass o WHERE o.oid = i.indclass[0] "
                "AND o.opcmethod = a.oid AND o.opcnamespace = 'pg_catalog'::regnamespace "
                "AND o.opcname = 'uuid_ops' AND o.opcintype = 'uuid'::regtype AND o.opcdefault) "
                "AND NOT EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = c.oid "
                "AND k.contype IN ('p', 'u', 'x') AND NOT "
                "(k.contype = 'u' AND k.conname = :name AND k.conrelid = to_regclass(:table) "
                "AND NOT k.condeferrable AND NOT k.condeferred AND k.convalidated)) "
                "ELSE false END AS expected, "
                "i.indisvalid AND i.indisready AND i.indislive AS usable, "
                "EXISTS (SELECT 1 FROM pg_constraint k WHERE k.conindid = c.oid "
                "AND k.contype IN ('p', 'u', 'x')) AS attached "
                "FROM pg_class c LEFT JOIN pg_index i ON i.indexrelid = c.oid "
                "LEFT JOIN pg_am a ON a.oid = c.relam WHERE c.oid = to_regclass(:name)"
            ),
            {"table": table, "column": column, "name": name},
        )
        .one_or_none()
    )
    if row is None:
        return None
    return bool(row.expected), bool(row.usable), bool(row.attached)


def _ensure_index(table: str, column: str, name: str) -> None:
    if _index_build_running(table):
        _refuse(f"an index build on {table} is still running")
    state = _index_state(table, column, name)
    if state is not None:
        expected, usable, attached = state
        if not expected or attached:
            _refuse(f"{name} is not the expected standalone index on {table}")
        if usable:
            return
        op.drop_index(name, table_name=table, postgresql_concurrently=True)
    op.create_index(name, table, [column], unique=True, postgresql_concurrently=True)


@contextmanager
def _autocommit_ddl() -> Iterator[None]:
    """Keep a bounded lock wait across concurrent DDL without changing the session."""
    with op.get_context().autocommit_block():
        connection = op.get_bind()
        previous = connection.scalar(sa.text("SELECT current_setting('lock_timeout')"))
        connection.execute(sa.text("SELECT set_config('lock_timeout', '5s', false)"))
        try:
            yield
        finally:
            connection.execute(
                sa.text("SELECT set_config('lock_timeout', :value, false)"), {"value": previous}
            )


def _assert_check(table: str, name: str, expression: str) -> None:
    actual = op.get_bind().scalar(
        sa.text(
            "SELECT pg_get_expr(conbin, conrelid) FROM pg_constraint "
            "WHERE conrelid = to_regclass(:table) AND conname = :name "
            "AND contype = 'c' AND NOT connoinherit"
        ),
        {"table": table, "name": name},
    )
    if actual is None or " ".join(actual.split()) != " ".join(expression.split()):
        _refuse(f"{table}.{name} has an unexpected check definition")


def _fk_shape(constraint: dict) -> tuple:
    return (
        tuple(constraint["constrained_columns"]),
        constraint["referred_schema"],
        constraint["referred_table"],
        tuple(constraint["referred_columns"]),
        constraint["options"].get("ondelete"),
        bool(constraint["options"].get("deferrable", False)),
    )


def _assert_finished_schema() -> None:
    """Accept a validation retry only after checking every committed feature object."""
    inspector = sa.inspect(op.get_bind())
    columns = {
        item["name"]: (
            str(item["type"].compile(dialect=postgresql.dialect())),
            item["nullable"],
            item["default"],
        )
        for item in inspector.get_columns("accepted_queued_messages")
    }
    expected_columns = dict.fromkeys(
        ("id", "organization_id", "conversation_id", "requester_id", "client_queue_id", "agent_id"),
        ("UUID", False, None),
    )
    expected_columns.update(
        {
            "payload": ("JSONB", False, None),
            "payload_hash": ("VARCHAR(64)", False, None),
            "state": ("VARCHAR(16)", False, None),
            "message_id": ("UUID", True, None),
            "steering_run_id": ("UUID", True, None),
            "created_at": ("TIMESTAMP WITH TIME ZONE", False, "now()"),
            "updated_at": ("TIMESTAMP WITH TIME ZONE", True, None),
        }
    )
    if columns != expected_columns:
        _refuse("accepted_queued_messages has an unexpected column definition")
    if inspector.get_pk_constraint("accepted_queued_messages")["constrained_columns"] != ["id"]:
        _refuse("accepted_queued_messages has an unexpected primary key")
    uniques = {
        item["name"]: tuple(item["column_names"])
        for item in inspector.get_unique_constraints("accepted_queued_messages")
    }
    if uniques != {
        "uq_accepted_queue_org_id": ("organization_id", "id"),
        "uq_accepted_queue_client_key": (
            "organization_id",
            "requester_id",
            "conversation_id",
            "client_queue_id",
        ),
    }:
        _refuse("accepted_queued_messages has unexpected uniqueness")
    expected_fks = {
        "fk_accepted_queued_messages_organization_id_organizations": (
            ("organization_id",),
            None,
            "organizations",
            ("id",),
            "CASCADE",
            False,
        ),
        "fk_accepted_queue_conversation": (
            ("organization_id", "conversation_id"),
            None,
            "conversations",
            ("organization_id", "id"),
            "CASCADE",
            False,
        ),
        "fk_accepted_queued_messages_requester_id_users": (
            ("requester_id",),
            None,
            "users",
            ("id",),
            "CASCADE",
            False,
        ),
        "fk_accepted_queued_messages_agent_id_agents": (
            ("agent_id",),
            None,
            "agents",
            ("id",),
            "CASCADE",
            False,
        ),
        "fk_accepted_queued_messages_message_id_messages": (
            ("message_id",),
            None,
            "messages",
            ("id",),
            "SET NULL",
            False,
        ),
        "accepted_queued_messages_steering_run_id_fkey": (
            ("steering_run_id",),
            None,
            "agent_runs",
            ("id",),
            "SET NULL",
            False,
        ),
    }
    actual_fks = {
        item["name"]: _fk_shape(item)
        for item in inspector.get_foreign_keys("accepted_queued_messages")
    }
    if actual_fks != expected_fks:
        _refuse("accepted_queued_messages has unexpected foreign keys")
    indexes = {
        item["name"]: (tuple(item["column_names"]), bool(item["unique"]))
        for item in inspector.get_indexes("accepted_queued_messages")
        if not item.get("duplicates_constraint")
    }
    if indexes != {
        "ix_accepted_queue_pending": (
            ("organization_id", "conversation_id", "state", "created_at"),
            False,
        ),
        "ix_accepted_queue_requester": (("organization_id", "requester_id", "created_at"), False),
    }:
        _refuse("accepted_queued_messages has unexpected indexes")
    receipt_checks = {
        item["name"] for item in inspector.get_check_constraints("accepted_queued_messages")
    }
    if receipt_checks != {name for _table, name, _expression in _RECEIPT_CHECKS}:
        _refuse("accepted_queued_messages has unexpected check constraints")
    for table, name, expression in (*_RECEIPT_CHECKS, *_CHECKS):
        _assert_check(table, name, expression)
    for table, column in _QUEUE_COLUMNS:
        _ensure_column(table, column, add=False)
    for table, column, name in _QUEUE_UNIQUE:
        if _index_state(table, column, name) != (True, True, True):
            _refuse(f"{name} is not the expected attached unique index")
    for table, column, name, ondelete in _QUEUE_FKS:
        matches = [item for item in inspector.get_foreign_keys(table) if item["name"] == name]
        if len(matches) != 1 or _fk_shape(matches[0]) != (
            (column,),
            None,
            "accepted_queued_messages",
            ("id",),
            ondelete,
            False,
        ):
            _refuse(f"{table}.{name} is not the expected receipt foreign key")
    task_columns = {item["name"]: item for item in inspector.get_columns("conversation_tasks")}
    if not all(task_columns[name]["nullable"] for name in ("source_run_id", "tool_call_id")):
        _refuse("queue task provenance has unexpected nullability")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    if sa.inspect(op.get_bind()).has_table("accepted_queued_messages"):
        _assert_finished_schema()
    else:
        for table, column, name in _QUEUE_UNIQUE:
            if _index_build_running(table):
                _refuse(f"an index build on {table} is still running")
            state = _index_state(table, column, name)
            if state is not None and (not state[0] or state[2]):
                _refuse(f"{name} is not the expected standalone index on {table}")
        for table, column in _QUEUE_COLUMNS:
            _ensure_column(table, column, add=True)
        with _autocommit_ddl():
            for table, column, name in _QUEUE_UNIQUE:
                _ensure_index(table, column, name)
        op.execute("SET LOCAL lock_timeout = '5s'")
        _create_receipt_table()
        for table, _column, name in _QUEUE_UNIQUE:
            op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE USING INDEX {name}")
        op.alter_column("conversation_tasks", "source_run_id", nullable=True)
        op.alter_column("conversation_tasks", "tool_call_id", nullable=True)
        for table, column, name, ondelete in _QUEUE_FKS:
            op.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) "
                f"REFERENCES accepted_queued_messages (id) ON DELETE {ondelete} NOT VALID"
            )
        for table, name, expression in _CHECKS:
            op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
    with _autocommit_ddl():
        for table, _column, name, _ondelete in _QUEUE_FKS:
            op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")
        for table, name, _expression in _CHECKS:
            op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def _create_receipt_table() -> None:
    op.create_table(
        "accepted_queued_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_queue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("steering_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_accepted_queued_messages_organization_id_organizations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_accepted_queue_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            name="fk_accepted_queued_messages_requester_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name="fk_accepted_queued_messages_agent_id_agents",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["messages.id"],
            name="fk_accepted_queued_messages_message_id_messages",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["steering_run_id"],
            ["agent_runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("accepted_queued_messages_pkey")),
        sa.UniqueConstraint("organization_id", "id", name="uq_accepted_queue_org_id"),
        sa.UniqueConstraint(
            "organization_id",
            "requester_id",
            "conversation_id",
            "client_queue_id",
            name="uq_accepted_queue_client_key",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'steering', 'steered', 'sent', 'task', 'cancelled')",
            name="ck_accepted_queue_state",
        ),
        sa.CheckConstraint("char_length(payload_hash) = 64", name="ck_accepted_queue_payload_hash"),
    )
    op.create_index(
        "ix_accepted_queue_pending",
        "accepted_queued_messages",
        ["organization_id", "conversation_id", "state", "created_at"],
    )
    op.create_index(
        "ix_accepted_queue_requester",
        "accepted_queued_messages",
        ["organization_id", "requester_id", "created_at"],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("LOCK TABLE accepted_queued_messages IN ACCESS EXCLUSIVE MODE")
    has_data = op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM accepted_queued_messages)")
    )
    if has_data:
        raise RuntimeError("Cannot discard retained accepted queue receipts during downgrade")

    op.drop_constraint("ck_conversation_task_provenance", "conversation_tasks", type_="check")
    op.drop_constraint("uq_conversation_task_queue_receipt", "conversation_tasks", type_="unique")
    op.drop_constraint(
        "fk_conversation_task_queue_receipt", "conversation_tasks", type_="foreignkey"
    )
    op.drop_column("conversation_tasks", "queue_receipt_id")
    op.alter_column("conversation_tasks", "tool_call_id", nullable=False)
    op.alter_column("conversation_tasks", "source_run_id", nullable=False)

    op.drop_constraint("uq_agent_run_accepted_queue", "agent_runs", type_="unique")
    op.drop_constraint("fk_agent_run_accepted_queue", "agent_runs", type_="foreignkey")
    op.drop_column("agent_runs", "accepted_queue_id")

    op.drop_constraint("uq_message_accepted_queue", "messages", type_="unique")
    op.drop_constraint("fk_message_accepted_queue", "messages", type_="foreignkey")
    op.drop_column("messages", "accepted_queue_id")

    op.drop_constraint("ck_chat_file_message_or_queue", "chat_files", type_="check")
    op.drop_constraint("fk_chat_files_queue_receipt", "chat_files", type_="foreignkey")
    op.drop_column("chat_files", "queue_receipt_id")

    op.drop_index("ix_accepted_queue_requester", table_name="accepted_queued_messages")
    op.drop_index("ix_accepted_queue_pending", table_name="accepted_queued_messages")
    op.drop_table("accepted_queued_messages")
