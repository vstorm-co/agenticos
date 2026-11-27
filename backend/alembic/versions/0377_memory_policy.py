"""Persist dated relations, workflow authority and Inbox shadow outcomes."""

import sqlalchemy as sa

from alembic import op

revision: str = "0377_memory_policy"
down_revision: str = "0376_memory_consolidation_cursor"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "memory_source_authorities",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("object_kind", sa.String(length=24), nullable=False),
        sa.Column("subject", sa.String(length=120), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("memory_source_authorities_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["workflows.id"],
            name=op.f("memory_source_authorities_workflow_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "organization_id", "object_kind", "subject", name=op.f("memory_source_authorities_pkey")
        ),
    )
    op.create_index(
        op.f("memory_source_authorities_workflow_id_idx"),
        "memory_source_authorities",
        ["workflow_id"],
        unique=False,
    )
    op.create_table(
        "memory_inbox_shadow_decisions",
        sa.Column("claim_id", sa.UUID(), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("revision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change", sa.String(length=16), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("baseline_notify", sa.Boolean(), nullable=False),
        sa.Column("recommendation", sa.String(length=16), nullable=False),
        sa.CheckConstraint(
            "recommendation IN ('notify', 'digest', 'review', 'ignore')",
            name=op.f("memory_inbox_shadow_decisions_recommendation_check"),
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["memory_claims.id"],
            name=op.f("memory_inbox_shadow_decisions_claim_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("memory_inbox_shadow_decisions_organization_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "claim_id",
            "rule_version",
            "policy_version",
            "revision_at",
            "change",
            name=op.f("memory_inbox_shadow_decisions_pkey"),
        ),
    )
    op.create_index(
        "ix_memory_inbox_shadow_org_rule",
        "memory_inbox_shadow_decisions",
        ["organization_id", "rule_version"],
        unique=False,
    )
    op.add_column("memory_claims", sa.Column("related_object_id", sa.UUID(), nullable=True))
    op.create_index(
        "ix_memory_claims_related_object",
        "memory_claims",
        ["related_object_id", "observed_at", "id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("memory_claims_related_object_id_fkey"),
        "memory_claims",
        "memory_objects",
        ["related_object_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("memory_claims_typed_relation_check"),
        "memory_claims",
        "related_object_id IS NULL OR (object_id IS NOT NULL AND object_id <> related_object_id "
        "AND subject IS NOT NULL AND subject IN ('relation_client', 'relation_responsible', 'relation_part_of'))",
    )
    op.add_column(
        "memory_inbox_rules", sa.Column("shadow_model_owner_id", sa.UUID(), nullable=True)
    )
    op.create_foreign_key(
        op.f("memory_inbox_rules_shadow_model_owner_id_fkey"),
        "memory_inbox_rules",
        "users",
        ["shadow_model_owner_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("memory_inbox_rules_shadow_model_owner_id_fkey"),
        "memory_inbox_rules",
        type_="foreignkey",
    )
    op.drop_column("memory_inbox_rules", "shadow_model_owner_id")
    op.drop_constraint(
        op.f("memory_claims_related_object_id_fkey"), "memory_claims", type_="foreignkey"
    )
    op.drop_constraint(op.f("memory_claims_typed_relation_check"), "memory_claims", type_="check")
    op.drop_index("ix_memory_claims_related_object", table_name="memory_claims")
    op.drop_column("memory_claims", "related_object_id")
    op.drop_index("ix_memory_inbox_shadow_org_rule", table_name="memory_inbox_shadow_decisions")
    op.drop_table("memory_inbox_shadow_decisions")
    op.drop_index(
        op.f("memory_source_authorities_workflow_id_idx"), table_name="memory_source_authorities"
    )
    op.drop_table("memory_source_authorities")
