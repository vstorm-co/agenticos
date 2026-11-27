"""Arranging the skills listing into sections, without a database.

The rows and the agent usage arrive already narrowed to what the caller may see
(`tests/integration/test_skill_sections.py` proves that half). What is left is
the sorting: which section a skill lands in, in what order the sections come,
and that nothing is lost or invented on the way.
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.repositories.skill import SkillKey
from app.schemas.resource_usage import AgentUsage
from app.services import skill_sections
from app.services.resource_usage import SkillBindings, skill_bindings
from app.services.skill_sections import (
    arrangement_of,
    by_agent,
    by_category,
    by_origin,
    category_label,
    fold_categories,
)


def _key(name: str, *, category: str | None = None, visibility: str = "org") -> SkillKey:
    return SkillKey(id=uuid.uuid4(), name=name, category=category, visibility=visibility)


def _agent(name: str) -> AgentUsage:
    return AgentUsage(id=uuid.uuid4(), name=name, slug=name.lower())


def _arranged(keys, *, serving=(), drafting=(), agents=()):
    """`by_agent` over per-agent id sets, as `skill_bindings` hands them over."""
    return by_agent(
        keys,
        serving={agent.id: frozenset(ids) for agent, ids in serving},
        drafting={agent.id: frozenset(ids) for agent, ids in drafting},
        agents={agent.id: agent for agent in agents},
    )


class TestByAgent:
    def test_a_skill_several_agents_serve_sits_under_each_of_them(self):
        refunds, tone = _key("refunds"), _key("tone")
        support, billing = _agent("Support"), _agent("billing")

        sections = _arranged(
            [refunds, tone],
            serving=[(support, {tone.id, refunds.id}), (billing, {refunds.id})],
            agents=(support, billing),
        )

        assert [(section.key, section.skill_ids) for section in sections] == [
            (f"agent:{billing.id}", [refunds.id]),
            (f"agent:{support.id}", [refunds.id, tone.id]),
        ]
        assert sections[0].agent == billing

    def test_a_skill_only_a_draft_binds_is_drafted_only(self):
        drafted, served = _key("drafted"), _key("served")
        support, builder = _agent("Support"), _agent("Builder")

        sections = _arranged(
            [drafted, served],
            serving=[(support, {served.id})],
            drafting=[(builder, {drafted.id, served.id})],
            agents=(support, builder),
        )

        assert [section.kind for section in sections] == ["agent", "drafted"]
        assert sections[1].skill_ids == [drafted.id]

    def test_a_skill_no_agent_uses_falls_last(self):
        lonely, drafted = _key("lonely"), _key("drafted")
        builder = _agent("Builder")

        sections = _arranged(
            [lonely, drafted], drafting=[(builder, {drafted.id})], agents=(builder,)
        )

        assert [(section.key, section.skill_ids) for section in sections] == [
            ("drafted", [drafted.id]),
            ("unused", [lonely.id]),
        ]

    def test_nothing_to_arrange_is_no_section(self):
        assert _arranged([]) == []


class TestByOrigin:
    def test_skills_split_into_own_private_platform_and_gallery_industries(self):
        own = _key("our-tone")
        mine = _key("my-notes", visibility="private")
        platform = _key("refund-policy")
        finance, ledger = _key("invoice-check"), _key("ledger-close")
        consent = _key("consent-explainer")

        sections = by_origin(
            [own, mine, platform, finance, consent, ledger],
            bundled_names=frozenset({"refund-policy"}),
            gallery_industries={
                "invoice-check": "finance",
                "ledger-close": "finance",
                "consent-explainer": "healthcare",
            },
        )

        assert [(section.key, section.skill_ids) for section in sections] == [
            ("origin:org", [own.id]),
            ("origin:private", [mine.id]),
            ("origin:platform", [platform.id]),
            ("origin:gallery:finance", [finance.id, ledger.id]),
            ("origin:gallery:healthcare", [consent.id]),
        ]
        assert sections[3].industry == "finance"

    def test_a_skill_shared_with_chosen_groups_is_the_organizations_own(self):
        team = _key("support-tone", visibility="team")

        sections = by_origin([team], bundled_names=frozenset(), gallery_industries={})

        assert [(section.key, section.skill_ids) for section in sections] == [
            ("origin:org", [team.id])
        ]

    def test_a_shipped_name_reads_as_shipped_even_when_private(self):
        """Installing keeps only the name, so the name is what decides."""
        copied = _key("refund-policy", visibility="private")

        sections = by_origin(
            [copied], bundled_names=frozenset({"refund-policy"}), gallery_industries={}
        )

        assert [section.key for section in sections] == ["origin:platform"]


class TestByCategory:
    def test_spellings_differing_in_case_share_one_shelf(self):
        upper, lower = _key("a", category="Security"), _key("b", category="security ")
        data = _key("c", category="Data")

        sections = by_category([upper, lower, data], suggested=["security"])

        assert [(section.key, section.category, section.skill_ids) for section in sections] == [
            ("category:data", "Data", [data.id]),
            ("category:security", "security", [upper.id, lower.id]),
        ]

    def test_a_skill_without_a_shelf_is_uncategorized_and_last(self):
        none, blank, shelved = _key("a"), _key("b", category="  "), _key("c", category="ops")

        sections = by_category([none, blank, shelved], suggested=[])

        assert [(section.kind, section.skill_ids) for section in sections] == [
            ("category", [shelved.id]),
            ("uncategorized", [none.id, blank.id]),
        ]


class TestCategoryLabels:
    def test_a_suggested_shelf_lends_its_spelling(self):
        assert category_label(["Security", "SECURITY"], ["security"]) == "security"

    def test_otherwise_the_first_spelling_in_sort_order_wins(self):
        assert category_label(["ops", "Ops"], ["security"]) == "Ops"

    def test_the_filter_offers_one_choice_per_shelf(self):
        assert fold_categories(["Security", "security", "Data", " "], ["security"]) == [
            "Data",
            "security",
        ]


class TestSectionKeys:
    def test_each_key_names_its_arrangement(self):
        assert arrangement_of(f"agent:{uuid.uuid4()}") == "agent"
        assert arrangement_of(skill_sections.DRAFTED) == "agent"
        assert arrangement_of(skill_sections.UNUSED) == "agent"
        assert arrangement_of("origin:private") == "origin"
        assert arrangement_of("origin:gallery:finance") == "origin"
        assert arrangement_of("category:") == "category"

    def test_a_key_that_names_no_section_is_refused(self):
        assert arrangement_of("origin:everywhere") is None
        assert arrangement_of("folder:sales") is None


@pytest.mark.anyio
async def test_no_skills_asked_reads_no_agents():
    """A search that matched nothing has nothing to look the agents up for."""
    db = AsyncMock()
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER)

    bindings = await skill_bindings(db, ctx, skill_ids=[])

    assert (bindings.serving, bindings.drafting, bindings.agents) == ({}, {}, {})
    db.execute.assert_not_awaited()


class TestSkillBindings:
    def test_a_skill_is_named_by_the_agents_that_bind_it_in_name_order(self):
        refunds, tone = uuid.uuid4(), uuid.uuid4()
        billing, support = _agent("Billing"), _agent("Support")
        bindings = SkillBindings(
            serving={billing.id: frozenset({refunds}), support.id: frozenset({refunds, tone})},
            drafting={support.id: frozenset({tone})},
            agents={billing.id: billing, support.id: support},
        )

        assert bindings.used_by(refunds) == [billing, support]
        assert bindings.used_by(tone) == [support]
        assert bindings.drafted_by(tone) == [support]
        assert bindings.drafted_by(refunds) == []
