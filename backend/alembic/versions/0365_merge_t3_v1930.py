"""Join the T3 migration chain with the upstream v1.93.0 head.

T3's `0353_nav_pins`, `0355_magic_link_claims` and
`0356_trigger_webhook_receipts` branch from upstream's
`0349_personal_work_context`, while upstream continued to
`0364_merge_routine_and_kb` through its own 0346-0362 chain and the two
0363 branches. This revision adds no schema changes; it keeps both upgrade
paths reachable without renumbering an applied revision.
"""

revision: str = "0365_merge_t3_v1930"
down_revision: tuple[str, str] = (
    "0364_merge_routine_and_kb",
    "0356_trigger_webhook_receipts",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
