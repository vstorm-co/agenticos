"""Who may change a system agent, what its spec may hold and how it is retired.

Against a real database, because each answer turns on a row: the seeded agent's
organization-wide visibility is what lets a Builder reach it at all, and what still
names a system agent is read from datasets, knowledge bases and running work.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents.spec import AgentSpec, ModelSettingsSpec
from app.agents.system_agents import JUDGE
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    NotFoundError,
    SystemAgentRestrictedError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentKind, AgentStatus
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.dataset import Dataset
from app.db.models.organization import Organization
from app.repositories import authoring_repo
from app.schemas.agent import SystemAgentCreate
from app.schemas.agent_environment import EnvironmentCreate, EnvironmentUpdate
from app.schemas.authoring import AuthoringStart
from app.schemas.eval_run import EvalRunRequest
from app.schemas.improvement import ImprovementTarget
from app.services.agent_environment import AgentEnvironmentService
from app.services.agent_registry import AgentRegistryService
from app.services.authoring import AuthoringService
from app.services.eval_run import EvalRunService
from app.services.improvement_pipeline import ImprovementPipelineService
from app.services.system_agents import SystemAgentService
from tests.integration.test_eval_suites import _dataset
from tests.integration.test_system_agents import _member, _organization, _profile, _user

pytestmark = pytest.mark.anyio


async def _seeded(db) -> tuple[Organization, AuthContext, Agent]:
    """An organization with a model, its owner, and its published default judge."""
    organization, owner = await _organization(db)
    await _profile(db, organization, label="Only", created_at=datetime.now(UTC))
    judge = await SystemAgentService(db).ensure(organization_id=organization.id, key=JUDGE.key)
    assert judge.status == AgentStatus.PUBLISHED.value
    ctx = AuthContext(user_id=owner.id, organization_id=organization.id, role=OrgRoleName.OWNER)
    return organization, ctx, judge


async def _as(db, organization: Organization, role: OrgRoleName) -> AuthContext:
    user = await _user(db)
    await _member(db, organization, user, role)
    return AuthContext(user_id=user.id, organization_id=organization.id, role=role)


def _edited(agent: Agent, **changes: object) -> AgentSpec:
    return AgentSpec.model_validate({**agent.draft_spec, **changes})


class TestOnlyAnAdministratorChangesOne:
    async def test_a_builder_reads_it_but_may_not_change_publish_or_retire_it(self, db) -> None:
        organization, _, judge = await _seeded(db)
        builder = await _as(db, organization, OrgRoleName.BUILDER)
        registry = AgentRegistryService(db)

        assert (await registry.get(builder, judge.id)).id == judge.id
        assert not await registry.may_edit(builder, judge)
        assert not await registry.may_publish(builder, judge)
        with pytest.raises(AuthorizationError, match="only an administrator"):
            await registry.save_draft(builder, judge.id, _edited(judge, instructions="Pass all."))
        with pytest.raises(AuthorizationError):
            await registry.publish(builder, judge.id)
        assert judge.current_version_id is not None
        with pytest.raises(AuthorizationError):
            await registry.rollback(builder, judge.id, to_version_id=judge.current_version_id)
        with pytest.raises(AuthorizationError):
            await registry.archive(builder, judge.id)

    async def test_the_listing_offers_a_builder_no_edit_and_an_admin_both(self, db) -> None:
        organization, _, judge = await _seeded(db)
        registry = AgentRegistryService(db)

        for role, allowed in ((OrgRoleName.BUILDER, False), (OrgRoleName.ADMIN, True)):
            ctx = await _as(db, organization, role)
            rows, _ = await registry.list_agents(ctx, kind=AgentKind.JUDGE)
            [row] = [row for row in rows if row.id == judge.id]
            assert (row.can_edit, row.can_publish) == (allowed, allowed)

    async def test_an_admin_changes_and_publishes_it(self, db) -> None:
        organization, _, judge = await _seeded(db)
        admin = await _as(db, organization, OrgRoleName.ADMIN)
        registry = AgentRegistryService(db)

        await registry.save_draft(admin, judge.id, _edited(judge, instructions="Grade harder."))
        version = await registry.publish(admin, judge.id)

        assert version.version == 2
        assert version.spec["instructions"] == "Grade harder."

    async def test_an_admin_of_another_organization_does_not_reach_it(self, db) -> None:
        _, _, judge = await _seeded(db)
        elsewhere, _ = await _organization(db)
        admin = await _as(db, elsewhere, OrgRoleName.ADMIN)

        with pytest.raises(NotFoundError):
            await AgentRegistryService(db).save_draft(admin, judge.id, _edited(judge))

    async def test_a_builder_still_changes_an_ordinary_agent(self, db) -> None:
        organization, _, _ = await _seeded(db)
        builder = await _as(db, organization, OrgRoleName.BUILDER)
        registry = AgentRegistryService(db)
        mine = await registry.create(builder, AgentSpec(name="Support", instructions="Help."))

        saved = await registry.save_draft(
            builder, mine.id, AgentSpec(name="Support", instructions="Help.", starters=["Hi"])
        )

        assert saved.draft_spec["starters"] == ["Hi"]

    async def test_a_builder_who_makes_a_judge_publishes_it_but_cannot_change_it_later(
        self, db
    ) -> None:
        """Making one is its creator's, so a dataset's judge grades from the start."""
        organization, _, _ = await _seeded(db)
        builder = await _as(db, organization, OrgRoleName.BUILDER)

        judge = await SystemAgentService(db).create_from_console(
            builder, SystemAgentCreate(kind="judge", name="Strict judge")
        )

        assert (judge.kind, judge.status) == (AgentKind.JUDGE.value, AgentStatus.PUBLISHED.value)
        with pytest.raises(AuthorizationError):
            await AgentRegistryService(db).save_draft(builder, judge.id, _edited(judge))


class TestWhatItsSpecMayHold:
    async def test_a_draft_holding_what_it_may_never_use_is_refused_by_field(self, db) -> None:
        _, owner, judge = await _seeded(db)

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).save_draft(
                owner,
                judge.id,
                _edited(judge, capabilities=[{"id": "web_fetch"}], starters=["Hello"]),
            )

        fields = [problem["field"] for problem in refused.value.details["fields"]]
        assert fields == ["capabilities", "starters"]
        await db.refresh(judge)
        assert judge.draft_spec.get("starters", []) == []

    async def test_an_imported_document_is_held_to_the_same(self, db) -> None:
        _, owner, judge = await _seeded(db)
        document = (
            _edited(judge, mcp_servers=[])
            .to_yaml()
            .replace("skill_ids: []", "skill_ids: []\nstarters:\n- Hello")
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).import_spec(owner, judge.id, document)

        assert refused.value.details["fields"][0]["field"] == "starters"

    async def test_how_it_reasons_and_what_it_knows_stay_saveable(self, db) -> None:
        _, owner, judge = await _seeded(db)

        saved = await AgentRegistryService(db).save_draft(
            owner,
            judge.id,
            _edited(judge, capabilities=[{"id": "thinking"}, {"id": "context"}, {"id": "skills"}]),
        )

        assert [binding["id"] for binding in saved.draft_spec["capabilities"]] == [
            "thinking",
            "context",
            "skills",
        ]

    async def test_publish_needs_instructions_and_room_for_the_whole_answer(self, db) -> None:
        _, owner, judge = await _seeded(db)
        registry = AgentRegistryService(db)
        cramped = _edited(judge, instructions=" ").model_copy(
            update={"model_settings": ModelSettingsSpec(max_tokens=JUDGE.max_tokens_floor - 1)}
        )
        await registry.save_draft(owner, judge.id, cramped)

        with pytest.raises(BadRequestError) as refused:
            await registry.publish(owner, judge.id)

        fields = [problem["field"] for problem in refused.value.details["fields"]]
        assert fields == ["instructions", "model_settings.max_tokens"]

        roomy = cramped.model_copy(
            update={
                "instructions": "Grade.",
                "model_settings": ModelSettingsSpec(max_tokens=JUDGE.max_tokens_floor),
            }
        )
        await registry.save_draft(owner, judge.id, roomy)
        assert (await registry.publish(owner, judge.id)).version == 2


class TestRetiringOne:
    async def test_the_organization_s_default_is_neither_archived_nor_deleted(self, db) -> None:
        _, owner, judge = await _seeded(db)
        registry = AgentRegistryService(db)

        with pytest.raises(BadRequestError, match="default judge"):
            await registry.archive(owner, judge.id)
        with pytest.raises(BadRequestError, match="default judge"):
            await registry.delete(owner, judge.id)

    async def test_one_a_dataset_grades_with_stays_until_the_dataset_picks_another(
        self, db
    ) -> None:
        organization, owner, _ = await _seeded(db)
        judge = await SystemAgentService(db).create_from_console(
            owner, SystemAgentCreate(kind="judge", name="Strict judge")
        )
        dataset = Dataset(
            id=uuid.uuid4(),
            organization_id=organization.id,
            owner_user_id=owner.user_id,
            visibility="org",
            name="Refunds",
            scoring={"judge": {"enabled": True, "agent_id": str(judge.id)}},
        )
        db.add(dataset)
        await db.flush()
        registry = AgentRegistryService(db)

        for retire in (registry.archive, registry.delete):
            with pytest.raises(BadRequestError) as refused:
                await retire(owner, judge.id)
            assert refused.value.details["uses"] == ["the dataset 'Refunds'"]

        dataset.scoring = {"judge": {"enabled": True, "agent_id": None}}
        await db.flush()
        await registry.delete(owner, judge.id)
        assert await db.get(Agent, judge.id) is None

    async def test_one_busy_with_a_request_stays_until_the_request_ends(self, db) -> None:
        organization, owner, _ = await _seeded(db)
        improver = await SystemAgentService(db).create_from_console(
            owner, SystemAgentCreate(kind="improver", name="Careful assistant")
        )
        support = await AgentRegistryService(db).create(owner, AgentSpec(name="Support"))
        request = await authoring_repo.create_request(
            db,
            organization_id=organization.id,
            kind="improve",
            target="agent",
            agent_id=support.id,
            skill_id=None,
            created_by_user_id=owner.user_id,
            estimate_usd=Decimal("0.01"),
            window_days=30,
            improver_agent_id=improver.id,
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(db).delete(owner, improver.id)
        assert refused.value.details["uses"] == ["a running authoring request"]

        request.status = "completed"
        await db.flush()
        await AgentRegistryService(db).delete(owner, improver.id)


class TestItsEnvironments:
    async def test_it_gets_no_environment_of_its_own_and_no_pin(self, db) -> None:
        _, owner, judge = await _seeded(db)
        service = AgentEnvironmentService(db)
        [default] = await service.list_for_agent(owner, judge.id)

        with pytest.raises(BadRequestError, match="default environment"):
            await service.create(owner, judge.id, EnvironmentCreate(name="staging"))
        with pytest.raises(BadRequestError, match="default environment"):
            await service.update(
                owner, judge.id, default.id, EnvironmentUpdate(tracks_latest=False)
            )
        assert judge.current_version_id is not None
        with pytest.raises(BadRequestError, match="default environment"):
            await service.update(
                owner, judge.id, default.id, EnvironmentUpdate(version_id=judge.current_version_id)
            )

    async def test_a_publish_moves_a_default_pinned_before_pins_were_refused(self, db) -> None:
        _, owner, judge = await _seeded(db)
        environment = await db.scalar(
            select(AgentEnvironment).where(
                AgentEnvironment.agent_id == judge.id, AgentEnvironment.is_default.is_(True)
            )
        )
        assert environment is not None
        environment.tracks_latest = False
        await db.flush()
        registry = AgentRegistryService(db)

        await registry.save_draft(owner, judge.id, _edited(judge, instructions="Grade again."))
        version = await registry.publish(owner, judge.id)

        await db.refresh(judge)
        await db.refresh(environment)
        assert judge.current_version_id == version.id
        assert (environment.version_id, environment.tracks_latest) == (version.id, True)


class TestWhatItIsNotFor:
    async def test_it_is_not_served_over_a2a(self, db) -> None:
        _, owner, judge = await _seeded(db)

        with pytest.raises(SystemAgentRestrictedError):
            await AgentRegistryService(db).set_a2a(owner, judge.id, enabled=True)

    async def test_it_is_not_improved_by_a_session_or_the_assistant(self, db) -> None:
        _, owner, judge = await _seeded(db)

        with pytest.raises(SystemAgentRestrictedError, match="improvement session"):
            await ImprovementPipelineService(db).estimate(
                owner, judge.id, ImprovementTarget(dataset_id=uuid.uuid4())
            )
        with pytest.raises(SystemAgentRestrictedError, match="authoring assistant"):
            await AuthoringService(db).estimate_agent(owner, judge.id, AuthoringStart())

    async def test_its_own_answers_are_not_evaluated(self, db) -> None:
        """It answers its caller in JSON, so a dataset's questions measure nothing about it."""
        _, owner, judge = await _seeded(db)
        dataset = await _dataset(db, owner, cases=1)

        with pytest.raises(SystemAgentRestrictedError, match="eval of its own answers"):
            await EvalRunService(db).estimate(
                owner, judge.id, EvalRunRequest(dataset_id=dataset.id)
            )
