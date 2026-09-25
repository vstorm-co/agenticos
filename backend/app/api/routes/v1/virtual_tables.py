"""Virtual Tables routes - the HTTP face of the shared table service.

The console, agent tools, workflow nodes and the public API all reach the same
`VirtualTableService`; these routes add nothing to it but the wire format.

Routes acting on the collection carry a `require(...)` gate. Routes acting on one
table deliberately do not: the service resolves access against that table's owner,
visibility and grants, and a role-level gate would refuse a viewer who was
explicitly given edit on a single table - the case sharing exists for.

**The error envelope is part of the contract.** Every refusal answers
`{"error": {"code", "message", "details"}}` (`ErrorEnvelope`), and each `code` below
is stable: a client branches on it, not on the message.

- `REVISION_CONFLICT` (409): the record changed since it was read. `details` carries
  `current_revision`; read the record again and retry.
- `REVISION_REQUIRED` (428): an upsert found the record and was not told which
  revision it replaces. `details` carries `current_revision`.
- `SCHEMA_VERSION_CONFLICT` (409): the schema changed since it was read.
- `SCHEMA_DEPENDENCY` (409): something depends on what a schema change removes.
- `TABLE_ARCHIVED` (409): the table refuses writes.
- `ALREADY_EXISTS` (409): a table name or a record's external id is taken.
- `VALIDATION_ERROR` (422): the request itself is malformed, refused before the service runs.
- `AUTHORIZATION_ERROR` (403): the caller lacks the permission a collection route requires.
- `CONCURRENT_CHANGE` (409): an upsert lost a race with a delete of the same record; retry.
- `INVALID_RECORD`, `ARCHIVED_COLUMN`, `INVALID_QUERY`, `INVALID_SCHEMA` (422): the
  value, filter or schema does not fit; `details.fields` names each field.
- `IDEMPOTENCY_KEY_REUSED` (422): the `Idempotency-Key` was used for a different
  request.
- `NOT_FOUND` (404): no such table or record - also what another organization's
  table, or one the caller may not reach, looks like.

**Idempotency.** Every record write accepts an `Idempotency-Key` header. Retrying a
write with the same key and the same body returns the stored answer (with
`Idempotent-Replayed: true`) and writes nothing; the same key with a different body
is refused. Keys are scoped to the caller and the kind of write. A replayed delete answers
204 as the first one did and is not marked.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query, Response, status

from app.api.deps import Auth, VirtualTableSvc, require
from app.api.routes.v1._path_convertors import ANYTEXT
from app.api.routes.v1._table_responses import answer
from app.core.permissions import Perm
from app.schemas.virtual_table import (
    ErrorEnvelope,
    OperationKey,
    RecordCreate,
    RecordExists,
    RecordList,
    RecordQuery,
    RecordRead,
    RecordSort,
    RecordUpdate,
    RecordUpsert,
    SchemaUpdate,
    SchemaVersionList,
    SortDirection,
    TableCreate,
    TableList,
    TableRead,
    TableUpdate,
)

router = APIRouter()

IdempotencyKey = Annotated[
    OperationKey | None,
    Header(
        description=(
            "Makes a retry safe: the same key and body return the first answer, and the "
            "same key with a different body is refused."
        ),
    ),
]

# NUL is refused in every string that reaches a text column: PostgreSQL cannot store it.
_NO_NUL = r"^[^\x00]*$"
# An external id also refuses line breaks. Its route uses the `anytext` convertor, which
# matches them, so this is where an id holding one is refused rather than misrouted.
_PLAIN_KEY = r"^[^\x00\r\n]*$"

ExternalIdPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=255,
        pattern=_PLAIN_KEY,
        description="The caller's own key for the record. It may contain `/`.",
    ),
]

_REFUSALS: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorEnvelope, "description": "No such table or record"},
    409: {"model": ErrorEnvelope, "description": "A conflict; see `error.code`"},
    422: {"model": ErrorEnvelope, "description": "The request does not fit the table"},
    428: {"model": ErrorEnvelope, "description": "`expected_revision` is required"},
}

# The collection routes carry a `require(...)` gate, which refuses with a 403 before the
# handler runs. The per-table routes have no gate and answer 404 for a table the caller may
# not reach, so they do not advertise it.
_GATED_REFUSALS: dict[int | str, dict[str, Any]] = {
    403: {
        "model": ErrorEnvelope,
        "description": "The caller lacks the permission this route requires",
    },
    **_REFUSALS,
}


@router.get(
    "",
    response_model=TableList,
    responses=_GATED_REFUSALS,
    dependencies=[Depends(require(Perm.TABLES_VIEW))],
)
async def list_tables(
    service: VirtualTableSvc,
    ctx: Auth,
    q: str | None = Query(
        None, max_length=100, pattern=_NO_NUL, description="Match on name or description"
    ),
    include_archived: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """The tables the caller may see, by name."""
    return await service.list_tables(
        ctx, include_archived=include_archived, search=q, skip=skip, limit=limit
    )


@router.post(
    "",
    response_model=TableRead,
    status_code=status.HTTP_201_CREATED,
    responses=_GATED_REFUSALS,
    dependencies=[Depends(require(Perm.TABLES_CREATE))],
)
async def create_table(data: TableCreate, service: VirtualTableSvc, ctx: Auth) -> Any:
    """Create a table with its first schema version."""
    return await service.create_table(ctx, data)


@router.get("/{table_id}", response_model=TableRead, responses=_REFUSALS)
async def describe_table(table_id: UUID, service: VirtualTableSvc, ctx: Auth) -> Any:
    """A table and the columns of its current schema."""
    return await service.describe_table(ctx, table_id)


@router.patch("/{table_id}", response_model=TableRead, responses=_REFUSALS)
async def update_table(
    table_id: UUID, data: TableUpdate, service: VirtualTableSvc, ctx: Auth
) -> Any:
    """Rename a table or change its description."""
    return await service.update_table(ctx, table_id, data)


@router.post("/{table_id}/archive", response_model=TableRead, responses=_REFUSALS)
async def archive_table(table_id: UUID, service: VirtualTableSvc, ctx: Auth) -> Any:
    """Archive a table. Records stay readable; every write is refused."""
    return await service.archive_table(ctx, table_id)


@router.put("/{table_id}/schema", response_model=TableRead, responses=_REFUSALS)
async def change_schema(
    table_id: UUID, data: SchemaUpdate, service: VirtualTableSvc, ctx: Auth
) -> Any:
    """Append the next schema version from the full list of columns the table should have."""
    return await service.update_schema(ctx, table_id, data)


@router.get("/{table_id}/schema-versions", response_model=SchemaVersionList, responses=_REFUSALS)
async def list_schema_versions(table_id: UUID, service: VirtualTableSvc, ctx: Auth) -> Any:
    """Every schema version the table has had."""
    return await service.list_schema_versions(ctx, table_id)


@router.get("/{table_id}/records", response_model=RecordList, responses=_REFUSALS)
async def list_records(
    table_id: UUID,
    service: VirtualTableSvc,
    ctx: Auth,
    sort: str = Query("created_at", description="`created_at`, `updated_at` or a column id"),
    direction: SortDirection = Query("asc"),
    skip: int = Query(0, ge=0, le=10_000),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """A page of records, unfiltered. Use `POST .../records/query` to filter."""
    query = RecordQuery(sort=RecordSort(by=sort, direction=direction), skip=skip, limit=limit)
    return await service.list_records(ctx, table_id, query)


@router.post("/{table_id}/records/query", response_model=RecordList, responses=_REFUSALS)
async def query_records(
    table_id: UUID, query: RecordQuery, service: VirtualTableSvc, ctx: Auth
) -> Any:
    """A page of records matching typed filters, in a deterministic order."""
    return await service.list_records(ctx, table_id, query)


@router.get("/{table_id}/records/exists", response_model=RecordExists, responses=_REFUSALS)
async def record_exists(
    table_id: UUID,
    service: VirtualTableSvc,
    ctx: Auth,
    external_id: str = Query(..., min_length=1, max_length=255, pattern=_PLAIN_KEY),
) -> Any:
    """Whether a record with this external id exists."""
    return RecordExists(exists=await service.record_exists(ctx, table_id, external_id))


@router.get(
    f"/{{table_id}}/records/by-external-id/{{external_id:{ANYTEXT}}}",
    response_model=RecordRead,
    responses=_REFUSALS,
)
async def get_record_by_external_id(
    table_id: UUID, external_id: ExternalIdPath, service: VirtualTableSvc, ctx: Auth
) -> Any:
    """One record, by the caller's own key for it."""
    return await service.get_record_by_external_id(ctx, table_id, external_id)


