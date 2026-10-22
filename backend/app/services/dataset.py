"""Datasets - the questions an agent is tested on, as versioned cases.

This module owns storage, access and versioning. Every change to a dataset's
cases goes through :meth:`DatasetService._mint`, which writes the next version
under a lock on the dataset row; nothing else writes a version, so "every change
mints a version" is a property of one method rather than of every caller.

Case text is copied from conversations and from files people upload, and it is
then exported and handed to models. A credential in it is redacted before the
case is stored, on every way in.
"""

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import takewhile
from typing import Any
from uuid import UUID

from pydantic import JsonValue, ValidationError
from pydantic_ai_harness.guardrails.detectors import redact_secrets
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.isolation import capability_tools
from app.agents.spec import AgentSpec
from app.agents.system_agents import JUDGE
from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    BadRequestError,
    EvalSuiteInUseError,
    NotFoundError,
)
from app.core.exceptions import ValidationError as InvalidCaseError
from app.core.field_errors import field_problems, refused_field
from app.core.permissions import AuthContext, Perm, Scope
from app.db.locks import LockScope, hold_subject
from app.db.models.case_generation import CaseOrigin
from app.db.models.conversation import Message
from app.db.models.dataset import CaseSource, Dataset, DatasetCase, DatasetChange, DatasetVersion
from app.db.updates import writable
from app.repositories import (
    agent_repo,
    agent_run_repo,
    case_generation_repo,
    conversation_repo,
    dataset_repo,
    message_rating_repo,
    promotion_gate_repo,
    resource_grant_repo,
)
from app.schemas.dataset import (
    MAX_HISTORY_TURNS,
    AnswerAs,
    DatasetCaseContent,
    DatasetCaseFromMessage,
    DatasetCaseList,
    DatasetCaseRead,
    DatasetCaseUpdate,
    DatasetCreate,
    DatasetFileFormat,
    DatasetList,
    DatasetRead,
    DatasetSort,
    DatasetStats,
    DatasetUpdate,
    DatasetVersionList,
    DatasetVersionRead,
    EditedCaseContent,
)
from app.schemas.resource_grant import as_visibility
from app.schemas.scoring import DatasetScoring, ExpectedToolCall
from app.services import dataset_files
from app.services.access import DATASET, accessible_ids, resolve_access, visible_resource_ids
from app.services.conversation import ConversationService
from app.services.exporting import MAX_EXPORT_ROWS, ExportResult, stamp

logger = logging.getLogger(__name__)

# The most cases one dataset holds. The export cap, so every version of every
# dataset can always be exported whole.
MAX_CASES = MAX_EXPORT_ROWS
_MAX_REPLY_STEPS = 50
_MAX_EXPECTED_CALLS = 50


def _name_taken(name: str) -> AlreadyExistsError:
    return AlreadyExistsError(
        message=f"A dataset named '{name}' already exists. Choose a different name.",
        details={"name": name},
    )


def _refuse_past_ceiling(held: int, adding: int) -> None:
    """Refuse a change that would take a dataset past :data:`MAX_CASES`.

    Raises:
        BadRequestError: Naming how many the dataset holds and how many were added.
    """
    if held + adding > MAX_CASES:
        raise BadRequestError(
            message=(
                f"A dataset holds at most {MAX_CASES} cases; this one has {held}. "
                "Split the cases across two datasets."
            ),
            details={"case_count": held, "adding": adding, "max_cases": MAX_CASES},
        )


@dataclass(frozen=True)
class GeneratedCase:
    """A generated case on its way into a dataset, with what it was drafted from."""

    content: DatasetCaseContent
    source_document_id: UUID | None = None
    source_run_id: UUID | None = None
    source_conversation_id: UUID | None = None
    source_message_id: UUID | None = None


def _refuse_past_storage(used: int, adding: int) -> None:
    """Refuse new case revisions that would take the organization past what it may store.

    Every added or edited case is a stored revision, kept for the versions that
    hold it; removing a case stores nothing, so it is never refused.

    Raises:
        BadRequestError: Naming how many revisions are stored, how many this
            change adds and the ceiling, and what to do about it.
    """
    ceiling = settings.DATASET_MAX_VERSION_ROWS_PER_ORG
    if adding and used + adding > ceiling:
        raise BadRequestError(
            message=(
                f"This organization's datasets store {used:,} case revisions - every case "
                f"added and every edit, kept for the versions that hold them - and this "
                f"change would add {adding:,} more; the limit is {ceiling:,}. Delete "
                "datasets you no longer need, or ask the deployment's administrator to "
                "raise DATASET_MAX_VERSION_ROWS_PER_ORG."
            ),
            details={"version_rows": used, "adding": adding, "max_version_rows": ceiling},
        )


def proposals_hidden_from(ctx: AuthContext) -> str | None:
    """The origin of the proposed cases this caller may not read, if any.

    A draft from chats paraphrases what somebody else asked an agent, which only
    a reader of runs may see - the same gate drafting from chats takes.
    """
    return None if ctx.has(Perm.RUNS_VIEW) else CaseOrigin.CONVERSATION.value


def redact_credentials(text: str | None) -> tuple[str | None, int]:
    """The text with any credential replaced by a placeholder, and how many were."""
    if not text:
        return text, 0
    verdict = redact_secrets(text)
    if verdict.action != "replace" or not isinstance(verdict.replacement, str):
        return text, 0
    return verdict.replacement, verdict.replacement.count("[redacted:")


