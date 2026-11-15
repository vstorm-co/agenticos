"""Discard model output when one of its evidence sources was erased in flight."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.background import discard_deferred
from app.core.permissions import OrgRoleName
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import AuthoringRequest, SpecProposalHunk
from app.db.models.context import ContextFile
from app.db.models.context_proposal import ContextProposal
from app.db.models.run_manifest import RunManifest
from app.db.models.skill import Skill
from app.db.models.skill_proposal import SkillProposal
from app.db.models.user import User
from app.schemas.authoring import AuthoringStart, ImprovementProposal, VerifyReport
from app.services.authoring import AuthoringService
from app.services.authoring_evidence import EvidenceService
from app.services.authoring_worker import AuthoringRun, AuthoringWorker
from app.services.user import UserService
from tests.integration.test_authoring import (
    _environment,  # noqa: F401 - no external model or notification calls
    _member,
    _rated,
    _setup,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]
MARKER = "private evidence belongs to the erased source"


@pytest.mark.parametrize("target", ["agent", "verify", "skill", "context"])
@pytest.mark.parametrize(
    ("erase_source", "model_fails"), [(True, False), (True, True), (False, True)]
)
async def test_erasure_during_model_call_discards_the_entire_result(
    engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    erase_source: bool,
    model_fails: bool,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        ctx, agent, _ = await _setup(db)
        source = await _member(db, ctx, OrgRoleName.MEMBER)
        source_run = await _rated(db, source, agent, comment=MARKER)
        pack = await EvidenceService(db).for_agent(ctx, agent.id, window_days=30)
        assert len(pack.runs) == 2
        monkeypatch.setattr(EvidenceService, "for_skill", AsyncMock(return_value=pack))
        monkeypatch.setattr(EvidenceService, "for_context", AsyncMock(return_value=pack))
        service = AuthoringService(db)
        if target in {"skill", "context"}:
            values = {
                "organization_id": ctx.organization_id,
                "owner_user_id": ctx.user_id,
                "name": "returns",
                "description": "Returns",
                "content": "Returns take 90 days.",
            }
            if target == "skill":
                resource = Skill(**values, visibility="org")
                db.add(resource)
                await db.flush()
                started = await service.start_skill(ctx, resource.id, AuthoringStart())
            else:
                resource = ContextFile(**values, mode="inject")
                db.add(resource)
                await db.flush()
                started = await service.start_context(ctx, resource.id, AuthoringStart())
        else:
            if target == "verify":
                agent.draft_spec = {
                    **agent.draft_spec,
                    "instructions": "Be brief. Explain returns.",
                }
                await db.flush()
            started = await service.start_agent(
                ctx, agent.id, AuthoringStart(kind="verify" if target == "verify" else "improve")
            )
        source_id, source_run_id, agent_id, request_id = (
            source.user_id,
            source_run.id,
            agent.id,
            started.id,
        )
        assert source_id is not None
        await db.commit()
        discard_deferred(db)
    produced, release = asyncio.Event(), asyncio.Event()
    helper_ids: list[UUID] = []

    async def ask[T: BaseModel](run: AuthoringRun, prompt: str, output_type: type[T]) -> T:
        assert MARKER in prompt
        helper = AgentRun(
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            user_id=ctx.user_id,
            surface="eval",
            status="completed",
            cost_usd=Decimal("0.02"),
            started_at=datetime.now(UTC),
        )
        run.db.add(helper)
        await run.db.flush()
        run.db.add(
            RunManifest(
                run_id=helper.id,
                organization_id=ctx.organization_id,
                payload={"instructions": MARKER, "messages": [MARKER]},
            )
        )
        await run._count(helper.id, helper.cost_usd)
        helper_ids.append(helper.id)
        evidence = [{"run_id": str(source_run_id), "quote": MARKER}]
        if output_type is ImprovementProposal:
            payload = {
                "summary": MARKER,
                "expected_effect": MARKER,
                "instructions": [
                    {"old_text": "Be brief.", "new_text": MARKER, "rationale": MARKER}
                ],
            }
        elif output_type is VerifyReport:
            payload = {"findings": [{"verdict": "risk", "text": MARKER, "evidence": evidence}]}
        else:
            payload = {
                "summary": MARKER,
                "expected_effect": MARKER,
                "description": MARKER,
                "content": MARKER,
                "rationale": MARKER,
                "evidence": evidence,
            }
        result = output_type.model_validate(payload)
        produced.set()
        await release.wait()
        if model_fails:
            raise RuntimeError(MARKER)
        return result

    monkeypatch.setattr(AuthoringRun, "_ask", ask)

    @asynccontextmanager
    async def worker_session() -> AsyncIterator[AsyncSession]:
        async with sessions() as db:
            try:
                yield db
                await db.commit()
            finally:
                discard_deferred(db)

    async with asyncio.timeout(15), asyncio.TaskGroup() as tasks:
        tasks.create_task(
            AuthoringWorker(request_id, ctx.organization_id, sessions=worker_session).run()
        )
        await produced.wait()
        if erase_source:
            async with sessions() as erasure:
                await UserService(erasure).delete(source_id)
                await erasure.commit()
                discard_deferred(erasure)
        release.set()
    async with sessions() as db:
        assert (await db.get(User, source_id) is None) == erase_source
        request = await db.get(AuthoringRequest, request_id)
        assert request is not None and request.status == "failed"
        assert request.error is not None
        assert ("evidence source was erased" in request.error) == erase_source
        assert MARKER not in request.error
        assert request.report is None and request.cost_usd == Decimal("0.02")
        for model in (SpecProposalHunk, SkillProposal, ContextProposal):
            assert await db.scalar(select(func.count()).select_from(model)) == 0
        assert len(helper_ids) == 1
        manifest = await db.scalar(select(RunManifest).where(RunManifest.run_id == helper_ids[0]))
        assert manifest is not None
        if erase_source:
            assert manifest.payload == {} and manifest.truncated
        else:
            assert manifest.payload["instructions"] == MARKER
        helper = await db.get(AgentRun, helper_ids[0])
        assert helper is not None and helper.cost_usd == Decimal("0.02")
