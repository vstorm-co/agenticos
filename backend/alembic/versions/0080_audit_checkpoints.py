"""A tamper-resistant high-water mark for each audit chain.

The hash chain in `0079_audit_hash_chain` catches an entry that was edited,
reordered, inserted or interior-deleted, but not the two deletions that leave the
survivors internally consistent: the newest entries dropped from a chain, and a
whole chain deleted. `agenticos cmd audit-verify` cannot tell a truncated chain
from a short one without a trusted record of how far each chain has reached, so
this adds one: `app_admin_audit_checkpoints`, one row per organization (and one
for the deployment-wide, null-organization chain).

`record_audit` advances a chain's checkpoint under the same per-organization lock
it appends the entry under, so the checkpoint never lags or races the chain. A
`BEFORE UPDATE OR DELETE` trigger refuses a row that moves backwards or is deleted.

**What that trigger is and is not.** It closes the ordinary write path: an app
admin acting through the product, and a bug in this codebase, cannot rewind a
checkpoint, which is what makes truncation detectable in the threat model the audit
trail is written against. It is not a control against anybody holding the
database's own credentials. Alembic and the runtime connect as the same
`POSTGRES_USER`, so that role owns this table: it can `DROP TRIGGER`, and a
`TRUNCATE` removes every row without firing a row-level `DELETE` trigger at all.
A superuser can do both and more. Anyone with those credentials can therefore
remove the checkpoints and then truncate the chains, and `audit-verify` sees a
short chain with nothing to compare it against.

Closing that is not a trigger's job - it needs a copy of the high-water mark kept
where this database's roles cannot reach it, an append-only or object-locked store
outside it. That is the next step on #1648, and `docs/governance.md` states the
boundary rather than leaving a reader to infer it.

Backfilled from the existing chains so a deployment that already has audit history
starts with an accurate high-water mark rather than a floor of zero (#1648).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "0080_audit_checkpoints"
down_revision: str | Sequence[str] | None = "0079_audit_hash_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GUARD_FUNCTION = """
CREATE FUNCTION app_admin_audit_checkpoint_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'app_admin_audit_checkpoints is append-only (#1648)';
    END IF;
    IF NEW.max_seq < OLD.max_seq OR NEW.entry_count < OLD.entry_count THEN
        RAISE EXCEPTION 'app_admin_audit_checkpoints may only advance (#1648)';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Head hash joined to the per-organization maximum, `IS NOT DISTINCT FROM` so the
# null-organization (deployment-wide) chain groups as one rather than dropping out.
# `SHARE` blocks `INSERT` while allowing reads, and is taken before the statement
# below rather than left to the insert's own snapshot. Without it a worker still
# running pre-0080 code can append an entry after the backfill reads the chain: that
# entry gets no checkpoint advance, and if it is later dropped as the tail before
# the next audited write, the survivors match the stale checkpoint exactly and
# verification calls the truncated chain intact. The lock is held to the end of the
# migration's transaction, which is the length of one `INSERT ... SELECT`.
_LOCK_CHAINS = "LOCK TABLE app_admin_audit_logs IN SHARE MODE"

_BACKFILL = """
INSERT INTO app_admin_audit_checkpoints
    (id, organization_id, max_seq, entry_count, head_entry_hash, created_at)
SELECT gen_random_uuid(), t.organization_id, t.max_seq, t.entry_count, head.entry_hash, now()
FROM (
    SELECT organization_id, MAX(seq) AS max_seq, COUNT(*) AS entry_count
    FROM app_admin_audit_logs
    GROUP BY organization_id
) AS t
JOIN app_admin_audit_logs AS head
    ON head.organization_id IS NOT DISTINCT FROM t.organization_id
    AND head.seq = t.max_seq;
"""


def upgrade() -> None:
    op.create_table(
        "app_admin_audit_checkpoints",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", UUID(as_uuid=True), nullable=True),
        sa.Column("max_seq", sa.BigInteger(), nullable=False),
        sa.Column("entry_count", sa.BigInteger(), nullable=False),
        sa.Column("head_entry_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="app_admin_audit_checkpoints_pkey"),
    )
    # NULLS NOT DISTINCT so the deployment-wide chain has exactly one checkpoint and
    # `record_audit`'s `ON CONFLICT (organization_id)` upsert can find it.
    op.execute(
        "ALTER TABLE app_admin_audit_checkpoints "
        "ADD CONSTRAINT app_admin_audit_checkpoints_organization_id_key "
        "UNIQUE NULLS NOT DISTINCT (organization_id)"
    )

    op.execute(_GUARD_FUNCTION)
    op.execute(
        "CREATE TRIGGER app_admin_audit_checkpoint_guard "
        "BEFORE UPDATE OR DELETE ON app_admin_audit_checkpoints "
        "FOR EACH ROW EXECUTE FUNCTION app_admin_audit_checkpoint_guard()"
    )

    op.execute(_LOCK_CHAINS)
    op.execute(_BACKFILL)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS app_admin_audit_checkpoint_guard ON app_admin_audit_checkpoints"
    )
    op.execute("DROP FUNCTION IF EXISTS app_admin_audit_checkpoint_guard()")
    op.drop_table("app_admin_audit_checkpoints")
