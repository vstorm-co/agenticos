"""Let an existing agent step wait durably for its user's answer.

Question waits extend the allowed status and wait-reason vocabulary. A nullable
child link on each attempt preserves ownership and cost accounting after a step
is cancelled. Existing approval-continuation segments are backfilled from the
step's current child. Downgrade moves question waits to needs_attention and
removes accepted-answer keys older runner schemas cannot read, retaining messages.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0298_workflow_question_wait"
down_revision: str = "0297_workflow_chat_source"
branch_labels: None = None
depends_on: None = None


def _constraints(*, questions: bool) -> None:
    status = "'queued', 'running', 'waiting_approval', 'waiting_retry', "
    status += "'needs_attention', 'budget_exceeded', 'cancelled', 'failed', 'succeeded'"
    reasons = "'approval', 'external_event', 'retry_backoff', 'timer'"
    if questions:
        status += ", 'waiting_for_user'"
        reasons += ", 'question'"
    for table, name, condition in (
        ("workflow_runs", "ck_workflow_run_status", f"status IN ({status})"),
        (
            "workflow_runs",
            "ck_workflow_run_paused_reason",
            f"paused_reason IS NULL OR paused_reason IN ({reasons})",
        ),
        (
            "node_runs",
            "ck_node_run_waiting_reason",
            f"waiting_reason IS NULL OR waiting_reason IN ({reasons})",
        ),
    ):
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, condition)


def upgrade() -> None:
    op.add_column("node_attempts", sa.Column("agent_run_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "node_attempts_agent_run_id_fkey",
        "node_attempts",
        "agent_runs",
        ["agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("node_attempts_agent_run_id_idx", "node_attempts", ["agent_run_id"])
    # Existing approval continuations also keep the same child across waits.
    # A failed/non-waiting attempt is the boundary of a previous child.
    op.execute("""
        UPDATE node_attempts AS attempt
        SET agent_run_id = node.waiting_agent_run_id
        FROM node_runs AS node
        WHERE attempt.node_run_id = node.id
          AND node.waiting_agent_run_id IS NOT NULL
          AND attempt.attempt_no > COALESCE((
              SELECT MAX(previous.attempt_no) FROM node_attempts AS previous
              WHERE previous.node_run_id = node.id
                AND previous.status <> 'in_flight'
                AND (previous.status <> 'completed'
                     OR previous.result->>'status' IS DISTINCT FROM 'waiting'
                     OR previous.result->>'reason' NOT IN ('approval', 'question'))
          ), 0)
    """)
    _constraints(questions=True)


def downgrade() -> None:
    # Older code can expose these waits as needing attention, without dropping
    # the saved agent conversation or silently running the pending tool.
    op.execute(
        "UPDATE workflow_runs SET status = 'needs_attention', paused_reason = NULL WHERE status = 'waiting_for_user'"
    )
    op.execute(
        "UPDATE node_runs SET status = 'needs_attention', waiting_reason = NULL WHERE waiting_reason = 'question'"
    )
    op.execute("UPDATE workflow_runs SET paused_reason = NULL WHERE paused_reason = 'question'")
    op.execute(
        "UPDATE agent_runs SET paused_state = paused_state - 'question_results' "
        "WHERE paused_state ? 'question_results'"
    )
    _constraints(questions=False)
    op.drop_index("node_attempts_agent_run_id_idx", table_name="node_attempts")
    op.drop_constraint("node_attempts_agent_run_id_fkey", "node_attempts", type_="foreignkey")
    op.drop_column("node_attempts", "agent_run_id")
