"""The skills listing arranged into sections, against Postgres.

What only a database shows:

- a skill several agents serve sits under each, a draft-only binding and no
  binding at all have sections of their own, and the counts are of the whole
  filtered set rather than of the cards a section carries;
- arranging never widens the listing: another member's private skill, an agent
  the caller cannot view and anything in another organization stay out of
  every section and every count, and the category filter offers no shelf
  whose skills the caller cannot open;
- shipped skills split by library and gallery industry, and categories fold
  letter case - in the sections and in the filter alike;
- a section pages like the flat listing, and arranging costs the same number
  of queries however many sections there are.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.agent import Agent, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.resource_grant import GrantLevel, ResourceGrant
from app.db.models.skill import Skill
from app.schemas.skill import SkillSections
from app.services import skill_library
from app.services.skills import SkillService
from tests.integration.test_authoring import _member, _owner

pytestmark = pytest.mark.anyio


async def _skill(
    db: AsyncSession,
    ctx: AuthContext,
    name: str,
    *,
    category: str | None = None,
    visibility: str = "org",
) -> Skill:
    skill = Skill(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        name=name,
        description=f"What {name} is for.",
        content=f"# {name}",
        category=category,
        visibility=visibility,
    )
    db.add(skill)
    await db.flush()
    return skill


async def _agent(
    db: AsyncSession,
    ctx: AuthContext,
    name: str,
    *,
    serves: Sequence[Skill] = (),
    drafts: Sequence[Skill] = (),
    visibility: str = "org",
) -> Agent:
    """An agent whose default environment serves `serves` and whose draft adds `drafts`."""
    served: dict[str, Any] = {"name": name, "skill_ids": [str(skill.id) for skill in serves]}
    agent = Agent(
        id=uuid.uuid4(),
        organization_id=ctx.organization_id,
        owner_user_id=ctx.user_id,
        visibility=visibility,
        slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
        name=name,
        status="published" if serves else "draft",
        draft_spec={**served, "skill_ids": [str(skill.id) for skill in (*serves, *drafts)]},
    )
    db.add(agent)
    await db.flush()
    if serves:
        version = AgentVersion(
            agent_id=agent.id, organization_id=ctx.organization_id, version=1, spec=served
        )
        db.add(version)
        await db.flush()
        agent.current_version_id = version.id
        db.add(
            AgentEnvironment(
                organization_id=ctx.organization_id,
                agent_id=agent.id,
                name="production",
                version_id=version.id,
                is_default=True,
            )
        )
        await db.flush()
    return agent


def _laid_out(sections: SkillSections) -> list[tuple[str, int, list[str]]]:
    return [
        (section.key, section.count, [item.name for item in section.items])
        for section in sections.sections
    ]


class TestByAgent:
    async def test_each_agent_holds_the_skills_it_serves_and_the_rest_fall_last(
        self, db: AsyncSession
    ):
        owner = await _owner(db)
        refunds = await _skill(db, owner, "refunds")
        tone = await _skill(db, owner, "tone")
        planned = await _skill(db, owner, "planned")
        lonely = await _skill(db, owner, "lonely")
        support = await _agent(db, owner, "Support", serves=[refunds, tone])
        billing = await _agent(db, owner, "Billing", serves=[refunds])
        await _agent(db, owner, "Builder", drafts=[planned])

        sections = await SkillService(db).list_sections(owner, "agent")

        assert _laid_out(sections) == [
            (f"agent:{billing.id}", 1, ["refunds"]),
            (f"agent:{support.id}", 2, ["refunds", "tone"]),
            ("drafted", 1, ["planned"]),
            ("unused", 1, ["lonely"]),
        ]
        assert sections.total == 4
        assert sections.sections[0].agent is not None
        assert sections.sections[0].agent.name == "Billing"
        by_name = {item.name: item for section in sections.sections for item in section.items}
        assert [agent.name for agent in by_name["refunds"].used_by] == ["Billing", "Support"]
        assert [agent.name for agent in by_name["planned"].drafted_by] == ["Builder"]
        assert lonely.id == by_name["lonely"].id

    async def test_an_agent_the_member_cannot_view_is_no_section_and_its_skill_reads_unused(
        self, db: AsyncSession
    ):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        recipes = await _skill(db, owner, "recipes")
        hidden = await _agent(db, owner, "Hidden", serves=[recipes], visibility="private")

        as_member = await SkillService(db).list_sections(member, "agent")
        as_owner = await SkillService(db).list_sections(owner, "agent")

        assert _laid_out(as_member) == [("unused", 1, ["recipes"])]
        assert _laid_out(as_owner) == [(f"agent:{hidden.id}", 1, ["recipes"])]

    async def test_per_section_cuts_the_cards_and_never_the_count(self, db: AsyncSession):
        owner = await _owner(db)
        for name in ("alpha", "beta", "gamma"):
            await _skill(db, owner, name)

        sections = await SkillService(db).list_sections(owner, "agent", per_section=2)

        assert _laid_out(sections) == [("unused", 3, ["alpha", "beta"])]

    async def test_arranging_costs_the_same_queries_however_many_sections(
        self, db: AsyncSession, engine: AsyncEngine
    ):
        """Every section's cards come from one batch, so a library spread over
        many agents is not a query per agent."""
        one = await _owner(db)
        await _agent(db, one, "Solo", serves=[await _skill(db, one, "solo")])
        many = await _owner(db)
        for index in range(4):
            await _agent(db, many, f"Agent{index}", serves=[await _skill(db, many, f"s{index}")])

        statements: list[str] = []

        def record(*args: Any) -> None:
            statements.append(args[2])

        async def counted(ctx: AuthContext) -> tuple[int, int]:
            statements.clear()
            event.listen(engine.sync_engine, "before_cursor_execute", record)
            try:
                sections = await SkillService(db).list_sections(ctx, "agent")
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", record)
            return len(sections.sections), len(statements)

        few, few_queries = await counted(one)
        lots, lots_queries = await counted(many)

        assert (few, lots) == (1, 4)
        assert lots_queries == few_queries


class TestNothingWidens:
    async def test_another_members_private_skill_is_in_no_section_and_no_count(
        self, db: AsyncSession
    ):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        await _skill(db, owner, "owner-notes", category="Secret", visibility="private")
        await _skill(db, member, "my-notes", visibility="private")
        await _skill(db, owner, "handbook", category="ops")

        for arrange in ("agent", "origin", "category"):
            sections = await SkillService(db).list_sections(member, arrange)

            shown = [item.name for section in sections.sections for item in section.items]
            assert sorted(shown) == ["handbook", "my-notes"], arrange
            assert sections.total == 2, arrange
            assert sum(section.count for section in sections.sections) == 2, arrange
            assert all(section.category != "Secret" for section in sections.sections), arrange
            assert sections.categories == ["ops"], arrange

    async def test_another_organizations_skills_and_agents_never_count(self, db: AsyncSession):
        mine = await _owner(db)
        theirs = await _owner(db)
        handbook = await _skill(db, mine, "handbook")
        foreign = await _skill(db, theirs, "foreign")
        # Their agent names my skill's id; a binding never crosses tenants.
        await _agent(db, theirs, "Theirs", serves=[handbook, foreign])

        sections = await SkillService(db).list_sections(mine, "agent")

        assert _laid_out(sections) == [("unused", 1, ["handbook"])]


class TestTheCategoryFilter:
    """The filter's choices name only shelves the caller can open, on both listings."""

    async def _choices(self, db: AsyncSession, ctx: AuthContext) -> list[str]:
        flat = await SkillService(db).list_readable(ctx)
        arranged = await SkillService(db).list_sections(ctx, "category")
        assert flat.categories == arranged.categories
        return flat.categories

    async def test_another_members_private_shelf_is_offered_only_to_who_can_open_it(
        self, db: AsyncSession
    ):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        await _skill(db, owner, "layoffs", category="Restructuring", visibility="private")
        await _skill(db, owner, "handbook", category="ops")

        assert await self._choices(db, member) == ["ops"]
        assert await self._choices(db, owner) == ["ops", "Restructuring"]

    async def test_a_shelf_stays_while_one_of_its_skills_is_visible(self, db: AsyncSession):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        await _skill(db, owner, "payroll", category="Finance", visibility="private")
        await _skill(db, owner, "invoices", category="finance")

        assert await self._choices(db, member) == ["finance"]

    async def test_the_callers_own_and_granted_private_skills_offer_their_shelves(
        self, db: AsyncSession
    ):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        await _skill(db, member, "my-notes", category="journal", visibility="private")
        granted = await _skill(db, owner, "runbook", category="incidents", visibility="private")
        await _skill(db, owner, "unshared", category="secret", visibility="private")
        db.add(
            ResourceGrant(
                organization_id=owner.organization_id,
                subject_user_id=member.user_id,
                resource_type="skill",
                resource_id=granted.id,
                level=GrantLevel.READ.value,
            )
        )
        await db.flush()

        assert await self._choices(db, member) == ["incidents", "journal"]

    async def test_another_organizations_shelves_are_never_offered(self, db: AsyncSession):
        mine = await _owner(db)
        theirs = await _owner(db)
        await _skill(db, mine, "handbook", category="ops")
        await _skill(db, theirs, "foreign", category="theirs")

        assert await self._choices(db, mine) == ["ops"]


