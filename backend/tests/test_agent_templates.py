"""The agent-template reader - what it accepts, and what it refuses to guess.

A template folder is read once per process and never validated again, so every
refusal here is one somebody meets while the manifest is still in front of them
rather than at publish, weeks later, in an organization that installed it.
"""

import re

import pytest

from app.core.config import settings
from app.services import agent_templates

pytestmark = pytest.mark.anyio


def _write(root, industry: str, key: str, body: str) -> None:
    folder = root / industry / key
    folder.mkdir(parents=True)
    (folder / agent_templates.MANIFEST).write_text(body, encoding="utf-8")


@pytest.fixture(autouse=True)
def _uncached():
    """The catalog is cached for the process; these tests move the root."""
    agent_templates.catalog.cache_clear()
    yield
    agent_templates.catalog.cache_clear()


class TestReadingTheCatalog:
    def test_a_missing_directory_is_a_warning_rather_than_a_crash(self, tmp_path, monkeypatch):
        """A deployment without the folder still starts; it just offers nothing."""
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path / "absent")

        assert agent_templates.catalog() == ()

    def test_loose_files_and_dot_folders_are_not_industries(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        (tmp_path / "README.md").write_text("not an industry", encoding="utf-8")
        (tmp_path / "_wip").mkdir()
        (tmp_path / "healthcare").mkdir()
        (tmp_path / "healthcare" / ".draft").mkdir()
        (tmp_path / "healthcare" / "notes.md").write_text("x", encoding="utf-8")
        _write(
            tmp_path, "healthcare", "desk", "---\nname: Desk\ndescription: d\n---\n\nYou answer.\n"
        )

        catalog = agent_templates.catalog()

        assert [i.id for i in catalog] == ["healthcare"]
        assert [t.key for t in catalog[0].templates] == ["healthcare/desk"]

    def test_an_industry_whose_templates_all_fail_is_dropped(self, tmp_path, monkeypatch):
        """An empty shelf is worse than no shelf - it looks like a bug in the UI."""
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        _write(tmp_path, "broken", "no-body", "---\nname: X\ndescription: d\n---\n\n")

        assert agent_templates.catalog() == ()

    def test_one_bad_manifest_does_not_cost_its_neighbours(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        _write(tmp_path, "healthcare", "bad", "---\nname: X\n---\n\nNo description.\n")
        _write(
            tmp_path, "healthcare", "good", "---\nname: Good\ndescription: d\n---\n\nYou answer.\n"
        )

        catalog = agent_templates.catalog()

        assert [t.key for t in catalog[0].templates] == ["healthcare/good"]

    def test_get_resolves_by_key(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        _write(tmp_path, "legal", "intake", "---\nname: Intake\ndescription: d\n---\n\nYou take.\n")

        assert agent_templates.get("legal/intake") is not None
        assert agent_templates.get("legal/missing") is None


class TestTheStarterTemplate:
    def test_its_bindings_are_keyed_by_capability(self, tmp_path, monkeypatch):
        """What the Toolbox recommends, and what a new agent starts with."""
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        # A deployment running its own sandbox service, so the binding is kept as
        # written; without one it falls back - see `TestForThisDeployment`.
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "token")
        folder, name = agent_templates.STARTER_TEMPLATE.split("/")
        _write(
            tmp_path,
            folder,
            name,
            "---\nname: Starter\ndescription: d\ncapabilities:\n- clock\n"
            "- id: sandbox\n  config:\n    include_execute: true\n---\n\nYou work.\n",
        )

        assert agent_templates.starter_capabilities() == {
            "clock": {"id": "clock"},
            "sandbox": {"id": "sandbox", "config": {"include_execute": True}},
        }

    def test_an_image_without_it_recommends_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)

        assert agent_templates.starter_capabilities() == {}

    def test_the_shipped_starter_binds_only_registered_capabilities(self):
        """A typo in the manifest would recommend a switch the Toolbox never shows."""
        from app.agents.capabilities import all_capabilities

        registered = {definition.id for definition in all_capabilities()}
        starter = agent_templates.starter_capabilities()

        assert starter
        assert set(starter) <= registered

    @pytest.mark.anyio
    async def test_the_capability_catalog_carries_the_starters_binding(self):
        """Marked Recommended in the Toolbox, config and all, and nothing else is."""
        from app.api.routes.v1.agents import list_capability_catalog

        catalog = await list_capability_catalog()
        starter = agent_templates.starter_capabilities()
        by_id = {entry.id: entry for entry in catalog.items}

        sandbox = by_id["sandbox"].recommended
        assert sandbox is not None
        assert sandbox.config == starter["sandbox"].get("config", {})
        assert by_id["guardrails"].recommended is None
        assert {i for i, e in by_id.items() if e.recommended} == set(starter) & set(by_id)


class TestForThisDeployment:
    """What a template cannot know - this deployment's browser and sandbox."""

    BINDINGS = (
        {"id": "browser_use", "config": {"max_steps": 20}},
        {"id": "sandbox", "config": {"backend": "service", "include_execute": True}},
        {"id": "clock"},
    )

    def test_its_own_browser_and_sandbox_are_used_where_it_runs_them(self, monkeypatch):
        monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "http://browser:9222")
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "token")

        assert agent_templates.for_this_deployment(self.BINDINGS) == [
            {"id": "browser_use", "config": {"max_steps": 20, "cdp_url": "http://browser:9222"}},
            {"id": "sandbox", "config": {"backend": "service", "include_execute": True}},
            {"id": "clock"},
        ]

    def test_without_them_the_browser_is_left_out_and_the_workspace_keeps_files(self, monkeypatch):
        """Either would refuse at publish, and the starter is every new agent's default."""
        monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "")
        monkeypatch.setattr(settings, "SANDBOXD_TOKEN", "")

        assert agent_templates.for_this_deployment(self.BINDINGS) == [
            {"id": "sandbox", "config": {"backend": "state"}},
            {"id": "clock"},
        ]

    def test_a_browser_the_template_names_is_kept(self, monkeypatch):
        monkeypatch.setattr(settings, "BROWSER_SIGN_IN_CDP_URL", "")
        named = ({"id": "browser_use", "config": {"cdp_url": "http://other:9222"}},)

        assert agent_templates.for_this_deployment(named) == list(named)


