"""The daily failure-ledger digest.

Once a day, per organization: mine the last 7 days for new failure
patterns and snapshot each untracked one into a DRAFT ledger entry, then
mail one digest to the deployment's configured recipient - one email per
organization that has anything new, none at all when there is nothing.

The entries are drafts, never open: a draft is a pattern the mining
found, not one a curator accepted, and opening it would put an
unreviewed rule on the path to an agent's instructions. A curator
accepts or dismisses each one in the console.

The recipient is configuration, not a default: `FAILURE_LEARNING_DIGEST_RECIPIENT`
is empty until somebody chooses an address, and while it is empty this job
does nothing at all - it creates no draft entries and sends no mail. One
address for the whole deployment, so it sees every organization's digest
and must be an operator address, not a member's.

A missed day is recovered by the next: the mining window is 7 days and a
pattern stays untracked until a draft exists for it, so a tick lost to a
deploy or an outage is picked up by the following day's run - which is
why this job takes one attempt, like the sweeps, rather than three like
the weekly and monthly reports.
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AlreadyExistsError
from app.core.permissions import AuthContext
from app.db.session import get_db_context
from app.repositories import agent_run as agent_run_repo
from app.repositories import organization as organization_repo
from app.schemas.failure_learning import FailurePattern, LedgerEntryCreate, LedgerScope
from app.services.email.service import EmailKey, get_email_service
from app.services.failure_learning import FailureLearningService
from app.worker.jobs import Tick

logger = logging.getLogger(__name__)


def _scope_label(pattern: FailurePattern) -> str:
    """Where the pattern lives, for a human reading the digest."""
    if pattern.agent_name is not None:
        return pattern.agent_name
    if pattern.agent_id is None:
        return f"model {pattern.model}" if pattern.model else "all models"
    return "unknown agent"


def _entry_title(pattern: FailurePattern) -> str:
    return f"{pattern.error_class} ({pattern.status})"


def _entry_summary(pattern: FailurePattern) -> str:
    """What the curator sees on the draft: the count and the window."""
    first = pattern.first_seen.date().isoformat() if pattern.first_seen else "unknown"
    last = pattern.last_seen.date().isoformat() if pattern.last_seen else "unknown"
    return (
        f"{_scope_label(pattern)}: {pattern.count} runs in the last 7 days, "
        f"first seen {first}, last seen {last}."
    )


async def _snapshot_new_patterns(
    db: AsyncSession, service: FailureLearningService, organization_id: UUID
) -> list[FailurePattern]:
    """Mine one organization's patterns and draft the untracked ones.

    A model-scoped pattern has no agent of its own, so it is anchored on
    the agent of its first sample run - the anchor only decides which
    agent's ledger the entry is created through; the entry itself stays
    model-scoped. A pattern with no sample run to anchor on is skipped
    rather than guessed at.
    """
    ctx = AuthContext(user_id=None, organization_id=organization_id, role="owner")
    mined = await service.list_org_patterns(ctx)
    created: list[FailurePattern] = []
    for pattern in mined.items:
        if pattern.already_tracked:
            continue
        scope: LedgerScope
        model: str | None
        if pattern.agent_id is not None:
            anchor_id, scope, model = pattern.agent_id, "agent", None
        else:
            anchor_id = await _anchor_agent(db, pattern, organization_id)
            if anchor_id is None:
                logger.warning(
                    "failure_ledger_digest_unanchored_pattern",
                    extra={"pattern_key": pattern.pattern_key},
                )
                continue
            scope, model = "model", pattern.model
        try:
            await service.create_ledger(
                ctx,
                anchor_id,
                LedgerEntryCreate(
                    scope=scope,
                    model=model,
                    pattern_key=pattern.pattern_key,
                    title=_entry_title(pattern),
                    summary=_entry_summary(pattern),
                    evidence={
                        "count": pattern.count,
                        "error_class": pattern.error_class,
                        "sample_run_ids": [str(run_id) for run_id in pattern.sample_run_ids],
                        "first_seen": pattern.first_seen.isoformat()
                        if pattern.first_seen
                        else None,
                        "last_seen": pattern.last_seen.isoformat() if pattern.last_seen else None,
                    },
                ),
            )
        except AlreadyExistsError:
            # Mined untracked, drafted since: the one-open-entry guard is
            # the second opinion, and the pattern is tracked now either way.
            continue
        created.append(pattern)
    return created


async def _anchor_agent(
    db: AsyncSession, pattern: FailurePattern, organization_id: UUID
) -> UUID | None:
    """The agent of a model pattern's first sample run, or None."""
    for run_id in pattern.sample_run_ids:
        run = await agent_run_repo.get_run(db, run_id, organization_id=organization_id)
        if run is not None:
            return run.agent_id
    return None


async def failure_ledger_digest(tick: Tick) -> dict[str, int | bool]:
    """Snapshot new patterns into draft entries and mail one digest per org.

    `tick` is unused beyond the schedule: the mining window is always the
    last 7 days from now, so a retried occurrence mines the same window
    and the already-tracked check plus the one-open-entry guard keep it
    from drafting twice.
    """
    recipient = settings.FAILURE_LEARNING_DIGEST_RECIPIENT
    if not recipient:
        logger.info("failure_ledger_digest_skipped_no_recipient_configured")
        return {
            "recipient_configured": False,
            "organizations": 0,
            "entries_created": 0,
            "digests_sent": 0,
        }
    async with get_db_context() as db:
        organizations = await organization_repo.list_all(db)
        service = FailureLearningService(db)
        created_total = sent_total = 0
        for organization in organizations:
            # One organization's failure must not stop the rest of the
            # estate from being digested.
            try:
                created = await _snapshot_new_patterns(db, service, organization.id)
                created_total += len(created)
                if not created:
                    continue
                summary = "\n".join(
                    f"{_scope_label(pattern)} - {_entry_title(pattern)}: {pattern.count} runs"
                    for pattern in created
                )
                result = await get_email_service().send(
                    key=EmailKey.FAILURE_LEARNING_DIGEST,
                    to=recipient,
                    context={"org_name": organization.name, "summary": summary},
                )
                if result.accepted:
                    sent_total += 1
                else:
                    logger.warning(
                        "failure_ledger_digest_not_accepted",
                        extra={
                            "organization_id": str(organization.id),
                            "error": result.error,
                        },
                    )
            except Exception:
                logger.exception(
                    "failure_ledger_digest_failed",
                    extra={"organization_id": str(organization.id)},
                )

    counts = {
        "recipient_configured": True,
        "organizations": len(organizations),
        "entries_created": created_total,
        "digests_sent": sent_total,
    }
    logger.info("failure_ledger_digest: %s", counts)
    return counts
