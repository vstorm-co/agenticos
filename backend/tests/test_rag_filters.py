"""The FA-039 filter/scope trust boundary (under the 100% gate).

These pin the narrowing-only guarantees: a business filter cannot express a
tenant or authorization, an empty allow-list is a caller error, an unknown value
is rejected, the scope's tenant is non-null by construction, and the deprecated
filter string can only fold into `parent_doc_id`, never widen.
"""

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import BadRequestError
from app.services.rag.filters import (
    DOCUMENT_TYPE_VOCABULARY,
    SOURCE_VOCABULARY,
    RetrievalFilters,
    RetrievalQuery,
    Source,
    TenantScope,
    UnscopedScope,
    compose,
    resolve_legacy_filter,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]


class TestVocabularies:
    def test_source_is_the_four_code_set_origins(self):
        assert sorted(SOURCE_VOCABULARY) == ["gdrive", "local", "s3", "upload"]
        assert Source.UPLOAD == "upload"

    def test_document_type_vocabulary_is_extensions_without_dots(self):
        assert "pdf" in DOCUMENT_TYPE_VOCABULARY
        assert "docx" in DOCUMENT_TYPE_VOCABULARY
        assert not any(v.startswith(".") for v in DOCUMENT_TYPE_VOCABULARY)


class TestRetrievalFilters:
    def test_all_optional_by_default(self):
        f = RetrievalFilters()
        assert f.source is None and f.document_type is None and f.parent_doc_id is None

    def test_explicit_none_on_a_list_field_is_accepted(self):
        # An explicit None runs the validators on None (no restriction), distinct
        # from an empty list (rejected).
        f = RetrievalFilters(source=None, document_type=None, organizational_unit=None)
        assert f.source is None and f.document_type is None

    def test_a_non_empty_allow_list_is_kept(self):
        f = RetrievalFilters(source=["upload"], organizational_unit=["legal"])
        assert f.source == ["upload"]
        assert f.organizational_unit == ["legal"]

    @pytest.mark.parametrize("field", ["source", "document_type", "organizational_unit"])
    def test_an_empty_list_is_rejected(self, field):
        with pytest.raises(ValidationError):
            RetrievalFilters(**{field: []})

    def test_a_known_document_type_passes(self):
        assert RetrievalFilters(document_type=["pdf", "md"]).document_type == ["pdf", "md"]

    def test_an_unknown_document_type_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalFilters(document_type=["pdf", "exe"])

    def test_a_smuggled_key_is_rejected_by_extra_forbid(self):
        with pytest.raises(ValidationError):
            RetrievalFilters(organization_id=str(uuid4()))

    def test_a_reversed_date_range_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalFilters(date_from=date(2025, 2, 1), date_to=date(2025, 1, 1))

    def test_an_ordered_or_one_sided_range_passes(self):
        assert RetrievalFilters(date_from=date(2025, 1, 1), date_to=date(2025, 2, 1))
        assert RetrievalFilters(date_from=date(2025, 1, 1)).date_to is None
        assert RetrievalFilters(date_to=date(2025, 2, 1)).date_from is None
        assert RetrievalFilters(date_from=date(2025, 1, 1), date_to=date(2025, 1, 1))


class TestRetrievalScope:
    def test_a_tenant_scope_carries_a_non_null_org(self):
        org = uuid4()
        assert TenantScope(organization_id=org).organization_id == org

    def test_a_tenant_scope_refuses_a_null_org(self):
        with pytest.raises(ValidationError):
            TenantScope(organization_id=None)

    def test_the_authorization_slot_defaults_to_unset(self):
        assert TenantScope(organization_id=uuid4()).authorized_document_ids is None

    def test_a_populated_empty_authorization_set_is_kept_distinct_from_none(self):
        scope = TenantScope(organization_id=uuid4(), authorized_document_ids=frozenset())
        assert scope.authorized_document_ids == frozenset()
        assert scope.authorized_document_ids is not None


class TestRetrievalQuery:
    def test_tenant_query_exposes_the_org(self):
        org = uuid4()
        q = RetrievalQuery(scope=TenantScope(organization_id=org))
        assert q.organization_id == org
        assert isinstance(q.filters, RetrievalFilters)

    def test_unscoped_query_has_no_org(self):
        assert RetrievalQuery(scope=UnscopedScope()).organization_id is None

    def test_compose_defaults_missing_filters(self):
        q = compose(TenantScope(organization_id=uuid4()), None)
        assert q.filters == RetrievalFilters()

    def test_compose_passes_filters_through(self):
        f = RetrievalFilters(source=["s3"])
        assert compose(UnscopedScope(), f).filters is f


class TestLegacyFilterShim:
    def test_an_absent_string_returns_the_filters_unchanged(self):
        f = RetrievalFilters(source=["upload"])
        assert resolve_legacy_filter(None, f) is f
        assert resolve_legacy_filter("", None) is None

    def test_a_full_match_maps_onto_parent_doc_id(self):
        f = resolve_legacy_filter('parent_doc_id == "doc-9"', None)
        assert f is not None and f.parent_doc_id == "doc-9"

    def test_a_full_match_merges_into_existing_filters(self):
        f = resolve_legacy_filter('parent_doc_id == "doc-9"', RetrievalFilters(source=["upload"]))
        assert f is not None and f.parent_doc_id == "doc-9" and f.source == ["upload"]

    def test_any_other_string_is_refused(self):
        with pytest.raises(BadRequestError):
            resolve_legacy_filter('filetype == "pdf"', None)

    def test_both_sources_supplied_is_a_conflict(self):
        with pytest.raises(BadRequestError):
            resolve_legacy_filter('parent_doc_id == "a"', RetrievalFilters(parent_doc_id="b"))
