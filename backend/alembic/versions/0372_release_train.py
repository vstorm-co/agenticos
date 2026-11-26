"""Join the independently reviewed release-train schema branches.

No schema or data changes occur here. Existing revision identities stay intact;
operators apply the complete train through one head after draining old workers.
"""

revision: str = "0372_release_train"
down_revision: tuple[str, ...] = (
    "0365_attempt_receipt_only",
    "0365_reusable_event_sources",
    "0365_routine_tool_settings",
    "0366_improvement_holdout_share",
    "0369_run_error_code",
    "0371_portable_document_snapshots",
    "0371_run_workspace_origins",
)
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
