"""Tests for the `audit-skill-bindings` sweep.

The sweep is the offline half of #179: it names published agents whose frozen
spec lends a skill the publisher could not reach, so an operator can decide what
to do. The two things that matter and are easy to get wrong: the answer is a fact
about the rows, not about the publisher's role today (so it must not un-flag
itself when that role later changes), and a publisher whose user row is gone is
reported as *unknown* rather than guessed either way. The row-based behaviour is
proved end to end in `tests/integration/test_skill_binding_audit.py`; these cover
the decisions and the wiring with the repositories mocked.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.commands import audit_skill_bindings as sweep
from app.commands.audit_skill_bindings import (
    BindingStatus,
    Finding,
    _bindings,
    _classify,
    _findings_for,
    _line,
    _location,
    _publisher,
    _report,
    _run,
    _scan,
    audit_skill_bindings,
)
from app.db.models.agent import AgentStatus
from app.db.models.resource_grant import GrantLevel, Visibility


def _skill(*, owner_user_id: uuid.UUID | None = None, visibility: str = Visibility.PRIVATE.value):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name="refund-policy",
        owner_user_id=owner_user_id,
        visibility=visibility,
        enabled=True,
    )


def _finding(**overrides) -> Finding:
    defaults = {
        "organization_id": uuid.uuid4(),
        "agent_slug": "support",
        "agent_name": "Support",
        "version_number": 3,
        "published_by_user_id": uuid.uuid4(),
        "publisher_email": "a@example.com",
        "skill_id": uuid.uuid4(),
        "skill_name": "refund-policy",
        "specialist": None,
        "status": BindingStatus.EXPOSED,
    }
    defaults.update(overrides)
    return Finding(**defaults)


class TestBindings:
    def test_the_agents_own_skill_ids_are_returned(self):
        sid = uuid.uuid4()
        spec = AgentSpec(name="Support", skill_ids=[sid])
        assert _bindings(spec) == [sweep.SkillBinding(skill_id=sid, specialist=None)]

    def test_an_inline_specialists_skill_ids_are_found_too(self):
        """The half of the check easy to forget: a specialist carries its own
        skill_ids inside the delegation capability's config."""
        own = uuid.uuid4()
        buried = uuid.uuid4()
        spec = AgentSpec(
            name="Boss",
            skill_ids=[own],
            capabilities=[
                CapabilityBindingSpec(
                    id="subagents",
                    config={
                        "inline": [
                            {
                                "name": "researcher",
                                "description": "researches a topic",
                                "instructions": "do research",
                                "skill_ids": [str(buried)],
                            }
                        ]
                    },
                )
            ],
        )
        bindings = _bindings(spec)
        assert sweep.SkillBinding(skill_id=own, specialist=None) in bindings
        assert sweep.SkillBinding(skill_id=buried, specialist="researcher") in bindings

    def test_a_delegation_config_that_does_not_parse_is_skipped(self):
        """The capability would not build from an unparsable config, so those
        specialists never run and lend nothing - the top-level bindings are still
        returned rather than the whole spec being abandoned."""
        own = uuid.uuid4()
        spec = AgentSpec(
            name="Boss",
            skill_ids=[own],
            capabilities=[CapabilityBindingSpec(id="subagents", config={"inline": "not-a-list"})],
        )
        assert _bindings(spec) == [sweep.SkillBinding(skill_id=own, specialist=None)]

    def test_a_disabled_delegation_binding_contributes_nothing(self):
        """A switched-off capability is not built, so `delegation_binding` returns
        nothing and its specialists are not walked."""
        own = uuid.uuid4()
        spec = AgentSpec(
            name="Boss",
            skill_ids=[own],
            capabilities=[
                CapabilityBindingSpec(
                    id="subagents",
                    enabled=False,
                    config={
                        "inline": [
                            {
                                "name": "researcher",
                                "description": "researches a topic",
                                "instructions": "do research",
                                "skill_ids": [str(uuid.uuid4())],
                            }
                        ]
                    },
                )
            ],
        )
        assert _bindings(spec) == [sweep.SkillBinding(skill_id=own, specialist=None)]


