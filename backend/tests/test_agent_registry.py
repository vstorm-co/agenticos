"""Tests for the agent registry - the lifecycle that makes agents safe to change.

The shape being defended: edit a draft freely, validate once at publish, run only
what was frozen. Three invariants carry most of the weight.

*A refusal looks like an absence.* Reaching an agent you may not see reports the
same "not found" as an agent that does not exist, so ids cannot be probed by
someone who merely belongs to the organization.

*Validation reports everything at once.* A Builder that surfaces one error per
round trip is a Builder people abandon halfway.

*Rollback moves forward.* It publishes a new version copied from an old one, so
the run history keeps saying what was actually live at the time.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.agents.capabilities import REGISTRY, CapabilityToolInfo, load_builtins, register
from app.agents.default_instructions import DEFAULT_INSTRUCTIONS
from app.agents.spec import AgentSpec, CapabilityBindingSpec, SpecialistSpec
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import AgentStatus
from app.db.models.resource_grant import GrantLevel, Visibility
from app.services.agent_registry import AgentRegistryService, slugify

REGISTRY_PATH = "app.services.agent_registry"


@pytest.fixture(autouse=True)
def _builtins_loaded():
    load_builtins()


class _EmailConfig(BaseModel):
    recipient: str


@pytest.fixture
def ungranted_capability():
    """A capability whose scope this deployment does not grant.

    Every built-in capability happens to sit inside `DEFAULT_GRANTED_SCOPES`,
    so the scope check has nothing to refuse without one of these - and a check
    that never fires is a check nobody notices breaking.
    """
    capability_id = "test_email_send"

    @register(
        id=capability_id,
        name="Send email",
        category="test",
        description="Sends mail nobody granted us the right to send",
        config_schema=_EmailConfig,
        scopes=("email:send",),
        tools=(CapabilityToolInfo(id="send_email", description="Sends mail."),),
    )
    def _build(ctx):
        return None

    yield capability_id
    REGISTRY.pop(capability_id)


def _ctx(role: str = OrgRoleName.OWNER, *, org_id=None, user_id=None) -> AuthContext:
    return AuthContext(
        user_id=user_id or uuid.uuid4(),
        organization_id=org_id or uuid.uuid4(),
        role=role,
    )


def _db():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _spec(name: str = "Support", **overrides) -> AgentSpec:
    return AgentSpec(name=name, **overrides)


def _agent(ctx: AuthContext, **overrides):
    """An agent row owned by the caller, so role scope alone reaches it."""
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.organization_id = ctx.organization_id
    agent.owner_user_id = ctx.user_id
    agent.visibility = Visibility.PRIVATE.value
    agent.status = AgentStatus.DRAFT.value
    agent.slug = "support"
    agent.name = "Support"
    agent.description = None
    agent.has_avatar = False
    agent.draft_spec = _spec().model_dump(mode="json")
    agent.current_version_id = None
    agent.created_at = None
    agent.updated_at = None
    for key, value in overrides.items():
        setattr(agent, key, value)
    return agent


def _skill(ctx: AuthContext, *, owner_user_id=None):
    """A private skill row in the caller's organization.

    Owned by the caller unless `owner_user_id` says otherwise, so role scope
    alone reaches it - and giving it away is how a test asks for a skill the
    publisher can see the id of and nothing more.
    """
    return MagicMock(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=owner_user_id or ctx.user_id,
        visibility=Visibility.PRIVATE.value,
    )


def _context_file(ctx: AuthContext, *, owner_user_id=None):
    """A private context-file row in the caller's organization - same shape as `_skill`."""
    return MagicMock(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=owner_user_id or ctx.user_id,
        visibility=Visibility.PRIVATE.value,
    )


def _version(agent_id, *, number: int = 1, spec: AgentSpec | None = None):
    version = MagicMock()
    version.id = uuid.uuid4()
    version.agent_id = agent_id
    version.version = number
    version.spec = (spec or _spec()).model_dump(mode="json")
    version.note = None
    version.published_by_user_id = uuid.uuid4()
    version.created_at = None
    return version


class TestSlugify:
    def test_a_name_becomes_a_mention_safe_handle(self):
        assert slugify("Support Bot 2.0!") == "support-bot-2-0"

    def test_runs_of_punctuation_collapse_to_one_separator(self):
        """`@ops--bot` and `@ops-bot` reading as different agents is a support ticket."""
        assert slugify("Ops  //  Bot") == "ops-bot"

    def test_a_name_with_nothing_usable_still_yields_a_handle(self):
        """An agent whose handle is the empty string could never be mentioned at all."""
        assert slugify("!!! ???") == "agent"

    def test_a_long_name_is_cut_to_a_handle_that_fits(self):
        assert slugify("a" * 200) == "a" * 64

    @pytest.mark.parametrize(
        ("name", "handle"),
        [
            ("Channel", "channel-agent"),
            ("all", "all-agent"),
            ("Here", "here-agent"),
            ("Everyone", "everyone-agent"),
        ],
    )
    def test_a_name_that_addresses_the_room_gets_out_of_the_way(self, name, handle):
        """`@channel`, `@all`, `@here` and `@everyone` address the room on every chat
        platform, so `parse_mention` refuses them before they can reach an agent. An
        agent taking one would have a handle nobody could ever say, and nothing about
        the agent would look wrong - so the handle moves rather than the parser.
        """
        assert slugify(name) == handle

    def test_a_name_that_merely_starts_with_one_keeps_its_handle(self):
        """The set is exact, not a prefix: `@channel-bot` reaches an agent fine."""
        assert slugify("Channel Bot") == "channel-bot"


