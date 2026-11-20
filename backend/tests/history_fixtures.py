"""Typed checkpoint payloads for tests that need proven private replay storage."""

from uuid import UUID

from pydantic import JsonValue

from app.schemas.conversation import HistoryCheckpoint, HistoryProvenance

CHECKPOINT_PROVENANCE = HistoryProvenance(
    agent_id=UUID("00000000-0000-0000-0000-000000000001"), configuration_digest="a" * 64
)


def stored_checkpoint(
    messages: object, *, provenance: HistoryProvenance = CHECKPOINT_PROVENANCE
) -> dict[str, JsonValue]:
    return HistoryCheckpoint.model_validate(
        {"version": 1, "provenance": provenance, "messages": messages}
    ).model_dump(mode="json")