class TestClassify:
    @pytest.mark.anyio
    async def test_an_org_visible_skill_is_fine_whoever_published_it(self):
        """Readable by every member, so who published the spec never mattered -
        and still does not, even with no publisher at all."""
        skill = _skill(visibility=Visibility.ORG.value)
        assert (
            await _classify(
                MagicMock(), organization_id=uuid.uuid4(), publisher_id=None, skill=skill
            )
            is None
        )

    @pytest.mark.anyio
    async def test_a_private_skill_with_no_publisher_is_unknown_not_a_guess(self):
        skill = _skill(visibility=Visibility.PRIVATE.value)
        status = await _classify(
            MagicMock(), organization_id=uuid.uuid4(), publisher_id=None, skill=skill
        )
        assert status is BindingStatus.UNKNOWN

    @pytest.mark.anyio
    async def test_a_skill_the_publisher_owns_is_reachable(self):
        publisher = uuid.uuid4()
        skill = _skill(owner_user_id=publisher)
        assert (
            await _classify(
                MagicMock(), organization_id=uuid.uuid4(), publisher_id=publisher, skill=skill
            )
            is None
        )

    @pytest.mark.anyio
    async def test_a_grant_to_the_publisher_makes_it_reachable(self):
        skill = _skill(owner_user_id=uuid.uuid4())
        with patch.object(
            sweep.resource_grant_repo,
            "get_level",
            new=AsyncMock(return_value=GrantLevel.READ),
        ):
            status = await _classify(
                MagicMock(), organization_id=uuid.uuid4(), publisher_id=uuid.uuid4(), skill=skill
            )
        assert status is None

    @pytest.mark.anyio
    async def test_a_private_skill_owned_by_someone_else_with_no_grant_is_exposed(self):
        skill = _skill(owner_user_id=uuid.uuid4())
        with patch.object(sweep.resource_grant_repo, "get_level", new=AsyncMock(return_value=None)):
            status = await _classify(
                MagicMock(), organization_id=uuid.uuid4(), publisher_id=uuid.uuid4(), skill=skill
            )
        assert status is BindingStatus.EXPOSED