class TestGet:
    @pytest.mark.anyio
    async def test_a_forbidden_agent_is_indistinguishable_from_a_missing_one(self):
        """Otherwise the error message becomes an oracle for enumerating agent ids.

        Both paths must produce the same message and the same details - a member
        probing ids learns only that they cannot see it, never that it exists.
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        forbidden = _agent(ctx, owner_user_id=uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=forbidden)),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(NotFoundError) as refused,
        ):
            await AgentRegistryService(_db()).get(ctx, forbidden.id)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError) as absent,
        ):
            await AgentRegistryService(_db()).get(ctx, forbidden.id)

        assert refused.value.message == absent.value.message
        assert refused.value.details == absent.value.details == {"agent_id": str(forbidden.id)}

    @pytest.mark.anyio
    async def test_a_grant_reaches_an_agent_the_role_does_not(self):
        """Sharing one agent with a Member has to work without promoting them."""
        ctx = _ctx(OrgRoleName.MEMBER)
        agent = _agent(ctx, owner_user_id=uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=GrantLevel.READ),
            ),
        ):
            found = await AgentRegistryService(_db()).get(ctx, agent.id)

        assert found is agent


class TestList:
    @pytest.mark.anyio
    async def test_a_role_that_sees_everything_never_looks_up_grants(self):
        """A query per listing, on every page, for a set that cannot narrow anything."""
        ctx = _ctx(OrgRoleName.OWNER)

        with (
            patch(
                "app.services.access.resource_grant_repo.list_shared_ids", new=AsyncMock()
            ) as shared_ids,
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await AgentRegistryService(_db()).list_agents(ctx)

        assert shared_ids.await_count == 0
        assert list_visible.call_args.kwargs["see_all"] is True
        assert list_visible.call_args.kwargs["shared_ids"] == []

    @pytest.mark.anyio
    async def test_a_narrower_role_lists_what_was_shared_with_them_too(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        shared = uuid.uuid4()

        with (
            patch(
                "app.services.access.resource_grant_repo.list_shared_ids",
                new=AsyncMock(return_value=[shared]),
            ) as shared_ids,
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await AgentRegistryService(_db()).list_agents(
                ctx, include_archived=True, skip=10, limit=5
            )

        assert shared_ids.call_args.kwargs["minimum_level"] is GrantLevel.READ
        assert list_visible.call_args.kwargs["see_all"] is False
        assert list_visible.call_args.kwargs["shared_ids"] == [shared]
        assert list_visible.call_args.kwargs["include_archived"] is True
        assert (list_visible.call_args.kwargs["skip"], list_visible.call_args.kwargs["limit"]) == (
            10,
            5,
        )

    @pytest.mark.anyio
    async def test_shared_with_me_for_a_wide_role_still_looks_up_grants(self):
        """ "Shared with me" is a question about grants and visibility, not reach.

        A role that sees everything skips the grant lookup for a plain listing;
        skipping it here would degenerate the answer into "the whole
        organization minus mine".
        """
        ctx = _ctx(OrgRoleName.OWNER)
        granted = uuid.uuid4()

        with (
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.list_shared_ids",
                new=AsyncMock(return_value=[granted]),
            ) as shared_ids,
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await AgentRegistryService(_db()).list_agents(ctx, shared_with_me=True)

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
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([], 0)),
            ) as list_visible,
        ):
            await AgentRegistryService(_db()).list_agents(ctx, shared_with_me=True)

        assert shared_ids.await_count == 1
        assert list_visible.call_args.kwargs["see_all"] is False
        assert list_visible.call_args.kwargs["shared_with_me"] is True
        assert list_visible.call_args.kwargs["shared_ids"] == [granted]

    @pytest.mark.anyio
    async def test_a_listed_agent_says_who_reaches_it_and_where_it_answers(self):
        """The gallery card reads 'shared with 3, on Slack' straight off the row.

        Both numbers come from one grouped query per page; an agent nobody
        shared and nobody exposed reads 0 and [], not a missing key.
        """
        ctx = _ctx(OrgRoleName.OWNER)
        listed = _agent(ctx)
        lonely = _agent(ctx)

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([listed, lonely], 2)),
            ),
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.count_for_resources",
                new=AsyncMock(return_value={listed.id: 3}),
            ) as counts,
            patch(
                f"{REGISTRY_PATH}.agent_exposure_repo.active_surfaces_for_agents",
                new=AsyncMock(return_value={listed.id: ["slack", "telegram"]}),
            ) as surfaces,
        ):
            rows, total = await AgentRegistryService(_db()).list_agents(ctx)

        assert total == 2
        assert (rows[0].shared_user_count, rows[0].channels) == (3, ["slack", "telegram"])
        assert (rows[1].shared_user_count, rows[1].channels) == (0, [])
        assert counts.call_args.kwargs["resource_ids"] == [listed.id, lonely.id]
        assert surfaces.call_args.kwargs["agent_ids"] == [listed.id, lonely.id]

    @pytest.mark.anyio
    async def test_a_published_agents_cap_rides_the_listing_and_a_drafts_does_not(self):
        """The headroom card needs the enforced cap - the published version's,
        not the draft's promise of one."""
        ctx = _ctx(OrgRoleName.OWNER)
        version_id = uuid.uuid4()
        published = _agent(ctx, current_version_id=version_id)
        draft = _agent(ctx)

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([published, draft], 2)),
            ),
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.count_for_resources",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_exposure_repo.active_surfaces_for_agents",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_budget_caps",
                new=AsyncMock(return_value={version_id: 60.0}),
            ) as caps,
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_compaction_windows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_model_profiles",
                new=AsyncMock(return_value={}),
            ),
        ):
            rows, _total = await AgentRegistryService(_db()).list_agents(ctx)

        assert caps.call_args.kwargs["version_ids"] == [version_id]
        assert rows[0].budget_monthly_usd == 60.0
        assert rows[1].budget_monthly_usd is None

    @pytest.mark.anyio
    async def test_the_window_a_listed_agents_model_accepts_rides_along(self):
        """What a chat divides its context gauge by.

        The share is resolved on the surface rather than stored with the reading,
        because the window belongs to the model answering *next* - and the chat
        lets somebody switch that between turns.
        """
        ctx = _ctx(OrgRoleName.OWNER)
        version_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        published = _agent(ctx, current_version_id=version_id)

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([published], 1)),
            ),
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.count_for_resources",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_exposure_repo.active_surfaces_for_agents",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_budget_caps",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_compaction_windows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_model_profiles",
                new=AsyncMock(return_value={version_id: profile_id}),
            ),
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profiles_by_ids",
                new=AsyncMock(
                    return_value={
                        profile_id: MagicMock(
                            context_length=128_000, provider="openai", model="gpt-4o"
                        )
                    }
                ),
            ),
        ):
            rows, _total = await AgentRegistryService(_db()).list_agents(ctx)

        assert rows[0].context_window_tokens == 128_000

    @pytest.mark.anyio
    async def test_a_profile_with_no_recorded_window_falls_back_to_the_registry(self):
        """The pricing snapshot is the fallback for a profile older than the
        column, and it is right more often than not - a self-hosted endpoint is
        where it is not."""
        ctx = _ctx(OrgRoleName.OWNER)
        version_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        published = _agent(ctx, current_version_id=version_id)

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([published], 1)),
            ),
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.count_for_resources",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_exposure_repo.active_surfaces_for_agents",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_budget_caps",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_compaction_windows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_model_profiles",
                new=AsyncMock(return_value={version_id: profile_id}),
            ),
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profiles_by_ids",
                new=AsyncMock(
                    return_value={
                        profile_id: MagicMock(
                            context_length=None, provider="openai", model="gpt-4o"
                        )
                    }
                ),
            ),
        ):
            rows, _total = await AgentRegistryService(_db()).list_agents(ctx)

        assert rows[0].context_window_tokens == 128_000

    @pytest.mark.anyio
    async def test_a_model_nothing_can_size_reports_no_window_rather_than_a_guess(self):
        """A share against an assumed window is a guess presented as a
        measurement, and it errs in the direction that lets a run reach the
        ceiling. The surface draws nothing instead."""
        ctx = _ctx(OrgRoleName.OWNER)
        version_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        published = _agent(ctx, current_version_id=version_id)

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([published], 1)),
            ),
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.count_for_resources",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_exposure_repo.active_surfaces_for_agents",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_budget_caps",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_compaction_windows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_model_profiles",
                new=AsyncMock(return_value={version_id: profile_id}),
            ),
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profiles_by_ids",
                new=AsyncMock(
                    return_value={
                        profile_id: MagicMock(
                            context_length=None, provider="ollama", model="llama3.3"
                        )
                    }
                ),
            ),
        ):
            rows, _total = await AgentRegistryService(_db()).list_agents(ctx)

        assert rows[0].context_window_tokens is None

    @pytest.mark.anyio
    async def test_an_author_who_overrode_the_window_is_the_one_the_gauge_believes(self):
        """One ceiling, one number.

        `compaction`'s `context_window` is what the *trigger* already measures
        against - an author sets it because the resolved figure is wrong for them,
        or to allow for the instructions and tool schemas the estimator does not
        count. A gauge dividing by the profile's number instead would describe a
        different ceiling than the one the agent acts on, which is how somebody
        watches 0.4% while their history is being summarised.
        """
        ctx = _ctx(OrgRoleName.OWNER)
        version_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        published = _agent(ctx, current_version_id=version_id)

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([published], 1)),
            ),
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.count_for_resources",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_exposure_repo.active_surfaces_for_agents",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_budget_caps",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_compaction_windows",
                new=AsyncMock(return_value={version_id: 5_000}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_model_profiles",
                new=AsyncMock(return_value={version_id: profile_id}),
            ),
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profiles_by_ids",
                new=AsyncMock(
                    return_value={
                        profile_id: MagicMock(
                            context_length=1_050_000, provider="openrouter", model="openai/gpt-5.5"
                        )
                    }
                ),
            ),
        ):
            rows, _total = await AgentRegistryService(_db()).list_agents(ctx)

        assert rows[0].context_window_tokens == 5_000

    @pytest.mark.anyio
    async def test_a_deleted_profile_leaves_the_window_unknown(self):
        """A published spec names a profile by id, and the row can be removed
        afterwards. The listing is about names and avatars; it says nothing about
        the window rather than failing over one."""
        ctx = _ctx(OrgRoleName.OWNER)
        version_id = uuid.uuid4()
        published = _agent(ctx, current_version_id=version_id)

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([published], 1)),
            ),
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.count_for_resources",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_exposure_repo.active_surfaces_for_agents",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_budget_caps",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_compaction_windows",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.published_model_profiles",
                new=AsyncMock(return_value={version_id: uuid.uuid4()}),
            ),
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profiles_by_ids",
                new=AsyncMock(return_value={}),
            ),
        ):
            rows, _total = await AgentRegistryService(_db()).list_agents(ctx)

        assert rows[0].context_window_tokens is None

    @pytest.mark.anyio
    async def test_the_listing_returns_the_page_and_the_total(self):
        """The total is the page count, not the page size - pagination depends on it."""
        ctx = _ctx(OrgRoleName.OWNER)
        agent = _agent(ctx)

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_visible",
                new=AsyncMock(return_value=([agent], 37)),
            ),
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.count_for_resources",
                new=AsyncMock(return_value={}),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_exposure_repo.active_surfaces_for_agents",
                new=AsyncMock(return_value={}),
            ),
        ):
            agents, total = await AgentRegistryService(_db()).list_agents(ctx)

        assert ([row.id for row in agents], total) == ([agent.id], 37)


class TestCreate:
    @pytest.mark.anyio
    async def test_a_new_agent_starts_as_a_draft_holding_the_submitted_spec(self):
        ctx = _ctx()
        spec = _spec("Support Bot", description="Answers customers")

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=_agent(ctx))
            ) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await AgentRegistryService(_db()).create(ctx, spec)

        written = create.call_args.kwargs
        assert written["slug"] == "support-bot"
        assert written["name"] == "Support Bot"
        assert written["description"] == "Answers customers"
        # The submitted spec, with one substitution: a new agent opens with a
        # starting prompt rather than an empty box. `TestWhatANewAgentOpensWith`
        # below is where that behaviour is pinned.
        assert written["draft_spec"] == {
            **spec.model_dump(mode="json"),
            "instructions": DEFAULT_INSTRUCTIONS,
        }
        assert written["owner_user_id"] == ctx.user_id
        assert audit.call_args.kwargs["action"] == "agent.created"

    @pytest.mark.anyio
    async def test_a_name_that_derives_a_taken_handle_is_refused(self):
        """The handle is the @mention; a second `@support` routes messages at random.

        Disambiguating silently (`support-2`) would be worse: nobody would know
        which of the two they had just talked to.
        """
        ctx = _ctx()

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.get_by_slug",
                new=AsyncMock(return_value=_agent(ctx)),
            ),
            patch(f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock()) as create,
            pytest.raises(AlreadyExistsError) as refused,
        ):
            await AgentRegistryService(_db()).create(ctx, _spec("Support!"))

        assert refused.value.details == {"slug": "support"}
        # The message has to tell them what to change. They typed a *name*; the
        # thing that collided is the handle derived from it, and a refusal that
        # only states the collision leaves them staring at an input that looks
        # fine.
        assert "@support" in refused.value.message
        assert "different handle" in refused.value.message
        assert create.await_count == 0


class TestPromoteSpecialist:
    """The one exit a specialist has that keeps its provenance visible.

    Promoting turns a specialist - inline or one a model invented mid-run - into an
    ordinary draft agent owned by whoever promoted it, and stops there: no publish,
    no pin, no touching what it came from. Each of those is the author's next
    decision, with the normal validation in front of it.
    """

    @pytest.mark.anyio
    async def test_a_promoted_specialist_becomes_a_draft_the_promoter_owns(self):
        ctx = _ctx()
        specialist = SpecialistSpec(
            name="invoice-parser",
            description="Pulls line items out of an invoice",
            instructions="You read invoices and return their line items as JSON.",
            model_profile_id=uuid4(),
        )

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=_agent(ctx))
            ) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await AgentRegistryService(_db()).promote_specialist(
                ctx, specialist, fallback_model_profile_id=None
            )

        written = create.call_args.kwargs
        assert written["slug"] == "invoice-parser"
        assert written["name"] == "invoice-parser"
        # The specialist's own instructions and model reach the draft verbatim - a
        # draft that publishes and runs the same is the whole point.
        assert written["draft_spec"]["instructions"] == specialist.instructions
        assert written["draft_spec"]["model_profile_id"] == str(specialist.model_profile_id)
        # Owned by the promoter, because `create` is - a specialist created inside
        # someone else's run does not become their agent without this.
        assert written["owner_user_id"] == ctx.user_id
        assert {call.kwargs["action"] for call in audit.await_args_list} == {
            "agent.created",
            "agent.promoted_from_specialist",
        }

    @pytest.mark.anyio
    async def test_a_specialist_on_the_parents_model_takes_the_parents_profile(self):
        """`model_profile_id=None` on a specialist means "the parent's model", and a
        standalone agent has no parent - so the fallback is resolved into the draft,
        which is what lets it publish without first being given a model by hand."""
        ctx = _ctx()
        parent_profile = uuid4()
        specialist = SpecialistSpec(
            name="summariser",
            description="Summarises in three bullets",
            instructions="Summarise the input in exactly three bullets.",
            model_profile_id=None,
        )

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=_agent(ctx))
            ) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
        ):
            await AgentRegistryService(_db()).promote_specialist(
                ctx, specialist, fallback_model_profile_id=parent_profile
            )

        assert create.call_args.kwargs["draft_spec"]["model_profile_id"] == str(parent_profile)

    @pytest.mark.anyio
    async def test_promoting_does_not_pin_the_new_agent_as_a_delegate(self):
        """`to_agent_spec` drops what a specialist cannot carry, and the draft is a
        plain agent: no delegates pinned to it, no delegates of its own. Promoting is
        a copy, not a wiring-up - pinning it back to a parent is a separate decision.
        """
        ctx = _ctx()
        specialist = SpecialistSpec(
            name="researcher",
            description="Finds and cites sources",
            instructions="Research the topic and cite your sources.",
            model_profile_id=uuid4(),
            capabilities=[CapabilityBindingSpec(id="web_search")],
        )

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=_agent(ctx))
            ) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
        ):
            await AgentRegistryService(_db()).promote_specialist(
                ctx, specialist, fallback_model_profile_id=None
            )

        draft = create.call_args.kwargs["draft_spec"]
        assert draft["subagents"] == []
        # The specialist's own capabilities do come across - a researcher that
        # cannot search is not the researcher that ran.
        assert [binding["id"] for binding in draft["capabilities"]] == ["web_search"]


