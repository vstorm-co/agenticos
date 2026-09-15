"""The typed retrieval filter contract (FA-039).

Two separate inputs meet only inside the vector store:

- :class:`RetrievalFilters` — the *business* filters, caller/model-supplied,
  validated, all optional, **narrowing only**. It carries no tenant and no
  authorization field, so a caller cannot even name them.
- :class:`RetrievalScope` — the *server-trusted* restrictions (the tenant
  conjunct now; a per-document authorization slot for FA-037 later), built
  exclusively from `ctx` / `AgentDeps`, never from a request or tool
  parameter.

The retrieval service composes `scope AND filters` into a
:class:`RetrievalQuery` and hands the store one structured object; each backend
translates it to its own query. The service builds no SQL and speaks no DSL.

Why widening is structurally impossible: business filters and scope are
different types built in different places, the store ANDs the scope conjuncts
into every query unconditionally, and a conjunction can only shrink a result
set. A supplied filter can only narrow.

This module is trust-boundary validation, so it is held to the 100% coverage
gate (unlike the template-inherited rest of `app/services/rag/*`).
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.rag.config import PARSER_FORMATS
from app.services.rag.models import VectorDocumentId

# The closed vocabulary `document_type` is validated against. It is the stored
# `filetype` — a file extension without the leading dot — for every format any
# parser can ingest (FA-039 P1: the portable technical canonical). A richer
# semantic taxonomy (`document_category`) is deferred pending issue-owner
# confirmation; do not overload `document_type` with it.
DOCUMENT_TYPE_VOCABULARY: frozenset[str] = frozenset(
    ext.lstrip(".") for formats in PARSER_FORMATS.values() for ext in formats
)


class Source(StrEnum):
    """The canonical ingestion-origin values, set in code at the call site.

    A closed vocabulary known at build time — the four origins the pipeline
    stamps: an upload, the local-directory sync, and the two registered
    connectors. A new connector adds a value here in the same commit that adds
    the connector. Exposed as an enum on the agent tool so the model reads the
    legal set straight out of the function schema and cannot guess wrong.
    """

    UPLOAD = "upload"
    LOCAL = "local"
    GDRIVE = "gdrive"
    S3 = "s3"


SOURCE_VOCABULARY: frozenset[str] = frozenset(Source)


class RetrievalFilters(BaseModel):
    """Business filters, caller/model-supplied, narrowing only.

    Semantics: **within a field, multiple values are OR; across fields, AND.**
    Tri-state and explicit — `None` (the field is absent) imposes no
    restriction, a non-empty list is an allow-list, and an **empty list is
    rejected** (a supplied-but-empty filter is a caller error, never silently
    "match everything"). Missing-field behaviour is fail-closed: when a filter
    on dimension X is supplied, a chunk that lacks X does not match.

    `extra="forbid"` is the guard for the API body: a caller that smuggles
    `organization_id` or any non-whitelisted key is rejected, making the trust
    boundary testable rather than only structural. (At the agent tool the typed
    signature is the whitelist, so a smuggled key never reaches this model.)
    """

    model_config = ConfigDict(extra="forbid")

    source: list[str] | None = Field(
        default=None, description="Ingestion origins to include (OR within the field)."
    )
    document_type: list[str] | None = Field(
        default=None, description="Document types (stored filetype/extension) to include."
    )
    organizational_unit: list[str] | None = Field(
        default=None, description="Organizational-unit tags to include."
    )
    date_from: date | None = Field(
        default=None, description="Inclusive lower bound on the document date."
    )
    date_to: date | None = Field(
        default=None, description="Inclusive upper bound on the document date."
    )
    parent_doc_id: VectorDocumentId | None = Field(
        default=None,
        description="Restrict to one vector document (a narrowing hint, not authority).",
    )

    @field_validator("source", "document_type", "organizational_unit")
    @classmethod
    def _reject_empty_list(cls, value: list[str] | None) -> list[str] | None:
        # Tri-state: a supplied-but-empty allow-list is ambiguous, so it is a
        # caller error rather than "match everything" (fail-open closed).
        if value is not None and len(value) == 0:
            raise ValueError("must be a non-empty list of values, or omitted entirely")
        return value

    @field_validator("document_type")
    @classmethod
    def _reject_unknown_document_type(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        unknown = sorted(v for v in value if v not in DOCUMENT_TYPE_VOCABULARY)
        if unknown:
            raise ValueError(
                f"unknown document_type value(s): {', '.join(unknown)}; "
                f"known types: {', '.join(sorted(DOCUMENT_TYPE_VOCABULARY))}"
            )
        return value

    @model_validator(mode="after")
    def _ordered_date_range(self) -> RetrievalFilters:
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_from > self.date_to
        ):
            raise ValueError("date_from must be on or before date_to")
        return self


class TenantScope(BaseModel):
    """The security-bearing scope: a non-null tenant, plus the FA-037 slot.

    `organization_id` is non-null by construction — the store ANDs it into
    every query, and there is no default and no fallback to an unscoped search.
    `authorized_document_ids` is the FA-037 per-document authorization slot:
    `None` means the slot is unset (no per-document narrowing), while a
    **populated-but-empty** set means match nothing (empty-denies-all), so a
    resolver that returns "no documents" can never read as "all documents".
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["tenant"] = "tenant"
    organization_id: UUID
    authorized_document_ids: frozenset[VectorDocumentId] | None = None


class UnscopedScope(BaseModel):
    """The single maintenance marker: no tenant conjunct.

    Reachable only from the named cross-tenant maintenance paths (the
    `rag-search` CLI / app-admin), never from an ordinary API or agent-tool
    caller. The store ANDs no tenant predicate for this variant.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["unscoped"] = "unscoped"


# A discriminated scope: tenant-scoped (the only shape an ordinary caller ever
# builds) or the explicit unscoped maintenance marker. There is no third
# "implicitly unscoped" state — a `TenantScope` cannot be built with a null org.
RetrievalScope = Annotated[TenantScope | UnscopedScope, Field(discriminator="kind")]


class RetrievalQuery(BaseModel):
    """The composed object the store receives: server scope AND business filters."""

    model_config = ConfigDict(frozen=True)

    scope: RetrievalScope
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)

    @property
    def organization_id(self) -> UUID | None:
        """The tenant this query embeds and filters through, or None when unscoped.

        Used both for the mandatory tenant WHERE conjunct and to scope embedding
        resolution to the right tenant (a shared collection name must embed on
        its own organization's key, #913).
        """
        return self.scope.organization_id if isinstance(self.scope, TenantScope) else None


def compose(scope: RetrievalScope, filters: RetrievalFilters | None) -> RetrievalQuery:
    """Compose a server scope with optional business filters into one query."""
    return RetrievalQuery(scope=scope, filters=filters or RetrievalFilters())


__all__ = [
    "DOCUMENT_TYPE_VOCABULARY",
    "SOURCE_VOCABULARY",
    "RetrievalFilters",
    "RetrievalQuery",
    "RetrievalScope",
    "Source",
    "TenantScope",
    "UnscopedScope",
    "compose",
]