class TestFindingsFor:
    def _version(self, spec: AgentSpec, *, publisher: uuid.UUID | None):
        return SimpleNamespace(
            version=2, published_by_user_id=publisher, spec=spec.model_dump(mode="json")
        )

    def _agent(self):
        return SimpleNamespace(organization_id=uuid.uuid4(), slug="support", name="Support")

    @pytest.mark.anyio
    async def test_a_reachable_binding_produces_no_finding(self):
        publisher = uuid.uuid4()
        skill = _skill(owner_user_id=publisher)
        spec = AgentSpec(name="Support", skill_ids=[skill.id])
        with patch.object(
            sweep.skill_repo, "get_many", new=AsyncMock(return_value={skill.id: skill})
        ):
            findings = await _findings_for(
                MagicMock(), self._agent(), self._version(spec, publisher=publisher)
            )
        assert findings == []

    @pytest.mark.anyio
    async def test_a_skill_the_org_does_not_return_is_a_dangling_reference_not_an_exposure(self):
        """Deleted, or another tenant's id: it loads nothing at run time, so the
        sweep leaves it to `resolve_for_agent` rather than reporting it."""
        spec = AgentSpec(name="Support", skill_ids=[uuid.uuid4()])
        with patch.object(sweep.skill_repo, "get_many", new=AsyncMock(return_value={})):
            findings = await _findings_for(
                MagicMock(), self._agent(), self._version(spec, publisher=uuid.uuid4())
            )
        assert findings == []

    @pytest.mark.anyio
    async def test_a_disabled_skill_is_not_an_exposure(self):
        """`resolve_for_agent` skips a disabled skill, so no run receives it -
        reporting it would fail the audit over something nothing loads."""
        skill = _skill(owner_user_id=uuid.uuid4())
        skill.enabled = False
        spec = AgentSpec(name="Support", skill_ids=[skill.id])
        get_level = AsyncMock()
        with (
            patch.object(
                sweep.skill_repo, "get_many", new=AsyncMock(return_value={skill.id: skill})
            ),
            patch.object(sweep.resource_grant_repo, "get_level", new=get_level),
        ):
            findings = await _findings_for(
                MagicMock(), self._agent(), self._version(spec, publisher=uuid.uuid4())
            )
        assert findings == []
        get_level.assert_not_awaited()

    @pytest.mark.anyio
    async def test_an_exposed_binding_is_reported_with_the_publishers_email(self):
        publisher = uuid.uuid4()
        skill = _skill(owner_user_id=uuid.uuid4())
        spec = AgentSpec(name="Support", skill_ids=[skill.id])
        with (
            patch.object(
                sweep.skill_repo, "get_many", new=AsyncMock(return_value={skill.id: skill})
            ),
            patch.object(sweep.resource_grant_repo, "get_level", new=AsyncMock(return_value=None)),
            patch.object(
                sweep.member_repo,
                "get_emails_for_users",
                new=AsyncMock(return_value={publisher: "author@example.com"}),
            ),
        ):
            findings = await _findings_for(
                MagicMock(), self._agent(), self._version(spec, publisher=publisher)
            )
        assert len(findings) == 1
        assert findings[0].status is BindingStatus.EXPOSED
        assert findings[0].publisher_email == "author@example.com"

    @pytest.mark.anyio
    async def test_a_spec_with_no_skill_bindings_needs_no_skill_query(self):
        spec = AgentSpec(name="Support")
        get_many = AsyncMock()
        with patch.object(sweep.skill_repo, "get_many", new=get_many):
            findings = await _findings_for(
                MagicMock(), self._agent(), self._version(spec, publisher=uuid.uuid4())
            )
        assert findings == []
        get_many.assert_not_awaited()

    @pytest.mark.anyio
    async def test_a_publisher_who_left_the_org_resolves_to_no_email(self):
        """User row present, membership gone: the batch is org-scoped, so it
        returns no email and the finding shows the id instead."""
        publisher = uuid.uuid4()
        skill = _skill(owner_user_id=uuid.uuid4())
        spec = AgentSpec(name="Support", skill_ids=[skill.id])
        with (
            patch.object(
                sweep.skill_repo, "get_many", new=AsyncMock(return_value={skill.id: skill})
            ),
            patch.object(sweep.resource_grant_repo, "get_level", new=AsyncMock(return_value=None)),
            patch.object(sweep.member_repo, "get_emails_for_users", new=AsyncMock(return_value={})),
        ):
            findings = await _findings_for(
                MagicMock(), self._agent(), self._version(spec, publisher=publisher)
            )
        assert findings[0].publisher_email is None

    @pytest.mark.anyio
    async def test_an_unknown_finding_does_not_look_up_an_email(self):
        """The publisher is gone, so there is nobody to resolve; the member query
        is skipped entirely."""
        skill = _skill(visibility=Visibility.PRIVATE.value)
        spec = AgentSpec(name="Support", skill_ids=[skill.id])
        emails = AsyncMock()
        with (
            patch.object(
                sweep.skill_repo, "get_many", new=AsyncMock(return_value={skill.id: skill})
            ),
            patch.object(sweep.member_repo, "get_emails_for_users", new=emails),
        ):
            findings = await _findings_for(
                MagicMock(), self._agent(), self._version(spec, publisher=None)
            )
        assert findings[0].status is BindingStatus.UNKNOWN
        emails.assert_not_awaited()


