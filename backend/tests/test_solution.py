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


async def test_preparation_is_bounded_private_and_has_automatic_expiry(
    mock_db_session: AsyncMock,
) -> None:
    from unittest.mock import MagicMock

    from app.clients.redis import RedisClient

    cache = MagicMock(spec=RedisClient)
    cache.set = AsyncMock(return_value=True)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    prepared = await SolutionService(mock_db_session).prepare(ctx, manifest(), cache)
    key, body = cache.set.call_args.args
    assert key == f"solution-plan:{ctx.organization_id}:{ctx.subject_id}:{prepared.plan_id}"
    assert cache.set.call_args.kwargs == {"ttl": 86400, "nx": True}
    assert (
        prepared.manifest_hash
        == plan_solution(SolutionManifest.model_validate_json(body)).manifest_hash
    )
    mock_db_session.execute.assert_not_called()


@pytest.mark.security
async def test_a_viewer_cannot_prepare_a_review(mock_db_session: AsyncMock) -> None:
    from unittest.mock import MagicMock

    from app.clients.redis import RedisClient

    cache = MagicMock(spec=RedisClient)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    with pytest.raises(AuthorizationError):
        await SolutionService(mock_db_session).prepare(ctx, manifest(), cache)
    cache.set.assert_not_called()


async def test_oversized_review_and_cache_collision_are_explicit_refusals(
    mock_db_session: AsyncMock,
) -> None:
    from unittest.mock import MagicMock

    from app.clients.redis import RedisClient
    from app.core.exceptions import BadRequestError

    cache = MagicMock(spec=RedisClient)
    cache.set = AsyncMock(return_value=False)
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    oversized = manifest()
    oversized.contexts[0].data.content = "x" * (1024 * 1024)
    with pytest.raises(BadRequestError, match="1 MiB"):
        await SolutionService(mock_db_session).prepare(ctx, oversized, cache)
    cache.set.assert_not_called()
    with pytest.raises(ConflictError, match="reserved"):
        await SolutionService(mock_db_session).prepare(ctx, manifest(), cache)


@pytest.mark.security
async def test_a_review_needs_a_principal_even_for_an_owner(mock_db_session: AsyncMock) -> None:
    from unittest.mock import MagicMock

    from app.clients.redis import RedisClient

    cache = MagicMock(spec=RedisClient)
    ctx = AuthContext(user_id=None, organization_id=uuid4(), role="owner")
    from app.schemas.solution import PreparedSolutionInstall

    request = PreparedSolutionInstall(
        plan_id=uuid4(), installation_key="same-key", expected_manifest_hash="0" * 64
    )
    with pytest.raises(AuthorizationError, match="subject"):
        await SolutionService(mock_db_session).install_prepared(ctx, request, cache)
    cache.set.assert_not_called()


async def test_expired_review_requires_preparation_again_without_writing(
    mock_db_session: AsyncMock,
) -> None:
    from unittest.mock import MagicMock

    from app.clients.redis import RedisClient
    from app.core.exceptions import NotFoundError
    from app.schemas.solution import PreparedSolutionInstall

    cache = MagicMock(spec=RedisClient)
    cache.get = AsyncMock(return_value=None)
    request = PreparedSolutionInstall(
        plan_id=uuid4(), installation_key="same-key", expected_manifest_hash="0" * 64
    )
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    with pytest.raises(NotFoundError, match="expired"):
        await SolutionService(mock_db_session).install_prepared(ctx, request, cache)
    mock_db_session.execute.assert_not_called()


async def test_prepared_install_still_refuses_a_changed_review_hash(
    mock_db_session: AsyncMock,
) -> None:
    from unittest.mock import MagicMock

    from app.clients.redis import RedisClient
    from app.schemas.solution import PreparedSolutionInstall

    cache = MagicMock(spec=RedisClient)
    cache.get = AsyncMock(return_value=manifest().model_dump_json())
    request = PreparedSolutionInstall(
        plan_id=uuid4(), installation_key="same-key", expected_manifest_hash="0" * 64
    )
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="owner")
    with pytest.raises(ConflictError, match="changed since review"):
        await SolutionService(mock_db_session).install_prepared(ctx, request, cache)
    mock_db_session.execute.assert_not_called()


@pytest.mark.security
async def test_receipt_history_requires_current_builder_authority(
    mock_db_session: AsyncMock,
) -> None:
    ctx = AuthContext(user_id=uuid4(), organization_id=uuid4(), role="viewer")
    with pytest.raises(AuthorizationError, match="agents:edit"):
        await SolutionService(mock_db_session).read_installation(ctx, "same-key")
    mock_db_session.execute.assert_not_called()
