"""Aggregated criterion metadata is visible only with every contributing dataset."""

from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent
from app.db.models.dataset import Dataset
from app.db.models.skill_check import SkillCheckAgent
from app.services import skill_check
from app.services.skill_check import SkillCheckService, Stage

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "denied",
    [
        None,
        "runs",
        "dataset",
        "skill",
        "identity",
        "id_only",
        "id_only_readable",
        "missing_stage",
        "missing_run",
        "removed_history",
        "replaced_dataset",
    ],
)
async def test_criterion_metadata_requires_all_sources(monkeypatch, denied):
    source_id = uuid4()
    org = uuid4()
    ctx = AuthContext(user_id=uuid4(), organization_id=org, role="owner")
    agent = Agent(id=uuid4(), organization_id=org, name="Agent")
    dataset = Dataset(id=uuid4(), organization_id=org, name="Private", case_count=5)
    row = SkillCheckAgent(
        id=uuid4(),
        organization_id=org,
        check_id=uuid4(),
        agent_id=agent.id,
        agent_version=1,
        state="criteria_better",
        stages=[],
        skill_set_run_id=None,
        dataset_run_id=None if denied == "missing_run" else uuid4(),
        expected_usd=Decimal("0.1"),
        at_most_usd=Decimal("0.2"),
        criteria=[
            {
                "scorer": "judge",
                "name": "private rubric",
                "skill": "private skill",
                "skill_id": str(source_id),
                "graded": 5,
                "before": 0,
                "after": 5,
                "fixed": 5,
                "broken": 0,
            }
        ],
    )
    if denied == "identity":
        del row.criteria[0]["skill_id"]
    if denied in {"id_only", "id_only_readable"}:
        del row.criteria[0]["skill"]
    if denied in {"removed_history", "replaced_dataset"}:
        row.stages = [
            {
                "kind": "dataset",
                "dataset_id": str(uuid4()),
                "eval_run_id": str(uuid4() if denied == "removed_history" else row.dataset_run_id),
                "compared": 5,
                "fixed": 5,
                "broken": 0,
                "unchanged": 0,
                "unknown": 0,
            }
        ]
    monkeypatch.setattr(
        skill_check.agent_repo, "get_many", AsyncMock(return_value={agent.id: agent})
    )

    async def accessible(_db, _ctx, _rows, permission, **_kwargs):
        if permission == Perm.AGENTS_VIEW:
            return {agent.id}
        return set() if denied == "dataset" else {dataset.id}

    monkeypatch.setattr(skill_check, "accessible_ids", accessible)
    monkeypatch.setattr(
        skill_check,
        "readable_criterion_skill_ids",
        AsyncMock(return_value=set() if denied in {"skill", "id_only"} else {source_id}),
    )
    if denied == "runs":
        ctx = replace(ctx, key_scopes=frozenset({Perm.AGENTS_VIEW, Perm.DATASETS_VIEW}))
    stages = {agent.id: [] if denied == "missing_stage" else [Stage("dataset", dataset)]}
    reads, hidden, _ = await SkillCheckService(AsyncMock())._agent_reads(ctx, [row], stages)
    assert hidden == 0
    assert bool(reads[0].criteria) is (denied in {None, "id_only_readable"})
    assert row.criteria[0]["name"] == "private rubric"
    if denied not in {None, "id_only_readable"}:
        assert "private rubric" not in reads[0].model_dump_json()
        assert "private skill" not in reads[0].model_dump_json()