class TestExecutableVersions:
    def _pair(self, spec: dict | None = None, *, status: str = AgentStatus.PUBLISHED.value):
        agent = SimpleNamespace(
            organization_id=uuid.uuid4(), slug=uuid.uuid4().hex[:6], name="A", status=status
        )
        version = SimpleNamespace(
            id=uuid.uuid4(),
            version=1,
            published_by_user_id=uuid.uuid4(),
            spec=spec or {"name": "A"},
        )
        return agent, version

    @pytest.mark.anyio
    async def test_it_unions_current_and_named_environment_pins_without_duplicates(self):
        """The default environment is `current_version_id`, so it shows up in both
        seeds - it must be counted once."""
        current = self._pair()
        named = self._pair()
        with (
            patch.object(
                sweep.agent_repo,
                "list_current_versions",
                new=AsyncMock(return_value=[current]),
            ),
            patch.object(
                sweep.agent_repo,
                "list_environment_versions",
                new=AsyncMock(return_value=[current, named]),
            ),
            patch.object(
                sweep.agent_repo, "get_versions_with_agents", new=AsyncMock(return_value=[])
            ),
        ):
            found = await sweep._executable_versions(MagicMock())
        assert sorted(v.id for _, v in found) == sorted({current[1].id, named[1].id})

    @pytest.mark.anyio
    async def test_it_follows_a_pinned_delegate_version_a_named_environment_reaches(self):
        """The delegate version is reachable only through the parent's pin, not
        through any environment of its own."""
        delegate = self._pair()
        parent = self._pair(
            {
                "name": "Parent",
                "subagents": [
                    {"agent_id": str(uuid.uuid4()), "agent_version_id": str(delegate[1].id)}
                ],
            }
        )
        with (
            patch.object(
                sweep.agent_repo, "list_current_versions", new=AsyncMock(return_value=[parent])
            ),
            patch.object(
                sweep.agent_repo, "list_environment_versions", new=AsyncMock(return_value=[])
            ),
            patch.object(
                sweep.agent_repo,
                "get_versions_with_agents",
                new=AsyncMock(side_effect=[[delegate], []]),
            ),
        ):
            found = await sweep._executable_versions(MagicMock())
        assert delegate[1].id in {v.id for _, v in found}

    @pytest.mark.anyio
    async def test_a_pin_to_an_already_seen_version_does_not_loop(self):
        """A pins B and B pins A: the closure must terminate, each seen once."""
        a = self._pair()
        b = self._pair()
        a[1].spec = {
            "name": "A",
            "subagents": [{"agent_id": str(uuid.uuid4()), "agent_version_id": str(b[1].id)}],
        }
        b[1].spec = {
            "name": "B",
            "subagents": [{"agent_id": str(uuid.uuid4()), "agent_version_id": str(a[1].id)}],
        }

        async def _resolve(_db, ids):
            return [b] if b[1].id in ids else [a] if a[1].id in ids else []

        with (
            patch.object(
                sweep.agent_repo, "list_current_versions", new=AsyncMock(return_value=[a])
            ),
            patch.object(
                sweep.agent_repo, "list_environment_versions", new=AsyncMock(return_value=[])
            ),
            patch.object(
                sweep.agent_repo, "get_versions_with_agents", new=AsyncMock(side_effect=_resolve)
            ),
        ):
            found = await sweep._executable_versions(MagicMock())
        assert sorted(v.id for _, v in found) == sorted({a[1].id, b[1].id})

    @pytest.mark.anyio
    async def test_a_pin_to_an_archived_delegate_is_dropped(self):
        """The runner refuses to delegate to an archived agent, so its pinned
        version can no longer load through the pin - flagging it would report a
        binding no run can reach."""
        delegate = self._pair(status=AgentStatus.ARCHIVED.value)
        parent = self._pair(
            {
                "name": "Parent",
                "subagents": [
                    {"agent_id": str(uuid.uuid4()), "agent_version_id": str(delegate[1].id)}
                ],
            }
        )
        with (
            patch.object(
                sweep.agent_repo, "list_current_versions", new=AsyncMock(return_value=[parent])
            ),
            patch.object(
                sweep.agent_repo, "list_environment_versions", new=AsyncMock(return_value=[])
            ),
            patch.object(
                sweep.agent_repo,
                "get_versions_with_agents",
                new=AsyncMock(return_value=[delegate]),
            ),
        ):
            found = await sweep._executable_versions(MagicMock())
        assert delegate[1].id not in {v.id for _, v in found}


