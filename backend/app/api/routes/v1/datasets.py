"""Dataset routes - the versioned test cases an agent's evals run over.

Routes acting on the collection carry a `require(...)` gate; routes acting on
one dataset deliberately do not, and delegate to `DatasetService`, which
resolves the caller's access to that row - a role gate cannot see the grant
that lets a Viewer edit one shared dataset.

Every route that changes a dataset's cases answers with what the change
created, and the change is a new version: the version before it stays readable
under `?version=`.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import Auth, DatasetSvc, require
from app.api.responses import csv_response, jsonl_response
from app.core.permissions import Perm
from app.schemas.dataset import (
    DatasetCaseCreate,
    DatasetCaseFromMessage,
    DatasetCaseList,
    DatasetCaseRead,
    DatasetCaseUpdate,
    DatasetCreate,
    DatasetFileFormat,
    DatasetList,
    DatasetRead,
    DatasetSort,
    DatasetUpdate,
    DatasetVersionList,
    DatasetVersionRead,
)
from app.services.dataset_files import MAX_IMPORT_BYTES

router = APIRouter()


@router.get("", response_model=DatasetList, dependencies=[Depends(require(Perm.DATASETS_VIEW))])
async def list_datasets(
    service: DatasetSvc,
    ctx: Auth,
    q: str | None = Query(None, max_length=100, description="Match on name or description"),
    sort: DatasetSort = Query("name", description="`name` A-Z, or `updated` newest change first"),
    shared_with_me: bool = Query(
        False, description="Only what was shared with the caller - never their own rows"
    ),
    editable: bool = Query(
        False, description="Only the datasets the caller may change, by role or by a grant"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The datasets the caller may see, each with its newest version and case count."""
    return await service.list_readable(
        ctx,
        shared_with_me=shared_with_me,
        editable=editable,
        search=q,
        sort=sort,
        skip=skip,
        limit=limit,
    )


@router.post(
    "",
    response_model=DatasetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require(Perm.DATASETS_EDIT))],
)
async def create_dataset(data: DatasetCreate, service: DatasetSvc, ctx: Auth) -> Any:
    """An empty dataset, private to its creator. Its first case makes version 1."""
    return await service.create(ctx, data)


@router.get("/{dataset_id}", response_model=DatasetRead)
async def get_dataset(dataset_id: UUID, service: DatasetSvc, ctx: Auth) -> Any:
    return await service.read(ctx, dataset_id)


@router.patch("/{dataset_id}", response_model=DatasetRead)
async def update_dataset(
    dataset_id: UUID, data: DatasetUpdate, service: DatasetSvc, ctx: Auth
) -> Any:
    """Rename or redescribe a dataset. Not a new version: no case changes."""
    return await service.update(ctx, dataset_id, data)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_dataset(dataset_id: UUID, service: DatasetSvc, ctx: Auth) -> None:
    await service.delete(ctx, dataset_id)


@router.get("/{dataset_id}/versions", response_model=DatasetVersionList)
async def list_dataset_versions(
    dataset_id: UUID,
    service: DatasetSvc,
    ctx: Auth,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """Every version of the dataset, newest first, with what each one changed."""
    return await service.list_versions(ctx, dataset_id, skip=skip, limit=limit)


@router.get("/{dataset_id}/cases", response_model=DatasetCaseList)
async def list_dataset_cases(
    dataset_id: UUID,
    service: DatasetSvc,
    ctx: Auth,
    version: int | None = Query(None, ge=1, description="A version number; the newest if omitted"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """A page of the cases one version holds, in their order."""
    return await service.list_cases(ctx, dataset_id, version=version, skip=skip, limit=limit)


@router.post(
    "/{dataset_id}/cases", response_model=DatasetCaseRead, status_code=status.HTTP_201_CREATED
)
async def add_dataset_case(
    dataset_id: UUID, data: DatasetCaseCreate, service: DatasetSvc, ctx: Auth
) -> Any:
    """Add a case written by hand. Creates the next version."""
    return await service.add_case(ctx, dataset_id, data)


@router.post(
    "/{dataset_id}/cases/from-message",
    response_model=DatasetCaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_dataset_case_from_message(
    dataset_id: UUID, data: DatasetCaseFromMessage, service: DatasetSvc, ctx: Auth
) -> Any:
    """Add to dataset: an agent's answer, with the question and the turns before it.

    The answer is kept as the counter-example unless `answer_as` says it is the
    reference answer, and the newest thumbs-down comment on it becomes the note.
    """
    return await service.add_from_message(ctx, dataset_id, data)


@router.patch("/{dataset_id}/cases/{case_id}", response_model=DatasetCaseRead)
async def update_dataset_case(
    dataset_id: UUID, case_id: UUID, data: DatasetCaseUpdate, service: DatasetSvc, ctx: Auth
) -> Any:
    """Edit a case in the newest version. The edit is a new version; the old one is kept."""
    return await service.update_case(ctx, dataset_id, case_id, data)


@router.delete(
    "/{dataset_id}/cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def remove_dataset_case(
    dataset_id: UUID, case_id: UUID, service: DatasetSvc, ctx: Auth
) -> None:
    """Leave a case out of the next version. Earlier versions still hold it."""
    await service.remove_case(ctx, dataset_id, case_id)


@router.post(
    "/{dataset_id}/import",
    response_model=DatasetVersionRead,
    status_code=status.HTTP_201_CREATED,
)
async def import_dataset_cases(
    dataset_id: UUID,
    service: DatasetSvc,
    ctx: Auth,
    file: UploadFile = File(..., description="A .csv or .jsonl file of cases"),
    fmt: DatasetFileFormat | None = Query(
        None, alias="format", description="Override the format the file's extension implies"
    ),
) -> Any:
    """Append every case in a CSV or JSONL file as one new version - all rows or none."""
    content = await file.read(MAX_IMPORT_BYTES + 1)
    return await service.import_cases(
        ctx, dataset_id, content=content, filename=file.filename, fmt=fmt
    )


@router.get("/{dataset_id}/export", response_model=None)
async def export_dataset_cases(
    dataset_id: UUID,
    service: DatasetSvc,
    ctx: Auth,
    fmt: DatasetFileFormat = Query("csv", alias="format", description="csv or jsonl"),
    version: int | None = Query(None, ge=1, description="A version number; the newest if omitted"),
) -> Any:
    """One version's cases as a file that imports back unchanged."""
    result = await service.export(ctx, dataset_id, version=version, fmt=fmt)
    return jsonl_response(result) if fmt == "jsonl" else csv_response(result)
