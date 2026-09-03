"""The agent-template reader - what it accepts, and what it refuses to guess.

A template folder is read once per process and never validated again, so every
refusal here is one somebody meets while the manifest is still in front of them
rather than at publish, weeks later, in an organization that installed it.
"""

import pytest

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
