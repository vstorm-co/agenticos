"""Map :class:`RetrievalQuery` to Qdrant ``Filter`` (FA-039 parity with pgvector)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from qdrant_client.models import (
    FieldCondition,
    Filter,
    IsEmptyCondition,
    MatchAny,
    MatchValue,
    PayloadField,
    Range,
)

from app.services.rag.filters import (
    AppScope,
    RetrievalFilters,
    RetrievalQuery,
    RetrievalScope,
    TenantScope,
    UnscopedScope,
)

LOGICAL_COLLECTION_KEY = "logical_collection"

# Returned when scope denies all documents (empty authorized set).
EmptyRetrieval = Literal["empty"]


def _metadata_key(field: str) -> str:
    """Payload keys mirror pg ``metadata->>'field'`` (flat on the point)."""
    return field


def tenant_payload_conditions(tenant: UUID | None) -> list[FieldCondition | IsEmptyCondition]:
    """Same semantics as ``PgVectorStore._org_filter`` (#1684)."""
    if tenant is None:
        return [IsEmptyCondition(is_empty=PayloadField(key="organization_id"))]
    return [
        FieldCondition(
            key="organization_id",
            match=MatchValue(value=str(tenant)),
        )
    ]


def _scope_conditions(
    scope: RetrievalScope,
) -> list[FieldCondition | IsEmptyCondition] | EmptyRetrieval:
    conditions: list[FieldCondition | IsEmptyCondition] = []
    authz = None
    if isinstance(scope, TenantScope):
        conditions.extend(
            [
                FieldCondition(
                    key="organization_id",
                    match=MatchValue(value=str(scope.organization_id)),
                )
            ]
        )
        authz = scope.authorized_document_ids
    elif isinstance(scope, AppScope):
        conditions.append(IsEmptyCondition(is_empty=PayloadField(key="organization_id")))
        authz = scope.authorized_document_ids
    elif isinstance(scope, UnscopedScope):
        authz = None
    else:
        raise TypeError(f"unknown scope type: {type(scope)!r}")

    if authz is not None:
        if not authz:
            return "empty"
        conditions.append(
            FieldCondition(
                key="parent_doc_id",
                match=MatchAny(any=list(authz)),
            )
        )
    return conditions


def _business_filter_conditions(filters: RetrievalFilters) -> list[FieldCondition | Filter]:
    must: list[FieldCondition | Filter] = []
    if filters.source is not None:
        must.append(
            FieldCondition(key=_metadata_key("source"), match=MatchAny(any=list(filters.source)))
        )
    if filters.document_type is not None:
        must.append(
            FieldCondition(
                key=_metadata_key("document_type"),
                match=MatchAny(any=list(filters.document_type)),
            )
        )
    if filters.organizational_unit is not None:
        must.append(
            FieldCondition(
                key=_metadata_key("organizational_unit"),
                match=MatchAny(any=list(filters.organizational_unit)),
            )
        )
    if filters.date_from is not None:
        must.append(
            FieldCondition(
                key=_metadata_key("doc_date"),
                range=Range(gte=filters.date_from.isoformat()),
            )
        )
    if filters.date_to is not None:
        must.append(
            FieldCondition(
                key=_metadata_key("doc_date"),
                range=Range(lte=filters.date_to.isoformat()),
            )
        )
    if filters.parent_doc_id is not None:
        must.append(
            FieldCondition(
                key="parent_doc_id",
                match=MatchValue(value=str(filters.parent_doc_id)),
            )
        )
    return must


def logical_collection_filter(collection_name: str) -> FieldCondition:
    return FieldCondition(
        key=LOGICAL_COLLECTION_KEY,
        match=MatchValue(value=collection_name),
    )


def retrieval_query_to_qdrant_filter(
    collection_name: str,
    query_filter: RetrievalQuery,
) -> Filter | EmptyRetrieval:
    """Compose scope AND business filters for one logical collection."""
    scope_part = _scope_conditions(query_filter.scope)
    if scope_part == "empty":
        return "empty"
    must: list[FieldCondition | IsEmptyCondition | Filter] = [
        logical_collection_filter(collection_name),
        *scope_part,
        *_business_filter_conditions(query_filter.filters),
    ]
    return Filter(must=must)


def tenant_scoped_filter(
    collection_name: str,
    tenant: UUID | None,
    *,
    parent_doc_id: str | None = None,
    source_path: str | None = None,
    content_hash: str | None = None,
    filename: str | None = None,
) -> Filter:
    """Row-level ops: logical collection + tenant (+ optional document keys)."""
    must: list[FieldCondition | IsEmptyCondition] = [
        logical_collection_filter(collection_name),
        *tenant_payload_conditions(tenant),
    ]
    if parent_doc_id is not None:
        must.append(
            FieldCondition(key="parent_doc_id", match=MatchValue(value=parent_doc_id)),
        )
    if source_path is not None:
        must.append(
            FieldCondition(
                key=_metadata_key("source_path"),
                match=MatchValue(value=source_path),
            )
        )
    if content_hash is not None:
        must.append(
            FieldCondition(
                key=_metadata_key("content_hash"),
                match=MatchValue(value=content_hash),
            )
        )
    if filename is not None:
        must.append(
            FieldCondition(
                key=_metadata_key("filename"),
                match=MatchValue(value=filename),
            )
        )
    return Filter(must=must)