class TestSaveDraft:
    @pytest.mark.anyio
    async def test_a_spec_that_could_never_publish_is_still_saved(self, ungranted_capability):
        """Half-finished configuration must survive a page reload.

        If saving validated, the Builder would become a form you cannot leave:
        pick a collection you have not created yet and your work is refused.
        Validation is publish's job, and only publish's.
        """
        ctx = _ctx()
        agent = _agent(ctx)
        broken = _spec(
            "Half Done",
            capabilities=[
                {"id": "no_such_capability"},
                {"id": ungranted_capability, "config": {}},
            ],
            collection_ids=[uuid.uuid4()],
            model_profile_id=uuid.uuid4(),
        )

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
        ):
            await AgentRegistryService(_db()).save_draft(ctx, agent.id, broken)

        assert update.call_args.kwargs["update_data"] == {
            "draft_spec": broken.model_dump(mode="json"),
            "name": "Half Done",
            "description": None,
        }


class TestImportSpec:
    """The round trip the export feature exists for: a spec committed to a
    client's own repository, edited there, and posted back (#873)."""

    @pytest.mark.anyio
    async def test_a_valid_document_replaces_the_draft(self):
        ctx = _ctx()
        agent = _agent(ctx)
        spec = _spec("Support", description="Answers billing questions")

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
        ):
            await AgentRegistryService(_db()).import_spec(ctx, agent.id, spec.to_yaml())

        assert update.call_args.kwargs["update_data"] == {
            "draft_spec": spec.model_dump(mode="json"),
            "name": "Support",
            "description": "Answers billing questions",
        }

    @pytest.mark.anyio
    async def test_a_document_that_does_not_parse_never_reaches_the_row(self):
        """The refusal is a `BadRequestError`, not the `ValidationError` nothing
        in `app/api/exception_handlers.py` maps - and it is raised before the
        agent is read, so a spec nobody could have saved opens no transaction."""
        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock()) as fetched,
            patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as update,
            pytest.raises(BadRequestError) as refused,
        ):
            await AgentRegistryService(_db()).import_spec(
                _ctx(), uuid.uuid4(), "name: x\ninstrucitons: typo\n"
            )

        assert refused.value.details["fields"][0]["field"] == "yaml.instrucitons"
        fetched.assert_not_called()
        update.assert_not_called()


class TestValidateSpec:
    @pytest.mark.anyio
    async def test_a_broken_spec_reports_every_problem_at_once(self, ungranted_capability):
        """One error per round trip is the difference between a Builder used and avoided.

        This spec is wrong in five independent ways; all five have to come back
        together, because the person fixing them is looking at one form.
        """
        ctx = _ctx()
        spec = _spec(
            capabilities=[
                {"id": "no_such_capability"},
                {"id": ungranted_capability, "config": {}},
            ],
            collection_ids=[uuid.uuid4()],
            model_profile_id=uuid.uuid4(),
        )

        with (
            patch(f"{REGISTRY_PATH}.credential_repo.get_profile", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=None)
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await AgentRegistryService(_db()).validate_spec(ctx, spec)

        problems = refused.value.details["problems"]
        assert len(problems) == 5
        assert "Unknown capability: no_such_capability" in problems
        assert any("needs scopes not granted here: email:send" in problem for problem in problems)
        assert any("Invalid configuration" in problem for problem in problems)
        assert "The selected model profile no longer exists" in problems
        assert any(problem.startswith("Collection not found:") for problem in problems)

    @pytest.mark.anyio
    async def test_a_refused_capability_config_names_the_input_as_well_as_the_capability(self):
        """This is the path a Builder submission takes, and it discarded the field.

        `validate_config` names each setting that broke a rule, and the
        aggregator kept only `exc.message` - so `default_top_k: 999` reached the
        form as one sentence about the capability and marked no box. Saving a
        draft does not validate a config schema at all, which leaves publish
        validation as the only place a mistyped setting is ever refused (found
        reviewing #892).
        """
        spec = _spec(
            capabilities=[{"id": "knowledge", "config": {"default_top_k": 999}}],
            model_profile_id=None,
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

        assert refused.value.details["fields"] == [
            {
                "field": "capabilities.knowledge.config.default_top_k",
                "message": "Input should be less than or equal to 50",
            }
        ]
        # And still as a line, because a form that does not render this field
        # has to say something.
        assert any(
            "Invalid configuration" in problem for problem in refused.value.details["problems"]
        )

    @pytest.mark.anyio
    async def test_a_specialists_config_is_marked_on_the_specialists_own_form(self):
        """One form per specialist, configuring the same capabilities as the
        parent - so an unscoped path would mark the parent's `knowledge` card
        for a mistake in a copy of it that lives inside a delegate."""
        spec = _spec(
            capabilities=[
                {
                    "id": "subagents",
                    "config": {
                        "inline": [
                            {
                                "name": "researcher",
                                "description": "Looks things up in the handbook.",
                                "instructions": "Research things.",
                                "capabilities": [
                                    {"id": "knowledge", "config": {"default_top_k": 999}}
                                ],
                            }
                        ]
                    },
                }
            ],
            model_profile_id=None,
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

        assert [problem["field"] for problem in refused.value.details["fields"]] == [
            "specialists.researcher.capabilities.knowledge.config.default_top_k"
        ]

    @pytest.mark.anyio
    async def test_a_spec_whose_problems_name_no_field_carries_no_fields_key(self):
        """An empty list would be a claim that nothing can be marked, which a
        reader has to tell apart from a refusal that never names one."""
        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(_ctx(), _spec(model_profile_id=None))

        assert refused.value.details == {
            "problems": ["No model selected - pick one before publishing"]
        }

    @pytest.mark.anyio
    async def test_an_agent_with_no_model_cannot_publish(self):
        """Nothing downstream can invent a model, so this has to be caught here.

        There is no organization default to fall back on since 0054: a model an
        agent did not choose is one somebody else's change can swap underneath
        it, so the absence is refused outright.
        """
        ctx = _ctx()

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(ctx, _spec())

        assert refused.value.details["problems"] == [
            "No model selected - pick one before publishing"
        ]

    @pytest.mark.anyio
    async def test_a_collection_belonging_to_another_organization_is_not_found(self):
        """The id exists, so a bare existence check would happily attach it."""
        ctx = _ctx()
        collection_id = uuid.uuid4()
        foreign = MagicMock(organization_id=uuid.uuid4())

        with (
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                f"{REGISTRY_PATH}.knowledge_base_repo.get_by_id",
                new=AsyncMock(return_value=foreign),
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await AgentRegistryService(_db()).validate_spec(
                ctx, _spec(collection_ids=[collection_id], model_profile_id=uuid.uuid4())
            )

        assert refused.value.details["problems"] == [f"Collection not found: {collection_id}"]

    @pytest.mark.anyio
    async def test_a_private_collection_the_publisher_cannot_reach_is_not_found(self):
        """An agent searches its bound collections for everyone who can run it,
        so binding one shares what is in it. The publisher has to be able to
        reach it themselves - and is told the same thing as for an id that does
        not exist, because a different refusal would map the organization's
        private collections one guess at a time."""
        ctx = _ctx(OrgRoleName.MEMBER)
        collection_id = uuid.uuid4()
        private = MagicMock(
            organization_id=ctx.organization_id,
            owner_user_id=uuid.uuid4(),
            visibility=Visibility.PRIVATE.value,
        )

        with (
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                f"{REGISTRY_PATH}.knowledge_base_repo.get_by_id",
                new=AsyncMock(return_value=private),
            ),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await AgentRegistryService(_db()).validate_spec(
                ctx, _spec(collection_ids=[collection_id], model_profile_id=uuid.uuid4())
            )

        assert refused.value.details["problems"] == [f"Collection not found: {collection_id}"]

    @pytest.mark.anyio
    async def test_an_mcp_server_that_is_not_an_organization_connection_is_refused(self):
        """`mcp_server_ids` used to be a field that did nothing at all.

        Refusing here is what makes it a promise: an agent published with a
        server bound either gets that server at run time or never publishes.
        The reason is spelled out because the likely mistake - picking a
        personal connection - leaves the row sitting in Settings where the
        person can see it, and a bare "not found" would send them hunting.
        """
        ctx = _ctx()
        connection_id = uuid.uuid4()

        with (
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                f"{REGISTRY_PATH}.mcp_connection_repo.get_org_scoped_by_id",
                new=AsyncMock(return_value=None),
            ) as lookup,
            pytest.raises(BadRequestError) as refused,
        ):
            await AgentRegistryService(_db()).validate_spec(
                ctx, _spec(mcp_server_ids=[connection_id], model_profile_id=uuid.uuid4())
            )

        problem = refused.value.details["problems"][0]
        assert str(connection_id) in problem
        assert "personal" in problem
        assert lookup.await_args.kwargs == {
            "connection_id": connection_id,
            "organization_id": ctx.organization_id,
        }

    @pytest.mark.anyio
    async def test_a_spec_whose_references_all_resolve_raises_nothing(self):
        ctx = _ctx()
        collection_id = uuid.uuid4()
        skill = _skill(ctx)

        with (
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                f"{REGISTRY_PATH}.knowledge_base_repo.get_by_id",
                new=AsyncMock(return_value=MagicMock(organization_id=ctx.organization_id)),
            ),
            patch(
                f"{REGISTRY_PATH}.mcp_connection_repo.get_org_scoped_by_id",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                f"{REGISTRY_PATH}.skill_repo.get_many",
                new=AsyncMock(return_value={skill.id: skill}),
            ),
        ):
            await AgentRegistryService(_db()).validate_spec(
                ctx,
                _spec(
                    capabilities=[{"id": "clock"}, {"id": "knowledge"}],
                    collection_ids=[collection_id],
                    skill_ids=[skill.id],
                    model_profile_id=uuid.uuid4(),
                    mcp_server_ids=[uuid.uuid4()],
                ),
            )


class TestSkillValidation:
    """Binding a skill lends it, so publish checks the publisher can read it.

    A bound skill's body and files are handed to every run of the agent, and
    skills are bound by UUID - from the API, or by hand-editing a draft - not only
    picked from a list the Builder filtered. Without this check a member whose role
    reaches only shared skills could bind a colleague's private one and read it
    through the agent.
    """

    @staticmethod
    async def _problems(ctx: AuthContext, spec: AgentSpec, **repos) -> list[str]:
        """The problems publishing this spec reports, with the model resolving."""
        with (
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(f"{REGISTRY_PATH}.skill_repo.get_many", new=AsyncMock(**repos)),
            pytest.raises(BadRequestError) as refused,
        ):
            await AgentRegistryService(_db()).validate_spec(ctx, spec)

        assert refused.value.details is not None
        problems: list[str] = refused.value.details["problems"]
        return problems

    @pytest.mark.anyio
    async def test_a_skill_this_organization_does_not_have_is_not_found(self):
        """Including another tenant's: the repository filters by organization, so
        an id from elsewhere arrives here as an absence."""
        skill_id = uuid.uuid4()

        problems = await self._problems(
            _ctx(),
            _spec(skill_ids=[skill_id], model_profile_id=uuid.uuid4()),
            return_value={},
        )

        assert problems == [f"Skill not found: {skill_id}"]

    @pytest.mark.anyio
    async def test_a_private_skill_the_publisher_cannot_reach_is_not_found(self):
        """The leak this check closes, reported as an absence.

        A member's role reaches shared skills only, so a colleague's private one
        is refused - and told the same thing as an id that does not exist, because
        a refusal that read differently would map the organization's private
        skills one guess at a time.
        """
        ctx = _ctx(OrgRoleName.MEMBER)
        private = _skill(ctx, owner_user_id=uuid.uuid4())

        with patch(
            "app.services.access.resource_grant_repo.get_level", new=AsyncMock(return_value=None)
        ):
            problems = await self._problems(
                ctx,
                _spec(skill_ids=[private.id], model_profile_id=uuid.uuid4()),
                return_value={private.id: private},
            )

        assert problems == [f"Skill not found: {private.id}"]

    @pytest.mark.anyio
    async def test_a_grant_lets_a_member_bind_a_skill_they_do_not_own(self):
        """A grant widens what a role allows, here as everywhere else."""
        ctx = _ctx(OrgRoleName.MEMBER)
        shared = _skill(ctx, owner_user_id=uuid.uuid4())

        with (
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                f"{REGISTRY_PATH}.skill_repo.get_many",
                new=AsyncMock(return_value={shared.id: shared}),
            ),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=GrantLevel.READ),
            ),
        ):
            await AgentRegistryService(_db()).validate_spec(
                ctx, _spec(skill_ids=[shared.id], model_profile_id=uuid.uuid4())
            )


