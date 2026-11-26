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
from app.db.vector_tables import VectorScope
from app.services.rag.filters import (
    DOCUMENT_TYPE_VOCABULARY,
    SOURCE_VOCABULARY,
    DocumentType,
    RetrievalFilters,
    RetrievalQuery,
    Source,
    TenantScope,
    UnscopedScope,
    bind_collection,
    can_union,
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

    def test_document_type_enum_mirrors_the_vocabulary(self):
        # The enum the agent tool publishes as a closed schema must carry exactly
        # the values the API validator enforces, so the two cannot drift.
        assert {str(member) for member in DocumentType} == set(DOCUMENT_TYPE_VOCABULARY)
        assert DocumentType("pdf") == "pdf"


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

    def test_a_known_source_passes(self):
        assert RetrievalFilters(source=["upload", "gdrive"]).source == ["upload", "gdrive"]

    def test_an_unknown_source_is_rejected(self):
        # `source` is a build-time-closed vocabulary, so a value outside it is a
        # caller error at the API boundary (the agent tool types it as an enum),
        # never a filter that silently matches nothing.
        with pytest.raises(ValidationError):
            RetrievalFilters(source=["upload", "ftp"])

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


class TestBindingSameNamedBases:
    """A collection name is not unique; one search reads one scope per name (#2537)."""

    def test_a_second_base_of_the_same_tenant_joins_the_first(self):
        tenant, first, second = uuid4(), uuid4(), uuid4()
        names: list[str] = []
        scopes: dict[str, VectorScope] = {}

        bind_collection(names, scopes, "handbook", VectorScope(tenant, knowledge_base_id=first))
        bind_collection(names, scopes, "handbook", VectorScope(tenant, knowledge_base_id=second))

        assert names == ["handbook"]
        assert scopes["handbook"] == VectorScope(
            tenant, knowledge_base_id=first, additional_knowledge_base_ids=(second,)
        )

    def test_differently_named_bases_are_bound_apart(self):
        tenant = uuid4()
        names: list[str] = []
        scopes: dict[str, VectorScope] = {}

        bind_collection(names, scopes, "a", VectorScope(tenant, knowledge_base_id=uuid4()))
        bind_collection(names, scopes, "b", VectorScope(tenant, knowledge_base_id=uuid4()))

        assert names == ["a", "b"]

    def test_bases_of_another_tenant_or_unfiled_rule_cannot_join(self):
        org = uuid4()
        bound = VectorScope(org, knowledge_base_id=uuid4())

        assert can_union(bound, VectorScope(org, knowledge_base_id=uuid4()))
        assert not can_union(bound, VectorScope(uuid4(), knowledge_base_id=uuid4()))
        assert not can_union(
            bound, VectorScope(None, knowledge_base_id=uuid4(), operator_unfiled_only=True)
        )
        assert not can_union(
            bound, VectorScope(org, knowledge_base_id=uuid4(), takes_unfiled=False)
        )

    def test_joining_a_scope_it_cannot_union_with_is_refused(self):
        names: list[str] = []
        scopes = {"handbook": VectorScope(uuid4(), knowledge_base_id=uuid4())}

        with pytest.raises(ValueError, match="another scope"):
            bind_collection(names, scopes, "handbook", VectorScope(None, knowledge_base_id=uuid4()))

    def test_joining_a_scope_naming_no_base_is_refused(self):
        tenant = uuid4()
        scopes = {"handbook": VectorScope(tenant, knowledge_base_id=uuid4())}

        with pytest.raises(ValueError, match="without a knowledge base"):
            bind_collection([], scopes, "handbook", VectorScope(tenant))

    def test_an_initial_binding_cannot_widen_to_the_whole_tenant(self):
        names: list[str] = []
        scopes: dict[str, VectorScope] = {}
        with pytest.raises(ValueError, match="without a knowledge base"):
            bind_collection(names, scopes, "handbook", VectorScope(uuid4()))
        assert names == []
        assert scopes == {}

    def test_an_existing_unbounded_scope_cannot_be_extended(self):
        tenant = uuid4()
        original = VectorScope(tenant)
        names = ["handbook"]
        scopes = {"handbook": original}
        with pytest.raises(ValueError, match="another scope"):
            bind_collection(
                names, scopes, "handbook", VectorScope(tenant, knowledge_base_id=uuid4())
            )
        assert names == ["handbook"]
        assert scopes == {"handbook": original}

    def test_operator_unfiled_data_does_not_join_a_private_scope_of_the_same_tenant(self):
        operator = VectorScope(None, knowledge_base_id=uuid4(), operator_unfiled_only=True)
        private = VectorScope(None, knowledge_base_id=uuid4())
        assert not can_union(operator, private)
