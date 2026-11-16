"""One durable draft attempt, current authority at each boundary, and no automatic model retry."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

import anyio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.redis import RedisClient
from app.core.browser_teaching import (
    MAX_GENERATION_SECONDS,
    BrowserProcedure,
    TeachingGeneration,
    TeachingReason,
    TeachingRefused,
    TeachingReview,
    TeachingState,
    stale_revision,
)
from app.core.exceptions import (
    SystemAgentOutputError,
    SystemAgentRunError,
    SystemAgentUnavailableError,
)
from app.core.permissions import AuthContext
from app.db.models.browser_teaching import BrowserTeachingSession
from app.db.models.skill_proposal import ProposalStatus, SkillProposal
from app.db.session import get_db_context
from app.repositories import browser_teaching as repo
from app.schemas.browser_teaching import TeachingPropose, TeachingRead
from app.services import background_jobs
from app.services.system_agent_runner import SystemAgentRunner
from app.worker.jobs import DRAFT_BROWSER_TEACHING, DraftBrowserTeaching

from . import _access
from ._draft import TeachingDraft, prompt, render, reviewed_draft
from ._service import BrowserTeachingService, audit, expire, read


def _matches(row: BrowserTeachingSession, job: DraftBrowserTeaching) -> bool:
    return (
        row.organization_id == job.organization_id
        and row.id == job.session_id
        and row.generation_token == job.token
        and row.generation_revision == job.revision
        and row.source_hash == job.source_hash
    )


def _reviewed(row: BrowserTeachingSession) -> tuple[TeachingReview, BrowserProcedure]:
    if row.review is None or row.procedure is None:
        raise TeachingRefused(TeachingReason.REVIEW_REQUIRED)
    review = TeachingReview.model_validate(row.review)
    procedure = BrowserProcedure.model_validate(row.procedure)
    if (
        BrowserTeachingService.reviewed(row, review) != procedure
        or row.source_hash != procedure.source_hash
    ):
        raise TeachingRefused(TeachingReason.REVIEW_REQUIRED)
    return review, procedure


class BrowserTeachingDraftService:
    def __init__(self, db: AsyncSession, redis: RedisClient) -> None:
        self.db, self.redis = db, redis

    async def propose(
        self, ctx: AuthContext, session_id: UUID, revision: int, data: TeachingPropose
    ) -> TeachingRead:
        current, row = await BrowserTeachingService(self.db, self.redis).owned(ctx, session_id)
        if row.generation_state in {
            TeachingGeneration.QUEUED,
            TeachingGeneration.GENERATING,
            TeachingGeneration.SUCCEEDED,
            TeachingGeneration.UNKNOWN,
        }:
            if (
                row.generation_revision == revision
                and row.generation_mode == data.mode
                and row.max_cost_usd == data.max_cost_usd
            ):
                return read(row)
            raise stale_revision()
        if row.revision != revision:
            raise stale_revision()
        if row.status != TeachingState.REVIEW or row.generation_state != TeachingGeneration.NONE:
            raise TeachingRefused(TeachingReason.REVIEW_REQUIRED)
        admission = await _access.authorize(self.db, current, row, live=False)
        _access.require_reviewable(row, admission.run)
        review, procedure = _reviewed(row)
        render(review, procedure, reviewed_draft(review, procedure))
        if data.mode == "assistant":
            try:
                await SystemAgentRunner(self.db).require_runnable(current, key="authoring_improver")
            except SystemAgentUnavailableError:
                raise TeachingRefused(TeachingReason.BUDGET_REFUSED) from None
        token = uuid4()
        row.generation_token = token
        row.generation_revision, row.generation_mode = revision, data.mode
        row.max_cost_usd, row.generation_state = data.max_cost_usd, TeachingGeneration.QUEUED.value
        row.reason_code, row.generation_started_at = None, None
        row.revision += 1
        job = DraftBrowserTeaching(
            organization_id=row.organization_id,
            session_id=row.id,
            revision=revision,
            source_hash=procedure.source_hash,
            token=token,
        )
        await background_jobs.enqueue(
            self.db,
            DRAFT_BROWSER_TEACHING,
            job,
            organization_id=row.organization_id,
            dedupe_key=f"browser-teaching:{row.id}:{revision}:{procedure.source_hash}",
            dedupe_active=True,
            concurrency_key=f"browser-teaching:{row.organization_id}:{row.owner_user_id}",
            idempotency_key=str(row.generation_token),
        )
        await self.db.flush()
        await audit(self.db, row, "browser_teaching.draft_requested")
        return read(row)


@dataclass(frozen=True)
class DraftClaim:
    job: DraftBrowserTeaching
    context: AuthContext
    review: TeachingReview
    procedure: BrowserProcedure
    mode: Literal["reviewed", "assistant"]
    max_cost_usd: Decimal | None


def _mode(row: BrowserTeachingSession) -> Literal["reviewed", "assistant"]:
    if row.generation_mode == "reviewed":
        return "reviewed"
    if row.generation_mode == "assistant":
        return "assistant"
    raise TeachingRefused(TeachingReason.REVIEW_REQUIRED)


async def _claim(job: DraftBrowserTeaching) -> DraftClaim | None:
    async with get_db_context() as db:
        row = await repo.session(db, job.organization_id, job.session_id, locked=True)
        if (
            row is None
            or not _matches(row, job)
            or row.generation_state != TeachingGeneration.QUEUED
        ):
            return None
        expire(row, datetime.now(UTC))
        if row.status != TeachingState.REVIEW:
            return None
        context = AuthContext(
            user_id=row.owner_user_id, organization_id=row.organization_id, role="member"
        )
        try:
            admission = await _access.authorize(db, context, row, live=False)
            _access.require_reviewable(row, admission.run)
            review, procedure = _reviewed(row)
            mode = _mode(row)
        except (TeachingRefused, ValidationError) as refused:
            row.generation_state = TeachingGeneration.REFUSED.value
            row.reason_code = (
                refused.reason.value
                if isinstance(refused, TeachingRefused)
                else TeachingReason.INVALID_DRAFT.value
            )
            row.revision += 1
            await audit(db, row, "browser_teaching.draft_refused")
            return None
        row.generation_state, row.generation_started_at = (
            TeachingGeneration.GENERATING.value,
            datetime.now(UTC),
        )
        row.revision += 1
        await audit(db, row, "browser_teaching.draft_started")
        return DraftClaim(
            job,
            admission.context,
            review,
            procedure,
            mode,
            row.max_cost_usd,
        )


async def _current(
    db: AsyncSession, claim: DraftClaim, *, locked: bool = False
) -> BrowserTeachingSession:
    row = await repo.session(db, claim.job.organization_id, claim.job.session_id, locked=locked)
    if (
        row is None
        or not _matches(row, claim.job)
        or row.status != TeachingState.REVIEW
        or row.generation_state != TeachingGeneration.GENERATING
    ):
        raise TeachingRefused(TeachingReason.AUTHORITY_CHANGED)
    if row.expires_at <= datetime.now(UTC):
        raise TeachingRefused(TeachingReason.EXPIRED)
    admission = await _access.authorize(db, claim.context, row, live=False)
    _access.require_reviewable(row, admission.run)
    if _reviewed(row) != (claim.review, claim.procedure):
        raise TeachingRefused(TeachingReason.REVIEW_REQUIRED)
    return row


async def _assistant(claim: DraftClaim) -> TeachingDraft:
    if claim.max_cost_usd is None or claim.max_cost_usd <= 0:
        raise TeachingRefused(TeachingReason.BUDGET_REFUSED)

    async def check(db: AsyncSession) -> None:
        await _current(db, claim)

    async with get_db_context() as db:
        await check(db)
        result = await SystemAgentRunner(db).run(
            claim.context,
            key="authoring_improver",
            prompt=prompt(claim.review, claim.procedure),
            output_type=TeachingDraft,
            run_limit_usd=claim.max_cost_usd,
            check_model_request=check,
        )
        return result.output


async def _finish(claim: DraftClaim, draft: TeachingDraft) -> None:
    content = render(claim.review, claim.procedure, draft)
    async with get_db_context() as db:
        row = await _current(db, claim, locked=True)
        proposal = await repo.proposal_for_source(db, row.organization_id, row.id)
        if proposal is None:
            proposal = SkillProposal(
                organization_id=row.organization_id,
                skill_id=row.target_skill_id,
                agent_id=row.agent_id,
                conversation_id=None,
                name=claim.review.name,
                description=draft.description,
                content=content,
                resources={},
                base_version=row.target_base_version,
                base_version_id=row.target_base_version_id,
                fork_id=None,
                source="browser_teaching",
                status=ProposalStatus.PENDING.value,
                browser_procedure=claim.procedure.model_dump(mode="json"),
                rationale="Created from an explicitly reviewed browser demonstration.",
                expected_effect="Provide a bounded site procedure that still requires fresh observations and current authority.",
                evidence=[],
            )
            await repo.create_proposal(db, proposal)
        elif proposal.browser_procedure != claim.procedure.model_dump(mode="json"):
            raise TeachingRefused(TeachingReason.REVIEW_REQUIRED)
        row.proposal_id, row.status = proposal.id, TeachingState.PROPOSED.value
        row.generation_state, row.reason_code = TeachingGeneration.SUCCEEDED.value, None
        row.revision += 1
        await audit(db, row, "browser_teaching.draft_created")


async def _settle(claim: DraftClaim, state: TeachingGeneration, reason: TeachingReason) -> None:
    with anyio.move_on_after(10, shield=True):
        with suppress(Exception):
            async with get_db_context() as db:
                row = await repo.session(
                    db, claim.job.organization_id, claim.job.session_id, locked=True
                )
                if (
                    row is None
                    or not _matches(row, claim.job)
                    or row.generation_state != TeachingGeneration.GENERATING
                ):
                    return
                row.generation_state, row.reason_code = state.value, reason.value
                row.revision += 1
                await audit(db, row, "browser_teaching.draft_stopped")


async def draft_browser_teaching(job: DraftBrowserTeaching) -> None:
    claim = await _claim(job)
    if claim is None:
        return
    try:
        with anyio.fail_after(MAX_GENERATION_SECONDS):
            draft = (
                reviewed_draft(claim.review, claim.procedure)
                if claim.mode == "reviewed"
                else await _assistant(claim)
            )
            await _finish(claim, draft)
    except TeachingRefused as refused:
        await _settle(claim, TeachingGeneration.REFUSED, refused.reason)
    except SystemAgentOutputError, ValidationError, ValueError:
        await _settle(claim, TeachingGeneration.REFUSED, TeachingReason.INVALID_DRAFT)
    except SystemAgentUnavailableError:
        await _settle(claim, TeachingGeneration.REFUSED, TeachingReason.BUDGET_REFUSED)
    except SystemAgentRunError:
        await _settle(claim, TeachingGeneration.REFUSED, TeachingReason.GENERATION_FAILED)
    except asyncio.CancelledError:
        await _settle(claim, TeachingGeneration.UNKNOWN, TeachingReason.GENERATION_UNKNOWN)
        raise
    except Exception:
        # A model/transport error may contain reviewed private task data. It is
        # neither logged nor retried; reconciliation retains this fixed receipt.
        await _settle(claim, TeachingGeneration.UNKNOWN, TeachingReason.GENERATION_UNKNOWN)
