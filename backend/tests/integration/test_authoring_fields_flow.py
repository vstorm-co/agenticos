"""Field changes end to end: what is staged, what is refused, and who may accept what.

- The improver reads the configuration and proposes changes to its fields; a
  change that is not a target, loosens approval, or adds something the person
  who asked may not grant is never staged.
- A capability it adds arrives with its writing tools gated, and the card names
  them; a change of model says what a run would cost on each.
- Accept writes the draft as the person accepting it: something they may not
  grant is refused, and a change of model waits for a check that shows it pays off.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import OrgRoleName
from app.db.models.agent_run import AgentRun
from app.db.models.authoring import SpecProposalHunk
from app.db.models.credential import ModelProfile
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.organization import OrganizationMember
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.schemas.authoring import AuthoringStart, HunkDecision
from app.services.authoring import AuthoringService
from tests.integration.test_authoring import (
    COMMENT,
    Improver,
    _environment,  # noqa: F401 - the autouse fixture that scripts the improver's model
    _improve,
    _member,
    _setup,
)

pytestmark = pytest.mark.anyio


async def _collection(db, ctx, *, personal: bool = False, visibility: str = "org") -> KnowledgeBase:
    """An organization's collection, or one of the caller's own no agent may bind."""
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name=f"Docs {uuid.uuid4().hex[:6]}",
        scope=KBScope.PERSONAL.value if personal else KBScope.ORG.value,
        organization_id=None if personal else ctx.organization_id,
        collection_name=f"c_{uuid.uuid4().hex[:12]}",
        embedding_model="text-embedding-3-small",
        embedding_dim=1536,
        visibility="private" if personal else visibility,
        owner_user_id=ctx.user_id,
    )
    db.add(kb)
    await db.flush()
    return kb


async def _profile(db, ctx, model: str) -> ModelProfile:
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        label=model,
        provider="openai",
        model=model,
    )
    db.add(profile)
    await db.flush()
    return profile


def _change(run_id: str, path: str, op: str, value: Any) -> dict[str, Any]:
    return {
        "path": path,
        "op": op,
        "value": value,
        "rationale": "The evidence asks for it",
        "expected_effect": "Fewer wrong windows, the same cost",
        "evidence": [{"run_id": run_id, "quote": COMMENT}],
    }


def _improver(
    db, run_id: str, fields: list[dict[str, Any]], *, instructions: list[Any] | None = None
) -> Improver:
    return Improver(
        db,
        improve={
            "summary": "s",
            "expected_effect": "e",
            "instructions": instructions or [],
            "tools": [],
            "fields": fields,
        },
    )


async def test_what_may_be_staged_is_staged_and_the_rest_is_only_counted(db):
    ctx, agent, run = await _setup(db)
    shared = await _collection(db, ctx)
    private = await _collection(db, ctx, personal=True)
    run_id = str(run.id)
    model = _improver(
        db,
        run_id,
        [
            _change(run_id, "model_settings/temperature", "set", 0.2),
            _change(run_id, "collection_ids", "add", str(shared.id)),
            _change(run_id, "collection_ids", "add", str(private.id)),
            _change(run_id, "capabilities", "add", {"id": "artifacts"}),
            _change(run_id, "budget/monthly_usd", "set", 50),
            _change(run_id, "capabilities/charts/approval", "set", "never"),
        ],
        instructions=[{"old_text": "Be brief.", "new_text": "Be concise.", "rationale": "r"}],
    )

    request = await _improve(db, ctx, agent, model)

    assert request.report is not None
    assert (request.report["proposed"], request.report["recorded"]) == (7, 4)
    assert "# Its configuration" in model.prompts[-1]
    assert shared.name in model.prompts[-1] and private.name in model.prompts[-1]
    batch = (await AuthoringService(db).for_agent(ctx, agent.id)).batch
    assert batch is not None
    by_path = {(hunk.path, str(hunk.new_value)): hunk for hunk in batch.hunks}
    added = next(hunk for hunk in batch.hunks if hunk.path == "capabilities")
    assert added.new_value["tool_approval"] == {"publish_artifact": "required"}
    assert added.effect == {"writes": ["publish_artifact"]}
    assert added.names == {"artifacts": "Apps"}
    assert by_path[("collection_ids", str(shared.id))].names == {str(shared.id): shared.name}
    assert by_path[(None, "None")].names == {}
    temperature = by_path[("model_settings/temperature", "0.2")]
    assert temperature.expected_effect == "Fewer wrong windows, the same cost"
    assert temperature.evidence[0].quote == COMMENT


async def test_the_person_who_asked_only_stages_what_they_may_grant(db):
    owner, agent, run = await _setup(db)
    builder = await _member(db, owner, OrgRoleName.BUILDER)
    private = await _collection(db, owner, personal=True)
    run_id = str(run.id)
    model = _improver(db, run_id, [_change(run_id, "collection_ids", "add", str(private.id))])

    request = await _improve(db, builder, agent, model)

    assert request.status == "completed", request.error
    assert request.report is not None and request.report["recorded"] == 0
    assert private.name not in model.prompts[-1]


async def test_accept_writes_the_draft_as_the_person_accepting_it(db):
    owner, agent, run = await _setup(db)
    builder = await _member(db, owner, OrgRoleName.MEMBER)
    db.add(
        ResourceGrant(
            organization_id=owner.organization_id,
            subject_user_id=builder.user_id,
            resource_type="agent",
            resource_id=agent.id,
            level=GrantLevel.EDIT.value,
        )
    )
    shared = await _collection(db, owner)
    private = await _collection(db, owner, visibility="private")
    run_id = str(run.id)
    model = _improver(
        db,
        run_id,
        [
            _change(run_id, "model_settings/temperature", "set", 0.2),
            _change(run_id, "collection_ids", "add", str(shared.id)),
            _change(run_id, "collection_ids", "add", str(private.id)),
        ],
    )
    await _improve(db, owner, agent, model)
    service = AuthoringService(db)
    batch = (await service.for_agent(owner, agent.id)).batch
    assert batch is not None
    temperature, open_one, closed_one = batch.hunks

    edited = await service.decide(
        builder, agent.id, temperature.id, HunkDecision(action="accept", value=0.3)
    )
    assert edited.draft_spec["model_settings"]["temperature"] == 0.3
    added = await service.decide(builder, agent.id, open_one.id, HunkDecision(action="accept"))
    assert str(shared.id) in [str(item) for item in added.draft_spec["collection_ids"]]
    with pytest.raises(AuthorizationError, match="may not grant"):
        await service.decide(builder, agent.id, closed_one.id, HunkDecision(action="accept"))

    undone = await service.decide(builder, agent.id, temperature.id, HunkDecision(action="undo"))
    assert undone.draft_spec.get("model_settings", {}).get("temperature") is None
    await service.decide(builder, agent.id, open_one.id, HunkDecision(action="undo"))
    with pytest.raises(BadRequestError, match="single setting or a text"):
        await service.decide(
            builder, agent.id, open_one.id, HunkDecision(action="accept", value="x")
        )
    with pytest.raises(BadRequestError, match="cannot be accepted"):
        await service.decide(
            builder, agent.id, temperature.id, HunkDecision(action="accept", value=9)
        )
    agent.draft_spec = {**agent.draft_spec, "model_settings": {"temperature": 1.0}}
    await db.flush()
    with pytest.raises(BadRequestError, match="no longer fits"):
        await service.decide(builder, agent.id, temperature.id, HunkDecision(action="accept"))
    read = await service.for_agent(builder, agent.id)
    assert read.batch is not None
    assert {hunk.id: hunk.names for hunk in read.batch.hunks}[closed_one.id] == {}


async def test_a_change_of_model_says_what_a_run_costs_and_waits_for_a_check(db):
    ctx, agent, run = await _setup(db)
    cheap = await _profile(db, ctx, "gpt-4o-mini")
    dear = await _profile(db, ctx, "gpt-4o")
    agent.draft_spec = {**agent.draft_spec, "model_profile_id": str(dear.id)}
    stored = await db.scalar(select(AgentRun).where(AgentRun.id == run.id))
    assert stored is not None
    stored.input_tokens, stored.output_tokens = 2000, 500
    await db.flush()
    run_id = str(run.id)
    model = _improver(db, run_id, [_change(run_id, "model_profile_id", "set", str(cheap.id))])

    await _improve(db, ctx, agent, model)

    service = AuthoringService(db)
    batch = (await service.for_agent(ctx, agent.id)).batch
    assert batch is not None
    (hunk,) = batch.hunks
    assert hunk.effect is not None
    assert (hunk.effect["runs"], hunk.effect["rough"]) == (1, True)
    before, after = hunk.effect["cost_per_run_before"], hunk.effect["cost_per_run_after"]
    assert isinstance(before, str) and isinstance(after, str) and float(after) < float(before)
    assert hunk.names == {str(dear.id): "gpt-4o", str(cheap.id): "gpt-4o-mini"}
    assert hunk.blocked == "check_first"
    with pytest.raises(BadRequestError, match="Check with evals"):
        await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
    with patch.object(AuthoringService, "_model_gate", new=AsyncMock(return_value=None)):
        accepted = await service.decide(ctx, agent.id, hunk.id, HunkDecision(action="accept"))
    assert accepted.draft_spec["model_profile_id"] == str(cheap.id)
    assert (
        await db.scalar(
            select(OrganizationMember.role).where(OrganizationMember.user_id == ctx.user_id)
        )
        == "owner"
    )


async def test_verify_reads_the_edit_to_the_configuration(db):
    ctx, agent, run = await _setup(db)
    agent.draft_spec = {**agent.draft_spec, "max_steps": 40}
    await db.flush()
    run_id = str(run.id)
    model = Improver(
        db,
        verify={
            "findings": [],
            "instructions": [],
            "fields": [_change(run_id, "max_steps", "set", 20)],
        },
    )

    request = await _improve(db, ctx, agent, model, kind="verify")

    assert request.status == "completed", request.error
    assert "~ max_steps: null\n  now: 40" in model.prompts[-1]
    batch = (await AuthoringService(db).for_agent(ctx, agent.id)).batch
    assert batch is not None
    assert [(hunk.path, hunk.base_value, hunk.new_value) for hunk in batch.hunks] == [
        ("max_steps", 40, 20)
    ]
    assert AuthoringStart(kind="verify").kind == "verify"


async def test_a_safeguard_is_not_staged_and_a_stored_removal_is_never_accepted(db):
    ctx, agent, run = await _setup(db)
    agent.draft_spec = {
        **agent.draft_spec,
        "capabilities": [*agent.draft_spec["capabilities"], {"id": "guardrails", "config": {}}],
    }
    await db.flush()
    run_id = str(run.id)
    model = _improver(
        db,
        run_id,
        [
            _change(run_id, "capabilities", "remove", {"id": "guardrails"}),
            _change(run_id, "capabilities/guardrails/config", "set", {"input": {}}),
            _change(run_id, "capabilities", "remove", {"id": "charts"}),
        ],
    )

    await _improve(db, ctx, agent, model)

    rows = list(
        await db.scalars(select(SpecProposalHunk).where(SpecProposalHunk.path.is_not(None)))
    )
    (row,) = rows
    assert row.base_value["id"] == "charts"
    row.base_value = {**row.base_value, "id": "guardrails"}
    await db.flush()
    with pytest.raises(BadRequestError, match="safeguard"):
        await AuthoringService(db).decide(ctx, agent.id, row.id, HunkDecision(action="accept"))


async def test_a_stored_change_to_subagents_is_never_accepted(db):
    """Their configuration holds whole agents, so a row written before the rule - or
    since - is refused at Accept as staging refuses it."""
    ctx, agent, run = await _setup(db)
    run_id = str(run.id)
    model = _improver(
        db,
        run_id,
        [
            _change(run_id, "capabilities/subagents/config", "set", {"inline": []}),
            _change(run_id, "capabilities", "add", {"id": "subagents", "config": {}}),
            _change(run_id, "capabilities", "remove", {"id": "charts"}),
        ],
    )

    await _improve(db, ctx, agent, model)

    (row,) = list(
        await db.scalars(select(SpecProposalHunk).where(SpecProposalHunk.path.is_not(None)))
    )
    row.path, row.op, row.base_value, row.new_value = (
        "capabilities/subagents/config",
        "set",
        {},
        {"inline": []},
    )
    await db.flush()
    with pytest.raises(BadRequestError, match="may not propose"):
        await AuthoringService(db).decide(ctx, agent.id, row.id, HunkDecision(action="accept"))
