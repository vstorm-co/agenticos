"""Tests for skills - organizational know-how handed to agents.

The things worth guarding: script execution stays off until there is a sandbox,
a skill that disappears after publish degrades the agent rather than breaking
the run, and an uploaded file is refused unless the model could actually read
it - by name and by content both.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.skills import SAFE_SKILL_TOOLS, Skills
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.resource_grant import GrantLevel, Visibility
from app.db.models.skill import Skill
from app.schemas.skill import SkillResourceUpdate, SkillUpdate
from app.services.skill_library import LibraryResource, LibrarySkill
from app.services.skills import (
    MAX_RESOURCE_BYTES,
    SUGGESTED_CATEGORIES,
    SkillService,
    _clean_resource_path,
    _decode_text,
)

SKILLS_PATH = "app.services.skills"


def _ctx(role: str = OrgRoleName.OWNER, *, org_id=None, user_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=role,
    )


def _skill(name="refunds", enabled=True, resources=None, *, ctx=None, owner_user_id=None):
    """A skill row; given a `ctx` it is one the caller owns, so role scope reaches it."""
    skill = MagicMock()
    skill.id = uuid.uuid4()
    skill.organization_id = ctx.organization_id if ctx else uuid.uuid4()
    skill.owner_user_id = owner_user_id or (ctx.user_id if ctx else uuid.uuid4())
    skill.visibility = Visibility.PRIVATE.value
    skill.name = name
    skill.description = "How refunds are handled."
    skill.content = "# Refunds\n\nCheck the order first."
    skill.enabled = enabled
    skill.version = 1
    skill.resources = resources or []
    return skill


def _row(name: str) -> Skill:
    """A real ORM row, for the tests that go through the response schema.

    Deliberately not the `MagicMock` above: a mock answers every attribute,
    including `built_in` and `file_count`, which are not on the row at all -
    so an assertion about them would hold against a response that never
    carried them.
    """
    return Skill(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        name=name,
        description="How refunds are handled.",
        category=None,
        enabled=True,
        resources=[],
    )


def _bundled(key: str, *, resources: tuple[str, ...] = ()) -> LibrarySkill:
    """One folder of the shipped library, as `skill_library.library()` reads it.

    The real dataclass rather than a mock: `size_bytes` is derived from the
    content, and a mock would answer with something for it whether the service
    passed the file through or not.
    """
    return LibrarySkill(
        key=key,
        name=key,
        description=f"What {key} is for.",
        category=None,
        content=f"# {key}",
        resources=tuple(LibraryResource(name=name, content="body") for name in resources),
    )


def _resource(name="template.md", content="Dear {name},"):
    """One of a skill's files, as the repository hands it back."""
    resource = MagicMock()
    resource.id = uuid.uuid4()
    resource.name = name
    resource.description = None
    resource.content = content
    return resource


def _db():
    db = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


class TestToolsetConstruction:
    def test_no_skills_means_no_toolset(self):
        """Three unusable tools would be context the model reads every turn."""
        assert Skills(skills=[]).get_toolset() is None

    def test_script_execution_is_not_exposed(self):
        """Without a sandbox, run_skill_script is remote code execution."""
        toolset = Skills(skills=[_skill()]).get_toolset()
        assert toolset is not None
        assert "run_skill_script" not in toolset.tools
        assert set(SAFE_SKILL_TOOLS) == set(toolset.tools)

    def test_skills_are_passed_in_memory(self):
        """No temp directory, so no cleanup, no race and no path surface."""
        toolset = Skills(skills=[_skill(), _skill(name="tone-of-voice")]).get_toolset()
        assert toolset is not None
        assert set(toolset.skills) == {"refunds", "tone-of-voice"}

    def test_resources_travel_with_their_skill(self):
        resource = MagicMock()
        resource.name = "template.md"
        resource.description = "Reply template"
        resource.content = "Dear {name},"
        toolset = Skills(skills=[_skill(resources=[resource])]).get_toolset()
        assert toolset is not None
        assert toolset.skills["refunds"].resources[0].name == "template.md"


