"""Index the skill tables' foreign keys that a delete reaches.

Deleting a skill, a fork, a version, an agent, a dataset, a check or an analysis
cascades through these keys, or sets them to null. Unindexed, each such delete scans
the whole table the key sits in, once per row it removes, while it holds its locks:

- `spec_proposal_batches.skill_id`, `fork_id` and `request_id`;
- `skill_improvement_runs.fork_id`, `source_fork_id`, `analysis_request_id` and
  `best_iteration_id`;
- `skill_improvement_iterations.skill_check_id`, `batch_id` and `authoring_request_id`;
- `skill_checks.base_version_id`, `fork_id`, `applied_version_id` and `proposal_id`;
- `skill_check_agents.agent_id` and `dataset_id`, which the composite index on the
  organization and agent cannot serve alone;
- `skill_proposals.authoring_request_id`, `skill_forks.created_for_agent_id` and
  `datasets.skill_id`.

**Downgrade** drops the indexes.

Revision ID: 0311_skill_fk_indexes
Revises: 0310_skill_check_stage_counts
Create Date: 2026-11-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0311_skill_fk_indexes"
down_revision: str | Sequence[str] | None = "0310_skill_check_stage_counts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(op.f("datasets_skill_id_idx"), "datasets", ["skill_id"], unique=False)
    op.create_index(
        "ix_skill_check_agents_agent_id", "skill_check_agents", ["agent_id"], unique=False
    )
    op.create_index(
        "ix_skill_check_agents_dataset", "skill_check_agents", ["dataset_id"], unique=False
    )
    op.create_index(
        "ix_skill_checks_applied_version", "skill_checks", ["applied_version_id"], unique=False
    )
    op.create_index(
        "ix_skill_checks_base_version", "skill_checks", ["base_version_id"], unique=False
    )
    op.create_index("ix_skill_checks_fork", "skill_checks", ["fork_id"], unique=False)
    op.create_index("ix_skill_checks_proposal", "skill_checks", ["proposal_id"], unique=False)
    op.create_index(
        op.f("skill_forks_created_for_agent_id_idx"),
        "skill_forks",
        ["created_for_agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_improvement_iterations_authoring_request_id_idx"),
        "skill_improvement_iterations",
        ["authoring_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_improvement_iterations_batch_id_idx"),
        "skill_improvement_iterations",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_improvement_iterations_skill_check_id_idx"),
        "skill_improvement_iterations",
        ["skill_check_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_improvement_runs_analysis_request_id_idx"),
        "skill_improvement_runs",
        ["analysis_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_improvement_runs_best_iteration_id_idx"),
        "skill_improvement_runs",
        ["best_iteration_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_improvement_runs_fork_id_idx"),
        "skill_improvement_runs",
        ["fork_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_improvement_runs_source_fork_id_idx"),
        "skill_improvement_runs",
        ["source_fork_id"],
        unique=False,
    )
    op.create_index(
        op.f("skill_proposals_authoring_request_id_idx"),
        "skill_proposals",
        ["authoring_request_id"],
        unique=False,
    )
    op.create_index(
        op.f("spec_proposal_batches_fork_id_idx"),
        "spec_proposal_batches",
        ["fork_id"],
        unique=False,
    )
    op.create_index(
        op.f("spec_proposal_batches_request_id_idx"),
        "spec_proposal_batches",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        op.f("spec_proposal_batches_skill_id_idx"),
        "spec_proposal_batches",
        ["skill_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("spec_proposal_batches_skill_id_idx"), table_name="spec_proposal_batches")
    op.drop_index(op.f("spec_proposal_batches_request_id_idx"), table_name="spec_proposal_batches")
    op.drop_index(op.f("spec_proposal_batches_fork_id_idx"), table_name="spec_proposal_batches")
    op.drop_index(op.f("skill_proposals_authoring_request_id_idx"), table_name="skill_proposals")
    op.drop_index(
        op.f("skill_improvement_runs_source_fork_id_idx"), table_name="skill_improvement_runs"
    )
    op.drop_index(op.f("skill_improvement_runs_fork_id_idx"), table_name="skill_improvement_runs")
    op.drop_index(
        op.f("skill_improvement_runs_best_iteration_id_idx"), table_name="skill_improvement_runs"
    )
    op.drop_index(
        op.f("skill_improvement_runs_analysis_request_id_idx"), table_name="skill_improvement_runs"
    )
    op.drop_index(
        op.f("skill_improvement_iterations_skill_check_id_idx"),
        table_name="skill_improvement_iterations",
    )
    op.drop_index(
        op.f("skill_improvement_iterations_batch_id_idx"), table_name="skill_improvement_iterations"
    )
    op.drop_index(
        op.f("skill_improvement_iterations_authoring_request_id_idx"),
        table_name="skill_improvement_iterations",
    )
    op.drop_index(op.f("skill_forks_created_for_agent_id_idx"), table_name="skill_forks")
    op.drop_index("ix_skill_checks_proposal", table_name="skill_checks")
    op.drop_index("ix_skill_checks_fork", table_name="skill_checks")
    op.drop_index("ix_skill_checks_base_version", table_name="skill_checks")
    op.drop_index("ix_skill_checks_applied_version", table_name="skill_checks")
    op.drop_index("ix_skill_check_agents_dataset", table_name="skill_check_agents")
    op.drop_index("ix_skill_check_agents_agent_id", table_name="skill_check_agents")
    op.drop_index(op.f("datasets_skill_id_idx"), table_name="datasets")
