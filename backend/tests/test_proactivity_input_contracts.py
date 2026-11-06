"""Reject incomplete consent and credential-bearing source references before storing them."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.routine_notifications import RoutineFinding
from app.schemas.routine_sources import RoutineSourcePolicy
from app.schemas.task import TaskFields
from app.schemas.telephony import PhoneCallCreate, PhoneContactConfig


def test_agent_next_step_needs_an_actual_agent_relation() -> None:
    with pytest.raises(ValidationError, match="Choose the agent"):
        TaskFields(title="Investigate", next_actor="agent")


def test_reviewed_project_source_must_include_its_workspace_fingerprint() -> None:
    with pytest.raises(ValidationError, match="exact workspace identity"):
        RoutineSourcePolicy(
            id=uuid4(),
            consented_by=uuid4(),
            reviewed_at=datetime.now(UTC),
            version_id=uuid4(),
            scope_hash="a" * 64,
            spec_hash="b" * 64,
            project_id=uuid4(),
        )


def test_attention_source_url_cannot_export_embedded_credentials() -> None:
    with pytest.raises(ValidationError, match="must not embed credentials"):
        RoutineFinding(
            key="thread",
            revision="message",
            title="Needs review",
            content="Draft",
            url="https://person:secret@example.com/mail",
        )


def test_important_phone_opt_in_requires_agents_and_specific_criteria() -> None:
    with pytest.raises(ValidationError, match="importance criteria"):
        PhoneContactConfig(identity_id=uuid4(), allow_important=True)


def test_case_contact_requires_both_a_case_and_its_importance_assessment() -> None:
    with pytest.raises(ValidationError, match="outcome and assessment"):
        PhoneCallCreate(
            request_key=uuid4(), endpoint_id=uuid4(), agent_id=uuid4(), outcome_id=uuid4()
        )