class TestAgentBinding:
    @pytest.mark.anyio
    async def test_an_agent_bound_to_no_skills_asks_the_database_nothing(self):
        """Most agents have no skills; that must not cost a query per run."""
        with patch("app.services.skills.skill_repo.get_many", new=AsyncMock()) as get_many:
            assert await SkillService(_db()).resolve_for_agent(_ctx(), []) == []

        assert get_many.await_count == 0

    @pytest.mark.anyio
    async def test_a_deleted_skill_degrades_the_agent_not_the_run(self):
        ctx = _ctx()
        present = _skill()
        missing_id = uuid.uuid4()

        with patch(
            "app.services.skills.skill_repo.get_many",
            new=AsyncMock(return_value={present.id: present}),
        ):
            resolved = await SkillService(_db()).resolve_for_agent(ctx, [present.id, missing_id])

        assert resolved == [present]

    @pytest.mark.anyio
    async def test_disabled_skills_are_skipped(self):
        ctx = _ctx()
        disabled = _skill(enabled=False)

        with patch(
            "app.services.skills.skill_repo.get_many",
            new=AsyncMock(return_value={disabled.id: disabled}),
        ):
            assert await SkillService(_db()).resolve_for_agent(ctx, [disabled.id]) == []

    @pytest.mark.anyio
    async def test_a_run_reads_a_skill_the_runner_could_not_reach_themselves(self):
        """Binding is lending, and the gate is publish - deliberately not the run.

        A member's role reaches shared skills only, so this one is a skill they
        could not open in the UI. The agent still reads it, exactly as it still
        searches a collection nobody shared with the person asking: the publisher
        was checked when the version was frozen
        (`AgentRegistryService._skill_problems`), and re-checking per runner would
        make one published version answer differently for two colleagues.
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        private = _skill(ctx=ctx, owner_user_id=uuid.uuid4())

        with patch(
            f"{SKILLS_PATH}.skill_repo.get_many",
            new=AsyncMock(return_value={private.id: private}),
        ):
            assert await SkillService(_db()).resolve_for_agent(ctx, [private.id]) == [private]

    @pytest.mark.anyio
    async def test_a_run_with_no_subject_still_reads_the_agents_skills(self):
        """The concrete reason a per-runner check here would be wrong.

        An API key, an embedded widget and a channel message all run on a context
        with no subject, and `resolve_access` refuses every one of those by
        design - so a runner-scoped check would strip every skill from exactly the
        surfaces a published agent exists to be reached through.
        """
        ctx = AuthContext.anonymous(uuid.uuid4())
        skill = _skill(ctx=ctx)

        with patch(
            f"{SKILLS_PATH}.skill_repo.get_many", new=AsyncMock(return_value={skill.id: skill})
        ):
            assert await SkillService(_db()).resolve_for_agent(ctx, [skill.id]) == [skill]

    @pytest.mark.anyio
    async def test_binding_order_is_preserved(self):
        """The order skills appear in is the order the model sees them listed."""
        ctx = _ctx()
        first, second = _skill(name="a"), _skill(name="b")

        with patch(
            "app.services.skills.skill_repo.get_many",
            new=AsyncMock(return_value={first.id: first, second.id: second}),
        ):
            resolved = await SkillService(_db()).resolve_for_agent(ctx, [second.id, first.id])

        assert [skill.name for skill in resolved] == ["b", "a"]


class TestSkillManagement:
    @pytest.mark.anyio
    async def test_duplicate_names_are_refused(self):
        """The name is how the model refers to a skill; two is an ambiguity."""
        with (
            patch(
                "app.services.skills.skill_repo.get_by_name",
                new=AsyncMock(return_value=_skill()),
            ),
            pytest.raises(AlreadyExistsError) as refused,
        ):
            await SkillService(_db()).create(_ctx(), name="refunds", description="x", content="")

        assert refused.value.details == {"name": "refunds"}
        # The refusal is expected, recoverable and one keystroke from being
        # resolved, so it has to name both ways out rather than only report
        # that the name is taken.
        assert "refunds" in refused.value.message
        assert "choose a different one" in refused.value.message
        assert "edit it" in refused.value.message

    @pytest.mark.anyio
    async def test_creation_is_audited(self):
        with (
            patch("app.services.skills.skill_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                "app.services.skills.skill_repo.create",
                new=AsyncMock(return_value=_skill()),
            ),
            patch("app.services.skills.record_audit", new=AsyncMock()) as audit,
        ):
            await SkillService(_db()).create(
                _ctx(), name="refunds", description="How refunds work", content="# Refunds"
            )
        assert audit.call_args.kwargs["action"] == "skill.created"

    @pytest.mark.anyio
    async def test_a_skill_you_cannot_reach_is_indistinguishable_from_one_that_is_not_there(self):
        """Otherwise the error message becomes an oracle for enumerating skill ids.

        Another organization's skill never comes back from the org-scoped
        lookup at all; one inside the organization that the caller may not see
        is refused after it. Both must read exactly the same, down to the
        details, or a member can probe for skills they were never shown.
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        forbidden = _skill(ctx=ctx, owner_user_id=uuid.uuid4())

        with (
            patch("app.services.skills.skill_repo.get", new=AsyncMock(return_value=forbidden)),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError) as refused,
        ):
            await SkillService(_db()).get(ctx, forbidden.id)

        with (
            patch("app.services.skills.skill_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError) as absent,
        ):
            await SkillService(_db()).get(ctx, forbidden.id)

        assert refused.value.message == absent.value.message
        assert refused.value.details == absent.value.details == {"skill_id": str(forbidden.id)}

    @pytest.mark.anyio
    async def test_the_organizations_skills_are_listed(self):
        ctx = _ctx()
        mine = _skill(ctx=ctx)

        with patch(
            "app.services.skills.skill_repo.list_visible", new=AsyncMock(return_value=([mine], 1))
        ) as list_visible:
            listed, total = await SkillService(_db()).list_skills(ctx)

        assert listed == [mine]
        assert total == 1
        assert list_visible.call_args.kwargs["organization_id"] == ctx.organization_id

    @pytest.mark.anyio
    async def test_the_listing_marks_a_skill_installed_from_the_library(self):
        """`built_in` is a name match, because an install keeps nothing else.

        A row that came from the shipped library and one somebody typed are the
        same shape; only the name says which, so an install that renamed on the
        way in would be indistinguishable from local work.
        """
        ctx = _ctx()
        installed, local = _row("refunds"), _row("our-own-thing")
        bundled = MagicMock()
        bundled.name = "refunds"

        with (
            patch(
                f"{SKILLS_PATH}.skill_repo.list_visible",
                new=AsyncMock(return_value=([installed, local], 2)),
            ),
            patch(f"{SKILLS_PATH}.skill_repo.list_categories", new=AsyncMock(return_value=[])),
            patch(
                f"{SKILLS_PATH}.skill_repo.list_names",
                new=AsyncMock(return_value={"refunds", "our-own-thing"}),
            ),
            patch(f"{SKILLS_PATH}.skill_library.library", return_value=[bundled]),
        ):
            listing = await SkillService(_db()).list_readable(ctx)

        assert [item.built_in for item in listing.items] == [True, False]

    @pytest.mark.anyio
    async def test_the_listing_carries_the_filters_the_page_cannot(self):
        """`total`, `categories` and the suggestions all outlive the page.

        Paging or searching narrows `items` and must not narrow any of them: a
        pager needs the count before paging, and a filter chip that vanished
        with the page it filtered would strand whoever pressed it.
        """
        ctx = _ctx()

        with (
            patch(
                f"{SKILLS_PATH}.skill_repo.list_visible",
                new=AsyncMock(return_value=([_row("refunds")], 87)),
            ),
            patch(
                f"{SKILLS_PATH}.skill_repo.list_categories",
                new=AsyncMock(return_value=["devops", "support"]),
            ),
            patch(f"{SKILLS_PATH}.skill_repo.list_names", new=AsyncMock(return_value=set())),
            patch(f"{SKILLS_PATH}.skill_library.library", return_value=[]),
        ):
            listing = await SkillService(_db()).list_readable(ctx, search="refund", limit=1)

        assert len(listing.items) == 1
        assert listing.total == 87
        assert listing.categories == ["devops", "support"]
        assert listing.suggested_categories == list(SUGGESTED_CATEGORIES)

    @pytest.mark.anyio
    async def test_a_role_that_sees_everything_never_looks_up_grants(self):
        """A query per listing, on every page, for a set that cannot widen anything."""
        ctx = _ctx(OrgRoleName.OWNER)

        with (
            patch(
                "app.services.access.resource_grant_repo.list_shared_ids", new=AsyncMock()
            ) as shared_ids,
            patch(
                "app.services.skills.skill_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await SkillService(_db()).list_skills(ctx)

        assert shared_ids.await_count == 0
        assert list_visible.call_args.kwargs["see_all"] is True
        assert list_visible.call_args.kwargs["shared_ids"] == []

    @pytest.mark.anyio
    async def test_a_narrower_role_lists_only_theirs_plus_what_was_shared(self):
        """The listing must admit exactly the rows resolve_access would, one by one.

        A viewer's role scope is "mine plus what was shared with me", so the
        query gets their user id for the ownership predicate and the granted
        ids for the shared one - and never the whole organization.
        """
        ctx = _ctx(OrgRoleName.VIEWER)
        shared = uuid.uuid4()

        with (
            patch(
                "app.services.access.resource_grant_repo.list_shared_ids",
                new=AsyncMock(return_value=[shared]),
            ) as shared_ids,
            patch(
                "app.services.skills.skill_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await SkillService(_db()).list_skills(ctx)

        assert shared_ids.call_args.kwargs["minimum_level"] is GrantLevel.READ
        assert list_visible.call_args.kwargs["see_all"] is False
        assert list_visible.call_args.kwargs["shared_ids"] == [shared]
        assert list_visible.call_args.kwargs["user_id"] == ctx.user_id

    @pytest.mark.anyio
    async def test_shared_with_me_for_a_wide_role_still_looks_up_grants(self):
        """ "Shared with me" is about grants and visibility, not reach."""
        ctx = _ctx(OrgRoleName.OWNER)
        granted = uuid.uuid4()

        with (
            patch(
                "app.services.skills.resource_grant_repo.list_shared_ids",
                new=AsyncMock(return_value=[granted]),
            ) as shared_ids,
            patch(
                "app.services.skills.skill_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await SkillService(_db()).list_skills(ctx, shared_with_me=True)

        assert shared_ids.await_count == 1
        assert list_visible.call_args.kwargs["see_all"] is True
        assert list_visible.call_args.kwargs["shared_with_me"] is True
        assert list_visible.call_args.kwargs["shared_ids"] == [granted]

    @pytest.mark.anyio
    async def test_shared_with_me_for_a_narrow_role_reuses_its_grant_lookup(self):
        """One grants query per listing, not two."""
        ctx = _ctx(OrgRoleName.MEMBER)
        granted = uuid.uuid4()

        with (
            patch(
                "app.services.access.resource_grant_repo.list_shared_ids",
                new=AsyncMock(return_value=[granted]),
            ) as shared_ids,
            patch(
                "app.services.skills.skill_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await SkillService(_db()).list_skills(ctx, shared_with_me=True)

        assert shared_ids.await_count == 1
        assert list_visible.call_args.kwargs["see_all"] is False
        assert list_visible.call_args.kwargs["shared_with_me"] is True
        assert list_visible.call_args.kwargs["shared_ids"] == [granted]

    @pytest.mark.anyio
    async def test_the_search_is_the_databases_and_so_is_the_page(self):
        """The client never holds an organization's whole set, so it cannot filter one."""
        ctx = _ctx()

        with patch(
            "app.services.skills.skill_repo.list_visible", new=AsyncMock(return_value=([], 0))
        ) as list_visible:
            await SkillService(_db()).list_skills(ctx, search="refund", skip=50, limit=25)

        assert list_visible.call_args.kwargs["search"] == "refund"
        assert list_visible.call_args.kwargs["skip"] == 50
        assert list_visible.call_args.kwargs["limit"] == 25

    @pytest.mark.anyio
    async def test_the_category_filter_and_the_sort_are_the_databases_too(self):
        """Same reason as the search: a page of fifty cannot be regrouped client-side.

        Plural: the filter is a multi-select, and "either shelf" has to reach
        the query as the whole list, not as whichever entry won.
        """
        ctx = _ctx()

        with patch(
            "app.services.skills.skill_repo.list_visible", new=AsyncMock(return_value=([], 0))
        ) as list_visible:
            await SkillService(_db()).list_skills(
                ctx, categories=["devops", "data"], sort="updated"
            )

        assert list_visible.call_args.kwargs["categories"] == ["devops", "data"]
        assert list_visible.call_args.kwargs["sort"] == "updated"

    def test_every_suggested_category_is_storable(self):
        """The pickers offer these before an organization invents its own; a
        suggestion the create endpoint would then refuse is a trap, so each one
        must pass the same validation a typed category does."""
        from app.schemas.skill import SkillCreate
        from app.services.skills import SUGGESTED_CATEGORIES

        assert SUGGESTED_CATEGORIES
        assert len(set(SUGGESTED_CATEGORIES)) == len(SUGGESTED_CATEGORIES)
        for name in SUGGESTED_CATEGORIES:
            SkillCreate(name="x", description="d", category=name)

    @pytest.mark.anyio
    async def test_the_category_choices_come_from_the_whole_organization(self):
        """The chips must not shrink to what the current page happens to show."""
        ctx = _ctx()

        with patch(
            "app.services.skills.skill_repo.list_categories",
            new=AsyncMock(return_value=["devops", "marketing"]),
        ) as list_categories:
            categories = await SkillService(_db()).list_categories(ctx)

        assert categories == ["devops", "marketing"]
        assert list_categories.call_args.kwargs["organization_id"] == ctx.organization_id

    @pytest.mark.anyio
    async def test_a_skill_is_created_on_the_shelf_it_was_given(self):
        with (
            patch("app.services.skills.skill_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                "app.services.skills.skill_repo.create", new=AsyncMock(return_value=_skill())
            ) as create,
            patch("app.services.skills.record_audit", new=AsyncMock()),
        ):
            await SkillService(_db()).create(
                _ctx(), name="refunds", description="x", content="", category="support"
            )

        assert create.call_args.kwargs["category"] == "support"

    @pytest.mark.anyio
    async def test_an_edit_bumps_the_version_agents_are_told_about(self):
        """Agents bind to a skill, not a version, so the bump is how an edit is noticed."""
        ctx = _ctx()
        skill = _skill(ctx=ctx)

        with (
            patch("app.services.skills.skill_repo.get", new=AsyncMock(return_value=skill)),
            patch(
                "app.services.skills.skill_repo.update", new=AsyncMock(return_value=skill)
            ) as update,
        ):
            updated = await SkillService(_db()).update(
                ctx, skill.id, SkillUpdate(content="# New policy")
            )

        assert update.call_args.kwargs["update_data"] == {
            "content": "# New policy",
            "version": skill.version + 1,
        }
        assert update.call_args.kwargs["skill"] is skill
        assert updated is skill

    @pytest.mark.anyio
    async def test_an_edit_is_audited_with_what_changed(self):
        """The highest-consequence of the three skill events.

        Creating and deleting a skill were already audited; editing one changes
        what every bound agent executes on its next run without changing which
        agents are affected, so it is the one most worth attributing later.
        """
        ctx = _ctx()
        skill = _skill(ctx=ctx)

        with (
            patch("app.services.skills.skill_repo.get", new=AsyncMock(return_value=skill)),
            patch("app.services.skills.skill_repo.update", new=AsyncMock(return_value=skill)),
            patch("app.services.skills.record_audit", new=AsyncMock()) as audit,
        ):
            await SkillService(_db()).update(ctx, skill.id, SkillUpdate(content="# New policy"))

        recorded = audit.call_args.kwargs
        assert recorded["action"] == "skill.updated"
        assert recorded["target_id"] == str(skill.id)
        assert "content" in recorded["details"]["fields"]

    @pytest.mark.anyio
    async def test_editing_a_skill_you_cannot_edit_writes_nothing(self):
        """Viewing and editing are separate permissions; the edit check is the one that counts."""
        ctx = _ctx(OrgRoleName.VIEWER)
        skill = _skill(ctx=ctx, owner_user_id=uuid.uuid4())

        with (
            patch("app.services.skills.skill_repo.get", new=AsyncMock(return_value=skill)),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            patch("app.services.skills.skill_repo.update", new=AsyncMock()) as update,
            pytest.raises(NotFoundError),
        ):
            await SkillService(_db()).update(ctx, skill.id, SkillUpdate(content="# Rewritten"))

        assert update.await_count == 0

    @pytest.mark.anyio
    async def test_deleting_a_skill_takes_the_grants_that_pointed_at_it(self):
        """The grant table is generic - no foreign key, so nothing cascades for it.

        Left behind, those rows share an id that no longer means anything, and
        they would silently apply to whatever reuses it.
        """
        ctx = _ctx()
        skill = _skill(ctx=ctx)

        with (
            patch("app.services.skills.skill_repo.get", new=AsyncMock(return_value=skill)),
            patch(
                "app.services.skills.resource_grant_repo.delete_for_resource", new=AsyncMock()
            ) as drop_grants,
            patch("app.services.skills.skill_repo.delete", new=AsyncMock()) as delete,
            patch("app.services.skills.record_audit", new=AsyncMock()) as audit,
        ):
            await SkillService(_db()).delete(ctx, skill.id)

        assert drop_grants.call_args.kwargs["resource_type"] == "skill"
        assert drop_grants.call_args.kwargs["resource_id"] == skill.id
        assert drop_grants.call_args.kwargs["organization_id"] == ctx.organization_id
        assert delete.call_args.args[1] is skill
        assert audit.call_args.kwargs["action"] == "skill.deleted"
        assert audit.call_args.kwargs["target_id"] == str(skill.id)


class TestBundledTopUp:
    """The listing closes the gap between the shipped catalog and an organization.

    Creation-time seeding copies whatever the deployment shipped *that day*; a
    skill added to the catalog later would otherwise never reach an existing
    organization, and its page would show one bundled skill where the
    deployment ships three - which is exactly how the defect was found.
    """

    def _bundled(self, key: str, name: str | None = None) -> MagicMock:
        entry = MagicMock()
        entry.key = key
        entry.name = name or key
        return entry

    @pytest.mark.anyio
    async def test_a_skill_added_to_the_catalog_appears_on_the_next_listing(self):
        ctx = _ctx()
        owner_id = uuid.uuid4()

        with (
            patch(f"{SKILLS_PATH}.skill_repo.list_visible", new=AsyncMock(return_value=([], 0))),
            patch(f"{SKILLS_PATH}.skill_repo.list_categories", new=AsyncMock(return_value=[])),
            patch(
                f"{SKILLS_PATH}.skill_repo.list_names",
                new=AsyncMock(return_value={"refund-policy"}),
            ),
            patch(
                f"{SKILLS_PATH}.skill_library.library",
                return_value=[self._bundled("refund-policy"), self._bundled("incident-report")],
            ),
            patch(
                f"{SKILLS_PATH}.member_repo.first_owner_id",
                new=AsyncMock(return_value=owner_id),
            ),
            patch.object(SkillService, "install_from_library", new=AsyncMock()) as install,
        ):
            await SkillService(_db()).list_readable(ctx)

        # Only the gap, and as the organization's owner - the reader whose
        # visit triggered this may be a viewer, and ownership widens access.
        install.assert_awaited_once()
        installer_ctx, key = install.await_args.args
        assert key == "incident-report"
        assert installer_ctx.user_id == owner_id
        assert installer_ctx.organization_id == ctx.organization_id

    @pytest.mark.anyio
    async def test_a_complete_organization_installs_nothing_and_asks_for_no_owner(self):
        ctx = _ctx()

        with (
            patch(f"{SKILLS_PATH}.skill_repo.list_visible", new=AsyncMock(return_value=([], 0))),
            patch(f"{SKILLS_PATH}.skill_repo.list_categories", new=AsyncMock(return_value=[])),
            patch(
                f"{SKILLS_PATH}.skill_repo.list_names",
                new=AsyncMock(return_value={"refund-policy"}),
            ),
            patch(
                f"{SKILLS_PATH}.skill_library.library",
                return_value=[self._bundled("refund-policy")],
            ),
            patch(f"{SKILLS_PATH}.member_repo.first_owner_id", new=AsyncMock()) as owner_lookup,
            patch.object(SkillService, "install_from_library", new=AsyncMock()) as install,
        ):
            await SkillService(_db()).list_readable(ctx)

        owner_lookup.assert_not_awaited()
        install.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_organization_with_no_owner_is_left_alone(self):
        # A skill row records who owns it, and that column is a foreign key to
        # a real person - with nobody to attribute to, the listing answers what
        # is there rather than inventing an owner or failing the page.
        ctx = _ctx()

        with (
            patch(f"{SKILLS_PATH}.skill_repo.list_visible", new=AsyncMock(return_value=([], 0))),
            patch(f"{SKILLS_PATH}.skill_repo.list_categories", new=AsyncMock(return_value=[])),
            patch(f"{SKILLS_PATH}.skill_repo.list_names", new=AsyncMock(return_value=set())),
            patch(
                f"{SKILLS_PATH}.skill_library.library",
                return_value=[self._bundled("refund-policy")],
            ),
            patch(f"{SKILLS_PATH}.member_repo.first_owner_id", new=AsyncMock(return_value=None)),
            patch.object(SkillService, "install_from_library", new=AsyncMock()) as install,
        ):
            listing = await SkillService(_db()).list_readable(ctx)

        install.assert_not_awaited()
        assert listing.total == 0

    @pytest.mark.anyio
    async def test_a_racing_twin_costs_that_row_and_never_the_readers_page(self):
        # Two first listings can race to the same missing skill; the loser's
        # collision is caught per-install, so the page still answers.
        ctx = _ctx()

        with (
            patch(f"{SKILLS_PATH}.skill_repo.list_visible", new=AsyncMock(return_value=([], 0))),
            patch(f"{SKILLS_PATH}.skill_repo.list_categories", new=AsyncMock(return_value=[])),
            patch(f"{SKILLS_PATH}.skill_repo.list_names", new=AsyncMock(return_value=set())),
            patch(
                f"{SKILLS_PATH}.skill_library.library",
                return_value=[self._bundled("refund-policy"), self._bundled("incident-report")],
            ),
            patch(
                f"{SKILLS_PATH}.member_repo.first_owner_id",
                new=AsyncMock(return_value=uuid.uuid4()),
            ),
            patch.object(
                SkillService,
                "install_from_library",
                new=AsyncMock(side_effect=[AlreadyExistsError(message="taken"), MagicMock()]),
            ) as install,
        ):
            listing = await SkillService(_db()).list_readable(ctx)

        # The collision did not stop the second install, and the listing answered.
        assert install.await_count == 2
        assert listing.suggested_categories == list(SUGGESTED_CATEGORIES)


class TestSkillLibrary:
    """The skills this deployment ships with, and what installing one does."""

    def test_every_bundled_skill_reads(self):
        """A folder that cannot be parsed is skipped and logged, so a broken one
        would show up here as an absence rather than as an exception."""
        from app.services import skill_library

        keys = {skill.key for skill in skill_library.library()}

        assert {"code-review", "incident-report", "refund-policy"} <= keys

    def test_a_bundled_skill_carries_its_files(self):
        """The whole point of the folder shape: a skill is a body plus the
        detail it loads on demand."""
        from app.services import skill_library

        skill = skill_library.get("code-review")

        assert skill is not None
        assert skill.description
        assert {resource.name for resource in skill.resources} == {
            "checklist.md",
            "review-comment.md",
        }
        assert all(resource.size_bytes > 0 for resource in skill.resources)

    def test_every_bundled_skill_names_its_shelf(self):
        """The listing groups by category, and a shipped skill that arrived
        uncategorized would sit outside every chip from its first day."""
        from app.services import skill_library

        by_key = {skill.key: skill.category for skill in skill_library.library()}

        assert by_key["code-review"] == "engineering"
        assert by_key["incident-report"] == "operations"
        assert by_key["refund-policy"] == "support"

    def test_a_manifest_without_a_category_is_simply_uncategorized(self, tmp_path):
        """The column is nullable for the same reason: no category is a state,
        not an error."""
        from app.services.skill_library import _read

        folder = tmp_path / "plain"
        folder.mkdir()
        (folder / "SKILL.md").write_text("---\ndescription: Plain.\n---\n\nBody.\n")

        assert _read(folder).category is None

    def test_the_frontmatter_is_not_left_in_the_body(self):
        """The model reads the body; a YAML header in it is noise it has to
        parse around."""
        from app.services import skill_library

        skill = skill_library.get("refund-policy")

        assert skill is not None
        assert not skill.content.startswith("---")
        assert "# Refunds" in skill.content

    def test_a_manifest_without_frontmatter_still_yields_a_skill(self, tmp_path):
        """Refusing would turn a missing header into a missing skill."""
        from app.services.skill_library import _read

        folder = tmp_path / "plain"
        folder.mkdir()
        (folder / "SKILL.md").write_text("---\ndescription: Plain.\n---\n\nBody.\n")

        skill = _read(folder)

        assert (skill.key, skill.name, skill.content) == ("plain", "plain", "Body.")

    def test_a_manifest_with_no_description_is_refused(self, tmp_path):
        """The description is what the model reads before deciding to load the
        body - a skill without one can never be chosen."""
        from app.services.skill_library import _read

        folder = tmp_path / "nameless"
        folder.mkdir()
        (folder / "SKILL.md").write_text("---\nname: nameless\n---\n\nBody.\n")

        with pytest.raises(ValueError, match="no description"):
            _read(folder)

    @pytest.mark.anyio
    async def test_installing_copies_the_body_and_every_file(self):
        ctx = _ctx()
        created = MagicMock(id=uuid.uuid4(), name="code-review")

        with (
            patch(f"{SKILLS_PATH}.skill_repo.get_by_name", new=AsyncMock(return_value=None)),
            patch(
                f"{SKILLS_PATH}.skill_repo.create", new=AsyncMock(return_value=created)
            ) as create,
            patch(f"{SKILLS_PATH}.skill_repo.create_resource", new=AsyncMock()) as add_resource,
            patch(f"{SKILLS_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await SkillService(_db()).install_from_library(ctx, "code-review")

        assert create.call_args.kwargs["name"] == "code-review"
        assert create.call_args.kwargs["content"]
        # The copy keeps the shelf the library put it on, and lands visible to
        # the whole organization - seeding is for everybody, not the seeder.
        assert create.call_args.kwargs["category"] == "engineering"
        assert create.call_args.kwargs["visibility"] == Visibility.ORG
        assert {call.kwargs["name"] for call in add_resource.await_args_list} == {
            "checklist.md",
            "review-comment.md",
        }
        assert [call.kwargs["action"] for call in audit.await_args_list] == [
            "skill.created",
            "skill.installed",
        ]
        # The actor on a seeded install is the first owner as an attribution,
        # not as a person who acted - the marker is what keeps the entry honest.
        assert audit.await_args_list[-1].kwargs["details"]["seeded"] is True

    @pytest.mark.anyio
    async def test_installing_something_that_does_not_ship_is_refused(self):
        with pytest.raises(NotFoundError, match="No such bundled skill"):
            await SkillService(_db()).install_from_library(_ctx(), "not-a-skill")

    @pytest.mark.anyio
    async def test_installing_twice_is_refused_by_name(self):
        """Two skills of one name is a reference the model cannot resolve, and
        the second install would silently produce one."""
        ctx = _ctx()

        with (
            patch(
                f"{SKILLS_PATH}.skill_repo.get_by_name",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(f"{SKILLS_PATH}.skill_repo.create_resource", new=AsyncMock()) as add_resource,
            patch(f"{SKILLS_PATH}.record_audit", new=AsyncMock()),
            pytest.raises(AlreadyExistsError),
        ):
            await SkillService(_db()).install_from_library(ctx, "code-review")

        assert add_resource.await_count == 0


class TestResourceNames:
    """What an uploaded file may be called.

    A resource name is a key in a table rather than a location on disk, so
    nothing here escapes anything today. It is refused anyway, for two reasons:
    a name that *reads* as an escape is one nobody reviewing a skill can reason
    about, and this refusal is the only thing standing between an upload and
    the filesystem the day one of these names is joined onto a path.
    """

    @pytest.mark.parametrize(
        "raw",
        [
            "../secrets.md",
            "references/../../etc/passwd",
            "..\\..\\windows\\hosts",
            "./../x.md",
            "references/..",
        ],
    )
    def test_a_name_that_steps_outside_the_skill_is_refused(self, raw):
        with pytest.raises(BadRequestError) as refused:
            _clean_resource_path(raw)

        assert "cannot step outside" in refused.value.message
        assert refused.value.details == {"name": raw}

    @pytest.mark.parametrize("raw", ["notes..md", "references/..hidden.md", "a/b..c/d.md"])
    def test_two_dots_inside_a_segment_are_part_of_a_file_name_not_a_step(self, raw):
        """The check is on whole segments. Refusing every name containing two
        dots would reject files people really have and teach them the rule is
        about characters rather than about stepping out of the skill."""
        assert _clean_resource_path(raw) == raw

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("references\\workflows.md", "references/workflows.md"),
            ("/skill/./references//workflows.md", "skill/references/workflows.md"),
        ],
    )
    def test_whatever_the_browser_sent_normalizes_to_one_name(self, raw, expected):
        """A directory picker adds a leading folder and Windows sends
        backslashes. The same file uploaded from two machines has to land on
        one row, because the name is what the model asks for."""
        assert _clean_resource_path(raw) == expected

    @pytest.mark.parametrize("raw", ["", "/", ".", "./", "//"])
    def test_a_name_that_normalizes_to_nothing_is_refused(self, raw):
        """A row keyed on the empty string is a file no model can ever ask for."""
        with pytest.raises(BadRequestError) as refused:
            _clean_resource_path(raw)

        assert refused.value.message == "A file needs a name"
        assert refused.value.details == {"name": raw}

    def test_a_path_longer_than_the_column_is_refused_rather_than_truncated(self):
        """`skill_resources.name` is 128 characters. Truncating would collapse
        two deep paths onto one name, and the second upload would then silently
        overwrite the first."""
        assert len(_clean_resource_path("a" * 128)) == 128

        with pytest.raises(BadRequestError, match="128 characters"):
            _clean_resource_path("references/" + "a" * 118)


class TestResourceContents:
    """The other half of the guard: what a file may contain."""

    def test_a_file_the_model_could_not_read_is_refused_rather_than_stored_as_noise(self):
        """A skill's files are handed to the model as text. A PDF stored here
        arrives as mojibake - a file the agent is told it has and cannot use,
        which is worse than not having it - so the refusal names the file and
        says what to do instead."""
        with pytest.raises(BadRequestError) as refused:
            _decode_text("report.pdf", b"%PDF-1.7\n\xff\xfe\x00\x01")

        assert "not text" in refused.value.message
        assert "URL" in refused.value.message
        assert refused.value.details == {"name": "report.pdf"}

    def test_the_guard_is_utf_8_and_not_ascii(self):
        """A checklist written in Polish is an ordinary skill file, and the
        bytes that make it non-ASCII must not read as a binary."""
        assert _decode_text("kroki.md", "Zwrot 50 zł - sprawdź ✓".encode()) == (
            "Zwrot 50 zł - sprawdź ✓"
        )

    def test_a_file_over_the_size_limit_is_refused(self):
        """Everything attached to a skill is loaded into a prompt, so the limit
        is what keeps one dropped archive from filling an agent's context. The
        last byte that fits still fits - a limit that refused it would be a
        different limit than the message states."""
        assert _decode_text("big.md", b"a" * MAX_RESOURCE_BYTES) == "a" * MAX_RESOURCE_BYTES

        with pytest.raises(BadRequestError, match="512 KB") as refused:
            _decode_text("big.md", b"a" * (MAX_RESOURCE_BYTES + 1))

        assert refused.value.details == {"name": "big.md"}


class TestSkillFiles:
    """A skill's files: the reference table, the template, the worked example.

    Two invariants run through all of it. Every write bumps the version, because
    a file is part of the skill as far as a bound agent is concerned; and every
    refusal writes nothing at all, because a version that moved for an upload
    the database then discarded says an agent changed when it did not.
    """

    @pytest.fixture
    def repo(self, monkeypatch):
        repo = MagicMock()
        repo.get = AsyncMock()
        repo.get_resource = AsyncMock(return_value=None)
        repo.get_resource_by_name = AsyncMock(return_value=None)
        repo.create_resource = AsyncMock()
        repo.update_resource = AsyncMock()
        repo.delete_resource = AsyncMock()
        repo.update = AsyncMock()
        monkeypatch.setattr(f"{SKILLS_PATH}.skill_repo", repo)
        return repo

    @pytest.fixture
    def audit(self, monkeypatch):
        recorder = AsyncMock()
        monkeypatch.setattr(f"{SKILLS_PATH}.record_audit", recorder)
        return recorder

    @pytest.fixture
    def ctx(self) -> AuthContext:
        return _ctx()

    @pytest.fixture
    def service(self) -> SkillService:
        return SkillService(_db())

    @pytest.fixture
    def skill(self, ctx, repo):
        """A skill the caller owns, already found by the repository."""
        owned = _skill(ctx=ctx)
        repo.get.return_value = owned
        return owned

    # -- attaching one file ---------------------------------------------

    @pytest.mark.anyio
    async def test_attaching_a_file_bumps_the_version_and_names_it_in_the_audit(
        self, service, ctx, repo, audit, skill
    ):
        """A file is part of the skill as far as a bound agent is concerned, so
        adding one is the same kind of event as rewriting the body. A version
        that only moved for the body would report an agent as unchanged while
        its reference table was being replaced."""
        stored = _resource(name="template.md")
        repo.create_resource.return_value = stored

        created = await service.add_resource(
            ctx, skill.id, name="template.md", description="Reply template", content="Dear {name},"
        )

        assert created is stored
        assert repo.create_resource.await_args.kwargs["skill_id"] == skill.id
        assert repo.update.await_args.kwargs["update_data"] == {"version": skill.version + 1}
        recorded = audit.await_args.kwargs
        assert recorded["action"] == "skill.resource_added"
        assert recorded["details"] == {"name": skill.name, "resource": "template.md"}

    @pytest.mark.anyio
    async def test_a_second_file_of_the_same_name_is_refused_and_nothing_is_written(
        self, service, ctx, repo, audit, skill
    ):
        """The name is what the model asks for, so two of them is a reference
        nothing can resolve."""
        repo.get_resource_by_name.return_value = _resource(name="template.md")

        with pytest.raises(AlreadyExistsError) as refused:
            await service.add_resource(
                ctx, skill.id, name="template.md", description=None, content="Dear {name},"
            )

        assert refused.value.details == {"name": "template.md", "field": "name"}
        repo.create_resource.assert_not_awaited()
        repo.update.assert_not_awaited()
        audit.assert_not_awaited()

    # -- uploading a set of them ----------------------------------------

    @pytest.mark.anyio
    async def test_a_folder_upload_keeps_its_shape_in_the_names_it_stores(
        self, service, ctx, repo, audit, skill
    ):
        """There is deliberately no folder table: a folder is a prefix some file
        has, which is why an empty one cannot exist and nothing has to keep the
        two in step."""
        repo.create_resource.side_effect = [
            _resource(name="skill/references/workflows.md"),
            _resource(name="skill/SKILL.md"),
        ]

        await service.put_resources(
            ctx,
            skill.id,
            [("skill\\references/workflows.md", b"# Workflows"), ("./skill/SKILL.md", b"# Body")],
        )

        assert [call.kwargs["name"] for call in repo.create_resource.await_args_list] == [
            "skill/references/workflows.md",
            "skill/SKILL.md",
        ]
        assert audit.await_args.kwargs["details"] == {
            "name": skill.name,
            "files": ["skill/references/workflows.md", "skill/SKILL.md"],
        }

    @pytest.mark.anyio
    async def test_re_uploading_a_folder_replaces_the_file_that_changed(
        self, service, ctx, repo, audit, skill
    ):
        """This is the upload path: somebody dragging a corrected folder in
        means the corrected version. Refusing the paths that already exist would
        ask them to do the merge by hand."""
        existing = _resource(name="checklist.md", content="old")
        added = _resource(name="template.md")
        repo.get_resource_by_name.side_effect = [existing, None]
        repo.update_resource.return_value = existing
        repo.create_resource.return_value = added

        written = await service.put_resources(
            ctx, skill.id, [("checklist.md", b"new"), ("template.md", b"Dear {name},")]
        )

        assert written == [existing, added]
        assert repo.update_resource.await_args.kwargs == {
            "resource": existing,
            "update_data": {"content": "new"},
        }
        assert repo.create_resource.await_count == 1

    @pytest.mark.anyio
    async def test_the_version_moves_once_for_the_whole_upload(
        self, service, ctx, repo, audit, skill
    ):
        """Three files dropped in together are one edit. A bump per file would
        make the version a count of files rather than a mark that what bound
        agents execute has changed."""
        await service.put_resources(ctx, skill.id, [("a.md", b"a"), ("b.md", b"b"), ("c.md", b"c")])

        repo.update.assert_awaited_once_with(
            service.db, skill=skill, update_data={"version": skill.version + 1}
        )

    @pytest.mark.anyio
    async def test_a_path_that_steps_outside_the_skill_never_reaches_the_repository(
        self, service, ctx, repo, audit, skill
    ):
        """The refusal has to happen before the write rather than beside it: a
        name the service rejected and stored anyway is the guard undone."""
        with pytest.raises(BadRequestError, match="cannot step outside"):
            await service.put_resources(
                ctx, skill.id, [("../../etc/passwd", b"root:x:0:0"), ("notes.md", b"fine")]
            )

        repo.create_resource.assert_not_awaited()
        repo.update_resource.assert_not_awaited()
        repo.update.assert_not_awaited()
        audit.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_refused_upload_leaves_the_version_and_the_audit_trail_alone(
        self, service, ctx, repo, audit, skill
    ):
        """The offending file can arrive after a good one, and the request is
        still refused whole. What was already written rolls back with the
        request's transaction - but a version bumped on the way past would
        survive nothing and describe an edit that never landed."""
        with pytest.raises(BadRequestError, match="cannot step outside"):
            await service.put_resources(
                ctx, skill.id, [("notes.md", b"fine"), ("../../etc/passwd", b"root:x:0:0")]
            )

        assert [call.kwargs["name"] for call in repo.create_resource.await_args_list] == [
            "notes.md"
        ]
        repo.update.assert_not_awaited()
        audit.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_binary_file_refuses_the_upload_rather_than_storing_noise(
        self, service, ctx, repo, audit, skill
    ):
        """What the model receives is a string, so a PNG would arrive as noise
        the agent is told it has and cannot read."""
        with pytest.raises(BadRequestError, match="not text") as refused:
            await service.put_resources(ctx, skill.id, [("logo.png", b"\x89PNG\r\n\x1a\n\xff\xfe")])

        assert refused.value.details == {"name": "logo.png"}
        repo.create_resource.assert_not_awaited()
        repo.update.assert_not_awaited()
        audit.assert_not_awaited()

    @pytest.mark.anyio
    async def test_uploading_to_a_skill_you_may_read_but_not_edit_writes_nothing(
        self, service, repo, audit
    ):
        """Viewing and editing are separate permissions and a Builder sees every
        skill in the organization while editing only their own. Files are an
        edit: the body says how the work is done, the files are the detail it
        works from, and both reach every bound agent on its next run."""
        ctx = _ctx(OrgRoleName.BUILDER)
        someone_elses = _skill(ctx=ctx, owner_user_id=uuid.uuid4())
        repo.get.return_value = someone_elses

        with (
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError),
        ):
            await service.put_resources(ctx, someone_elses.id, [("notes.md", b"fine")])

        repo.create_resource.assert_not_awaited()
        repo.update.assert_not_awaited()

        # What was refused is the edit, not the row: the same Builder reading
        # the same skill's files goes through.
        readable = _resource()
        repo.get_resource.return_value = readable
        assert await service.get_resource(ctx, someone_elses.id, readable.id) is readable

    # -- reading, editing and removing one ------------------------------

    @pytest.mark.anyio
    async def test_a_file_is_looked_up_inside_the_skill_that_owns_it(
        self, service, ctx, repo, skill
    ):
        """The caller proved they may reach *this skill*. A resource id from
        another one must not be readable through it, and the scoped lookup is
        what enforces that - the id alone proves nothing."""
        stored = _resource()
        repo.get_resource.return_value = stored

        found = await service.get_resource(ctx, skill.id, stored.id)

        assert found is stored
        assert repo.get_resource.await_args.args[1] == stored.id
        assert repo.get_resource.await_args.kwargs == {"skill_id": skill.id}

    @pytest.mark.anyio
    async def test_a_file_id_that_belongs_to_another_skill_is_not_found(
        self, service, ctx, repo, skill
    ):
        repo.get_resource.return_value = None
        resource_id = uuid.uuid4()

        with pytest.raises(NotFoundError) as refused:
            await service.get_resource(ctx, skill.id, resource_id)

        assert refused.value.details == {"resource_id": str(resource_id)}

    @pytest.mark.anyio
    async def test_editing_a_file_bumps_the_version_and_is_audited(
        self, service, ctx, repo, audit, skill
    ):
        stored = _resource(name="checklist.md")
        repo.get_resource.return_value = stored
        repo.update_resource.return_value = stored

        updated = await service.update_resource(
            ctx, skill.id, stored.id, SkillResourceUpdate(content="# New")
        )

        assert updated is stored
        assert repo.update_resource.await_args.kwargs["update_data"] == {"content": "# New"}
        assert repo.update.await_args.kwargs["update_data"] == {"version": skill.version + 1}
        recorded = audit.await_args.kwargs
        assert recorded["action"] == "skill.resource_updated"
        assert recorded["details"] == {"name": skill.name, "resource": "checklist.md"}

    @pytest.mark.anyio
    async def test_editing_a_file_that_is_not_there_writes_nothing(
        self, service, ctx, repo, audit, skill
    ):
        repo.get_resource.return_value = None

        with pytest.raises(NotFoundError):
            await service.update_resource(
                ctx, skill.id, uuid.uuid4(), SkillResourceUpdate(content="# New")
            )

        repo.update_resource.assert_not_awaited()
        repo.update.assert_not_awaited()
        audit.assert_not_awaited()

    @pytest.mark.anyio
    async def test_removing_a_file_bumps_the_version_and_names_it_in_the_audit(
        self, service, ctx, repo, audit, skill
    ):
        """The name is read before the row goes. Taken afterwards it would be
        gone, and the entry would say which skill lost a file without saying
        which file."""
        stored = _resource(name="checklist.md")
        repo.get_resource.return_value = stored

        await service.remove_resource(ctx, skill.id, stored.id)

        assert repo.delete_resource.await_args.args[1] is stored
        assert repo.update.await_args.kwargs["update_data"] == {"version": skill.version + 1}
        recorded = audit.await_args.kwargs
        assert recorded["action"] == "skill.resource_removed"
        assert recorded["details"] == {"name": skill.name, "resource": "checklist.md"}

    @pytest.mark.anyio
    async def test_removing_a_file_that_is_not_there_deletes_nothing(
        self, service, ctx, repo, audit, skill
    ):
        repo.get_resource.return_value = None

        with pytest.raises(NotFoundError):
            await service.remove_resource(ctx, skill.id, uuid.uuid4())

        repo.delete_resource.assert_not_awaited()
        repo.update.assert_not_awaited()
        audit.assert_not_awaited()
