"""Reserve retained inputs, draft snapshots and Wait payloads with inline results.

Stop API and worker writers during this accounting backfill. No payloads or
recorded fees are removed; existing data can put an organization over quota.

Revision ID: 0224_workflow_input_bytes
Revises: 0223_workflow_result_bytes
"""

from alembic import op

revision: str = "0224_workflow_input_bytes"
down_revision: str | None = "0223_workflow_result_bytes"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE workflow_runs r SET inline_result_bytes = inline_result_bytes
            + coalesce(octet_length(r.input::text), 0)
            + coalesce(octet_length(r.draft_graph_snapshot::text), 0)
            + coalesce((SELECT sum(octet_length(n.resume_payload::text))
                FROM node_runs n WHERE n.workflow_run_id = r.id), 0)
    """)


def downgrade() -> None:
    # Reconstruct the earlier conservative result-only contract; subtracting
    # PostgreSQL text sizes from new compact reservations could undercount.
    op.execute("""
        UPDATE workflow_runs r SET inline_result_bytes =
            coalesce((SELECT sum(octet_length(a.result::text)) FROM node_attempts a
                JOIN node_runs n ON n.id = a.node_run_id WHERE n.workflow_run_id = r.id), 0)
            + coalesce(octet_length(r.output::text), 0)
            + coalesce(octet_length(r.webhook_response::text), 0)
            + coalesce(octet_length(r.error::text), 0)
    """)
