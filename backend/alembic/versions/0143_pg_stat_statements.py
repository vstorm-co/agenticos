"""Record what each statement costs, where the database allows it (#2228).

Until this, production had no `pg_stat_statements`: a slow query on the
2026-10-18 slowdown could only be found by reading container logs. The extension
is the standard answer and ships with every Postgres build, pgvector's included.

It is optional, and this revision treats it so. Creating it needs a role allowed
to create untrusted extensions, and a managed database may not offer the library
at all. Neither is a reason to stop a deployment's schema from upgrading, so both
refusals are reported as a notice and the chain goes on. `doctor`'s
`query statistics` line says whether it is actually recording - which also
needs `shared_preload_libraries=pg_stat_statements` at server start, set in
`docker-compose-prod.yml`.

The downgrade leaves the extension where it is: it holds no application data,
and an operator may have created it before this revision existed, so dropping
it on the way down could remove something this chain never owned.

Revision ID: 0143_pg_stat_statements
Revises: 0142_message_reply_to
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0143_pg_stat_statements"
down_revision: str | None = "0142_message_reply_to"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
        EXCEPTION
            WHEN insufficient_privilege OR undefined_file OR feature_not_supported THEN
                RAISE NOTICE 'pg_stat_statements not created: %', SQLERRM;
        END
        $$;
        """
    )


def downgrade() -> None:
    pass
