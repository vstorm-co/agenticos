"""Admit a bounded operation under existing workflow and vault authority."""

import hashlib
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext
from app.db.locks import LockScope, hold_subject
from app.db.models.workflow_media_operation import WorkflowMediaOperation
from app.db.models.workflow_run import NodeAttempt, WorkflowRun
from app.db.session import get_worker_db_context
from app.repositories import organization_repo
from app.repositories import workflow_media_operation as media_repo
from app.services import image_models, video_models
from app.services.organization_secret import OrganizationSecretService
from app.services.spend import organization_monthly_spend
from app.services.workflow_execution import budget, context
from app.services.workflow_media import _authority
from app.services.workflow_media._errors import MediaOperationError
from app.services.workflow_media._journal import collectable
from app.services.workflow_media._pricing import snapshot
from app.workflows import files
from app.workflows.nodes._media_config import (
    ImageGenerateConfig,
    MediaGenerateInput,
    VideoGenerateConfig,
)

type MediaConfig = ImageGenerateConfig | VideoGenerateConfig


def kind_of(config: MediaConfig) -> str:
    return "image" if isinstance(config, ImageGenerateConfig) else "video"


def request_hash(
    config: MediaConfig, supplied: MediaGenerateInput, reference_sha256: str | None
) -> str:
    """Persist no prompt or raw provider body, only the immutable request identity."""
    encoded = json.dumps(
        {
            "kind": kind_of(config),
            "config": config.model_dump(mode="json"),
            "input": supplied.model_dump(mode="json"),
            "reference_sha256": reference_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def provider_api(config: MediaConfig) -> str:
    if isinstance(config, ImageGenerateConfig):
        provider = image_models.by_provider(config.provider)
        if provider is not None:
            return provider.prefix
    else:
        provider = video_models.by_provider(config.provider)
        if provider is not None:
            return provider.api
    raise MediaOperationError("MEDIA_PROVIDER_UNAVAILABLE", "This media provider is unavailable")


def remaining_seconds(run: WorkflowRun, config: MediaConfig) -> float:
    seconds = float(config.timeout_seconds)
    if run.deadline_at is not None:
        seconds = min(seconds, (run.deadline_at - datetime.now(UTC)).total_seconds())
    if seconds <= 0:
        raise MediaOperationError("DEADLINE_EXCEEDED", "This media run's deadline has passed")
    return seconds


async def _budget_for_new(
    db: AsyncSession, run: WorkflowRun, attempt: NodeAttempt, config: MediaConfig, amount: Decimal
) -> None:
    own = budget.own_cap(config)
    free = await budget.unreserved(db, run)
    available = None if free is None else free + (attempt.reserved_usd or Decimal(0))
    ceiling = own if available is None else available if own is None else min(own, available)
    if ceiling is not None and amount > ceiling:
        raise MediaOperationError(
            "MEDIA_BUDGET_INSUFFICIENT",
            "The media reservation exceeds this step's available budget",
        )
    organization = await organization_repo.get_by_id(db, run.organization_id)
    if organization is not None and organization.monthly_budget_usd is not None:
        spent = await organization_monthly_spend(db, run.organization_id)
        held = await media_repo.outstanding_usd(db, organization_id=run.organization_id)
        if spent + held + amount > organization.monthly_budget_usd:
            raise MediaOperationError(
                "MEDIA_ORGANIZATION_BUDGET_INSUFFICIENT",
                "The organization cannot reserve this media request",
            )


async def admit(
    config: MediaConfig, supplied: MediaGenerateInput, *, reference_sha256: str | None
) -> WorkflowMediaOperation:
    current = context.current()
    identity = request_hash(config, supplied, reference_sha256)
    async with get_worker_db_context() as db:
        # All file writers and the dispatcher take this lock before run rows.
        # Media admissions share it for the USD and byte hold check/insert.
        await hold_subject(db, LockScope.WORKFLOW_FILE_BYTES, current.organization_id)
        run, attempt = await _authority.dispatch_rows(db, current, locked=True)
        auth = await _authority.principal(db, current, run)
        remaining_seconds(run, config)
        secret = await OrganizationSecretService(db).workflow_media_secret(
            auth, config.secret_id, provider=config.provider, locked=True
        )
        token = await _authority.fence(db, current, locked=True)
        existing = await media_repo.current_for_node(
            db,
            organization_id=current.organization_id,
            node_run_id=current.node_run_id,
            locked=True,
        )
        if existing is not None:
            if (
                existing.workflow_run_id != current.workflow_run_id
                or existing.request_hash != identity
                or existing.secret_id != secret.id
                or existing.secret_generation != secret.authorization_generation
                or existing.provider_api != provider_api(config)
            ):
                raise MediaOperationError(
                    "MEDIA_OPERATION_CHANGED",
                    "The original media request or credential has changed",
                )
            prepared_here = (
                existing.phase == "prepared"
                and existing.origin_attempt_id == attempt.id
                and existing.collector_token == token
            )
            if not prepared_here and not collectable(existing):
                raise MediaOperationError(
                    "MEDIA_RECONCILIATION_REQUIRED",
                    "This media operation cannot safely submit again",
                )
            return await media_repo.change(
                db,
                existing.id,
                organization_id=current.organization_id,
                values={"collector_attempt_id": attempt.id, "collector_token": token},
            )
        amount = config.reservation_usd()
        await _budget_for_new(db, run, attempt, config, amount)
        await files.reserve_capacity(db, size=config.max_output_bytes)
        return await media_repo.create(
            db,
            media_repo.MediaAdmission(
                id=uuid4(),
                organization_id=current.organization_id,
                workflow_run_id=current.workflow_run_id,
                node_run_id=current.node_run_id,
                attempt_id=attempt.id,
                collector_token=token,
                request_hash=identity,
                media_kind=kind_of(config),
                provider=config.provider,
                provider_api=provider_api(config),
                model=config.model,
                pricing_snapshot=snapshot(config).model_dump(mode="json"),
                secret_id=secret.id,
                secret_generation=secret.authorization_generation,
                reserved_usd=amount,
                reserved_bytes=config.max_output_bytes,
                output_file_id=uuid4(),
                output_filename=config.filename,
            ),
        )


async def recheck(
    operation: WorkflowMediaOperation, config: MediaConfig
) -> tuple[AuthContext, float]:
    """A fresh identity map sees authority changes made during provider/blob I/O."""
    current = context.current()
    async with get_worker_db_context() as db:
        run, _attempt = await _authority.dispatch_rows(db, current)
        auth = await _authority.principal(db, current, run)
        secret = await OrganizationSecretService(db).workflow_media_secret(
            auth, operation.secret_id, provider=operation.provider
        )
        if secret.authorization_generation != operation.secret_generation:
            raise MediaOperationError(
                "MEDIA_CREDENTIAL_CHANGED", "The original media credential has changed"
            )
        return auth, remaining_seconds(run, config)


@asynccontextmanager
async def effect_key(
    operation: WorkflowMediaOperation, config: MediaConfig
) -> AsyncGenerator[tuple[str, float]]:
    """Fence key rotation through a bounded call without holding a run/outbox lock."""
    auth, _ = await recheck(operation, config)
    async with get_worker_db_context() as db:
        value = await OrganizationSecretService(db).workflow_media_key(
            auth,
            operation.secret_id,
            provider=operation.provider,
            expected_generation=operation.secret_generation,
        )
        # Lock acquisition may wait behind a rotation or another collector. Read
        # principal, grants, run and claim again after it succeeds.
        _auth, seconds = await recheck(operation, config)
        yield value.api_key.get_secret_value(), seconds
