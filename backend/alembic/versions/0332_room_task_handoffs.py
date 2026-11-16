"""Pin room leads and retain reviewed handoffs to canonical Tasks.

Revision ID: 0332_room_task_handoffs
Revises: 0331_merge_core_accounts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0332_room_task_handoffs"
down_revision: str | Sequence[str] | None = "0331_merge_core_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "room_submissions",
        sa.Column("intent", sa.String(16), nullable=False, server_default="message"),
    )
    op.add_column(
        "room_submissions", sa.Column("lead_policy_revision", sa.Integer(), nullable=True)
    )
    op.create_unique_constraint(
        "uq_room_submission_scope", "room_submissions", ["organization_id", "conversation_id", "id"]
    )
    op.create_check_constraint(
        op.f("room_submissions_lead_intent_check"),
        "room_submissions",
        "(intent = 'message' AND lead_policy_revision IS NULL) OR "
        "(intent = 'ask_lead' AND lead_policy_revision IS NOT NULL "
        "AND lead_policy_revision >= 1 AND agent_id IS NOT NULL)",
    )
    op.create_table(
        "room_lead_policies",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("lead_agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("specialists", postgresql.JSONB(), nullable=False),
        sa.Column("max_items", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "organization_id", "conversation_id", name=op.f("room_lead_policies_pkey")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_room_lead_policy_conversation",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("revision >= 1", name=op.f("room_lead_policies_revision_check")),
        sa.CheckConstraint(
            "max_items BETWEEN 1 AND 3", name=op.f("room_lead_policies_max_items_check")
        ),
        sa.CheckConstraint(
            "(lead_agent_id IS NULL) = (lead_version_id IS NULL) AND (NOT enabled OR lead_agent_id IS NOT NULL)",
            name=op.f("room_lead_policies_lead_check"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(specialists) = 'array' AND jsonb_array_length(specialists) <= 12",
            name=op.f("room_lead_policies_specialists_check"),
        ),
    )
    op.create_table(
        "room_routing_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("submission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("thread_root_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("proposal_hash", sa.String(64), nullable=False),
        sa.Column("items", postgresql.JSONB(), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("decision_key", sa.String(128), nullable=True),
        sa.Column("decision_hash", sa.String(64), nullable=True),
        sa.Column("accepted_item_ids", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("room_routing_proposals_pkey")),
        sa.UniqueConstraint(
            "organization_id", "conversation_id", "id", name="uq_room_routing_proposal_scope"
        ),
        sa.UniqueConstraint("submission_id", name="uq_room_routing_proposal_submission"),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            name="fk_room_routing_proposal_conversation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id", "submission_id"],
            [
                "room_submissions.organization_id",
                "room_submissions.conversation_id",
                "room_submissions.id",
            ],
            name="fk_room_routing_proposal_submission",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "message_id"],
            ["messages.conversation_id", "messages.id"],
            name="fk_room_routing_proposal_message",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "thread_root_message_id"],
            ["messages.conversation_id", "messages.id"],
            name="fk_room_routing_proposal_thread",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            name=op.f("room_routing_proposals_requester_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_run_id"],
            ["agent_runs.id"],
            name=op.f("room_routing_proposals_lead_run_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "policy_revision >= 1 AND revision >= 1",
            name=op.f("room_routing_proposals_revision_check"),
        ),
        sa.CheckConstraint(
            "decision IN ('pending', 'accepted', 'discarded')",
            name=op.f("room_routing_proposals_decision_check"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(items) = 'array' AND jsonb_array_length(items) BETWEEN 1 AND 3",
            name=op.f("room_routing_proposals_items_check"),
        ),
        sa.CheckConstraint(
            "(decision = 'pending' AND decision_key IS NULL AND decision_hash IS NULL) OR (decision <> 'pending' AND decision_key IS NOT NULL AND decision_hash IS NOT NULL)",
            name=op.f("room_routing_proposals_decision_receipt_check"),
        ),
    )
    op.create_index(
        "room_routing_proposals_room_idx",
        "room_routing_proposals",
        ["organization_id", "conversation_id", "created_at"],
    )
    op.create_table(
        "room_task_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("proposal_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted_revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("provenance", postgresql.JSONB(), nullable=False),
        sa.Column("dispatch_trigger_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("room_task_links_pkey")),
        sa.UniqueConstraint("proposal_id", "proposal_item_id", name="uq_room_task_link_item"),
        sa.UniqueConstraint(
            "dispatch_trigger_id", name=op.f("room_task_links_dispatch_trigger_id_key")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "conversation_id", "proposal_id"],
            [
                "room_routing_proposals.organization_id",
                "room_routing_proposals.conversation_id",
                "room_routing_proposals.id",
            ],
            name="fk_room_task_link_proposal",
            ondelete="SET NULL (proposal_id)",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "table_id", "task_id"],
            [
                "virtual_table_records.organization_id",
                "virtual_table_records.table_id",
                "virtual_table_records.id",
            ],
            name="fk_room_task_link_task",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            name=op.f("room_task_links_requester_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dispatch_trigger_id"],
            ["agent_triggers.id"],
            name=op.f("room_task_links_dispatch_trigger_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "accepted_revision >= 1", name=op.f("room_task_links_accepted_revision_check")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(provenance) = 'object'", name=op.f("room_task_links_provenance_check")
        ),
    )
    op.create_index(
        "room_task_links_room_idx",
        "room_task_links",
        ["organization_id", "conversation_id", "created_at"],
    )


def downgrade() -> None:
    used = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM room_lead_policies) "
                "OR EXISTS (SELECT 1 FROM room_routing_proposals) "
                "OR EXISTS (SELECT 1 FROM room_task_links) "
                "OR EXISTS (SELECT 1 FROM room_submissions WHERE intent = 'ask_lead')"
            )
        )
        .scalar_one()
    )
    if used:
        raise RuntimeError("Cannot downgrade while room lead policy or handoff evidence exists")
    op.drop_table("room_task_links")
    op.drop_table("room_routing_proposals")
    op.drop_table("room_lead_policies")
    op.drop_constraint(
        op.f("room_submissions_lead_intent_check"), "room_submissions", type_="check"
    )
    op.drop_constraint("uq_room_submission_scope", "room_submissions", type_="unique")
    op.drop_column("room_submissions", "lead_policy_revision")
    op.drop_column("room_submissions", "intent")