@router.put(
    f"/{{table_id}}/records/by-external-id/{{external_id:{ANYTEXT}}}",
    response_model=RecordRead,
    responses={**_REFUSALS, 201: {"model": RecordRead, "description": "Created"}},
)
async def upsert_record(
    table_id: UUID,
    external_id: ExternalIdPath,
    data: RecordUpsert,
    response: Response,
    service: VirtualTableSvc,
    ctx: Auth,
    idempotency_key: IdempotencyKey = None,
) -> Any:
    """Create the record with this external id, or update it.

    201 when it was created. When it already exists the call is an update: send
    `expected_revision`, or receive `REVISION_REQUIRED` (428) with the revision to send.
    """
    written = await service.upsert_record(
        ctx, table_id, external_id, data, operation_key=idempotency_key
    )
    return answer(response, written)


@router.post(
    "/{table_id}/records",
    response_model=RecordRead,
    status_code=status.HTTP_201_CREATED,
    responses=_REFUSALS,
)
async def create_record(
    table_id: UUID,
    data: RecordCreate,
    response: Response,
    service: VirtualTableSvc,
    ctx: Auth,
    idempotency_key: IdempotencyKey = None,
) -> Any:
    """Create a record at revision 1."""
    written = await service.create_record(ctx, table_id, data, operation_key=idempotency_key)
    return answer(response, written)


