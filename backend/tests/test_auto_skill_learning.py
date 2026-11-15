"""Tests for automatic skill learning — the step after an approval.

The things worth guarding: learning a proposal twice writes nothing the
second time, a skill somebody rewrote since the proposal was written is
refused rather than overwritten, a new skill is created through the one skill
writer with its provenance audited, and a name collision with different
content is refused rather than renamed silently. No database here: the skill
catalog and the registry are fakes, and the audit trail is a mock.
"""

import hashlib
import uuid
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.core.exceptions import AlreadyExistsError, ConflictError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName, Perm, role_has
from app.db.models.skill import Skill
from app.schemas.auto_skill_learning import LearnSkillCreate
from app.services.auto_skill_learning import AutoSkillLearningService

pytestmark = pytest.mark.anyio

NEW_TEXT = "# Refunds\n\nCheck the order first, then the tracking number."
BASE_TEXT = "# Refunds\n\nCheck the order first."
OTHER_TEXT = "# Refunds\n\nRefund everything, no questions asked."


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
        "content": NEW_TEXT,
        "rationale": "Refunds kept failing when tracking was missing.",
        "ledger_entry_id": uuid.uuid4(),
        "pattern_key": "failed:ModelHTTPError:400",
        "base_content_sha256": _sha256(BASE_TEXT),
    }
    values.update(overrides)
    return LearnSkillCreate(**values)  # type: ignore[arg-type]


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
    service = AutoSkillLearningService(AsyncMock())
    service.registry = _Registry()
    service.skills = _Skills()
    audit = AsyncMock()
    monkeypatch.setattr("app.services.auto_skill_learning.record_audit", audit)
    service.audit = audit  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "app.services.auto_skill_learning.skill_repo.get_by_name",
        AsyncMock(return_value=None),
    )
    return service


async def test_a_viewer_cannot_create_or_probe_a_new_skill_name(
    _service: AutoSkillLearningService, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.VIEWER)
    assert role_has(OrgRoleName.VIEWER, Perm.AGENTS_VIEW)
    assert not role_has(OrgRoleName.VIEWER, Perm.SKILLS_EDIT)
    get_by_name = AsyncMock(return_value=None)
    monkeypatch.setattr("app.services.auto_skill_learning.skill_repo.get_by_name", get_by_name)

    with pytest.raises(NotFoundError):
        await _service.learn(ctx, uuid.uuid4(), _proposal(name="refund-tracking"))

    assert _service.skills.create_calls == 0  # type: ignore[attr-defined]
    get_by_name.assert_not_awaited()
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


@pytest.mark.parametrize(
    ("pattern", "rationale", "name", "description"),
    [
        (
            None,
            None,
            "learned-skill",
            "Learned from a recurring failure. See the audit trail for its proposal.",
        ),
        (
            "failed:rate_limit",
            None,
            "learned-failed-rate-limit",
            "Learned from recurring failures: failed:rate_limit",
        ),
        (None, "!!!", "learned-skill", "!!!"),
        (
            None,
            "Check the order before offering a refund and notify the operator",
            "check-the-order-before-offering-a-refund-and",
            "Check the order before offering a refund and notify the operator",
        ),
    ],
)
async def test_missing_optional_provenance_still_produces_a_usable_catalog_entry(
    _service: AutoSkillLearningService,
    pattern: str | None,
    rationale: str | None,
    name: str,
    description: str,
) -> None:
    data = _proposal(pattern_key=pattern, rationale=rationale, ledger_entry_id=None)

    learned = await _service.learn(_ctx(), uuid.uuid4(), data)

    [created] = _service.skills.created
    assert learned.name == created.name == name
    assert created.description == description
    assert created.content == NEW_TEXT and created.category == "learned"
    assert learned.proposal_id == data.proposal_id and learned.ledger_entry_id is None
    _service.audit.assert_awaited_once()
    assert _service.audit.await_args.kwargs["details"]["ledger_entry_id"] is None


async def test_learning_a_new_skill_creates_it_in_the_learned_category(
    _service: AutoSkillLearningService,
) -> None:
    ctx = _ctx()
    read = await _service.learn(
        ctx, uuid.uuid4(), _proposal(name="refund-tracking", description="Check tracking first.")
    )

    assert read.created is True
    assert read.already_learned is False
    assert read.version == 1
    assert read.name == "refund-tracking"
    assert read.content_sha256 == _sha256(NEW_TEXT)
    created = _service.skills.created  # type: ignore[attr-defined]
    assert len(created) == 1
    assert created[0].category == "learned"
    audit = _service.audit  # type: ignore[attr-defined]
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["action"] == "skill.learned"
    details = audit.await_args.kwargs["details"]
    assert details["pattern_key"] == "failed:ModelHTTPError:400"
    assert details["created"] is True


async def test_a_name_is_derived_from_the_pattern_key_when_the_proposal_has_none(
    _service: AutoSkillLearningService,
) -> None:
    read = await _service.learn(_ctx(), uuid.uuid4(), _proposal())

    assert read.name == "learned-failed-modelhttperror-400"
    assert _service.skills.created[0].name == "learned-failed-modelhttperror-400"  # type: ignore[attr-defined]


async def test_a_description_is_derived_from_the_rationale(
    _service: AutoSkillLearningService,
) -> None:
    await _service.learn(_ctx(), uuid.uuid4(), _proposal())

    assert (
        _service.skills.created[0].description  # type: ignore[attr-defined]
        == "Refunds kept failing when tracking was missing."
    )


async def test_learning_the_same_new_skill_twice_writes_nothing_the_second_time(
    _service: AutoSkillLearningService, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx()
    agent_id = uuid.uuid4()
    data = _proposal(name="refund-tracking")
    first = await _service.learn(ctx, agent_id, data)
    learned = first.skill_id

    existing = _service.skills.by_id[learned]  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "app.services.auto_skill_learning.skill_repo.get_by_name",
        AsyncMock(return_value=existing),
    )
    _service.audit.reset_mock()  # type: ignore[attr-defined]

    second = await _service.learn(ctx, agent_id, data)

    assert second.already_learned is True
    assert second.created is False
    assert second.skill_id == learned
    assert len(_service.skills.created) == 1  # type: ignore[attr-defined]
    _service.audit.assert_not_awaited()  # type: ignore[attr-defined]


async def test_a_name_taken_by_different_content_is_refused(
    _service: AutoSkillLearningService, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = _row("refund-tracking", OTHER_TEXT)
    monkeypatch.setattr(
        "app.services.auto_skill_learning.skill_repo.get_by_name",
        AsyncMock(return_value=other),
    )

    with pytest.raises(AlreadyExistsError):
        await _service.learn(_ctx(), uuid.uuid4(), _proposal(name="refund-tracking"))

    assert _service.skills.created == []  # type: ignore[attr-defined]


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
