"""Add an agent audience to existing managed Virtual Table task boards."""

from alembic import op

revision: str = "0328_agent_task_boards"
down_revision: str = "0327_decision_model_api"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_constraint("ck_task_board_scope", "task_boards", type_="check")
    op.create_check_constraint(
        "ck_task_board_scope",
        "task_boards",
        "scope_kind IN ('private', 'agent', 'project', 'group', 'organization')",
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM task_boards WHERE scope_kind = 'agent') "
        "THEN RAISE EXCEPTION 'Remove agent task boards before downgrading'; END IF; END $$"
    )
    op.drop_constraint("ck_task_board_scope", "task_boards", type_="check")
    op.create_check_constraint(
        "ck_task_board_scope",
        "task_boards",
        "scope_kind IN ('private', 'project', 'group', 'organization')",
    )