class TestScan:
    @pytest.mark.anyio
    async def test_it_reports_a_finding_from_every_executable_version(self):
        agent_a = SimpleNamespace(organization_id=uuid.uuid4(), slug="a", name="A")
        agent_b = SimpleNamespace(organization_id=uuid.uuid4(), slug="b", name="B")
        version_a = SimpleNamespace(id=uuid.uuid4(), version=1, published_by_user_id=uuid.uuid4())
        version_b = SimpleNamespace(id=uuid.uuid4(), version=1, published_by_user_id=uuid.uuid4())
        with (
            patch.object(
                sweep,
                "_executable_versions",
                new=AsyncMock(return_value=[(agent_a, version_a), (agent_b, version_b)]),
            ),
            patch.object(
                sweep, "_findings_for", new=AsyncMock(side_effect=[[_finding()], [_finding()]])
            ),
        ):
            findings = await _scan(MagicMock())
        assert len(findings) == 2


class TestRenderHelpers:
    def test_a_deleted_publisher_is_named_unknown(self):
        assert "unknown" in _publisher(_finding(published_by_user_id=None))

    def test_a_departed_member_is_shown_by_id(self):
        pid = uuid.uuid4()
        assert str(pid) in _publisher(_finding(published_by_user_id=pid, publisher_email=None))

    def test_a_current_member_is_shown_by_email(self):
        assert _publisher(_finding(publisher_email="a@b.c")) == "a@b.c"

    def test_a_top_level_binding_names_the_agents_skill_ids(self):
        assert _location(_finding(specialist=None)) == "agent skill_ids"

    def test_a_specialist_binding_names_the_specialist(self):
        assert _location(_finding(specialist="researcher")) == "specialist 'researcher'"

    def test_a_line_carries_the_agent_the_skill_and_where_it_sits(self):
        line = _line(_finding(agent_slug="support", skill_name="refund-policy"))
        assert "support" in line
        assert "refund-policy" in line


class TestReport:
    def test_a_clean_deployment_reports_nothing_and_fails_nothing(self):
        assert _report([]) == 0

    def test_the_exposure_count_is_the_exit_code(self):
        findings = [_finding(status=BindingStatus.EXPOSED), _finding(status=BindingStatus.EXPOSED)]
        assert _report(findings) == 2

    def test_unknowns_are_reported_but_do_not_fail_the_run(self):
        assert _report([_finding(status=BindingStatus.UNKNOWN)]) == 0

    def test_both_kinds_are_reported_together(self):
        findings = [
            _finding(status=BindingStatus.EXPOSED),
            _finding(status=BindingStatus.UNKNOWN),
        ]
        assert _report(findings) == 1


class TestRun:
    @staticmethod
    def _db_context(db):
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def context():
            yield db

        return context

    @pytest.mark.anyio
    async def test_it_scans_within_a_database_session_and_returns_the_exposure_count(self):
        with (
            patch.object(sweep, "get_db_context", self._db_context(MagicMock())),
            patch.object(
                sweep, "_scan", new=AsyncMock(return_value=[_finding(status=BindingStatus.EXPOSED)])
            ),
        ):
            assert await _run() == 1


class TestEntryPoint:
    def test_it_exits_non_zero_when_an_exposure_is_found(self):
        from click.testing import CliRunner

        with patch.object(sweep.asyncio, "run", return_value=2):
            result = CliRunner().invoke(audit_skill_bindings, [])
        assert result.exit_code == 1

    def test_it_exits_zero_when_nothing_is_exposed(self):
        from click.testing import CliRunner

        with patch.object(sweep.asyncio, "run", return_value=0):
            result = CliRunner().invoke(audit_skill_bindings, [])
        assert result.exit_code == 0