class TestByOrigin:
    async def test_shipped_skills_split_by_library_and_gallery_industry(self, db: AsyncSession):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        industry = skill_library.gallery()[0]
        bundled = skill_library.library()[0].name
        installed = industry.skills[0].name
        await _skill(db, owner, bundled)
        await _skill(db, owner, installed)
        await _skill(db, owner, "our-tone")
        await _skill(db, member, "my-notes", visibility="private")

        sections = await SkillService(db).list_sections(member, "origin")

        assert _laid_out(sections) == [
            ("origin:org", 1, ["our-tone"]),
            ("origin:private", 1, ["my-notes"]),
            ("origin:platform", 1, [bundled]),
            (f"origin:gallery:{industry.id}", 1, [installed]),
        ]
        gallery = sections.sections[3]
        assert gallery.industry == industry.id
        assert gallery.items[0].gallery_industry == industry.id
        assert gallery.items[0].built_in is True
        assert sections.sections[2].items[0].gallery_industry is None


class TestByCategory:
    async def test_spellings_fold_into_one_shelf_and_the_filter_matches_any_case(
        self, db: AsyncSession
    ):
        owner = await _owner(db)
        await _skill(db, owner, "firewall", category="Security")
        await _skill(db, owner, "passwords", category="security")
        await _skill(db, owner, "loose")

        sections = await SkillService(db).list_sections(owner, "category")
        listed = await SkillService(db).list_readable(owner, categories=["SECURITY"])

        assert _laid_out(sections) == [
            ("category:security", 2, ["firewall", "passwords"]),
            ("category:", 1, ["loose"]),
        ]
        assert sections.sections[0].category == "security"
        assert sections.categories == ["security"]
        assert listed.total == 2

    async def test_the_filters_narrow_the_sections_and_their_counts(self, db: AsyncSession):
        owner = await _owner(db)
        await _skill(db, owner, "refund-policy", category="support")
        await _skill(db, owner, "refund-tone", category="Support")
        await _skill(db, owner, "invoices", category="finance")

        sections = await SkillService(db).list_sections(owner, "category", search="refund")

        assert _laid_out(sections) == [("category:support", 2, ["refund-policy", "refund-tone"])]
        assert sections.total == 2


