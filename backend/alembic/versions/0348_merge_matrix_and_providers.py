"""Join main's Matrix channel and this release's provider migrations.

`0345_matrix_channel` and `0347_chatgpt_registrations` were written in parallel
from the same `0344_user_appearance`. Neither touches the other's tables, so
either order upgrades to the same schema.
"""

revision: str = "0348_merge_matrix_and_providers"
down_revision: tuple[str, str] = ("0345_matrix_channel", "0347_chatgpt_registrations")
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
