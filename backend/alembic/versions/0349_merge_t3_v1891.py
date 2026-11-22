"""Join the T3 approvals head with the v1.89.1 core migration head.

T3 and upstream both branch from `0342_criterion_verdicts`. Released revisions
stay where they are, so a database already at `0348_approval_expired_notice` still
applies the upstream revisions it has not seen. This revision adds no schema.
"""

revision: str = "0349_merge_t3_v1891"
down_revision: tuple[str, str] = (
    "0348_approval_expired_notice",
    "0348_architect_generated_avatar",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
