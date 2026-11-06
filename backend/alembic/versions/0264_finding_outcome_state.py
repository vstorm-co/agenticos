"""Make each watch finding the Inbox projection of its shared outcome.

Preserve finding/case identifiers and old decisions. Nonurgent findings receive
cases too; historical decisions close obsolete pending deliveries rather than
recreating attention. Downgrade drops the link only: it cannot undo decisions
or recall deliveries already accepted by an external provider.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0264_finding_outcome_state"
down_revision: str | None = "0263_routine_notification_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inconsistent = op.get_bind().scalar(
        sa.text("""
        SELECT count(*) FROM suggestions s
        JOIN notifications n ON n.organization_id = s.organization_id
            AND n.recipient_user_id = s.user_id AND n.event_type = 'finding'
            AND n.occurrence_id = s.id::text
        JOIN outcomes o ON o.id = n.outcome_id
        WHERE s.kind = 'finding' AND (
            o.organization_id != s.organization_id OR o.user_id != s.user_id
            OR o.kind != 'finding' OR o.dedupe_key != 'finding:' || s.id::text
        )
    """)
    )
    inconsistent += op.get_bind().scalar(
        sa.text("""
        SELECT count(*) FROM suggestions s JOIN outcomes o
            ON o.organization_id = s.organization_id AND o.user_id = s.user_id
            AND o.dedupe_key = 'finding:' || s.id::text
        WHERE s.kind = 'finding' AND o.kind != 'finding'
        """)
    )
    if inconsistent:
        raise RuntimeError(
            "Existing finding outcomes have noncanonical scope or identity. Review them before upgrading; no case IDs were reassigned."
        )
    op.add_column("suggestions", sa.Column("outcome_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "suggestions_outcome_id_fkey",
        "suggestions",
        "outcomes",
        ["outcome_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("suggestions_outcome_id_idx", "suggestions", ["outcome_id"], unique=True)
    op.execute("""
        INSERT INTO outcomes (id, organization_id, user_id, kind, dedupe_key,
            summary, context_url, status, source_conversation_id, settled_at, settled_via)
        SELECT gen_random_uuid(), s.organization_id, s.user_id, 'finding',
            'finding:' || s.id::text, s.title, '/inbox?view=watches',
            CASE WHEN s.status = 'open' THEN 'open' ELSE 'resolved' END,
            c.id,
            CASE WHEN s.status = 'open' THEN NULL ELSE COALESCE(s.decided_at, now()) END,
            CASE WHEN s.status = 'open' THEN NULL ELSE 'inbox' END
        FROM suggestions s
        LEFT JOIN watches w ON w.id = s.watch_id
            AND w.organization_id = s.organization_id AND w.user_id = s.user_id
        LEFT JOIN conversations c ON c.id = w.source_conversation_id
            AND c.organization_id = s.organization_id AND c.user_id = s.user_id
        WHERE s.kind = 'finding'
        ON CONFLICT ON CONSTRAINT uq_outcome_person_key DO NOTHING
    """)
    op.execute("""
        UPDATE suggestions s SET outcome_id = o.id FROM outcomes o
        WHERE s.kind = 'finding' AND o.organization_id = s.organization_id
            AND o.user_id = s.user_id AND o.dedupe_key = 'finding:' || s.id::text
            AND o.kind = 'finding'
    """)
    op.execute("""
        UPDATE outcomes o SET status = 'resolved',
            settled_at = COALESCE(s.decided_at, now()), settled_via = 'inbox'
        FROM suggestions s WHERE s.outcome_id = o.id
            AND s.status IN ('accepted', 'dismissed')
            AND o.status IN ('open', 'acknowledged')
    """)
    op.execute("""
        UPDATE suggestions s SET
            status = CASE WHEN s.status != 'open' THEN s.status
                WHEN o.status = 'muted' THEN 'dismissed' ELSE 'accepted' END,
            decided_at = COALESCE(s.decided_at, o.settled_at, now())
        FROM outcomes o WHERE s.outcome_id = o.id AND o.status IN ('resolved', 'muted')
    """)
    op.execute("""
        UPDATE notifications n SET outcome_id = s.outcome_id
        FROM suggestions s WHERE n.event_type = 'finding'
            AND n.occurrence_id = s.id::text AND n.organization_id = s.organization_id
            AND n.recipient_user_id = s.user_id AND s.kind = 'finding'
    """)
    op.execute("""
        UPDATE notifications n SET read_at = COALESCE(n.read_at, now()),
            dismissed_at = CASE WHEN o.status IN ('resolved', 'muted')
                THEN COALESCE(n.dismissed_at, now()) ELSE n.dismissed_at END
        FROM outcomes o WHERE n.outcome_id = o.id AND o.kind = 'finding' AND o.status != 'open'
    """)
    op.execute("""
        UPDATE notification_deliveries d SET status = 'skipped', last_error = 'outcome settled',
            claimed_at = NULL, claimed_until = NULL
        FROM notifications n JOIN outcomes o ON o.id = n.outcome_id
        WHERE d.notification_id = n.id AND d.status = 'pending'
            AND o.kind = 'finding' AND o.status != 'open'
    """)


def downgrade() -> None:
    op.drop_index("suggestions_outcome_id_idx", "suggestions")
    op.drop_constraint("suggestions_outcome_id_fkey", "suggestions", type_="foreignkey")
    op.drop_column("suggestions", "outcome_id")