class TestContextValidation:
    """Binding a context file lends it, so publish checks the publisher can read it.

    A bound file's body reaches every run - injected or read on demand - and files
    are bound by UUID, so without this check a member could bind a colleague's
    private file and read it through the agent. The same rule as a skill.
    """

    @staticmethod
    async def _problems(ctx: AuthContext, spec: AgentSpec, **repos) -> list[str]:
        with (
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(f"{REGISTRY_PATH}.context_repo.get_many", new=AsyncMock(**repos)),
            pytest.raises(BadRequestError) as refused,
        ):
            await AgentRegistryService(_db()).validate_spec(ctx, spec)
        assert refused.value.details is not None
        problems: list[str] = refused.value.details["problems"]
        return problems

    @pytest.mark.anyio
    async def test_a_file_this_organization_does_not_have_is_not_found(self):
        context_id = uuid.uuid4()
        problems = await self._problems(
            _ctx(),
            _spec(context_ids=[context_id], model_profile_id=uuid.uuid4()),
            return_value={},
        )
        assert problems == [f"Context file not found: {context_id}"]

    @pytest.mark.anyio
    async def test_a_private_file_the_publisher_cannot_reach_is_not_found(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        private = _context_file(ctx, owner_user_id=uuid.uuid4())
        with patch(
            "app.services.access.resource_grant_repo.get_level", new=AsyncMock(return_value=None)
        ):
            problems = await self._problems(
                ctx,
                _spec(context_ids=[private.id], model_profile_id=uuid.uuid4()),
                return_value={private.id: private},
            )
        assert problems == [f"Context file not found: {private.id}"]

    @pytest.mark.anyio
    async def test_a_grant_lets_a_member_bind_a_file_they_do_not_own(self):
        ctx = _ctx(OrgRoleName.MEMBER)
        shared = _context_file(ctx, owner_user_id=uuid.uuid4())
        with (
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                f"{REGISTRY_PATH}.context_repo.get_many",
                new=AsyncMock(return_value={shared.id: shared}),
            ),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=GrantLevel.READ),
            ),
        ):
            await AgentRegistryService(_db()).validate_spec(
                ctx, _spec(context_ids=[shared.id], model_profile_id=uuid.uuid4())
            )


class TestToolApprovalValidation:
    @pytest.mark.anyio
    async def test_an_approval_for_a_tool_the_capability_does_not_have_is_refused(
        self, ungranted_capability
    ):
        """The dangerous kind of typo.

        A `tool_approval` key matching nothing is not an error at run time, it
        is silence: the tool the author meant to gate runs unapproved and
        nobody is told. So it fails at publish, while somebody is looking.
        """
        db = _db()
        # A default model exists, so the typo is the only problem reported.
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=object()))
        )
        service = AgentRegistryService(db)
        spec = _spec(
            capabilities=[{"id": ungranted_capability, "tool_approval": {"send_emial": "required"}}]
        )

        with pytest.raises(BadRequestError) as refused:
            await service.validate_spec(_ctx(), spec)

        assert refused.value.details is not None
        assert any("send_emial" in problem for problem in refused.value.details["problems"])


class TestToolOverrideValidation:
    """What a rename may not be, checked while somebody is looking at the form.

    All three of these are silent at run time. An override on a tool that does
    not exist changes nothing and says nothing; a name a model cannot emit is a
    tool it can never call; two tools sharing a name is a library error raised
    mid-conversation.
    """

    @staticmethod
    def _service():
        db = _db()
        # A default model exists, so the override is the only problem reported.
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=object()))
        )
        return AgentRegistryService(db)

    async def _refuse(self, spec: AgentSpec) -> list[str]:
        with pytest.raises(BadRequestError) as refused:
            await self._service().validate_spec(_ctx(), spec)
        assert refused.value.details is not None
        return refused.value.details["problems"]

    @pytest.mark.anyio
    async def test_an_override_for_a_tool_the_capability_does_not_have_is_refused(
        self, ungranted_capability
    ):
        problems = await self._refuse(
            _spec(
                capabilities=[
                    {
                        "id": ungranted_capability,
                        "tool_overrides": {"send_emial": {"name": "post_letter"}},
                    }
                ]
            )
        )

        assert any("send_emial" in problem for problem in problems)

    @pytest.mark.anyio
    async def test_a_name_the_model_could_not_call_is_refused(self, ungranted_capability):
        """The model has to emit this string; `send email` is not a tool."""
        problems = await self._refuse(
            _spec(
                capabilities=[
                    {
                        "id": ungranted_capability,
                        "tool_overrides": {"send_email": {"name": "send email"}},
                    }
                ]
            )
        )

        assert any("cannot call" in problem for problem in problems)

    @pytest.mark.anyio
    async def test_a_rename_onto_a_sibling_tools_name_is_refused(self):
        """Two tools with one name is a `UserError` from inside the toolset.

        Refusing here is the difference between a form that says what is wrong
        and a conversation that dies halfway through.
        """
        problems = await self._refuse(
            _spec(
                capabilities=[
                    {
                        "id": "skills",
                        "tool_overrides": {"load_skill": {"name": "list_skills"}},
                    }
                ]
            )
        )

        assert any("two tools called list_skills" in problem for problem in problems)

    @pytest.mark.anyio
    async def test_a_rename_a_model_can_call_is_accepted(self):
        """Dashes and digits are as callable as underscores; refusing them is noise."""
        # The model profile resolves through _service()'s db.execute mock.
        spec = _spec(
            model_profile_id=uuid.uuid4(),
            capabilities=[
                {
                    "id": "skills",
                    "tool_overrides": {
                        "load_skill": {
                            "name": "load-playbook_2",
                            "description": "Load one of the team's playbooks.",
                        }
                    },
                }
            ],
        )

        await self._service().validate_spec(_ctx(), spec)