class TestWhatAManifestMayCarry:
    def test_the_folder_name_is_the_fallback_name(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        _write(tmp_path, "legal", "intake", "---\ndescription: d\n---\n\nYou take.\n")

        assert agent_templates.catalog()[0].templates[0].name == "intake"

    def test_a_binding_is_an_id_or_a_mapping_carrying_one(self, tmp_path, monkeypatch):
        """`- clock` is the readable form and `- {id: knowledge, config: ...}` the full one."""
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        _write(
            tmp_path,
            "legal",
            "intake",
            "---\nname: I\ndescription: d\ncapabilities:\n  - clock\n"
            "  - {id: knowledge, config: {default_top_k: 3}}\n"
            "skills:\n  - legal/matter-intake\nmcp:\n  - notion\nattach:\n  - collection\n"
            "budget_usd: 25\n---\n\nYou take.\n",
        )

        template = agent_templates.catalog()[0].templates[0]

        assert template.capabilities == (
            {"id": "clock"},
            {"id": "knowledge", "config": {"default_top_k": 3}},
        )
        assert template.skills == ("legal/matter-intake",)
        assert template.mcp == ("notion",)
        assert template.attach == ("collection",)
        assert template.budget_usd == 25.0

    def test_a_budget_that_is_not_a_number_is_dropped_rather_than_guessed(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        _write(
            tmp_path, "legal", "i", "---\nname: I\ndescription: d\nbudget_usd: soon\n---\n\nYou.\n"
        )

        assert agent_templates.catalog()[0].templates[0].budget_usd is None

    @pytest.mark.parametrize(
        "frontmatter",
        [
            "name: X\ndescription: d\ncapabilities: clock",
            "name: X\ndescription: d\ncapabilities:\n  - [nope]",
            "name: X\ndescription: d\nskills: healthcare/one",
        ],
        ids=["capabilities-not-a-list", "binding-without-an-id", "skills-not-a-list"],
    )
    def test_a_manifest_shaped_wrongly_is_skipped(self, tmp_path, monkeypatch, frontmatter):
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        _write(tmp_path, "legal", "i", f"---\n{frontmatter}\n---\n\nYou answer.\n")

        assert agent_templates.catalog() == ()


class TestMcpBindings:
    """A template may bind a server nobody has to authorise - the platform's own."""

    def test_bindings_are_carried_as_the_spec_takes_them(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        _write(
            tmp_path,
            "general",
            "architect",
            "---\nname: A\ndescription: d\nmcp_servers:\n- account: platform\n---\n\nYou help.\n",
        )

        [template] = agent_templates.catalog()[0].templates

        assert template.mcp_servers == ({"account": "platform"},)

    def test_a_binding_list_of_names_is_a_manifest_to_fix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(agent_templates, "TEMPLATES_ROOT", tmp_path)
        _write(
            tmp_path,
            "general",
            "architect",
            "---\nname: A\ndescription: d\nmcp_servers:\n- platform\n---\n\nYou help.\n",
        )

        assert agent_templates.catalog() == ()


class TestTheShippedClaudeCodeLikeAgent:
    @pytest.mark.security
    def test_it_reaches_the_platform_with_writes_held_for_approval(self):
        """A fresh agent from it answers questions about the platform out of the
        box, and asks before changing anything there (#2190)."""
        template = agent_templates.get("general/claude-code-like")

        assert template is not None
        assert {"account": "platform", "approval": "writes"} in template.mcp_servers


def _instruction_texts(value: object) -> list[str]:
    """Every `instructions` string under a template's bindings, at any depth."""
    if isinstance(value, dict):
        found = [v for k, v in value.items() if k == "instructions" and isinstance(v, str)]
        return found + [t for v in value.values() for t in _instruction_texts(v)]
    if isinstance(value, list | tuple):
        return [t for v in value for t in _instruction_texts(v)]
    return []


def _wrapped_lines(text: str) -> list[str]:
    """Lines that continue the sentence above them - a hard wrap, not a new block."""
    starts_block = ("- ", "* ", "+ ", "#", ">", "|", "```", "~~~")
    wrapped, fenced, previous = [], False, ""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            fenced = not fenced
        elif (
            not fenced
            and stripped
            and previous
            and not previous.startswith(("|", "#"))
            and not stripped.startswith(starts_block)
            and not re.match(r"\d+[.)] ", stripped)
        ):
            wrapped.append(stripped)
        previous = "" if fenced else stripped
    return wrapped


class TestShippedInstructions:
    """The catalog the product ships, read as an installed agent reads it."""

    def test_instructions_are_whole_paragraphs_not_80_column_lines(self):
        """The Builder's editor and the spec export show the text as written, so a
        template hard-wrapped for the repository arrived as a column of short
        lines in every agent installed from it."""
        offenders = {
            template.key: lines
            for industry in agent_templates.catalog()
            for template in industry.templates
            for text in [template.instructions, *_instruction_texts(template.capabilities)]
            if (lines := _wrapped_lines(text))
        }

        assert offenders == {}
