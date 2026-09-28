"""Idempotency receipts: a retried write returns what the first one did.

A caller that names an operation key gets exactly-once effect. The key is scoped
to the organization, the principal and the operation, so two callers that pick
the same string never meet, and one caller using it for two kinds of write does
not collide. What ties a key to one request is `payload_hash`: reusing a key for a
different body is refused, because replaying the old answer to a new question is
the silent failure this exists to prevent.

Only successes are stored. A refused write (a stale revision, an invalid value)
leaves no receipt, so the caller corrects the request and retries with the same
key.
"""

import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.repositories import virtual_table_repo
from app.schemas.virtual_table import RecordRead
from app.services.virtual_tables.exceptions import IdempotencyKeyReuseError


class WriteOutcome(BaseModel):
    """What a create, update or upsert did, as stored on its receipt and replayed from it."""

    created: bool
    record: RecordRead
    """The record as the write left it."""


class DeleteOutcome(BaseModel):
    """What a delete did."""

    record_id: UUID


def payload_hash(payload: dict[str, Any]) -> str:
    """A stable digest of the request: same content, same hash, whatever the key order."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def run_once[Outcome: BaseModel](
    db: AsyncSession,
    ctx: AuthContext,
    *,
    operation: str,
    operation_key: str | None,
    payload: dict[str, Any],
    outcome_type: type[Outcome],
    action: Callable[[], Awaitable[Outcome]],
) -> tuple[Outcome, bool]:
    """Run `action` once per key, and say whether this call replayed a stored outcome.

    The action, the receipt and everything the action writes share one savepoint,
    so a failure anywhere leaves no receipt behind even if the caller keeps the
    session. Without a key the action simply runs.

    Raises:
        IdempotencyKeyReuseError: The key was used before with a different request.
    """
    async with db.begin_nested():
        if operation_key is None:
            return await action(), False
        digest = payload_hash(payload)
        claimed = await virtual_table_repo.claim_receipt(
            db,
            organization_id=ctx.organization_id,
            principal_id=ctx.subject_id,
            operation=operation,
            operation_key=operation_key,
            payload_hash=digest,
        )
        if claimed is None:
            stored = await virtual_table_repo.read_receipt(
                db,
                organization_id=ctx.organization_id,
                principal_id=ctx.subject_id,
                operation=operation,
                operation_key=operation_key,
            )
            if not secrets.compare_digest(stored.payload_hash, digest):
                raise IdempotencyKeyReuseError(operation=operation)
            return outcome_type.model_validate(stored.outcome), True
        outcome = await action()
        await virtual_table_repo.set_receipt_outcome(
            db, receipt=claimed, outcome=outcome.model_dump(mode="json")
        )
        return outcome, False
