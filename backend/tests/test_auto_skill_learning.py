"""Tests for applying stored, human-approved skill proposals.

The things worth guarding: only an applied proposal for this skill is used,
caller text cannot replace its approved content, audit details come from the
proposal and its ledger entry, and learning twice remains a no-op. No database
here: the skill catalog and registry are fakes, and the audit trail is a mock.
"""

import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm, role_has
from app.db.models.skill import Skill
from app.schemas.auto_skill_learning import LearnSkillCreate
from app.services.auto_skill_learning import AutoSkillLearningService

pytestmark = pytest.mark.anyio

NEW_TEXT = "# Refunds\n\nCheck the order first, then the tracking number."
BASE_TEXT = "# Refunds\n\nCheck the order first."
OTHER_TEXT = "# Refunds\n\nRefund everything, no questions asked."
_PROPOSAL_INPUTS: dict[UUID, LearnSkillCreate] = {}
_LEDGER_PATTERN_KEYS: dict[UUID, str | None] = {}


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _ctx() -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)


def _row(name: str, content: str, *, version: int = 1, category: str | None = None) -> Skill:
    return Skill(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name=name,
        description="How refunds are handled.",
        content=content,
        category=category,
        version=version,
    )


def _proposal(**overrides: object) -> LearnSkillCreate:
    values: dict[str, object] = {
        "proposal_id": uuid.uuid4(),
        "skill_id": uuid.uuid4(),
        "content": NEW_TEXT,
        "rationale": "Refunds kept failing when tracking was missing.",
        "ledger_entry_id": uuid.uuid4(),
        "pattern_key": "failed:ModelHTTPError:400",
        "base_content_sha256": _sha256(BASE_TEXT),
    }
    values.update(overrides)
    data = LearnSkillCreate(**values)  # type: ignore[arg-type]
    _PROPOSAL_INPUTS[data.proposal_id] = data
    if data.ledger_entry_id is not None:
        _LEDGER_PATTERN_KEYS[data.ledger_entry_id] = data.pattern_key
    return data


class _Registry:
    """An agent the caller may view, or none at all."""

    def __init__(self, *, found: bool = True) -> None:
        self.found = found
        self.calls: list[UUID] = []

    async def get(self, ctx: AuthContext, agent_id: UUID, **_kwargs: object) -> object:
        self.calls.append(agent_id)
        if not self.found:
            raise NotFoundError(message="Agent not found", details={"agent_id": str(agent_id)})
        return object()


class _Skills:
    """The one skill writer, faked: create and update behave like the real one."""

    def __init__(self, skills: list[Skill] | None = None) -> None:
        self.by_id: dict[UUID, Skill] = {skill.id: skill for skill in skills or []}
        self.created: list[Skill] = []
        self.create_calls = 0
        self.updated: list[Skill] = []

    async def get(self, ctx: AuthContext, skill_id: UUID, **_kwargs: object) -> Skill:
        skill = self.by_id.get(skill_id)
        if skill is None:
            raise NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
        if _kwargs.get("perm") is Perm.SKILLS_EDIT and not ctx.has(Perm.SKILLS_EDIT):
            raise NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
        return skill

    async def create(self, ctx: AuthContext, **kwargs: object) -> Skill:
        self.create_calls += 1
        skill = _row(
            str(kwargs["name"]),
            str(kwargs["content"]),
            category=kwargs.get("category"),  # type: ignore[arg-type]
        )
        skill.description = str(kwargs["description"])
        self.by_id[skill.id] = skill
        self.created.append(skill)
        return skill

    async def update(self, ctx: AuthContext, skill_id: UUID, data: object) -> Skill:
        skill = self.by_id[skill_id]
        skill.content = str(data.content)
        skill.version += 1
        self.updated.append(skill)
        return skill