def _redact_json(value: JsonValue) -> tuple[JsonValue, int]:
    if isinstance(value, str):
        cleaned, found = redact_credentials(value)
        return cleaned, found
    if isinstance(value, list):
        items = [_redact_json(item) for item in value]
        return [item for item, _ in items], sum(found for _, found in items)
    if isinstance(value, dict):
        entries = {key: _redact_json(item) for key, item in value.items()}
        return {key: item for key, (item, _) in entries.items()}, sum(
            found for _, found in entries.values()
        )
    return value, 0


def redacted_case(content: DatasetCaseContent) -> tuple[dict[str, Any], int]:
    """A case's fields ready for its row, with every credential in them redacted.

    Everything a model is later handed or a person exports: the turns, the
    answers, the note, the tags, the arguments an expected tool call is matched
    on and every parameter of a check. A check's `type` is left alone, because it
    names the rule rather than holding anything somebody wrote.
    """
    data = content.model_dump(mode="json")
    found = 0
    for field in ("input", "reference_answer", "counter_example", "note"):
        data[field], count = redact_credentials(data[field])
        found += count
    for turn in data["history"]:
        turn["content"], count = redact_credentials(turn["content"])
        found += count
    for call in data["expected_tool_calls"]:
        call["args"], count = _redact_json(call["args"])
        found += count
    for check in data["checks"]:
        for key in [key for key in check if key != "type"]:
            check[key], count = _redact_json(check[key])
            found += count
    data["tags"], count = _redact_json(data["tags"])
    found += count
    return data, found


def _case_read(case: DatasetCase) -> DatasetCaseRead:
    return DatasetCaseRead.model_validate(case)


def _version_read(version: DatasetVersion) -> DatasetVersionRead:
    return DatasetVersionRead.model_validate(version)


def _dataset_read(
    dataset: Dataset,
    *,
    can_edit: bool,
    can_run: bool,
    judge_name: str | None,
    stats: DatasetStats | None = None,
    pending: int = 0,
) -> DatasetRead:
    return DatasetRead(
        stats=stats or DatasetStats(),
        judge_name=judge_name,
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        visibility=as_visibility(dataset.visibility),
        owner_user_id=dataset.owner_user_id,
        agent_id=dataset.agent_id,
        latest_version=dataset.latest_version,
        case_count=dataset.case_count,
        can_edit=can_edit,
        can_run=can_run,
        pending_proposals=pending if can_edit else 0,
        scoring=DatasetScoring.model_validate(dataset.scoring),
        created_at=dataset.created_at,
        updated_at=dataset.updated_at,
    )


