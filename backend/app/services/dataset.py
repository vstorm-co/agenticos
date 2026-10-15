"""Datasets - the questions an agent is tested on, as versioned cases.

This module owns storage, access and versioning. Every change to a dataset's
cases goes through :meth:`DatasetService._mint`, which writes the next version
under a lock on the dataset row; nothing else writes a version, so "every change
mints a version" is a property of one method rather than of every caller.

Case text is copied from conversations and from files people upload, and it is
then exported and handed to models. A credential in it is redacted before the
case is stored, on every way in.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from pydantic import JsonValue, ValidationError
from pydantic_ai_harness.guardrails.detectors import redact_secrets
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.system_agents import JUDGE
from app.core.audit import record_audit
from app.core.config import settings
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.exceptions import ValidationError as InvalidCaseError
from app.core.field_errors import field_problems, refused_field
from app.core.permissions import AuthContext, Perm, Scope
from app.db.models.dataset import CaseSource, Dataset, DatasetCase, DatasetChange, DatasetVersion
from app.db.updates import writable
from app.repositories import (
    agent_repo,
    conversation_repo,
    dataset_repo,
    message_rating_repo,
    resource_grant_repo,
)
from app.schemas.dataset import (
    MAX_HISTORY_TURNS,
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
from app.schemas.scoring import DatasetScoring
from app.services import dataset_files
from app.services.access import DATASET, accessible_ids, resolve_access, visible_resource_ids
from app.services.conversation import ConversationService
from app.services.exporting import MAX_EXPORT_ROWS, ExportResult, stamp

logger = logging.getLogger(__name__)

# The most cases one dataset holds. The export cap, so every version of every
# dataset can always be exported whole.
MAX_CASES = MAX_EXPORT_ROWS


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


def _refuse_past_storage(used: int, adding: int) -> None:
    """Refuse a version that would take the organization past its stored case rows.

    Raises:
        BadRequestError: Naming how many rows are held, how many this version
            adds and the ceiling, and what to do about it.
    """
    ceiling = settings.DATASET_MAX_VERSION_ROWS_PER_ORG
    if used + adding > ceiling:
        raise BadRequestError(
            message=(
                f"This organization's datasets hold {used:,} cases across their versions, "
                f"and this change would add {adding:,} more; the limit is {ceiling:,}. "
                "Delete datasets you no longer need, or ask the deployment's "
                "administrator to raise DATASET_MAX_VERSION_ROWS_PER_ORG."
            ),
            details={"version_rows": used, "adding": adding, "max_version_rows": ceiling},
        )


def _redact(text: str | None) -> tuple[str | None, int]:
    """The text with any credential replaced by a placeholder, and how many were."""
    if not text:
        return text, 0
    verdict = redact_secrets(text)
    if verdict.action != "replace" or not isinstance(verdict.replacement, str):
        return text, 0
    return verdict.replacement, verdict.replacement.count("[redacted:")


def _redact_json(value: JsonValue) -> tuple[JsonValue, int]:
    if isinstance(value, str):
        cleaned, found = _redact(value)
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


def _redacted(content: DatasetCaseContent) -> tuple[dict[str, Any], int]:
    """A case's fields ready for its row, with every credential in them redacted.

    Everything a model is later handed or a person exports: the turns, the
    answers, the note, the tags, the arguments an expected tool call is matched
    on and every parameter of a check. A check's `type` is left alone, because it
    names the rule rather than holding anything somebody wrote.
    """
    data = content.model_dump(mode="json")
    found = 0
    for field in ("input", "reference_answer", "counter_example", "note"):
        data[field], count = _redact(data[field])
        found += count
    for turn in data["history"]:
        turn["content"], count = _redact(turn["content"])
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
    judge_name: str | None,
    stats: DatasetStats | None = None,
) -> DatasetRead:
    return DatasetRead(
        stats=stats or DatasetStats(),
        judge_name=judge_name,
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        visibility=as_visibility(dataset.visibility),
        owner_user_id=dataset.owner_user_id,
        latest_version=dataset.latest_version,
        case_count=dataset.case_count,
        can_edit=can_edit,
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
        stats = await self._stats(ctx, [dataset])
        judges = await self._judge_names(ctx, [dataset])
        return _dataset_read(
            dataset,
            can_edit=await self._can_edit(ctx, dataset),
            judge_name=judges.get(dataset.id),
            stats=stats.get(dataset.id),
        )

    async def list_readable(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        editable: bool = False,
        search: str | None = None,
        judge_id: UUID | None = None,
        sort: DatasetSort = "name",
        skip: int = 0,
        limit: int = 50,
    ) -> DatasetList:
        """A page of the datasets this caller may see, each saying whether they may edit it.

        `judge_id` narrows to the datasets that judge grades: those that picked
        it, and for the seeded default judge those that picked none.

        Scoped like every shared resource: a role reaching the whole organization
        lists everything, anyone else their own, the org-visible ones and those
        shared with them - the set :func:`resolve_access` admits one row at a
        time. `can_edit` costs one grant query for the page, not one per row.
        """
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
        items, total = await dataset_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=grant_ids,
            shared_with_me=shared_with_me,
            edit_scope=ctx.scope_for(Perm.DATASETS_EDIT) if editable else None,
            edit_ids=edit_ids,
            search=search,
            judge_id=judge_id,
            judge_is_default=judge_id is not None and await self._is_default_judge(ctx, judge_id),
            sort=sort,
            skip=skip,
            limit=limit,
        )
        may_edit = await accessible_ids(
            self.db, ctx, items, Perm.DATASETS_EDIT, resource_type=DATASET
        )
        stats = await self._stats(ctx, items)
        judges = await self._judge_names(ctx, items)
        return DatasetList(
            items=[
                _dataset_read(
                    item,
                    can_edit=item.id in may_edit,
                    judge_name=judges.get(item.id),
                    stats=stats.get(item.id),
                )
                for item in items
            ],
            total=total,
        )

    async def _is_default_judge(self, ctx: AuthContext, agent_id: UUID) -> bool:
        default = await agent_repo.get_system(
            self.db, organization_id=ctx.organization_id, key=JUDGE.key
        )
        return default is not None and default.id == agent_id

    async def _refuse_taken_name(self, ctx: AuthContext, name: str) -> None:
        if await dataset_repo.get_by_name(self.db, name, organization_id=ctx.organization_id):
            raise _name_taken(name)

    async def create(self, ctx: AuthContext, data: DatasetCreate) -> DatasetRead:
        """An empty dataset, private to its creator until it is shared."""
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
        """Delete a dataset with every version and case it held."""
        dataset = await self.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        name = dataset.name
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
    ) -> DatasetCaseList:
        """A page of the cases one version holds - the newest version unless one is named."""
        dataset = await self.get(ctx, dataset_id)
        held = await self._version(ctx, dataset, version)
        if held is None:
            return DatasetCaseList(items=[], total=0, version=0)
        cases = await dataset_repo.list_cases(
            self.db, held.id, organization_id=ctx.organization_id, skip=skip, limit=limit
        )
        return DatasetCaseList(
            items=[_case_read(case) for case in cases], total=held.case_count, version=held.number
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
        read `previous` under it, so the number and the membership copied are
        the ones no other edit can have moved.

        Args:
            added: New revisions, appended after the last case in order.
            replaced: `(old, new, position)` - an edit, kept where the old one was.
            removed: The revision a deletion leaves out.

        Raises:
            BadRequestError: When the change would take the dataset past
                :data:`MAX_CASES`, or the organization past
                `DATASET_MAX_VERSION_ROWS_PER_ORG` stored case rows.
        """
        added = added or []
        before = previous.case_count if previous is not None else 0
        count = before + len(added) - (1 if removed is not None else 0)
        _refuse_past_ceiling(before, len(added))
        _refuse_past_storage(
            await dataset_repo.version_rows(self.db, organization_id=ctx.organization_id), count
        )
        new_revisions = [*added, *([replaced[1]] if replaced is not None else [])]
        if new_revisions:
            await dataset_repo.add_cases(self.db, new_revisions)

        version = await dataset_repo.create_version(
            self.db,
            dataset_id=dataset.id,
            organization_id=ctx.organization_id,
            number=dataset.latest_version + 1,
            case_count=count,
            change=change.value,
            changed_cases=len(added) + (1 if replaced or removed else 0),
            created_by_user_id=ctx.subject_id,
        )
        placements: list[tuple[UUID, int]] = []
        next_position = 0
        if previous is not None:
            skip = {case.id for case in (removed, replaced[0] if replaced else None) if case}
            await dataset_repo.copy_membership(
                self.db,
                organization_id=ctx.organization_id,
                source_version_id=previous.id,
                target_version_id=version.id,
                skip=skip,
            )
            next_position = (
                await dataset_repo.last_position(
                    self.db, previous.id, organization_id=ctx.organization_id
                )
                + 1
            )
        if replaced is not None:
            placements.append((replaced[1].id, replaced[2]))
        placements.extend((case.id, next_position + index) for index, case in enumerate(added))
        await dataset_repo.add_membership(self.db, version_id=version.id, placements=placements)

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
        fields, redacted = _redacted(content)
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
        fields, redacted = _redacted(content)
        provenance = {
            "source_run_id": current.source_run_id,
            "source_conversation_id": current.source_conversation_id,
            "source_message_id": current.source_message_id,
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
            fields, found = _redacted(case)
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

        The answer becomes the counter-example (or the reference answer, when
        somebody is keeping a good one), the newest comment left with a thumbs-down
        on it becomes the note, and the case keeps a link to the run, the
        conversation and the message it came from.

        The source is checked like any read of a transcript: it must be in the
        caller's organization, and the caller must hold `runs:view` (which reads
        every run in it, as Activity does) or be able to open the conversation.

        Raises:
            NotFoundError: For a message that is not there, is in another
                organization, or is in a conversation the caller may not read.
            BadRequestError: For a message that is not an agent's answer, or that
                has no question before it.
        """
        await self.get(ctx, dataset_id, perm=Perm.DATASETS_EDIT)
        missing = NotFoundError(
            message="Message not found", details={"message_id": data.message_id}
        )
        message = await conversation_repo.get_message_by_id(self.db, data.message_id)
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
        if not message.content.strip():
            raise refused_field("message_id", "This answer has no text to keep as a case")

        earlier = [
            turn
            for turn in await conversation_repo.get_messages_before(
                self.db,
                conversation.id,
                organization_id=ctx.organization_id,
                ordinal=message.ordinal,
                limit=MAX_HISTORY_TURNS + 1,
            )
            if turn.role in ("user", "assistant") and turn.content.strip()
        ]
        asked = next(
            (index for index in range(len(earlier) - 1, -1, -1) if earlier[index].role == "user"),
            None,
        )
        if asked is None:
            raise refused_field("message_id", "This answer has no question before it to test on")
        comments = await message_rating_repo.get_down_rating_comments_for_messages(
            self.db, message_ids=[message.id]
        )
        answer = message.content
        try:
            content = DatasetCaseContent(
                input=earlier[asked].content,
                history=[
                    {"role": turn.role, "content": turn.content}
                    for turn in earlier[:asked][-MAX_HISTORY_TURNS:]
                ],
                counter_example=answer if data.answer_as == "counter_example" else None,
                reference_answer=answer if data.answer_as == "reference_answer" else None,
                note=comments.get(message.id),
            )
        except ValidationError as exc:
            raise BadRequestError(
                message="This conversation is too long to keep as a case",
                details={"fields": field_problems(exc.errors(), root="message_id")},
            ) from None
        return await self._add(
            ctx,
            dataset_id,
            content,
            source=CaseSource.CONVERSATION,
            source_run_id=message.run_id,
            source_conversation_id=conversation.id,
            source_message_id=message.id,
        )