@pytest.fixture
def _service(monkeypatch: pytest.MonkeyPatch) -> AutoSkillLearningService:
    _PROPOSAL_INPUTS.clear()
    _LEDGER_PATTERN_KEYS.clear()
    service = AutoSkillLearningService(AsyncMock())
    service.registry = _Registry()
    service.skills = _Skills()
    audit = AsyncMock()
    monkeypatch.setattr("app.services.auto_skill_learning.record_audit", audit)
    service.audit = audit  # type: ignore[attr-defined]

    async def get_proposal(_db: object, proposal_id: UUID, **_kwargs: UUID) -> SimpleNamespace:
        data = _PROPOSAL_INPUTS[proposal_id]
        return SimpleNamespace(
            id=proposal_id,
            status="applied",
            target_type="skill",
            skill_id=data.skill_id,
            reverted_at=None,
            new_text=data.content,
            applied_content_sha256=_sha256(data.content),
            base_content_sha256=data.base_content_sha256,
            rationale=data.rationale,
            ledger_entry_id=data.ledger_entry_id,
        )

    async def get_entry(_db: object, entry_id: UUID, **_kwargs: UUID) -> SimpleNamespace | None:
        if entry_id not in _LEDGER_PATTERN_KEYS:
            return None
        return SimpleNamespace(pattern_key=_LEDGER_PATTERN_KEYS[entry_id])

    monkeypatch.setattr(
        "app.services.auto_skill_learning.failure_learning_repo.get_proposal", get_proposal
    )
    monkeypatch.setattr(
        "app.services.auto_skill_learning.failure_learning_repo.get_entry", get_entry
    )
    return service


async def test_a_proposal_without_an_existing_skill_target_is_not_accepted(
    _service: AutoSkillLearningService,
) -> None:
    with pytest.raises(NotFoundError, match="Applied skill proposal not found"):
        await _service.learn(_ctx(), uuid.uuid4(), _proposal(skill_id=None, name="refund-tracking"))

    assert _service.skills.create_calls == 0  # type: ignore[attr-defined]
    _service.audit.assert_not_awaited()  # type: ignore[attr-defined]


async def test_a_viewer_cannot_learn_into_an_existing_skill(
    _service: AutoSkillLearningService,
) -> None:
    skill = _row("refunds", BASE_TEXT)
    _service.skills = _Skills([skill])  # type: ignore[attr-defined]
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.VIEWER)
    assert not role_has(OrgRoleName.VIEWER, Perm.SKILLS_EDIT)

    with pytest.raises(NotFoundError):
        await _service.learn(
            ctx, uuid.uuid4(), _proposal(skill_id=skill.id, base_content_sha256=_sha256(BASE_TEXT))
        )

    assert _service.skills.created == []  # type: ignore[attr-defined]
    assert _service.skills.updated == []  # type: ignore[attr-defined]
    _service.audit.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.security
