"""The profile sheet against a real deployment, with two controls broken (#1448).

The issue asks for exactly this: a deployment that violates two controls, and a
doctor that names both. It is an integration test because two of the controls are
questions to the database - which model profiles exist, what the deployment's own
settings say - and a mocked session answering them is a sheet that proves the
mock rather than the deployment.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.credential import ModelProfile
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.organization import Organization
from app.db.models.user import User
from app.services import deployment_profile
from app.services.deployment_profile import evaluate

pytestmark = [pytest.mark.anyio, pytest.mark.security]


async def _organization(db: AsyncSession) -> Organization:
    user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="x", full_name="Ada")
    db.add(user)
    await db.flush()
    organization = Organization(
        name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", created_by_user_id=user.id
    )
    db.add(organization)
    await db.flush()
    return organization


def _compliant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything the profile can check, set the way the profile asks."""
    monkeypatch.setattr(settings, "POSTGRES_SSLMODE", "verify-full")
    monkeypatch.setattr(settings, "REDIS_SSL", True)
    monkeypatch.setattr(settings, "VAULT_MASTER_KEY", "k" * 64)
    monkeypatch.setattr(settings, "VAULT_MASTER_KEYS", {})
    monkeypatch.setattr(settings, "LOGFIRE_TOKEN", None)
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://console.example")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://api.example")
    monkeypatch.setattr(deployment_profile, "sso_issuer", lambda: "https://id.corp.example")


async def test_a_deployment_that_matches_the_profile_fails_nothing(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    _compliant(monkeypatch)
    organization = await _organization(db)
    db.add(DeploymentSettings(singleton=True, signup_mode="invite_only"))
    db.add(
        ModelProfile(
            organization_id=organization.id,
            label="Local llama",
            provider="openai",
            model="llama3",
            base_url="http://ollama.internal:11434/v1",
        )
    )
    await db.flush()

    rows = await evaluate(db, "hipaa")

    assert [row.key for row in rows if row.failed] == []


async def test_two_broken_controls_are_both_named(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Both, not the first: a sheet that stopped at the first failure would send
    somebody round the loop once per control."""
    _compliant(monkeypatch)
    organization = await _organization(db)
    # One: registration is open to anybody who reaches the sign-in page.
    db.add(DeploymentSettings(singleton=True, signup_mode="open"))
    # Two: a model profile with no endpoint of its own is the vendor's public API.
    db.add(
        ModelProfile(
            organization_id=organization.id,
            label="Hosted GPT",
            provider="openai",
            model="gpt-4.1",
            base_url=None,
        )
    )
    await db.flush()

    rows = await evaluate(db, "hipaa")
    failed = {row.key: row.detail for row in rows if row.failed}

    assert set(failed) == {"signup", "local-model"}
    assert "Hosted GPT" in failed["local-model"]


async def test_a_control_the_operator_owns_does_not_fail_the_command(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
):
    """Volume encryption is named on every sheet and fails none of them: a command
    that failed on it would be a command nobody could ever pass."""
    _compliant(monkeypatch)
    db.add(DeploymentSettings(singleton=True, signup_mode="closed"))
    await db.flush()

    rows = await evaluate(db, "hipaa")
    attested = {row.key for row in rows if row.outcome == "attested"}

    assert "content-at-rest" in attested
    assert not any(row.failed for row in rows if row.outcome == "attested")
