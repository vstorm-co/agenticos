"""Keys drafted from a case's reference answer, for a person to review.

A person asks for the facts a case's reference answer holds; the key extractor
lists them in a job, since a long document can take it longer than a request may
wait, and the list waits as the case's draft until the person uses or dismisses
it. Only a value the answer states as written is kept, found the way a `keys`
check looks for it, so a value the extractor invented or reworded never reaches
the review.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.system_agents import KEY_EXTRACTOR
from app.core.audit import record_audit
from app.core.exceptions import AppException, AuthenticationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.case_key_draft import CaseKeyDraft, KeyDraftStatus
from app.db.models.dataset import Dataset, DatasetCase
from app.db.session import get_worker_db_context
from app.repositories import case_key_draft_repo, dataset_repo
from app.schemas.case_key_draft import CaseKeyDraftRead, ExtractedKeys
from app.schemas.dataset_helpers import DatasetHelpers
from app.schemas.scoring import MAX_KEYS, DocumentKey
from app.services.api_key import job_context
from app.services.background_jobs import enqueue
from app.services.dataset import DatasetService
from app.services.scorers import carries
from app.services.system_agent_runner import SystemAgentRunner
from app.worker.jobs import EXTRACT_CASE_KEYS, ExtractCaseKeys

logger = logging.getLogger(__name__)

NO_REFERENCE = "This case has no reference answer to list keys from"
REQUESTER_GONE = "Whoever asked for these keys is no longer a member."
STOPPED = "Listing the keys stopped before it finished. Ask again."
FAILED = "Listing the keys failed. Ask again."
REFERENCE_CHANGED = "The reference answer changed since the keys were asked for. Ask again."


def _read(draft: CaseKeyDraft) -> CaseKeyDraftRead:
    return CaseKeyDraftRead.model_validate(draft)


def kept_keys(document: str, keys: list[DocumentKey]) -> list[dict[str, str]]:
    """The keys whose value `document` states, each label once, in their order.

    A label is compared trimmed and without case, and the first one stands.
    """
    seen: set[str] = set()
    kept: list[dict[str, str]] = []
    for entry in keys:
        label, value = entry.key.strip(), entry.value.strip()
        if not label or not value or label.casefold() in seen:
            continue
        if not carries(document, value):
            continue
        seen.add(label.casefold())
        kept.append({"key": label, "value": value})
        if len(kept) == MAX_KEYS:
            break
    return kept


def _model_of(dataset: Dataset) -> UUID | None:
    return DatasetHelpers.model_validate(dataset.helper_settings or {}).generator.model_profile_id


class CaseKeyDraftService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.datasets = DatasetService(db)

    async def start(self, ctx: AuthContext, dataset_id: UUID, case_id: UUID) -> CaseKeyDraftRead:
        """Ask for the keys of a case's reference answer. Answers at once; a job lists them.

        A case's earlier draft is replaced. The job is queued in this transaction,
        and checks the caller's access again when it runs.

        Raises:
            NotFoundError, AuthorizationError: As :meth:`DatasetService.editable_case` does.
            BadRequestError: The case has no reference answer.
            SystemAgentUnavailableError: The key extractor cannot run for this caller.
        """
        dataset, case = await self.datasets.editable_case(ctx, dataset_id, case_id)
        if not (case.reference_answer or "").strip():
            raise BadRequestError(message=NO_REFERENCE, details={"case_id": case_id})
        # Refused here with the reason, rather than queued to fail at once.
        await SystemAgentRunner(self.db).require_runnable(
            ctx, key=KEY_EXTRACTOR.key, model_profile_id=_model_of(dataset)
        )
        draft = await case_key_draft_repo.replace(
            self.db,
            organization_id=ctx.organization_id,
            dataset_id=dataset.id,
            case_id=case.case_id,
            revision_id=case.id,
            requested_by_user_id=ctx.subject_id,
            created_by_api_key_id=ctx.api_key_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="dataset.keys_requested",
            target_type="dataset",
            target_id=str(dataset.id),
            details={"case_id": str(case.case_id)},
        )
        await enqueue(
            self.db,
            EXTRACT_CASE_KEYS,
            ExtractCaseKeys(draft_id=draft.id, organization_id=ctx.organization_id),
            organization_id=ctx.organization_id,
        )
        return _read(draft)

    async def get(self, ctx: AuthContext, dataset_id: UUID, case_id: UUID) -> CaseKeyDraftRead:
        """The case's draft, for a person who may edit the case and read its text.

        Raises:
            NotFoundError: As :meth:`DatasetService.editable_case` does, or when the
                case has no draft.
            AuthorizationError: As :meth:`DatasetService.editable_case` does.
        """
        dataset, case = await self.datasets.editable_case(ctx, dataset_id, case_id)
        draft = await case_key_draft_repo.get_for_case(
            self.db, organization_id=ctx.organization_id, dataset_id=dataset.id, case_id=case_id
        )
        if draft is None or not await self._reads_current(draft, case):
            raise NotFoundError(
                message="This case has no drafted keys", details={"case_id": case.case_id}
            )
        return _read(draft)

    async def _reads_current(self, draft: CaseKeyDraft, case: DatasetCase) -> bool:
        """Whether the draft was listed from the reference answer the case holds now.

        Any edit makes a new revision; only one that changed the reference answer
        leaves the draft's keys describing another document.
        """
        if draft.revision_id == case.id:
            return True
        listed = await dataset_repo.get_case_revision(
            self.db, draft.revision_id, organization_id=draft.organization_id
        )
        # A draft is deleted with the revision it read (`ON DELETE CASCADE`).
        assert listed is not None
        return (listed.reference_answer or "").strip() == (case.reference_answer or "").strip()

    async def dismiss(self, ctx: AuthContext, dataset_id: UUID, case_id: UUID) -> None:
        """Delete the case's draft, used or not. Deleting none is not an error.

        Raises:
            NotFoundError, AuthorizationError: As :meth:`DatasetService.editable_case` does.
        """
        dataset, case = await self.datasets.editable_case(ctx, dataset_id, case_id)
        await case_key_draft_repo.delete_for_case(
            self.db,
            organization_id=ctx.organization_id,
            dataset_id=dataset.id,
            case_id=case.case_id,
        )

    async def extract(self, draft_id: UUID, organization_id: UUID) -> None:
        """Run the key extractor for a draft that is still running, and record how it went.

        Never raises: a refusal is the draft's `error`, and the run the extractor
        made - its cost included - is linked to the draft whether it answered or not.
        """
        draft = await case_key_draft_repo.get(self.db, draft_id, organization_id=organization_id)
        if draft is None or draft.status != KeyDraftStatus.RUNNING.value:
            return
        try:
            ctx = await job_context(
                self.db,
                organization_id=organization_id,
                user_id=draft.requested_by_user_id,
                api_key_id=draft.created_by_api_key_id,
            )
        except AuthenticationError as exc:
            await self._fail(draft_id, organization_id, exc.message)
            return
        if ctx is None:
            await self._fail(draft_id, organization_id, REQUESTER_GONE)
            return
        try:
            dataset, case = await self.datasets.editable_case(ctx, draft.dataset_id, draft.case_id)
        except AppException as exc:
            await self._fail(draft_id, organization_id, exc.message)
            return
        document = (case.reference_answer or "").strip()
        if not document:
            await self._fail(draft_id, organization_id, NO_REFERENCE)
            return
        if not await self._reads_current(draft, case):
            await self._fail(draft_id, organization_id, REFERENCE_CHANGED)
            return
        runner = SystemAgentRunner(self.db)
        try:
            result = await runner.run(
                ctx,
                key=KEY_EXTRACTOR.key,
                model_profile_id=_model_of(dataset),
                prompt=f"Document:\n\n{document}",
                output_type=ExtractedKeys,
            )
        except AppException as exc:
            await self._fail(
                draft_id, organization_id, exc.message, run_id=getattr(exc, "run_id", None)
            )
            return
        except Exception:
            logger.exception("case_key_draft_failed", extra={"draft_id": str(draft_id)})
            await self.db.rollback()
            await self._fail(draft_id, organization_id, FAILED, run_id=runner.failed_run_id)
            return
        await case_key_draft_repo.finish(
            self.db,
            draft_id,
            organization_id=organization_id,
            status=KeyDraftStatus.READY,
            finished_at=datetime.now(UTC),
            keys=kept_keys(document, result.output.keys),
            run_id=result.run.id,
        )

    async def _fail(
        self, draft_id: UUID, organization_id: UUID, error: str, *, run_id: UUID | None = None
    ) -> None:
        await case_key_draft_repo.finish(
            self.db,
            draft_id,
            organization_id=organization_id,
            status=KeyDraftStatus.FAILED,
            finished_at=datetime.now(UTC),
            error=error[:500],
            run_id=run_id,
        )


async def extract_case_keys(draft_id: UUID, organization_id: UUID) -> None:
    """The job: list one draft's keys in a session of its own."""
    async with get_worker_db_context() as db:
        await CaseKeyDraftService(db).extract(draft_id, organization_id)


async def settle_lost(draft_id: UUID, organization_id: UUID) -> None:
    """Fail a draft whose job ended for good while it was still running.

    A worker killed under the job cannot mark the draft itself, and nothing else
    would ever finish it. A draft the job already ended is left as it is.
    """
    async with get_worker_db_context() as db:
        await case_key_draft_repo.finish(
            db,
            draft_id,
            organization_id=organization_id,
            status=KeyDraftStatus.FAILED,
            finished_at=datetime.now(UTC),
            error=STOPPED,
        )
