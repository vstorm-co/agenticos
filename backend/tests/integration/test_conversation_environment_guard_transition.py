"""A legal STARTING→READY commit must not cause the live guard to dispose its context."""

import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.capabilities.browser_use._page import BrowserTarget
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.core.config import settings
from app.core.permissions import AuthContext
from app.db.models.agent import AgentVersion
from app.db.models.conversation_environment import ConversationEnvironment
from app.db.models.organization import OrganizationMember
from app.services import conversation_environment_browser as browser
from app.services.conversation_environment_policy import authority, settings_for
from app.services.conversation_environment_resources import BrowserEnvironmentResource
from app.services.conversation_environments import ConversationEnvironmentService
from tests.integration.test_conversation_environments import environment, identities

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "transition",
    [
        "ready",
        "deleted",
        "expired",
        "revision",
        "target_removed",
        "member_revoked",
        "binding_changed",
    ],
)
async def test_guard_rechecks_ready_transition_in_a_fresh_transaction_without_losing_authority(
    db: AsyncSession, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, transition: str
) -> None:
    monkeypatch.setattr(settings, "BROWSER_CDP_ALLOWED_HOSTS", ["browser"])
    monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "http://browser:9222")
    user, org, conversation, agent = await identities(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    spec = AgentSpec(
        name="Browser",
        instructions="Keep this live page",
        capabilities=[
            CapabilityBindingSpec(id="browser_use", config={"session_lifetime": "conversation"})
        ],
    )
    version = AgentVersion(
        id=uuid4(),
        organization_id=org.id,
        agent_id=agent.id,
        version=1,
        spec=spec.model_dump(mode="json"),
        published_by_user_id=user.id,
    )
    db.add(version)
    await db.flush()
    agent.current_version_id = version.id
    ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
    admitted = await authority(db, ctx, conversation_id=conversation.id, agent_id=agent.id)
    resolved = await settings_for(db, admitted, "browser")
    row = environment(user, org, conversation, agent)
    row.agent_version_id, row.fingerprint, row.provisioning_attempt = (
        version.id,
        resolved.fingerprint,
        1,
    )
    db.add(row)
    await db.flush()
    target = BrowserTarget(context_id="same-owned-context", target_id="same-live-target")
    resource = BrowserEnvironmentResource(
        environment_id=row.id,
        organization_id=org.id,
        cdp_url="http://browser:9222",
        tabs={"main": target},
    )
    service = ConversationEnvironmentService(db)
    payload = service.payload(row)
    assert await service.store_resource(payload, 1, resource, "physical-browser")
    await db.commit()

    factory = async_sessionmaker(engine, expire_on_commit=False)
    claim_entered, proceed = anyio.Event(), anyio.Event()
    original_claim = ConversationEnvironmentService.claim
    claim_results = []

    @asynccontextmanager
    async def session():
        async with factory.begin() as fresh:
            yield fresh

    async def paused_claim(self, requested, attempt):
        assert requested == payload
        claim_entered.set()
        await proceed.wait()
        result = await original_claim(self, requested, attempt)
        claim_results.append(result)
        return result

    monkeypatch.setattr(browser, "get_worker_db_context", session)
    monkeypatch.setattr(ConversationEnvironmentService, "claim", paused_claim)
    guard = asyncio.create_task(browser._still_owned(payload, target))
    try:
        with anyio.fail_after(5):
            await claim_entered.wait()
        async with factory.begin() as writer:
            concurrent = ConversationEnvironmentService(writer)
            assert await concurrent.ready(payload, 1)
            current = await writer.get(ConversationEnvironment, payload.environment_id)
            assert current is not None and current.state == "ready"
            if transition == "deleted":
                await writer.delete(current)
            elif transition == "expired":
                await concurrent.expire(current)
            elif transition == "revision":
                current.revision += 1
            elif transition == "target_removed":
                await concurrent.replace_resource(current, resource.model_copy(update={"tabs": {}}))
            elif transition == "member_revoked":
                await writer.execute(
                    delete(OrganizationMember).where(
                        OrganizationMember.organization_id == org.id,
                        OrganizationMember.user_id == user.id,
                    )
                )
            elif transition == "binding_changed":
                changed = spec.model_copy(
                    update={
                        "capabilities": [
                            CapabilityBindingSpec(
                                id="browser_use",
                                config={
                                    "session_lifetime": "conversation",
                                    "allowed_domains": ["example.com"],
                                },
                            )
                        ]
                    }
                )
                next_version = AgentVersion(
                    id=uuid4(),
                    organization_id=org.id,
                    agent_id=agent.id,
                    version=2,
                    spec=changed.model_dump(mode="json"),
                    published_by_user_id=user.id,
                )
                writer.add(next_version)
                await writer.flush()
                current_agent = await writer.get(type(agent), agent.id)
                assert current_agent is not None
                current_agent.current_version_id = next_version.id
        proceed.set()
        with anyio.fail_after(5):
            assert await guard is (transition == "ready")
        assert claim_results == [None]
        async with factory() as check:
            saved = await check.get(ConversationEnvironment, payload.environment_id)
            if transition == "ready":
                assert saved is not None and saved.state == "ready"
                assert ConversationEnvironmentService(check).resource(saved, org.id) == resource
    finally:
        proceed.set()
        if not guard.done():
            guard.cancel()
        await asyncio.gather(guard, return_exceptions=True)