class TestSectionPaging:
    async def test_a_section_pages_like_the_flat_listing(self, db: AsyncSession):
        owner = await _owner(db)
        refunds = await _skill(db, owner, "refunds")
        await _skill(db, owner, "alpha")
        await _skill(db, owner, "beta")
        support = await _agent(db, owner, "Support", serves=[refunds])

        unused = await SkillService(db).list_readable(owner, section="unused", skip=1, limit=1)
        served = await SkillService(db).list_readable(owner, section=f"agent:{support.id}")
        gone = await SkillService(db).list_readable(owner, section=f"agent:{uuid.uuid4()}")

        assert (unused.total, [item.name for item in unused.items]) == (2, ["beta"])
        assert [item.name for item in served.items] == ["refunds"]
        assert [agent.name for agent in served.items[0].used_by] == ["Support"]
        assert (gone.total, gone.items) == (0, [])

    async def test_a_section_pages_within_the_callers_reach(self, db: AsyncSession):
        owner = await _owner(db)
        member = await _member(db, owner, OrgRoleName.MEMBER)
        await _skill(db, owner, "owner-notes", visibility="private")

        page = await SkillService(db).list_readable(member, section="origin:private")

        assert page.total == 0

    async def test_a_key_that_names_no_section_is_refused(self, db: AsyncSession):
        owner = await _owner(db)

        with pytest.raises(BadRequestError) as refused:
            await SkillService(db).list_readable(owner, section="folder:sales")

        assert refused.value.details["fields"][0]["field"] == "section"
