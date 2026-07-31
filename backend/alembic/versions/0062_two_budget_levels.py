"""Two budget levels only - and a ledger for what ingestion embeds

Revision ID: 0062_two_budget_levels
Revises: 0061_kb_embedding_secret
Create Date: 2026-07-30

The platform's budget model is now exactly two ceilings: the agent's monthly
cap and the organization's. Everything else goes, and the spend the budgets
could not see gets a table.

`agent_exposures.max_per_run_usd` / `monthly_usd` are dropped. A per-binding
ceiling was a third budget level nobody asked to reason about: the agent's
spend is metered wherever it runs, and the organization's cap is the ceiling
on the bill. The `exposure_id` attribution on runs stays - "where did this run
come from" is still a question - but the index that existed solely for the
per-exposure monthly lookup goes with the lookup.

`budget.max_per_run_usd` is stripped from every stored spec - `agents.
draft_spec` and every `agent_versions.spec`. The spec model declares
`extra="forbid"`, so a key the model no longer knows does not deprecate, it
makes the row unreadable: one stale spec answers 500 for the whole listing.
Published versions are rewritten too, immutability notwithstanding, for the
same reason 0046 rewrote OCR codes - a version that cannot be loaded is not
history, it is a landmine.

`ingestion_spend` is new. Embedding a document happens in a worker, on
nobody's run, and that spend was recorded nowhere - an organization could
embed unbounded volume under an exhausted budget because the monthly total
only ever summed runs. One row per metering window (an upload, a sync);
`organization_id` is nullable because a local-directory sync run by an
operator has no tenant to bill, and SET NULL on the document because deleting
a document must not delete the record of what indexing it cost.

Down-migration restores the columns and the index but not the stripped
per-run values - they are gone, and inventing them would be a guess.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision = "0062_two_budget_levels"
down_revision = "0061_kb_embedding_secret"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_exposure_budget_positive", "agent_exposures", type_="check")
    op.drop_column("agent_exposures", "max_per_run_usd")
    op.drop_column("agent_exposures", "monthly_usd")
    op.drop_index("ix_agent_runs_exposure_started", table_name="agent_runs")

    # `#-` is a no-op on rows without the path, so no WHERE is needed for
    # correctness - the predicate just keeps the update off rows that would
    # not change.
    op.execute(
        """
        UPDATE agents
        SET draft_spec = draft_spec #- '{budget,max_per_run_usd}'
        WHERE draft_spec -> 'budget' ? 'max_per_run_usd'
        """
    )
    op.execute(
        """
        UPDATE agent_versions
        SET spec = spec #- '{budget,max_per_run_usd}'
        WHERE spec -> 'budget' ? 'max_per_run_usd'
        """
    )

    op.create_table(
        "ingestion_spend",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "rag_document_id",
            PG_UUID(as_uuid=True),
            sa.ForeignKey("rag_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("cost_is_partial", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The monthly lookup's shape: one organization, one window.
    op.create_index(
        "ix_ingestion_spend_org_created",
        "ingestion_spend",
        ["organization_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_spend_org_created", table_name="ingestion_spend")
    op.drop_table("ingestion_spend")

    op.create_index(
        "ix_agent_runs_exposure_started",
        "agent_runs",
        ["exposure_id", "started_at"],
    )
    op.add_column("agent_exposures", sa.Column("monthly_usd", sa.Numeric(12, 6), nullable=True))
    op.add_column("agent_exposures", sa.Column("max_per_run_usd", sa.Numeric(12, 6), nullable=True))
    op.create_check_constraint(
        "ck_exposure_budget_positive",
        "agent_exposures",
        "(max_per_run_usd IS NULL OR max_per_run_usd > 0) "
        "AND (monthly_usd IS NULL OR monthly_usd > 0)",
    )
