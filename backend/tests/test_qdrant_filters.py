"""Unit tests for Qdrant filter mapping (FA-039 scope parity)."""

from __future__ import annotations

import uuid

from qdrant_client.models import IsEmptyCondition, MatchAny, MatchValue

from app.services.rag.filters import (
    AppScope,
    RetrievalFilters,
    RetrievalQuery,
    TenantScope,
    UnscopedScope,
    compose,
)
from app.services.rag.qdrant_filters import (
    LOGICAL_COLLECTION_KEY,
    retrieval_query_to_qdrant_filter,
    tenant_payload_conditions,
)


def test_tenant_scope_and_business_filters_and_collection() -> None:
    org = uuid.uuid4()
    scope = TenantScope(organization_id=org)
    filters = RetrievalFilters(source=["upload"], parent_doc_id="doc-1")
    q = compose(scope, filters)
    filt = retrieval_query_to_qdrant_filter("kb_main", q)
    assert filt != "empty"
    assert filt.must is not None
    keys = {c.key for c in filt.must if hasattr(c, "key")}
    assert LOGICAL_COLLECTION_KEY in keys
    assert "organization_id" in keys
    assert "source" in keys
    assert "parent_doc_id" in keys


def test_app_scope_requires_missing_organization_id() -> None:
    q = compose(AppScope(), None)
    filt = retrieval_query_to_qdrant_filter("shared", q)
    assert filt != "empty"
    assert any(isinstance(c, IsEmptyCondition) for c in filt.must or [])


def test_empty_authorized_set_denies_all() -> None:
    org = uuid.uuid4()
    scope = TenantScope(organization_id=org, authorized_document_ids=frozenset())
    q = RetrievalQuery(scope=scope)
    assert retrieval_query_to_qdrant_filter("kb", q) == "empty"


def test_authorized_document_ids_use_match_any() -> None:
    org = uuid.uuid4()
    scope = TenantScope(organization_id=org, authorized_document_ids=frozenset({"a", "b"}))
    q = RetrievalQuery(scope=scope)
    filt = retrieval_query_to_qdrant_filter("kb", q)
    assert filt != "empty"
    parent_conds = [
        c
        for c in filt.must or []
        if getattr(c, "key", None) == "parent_doc_id"
        and isinstance(getattr(c, "match", None), MatchAny)
    ]
    assert parent_conds
    assert set(parent_conds[0].match.any) == {"a", "b"}  # type: ignore[union-attr]


def test_unscoped_has_no_tenant_conjunct() -> None:
    q = compose(UnscopedScope(), None)
    filt = retrieval_query_to_qdrant_filter("maint", q)
    assert filt != "empty"
    assert not any(
        getattr(c, "key", None) == "organization_id" for c in filt.must or []
    )


def test_tenant_payload_conditions_bound_value() -> None:
    org = uuid.uuid4()
    conds = tenant_payload_conditions(org)
    assert len(conds) == 1
    assert isinstance(conds[0].match, MatchValue)
    assert conds[0].match.value == str(org)  # type: ignore[union-attr]
