"""Allow negotiated token prices to survive terminal accounting.

A valid million-token custom-priced call can exceed the six integer digits of
Numeric(12, 6). Widen monetary storage uniformly while retaining six fractional
places and the existing API values. Downgrade refuses out-of-range data through
PostgreSQL numeric validation rather than truncating or clamping costs.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0353_monetary_cost_capacity"
down_revision: str = "0352_model_profile_pricing"
branch_labels: None = None
depends_on: None = None

_COLUMNS = (
    ("agent_runs", "cost_usd"),
    ("authoring_requests", "cost_usd"),
    ("authoring_requests", "estimate_usd"),
    ("eval_run_cases", "cost_usd"),
    ("eval_runs", "estimate_usd"),
    ("eval_runs", "rerun_ceiling_usd"),
    ("eval_suites", "max_run_usd"),
    ("groups", "monthly_budget_usd"),
    ("improvement_iterations", "cost_usd"),
    ("improvement_runs", "archived_cost_usd"),
    ("improvement_runs", "budget_usd"),
    ("improvement_runs", "estimate_usd"),
    ("improvement_runs", "spent_usd"),
    ("ingestion_spend", "cost_usd"),
    ("messages", "cost_usd"),
    ("node_attempts", "cost"),
    ("node_attempts", "reserved_usd"),
    ("organizations", "monthly_budget_usd"),
    ("organizations", "proactive_limit_usd"),
    ("phone_calls", "estimated_cost_usd"),
    ("phone_calls", "price_per_minute_usd"),
    ("phone_endpoints", "daily_budget_usd"),
    ("phone_endpoints", "price_per_minute_usd"),
    ("purged_run_spend", "cost_usd"),
    ("skill_check_agents", "at_most_usd"),
    ("skill_check_agents", "expected_usd"),
    ("skill_checks", "at_most_usd"),
    ("skill_checks", "expected_usd"),
    ("skill_improvement_iterations", "cost_usd"),
    ("skill_improvement_runs", "budget_usd"),
    ("skill_improvement_runs", "estimate_usd"),
    ("system_agent_profiles", "monthly_budget_usd"),
    ("voice_calls", "cost_usd"),
    ("workflow_node_spend", "cost_usd"),
    ("workflow_runs", "budget_limit"),
    ("workflow_runs", "child_cost"),
    ("workflow_runs", "spent_cost"),
    ("workflow_versions", "budget_limit"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(table, column, existing_type=sa.Numeric(12, 6), type_=sa.Numeric(38, 6))


def downgrade() -> None:
    for table, column in reversed(_COLUMNS):
        op.alter_column(table, column, existing_type=sa.Numeric(38, 6), type_=sa.Numeric(12, 6))
