"""Join the proactivity and Discord histories and retain every channel surface.

Both branches widened the same exposure check. Their final union is declared
again after both heads, so a fresh upgrade cannot leave whichever check ran last.
"""

from alembic import op

revision: str = "0282_merge_proactivity_main"
down_revision: tuple[str, str] = (
    "0281_secret_auth_generation",
    "0256_discord_role_mappings",
)
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.drop_constraint("ck_exposure_surface", "agent_exposures", type_="check")
    op.create_check_constraint(
        "ck_exposure_surface",
        "agent_exposures",
        "surface IN ('slack', 'telegram', 'mattermost', 'teams', 'discord', 'sms', 'email', 'imessage')",
    )


def downgrade() -> None:
    # Both branch heads remain installed and still own all these surface values.
    pass