class TestPublish:
    @pytest.mark.anyio
    async def test_publishing_freezes_the_draft_as_the_version_that_runs(self):
        """The pointer and the frozen copy have to move together, or a run reads a draft."""
        ctx = _ctx()
        spec = _spec("Support", instructions="Be brief", model_profile_id=uuid.uuid4())
        agent = _agent(ctx, draft_spec=spec.model_dump(mode="json"))
        version = _version(agent.id, number=3, spec=spec)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(f"{REGISTRY_PATH}.agent_repo.next_version_number", new=AsyncMock(return_value=3)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create_version",
                new=AsyncMock(return_value=version),
            ) as create_version,
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
            patch(f"{REGISTRY_PATH}.agent_environment_repo") as environments,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            environments.get_default_for_agent = AsyncMock(return_value=None)
            environments.create = AsyncMock()
            published = await AgentRegistryService(_db()).publish(ctx, agent.id, note="first cut")

        frozen = create_version.call_args.kwargs
        assert frozen["version"] == 3
        assert frozen["spec"] == spec.model_dump(mode="json")
        assert frozen["note"] == "first cut"
        assert update.call_args.kwargs["update_data"] == {
            "current_version_id": version.id,
            "status": AgentStatus.PUBLISHED.value,
        }
        assert audit.call_args.kwargs["details"] == {"version": 3, "note": "first cut"}
        assert published is version
        # A first publish mints the default environment, pinned to the version
        # that just went live - so every published agent has one.
        created = environments.create.call_args.kwargs
        assert (created["name"], created["is_default"], created["version_id"]) == (
            "production",
            True,
            version.id,
        )

    @pytest.mark.anyio
    async def test_a_draft_that_does_not_validate_freezes_nothing(self):
        """A refused publish must leave the previous version live and untouched."""
        ctx = _ctx()
        # The default draft names no model, which is the refusal.
        agent = _agent(ctx)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.create_version", new=AsyncMock()) as create_version,
            patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as update,
            pytest.raises(BadRequestError),
        ):
            await AgentRegistryService(_db()).publish(ctx, agent.id)

        assert create_version.await_count == 0
        assert update.await_count == 0


class TestRollback:
    @pytest.mark.anyio
    async def test_rolling_back_publishes_a_new_version_instead_of_moving_the_pointer(self):
        """History stays linear: the timeline shows the rollback happened.

        Repointing at v1 would make every run record ambiguous - "v1" would name
        two different stretches of time with a bad release in between.
        """
        ctx = _ctx()
        agent = _agent(ctx)
        old_spec = _spec(
            "Support", instructions="The version that worked", model_profile_id=uuid.uuid4()
        )
        source = _version(agent.id, number=1, spec=old_spec)
        fresh = _version(agent.id, number=5, spec=old_spec)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=source)),
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(f"{REGISTRY_PATH}.agent_repo.next_version_number", new=AsyncMock(return_value=5)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create_version", new=AsyncMock(return_value=fresh)
            ) as create_version,
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
            patch(f"{REGISTRY_PATH}.agent_environment_repo") as environments,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            default = MagicMock()
            environments.get_default_for_agent = AsyncMock(return_value=default)
            environments.update = AsyncMock()
            restored = await AgentRegistryService(_db()).rollback(
                ctx, agent.id, to_version_id=source.id
            )

        written = create_version.call_args.kwargs
        assert written["version"] == 5
        assert written["spec"] == source.spec
        assert written["note"] == "Rollback to v1"
        assert update.call_args.kwargs["update_data"] == {
            "current_version_id": fresh.id,
            "status": AgentStatus.PUBLISHED.value,
            "draft_spec": source.spec,
        }
        assert audit.call_args.kwargs["details"] == {"from_version": 1, "new_version": 5}
        assert restored is fresh
        # A rollback moves the default environment with the pointer - the new
        # version is what the default audience now gets.
        assert environments.update.call_args.kwargs["update_data"] == {"version_id": fresh.id}

    @pytest.mark.anyio
    async def test_a_version_belonging_to_another_agent_cannot_be_rolled_into_this_one(self):
        """Version ids are org-scoped, so without this an agent could adopt a sibling's spec."""
        ctx = _ctx()
        agent = _agent(ctx)
        stranger = _version(uuid.uuid4(), number=2)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=stranger)),
            pytest.raises(NotFoundError) as refused,
        ):
            await AgentRegistryService(_db()).rollback(ctx, agent.id, to_version_id=stranger.id)

        assert refused.value.details == {"version_id": str(stranger.id)}

    @pytest.mark.anyio
    async def test_a_version_that_does_not_exist_is_not_found(self):
        ctx = _ctx()
        agent = _agent(ctx)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError),
        ):
            await AgentRegistryService(_db()).rollback(ctx, agent.id, to_version_id=uuid.uuid4())

    @pytest.mark.anyio
    async def test_an_old_version_whose_references_are_gone_cannot_be_restored(self):
        """The collection it searched was deleted last week; republishing it would break at 3am."""
        ctx = _ctx()
        agent = _agent(ctx)
        source = _version(agent.id, spec=_spec(collection_ids=[uuid.uuid4()]))

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=source)),
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            patch(
                f"{REGISTRY_PATH}.knowledge_base_repo.get_by_id", new=AsyncMock(return_value=None)
            ),
            patch(f"{REGISTRY_PATH}.agent_repo.create_version", new=AsyncMock()) as create_version,
            pytest.raises(BadRequestError),
        ):
            await AgentRegistryService(_db()).rollback(ctx, agent.id, to_version_id=source.id)

        assert create_version.await_count == 0


class TestArchiveAndDelete:
    @pytest.mark.anyio
    async def test_archiving_hides_the_agent_and_keeps_everything_else(self):
        """What people mean by "delete" is this: stop it, keep the trail."""
        ctx = _ctx()
        agent = _agent(ctx, status=AgentStatus.PUBLISHED.value)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
            patch(f"{REGISTRY_PATH}.agent_repo.delete", new=AsyncMock()) as delete,
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.delete_for_resource", new=AsyncMock()
            ) as drop_grants,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            archived = await AgentRegistryService(_db()).archive(ctx, agent.id)

        assert update.call_args.kwargs["update_data"] == {"status": AgentStatus.ARCHIVED.value}
        assert delete.await_count == 0
        assert drop_grants.await_count == 0
        assert audit.call_args.kwargs["action"] == "agent.archived"
        assert archived is agent

    @pytest.mark.anyio
    async def test_deleting_an_agent_takes_the_grants_that_pointed_at_it(self):
        """The grant table is generic - no foreign key, so nothing cascades for it.

        Left behind, those rows are a share of an id that no longer means
        anything, and they outlive the resource they described.
        """
        ctx = _ctx()
        agent = _agent(ctx)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.resource_grant_repo.delete_for_resource", new=AsyncMock()
            ) as drop_grants,
            patch(f"{REGISTRY_PATH}.agent_repo.delete", new=AsyncMock()) as delete,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await AgentRegistryService(_db()).delete(ctx, agent.id)

        assert drop_grants.call_args.kwargs["resource_type"] == "agent"
        assert drop_grants.call_args.kwargs["resource_id"] == agent.id
        assert drop_grants.call_args.kwargs["organization_id"] == ctx.organization_id
        assert delete.call_args.args[1] is agent
        assert audit.call_args.kwargs["action"] == "agent.deleted"


class TestGetVersion:
    """One frozen version, and the two ways it can be absent."""

    @pytest.mark.anyio
    async def test_a_version_is_read_within_the_callers_organization(self):
        ctx = _ctx()
        agent = _agent(ctx)
        version = _version(agent.id)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=version)
            ) as get_version,
        ):
            found = await AgentRegistryService(_db()).get_version(ctx, agent.id, version.id)

        assert found is version
        assert get_version.call_args.kwargs["organization_id"] == ctx.organization_id

    @pytest.mark.anyio
    async def test_a_missing_version_is_reported_as_not_found(self):
        ctx = _ctx()
        agent = _agent(ctx)
        version_id = uuid.uuid4()

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError) as refused,
        ):
            await AgentRegistryService(_db()).get_version(ctx, agent.id, version_id)

        assert refused.value.details == {"version_id": str(version_id)}

    @pytest.mark.anyio
    async def test_a_version_belonging_to_another_agent_is_refused_the_same_way(self):
        """Otherwise a version id read under the wrong agent would answer.

        Both refusals are byte-identical on purpose: a caller learns that this
        agent has no such version, never that the version exists elsewhere.
        """
        ctx = _ctx()
        agent = _agent(ctx)
        stranger = _version(uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=stranger)),
            pytest.raises(NotFoundError) as refused,
        ):
            await AgentRegistryService(_db()).get_version(ctx, agent.id, stranger.id)

        assert refused.value.details == {"version_id": str(stranger.id)}


class TestListVersions:
    @pytest.mark.anyio
    async def test_versions_are_read_within_the_callers_organization(self):
        ctx = _ctx()
        agent = _agent(ctx)
        versions = [_version(agent.id, number=1), _version(agent.id, number=2)]

        publisher = versions[0].published_by_user_id

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.list_versions",
                new=AsyncMock(return_value=versions),
            ) as list_versions,
            patch(
                f"{REGISTRY_PATH}.member_repo.get_emails_for_users",
                new=AsyncMock(return_value={publisher: "builder@acme.test"}),
            ),
        ):
            listed = await AgentRegistryService(_db()).list_versions(ctx, agent.id)

        assert [row.version for row in listed] == [v.version for v in versions]
        assert list_versions.call_args.kwargs["organization_id"] == ctx.organization_id
        # "Who changed this" is the reason a history is read; a uuid answers it
        # with another question.
        assert listed[0].published_by_email == "builder@acme.test"


