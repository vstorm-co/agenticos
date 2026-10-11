"""Tests for the generated sharing routes.

The five sharing endpoints exist once per resource type - agents, collections,
skills, context files, vault secrets, artifacts - generated from one definition.
What is worth testing is the generation itself: that each type really gets all
five, that they are wired to the right resource type, and that a row from
another organization is refused before the sharing service is ever reached.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routes.v1._sharing_loaders import (
    load_agent,
    load_artifact,
    load_collection,
    load_context,
    load_secret,
    load_skill,
    load_table,
    load_workflow,
)
from app.api.routes.v1.sharing import (
    agent_sharing_router,
    artifact_sharing_router,
    collection_sharing_router,
    context_sharing_router,
    secret_sharing_router,
    skill_sharing_router,
    table_sharing_router,
    workflow_sharing_router,
)
from app.core.exceptions import NotFoundError
from app.services.access import AGENT, COLLECTION, SECRET, SKILL
from app.services.sharing import SharingState

ROUTERS = (
    ("agents", agent_sharing_router),
    ("collections", collection_sharing_router),
    ("skills", skill_sharing_router),
    ("context", context_sharing_router),
    ("secrets", secret_sharing_router),
    ("tables", table_sharing_router),
    ("workflows", workflow_sharing_router),
    ("artifacts", artifact_sharing_router),
)

LOADERS = (
    ("agent", load_agent, "Agent not found", "agent_id"),
    ("collection", load_collection, "Collection not found", "kb_id"),
    ("skill", load_skill, "Skill not found", "skill_id"),
    ("context", load_context, "Context file not found", "context_id"),
    ("secret", load_secret, "Secret not found", "secret_id"),
    ("table", load_table, "Table not found", "table_id"),
    ("workflow", load_workflow, "Workflow not found", "workflow_id"),
    ("artifact", load_artifact, "Artifact not found", "artifact_id"),
)


class TestGeneratedRoutes:
    @pytest.mark.parametrize(("name", "router"), ROUTERS)
    def test_every_resource_type_gets_the_whole_sharing_api(self, name, router):
        """A type missing one endpoint is a type you cannot un-share from."""
        methods = {
            (route.path, method)
            for route in router.routes
            for method in route.methods
            if method != "HEAD"
        }
        assert methods == {
            ("/{resource_id}/sharing", "GET"),
            ("/{resource_id}/sharing/grants", "PUT"),
            ("/{resource_id}/sharing/grants/{subject_user_id}", "DELETE"),
            ("/{resource_id}/sharing/group-grants/{group_id}", "DELETE"),
            ("/{resource_id}/sharing/visibility", "PATCH"),
        }, name

    def test_every_router_is_its_own_instance(self):
        """Sharing the same router would make every type write grants as one type."""
        instances = {id(router) for _, router in ROUTERS}
        assert len(instances) == len(ROUTERS)


class TestResourceLoaders:
    """The loaders are the tenant boundary: nothing below them re-checks the org."""

    @pytest.mark.parametrize(("kind", "loader", "message", "detail_key"), LOADERS)
    @pytest.mark.anyio
    async def test_a_row_from_another_organization_is_reported_as_missing(
        self, kind, loader, message, detail_key
    ):
        row = MagicMock(organization_id=uuid.uuid4())
        db = MagicMock(get=AsyncMock(return_value=row))
        resource_id = uuid.uuid4()

        with pytest.raises(NotFoundError) as refused:
            await loader(db, resource_id, uuid.uuid4())

        assert refused.value.message == message
        assert refused.value.details == {detail_key: str(resource_id)}

    @pytest.mark.parametrize(("kind", "loader", "message", "detail_key"), LOADERS)
    @pytest.mark.anyio
    async def test_a_missing_row_is_reported_the_same_way(self, kind, loader, message, detail_key):
        """Identical to the foreign-row case, so ids cannot be probed."""
        db = MagicMock(get=AsyncMock(return_value=None))
        resource_id = uuid.uuid4()

        with pytest.raises(NotFoundError) as refused:
            await loader(db, resource_id, uuid.uuid4())

        assert refused.value.message == message
        assert refused.value.details == {detail_key: str(resource_id)}

    @pytest.mark.parametrize(("kind", "loader", "message", "detail_key"), LOADERS)
    @pytest.mark.anyio
    async def test_a_row_in_the_callers_organization_is_returned(
        self, kind, loader, message, detail_key
    ):
        organization_id = uuid.uuid4()
        row = MagicMock(organization_id=organization_id)
        db = MagicMock(get=AsyncMock(return_value=row))

        assert await loader(db, uuid.uuid4(), organization_id) is row


class TestHandlerBehaviour:
    """The generated handlers, exercised directly.

    Calling them through the app would need a database; calling them directly
    still proves the part that is generated - that each handler passes *its own*
    resource type to the sharing service, which is what decides whose grants a
    row gets.
    """

    @staticmethod
    def _handler(router, path: str, method: str):
        for route in router.routes:
            if route.path == path and method in route.methods:
                return route.endpoint
        raise AssertionError(f"no {method} {path}")

    @pytest.mark.anyio
    async def test_reading_sharing_uses_the_routers_own_resource_type(self):
        ctx = MagicMock(organization_id=uuid.uuid4())
        resource = MagicMock(id=uuid.uuid4(), owner_user_id=uuid.uuid4(), visibility="private")
        service = MagicMock(get_sharing=AsyncMock(return_value=SharingState([], {}, {})))
        db = MagicMock(get=AsyncMock(return_value=resource))
        resource.organization_id = ctx.organization_id

        handler = self._handler(agent_sharing_router, "/{resource_id}/sharing", "GET")
        result = await handler(resource.id, db, service, ctx)

        assert service.get_sharing.call_args.kwargs["resource_type"] is AGENT
        assert result.resource_type == AGENT.key

    @pytest.mark.anyio
    async def test_each_router_carries_a_different_resource_type(self):
        for router, expected in (
            (agent_sharing_router, AGENT),
            (collection_sharing_router, COLLECTION),
            (skill_sharing_router, SKILL),
            (secret_sharing_router, SECRET),
        ):
            ctx = MagicMock(organization_id=uuid.uuid4())
            resource = MagicMock(
                id=uuid.uuid4(),
                organization_id=ctx.organization_id,
                owner_user_id=uuid.uuid4(),
                visibility="private",
            )
            service = MagicMock(get_sharing=AsyncMock(return_value=SharingState([], {}, {})))
            db = MagicMock(get=AsyncMock(return_value=resource))

            handler = self._handler(router, "/{resource_id}/sharing", "GET")
            result = await handler(resource.id, db, service, ctx)

            assert result.resource_type == expected.key

    @pytest.mark.anyio
    async def test_sharing_returns_the_grant_that_was_written(self):
        ctx = MagicMock(organization_id=uuid.uuid4())
        subject = uuid.uuid4()
        resource = MagicMock(id=uuid.uuid4(), organization_id=ctx.organization_id)
        grant = MagicMock(
            id=uuid.uuid4(),
            subject_user_id=subject,
            subject_group_id=None,
            resource_type=AGENT.key,
            resource_id=resource.id,
            level="edit",
        )
        service = MagicMock(share=AsyncMock(return_value=grant))
        db = MagicMock(get=AsyncMock(return_value=resource))

        handler = self._handler(agent_sharing_router, "/{resource_id}/sharing/grants", "PUT")
        result = await handler(
            resource.id,
            MagicMock(subject_user_id=subject, subject_group_id=None, level="edit"),
            db,
            service,
            ctx,
        )

        assert result.subject_user_id == subject
        assert result.level == "edit"

    @pytest.mark.anyio
    async def test_unsharing_names_the_member_being_removed(self):
        ctx = MagicMock(organization_id=uuid.uuid4())
        subject = uuid.uuid4()
        resource = MagicMock(id=uuid.uuid4(), organization_id=ctx.organization_id)
        service = MagicMock(revoke=AsyncMock())
        db = MagicMock(get=AsyncMock(return_value=resource))

        handler = self._handler(
            agent_sharing_router, "/{resource_id}/sharing/grants/{subject_user_id}", "DELETE"
        )
        await handler(resource.id, subject, db, service, ctx)

        assert service.revoke.call_args.kwargs["subject_user_id"] == subject
        assert service.revoke.call_args.kwargs["resource_type"] is AGENT

    @pytest.mark.anyio
    async def test_sharing_with_a_group_goes_to_the_group_path(self):
        """A body naming a group must never be written as a grant to a person."""
        ctx = MagicMock(organization_id=uuid.uuid4())
        group_id = uuid.uuid4()
        resource = MagicMock(id=uuid.uuid4(), organization_id=ctx.organization_id)
        grant = MagicMock(
            id=uuid.uuid4(),
            subject_user_id=None,
            subject_group_id=group_id,
            resource_type=AGENT.key,
            resource_id=resource.id,
            level="use",
        )
        service = MagicMock(share_with_group=AsyncMock(return_value=grant), share=AsyncMock())
        db = MagicMock(get=AsyncMock(return_value=resource))

        handler = self._handler(agent_sharing_router, "/{resource_id}/sharing/grants", "PUT")
        result = await handler(
            resource.id,
            MagicMock(subject_user_id=None, subject_group_id=group_id, level="use"),
            db,
            service,
            ctx,
        )

        assert service.share_with_group.call_args.kwargs["group_id"] == group_id
        assert service.share_with_group.call_args.kwargs["resource_type"] is AGENT
        service.share.assert_not_called()
        assert result.subject_group_id == group_id
        assert result.subject_user_id is None

    @pytest.mark.anyio
    async def test_unsharing_a_group_names_the_group_being_removed(self):
        ctx = MagicMock(organization_id=uuid.uuid4())
        group_id = uuid.uuid4()
        resource = MagicMock(id=uuid.uuid4(), organization_id=ctx.organization_id)
        service = MagicMock(revoke_group=AsyncMock())
        db = MagicMock(get=AsyncMock(return_value=resource))

        handler = self._handler(
            skill_sharing_router, "/{resource_id}/sharing/group-grants/{group_id}", "DELETE"
        )
        await handler(resource.id, group_id, db, service, ctx)

        assert service.revoke_group.call_args.kwargs["group_id"] == group_id
        assert service.revoke_group.call_args.kwargs["resource_type"] is SKILL

    @pytest.mark.anyio
    async def test_changing_visibility_returns_the_new_state(self):
        """The caller should not have to re-fetch to see what they just set."""
        ctx = MagicMock(organization_id=uuid.uuid4())
        resource = MagicMock(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            owner_user_id=uuid.uuid4(),
            visibility="private",
        )

        async def _apply(_ctx, target, *, resource_type, visibility):
            target.visibility = visibility.value
            return target

        service = MagicMock(
            set_visibility=AsyncMock(side_effect=_apply),
            get_sharing=AsyncMock(return_value=SharingState([], {}, {})),
        )
        db = MagicMock(get=AsyncMock(return_value=resource))

        handler = self._handler(agent_sharing_router, "/{resource_id}/sharing/visibility", "PATCH")
        result = await handler(resource.id, MagicMock(visibility="org"), db, service, ctx)

        assert result.visibility == "org"


class TestRendering:
    @pytest.mark.anyio
    async def test_a_grant_carries_the_email_resolved_for_it(self):
        ctx = MagicMock(organization_id=uuid.uuid4())
        subject = uuid.uuid4()
        resource = MagicMock(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            owner_user_id=uuid.uuid4(),
            visibility="team",
        )
        grant = MagicMock(
            id=uuid.uuid4(),
            subject_user_id=subject,
            subject_group_id=None,
            resource_type=AGENT.key,
            resource_id=resource.id,
            level="read",
        )
        service = MagicMock(
            get_sharing=AsyncMock(
                return_value=SharingState([grant], {subject: "a@example.com"}, {})
            )
        )
        db = MagicMock(get=AsyncMock(return_value=resource))

        handler = TestHandlerBehaviour._handler(
            agent_sharing_router, "/{resource_id}/sharing", "GET"
        )
        result = await handler(resource.id, db, service, ctx)

        assert result.grants[0].subject_email == "a@example.com"
        assert result.visibility == "team"

    @pytest.mark.anyio
    async def test_a_grant_whose_email_is_unknown_renders_without_one(self):
        """A member removed from the org leaves a grant behind; it must still list."""
        ctx = MagicMock(organization_id=uuid.uuid4())
        resource = MagicMock(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            owner_user_id=None,
            visibility="private",
        )
        grant = MagicMock(
            id=uuid.uuid4(),
            subject_user_id=uuid.uuid4(),
            subject_group_id=None,
            resource_type=AGENT.key,
            resource_id=resource.id,
            level="read",
        )
        service = MagicMock(get_sharing=AsyncMock(return_value=SharingState([grant], {}, {})))
        db = MagicMock(get=AsyncMock(return_value=resource))

        handler = TestHandlerBehaviour._handler(
            agent_sharing_router, "/{resource_id}/sharing", "GET"
        )
        result = await handler(resource.id, db, service, ctx)

        assert result.grants[0].subject_email is None
        assert result.owner_user_id is None


class TestGroupRendering:
    @pytest.mark.anyio
    async def test_a_group_grant_carries_the_group_name_and_no_person(self):
        ctx = MagicMock(organization_id=uuid.uuid4())
        group_id = uuid.uuid4()
        resource = MagicMock(
            id=uuid.uuid4(),
            organization_id=ctx.organization_id,
            owner_user_id=uuid.uuid4(),
            visibility="private",
        )
        grant = MagicMock(
            id=uuid.uuid4(),
            subject_user_id=None,
            subject_group_id=group_id,
            resource_type=AGENT.key,
            resource_id=resource.id,
            level="edit",
        )
        service = MagicMock(
            get_sharing=AsyncMock(return_value=SharingState([grant], {}, {group_id: "Finance"}))
        )
        db = MagicMock(get=AsyncMock(return_value=resource))

        handler = TestHandlerBehaviour._handler(
            agent_sharing_router, "/{resource_id}/sharing", "GET"
        )
        result = await handler(resource.id, db, service, ctx)

        rendered = result.grants[0]
        assert rendered.subject_group_id == group_id
        assert rendered.subject_group_name == "Finance"
        assert rendered.subject_user_id is None
        assert rendered.subject_email is None


def test_the_factory_is_not_accidentally_shared_state():
    """Two routers built from the same factory must not share a route list."""
    with patch("app.api.routes.v1._sharing_routes.SharingSvc", MagicMock()):
        assert agent_sharing_router.routes is not collection_sharing_router.routes
