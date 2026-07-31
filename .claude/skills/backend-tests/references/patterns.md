# Worked patterns

Read the real neighbours before copying these — `tests/test_agent_registry.py`,
`tests/api/test_platform_routes.py`, `tests/integration/test_schema_guarantees.py`.

## Unit — a service

Mock the repository, not the service. Assert the consequence.

```python
import pytest
from unittest.mock import AsyncMock

from app.core.exceptions import NotFoundError
from app.repositories import agent_repo
from app.services.agent_registry import AgentRegistryService

pytestmark = pytest.mark.anyio


async def test_publishing_an_agent_with_an_unknown_capability_is_refused(
    monkeypatch, mock_db_session
):
    """The refusal has to happen at publish. At run time it is a broken agent
    in production instead of a red form in front of the person who made it."""
    monkeypatch.setattr(agent_repo, "get_by_id", AsyncMock(return_value=agent))
    with pytest.raises(BadRequestError) as exc:
        await service.publish(ctx, agent_id=agent.id)
    assert "unknown capability" in str(exc.value).lower()
```

## API — a route and its gate

The route layer has a failure unit tests cannot see: a route that forgets
`require(...)` or names the wrong permission breaks no unit test anywhere — the
service it calls is still tested, still correct, and now reachable by anyone.

`tests/api/test_platform_routes.py` builds callers from **synthetic roles** — one
holding exactly a single permission, and one holding every permission except one.
Driving it from `owner` and `viewer` would only show that some role is refused
somewhere; isolating one permission is what makes "gated on *this* permission and
nothing else" an assertion rather than a hope.

`TestEveryPlatformRouteIsGuarded` is the load-bearing test: it proves the *next*
route will have a gate at all. If it fails on a route you just added, decide which
half of the rule applies — collection route gets `require(...)`, per-resource route
gets none and hands the decision to a service (see the `permissions-rbac` skill).

```python
async def test_creating_an_agent_without_agents_edit_is_refused(client):
    app.dependency_overrides[deps.get_auth_context] = lambda: caller_without(Perm.AGENTS_EDIT)
    resp = await client.post("/api/v1/agents", json={...})
    assert resp.status_code == 403
```

## Integration — a schema guarantee

Everything here asserts something a mock cannot.

```python
async def test_two_default_profiles_in_one_org_are_refused(db: AsyncSession):
    """The partial unique index is the only thing preventing a second default,
    and a service that forgets to clear the old one is a normal mistake."""
    db.add(ModelProfile(organization_id=org.id, is_default=True, ...))
    db.add(ModelProfile(organization_id=org.id, is_default=True, ...))
    with pytest.raises(IntegrityError):
        await db.flush()
```

Reach for this layer for: `CHECK` constraints, partial unique indexes, cascade
behaviour, `NOT NULL` on org columns, and cross-tenant reads that should return
nothing.

## Migrations

`make test-migrations` applies and rolls back the whole chain against Postgres. It is
the only thing that proves `downgrade()` is real. Run it when you touch
`alembic/versions/` — see the `alembic-migration` skill.