class TestGetRunnableSpec:
    @pytest.mark.anyio
    async def test_the_published_spec_runs_and_not_the_draft(self):
        """Running the draft would mean running something nobody approved."""
        ctx = _ctx()
        published = _spec("Support", instructions="Approved wording")
        version = _version(uuid.uuid4(), spec=published)
        agent = _agent(
            ctx,
            status=AgentStatus.PUBLISHED.value,
            current_version_id=version.id,
            draft_spec=_spec("Support", instructions="Someone is mid-edit").model_dump(mode="json"),
        )

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=version)),
        ):
            found, spec, version_id = await AgentRegistryService(_db()).get_runnable_spec(
                ctx, agent.id
            )

        assert found is agent
        assert spec.instructions == "Approved wording"
        assert version_id == version.id

    @pytest.mark.anyio
    async def test_a_named_environment_resolves_its_own_pinned_version(self):
        """The whole point of environments: a dev bot runs what dev pins,
        not what publish last repointed."""
        ctx = _ctx()
        pinned = _version(uuid.uuid4(), number=2, spec=_spec("Support", instructions="Older"))
        agent = _agent(ctx, status=AgentStatus.PUBLISHED.value, current_version_id=uuid.uuid4())
        pinned.agent_id = agent.id
        environment = MagicMock(agent_id=agent.id, version_id=pinned.id)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_environment_repo.get",
                new=AsyncMock(return_value=environment),
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=pinned)
            ) as versions,
        ):
            _, spec, version_id = await AgentRegistryService(_db()).get_runnable_spec(
                ctx, agent.id, environment_id=environment.id
            )

        assert versions.call_args.args[1] == pinned.id
        assert version_id == pinned.id
        assert spec.instructions == "Older"

    @pytest.mark.anyio
    async def test_another_agents_environment_is_reported_as_missing(self):
        """An environment id resolving across agents would run one agent under
        another's pinned spec."""
        ctx = _ctx()
        agent = _agent(ctx, status=AgentStatus.PUBLISHED.value, current_version_id=uuid.uuid4())
        foreign = MagicMock(agent_id=uuid.uuid4(), version_id=uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_environment_repo.get",
                new=AsyncMock(return_value=foreign),
            ),
            pytest.raises(NotFoundError, match="Environment"),
        ):
            await AgentRegistryService(_db()).get_runnable_spec(
                ctx, agent.id, environment_id=foreign.id
            )

    @pytest.mark.anyio
    async def test_an_agent_that_was_never_published_cannot_be_run(self):
        ctx = _ctx()
        agent = _agent(ctx, current_version_id=None)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            pytest.raises(BadRequestError, match="has not been published yet"),
        ):
            await AgentRegistryService(_db()).get_runnable_spec(ctx, agent.id)

    @pytest.mark.anyio
    async def test_an_archived_agent_refuses_new_runs(self):
        """Archiving is how an agent is stopped; still answering would defeat it."""
        ctx = _ctx()
        agent = _agent(ctx, status=AgentStatus.ARCHIVED.value, current_version_id=uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            pytest.raises(BadRequestError, match="is archived"),
        ):
            await AgentRegistryService(_db()).get_runnable_spec(ctx, agent.id)

    @pytest.mark.anyio
    async def test_a_version_pointer_that_dangles_fails_loudly(self):
        """Falling back to the draft here is exactly the silent substitution to avoid."""
        ctx = _ctx()
        agent = _agent(ctx, status=AgentStatus.PUBLISHED.value, current_version_id=uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_version", new=AsyncMock(return_value=None)),
            pytest.raises(BadRequestError, match="points at a missing version"),
        ):
            await AgentRegistryService(_db()).get_runnable_spec(ctx, agent.id)


class TestClone:
    @pytest.mark.anyio
    async def test_a_clone_copies_the_draft_and_starts_over(self):
        """The spec is what carries over. Everything else is a statement about
        the original that nobody has made about the copy - so the copy has no
        versions, no grants and no exposures, and belongs to whoever cloned it.
        """
        ctx = _ctx()
        spec = _spec("Support", description="Answers customers", instructions="Be brief.")
        source = _agent(ctx, draft_spec=spec.model_dump(mode="json"))

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=source)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=_agent(ctx))
            ) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await AgentRegistryService(_db()).clone(ctx, source.id)

        written = create.call_args.kwargs
        assert written["name"] == "Support (copy)"
        assert written["slug"] == "support-copy"
        assert written["draft_spec"]["instructions"] == "Be brief."
        assert written["draft_spec"]["description"] == "Answers customers"
        assert written["owner_user_id"] == ctx.user_id
        assert [call.kwargs["action"] for call in audit.await_args_list] == [
            "agent.created",
            "agent.cloned",
        ]
        assert audit.await_args_list[-1].kwargs["details"]["source_agent_id"] == str(source.id)

    @pytest.mark.anyio
    async def test_a_clone_takes_the_name_it_was_given(self):
        ctx = _ctx()
        source = _agent(ctx)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=source)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=_agent(ctx))
            ) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
        ):
            await AgentRegistryService(_db()).clone(ctx, source.id, name="Support EU")

        assert create.call_args.kwargs["name"] == "Support EU"
        assert create.call_args.kwargs["slug"] == "support-eu"

    @pytest.mark.anyio
    async def test_cloning_twice_numbers_the_copy_instead_of_refusing(self):
        """The derived name has no field to correct.

        `create` refuses a taken handle by telling the caller to pick another
        name - right for a name somebody typed, useless for one this service
        made up on their behalf.
        """
        ctx = _ctx()
        source = _agent(ctx)
        taken = {"support-copy", "support-copy-2"}

        async def slug_lookup(_db, slug, **_kwargs):
            return _agent(ctx) if slug in taken else None

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=source)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(side_effect=slug_lookup)
            ),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=_agent(ctx))
            ) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
        ):
            await AgentRegistryService(_db()).clone(ctx, source.id)

        assert create.call_args.kwargs["name"] == "Support (copy 3)"

    @pytest.mark.anyio
    async def test_a_name_that_would_outgrow_the_column_is_cut_to_fit(self):
        """`AgentSpec.name` is bounded, and a copy of a copy of a copy grows."""
        ctx = _ctx()
        source = _agent(ctx, name="S" * 128, draft_spec=_spec("S" * 128).model_dump(mode="json"))

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=source)),
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=_agent(ctx))
            ) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
        ):
            await AgentRegistryService(_db()).clone(ctx, source.id)

        name = create.call_args.kwargs["name"]
        assert len(name) == 128
        assert name.endswith(" (copy)")

    @pytest.mark.anyio
    async def test_a_role_that_cannot_create_agents_cannot_clone_one(self):
        """A grant widens what its holder may do to *that* agent.

        It has never meant they may add agents to the organization, and reading
        it that way would let one shared agent become a hundred.
        """
        ctx = _ctx(OrgRoleName.VIEWER)
        source = _agent(ctx)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=source)),
            patch(f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock()) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
            pytest.raises(AuthorizationError, match="creates one"),
        ):
            await AgentRegistryService(_db()).clone(ctx, source.id)

        assert create.await_count == 0

    @pytest.mark.anyio
    async def test_a_registry_full_of_copies_reports_the_collision_it_cannot_solve(self):
        """Numbering gives up somewhere, and where it does the truthful answer is
        the one `create` already writes: the handle is taken."""
        ctx = _ctx()
        source = _agent(ctx)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=source)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.get_by_slug",
                new=AsyncMock(return_value=_agent(ctx)),
            ),
            patch(f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock()) as create,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
            pytest.raises(AlreadyExistsError, match="already taken"),
        ):
            await AgentRegistryService(_db()).clone(ctx, source.id)

        assert create.await_count == 0


class TestUnarchive:
    @pytest.mark.anyio
    async def test_an_agent_with_a_version_comes_back_published(self):
        ctx = _ctx()
        agent = _agent(ctx, status=AgentStatus.ARCHIVED.value, current_version_id=uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audit,
        ):
            await AgentRegistryService(_db()).unarchive(ctx, agent.id)

        assert update.call_args.kwargs["update_data"] == {"status": AgentStatus.PUBLISHED.value}
        assert audit.call_args.kwargs["action"] == "agent.unarchived"

    @pytest.mark.anyio
    async def test_an_agent_that_never_published_comes_back_as_a_draft(self):
        """Restoring it as published would claim it can run, and the run would
        be the thing that found out otherwise."""
        ctx = _ctx()
        agent = _agent(ctx, status=AgentStatus.ARCHIVED.value, current_version_id=None)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
        ):
            await AgentRegistryService(_db()).unarchive(ctx, agent.id)

        assert update.call_args.kwargs["update_data"] == {"status": AgentStatus.DRAFT.value}

    @pytest.mark.anyio
    async def test_restoring_something_that_was_never_archived_is_refused(self):
        """Succeeding silently would make the button look like it did something."""
        ctx = _ctx()
        agent = _agent(ctx, status=AgentStatus.DRAFT.value)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as update,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
            pytest.raises(BadRequestError, match="not archived"),
        ):
            await AgentRegistryService(_db()).unarchive(ctx, agent.id)

        assert update.await_count == 0


