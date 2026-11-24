"""Room planning decisions and links to existing canonical task records."""

from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class RoomLeadPolicy(Base, TimestampMixin):
    __tablename__ = "room_lead_policies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_room_lead_policy_conversation",
        ),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint("max_items BETWEEN 1 AND 3", name="max_items"),
        CheckConstraint(
            "(lead_agent_id IS NULL) = (lead_version_id IS NULL) AND "
            "(NOT enabled OR lead_agent_id IS NOT NULL)",
            name="lead",
        ),
        CheckConstraint(
            "jsonb_typeof(specialists) = 'array' AND jsonb_array_length(specialists) <= 12",
            name="specialists",
        ),
    )

    organization_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    lead_agent_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    lead_version_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    specialists: Mapped[list[dict[str, str]]] = mapped_column(JSONB, default=list)
    max_items: Mapped[int] = mapped_column(Integer, default=3)

    def __repr__(self) -> str:
        return f"<RoomLeadPolicy(conversation_id={self.conversation_id}, revision={self.revision})>"


class RoomRoutingProposal(Base, TimestampMixin):
    __tablename__ = "room_routing_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
            ondelete="CASCADE",
            name="fk_room_routing_proposal_conversation",
        ),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id", "submission_id"],
            [
                "room_submissions.organization_id",
                "room_submissions.conversation_id",
                "room_submissions.id",
            ],
            ondelete="CASCADE",
            name="fk_room_routing_proposal_submission",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "message_id"],
            ["messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
            name="fk_room_routing_proposal_message",
        ),
        ForeignKeyConstraint(
            ["conversation_id", "thread_root_message_id"],
            ["messages.conversation_id", "messages.id"],
            ondelete="CASCADE",
            name="fk_room_routing_proposal_thread",
        ),
        UniqueConstraint(
            "organization_id", "conversation_id", "id", name="uq_room_routing_proposal_scope"
        ),
        UniqueConstraint("submission_id", name="uq_room_routing_proposal_submission"),
        CheckConstraint("policy_revision >= 1 AND revision >= 1", name="revision"),
        CheckConstraint("decision IN ('pending', 'accepted', 'discarded')", name="decision"),
        CheckConstraint(
            "jsonb_typeof(items) = 'array' AND jsonb_array_length(items) BETWEEN 1 AND 3",
            name="items",
        ),
        CheckConstraint(
            "(decision = 'pending' AND decision_key IS NULL AND decision_hash IS NULL) OR "
            "(decision <> 'pending' AND decision_key IS NOT NULL AND decision_hash IS NOT NULL)",
            name="decision_receipt",
        ),
        Index(
            "room_routing_proposals_room_idx", "organization_id", "conversation_id", "created_at"
        ),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    submission_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    thread_root_message_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    requester_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lead_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL")
    )
    policy_revision: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    proposal_hash: Mapped[str] = mapped_column(String(64))
    items: Mapped[list[dict[str, object]]] = mapped_column(JSONB)
    decision: Mapped[Literal["pending", "accepted", "discarded"]] = mapped_column(
        String(16), default="pending"
    )
    decision_key: Mapped[str | None] = mapped_column(String(128))
    decision_hash: Mapped[str | None] = mapped_column(String(64))
    accepted_item_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)

    def __repr__(self) -> str:
        return f"<RoomRoutingProposal(id={self.id}, decision={self.decision})>"


class RoomTaskLink(Base, TimestampMixin):
    __tablename__ = "room_task_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id", "proposal_id"],
            [
                "room_routing_proposals.organization_id",
                "room_routing_proposals.conversation_id",
                "room_routing_proposals.id",
            ],
            ondelete="SET NULL (proposal_id)",
            name="fk_room_task_link_proposal",
        ),
        ForeignKeyConstraint(
            ["organization_id", "table_id", "task_id"],
            [
                "virtual_table_records.organization_id",
                "virtual_table_records.table_id",
                "virtual_table_records.id",
            ],
            ondelete="CASCADE",
            name="fk_room_task_link_task",
        ),
        UniqueConstraint("proposal_id", "proposal_item_id", name="uq_room_task_link_item"),
        CheckConstraint("accepted_revision >= 1", name="accepted_revision"),
        CheckConstraint("jsonb_typeof(provenance) = 'object'", name="provenance"),
        Index("room_task_links_room_idx", "organization_id", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    proposal_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    proposal_item_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    table_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True))
    requester_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    accepted_revision: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    # Retain immutable review provenance after source-room deletion. No working
    # chat, Inbox id, transcript, secret or model output belongs in this snapshot.
    provenance: Mapped[dict[str, str | int]] = mapped_column(JSONB)
    # Evidence of the canonical dispatch; it adds no second execution authority.
    dispatch_trigger_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_triggers.id", ondelete="SET NULL"),
        unique=True,
    )

    def __repr__(self) -> str:
        return f"<RoomTaskLink(id={self.id}, task_id={self.task_id})>"