async def test_a_caller_cannot_assert_an_unstored_proposal(
    _service: AutoSkillLearningService, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _proposal(skill_id=uuid.uuid4())
    monkeypatch.setattr(
        "app.services.auto_skill_learning.failure_learning_repo.get_proposal",
        AsyncMock(return_value=None),
    )

    with pytest.raises(NotFoundError, match="Applied skill proposal not found"):
        await _service.learn(_ctx(), uuid.uuid4(), data)

    assert _service.skills.created == []  # type: ignore[attr-defined]
    _service.audit.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.security
async def test_only_an_applied_skill_proposal_can_be_learned(
    _service: AutoSkillLearningService, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _proposal()
    proposal = SimpleNamespace(
        id=data.proposal_id,
        status="draft",
        target_type="skill",
        skill_id=data.skill_id,
        reverted_at=None,
        new_text=data.content,
        applied_content_sha256=_sha256(data.content),
        base_content_sha256=data.base_content_sha256,
        rationale=data.rationale,
        ledger_entry_id=data.ledger_entry_id,
    )
    monkeypatch.setattr(
        "app.services.auto_skill_learning.failure_learning_repo.get_proposal",
        AsyncMock(return_value=proposal),
    )

    with pytest.raises(NotFoundError, match="Applied skill proposal not found"):
        await _service.learn(_ctx(), uuid.uuid4(), data)

    assert _service.skills.updated == []  # type: ignore[attr-defined]
    _service.audit.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.security
async def test_a_caller_cannot_replace_the_text_in_an_applied_proposal(
    _service: AutoSkillLearningService, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _proposal()
    proposal = SimpleNamespace(
        id=data.proposal_id,
        status="applied",
        target_type="skill",
        skill_id=data.skill_id,
        reverted_at=None,
        new_text=OTHER_TEXT,
        applied_content_sha256=_sha256(OTHER_TEXT),
        base_content_sha256=data.base_content_sha256,
        rationale=data.rationale,
        ledger_entry_id=data.ledger_entry_id,
    )
    monkeypatch.setattr(
        "app.services.auto_skill_learning.failure_learning_repo.get_proposal",
        AsyncMock(return_value=proposal),
    )

    with pytest.raises(ConflictError, match="does not match the applied proposal"):
        await _service.learn(_ctx(), uuid.uuid4(), data)

    assert _service.skills.created == []  # type: ignore[attr-defined]
    _service.audit.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.security
async def test_applied_proposal_hash_must_match_its_stored_text(
    _service: AutoSkillLearningService, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _proposal()
    proposal = SimpleNamespace(
        id=data.proposal_id,
        status="applied",
        target_type="skill",
        skill_id=data.skill_id,
        reverted_at=None,
        new_text=data.content,
        applied_content_sha256=_sha256(OTHER_TEXT),
        base_content_sha256=data.base_content_sha256,
        rationale=data.rationale,
        ledger_entry_id=data.ledger_entry_id,
    )
    monkeypatch.setattr(
        "app.services.auto_skill_learning.failure_learning_repo.get_proposal",
        AsyncMock(return_value=proposal),
    )

    with pytest.raises(ConflictError, match="applied proposal content is inconsistent"):
        await _service.learn(_ctx(), uuid.uuid4(), data)

    assert _service.skills.updated == []  # type: ignore[attr-defined]
    _service.audit.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.security
async def test_audit_uses_the_stored_ledger_pattern_key(
    _service: AutoSkillLearningService, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = _row("refunds", BASE_TEXT)
    _service.skills = _Skills([skill])  # type: ignore[attr-defined]
    stored_ledger_entry_id = uuid.uuid4()
    data = _proposal(
        skill_id=skill.id,
        rationale=None,
        ledger_entry_id=None,
        pattern_key="caller-supplied-pattern",
        base_content_sha256=None,
    )
    stored_proposal = SimpleNamespace(
        id=data.proposal_id,
        status="applied",
        target_type="skill",
        skill_id=skill.id,
        reverted_at=None,
        new_text=NEW_TEXT,
        applied_content_sha256=_sha256(NEW_TEXT),
        base_content_sha256=_sha256(BASE_TEXT),
        rationale="Stored rationale",
        ledger_entry_id=stored_ledger_entry_id,
    )
    monkeypatch.setattr(
        "app.services.auto_skill_learning.failure_learning_repo.get_proposal",
        AsyncMock(return_value=stored_proposal),
    )
    monkeypatch.setattr(
        "app.services.auto_skill_learning.failure_learning_repo.get_entry",
        AsyncMock(return_value=SimpleNamespace(pattern_key="stored-pattern")),
    )

    await _service.learn(_ctx(), uuid.uuid4(), data)

    details = _service.audit.await_args.kwargs["details"]  # type: ignore[attr-defined]
    assert details["pattern_key"] == "stored-pattern"
    assert details["proposal_id"] == str(data.proposal_id)
    assert details["ledger_entry_id"] == str(stored_ledger_entry_id)
    assert details["rationale"] == "Stored rationale"
    assert details["base_content_sha256"] == _sha256(BASE_TEXT)
    assert details["content_sha256"] == _sha256(NEW_TEXT)


@pytest.mark.security
async def test_a_proposal_without_a_ledger_entry_audits_no_pattern_key(
    _service: AutoSkillLearningService,
) -> None:
    skill = _row("refunds", BASE_TEXT)
    _service.skills = _Skills([skill])  # type: ignore[attr-defined]
    data = _proposal(skill_id=skill.id, ledger_entry_id=None, pattern_key="caller-supplied")

    await _service.learn(_ctx(), uuid.uuid4(), data)

    details = _service.audit.await_args.kwargs["details"]  # type: ignore[attr-defined]
    assert details["pattern_key"] is None


@pytest.mark.security
async def test_a_missing_ledger_entry_audits_no_pattern_key(
    _service: AutoSkillLearningService,
) -> None:
    skill = _row("refunds", BASE_TEXT)
    _service.skills = _Skills([skill])  # type: ignore[attr-defined]
    data = _proposal(skill_id=skill.id, pattern_key="caller-supplied")
    assert data.ledger_entry_id is not None
    del _LEDGER_PATTERN_KEYS[data.ledger_entry_id]

    await _service.learn(_ctx(), uuid.uuid4(), data)

    details = _service.audit.await_args.kwargs["details"]  # type: ignore[attr-defined]
    assert details["pattern_key"] is None


async def test_an_existing_skill_already_carrying_the_text_is_a_no_op(
    _service: AutoSkillLearningService,
) -> None:
    skill = _row("refunds", NEW_TEXT, version=3)
    _service.skills = _Skills([skill])  # type: ignore[attr-defined]

    read = await _service.learn(
        _ctx(), uuid.uuid4(), _proposal(skill_id=skill.id, base_content_sha256=_sha256(BASE_TEXT))
    )

    assert read.already_learned is True
    assert read.created is False
    assert read.version == 3
    assert _service.skills.updated == []  # type: ignore[attr-defined]
    _service.audit.assert_not_awaited()  # type: ignore[attr-defined]


async def test_an_existing_skill_still_at_its_base_is_updated_through_the_skill_writer(
    _service: AutoSkillLearningService,
) -> None:
    skill = _row("refunds", BASE_TEXT, version=2)
    _service.skills = _Skills([skill])  # type: ignore[attr-defined]

    read = await _service.learn(
        _ctx(), uuid.uuid4(), _proposal(skill_id=skill.id, base_content_sha256=_sha256(BASE_TEXT))
    )

    assert read.already_learned is False
    assert read.created is False
    assert read.version == 3
    assert skill.content == NEW_TEXT
    _service.audit.assert_awaited_once()  # type: ignore[attr-defined]
    assert _service.audit.await_args.kwargs["action"] == "skill.learned"  # type: ignore[attr-defined]


async def test_a_skill_rewritten_since_the_proposal_is_refused(
    _service: AutoSkillLearningService,
) -> None:
    skill = _row("refunds", OTHER_TEXT, version=4)
    _service.skills = _Skills([skill])  # type: ignore[attr-defined]

    with pytest.raises(ConflictError):
        await _service.learn(
            _ctx(),
            uuid.uuid4(),
            _proposal(skill_id=skill.id, base_content_sha256=_sha256(BASE_TEXT)),
        )

    assert skill.content == OTHER_TEXT
    assert skill.version == 4


async def test_an_agent_the_caller_cannot_reach_is_not_found(
    _service: AutoSkillLearningService,
) -> None:
    _service.registry = _Registry(found=False)  # type: ignore[attr-defined]

    with pytest.raises(NotFoundError):
        await _service.learn(_ctx(), uuid.uuid4(), _proposal())

    assert _service.skills.created == []  # type: ignore[attr-defined]
