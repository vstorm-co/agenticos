"""Discovery serves only exact applied versions under current binding and output bounds."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agents.capabilities.skills._log import ServedSkill, SkillUseLog
from app.core.browser_teaching import TeachingRefused
from app.services.browser_teaching import _discovery
from tests.integration.test_browser_teaching import applied_binding
from tests.integration.test_browser_teaching import draft_runtime as draft_runtime
from tests.integration.test_browser_teaching import teaching as teaching
from tests.test_browser_teaching_contracts import ORIGIN, SECRET

pytestmark = [pytest.mark.anyio, pytest.mark.security]


@pytest.mark.parametrize(
    "case, expected",
    [
        ("unbound", False),
        ("main", True),
        ("unbound_fork", False),
        ("same_fork", True),
        ("different_fork", False),
        ("same_version", True),
        ("different_version", False),
        ("pinned_main_with_fork", False),
    ],
)
def test_exact_main_fork_or_pinned_version_binding_is_required(case, expected):
    skill, fork = uuid4(), uuid4()
    version = SimpleNamespace(skill_id=skill, fork_id=None, number=3)
    spec = SimpleNamespace(skill_ids=[skill], skill_bindings=[])
    if case == "unbound":
        spec.skill_ids = []
    elif case == "unbound_fork":
        version.fork_id = fork
    elif case in {"same_fork", "different_fork"}:
        version.fork_id = fork
        spec.skill_bindings = [
            SimpleNamespace(
                skill_id=skill, fork_id=fork if case == "same_fork" else uuid4(), version=None
            )
        ]
    elif case in {"same_version", "different_version", "pinned_main_with_fork"}:
        spec.skill_bindings = [
            SimpleNamespace(
                skill_id=skill, fork_id=None, version=3 if case != "different_version" else 2
            )
        ]
        if case == "pinned_main_with_fork":
            version.fork_id = fork
    assert _discovery.on_bound_line(spec, version) is expected


@pytest.mark.parametrize(
    "gate",
    [
        "log",
        "organization",
        "run",
        "agent",
        "signed_in",
        "private",
        "person",
        "user_mismatch",
    ],
)
async def test_incomplete_execution_identity_is_refused_before_any_database_lookup(gate):
    user, agent = uuid4(), uuid4()
    audience = SimpleNamespace(
        user_id=user, browses_signed_in=True, private=True, shared_transcript=False
    )
    deps = SimpleNamespace(
        organization_id=uuid4(),
        run_id=uuid4(),
        agent_id=agent,
        user_id=str(user),
        run_person=user,
        audience=audience,
        impersonated=False,
        delegated=False,
    )
    log = SkillUseLog(agent_id=agent, served={})
    if gate == "log":
        log = None
    elif gate in {"organization", "run", "agent"}:
        setattr(deps, gate + "_id", None)
    elif gate == "signed_in":
        audience.browses_signed_in = False
    elif gate == "private":
        audience.private = False
    elif gate == "person":
        audience.user_id = None
    else:
        deps.user_id = str(uuid4())
    db = AsyncMock()
    with pytest.raises(TeachingRefused):
        await _discovery.discover(db, deps, log, ORIGIN)
    assert not db.mock_calls


@pytest.mark.parametrize(
    "case",
    [
        "unserved",
        "ordinary_version",
        "missing_proposal_id",
        "missing_metadata",
        "missing_skill",
        "missing_proposal",
        "wrong_proposal_source",
        "wrong_proposal_skill",
        "description",
        "invalid_procedure",
    ],
)
async def test_missing_or_invalid_immutable_provenance_is_never_discoverable(
    teaching, draft_runtime, monkeypatch, case
):
    t = teaching
    skill, version, proposal, log = await applied_binding(t, draft_runtime)
    if case == "unserved":
        log.served = {skill.name: ServedSkill(skill.id, None)}
    elif case in {"ordinary_version", "missing_proposal_id", "missing_metadata"}:
        fields = (
            "id",
            "skill_id",
            "source",
            "proposal_id",
            "browser_procedure",
            "fork_id",
            "number",
            "content",
            "description",
        )
        observed = SimpleNamespace(**{key: getattr(version, key) for key in fields})
        if case == "ordinary_version":
            observed.source = "edit"
        elif case == "missing_proposal_id":
            observed.proposal_id = None
        else:
            observed.browser_procedure = None
        monkeypatch.setattr(
            _discovery.version_repo, "get_versions", AsyncMock(return_value={version.id: observed})
        )
    elif case == "missing_skill":
        monkeypatch.setattr(_discovery.skill_repo, "get", AsyncMock(return_value=None))
    elif case == "missing_proposal":
        monkeypatch.setattr(_discovery.proposal_repo, "get", AsyncMock(return_value=None))
    elif case in {"wrong_proposal_source", "wrong_proposal_skill"}:
        fields = ("status", "source", "skill_id", "browser_procedure", "content", "description")
        observed = SimpleNamespace(**{key: getattr(proposal, key) for key in fields})
        if case == "wrong_proposal_source":
            observed.source = "workspace"
        else:
            observed.skill_id = uuid4()
        monkeypatch.setattr(_discovery.proposal_repo, "get", AsyncMock(return_value=observed))
    elif case == "description":
        proposal.description = "Changed after approval"
    else:
        version.browser_procedure = proposal.browser_procedure = {"invalid": SECRET}
    await t.db.flush()
    assert await _discovery.discover(t.db, t.deps(), log, ORIGIN) == ()


@pytest.mark.parametrize("bound", ["bytes", "results", "candidates"])
async def test_discovery_bounds_output_and_candidate_work_before_serving(
    teaching, draft_runtime, monkeypatch, bound
):
    t = teaching
    skill, version, _, log = await applied_binding(t, draft_runtime)
    if bound == "bytes":
        monkeypatch.setattr(_discovery, "MAX_EVENT_BYTES", 1)
        assert await _discovery.discover(t.db, t.deps(), log, ORIGIN) == ()
    elif bound == "results":
        monkeypatch.setattr(_discovery, "MAX_RESULTS", 1)
        log.served = {
            "first": ServedSkill(skill.id, version.id),
            "second": ServedSkill(skill.id, version.id),
        }
        found = await _discovery.discover(t.db, t.deps(), log, ORIGIN)
        assert len(found) == 1 and found[0].skill_name == "first"
    else:
        monkeypatch.setattr(_discovery, "MAX_CANDIDATES", 1)
        log.served = {
            "first": ServedSkill(skill.id, None),
            "second": ServedSkill(skill.id, version.id),
        }
        assert await _discovery.discover(t.db, t.deps(), log, ORIGIN) == ()