@router.get("/{table_id}/records/{record_id}", response_model=RecordRead, responses=_REFUSALS)
async def get_record(table_id: UUID, record_id: UUID, service: VirtualTableSvc, ctx: Auth) -> Any:
    """One record."""
    return await service.get_record(ctx, table_id, record_id)


@router.patch("/{table_id}/records/{record_id}", response_model=RecordRead, responses=_REFUSALS)
async def update_record(
    table_id: UUID,
    record_id: UUID,
    data: RecordUpdate,
    response: Response,
    service: VirtualTableSvc,
    ctx: Auth,
    idempotency_key: IdempotencyKey = None,
) -> Any:
    """Change the named cells, if the record is still at `expected_revision`.

    An update that would leave every cell as it is changes nothing: the revision stays and
    the current record is returned.
    """
    written = await service.update_record(
        ctx, table_id, record_id, data, operation_key=idempotency_key
    )
    return answer(response, written)


@router.delete(
    "/{table_id}/records/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=_REFUSALS,
)
async def delete_record(
    table_id: UUID,
    record_id: UUID,
    service: VirtualTableSvc,
    ctx: Auth,
    expected_revision: int = Query(..., ge=1, description="The revision the caller last read"),
    idempotency_key: IdempotencyKey = None,
) -> None:
    """Delete a record, if it is still at `expected_revision`. Its history is kept."""
    await service.delete_record(
        ctx,
        table_id,
        record_id,
        expected_revision=expected_revision,
        operation_key=idempotency_key,
    )
