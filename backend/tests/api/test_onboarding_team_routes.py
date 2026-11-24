"""Tests for onboarding team proposal and build routes."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import deps
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.main import app
from app.schemas.onboarding import (
    CreatedAgentInfo,
    OnboardingTeamProposal,
    OnboardingTeamResult,
    ProposedLead,
    ProposedSpecialist,
)

pytestmark = pytest.mark.anyio


def _context(role: str = OrgRoleName.OWNER) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


@pytest.fixture
def onboarding_service() -> MagicMock:
    svc = MagicMock()
    svc.propose_team = MagicMock(
        return_value=OnboardingTeamProposal(
            industry="software",
            role="Engineering Lead",
            rationale="Test rationale",
            lead=ProposedLead(
                name="Tech Lead",
                role="Engineering Lead",
                description="Coordinates specialists",
                starters=["Starter 1", "Starter 2"],
            ),
            specialists=[
                ProposedSpecialist(
                    key="software/api-support",
                    name="API Support",
                    role="Integration",
                    description="Supports API questions",
                    capabilities=["web_research"],
                    recommended=True,
                )
            ],
        )
    )
    svc.build_team = AsyncMock(
        return_value=OnboardingTeamResult(
            lead_agent_id=uuid.uuid4(),
            lead_agent_slug="tech-lead",
            lead_conversation_id=uuid.uuid4(),
            created_agents=[
                CreatedAgentInfo(
                    id=uuid.uuid4(),
                    name="Tech Lead",
                    slug="tech-lead",
                    role="Engineering Lead",
                    is_lead=True,
                    status="published",
                )
            ],
            message="Team created successfully",
        )
    )
    app.dependency_overrides[deps.get_auth_context] = lambda: _context()
    app.dependency_overrides[deps.get_onboarding_team_service] = lambda: svc
    yield svc
    app.dependency_overrides.clear()


async def test_team_proposal_endpoint(onboarding_service: MagicMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"{settings.API_V1_STR}/onboarding/team-proposal",
            json={
                "role": "CTO",
                "industry": "software",
                "team_size": "small",
                "goals": ["API integrations", "Release management"],
                "tools": ["github", "slack"],
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["industry"] == "software"
    assert data["lead"]["name"] == "Tech Lead"
    assert len(data["specialists"]) == 1


async def test_build_team_endpoint(onboarding_service: MagicMock) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"{settings.API_V1_STR}/onboarding/team",
            json={
                "lead": {
                    "name": "Tech Lead",
                    "role": "Engineering Lead",
                    "description": "Coordinates specialists",
                    "starters": ["Starter 1"],
                },
                "specialists": [
                    {
                        "key": "software/api-support",
                        "name": "API Support",
                        "role": "Integration",
                        "description": "Supports API questions",
                        "capabilities": ["web_research"],
                        "recommended": True,
                    }
                ],
            },
        )
    assert response.status_code == 201
    data = response.json()
    assert data["lead_agent_slug"] == "tech-lead"
    assert data["lead_conversation_id"] is not None
    assert len(data["created_agents"]) == 1
