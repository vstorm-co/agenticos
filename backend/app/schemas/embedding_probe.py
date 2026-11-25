"""Embedding tests, as a client sees them.

A test is a request a person makes: it spends embedding quota and answers whether
a change would leave a collection's stored vectors where they are. Failure is a
result, not an error - the form shows it - so a refused test is a 200 with
`passed: false`, and only a request that is wrong on its face is a 4xx.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.base import BaseSchema
from app.schemas.knowledge_base import KBScopeLiteral
from app.schemas.service_connection import ConnectionAddress

EmbeddingProbeOutcome = Literal[
    "passed",
    "no_chunks",
    "unreachable",
    "key_refused",
    "model_unknown",
    "wrong_width",
    "vectors_differ",
]


class NewEmbeddingProbeRequest(BaseSchema):
    """Measure the width a custom model answers at, before a collection is made on it."""

    embedding_endpoint_id: UUID = Field(
        description="The `openai_compatible` service connection to embed through."
    )
    embedding_model: str = Field(min_length=1, max_length=128)
    scope: KBScopeLiteral = "personal"


class KbEmbeddingProbeRequest(BaseSchema):
    """The embedding settings a knowledge base would move to.

    Omitted means keep, as in `PATCH /kb/{id}`: only what is named differs from what
    the base has now.
    """

    embedding_provider: str | None = None
    embedding_endpoint_id: UUID | None = None
    embedding_secret_id: UUID | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None


class ConnectionProbeRequest(BaseSchema):
    """The address and key a connection would move to; omitted means keep."""

    base_url: ConnectionAddress | None = None
    secret_id: UUID | None = None


class EmbeddingProbeEstimate(BaseSchema):
    """What a test would cost, before anybody runs it."""

    calls: int = Field(description="Requests a passing test makes: one per sampled chunk.")
    max_calls: int = Field(description="The most it makes, with the one retry every base gets.")
    knowledge_bases: int


class KnowledgeBaseProbeRead(BaseSchema):
    knowledge_base_id: UUID
    name: str
    outcome: EmbeddingProbeOutcome
    min_cosine: float | None = Field(
        description="The lowest similarity, over the sampled chunks, between a stored vector "
        "and the same text embedded now. Null when no comparison was made."
    )
    calls: int


class EmbeddingProbeResult(BaseSchema):
    passed: bool
    outcome: EmbeddingProbeOutcome
    dim: int | None = Field(description="The width the endpoint answered at, when measured.")
    calls: int
    knowledge_bases: list[KnowledgeBaseProbeRead]
    probe_token: str | None = Field(
        description="Present only when the test passed. Send it with the save, within ten "
        "minutes, for the same settings."
    )
    expires_at: datetime | None
