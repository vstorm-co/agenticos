"""A model profile can name the endpoint it talks to

Revision ID: 0067_profile_endpoint
Revises: 0066_drop_users_role
Create Date: 2026-07-31

Three pieces of this feature already existed and nothing joined them:
`ProviderSpec.base_url_param` said which providers accept an endpoint,
`ModelProfileService._validate_base_url` checked one carefully, and
`model_resolver._build_provider` knew how to pass one to the SDK. The resolver in
between set `base_url=None` unconditionally, and `_validate_base_url` was called
from nowhere - so no deployment could point a profile at a gateway, a LiteLLM
proxy or an Ollama on its own network, and the `Custom URL` column in
`docs/models.md` described something that could not happen.

On the profile rather than on the secret: a secret says what authenticates, an
endpoint says where the request goes. The same key in front of a staging proxy and
a production one is two profiles and one secret; one endpoint with two keys is not
a case anybody has.

Nullable, with no backfill. An absent endpoint is exactly what every existing row
means - the provider's own public API - so there is nothing to migrate.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0067_profile_endpoint"
down_revision: str | None = "0066_drop_users_role"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("model_profiles", sa.Column("base_url", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("model_profiles", "base_url")
