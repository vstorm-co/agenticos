"""The workflows a page version declares (#1976), on real rows.

What a publish may declare is checked against the workflows the agent's Workflows
capability binds and against the person's own right to run each one; what a restore
copies is checked again against the agent as it is now. The refusals assert the exact
sentence - the model reads them - and the version rows show what was stored.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.spec import AgentSpec
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.artifact import ArtifactMediaType
from app.db.models.audit_log import AppAdminAuditLog
from app.db.models.organization import Organization, OrganizationMember
from app.db.models.resource_grant import Visibility
from app.db.models.workflow import Workflow, WorkflowStatus
from app.repositories import artifact_repo
from app.schemas.artifact import ActionRequest
from app.services import artifact as artifacts
from app.services.artifact import ArtifactService
from app.services.artifact_actions import (
    LIVE_ACTIONS,
    MAX_ACTIONS,
    MAX_LABEL,
    NO_PERSON,
    clean_label,
)
from app.services.file_storage import LocalFileStorage
from tests.integration.virtual_table_support import make_org, make_user

pytestmark = pytest.mark.anyio


@pytest.fixture
def storage(tmp_path: Path) -> Iterator[LocalFileStorage]:
    local = LocalFileStorage(tmp_path)
    with (
        patch("app.services.artifact.get_file_storage", return_value=local),
        patch("app.services.file_storage.get_file_storage", return_value=local),
    ):
        yield local


@dataclass
class _World:
    db: AsyncSession
    org: Organization
    boss: AuthContext
    olga: AuthContext
    agent: Agent
    workflows: list[Workflow] = field(default_factory=list)
    page_id: uuid.UUID | None = None

    async def workflow(
        self,
        name: str,
        *,
        trigger: str | None = "trigger.manual",
        status: WorkflowStatus = WorkflowStatus.PUBLISHED,
        visibility: Visibility = Visibility.ORG,
        org: Organization | None = None,
    ) -> Workflow:
        target = org or self.org
        row = Workflow(
            id=uuid.uuid4(),
            organization_id=target.id,
            owner_user_id=self.boss.user_id,
            slug=f"wf-{uuid.uuid4().hex[:8]}",
            name=name,
            status=status.value,
            visibility=visibility.value,
            draft_graph={},
            live_trigger=trigger,
        )
        self.db.add(row)
        await self.db.flush()
        self.workflows.append(row)
        return row

    async def bind(self, *workflows: Workflow) -> None:
        """The agent's current spec binds exactly these in its Workflows capability."""
        spec = AgentSpec(
            name="Reporter",
            capabilities=[
                {"id": "workflows", "config": {"workflow_ids": [str(w.id) for w in workflows]}}
            ],
        )
        number = len((await self.db.execute(select(AgentVersion))).all()) + 1
        version = AgentVersion(
            id=uuid.uuid4(),
            agent_id=self.agent.id,
            organization_id=self.org.id,
            version=number,
            spec=spec.model_dump(mode="json"),
        )
        self.db.add(version)
        await self.db.flush()
        self.agent.current_version_id = version.id
        await self.db.flush()

    async def publish(
        self,
        body: str = "<p>v1</p>",
        *,
        actions: list[ActionRequest] | None = None,
        allowed: tuple[Workflow, ...] | None = None,
        by: AuthContext | str | None = "olga",
    ) -> artifacts.PublishedArtifact:
        person = self.olga if by == "olga" else by
        assert person is None or isinstance(person, AuthContext)
        published = await artifacts.publish_with(
            self.db,
            organization_id=self.org.id,
            agent_id=self.agent.id,
            owner_user_id=self.olga.user_id,
            run_id=None,
            name="tool",
            title="Tool",
            media_type=ArtifactMediaType.HTML,
            data=body.encode(),
            run_person=person.user_id if person is not None else None,
            actions=actions,
            workflow_ids=frozenset(
                w.id for w in (allowed if allowed is not None else self.workflows)
            ),
        )
        self.page_id = published.artifact_id
        return published

    async def stored(self, number: int) -> list[dict]:
        assert self.page_id is not None
        version = await artifact_repo.get_version_by_number(self.db, self.page_id, number)
        assert version is not None
        return version.actions


