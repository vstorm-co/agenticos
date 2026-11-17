"""Join the WhatsApp chain and main's channel runtime and memory revisions.

Both histories may already be applied in existing deployments. Retain their
revision IDs and run both branches before exposing a single upgrade head.
"""

revision: str = "0339_merge_channel_runtime"
down_revision: tuple[str, str] = (
    "0338_merge_whatsapp_routines",
    "0336_run_memory_snapshot",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