class DatasetService:
    """Manage an organization's datasets and their versioned cases."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(
        self, ctx: AuthContext, dataset_id: UUID, *, perm: Perm = Perm.DATASETS_VIEW
    ) -> Dataset:
        """One dataset the caller may exercise `perm` on.

        Raises:
            NotFoundError: When it does not exist, belongs to another organization,
                or the caller lacks `perm` on it. One answer for all three: whether
                a private dataset exists is itself something the caller may not
                learn.
        """
        dataset = await dataset_repo.get(self.db, dataset_id, organization_id=ctx.organization_id)
        if dataset is None or not await resolve_access(
            self.db, ctx, dataset, perm, resource_type=DATASET
        ):
            raise NotFoundError(message="Dataset not found", details={"dataset_id": dataset_id})
        return dataset

    async def _can_edit(self, ctx: AuthContext, dataset: Dataset) -> bool:
        return await resolve_access(
            self.db, ctx, dataset, Perm.DATASETS_EDIT, resource_type=DATASET
        )

    async def _pending(self, ctx: AuthContext, dataset_ids: list[UUID]) -> dict[UUID, int]:
        return await case_generation_repo.count_pending(
            self.db,
            dataset_ids,
            organization_id=ctx.organization_id,
            without_origin=proposals_hidden_from(ctx),
        )

    async def _stats(self, ctx: AuthContext, datasets: list[Dataset]) -> dict[UUID, DatasetStats]:
        return await dataset_repo.case_stats(
            self.db, [dataset.id for dataset in datasets], organization_id=ctx.organization_id
        )

    async def _judge_names(self, ctx: AuthContext, datasets: list[Dataset]) -> dict[UUID, str]:
        """Each dataset's judge by name: the one it picked, or the seeded default.

        A read never seeds, so before the default judge exists a dataset that
        picked none has no name here, as one whose judge was deleted has none.
        """
        picked = {
            dataset.id: DatasetScoring.model_validate(dataset.scoring).judge.agent_id
            for dataset in datasets
        }
        judges = await agent_repo.get_many(
            self.db,
            [agent_id for agent_id in set(picked.values()) if agent_id is not None],
            organization_id=ctx.organization_id,
        )
        default = (
            await agent_repo.get_system(self.db, organization_id=ctx.organization_id, key=JUDGE.key)
            if None in picked.values()
            else None
        )
        names: dict[UUID, str] = {}
        for dataset_id, agent_id in picked.items():
            judge = default if agent_id is None else judges.get(agent_id)
            if judge is not None:
                names[dataset_id] = judge.name
        return names

    async def read(self, ctx: AuthContext, dataset_id: UUID) -> DatasetRead:
        dataset = await self.get(ctx, dataset_id)
        can_edit = await self._can_edit(ctx, dataset)
        pending = (await self._pending(ctx, [dataset.id])).get(dataset.id, 0) if can_edit else 0
        stats = await self._stats(ctx, [dataset])
        judges = await self._judge_names(ctx, [dataset])
        return _dataset_read(
            dataset,
            can_edit=can_edit,
            can_run=await resolve_access(
                self.db, ctx, dataset, Perm.DATASETS_RUN, resource_type=DATASET
            ),
            judge_name=judges.get(dataset.id),
            stats=stats.get(dataset.id),
            pending=pending,
        )

    async def list_readable(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        editable: bool = False,
        runnable: bool = False,
        search: str | None = None,
        judge_id: UUID | None = None,
        asked_by_run: UUID | None = None,
        sort: DatasetSort = "name",
        skip: int = 0,
        limit: int = 50,
    ) -> DatasetList:
        """A page of the datasets this caller may see, each saying whether they may edit it.

        `judge_id` narrows to the datasets that judge grades: those that picked
        it, and for the seeded default judge those that picked none. `runnable`
        narrows to those the caller may run that hold a case to run - what an
        eval or a score needs - so "may I run any" is the `total` of one row.
        `asked_by_run` narrows to those whose newest version holds a case asking
        that run's question - read from the run, so the question itself never
        travels in a URL. A run the caller may not read narrows to nothing.

        Scoped like every shared resource: a role reaching the whole organization
        lists everything, anyone else their own, the org-visible ones and those
        shared with them - the set :func:`resolve_access` admits one row at a
        time. `can_edit` costs one grant query for the page, not one per row.
        """
        asking = None
        if asked_by_run is not None:
            asking = await self._question_of(ctx, asked_by_run)
            if asking is None:
                return DatasetList(items=[], total=0)
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=DATASET, perm=Perm.DATASETS_VIEW
        )
        grant_ids = [] if shared is None else shared
        if shared_with_me and shared is None:
            grant_ids = await resource_grant_repo.list_shared_ids(
                self.db,
                organization_id=ctx.organization_id,
                subject_user_id=ctx.subject_id,
                resource_type=DATASET.key,
            )
        # The same answer `can_edit` gives per row, asked of the whole listing, so
        # "is there anything I may add to" is one row of one page, not a scan.
        edit_ids = (
            await visible_resource_ids(self.db, ctx, resource_type=DATASET, perm=Perm.DATASETS_EDIT)
            if editable
            else None
        ) or []
        run_ids = (
            await visible_resource_ids(self.db, ctx, resource_type=DATASET, perm=Perm.DATASETS_RUN)
            if runnable
            else None
        ) or []
        items, total = await dataset_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=grant_ids,
            shared_with_me=shared_with_me,
            edit_scope=ctx.scope_for(Perm.DATASETS_EDIT) if editable else None,
            edit_ids=edit_ids,
            run_scope=ctx.scope_for(Perm.DATASETS_RUN) if runnable else None,
            run_ids=run_ids,
            search=search,
            judge_id=judge_id,
            judge_is_default=judge_id is not None and await self._is_default_judge(ctx, judge_id),
            asking=asking,
            sort=sort,
            skip=skip,
            limit=limit,
        )
        may_edit = await accessible_ids(
            self.db, ctx, items, Perm.DATASETS_EDIT, resource_type=DATASET
        )
        may_run = await accessible_ids(
            self.db, ctx, items, Perm.DATASETS_RUN, resource_type=DATASET
        )
        pending = await self._pending(ctx, [item.id for item in items if item.id in may_edit])
        stats = await self._stats(ctx, items)
        judges = await self._judge_names(ctx, items)
        return DatasetList(
            items=[
                _dataset_read(
                    item,
                    can_edit=item.id in may_edit,
                    can_run=item.id in may_run,
                    judge_name=judges.get(item.id),
                    stats=stats.get(item.id),
                    pending=pending.get(item.id, 0),
                )
                for item in items
            ],
            total=total,
        )

    async def _question_of(self, ctx: AuthContext, run_id: UUID) -> str | None:
        """The question one run answered, for a caller who may read the run.

        None for a run of another organization, one the caller may not read -
        reading a run takes `runs:view`, as its transcript does - or one that
        kept no question. Redacted as a case's input is when it is stored, so a
        question holding a credential still finds the case taken from it.
        """
        if not ctx.has(Perm.RUNS_VIEW):
            return None
        question = await conversation_repo.question_of_run(
            self.db, run_id=run_id, organization_id=ctx.organization_id
        )
        return redact_credentials(question)[0]

    async def _is_default_judge(self, ctx: AuthContext, agent_id: UUID) -> bool:
        default = await agent_repo.get_system(
            self.db, organization_id=ctx.organization_id, key=JUDGE.key
        )
        return default is not None and default.id == agent_id

    async def _refuse_taken_name(self, ctx: AuthContext, name: str) -> None:
        if await dataset_repo.get_by_name(self.db, name, organization_id=ctx.organization_id):
            raise _name_taken(name)

    async def create(
        self, ctx: AuthContext, data: DatasetCreate, *, agent_id: UUID | None = None
    ) -> DatasetRead:
        """An empty dataset, visible to the whole organization unless `data` says otherwise.

        `agent_id` names the agent it is made to test, for the caller that made it
        for one; the caller has checked that agent is theirs to see.
        """
        await self._refuse_taken_name(ctx, data.name)
        try:
            # A savepoint, because the check above is a read two requests can both
            # pass: the loser's insert then meets `uq_dataset_org_name` and answers
            # 409 like the check would have, rather than 500.
            async with self.db.begin_nested():
                dataset = await dataset_repo.create(
                    self.db,
                    organization_id=ctx.organization_id,
                    owner_user_id=ctx.subject_id,
                    name=data.name,
                    description=data.description,
                    visibility=data.visibility,
                    agent_id=agent_id,
                )
        except IntegrityError:
            raise _name_taken(data.name) from None
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="dataset.created",
            target_type="dataset",
            target_id=str(dataset.id),
            details={"name": dataset.name},
        )
        return await self.read(ctx, dataset.id)

    async def update(self, ctx: AuthContext, dataset_id: UUID, data: DatasetUpdate) -> DatasetRead:
        """Rename or redescribe a dataset. Its cases, and so its version, do not change."""
        dataset = await self.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        update_data = writable(data, over=Dataset)
        if "name" in update_data and update_data["name"] != dataset.name:
            await self._refuse_taken_name(ctx, update_data["name"])
        try:
            async with self.db.begin_nested():
                updated = await dataset_repo.update(
                    self.db, dataset=dataset, update_data=update_data
                )
        except IntegrityError:
            raise _name_taken(update_data["name"]) from None
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="dataset.updated",
            target_type="dataset",
            target_id=str(dataset.id),
            details={"name": updated.name, "fields": sorted(update_data)},
        )
        return await self.read(ctx, updated.id)

    async def delete(self, ctx: AuthContext, dataset_id: UUID) -> None:
        """Delete a dataset with every version and case it held.

        Raises:
            EvalSuiteInUseError: An eval suite checking it guards an environment;
                its suites would go with it and leave that environment unguarded.
        """
        dataset = await self.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        name = dataset.name
        guarded = await promotion_gate_repo.guarded_by_dataset(
            self.db, dataset.id, organization_id=ctx.organization_id
        )
        if guarded:
            names = ", ".join(environment.name for environment in guarded)
            raise EvalSuiteInUseError(
                message=(
                    f"'{name}' is checked by eval suites that guard {names}. "
                    "Take them off there before deleting it."
                ),
                details={"dataset_id": dataset.id, "environments": [e.id for e in guarded]},
            )
        await resource_grant_repo.delete_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=DATASET.key,
            resource_id=dataset.id,
        )
        await dataset_repo.delete(self.db, dataset)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="dataset.deleted",
            target_type="dataset",
            target_id=str(dataset_id),
            details={"name": name},
        )

    async def list_versions(
        self, ctx: AuthContext, dataset_id: UUID, *, skip: int = 0, limit: int = 50
    ) -> DatasetVersionList:
        dataset = await self.get(ctx, dataset_id)
        items, total = await dataset_repo.list_versions(
            self.db, dataset.id, organization_id=ctx.organization_id, skip=skip, limit=limit
        )
        return DatasetVersionList(items=[_version_read(item) for item in items], total=total)

    async def _version(
        self, ctx: AuthContext, dataset: Dataset, number: int | None
    ) -> DatasetVersion | None:
        """The version asked for, the newest when none is, or `None` before any exists.

        Raises:
            NotFoundError: For a number the dataset never reached.
        """
        wanted = dataset.latest_version if number is None else number
        if wanted == 0 and number is None:
            return None
        version = await dataset_repo.get_version(
            self.db, dataset.id, wanted, organization_id=ctx.organization_id
        )
        if version is None:
            raise NotFoundError(
                message="This dataset has no such version",
                details={"dataset_id": dataset.id, "version": number},
            )
        return version

    async def list_cases(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        *,
        version: int | None = None,
        skip: int = 0,
        limit: int = 50,
        same_input: str | None = None,
    ) -> DatasetCaseList:
        """A page of the cases one version holds - the newest version unless one is named.

        `same_input` narrows to the cases asking that question, as a new case is
        checked for one already there; `total` then counts the matches on this page.
        It is redacted as a case's input is when stored, so a question holding a
        credential still finds the case asking it.
        """
        dataset = await self.get(ctx, dataset_id)
        held = await self._version(ctx, dataset, version)
        if held is None:
            return DatasetCaseList(items=[], total=0, version=0)
        cases = await dataset_repo.list_cases(
            self.db,
            held.id,
            organization_id=ctx.organization_id,
            skip=skip,
            limit=limit,
            same_input=redact_credentials(same_input)[0],
        )
        total = held.case_count if same_input is None else len(cases)
        return DatasetCaseList(
            items=[_case_read(case) for case in cases], total=total, version=held.number
        )

    async def _mint(
        self,
        ctx: AuthContext,
        dataset: Dataset,
        *,
        change: DatasetChange,
        previous: DatasetVersion | None,
        added: list[DatasetCase] | None = None,
        replaced: tuple[DatasetCase, DatasetCase, int] | None = None,
        removed: DatasetCase | None = None,
        redacted: int = 0,
    ) -> DatasetVersion:
        """Write the next version: the previous one's cases, with this change applied.

        The caller holds the dataset's row lock (:func:`dataset_repo.lock`) and
        read `previous` under it, so the number minted and the revisions closed
        are the ones no other edit can have moved. Nothing is copied: the new
        revisions are placed in this version, and the ones it leaves out are
        closed at it, which no earlier version can see.

        Args:
            added: New revisions, appended after the last case in order.
            replaced: `(old, new, position)` - an edit, kept where the old one was.
            removed: The revision a deletion leaves out.

        Raises:
            BadRequestError: When the change would take the dataset past
                :data:`MAX_CASES`, or the organization past
                `DATASET_MAX_VERSION_ROWS_PER_ORG` stored case revisions.
        """
        added = added or []
        before = previous.case_count if previous is not None else 0
        count = before + len(added) - (1 if removed is not None else 0)
        number = dataset.latest_version + 1
        _refuse_past_ceiling(before, len(added))
        new_revisions = [*added, *([replaced[1]] if replaced is not None else [])]
        if new_revisions:
            # Held to the commit, before counting: the dataset's own lock does not
            # stop an edit of another dataset reading the same count.
            await hold_subject(
                self.db, LockScope.DATASET_REVISIONS_PER_ORGANIZATION, ctx.organization_id
            )
            _refuse_past_storage(
                await dataset_repo.stored_revisions(self.db, organization_id=ctx.organization_id),
                len(new_revisions),
            )
        next_position = (
            await dataset_repo.last_position(
                self.db, previous.id, organization_id=ctx.organization_id
            )
            + 1
            if previous is not None
            else 0
        )
        if replaced is not None:
            replaced[1].position = replaced[2]
        for index, case in enumerate(added):
            case.position = next_position + index
        for revision in new_revisions:
            revision.added_in = number
        if new_revisions:
            await dataset_repo.add_cases(self.db, new_revisions)
        await dataset_repo.close_revisions(
            self.db,
            [case.id for case in (removed, replaced[0] if replaced else None) if case],
            organization_id=ctx.organization_id,
            at=number,
        )

        version = await dataset_repo.create_version(
            self.db,
            dataset_id=dataset.id,
            organization_id=ctx.organization_id,
            number=number,
            case_count=count,
            change=change.value,
            changed_cases=len(added) + (1 if replaced or removed else 0),
            created_by_user_id=ctx.subject_id,
        )

        await dataset_repo.update(
            self.db,
            dataset=dataset,
            update_data={
                "latest_version": version.number,
                "case_count": count,
            },
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="dataset.version_created",
            target_type="dataset",
            target_id=str(dataset.id),
            details={
                "name": dataset.name,
                "version": version.number,
                "change": change.value,
                "changed_cases": version.changed_cases,
                "redacted_secrets": redacted,
            },
        )
        return version

    async def _locked(self, ctx: AuthContext, dataset_id: UUID) -> Dataset:
        """The dataset locked for minting, once the caller is known to may edit it."""
        dataset = await dataset_repo.lock(self.db, dataset_id, organization_id=ctx.organization_id)
        if dataset is None or not await self._can_edit(ctx, dataset):
            raise NotFoundError(message="Dataset not found", details={"dataset_id": dataset_id})
        return dataset

    def _revision(
        self,
        ctx: AuthContext,
        dataset: Dataset,
        fields: dict[str, Any],
        *,
        source: CaseSource,
        case_id: UUID | None = None,
        **provenance: UUID | None,
    ) -> DatasetCase:
        return DatasetCase(
            id=uuid.uuid4(),
            dataset_id=dataset.id,
            organization_id=ctx.organization_id,
            case_id=case_id or uuid.uuid4(),
            source=source.value,
            created_by_user_id=ctx.subject_id,
            **fields,
            **provenance,
        )

    async def _add(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        content: DatasetCaseContent,
        *,
        source: CaseSource,
        **provenance: UUID | None,
    ) -> DatasetCaseRead:
        dataset = await self._locked(ctx, dataset_id)
        previous = await self._version(ctx, dataset, None)
        message_id = provenance.get("source_message_id")
        if message_id is not None and previous is not None:
            # Checked again under the lock: two requests for the same answer
            # both pass the check made before it, and the second would add a twin.
            await self._refuse_held_answer(ctx, previous, message_id)
        fields, redacted = redacted_case(content)
        case = self._revision(ctx, dataset, fields, source=source, **provenance)
        await self._mint(
            ctx,
            dataset,
            change=DatasetChange.ADD,
            previous=previous,
            added=[case],
            redacted=redacted,
        )
        return _case_read(case)

    async def add_case(
        self, ctx: AuthContext, dataset_id: UUID, data: DatasetCaseContent
    ) -> DatasetCaseRead:
        """Add a case written by hand, as a new version."""
        return await self._add(ctx, dataset_id, data, source=CaseSource.MANUAL)

    async def lock_for_edit(self, ctx: AuthContext, dataset_id: UUID) -> Dataset:
        """The dataset, locked until the transaction ends, for a caller who may edit it.

        For work that must read something under the same lock a version is
        minted under, before handing what it read to :meth:`add_generated`.

        Raises:
            NotFoundError: As :meth:`get` does, for a dataset the caller may not edit.
        """
        return await self._locked(ctx, dataset_id)

    async def add_generated(
        self, ctx: AuthContext, dataset: Dataset, cases: list[GeneratedCase]
    ) -> DatasetVersionRead:
        """Add generated cases a person accepted, as one new version.

        `dataset` comes from :meth:`lock_for_edit` in this transaction. Every case
        is redacted again on the way in, because a reviewer may have edited it.
        """
        previous = await self._version(ctx, dataset, None)
        revisions: list[DatasetCase] = []
        redacted = 0
        for case in cases:
            fields, found = redacted_case(case.content)
            redacted += found
            revisions.append(
                self._revision(
                    ctx,
                    dataset,
                    fields,
                    source=CaseSource.SYNTHETIC,
                    source_document_id=case.source_document_id,
                    source_run_id=case.source_run_id,
                    source_conversation_id=case.source_conversation_id,
                    source_message_id=case.source_message_id,
                )
            )
        version = await self._mint(
            ctx,
            dataset,
            change=DatasetChange.GENERATE,
            previous=previous,
            added=revisions,
            redacted=redacted,
        )
        return _version_read(version)

    async def _held_case(
        self, ctx: AuthContext, dataset: Dataset, case_id: UUID
    ) -> tuple[DatasetVersion, DatasetCase, int]:
        previous = await self._version(ctx, dataset, None)
        found = (
            await dataset_repo.find_case(
                self.db, previous.id, case_id, organization_id=ctx.organization_id
            )
            if previous is not None
            else None
        )
        if previous is None or found is None:
            raise NotFoundError(
                message="The dataset's newest version holds no such case",
                details={"dataset_id": dataset.id, "case_id": case_id},
            )
        return previous, found[0], found[1]

    async def read_case(
        self, ctx: AuthContext, dataset_id: UUID, case_id: UUID, *, version: int | None = None
    ) -> DatasetCaseRead:
        """One case as a version holds it - the newest unless one is named. Needs
        `datasets:view` on the dataset.

        Raises:
            NotFoundError: The dataset is not one the caller may read, or the
                version does not hold the case.
        """
        dataset = await self.get(ctx, dataset_id)
        return _case_read(await self.case_at(ctx, dataset, case_id, version=version))

    async def case_at(
        self, ctx: AuthContext, dataset: Dataset, case_id: UUID, *, version: int | None = None
    ) -> DatasetCase:
        """The revision of a case a version holds - the newest version unless one is named.

        Raises:
            NotFoundError: When that version does not exist or does not hold the case.
        """
        held = await self._version(ctx, dataset, version)
        found = (
            None
            if held is None
            else await dataset_repo.find_case(
                self.db, held.id, case_id, organization_id=ctx.organization_id
            )
        )
        if found is None:
            raise NotFoundError(
                message="This version of the dataset holds no such case",
                details={"dataset_id": dataset.id, "case_id": case_id, "version": version},
            )
        return found[0]

    async def update_case(
        self, ctx: AuthContext, dataset_id: UUID, case_id: UUID, data: DatasetCaseUpdate
    ) -> DatasetCaseRead:
        """Edit a case. The edit is a new revision in a new version; the old one stays readable."""
        dataset = await self._locked(ctx, dataset_id)
        previous, current, position = await self._held_case(ctx, dataset, case_id)
        merged = {
            **DatasetCaseRead.model_validate(current).model_dump(),
            **writable(data, over=DatasetCase),
        }
        # Each half is valid alone, but an edit clearing the only expectation the
        # stored case had leaves a union that is not.
        try:
            content = EditedCaseContent.model_validate(
                {key: merged[key] for key in DatasetCaseContent.model_fields}
            )
        except ValidationError as exc:
            raise InvalidCaseError(
                message="This edit leaves a case that is not valid",
                details={"fields": field_problems(exc.errors(), root="")},
            ) from None
        fields, redacted = redacted_case(content)
        provenance = {
            "source_run_id": current.source_run_id,
            "source_conversation_id": current.source_conversation_id,
            "source_message_id": current.source_message_id,
            "source_document_id": current.source_document_id,
        }
        revision = self._revision(
            ctx,
            dataset,
            fields,
            source=CaseSource(current.source),
            case_id=current.case_id,
            **provenance,
        )
        await self._mint(
            ctx,
            dataset,
            change=DatasetChange.EDIT,
            previous=previous,
            replaced=(current, revision, position),
            redacted=redacted,
        )
        return _case_read(revision)

    async def remove_case(self, ctx: AuthContext, dataset_id: UUID, case_id: UUID) -> None:
        """Leave a case out of a new version. The versions that held it still do."""
        dataset = await self._locked(ctx, dataset_id)
        previous, current, _ = await self._held_case(ctx, dataset, case_id)
        await self._mint(
            ctx, dataset, change=DatasetChange.REMOVE, previous=previous, removed=current
        )

    async def import_cases(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        *,
        content: bytes,
        filename: str | None,
        fmt: DatasetFileFormat | None,
    ) -> DatasetVersionRead:
        """Append every case in a CSV or JSONL file, as one new version.

        The file is parsed, measured against the ceiling and redacted before the
        dataset is locked, so a large upload holds up nobody else's edit; and it is
        refused whole if any row is wrong (see :func:`dataset_files.parse`). The
        ceiling is checked again under the lock, against the count it guards.
        """
        current = await self.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        cases = dataset_files.parse(content, dataset_files.format_of(filename, fmt))
        _refuse_past_ceiling(current.case_count, len(cases))
        revisions: list[DatasetCase] = []
        redacted = 0
        for case in cases:
            fields, found = redacted_case(case)
            redacted += found
            revisions.append(self._revision(ctx, current, fields, source=CaseSource.IMPORT))
        dataset = await self._locked(ctx, dataset_id)
        previous = await self._version(ctx, dataset, None)
        version = await self._mint(
            ctx,
            dataset,
            change=DatasetChange.IMPORT,
            previous=previous,
            added=revisions,
            redacted=redacted,
        )
        return _version_read(version)

    async def export(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        *,
        version: int | None,
        fmt: DatasetFileFormat,
    ) -> ExportResult:
        """One version's cases as a file that imports back unchanged.

        Audited like every bulk export: a dataset's cases are often copied from
        real conversations, and who took a copy of them away is worth recording.
        """
        dataset = await self.get(ctx, dataset_id)
        held = await self._version(ctx, dataset, version)
        cases = (
            await dataset_repo.list_cases(
                self.db, held.id, organization_id=ctx.organization_id, limit=None
            )
            if held is not None
            else []
        )
        content = dataset_files.render(cases, fmt)
        number = held.number if held is not None else 0
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="dataset.exported",
            target_type="dataset",
            target_id=str(dataset.id),
            details={"version": number, "format": fmt, "row_count": len(cases)},
        )
        return ExportResult(
            content=content,
            filename=stamp(f"dataset_v{number}", datetime.now(UTC), fmt),
            row_count=len(cases),
        )

    async def add_from_message(
        self, ctx: AuthContext, dataset_id: UUID, data: DatasetCaseFromMessage
    ) -> DatasetCaseRead:
        """Turn an agent's answer into a case: the question, the turns before it, the answer.

        `with_history` false leaves the turns before the question out, for a
        question that stands on its own in a conversation that was about more.

        The answer is the agent's whole reply to the question - every step it
        wrote before the next question, whichever of them `message_id` names.
        Its text becomes the counter-example (or the reference answer, when
        somebody is keeping a good one), and a good one's tool calls become the
        calls the case expects, by tool name - those that succeeded and that
        change something, so a mistaken call and a read are not asked for again. The newest comment left with a
        thumbs-down on the reply becomes the note, and the case keeps a link to
        the run, the conversation and the reply's last step.

        The source is checked like any read of a transcript: it must be in the
        caller's organization, and the caller must hold `runs:view` (which reads
        every run in it, as Activity does) or be able to open the conversation.

        Raises:
            NotFoundError: For a message that is not there, is in another
                organization, or is in a conversation the caller may not read.
            BadRequestError: For a message that is not an agent's answer, one
                with nothing to keep - no text, nor for a reference a tool call -
                or one with no question before it.
            AlreadyExistsError: The dataset's newest version already holds a
                case made from this answer.
        """
        dataset = await self.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        content, provenance = await self._case_from_message(
            ctx, dataset, data.message_id, data.answer_as, with_history=data.with_history
        )
        return await self._add(
            ctx, dataset_id, content, source=CaseSource.CONVERSATION, **provenance
        )

    async def _case_from_message(
        self,
        ctx: AuthContext,
        dataset: Dataset,
        message_id: UUID,
        answer_as: AnswerAs,
        *,
        with_history: bool = True,
    ) -> tuple[DatasetCaseContent, dict[str, UUID | None]]:
        """The case an agent's answer makes, and the links back to where it came from.

        Raises as :meth:`add_from_message` documents.
        """
        missing = NotFoundError(message="Message not found", details={"message_id": message_id})
        message = await conversation_repo.get_message_by_id(self.db, message_id)
        if message is None:
            raise missing
        reads_every_run = ctx.scope_for(Perm.RUNS_VIEW) >= Scope.ALL
        try:
            conversation = await ConversationService(self.db).get_conversation(
                message.conversation_id,
                organization_id=ctx.organization_id,
                user_id=None if reads_every_run else ctx.subject_id,
                include_favourite=False,
                ctx=ctx,
            )
        except NotFoundError:
            # One answer for a message that is not there and one the caller may
            # not reach, so the refusal cannot tell them which.
            raise missing from None
        if message.role != "assistant":
            raise refused_field("message_id", "Only an agent's answer can be added to a dataset")
        before = await conversation_repo.get_messages_before(
            self.db,
            conversation.id,
            organization_id=ctx.organization_id,
            ordinal=message.ordinal,
            limit=MAX_HISTORY_TURNS + _MAX_REPLY_STEPS + 1,
        )
        after = await conversation_repo.get_messages_following(
            self.db,
            conversation.id,
            organization_id=ctx.organization_id,
            ordinal=message.ordinal,
            limit=_MAX_REPLY_STEPS,
        )
        asking = len(before)
        while asking > 0 and before[asking - 1].role == "assistant":
            asking -= 1
        reply = [
            *before[asking:],
            message,
            *takewhile(lambda turn: turn.role == "assistant", after),
        ]
        last = reply[-1]
        answer = "\n\n".join(turn.content.strip() for turn in reply if turn.content.strip())
        keeps_good = answer_as == "reference_answer"
        calls = (
            await self._expected_calls(ctx, last.run_id or message.run_id, reply)
            if keeps_good
            else []
        )
        if not answer and not calls:
            raise refused_field(
                "message_id",
                "This answer has no text, nor a tool call that changed something, to keep as a case"
                if keeps_good
                else "This answer has no text to keep as a counter-example; keep it as a "
                "reference answer to expect the tools it called",
            )
        newest = await self._version(ctx, dataset, None)
        if newest is not None:
            await self._refuse_held_answer(ctx, newest, last.id)

        earlier = [
            turn
            for turn in before[:asking]
            if turn.role in ("user", "assistant") and turn.content.strip()
        ]
        asked = next(
            (index for index in range(len(earlier) - 1, -1, -1) if earlier[index].role == "user"),
            None,
        )
        if asked is None:
            raise refused_field("message_id", "This answer has no question before it to test on")
        comments = await message_rating_repo.get_down_rating_comments_for_messages(
            self.db, message_ids=[turn.id for turn in reply]
        )
        try:
            content = DatasetCaseContent(
                input=earlier[asked].content,
                history=[
                    {"role": turn.role, "content": turn.content}
                    for turn in earlier[:asked][-MAX_HISTORY_TURNS:]
                ]
                if with_history
                else [],
                counter_example=None if keeps_good else answer,
                reference_answer=(answer or None) if keeps_good else None,
                expected_tool_calls=[
                    ExpectedToolCall(tool=name) for name in calls[:_MAX_EXPECTED_CALLS]
                ],
                note=next(
                    (comments[turn.id] for turn in reversed(reply) if turn.id in comments), None
                ),
            )
        except ValidationError as exc:
            raise BadRequestError(
                message="This conversation is too long to keep as a case",
                details={"fields": field_problems(exc.errors(), root="message_id")},
            ) from None
        return content, {
            "source_run_id": last.run_id or message.run_id,
            "source_conversation_id": conversation.id,
            "source_message_id": last.id,
        }

    async def _refuse_held_answer(
        self, ctx: AuthContext, version: DatasetVersion, message_id: UUID
    ) -> None:
        kept = await dataset_repo.case_from_message(
            self.db, version.id, message_id, organization_id=ctx.organization_id
        )
        if kept is not None:
            raise AlreadyExistsError(
                message="This answer is already a case of this dataset",
                details={"case_id": kept.case_id},
            )

    async def add_from_messages(
        self,
        ctx: AuthContext,
        dataset_id: UUID,
        message_ids: list[UUID],
        *,
        answer_as: AnswerAs | Mapping[UUID, AnswerAs] = "counter_example",
        with_history: bool = True,
    ) -> tuple[DatasetVersionRead | None, int]:
        """Add several agents' answers as cases, in one new version.

        `answer_as` is one for every answer, or each answer's own by its id - a
        good answer kept as the reference beside a bad one kept as the
        counter-example, still in one version; an id it does not name is kept
        as a counter-example. `with_history` false leaves out the turns before
        each question.

        Each answer is built and checked as :meth:`add_from_message` builds and
        checks one. An answer the caller may not read - absent, in another
        organization or in a conversation they cannot open, all counted alike -
        or one with no question before it, is skipped rather than refusing the
        rest, as is a reply the dataset already holds or the batch named twice. Measured against the ceiling and redacted before the dataset is
        locked, as :meth:`import_cases` is.

        Returns:
            The version the cases were added in - `None` when none could be -
            and how many answers were skipped.

        Raises:
            NotFoundError: For a dataset the caller may not edit.
            BadRequestError: When the cases would take the dataset past
                :data:`MAX_CASES`.
        """
        current = await self.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        built: list[tuple[DatasetCaseContent, dict[str, UUID | None]]] = []
        replies: set[UUID | None] = set()
        for message_id in message_ids:
            kept_as = (
                answer_as.get(message_id, "counter_example")
                if isinstance(answer_as, Mapping)
                else answer_as
            )
            try:
                case = await self._case_from_message(
                    ctx, current, message_id, kept_as, with_history=with_history
                )
            except NotFoundError, BadRequestError, AlreadyExistsError:
                continue
            if case[1]["source_message_id"] in replies:
                continue
            replies.add(case[1]["source_message_id"])
            built.append(case)
        skipped = len(message_ids) - len(built)
        if not built:
            return None, skipped
        _refuse_past_ceiling(current.case_count, len(built))
        redacted_revisions: list[tuple[DatasetCase, int]] = []
        for content, provenance in built:
            fields, found = redacted_case(content)
            redacted_revisions.append(
                (
                    self._revision(
                        ctx, current, fields, source=CaseSource.CONVERSATION, **provenance
                    ),
                    found,
                )
            )
        dataset = await self._locked(ctx, dataset_id)
        previous = await self._version(ctx, dataset, None)
        # A request that added one of these answers since the check above held
        # this lock first; its case stands and the twin is skipped.
        held = (
            set()
            if previous is None
            else await dataset_repo.messages_held(
                self.db,
                previous.id,
                [
                    case.source_message_id
                    for case, _ in redacted_revisions
                    if case.source_message_id
                ],
                organization_id=ctx.organization_id,
            )
        )
        revisions = [case for case, _ in redacted_revisions if case.source_message_id not in held]
        redacted = sum(
            found for case, found in redacted_revisions if case.source_message_id not in held
        )
        skipped += len(redacted_revisions) - len(revisions)
        if not revisions:
            return None, skipped
        version = await self._mint(
            ctx,
            dataset,
            change=DatasetChange.ADD,
            previous=previous,
            added=revisions,
            redacted=redacted,
        )
        return _version_read(version), skipped

    async def _expected_calls(
        self, ctx: AuthContext, run_id: UUID | None, reply: list[Message]
    ) -> list[str]:
        """The tools a good reply called that a case should expect: those that succeeded
        and that the answering agent's spec does not declare read-only."""
        calls = await conversation_repo.tool_calls_of_messages(self.db, [turn.id for turn in reply])
        reads: set[str] = set()
        run = (
            None
            if run_id is None
            else await agent_run_repo.get_run(self.db, run_id, organization_id=ctx.organization_id)
        )
        if run is not None and run.agent_version_id is not None:
            version = await agent_repo.get_version(
                self.db, run.agent_version_id, organization_id=ctx.organization_id
            )
            if version is not None:
                tools = capability_tools(AgentSpec.model_validate(version.spec))
                reads = {name for name, tool in tools.items() if tool.read_only}
        return [
            call.tool_name
            for call in calls
            if call.status == "completed" and call.tool_name not in reads
        ]