def _ask(workflow: Workflow | str, label: str | None = None) -> ActionRequest:
    ref = workflow if isinstance(workflow, str) else workflow.id
    return ActionRequest(workflow=ref, label=label)


async def _world(db: AsyncSession) -> _World:
    boss_user = await make_user(db)
    org = await make_org(db, owner=boss_user)
    boss = AuthContext(user_id=boss_user.id, organization_id=org.id, role="owner")
    olga_user = await make_user(db)
    db.add(OrganizationMember(organization_id=org.id, user_id=olga_user.id, role="member"))
    await db.flush()
    olga = AuthContext(user_id=olga_user.id, organization_id=org.id, role="member")
    agent = Agent(
        organization_id=org.id,
        name="Reporter",
        created_by_user_id=olga_user.id,
        slug=f"a-{uuid.uuid4().hex[:8]}",
        status=AgentStatus.PUBLISHED.value,
        draft_spec={"name": "Reporter"},
    )
    db.add(agent)
    await db.flush()
    return _World(db, org, boss, olga, agent)


class TestDeclaring:
    async def test_a_bound_manual_workflow_is_stored_and_echoed(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")

        published = await world.publish(actions=[_ask(refund, "  Refund\n the order  ")])

        assert published.actions[0].model_dump() == {
            "workflow": "Refund",
            "label": "Refund the order",
        }
        assert await world.stored(1) == [
            {"workflow_id": str(refund.id), "label": "Refund the order"}
        ]

    async def test_a_workflow_is_named_by_its_exact_name_and_an_empty_label_takes_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")

        await world.publish(actions=[_ask("Refund", " ")])

        assert await world.stored(1) == [{"workflow_id": str(refund.id), "label": "Refund"}]

    async def test_an_api_trigger_is_by_hand_too(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        api = await world.workflow("Intake", trigger="core.input")

        await world.publish(actions=[_ask(api)])

        assert len(await world.stored(1)) == 1

    @pytest.mark.parametrize("reference", ["Refund", "no such"])
    async def test_a_workflow_the_agent_does_not_bind_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage, reference: str
    ) -> None:
        world = await _world(db)
        await world.workflow("Refund")

        with pytest.raises(BadRequestError) as refused:
            await world.publish(actions=[_ask(reference)], allowed=())

        assert "is not bound in this agent's Workflows capability" in refused.value.message

    async def test_a_workflow_of_another_organization_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        other = await make_org(db, owner=await make_user(db))
        foreign = await world.workflow("Foreign", org=other)

        with pytest.raises(BadRequestError) as refused:
            await world.publish(actions=[_ask(foreign)])

        assert "is not bound in this agent's Workflows capability" in refused.value.message

    async def test_an_archived_workflow_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        old = await world.workflow("Old", status=WorkflowStatus.ARCHIVED)

        with pytest.raises(BadRequestError) as refused:
            await world.publish(actions=[_ask(old)])

        assert refused.value.message == "Workflow 'Old' is archived, so a page cannot start it."

    async def test_a_workflow_with_no_published_version_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        draft = await world.workflow("Draft", trigger=None)

        with pytest.raises(BadRequestError) as refused:
            await world.publish(actions=[_ask(draft)])

        assert "has no published version" in refused.value.message

    @pytest.mark.parametrize("trigger", ["trigger.webhook", "trigger.schedule", "trigger.chat"])
    async def test_a_workflow_that_does_not_start_by_hand_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage, trigger: str
    ) -> None:
        world = await _world(db)
        hook = await world.workflow("Hook", trigger=trigger)

        with pytest.raises(BadRequestError) as refused:
            await world.publish(actions=[_ask(hook)])

        assert refused.value.message == (
            "Workflow 'Hook' does not start from a Manual or API trigger, so a page cannot "
            "start it."
        )

    async def test_a_person_who_may_not_run_the_workflow_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        private = await world.workflow("Payroll", visibility=Visibility.PRIVATE)

        with pytest.raises(BadRequestError) as refused:
            await world.publish(actions=[_ask(private)])

        assert "Payroll" not in refused.value.message
        assert "is not bound in this agent's Workflows capability" in refused.value.message

    async def test_a_bound_workflow_the_person_cannot_reach_is_not_named_by_id_or_name(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        private = await world.workflow("Payroll", visibility=Visibility.PRIVATE)
        twin = await world.workflow("Payroll")

        with pytest.raises(BadRequestError) as by_id:
            await world.publish(actions=[ActionRequest(workflow=private.id)], allowed=(private,))
        assert "Payroll" not in by_id.value.message
        # By name, the refusal repeats only what the model wrote - the unknown-name text.
        with pytest.raises(BadRequestError) as by_name:
            await world.publish(actions=[_ask("Payroll")], allowed=(private,))
        assert "is not bound in this agent's Workflows capability" in by_name.value.message

        # A name held by an inaccessible workflow and an accessible one is not ambiguous.
        published = await world.publish(actions=[_ask("Payroll")], allowed=(private, twin))
        assert published.actions[0].workflow == "Payroll"

    async def test_more_than_five_actions_are_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        many = [await world.workflow(f"W{n}") for n in range(MAX_ACTIONS + 1)]

        with pytest.raises(BadRequestError) as refused:
            await world.publish(actions=[_ask(w) for w in many])

        assert refused.value.message == "A page declares at most 5 actions; this one has 6."

    async def test_the_same_workflow_twice_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")

        with pytest.raises(BadRequestError) as refused:
            await world.publish(actions=[_ask(refund), _ask("Refund")])

        assert refused.value.message == "Workflow 'Refund' is declared twice."

    async def test_two_workflows_of_one_name_ask_for_the_id(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        await world.workflow("Refund")
        await world.workflow("Refund")

        with pytest.raises(BadRequestError) as refused:
            await world.publish(actions=[_ask("Refund")])

        assert "Several workflows are named 'Refund'" in refused.value.message

    async def test_a_markdown_page_takes_no_actions(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")

        with pytest.raises(BadRequestError) as refused:
            await artifacts.publish_with(
                db,
                organization_id=world.org.id,
                agent_id=world.agent.id,
                owner_user_id=world.olga.user_id,
                run_id=None,
                name="tool",
                title=None,
                media_type=ArtifactMediaType.MARKDOWN,
                data=b"# page",
                run_person=world.olga.user_id,
                actions=[_ask(refund)],
                workflow_ids=frozenset({refund.id}),
            )
        assert "pass `actions: []`" in refused.value.message
        assert "bindings" not in refused.value.message

    async def test_a_markdown_republish_that_keeps_actions_is_refused_with_the_actions_text(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")
        await world.publish(actions=[_ask(refund)])

        with pytest.raises(BadRequestError) as refused:
            await artifacts.publish_with(
                db,
                organization_id=world.org.id,
                agent_id=world.agent.id,
                owner_user_id=world.olga.user_id,
                run_id=None,
                name="tool",
                title=None,
                media_type=ArtifactMediaType.MARKDOWN,
                data=b"# page",
                run_person=world.olga.user_id,
                workflow_ids=frozenset({refund.id}),
            )
        assert "pass `actions: []`" in refused.value.message

    async def test_a_publish_is_audited_with_the_workflow_ids_only(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")

        published = await world.publish(actions=[_ask(refund, "Pay it back")])

        rows = await db.execute(
            select(AppAdminAuditLog.details).where(
                AppAdminAuditLog.target_id == str(published.artifact_id),
                AppAdminAuditLog.action == "artifact.published",
            )
        )
        details = rows.scalar_one()
        assert details["actions"] == [str(refund.id)]
        assert "Pay it back" not in json.dumps(details)


class TestACarriedDeclaration:
    async def test_omitted_actions_are_kept_and_the_result_says_so(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")
        await world.publish(actions=[_ask(refund)])

        again = await world.publish("<p>v2</p>")

        assert again.actions == "kept"
        assert await world.stored(2) == await world.stored(1)

    async def test_an_empty_list_removes_them(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")
        await world.publish(actions=[_ask(refund)])

        removed = await world.publish(actions=[])

        assert (removed.unchanged, removed.actions) == (False, [])
        assert await world.stored(2) == []

    async def test_a_page_with_none_reports_none(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)

        assert (await world.publish()).actions == []

    async def test_the_same_bytes_and_actions_are_unchanged(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")
        await world.publish(actions=[_ask(refund, "Refund")])

        same = await world.publish(actions=[_ask(refund, "Refund")])
        kept = await world.publish()

        assert (same.unchanged, same.version_number) == (True, 1)
        assert (kept.unchanged, kept.actions) == (True, "kept")

    async def test_the_same_bytes_with_other_actions_are_a_new_version(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")
        await world.publish(actions=[_ask(refund, "Refund")])

        relabelled = await world.publish(actions=[_ask(refund, "Pay back")])
        added = await world.publish()  # carried: unchanged again

        assert (relabelled.unchanged, relabelled.version_number) == (False, 2)
        assert (added.unchanged, added.version_number) == (True, 2)


class TestARunWithNobodyBehindIt:
    async def test_it_cannot_add_actions(self, db: AsyncSession, storage: LocalFileStorage) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")

        with pytest.raises(AuthorizationError) as refused:
            await world.publish(actions=[_ask(refund)], by=None)

        assert refused.value.message == NO_PERSON

    async def test_it_may_publish_a_page_without_actions(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")

        first = await world.publish(by=None)
        again = await world.publish("<p>v2</p>", actions=[], by=None)

        assert (first.actions, again.actions, again.version_number) == ([], [], 2)
        assert refund.id is not None

    async def test_it_cannot_change_or_clear_the_actions_of_a_page_that_has_them(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")
        await world.publish(actions=[_ask(refund)])

        for kwargs in ({"actions": []}, {"actions": [_ask(refund)]}, {"body": "<p>swapped</p>"}):
            with pytest.raises(AuthorizationError) as refused:
                await world.publish(by=None, **kwargs)
            assert refused.value.message == LIVE_ACTIONS

    async def test_it_may_republish_such_a_page_unchanged(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund = await world.workflow("Refund")
        await world.publish(actions=[_ask(refund)])

        again = await world.publish(by=None)

        assert (again.unchanged, again.version_number, again.actions) == (True, 1, "kept")


class TestRestoring:
    async def _two_versions(self, world: _World) -> tuple[Workflow, artifacts.PublishedArtifact]:
        refund = await world.workflow("Refund")
        await world.bind(refund)
        first = await world.publish(actions=[_ask(refund, "Refund")])
        await world.publish("<p>v2</p>", actions=[])
        return refund, first

    async def test_a_restore_copies_the_actions(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund, first = await self._two_versions(world)

        await ArtifactService(db).restore_version(world.olga, first.artifact_id, first.version_id)

        assert await world.stored(3) == [{"workflow_id": str(refund.id), "label": "Refund"}]

    async def test_a_restore_is_refused_when_the_agent_no_longer_binds_the_workflow(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        _, first = await self._two_versions(world)
        await world.bind()

        with pytest.raises(AuthorizationError) as refused:
            await ArtifactService(db).restore_version(
                world.olga, first.artifact_id, first.version_id
            )

        assert refused.value.message == (
            "Action 'Refund' starts a workflow that the agent no longer has bound in its "
            "Workflows capability, that is gone, or that you may not run. So this version can't be restored with its actions."
        )

    async def test_a_restore_is_refused_when_the_workflow_was_archived_since(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund, first = await self._two_versions(world)
        refund.status = WorkflowStatus.ARCHIVED.value
        await db.flush()

        with pytest.raises(AuthorizationError) as refused:
            await ArtifactService(db).restore_version(
                world.olga, first.artifact_id, first.version_id
            )

        assert "is archived" in refused.value.message

    async def test_a_restore_is_refused_when_the_restorer_may_not_run_it(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund, first = await self._two_versions(world)
        refund.visibility = Visibility.PRIVATE.value
        await db.flush()

        with pytest.raises(AuthorizationError) as refused:
            await ArtifactService(db).restore_version(
                world.olga, first.artifact_id, first.version_id
            )

        assert "you may not run" in refused.value.message

    async def test_a_restore_is_refused_when_the_agent_is_gone(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        _, first = await self._two_versions(world)
        page = await artifact_repo.get(db, first.artifact_id, organization_id=world.org.id)
        assert page is not None
        page.agent_id = None
        await db.flush()

        with pytest.raises(AuthorizationError) as refused:
            await ArtifactService(db).restore_version(
                world.olga, first.artifact_id, first.version_id
            )
        assert refused.value.message == (
            "This version runs workflows, but the page's agent is gone, so it can't be restored."
        )

    async def test_a_restore_with_an_agent_that_has_no_published_spec_is_refused(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        _, first = await self._two_versions(world)
        world.agent.current_version_id = None
        await db.flush()

        with pytest.raises(AuthorizationError):
            await ArtifactService(db).restore_version(
                world.olga, first.artifact_id, first.version_id
            )

    @pytest.mark.parametrize("gone", ["agent", "version"])
    async def test_a_restore_is_refused_when_the_agent_or_its_version_cannot_be_read(
        self, db: AsyncSession, storage: LocalFileStorage, gone: str
    ) -> None:
        world = await _world(db)
        _, first = await self._two_versions(world)

        with (
            patch(
                f"app.services.artifact.agent_repo.{'get' if gone == 'agent' else 'get_version'}"
            ) as read,
            pytest.raises(AuthorizationError),
        ):
            read.return_value = None
            await ArtifactService(db).restore_version(
                world.olga, first.artifact_id, first.version_id
            )

    async def test_a_restore_without_actions_asks_nothing_of_the_agent(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        plain = await world.publish("<p>plain</p>")
        await world.publish("<p>v2</p>")

        await ArtifactService(db).restore_version(world.olga, plain.artifact_id, plain.version_id)

        assert await world.stored(3) == []

    async def test_actions_are_restored_in_a_named_environment_by_its_pinned_version(
        self, db: AsyncSession, storage: LocalFileStorage
    ) -> None:
        world = await _world(db)
        refund, first = await self._two_versions(world)
        version = await db.get(AgentVersion, world.agent.current_version_id)
        assert version is not None
        environment = AgentEnvironment(
            organization_id=world.org.id,
            agent_id=world.agent.id,
            name="staging",
            version_id=version.id,
            is_default=False,
        )
        db.add(environment)
        await db.flush()
        page = await artifact_repo.get(db, first.artifact_id, organization_id=world.org.id)
        assert page is not None
        page.environment_id = environment.id
        await db.flush()

        await ArtifactService(db).restore_version(world.olga, first.artifact_id, first.version_id)

        assert await world.stored(3) == [{"workflow_id": str(refund.id), "label": "Refund"}]

        # A pinned version the agent no longer has allows nothing.
        environment.version_id = world.agent.current_version_id
        agent_version = await db.get(AgentVersion, environment.version_id)
        assert agent_version is not None
        agent_version.spec = AgentSpec(name="Reporter").model_dump(mode="json")
        await db.flush()
        with pytest.raises(AuthorizationError):
            await ArtifactService(db).restore_version(
                world.olga, first.artifact_id, first.version_id
            )


def test_a_label_is_plain_text_of_bounded_length() -> None:
    assert clean_label("a\x00b" + chr(0x2028) + "c\td", "x") == "a b c d"
    assert clean_label("x" * 200, "y") == "x" * MAX_LABEL
    assert clean_label("\n\t ", "Refund") == "Refund"
    assert clean_label(None, "Refund") == "Refund"
    # Bidi overrides and isolates and zero-width characters are not copy.
    assert clean_label("Pay\u202eevil\u202c \u2066x\u2069\u200bok\ufeff", "y") == "Pay evil x ok"
    assert clean_label("\u202e\u200b", "Refund") == "Refund"
