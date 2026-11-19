"""Bundle review and authority are checked before any creation or replay."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.schemas.solution import SolutionInstall, SolutionManifest
from app.services.solution import SolutionService, plan_solution

pytestmark = pytest.mark.anyio


def manifest() -> SolutionManifest:
    return SolutionManifest.model_validate(
        {
            "name": "support",
            "contexts": [
                {
                    "key": "policy",
                    "data": {"name": "Policy", "content": "Escalate unknown requests."},
                }
            ],
        }
    )


def test_hash_covers_content_and_is_stable() -> None:
    original = manifest()
    assert (
        plan_solution(original).manifest_hash
        == plan_solution(
            SolutionManifest.model_validate_json(original.model_dump_json())
        ).manifest_hash
    )
    changed = original.model_copy(deep=True)
    changed.contexts[0].data.content = "Ask the owner."
    assert plan_solution(original).manifest_hash != plan_solution(changed).manifest_hash
    assert not plan_solution(original).publishes and not plan_solution(original).executes


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "empty"},
        {
            "name": "duplicate",
            "contexts": [
                {"key": "same", "data": {"name": "One"}},
                {"key": "same", "data": {"name": "Two"}},
            ],
        },
        {
            "name": "unknown",
            "agents": [{"key": "agent", "spec": {"name": "Agent"}, "context_keys": ["missing"]}],
        },
        {
            "name": "unknown",
            "contexts": [{"key": "policy", "data": {"name": "Policy"}}],
            "agents": [
                {"key": "agent", "spec": {"name": "Agent"}, "context_keys": ["policy", "policy"]}
            ],
        },
    ],
)
def test_empty_duplicate_and_unknown_references_are_refused(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SolutionManifest.model_validate(payload)


async def test_changed_review_is_refused_before_writing(mock_db_session: AsyncMock) -> None:
    request = SolutionInstall(
        installation_key="support", expected_manifest_hash="0" * 64, manifest=manifest()
    )
    with pytest.raises(ConflictError, match="changed since review"):
        await SolutionService(mock_db_session).install(
            AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner"), request
        )
    mock_db_session.execute.assert_not_called()


@pytest.mark.security
@pytest.mark.parametrize("subject", [True, False])
async def test_missing_authority_is_refused_before_writing(
    mock_db_session: AsyncMock, subject: bool
) -> None:
    request = SolutionInstall(
        installation_key="support",
        expected_manifest_hash=plan_solution(manifest()).manifest_hash,
        manifest=manifest(),
    )
    context = AuthContext(
        user_id=uuid4() if subject else None, organization_id=uuid4(), role="viewer"
    )
    with pytest.raises(AuthorizationError):
        await SolutionService(mock_db_session).install(context, request)
    mock_db_session.execute.assert_not_called()