class TestAvatar:
    @pytest.mark.anyio
    async def test_an_uploaded_image_is_stored_and_pointed_at(self):
        ctx = _ctx()
        agent = _agent(ctx, avatar_url=None)
        storage = MagicMock()
        storage.save = AsyncMock(return_value="avatars/agents/x/logo.png")
        storage.delete = AsyncMock()

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.get_file_storage", return_value=storage),
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
        ):
            await AgentRegistryService(_db()).set_avatar(
                ctx, agent.id, file_data=b"png", filename="logo.png", content_type="image/png"
            )

        assert update.call_args.kwargs["update_data"] == {"avatar_url": "avatars/agents/x/logo.png"}
        assert storage.delete.await_count == 0

    @pytest.mark.anyio
    async def test_replacing_an_avatar_drops_the_file_it_replaced(self):
        """Otherwise every replacement leaves a file nothing points at."""
        ctx = _ctx()
        agent = _agent(ctx, avatar_url="avatars/agents/x/old.png")
        storage = MagicMock()
        storage.save = AsyncMock(return_value="avatars/agents/x/new.png")
        storage.delete = AsyncMock()

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.get_file_storage", return_value=storage),
            patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)),
        ):
            await AgentRegistryService(_db()).set_avatar(
                ctx, agent.id, file_data=b"png", filename="new.png", content_type="image/png"
            )

        assert storage.delete.await_args.args == ("avatars/agents/x/old.png",)

    @pytest.mark.anyio
    async def test_a_storage_that_cannot_delete_the_old_file_still_accepts_the_new_one(self):
        """The replacement is what the caller asked for; the orphan is unreachable
        the moment the row stops pointing at it."""
        ctx = _ctx()
        agent = _agent(ctx, avatar_url="avatars/agents/x/old.png")
        storage = MagicMock()
        storage.save = AsyncMock(return_value="avatars/agents/x/new.png")
        storage.delete = AsyncMock(side_effect=OSError("gone"))

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(f"{REGISTRY_PATH}.get_file_storage", return_value=storage),
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
        ):
            await AgentRegistryService(_db()).set_avatar(
                ctx, agent.id, file_data=b"png", filename="new.png", content_type="image/png"
            )

        assert update.await_count == 1

    @pytest.mark.anyio
    async def test_something_that_is_not_an_image_is_refused(self):
        ctx = _ctx()

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent(ctx))),
            pytest.raises(BadRequestError, match="images are allowed"),
        ):
            await AgentRegistryService(_db()).set_avatar(
                ctx,
                uuid.uuid4(),
                file_data=b"%PDF",
                filename="spec.pdf",
                content_type="application/pdf",
            )

    @pytest.mark.anyio
    async def test_an_image_over_the_limit_is_refused(self):
        ctx = _ctx()

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=_agent(ctx))),
            pytest.raises(BadRequestError, match="too large"),
        ):
            await AgentRegistryService(_db()).set_avatar(
                ctx,
                uuid.uuid4(),
                file_data=b"x" * (2 * 1024 * 1024 + 1),
                filename="huge.png",
                content_type="image/png",
            )

    @pytest.mark.anyio
    async def test_reading_an_avatar_goes_through_the_agents_own_access_check(self):
        """An avatar is not public just because it is an image: an unguarded path
        would answer which agent ids exist."""
        ctx = _ctx()

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=None)),
            pytest.raises(NotFoundError, match="Agent not found"),
        ):
            await AgentRegistryService(_db()).avatar_path(ctx, uuid.uuid4())

    @pytest.mark.anyio
    async def test_an_agent_with_no_avatar_reports_nothing_to_stream(self):
        ctx = _ctx()

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.get",
                new=AsyncMock(return_value=_agent(ctx, avatar_url=None)),
            ),
            pytest.raises(NotFoundError, match="no avatar"),
        ):
            await AgentRegistryService(_db()).avatar_path(ctx, uuid.uuid4())

    @pytest.mark.anyio
    async def test_a_row_pointing_at_a_file_that_is_gone_reports_no_avatar(self):
        """Same answer as having none. A caller cannot act on the difference, and
        the alternative is a 500 from a missing file."""
        ctx = _ctx()
        storage = MagicMock()
        missing = MagicMock()
        missing.exists.return_value = False
        storage.get_full_path.return_value = missing

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.get",
                new=AsyncMock(return_value=_agent(ctx, avatar_url="avatars/agents/x/gone.png")),
            ),
            patch(f"{REGISTRY_PATH}.get_file_storage", return_value=storage),
            pytest.raises(NotFoundError, match="no avatar"),
        ):
            await AgentRegistryService(_db()).avatar_path(ctx, uuid.uuid4())

    @pytest.mark.anyio
    async def test_a_stored_avatar_is_answered_with_the_file_on_disk(self):
        ctx = _ctx()
        storage = MagicMock()
        stored = MagicMock()
        stored.exists.return_value = True
        stored.__str__ = lambda _self: "/data/avatars/agents/x/logo.png"
        storage.get_full_path.return_value = stored

        with (
            patch(
                f"{REGISTRY_PATH}.agent_repo.get",
                new=AsyncMock(return_value=_agent(ctx, avatar_url="avatars/agents/x/logo.png")),
            ),
            patch(f"{REGISTRY_PATH}.get_file_storage", return_value=storage),
        ):
            path = await AgentRegistryService(_db()).avatar_path(ctx, uuid.uuid4())

        assert path == "/data/avatars/agents/x/logo.png"
        assert storage.get_full_path.call_args.args == ("avatars/agents/x/logo.png",)

    @pytest.mark.anyio
    async def test_choosing_a_colour_writes_the_slot(self):
        ctx = _ctx()
        agent = _agent(ctx)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
        ):
            await AgentRegistryService(_db()).set_avatar_color(ctx, agent.id, color=5)

        assert update.call_args.kwargs["update_data"] == {"avatar_color": 5}

    @pytest.mark.anyio
    async def test_a_null_colour_resets_to_auto(self):
        """The picker's Auto sends null; it must reach the column, not be dropped."""
        ctx = _ctx()
        agent = _agent(ctx)

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock(return_value=agent)
            ) as update,
        ):
            await AgentRegistryService(_db()).set_avatar_color(ctx, agent.id, color=None)

        assert update.call_args.kwargs["update_data"] == {"avatar_color": None}

    @pytest.mark.anyio
    async def test_choosing_a_colour_needs_edit_on_the_agent(self):
        """A colour is an edit; a Member with no grant is refused, and the refusal
        looks like an absence - the same as reaching an agent that is not there."""
        ctx = _ctx(OrgRoleName.MEMBER)
        agent = _agent(ctx, owner_user_id=uuid.uuid4())

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get", new=AsyncMock(return_value=agent)),
            patch(
                "app.services.access.resource_grant_repo.get_level",
                new=AsyncMock(return_value=None),
            ),
            patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as update,
            pytest.raises(NotFoundError),
        ):
            await AgentRegistryService(_db()).set_avatar_color(ctx, agent.id, color=3)

        assert update.await_count == 0


class TestWhatANewAgentOpensWith:
    """A prompt, not an empty box.

    An agent with no instructions still answers - as whatever the underlying model
    is by default, which is a different product on every provider and changes when
    the model is upgraded.
    """

    @pytest.mark.anyio
    async def test_a_new_agent_is_given_a_starting_prompt(self):
        created = MagicMock()
        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=created)
            ) as create,
        ):
            await AgentRegistryService(_db()).create(_ctx(), _spec("Support"))

        assert create.call_args.kwargs["draft_spec"]["instructions"] == DEFAULT_INSTRUCTIONS

    @pytest.mark.anyio
    async def test_a_prompt_somebody_wrote_is_left_alone(self):
        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=MagicMock())
            ) as create,
        ):
            await AgentRegistryService(_db()).create(
                _ctx(), _spec("Support", instructions="Answer only in Polish.")
            )

        assert create.call_args.kwargs["draft_spec"]["instructions"] == "Answer only in Polish."

    @pytest.mark.anyio
    async def test_a_prompt_of_only_whitespace_is_not_a_prompt(self):
        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock(return_value=MagicMock())
            ) as create,
        ):
            await AgentRegistryService(_db()).create(_ctx(), _spec("Support", instructions="   \n"))

        assert create.call_args.kwargs["draft_spec"]["instructions"] == DEFAULT_INSTRUCTIONS


