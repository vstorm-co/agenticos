"""RAG spend that lands on no agent run - indexing, and a direct search.

Agent runs record their cost on `agent_runs.cost_usd`, and that includes the
embeddings a knowledge search *inside a run* makes, because a run's ledger is
metering while it executes. Two RAG activities have no run to bill: indexing a
document happens in a worker on nobody's conversation, and `POST /rag/search`
answers a caller directly. For months the first was recorded nowhere - an
organization could embed unbounded volume under an exhausted budget, because the
monthly total only ever summed runs - and the second, once metered, landed here
too. `source` tells them apart (:class:`SpendSource`) so the dashboard does not
report a search as indexing; both still count toward the monthly budget.

One row per model per metering window - a document upload, a connector sync, one
search - rather than per API call. The unit someone reconciles against a bill is
"what did this cost with which model", not "what did chunk 37 cost"; and a window
can spend in two models at once, because describing a scanned page is a vision
call and embedding it is not.
"""

import uuid
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class SpendSource(StrEnum):
    """Which RAG activity a row of non-run spend paid for.

    The table began as indexing alone, then a metered knowledge search landed
    its embedding and rerank cost here too - both are RAG spend outside any
    agent run. Left undistinguished, a search inflated the dashboard's
    "indexing" subtotal, so this says which is which. Both still count toward
    the monthly budget; only the reporting split reads the column.
    """

    INGESTION = "ingestion"
    RETRIEVAL = "retrieval"


class IngestionSpend(Base, TimestampMixin):
    __tablename__ = "ingestion_spend"

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Nullable: a local-directory sync run by an operator has no tenant to
    # bill. The row still exists - a total that quietly under-reports is worse
    # than one holding rows nobody claims - but it counts toward no
    # organization's budget.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )

    # SET NULL: deleting a document must not delete the record of what
    # indexing it cost. The spend still happened.
    rag_document_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("rag_documents.id", ondelete="SET NULL"),
        nullable=True,
    )

    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Non-zero for the image describer, whose output is the description it
    # writes; zero for embeddings, which only read.
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Numeric, not float: summed into the same monthly totals as run cost.
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal(0))
    # True when the model had no price - the cost is then a floor.
    cost_is_partial: Mapped[bool] = mapped_column(nullable=False, default=False)

    # Indexing or retrieval. `server_default` so the rows written before the
    # column existed - all of them indexing - read as such without a backfill.
    source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=SpendSource.INGESTION.value,
        server_default=SpendSource.INGESTION.value,
    )

    # Declared here as well as in the migration: the integration tests build
    # the schema from the models, and the monthly lookup queries exactly this
    # shape - one organization, one window.
    __table_args__ = (Index("ix_ingestion_spend_org_created", "organization_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<IngestionSpend(org={self.organization_id}, cost=${self.cost_usd})>"
