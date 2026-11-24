"""Join the T3 OpenBot credential chain with the v1.85.0 core migration head.

Both lines branch from the v1.76.1 checkpoint and touch different tables. This
revision adds no schema changes; it keeps both upgrade paths reachable without
renumbering an applied revision.
"""

revision: str = "0346_merge_t3_v1850"
down_revision: tuple[str, str] = (
    "0342_criterion_verdicts",
    "0345_credential_continuations",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
