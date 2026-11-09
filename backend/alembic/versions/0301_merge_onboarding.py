"""Join released workflow/RAG upgrades with the guided-onboarding migrations.

Keep both applied histories intact: deployments may already hold either head.
The parent revisions own their respective tables and can upgrade in either order.
"""

revision: str = "0301_merge_onboarding"
down_revision: tuple[str, str] = ("0300_unfiled_writer_provenance", "0298_verified_mailbox")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