class TestWorkspaceConfigurationsRefusedAtPublish:
    """The two a spec cannot judge for itself.

    Both otherwise fail inside a conversation, where the author is no longer
    looking at a form and the message reaches a user instead of them.
    """

    @pytest.mark.anyio
    async def test_a_container_workspace_needs_a_registered_connection(self, monkeypatch):
        """Otherwise the first tool call fails inside somebody's conversation,
        for a reason only an operator can fix and nobody is watching for."""
        from app.repositories import sandbox_connection_repo

        monkeypatch.setattr(sandbox_connection_repo, "get_default", AsyncMock(return_value=None))
        spec = _spec(capabilities=[{"id": "sandbox", "config": {"backend": "service"}}])

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

        assert any(
            "registered no sandbox connection" in problem
            for problem in refused.value.details["problems"]
        )

    @pytest.mark.anyio
    async def test_a_connection_from_another_organization_is_refused(self, monkeypatch):
        """The repository is asked inside the caller's organization, so another
        tenant's host reads as "does not exist" rather than being reachable."""
        from app.repositories import sandbox_connection_repo

        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=None))
        spec = _spec(
            capabilities=[
                {
                    "id": "sandbox",
                    "config": {"backend": "service", "connection_id": str(uuid4())},
                }
            ]
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

        assert any(
            "does not exist in this" in problem for problem in refused.value.details["problems"]
        )

    @pytest.mark.anyio
    async def test_a_connection_with_no_credential_is_refused(self, monkeypatch):
        """It resolves, and every sandbox opened on it would be refused a session."""
        from app.repositories import sandbox_connection_repo

        connection = MagicMock(secret_id=None)
        connection.name = "Big box"
        monkeypatch.setattr(
            sandbox_connection_repo, "get_default", AsyncMock(return_value=connection)
        )
        spec = _spec(capabilities=[{"id": "sandbox", "config": {"backend": "service"}}])

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

        assert any("Big box" in problem for problem in refused.value.details["problems"])

    @pytest.mark.anyio
    async def test_a_connection_on_the_state_backend_is_refused(self):
        """The platform stores that workspace itself, so a host is not a choice it
        has. Ignoring the field would leave an author believing they picked one."""
        spec = _spec(
            capabilities=[
                {
                    "id": "sandbox",
                    "config": {"backend": "state", "connection_id": str(uuid4())},
                }
            ]
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

        assert any("does not run" in problem for problem in refused.value.details["problems"])

    @pytest.mark.anyio
    async def test_a_named_connection_with_a_credential_is_not_a_problem(self, monkeypatch):
        """The branch the three refusals above exist to let through. Asserted on
        the workspace's own problems rather than on publishing succeeding: this
        spec is deliberately bare, so it has others."""
        from app.repositories import sandbox_connection_repo

        connection = MagicMock(secret_id=uuid4())
        connection.name = "Big box"
        monkeypatch.setattr(sandbox_connection_repo, "get", AsyncMock(return_value=connection))
        spec = _spec(
            capabilities=[
                {
                    "id": "sandbox",
                    "config": {"backend": "service", "connection_id": str(uuid4())},
                }
            ]
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

        assert not [
            problem for problem in refused.value.details["problems"] if "connection" in problem
        ]

    @pytest.mark.anyio
    async def test_a_runtime_on_a_backend_with_no_container_is_refused(self):
        """Silently ignoring it would leave an author believing they chose one."""
        spec = _spec(
            capabilities=[{"id": "sandbox", "config": {"backend": "state", "runtime": "python"}}]
        )

        with pytest.raises(BadRequestError) as refused:
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

        assert any(
            "no runtime to choose" in problem for problem in refused.value.details["problems"]
        )

    @pytest.mark.anyio
    async def test_a_per_user_workspace_publishes_and_is_judged_at_run_time(self, monkeypatch):
        """Publishing cannot know which surfaces an agent will be reached from,
        and a web-only agent with a per-user workspace is a good configuration.
        """
        profile = MagicMock(id=uuid.uuid4())
        spec = _spec(
            capabilities=[{"id": "sandbox", "config": {"session_scope": "user"}}],
            model_profile_id=profile.id,
        )

        with patch(
            f"{REGISTRY_PATH}.credential_repo.get_profile", new=AsyncMock(return_value=profile)
        ):
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)


class TestBrowserUseRefusedAtPublish:
    """A remote `cdp_url` this deployment must not connect to.

    The SSRF check resolves DNS, which blocks, so it runs at publish off the event
    loop rather than at build on it (agenticos#33). Every binding passes through
    `_binding_problems`, so a specialist's endpoint is checked the same way.
    """

    @pytest.mark.anyio
    async def test_a_loopback_cdp_url_is_refused(self):
        """A debugger on the host, a metadata service - refused before it runs."""
        spec = _spec(
            capabilities=[
                {
                    "id": "browser_use",
                    "config": {"mode": "remote", "cdp_url": "http://127.0.0.1:9222"},
                }
            ],
            model_profile_id=uuid.uuid4(),
        )

        with (
            patch(
                f"{REGISTRY_PATH}.credential_repo.get_profile",
                new=AsyncMock(return_value=MagicMock()),
            ),
            pytest.raises(BadRequestError) as refused,
        ):
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)

        assert any(
            "remote endpoint cannot be reached" in problem
            for problem in refused.value.details["problems"]
        )

    @pytest.mark.anyio
    async def test_a_public_cdp_url_publishes(self):
        """A reachable public browser service is fine - nothing to refuse."""
        profile = MagicMock(id=uuid.uuid4())
        spec = _spec(
            capabilities=[
                {
                    "id": "browser_use",
                    "config": {"mode": "remote", "cdp_url": "http://8.8.8.8:9222"},
                }
            ],
            model_profile_id=profile.id,
        )

        with patch(
            f"{REGISTRY_PATH}.credential_repo.get_profile", new=AsyncMock(return_value=profile)
        ):
            await AgentRegistryService(_db()).validate_spec(_ctx(), spec)


def _bound(capability_id: str, config: dict, **approval: object):
    """A one-capability spec, configured and gated as one binding says."""
    return _spec(
        capabilities=[{"id": capability_id, "config": config, **approval}],
        model_profile_id=uuid.uuid4(),
    )


async def _refusal(spec) -> list[str]:
    with (
        patch(
            f"{REGISTRY_PATH}.credential_repo.get_profile",
            new=AsyncMock(return_value=MagicMock()),
        ),
        pytest.raises(BadRequestError) as refused,
    ):
        await AgentRegistryService(_db()).validate_spec(_ctx(), spec)
    return refused.value.details["problems"]


async def _publishes(spec) -> None:
    with patch(
        f"{REGISTRY_PATH}.credential_repo.get_profile",
        new=AsyncMock(return_value=MagicMock(id=spec.model_profile_id)),
    ):
        await AgentRegistryService(_db()).validate_spec(_ctx(), spec)


class TestAFetchTheApprovalGateCouldNotHold:
    """Approval on a `web_fetch` binding that hands the fetch to the provider.

    `ApprovalGate` wraps tool execution, and a native fetch is executed by the
    model provider - so the gate never sees it, the queue stays empty, and the
    agent reads pages nobody approved. That is silent at run time, which is why
    it is refused here.
    """

    @staticmethod
    def _spec_with(config: dict, **approval: object):
        return _bound("web_fetch", config, **approval)

    @pytest.mark.anyio
    async def test_native_fetch_with_approval_required_is_refused(self):
        problems = await _refusal(self._spec_with({"method": "native"}, approval="required"))
        assert any("no call to hold" in problem for problem in problems)

    @pytest.mark.anyio
    async def test_auto_is_refused_too_because_the_model_decides_which_it_gets(self):
        """Which of the two an `auto` binding runs is a property of the model
        profile, and that changes without republishing the agent."""
        problems = await _refusal(
            self._spec_with({"method": "auto"}, tool_approval={"web_fetch": "required"})
        )
        assert any("no call to hold" in problem for problem in problems)

    @pytest.mark.anyio
    async def test_a_local_fetch_can_be_approved_and_publishes(self):
        await _publishes(self._spec_with({"method": "local"}, approval="required"))

    @pytest.mark.anyio
    async def test_native_fetch_nobody_asked_to_approve_publishes(self):
        """The refusal is about approval, not about the provider doing the work."""
        await _publishes(self._spec_with({"method": "native"}))


class TestASearchTheApprovalGateCouldNotHold:
    """The same refusal for `web_research`, which has the same shape (#857).

    Under `method: native` the capability contributes Pydantic AI's own
    `WebSearch()` and the provider runs the search on its own side, so there is
    no local call for the gate to hold - a binding that asks for approval gets
    an empty queue and an agent searching unapproved.
    """

    @staticmethod
    def _spec_with(config: dict, **approval: object):
        return _bound("web_research", config, **approval)

    @pytest.mark.anyio
    async def test_native_search_with_approval_required_is_refused(self):
        problems = await _refusal(self._spec_with({"method": "native"}, approval="required"))
        assert any("no call to hold" in problem for problem in problems)

    @pytest.mark.anyio
    async def test_the_refusal_names_the_tool_and_what_to_do_about_it(self):
        problems = await _refusal(
            self._spec_with({"method": "native"}, tool_approval={"web_search": "required"})
        )
        assert any(
            "requires approval for web_search" in problem
            and "method 'native'" in problem
            and "Choose a method this deployment runs itself" in problem
            for problem in problems
        )

    @pytest.mark.anyio
    async def test_a_search_this_deployment_runs_can_be_approved_and_publishes(self):
        await _publishes(self._spec_with({"method": "duckduckgo"}, approval="required"))

    @pytest.mark.anyio
    async def test_native_search_nobody_asked_to_approve_publishes(self):
        """The refusal is about approval, not about the provider doing the work."""
        await _publishes(self._spec_with({"method": "native"}))


class TestASharedWorkspaceIsAnswerableAfterwards:
    """`session_scope="agent"` ships without a permission of its own.

    So the audit entry is what makes the decision answerable: a member who finds
    a file they never created can be told when the sharing started and who chose
    it, rather than concluding something leaked.
    """

    @staticmethod
    async def _publish(spec):
        service = AgentRegistryService(_db())
        agent = MagicMock(id=uuid.uuid4(), draft_spec=spec.model_dump(mode="json"))

        with (
            patch.object(service, "get", new=AsyncMock(return_value=agent)),
            patch.object(service, "validate_spec", new=AsyncMock()),
            patch.object(service, "_repoint_default_environment", new=AsyncMock()),
            patch(f"{REGISTRY_PATH}.agent_repo.next_version_number", new=AsyncMock(return_value=3)),
            patch(
                f"{REGISTRY_PATH}.agent_repo.create_version",
                new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
            ),
            patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()),
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()) as audited,
        ):
            await service.publish(_ctx(), agent.id)

        return [call.kwargs["action"] for call in audited.await_args_list]

    @pytest.mark.anyio
    async def test_sharing_between_people_is_recorded(self):
        actions = await self._publish(
            _spec(capabilities=[{"id": "sandbox", "config": {"session_scope": "agent"}}])
        )

        assert "agent.workspace_shared" in actions

    @pytest.mark.anyio
    async def test_a_workspace_nobody_else_can_read_is_not(self):
        """Recording every publish as sharing would make the entry meaningless."""
        actions = await self._publish(
            _spec(capabilities=[{"id": "sandbox", "config": {"session_scope": "conversation"}}])
        )

        assert "agent.workspace_shared" not in actions

    @pytest.mark.anyio
    async def test_an_agent_with_no_workspace_is_not(self):
        actions = await self._publish(_spec())

        assert "agent.workspace_shared" not in actions


class TestACapabilityAgentsMayNotBind:
    """`channel_tools` is granted per bound bot, and the Toolbox does not offer it.

    What the product *can* still do is send it back: a browser holding a draft
    loaded before the capability moved re-posts the whole spec on the next save.
    Refusing at publish was the first answer and it was a dead end - the message
    names a switch the Builder does not show, so there is nothing to act on and
    no way to remove the binding from the only screen that edits capabilities.
    """

    @pytest.mark.anyio
    async def test_saving_a_draft_drops_it(self):
        service = AgentRegistryService(_db())
        service.get = AsyncMock(return_value=MagicMock())
        spec = _spec(capabilities=[{"id": "clock"}, {"id": "channel_tools"}])

        with patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as stored:
            await service.save_draft(_ctx(), uuid.uuid4(), spec)

        saved = stored.call_args.kwargs["update_data"]["draft_spec"]
        assert [binding["id"] for binding in saved["capabilities"]] == ["clock"]

    @pytest.mark.anyio
    async def test_a_stale_tab_heals_the_row_it_keeps_reposting(self):
        """Which is the whole point of doing it on write. A migration cleared
        these once and the next save put one straight back."""
        service = AgentRegistryService(_db())
        service.get = AsyncMock(return_value=MagicMock())

        with patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as stored:
            await service.save_draft(
                _ctx(), uuid.uuid4(), _spec(capabilities=[{"id": "channel_tools"}])
            )

        assert stored.call_args.kwargs["update_data"]["draft_spec"]["capabilities"] == []

    @pytest.mark.anyio
    async def test_a_spec_that_names_none_is_stored_unchanged(self):
        """No copy, no log line, nothing to explain - which is every save."""
        service = AgentRegistryService(_db())
        service.get = AsyncMock(return_value=MagicMock())
        spec = _spec(capabilities=[{"id": "clock"}])

        with patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as stored:
            await service.save_draft(_ctx(), uuid.uuid4(), spec)

        saved = stored.call_args.kwargs["update_data"]["draft_spec"]
        assert [binding["id"] for binding in saved["capabilities"]] == ["clock"]

    @pytest.mark.anyio
    async def test_the_same_holds_for_a_spec_arriving_as_a_new_agent(self):
        """A YAML import is the other write, and it reaches `create`."""
        service = AgentRegistryService(_db())

        with (
            patch(f"{REGISTRY_PATH}.agent_repo.get_by_slug", new=AsyncMock(return_value=None)),
            patch(f"{REGISTRY_PATH}.agent_repo.create", new=AsyncMock()) as created,
            patch(f"{REGISTRY_PATH}.record_audit", new=AsyncMock()),
        ):
            await service.create(_ctx(), _spec(capabilities=[{"id": "channel_tools"}]))

        assert created.call_args.kwargs["draft_spec"]["capabilities"] == []

    @pytest.mark.anyio
    async def test_a_capability_that_does_not_exist_is_left_for_publish_to_refuse(self):
        """A draft naming an unknown id has to stay saveable - half-finished
        configuration is the whole reason `save_draft` does not validate."""
        service = AgentRegistryService(_db())
        service.get = AsyncMock(return_value=MagicMock())

        with patch(f"{REGISTRY_PATH}.agent_repo.update", new=AsyncMock()) as stored:
            await service.save_draft(
                _ctx(), uuid.uuid4(), _spec(capabilities=[{"id": "no_such_capability"}])
            )

        saved = stored.call_args.kwargs["update_data"]["draft_spec"]
        assert [binding["id"] for binding in saved["capabilities"]] == ["no_such_capability"]
