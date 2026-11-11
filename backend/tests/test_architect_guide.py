"""The Architect's guide carries the documentation as it is, not as it was.

`scripts/gen_architect_guide.py` copies a handful of pages from `docs/` into the
`agenticos-guide` skill, because the backend image has no `docs/`. A copy that
drifted would have the Architect quote a command the page no longer gives.
"""

import importlib.util
import sys
from pathlib import Path
from typing import Protocol, runtime_checkable

import pytest

from app.services import skill_library

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATOR = REPO_ROOT / "scripts/gen_architect_guide.py"


@runtime_checkable
class GuideGenerator(Protocol):
    PAGES: tuple[str, ...]
    ROOT: Path
    DOCS: Path
    SKILL: Path

    def target(self, page: str) -> Path: ...
    def render(self, page: str) -> str: ...
    def main(self) -> int: ...


@pytest.fixture(scope="module")
def gen() -> GuideGenerator:
    spec = importlib.util.spec_from_file_location("gen_architect_guide", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert isinstance(module, GuideGenerator)
    return module


def test_every_copied_page_matches_its_source(gen: GuideGenerator) -> None:
    stale = [
        page
        for page in gen.PAGES
        if gen.target(page).read_text(encoding="utf-8") != gen.render(page)
    ]
    assert stale == [], "run: python3 scripts/gen_architect_guide.py"


def test_a_link_the_copy_cannot_resolve_points_at_the_published_page(gen: GuideGenerator) -> None:
    """The skill carries a subset flat under `docs/`, so some links must leave."""
    rendered = gen.render("features.md")
    assert "](https://vstorm-co.github.io/agenticos/resources/" in rendered
    # A page the copy does carry stays a relative link.
    assert "](desktop.md" in rendered


def test_fresh_generation_is_the_same_as_regeneration(
    gen: GuideGenerator, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = {page: gen.render(page) for page in gen.PAGES}
    monkeypatch.setattr(gen, "ROOT", tmp_path)
    monkeypatch.setattr(gen, "SKILL", tmp_path / "empty-skill")
    monkeypatch.setattr(sys, "argv", [str(GENERATOR)])
    assert gen.main() == 0
    assert {page: gen.target(page).read_text(encoding="utf-8") for page in gen.PAGES} == expected
    monkeypatch.setattr(sys, "argv", [str(GENERATOR), "--check"])
    assert gen.main() == 0


@pytest.mark.parametrize(
    ("page", "source", "expected"),
    [
        ("features.md", "[API](api.md#keys)", "[API](api.md#keys)"),
        (
            "features.md",
            "[Glossary](reference/glossary.md#agent)",
            "[Glossary](reference-glossary.md#agent)",
        ),
        ("reference/glossary.md", "[Features](../features.md)", "[Features](features.md)"),
        (
            "reference/glossary.md",
            "[Capabilities](capabilities.md#budget)",
            "[Capabilities](https://vstorm-co.github.io/agenticos/reference/capabilities/#budget)",
        ),
        (
            "features.md",
            "[Resources](resources/index.md#help)",
            "[Resources](https://vstorm-co.github.io/agenticos/resources/#help)",
        ),
        (
            "features.md",
            "[Remote](https://example.org/guide.md#section)",
            "[Remote](https://example.org/guide.md#section)",
        ),
        ("features.md", "[Remote](//example.org/guide.md)", "[Remote](//example.org/guide.md)"),
        ("features.md", "`[Topic](topic.md)`", "`[Topic](topic.md)`"),
        (
            "features.md",
            "`" * 2 + "a ` [Topic](topic.md)" + "`" * 2,
            "`" * 2 + "a ` [Topic](topic.md)" + "`" * 2,
        ),
        (
            "features.md",
            "````markdown\n```text\n[Topic](topic.md)\n```\n````",
            "````markdown\n```text\n[Topic](topic.md)\n```\n````",
        ),
        (
            "features.md",
            "~~~markdown\n[Topic](topic.md)\n~~~",
            "~~~markdown\n[Topic](topic.md)\n~~~",
        ),
    ],
)
def test_links_resolve_from_the_source_page_without_generated_files(
    gen: GuideGenerator,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    page: str,
    source: str,
    expected: str,
) -> None:
    docs = tmp_path / "docs"
    path = docs / page
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(gen, "DOCS", docs)
    monkeypatch.setattr(gen, "SKILL", tmp_path / "empty-skill")
    assert gen.render(page) == expected


def test_the_skill_offers_every_copied_page_by_name(gen: GuideGenerator) -> None:
    skill = skill_library.gallery_get("software/agenticos-guide")
    assert skill is not None
    names = {resource.name for resource in skill.resources}
    for page in gen.PAGES:
        relative = str(gen.target(page).relative_to(gen.SKILL))
        assert relative in names
        # The map in SKILL.md points at the file the skill actually holds.
        assert f"`{relative}`" in skill.content


def test_the_architect_guide_remains_optional() -> None:
    from app.services import agent_templates

    architect = agent_templates.get("general/platform-assistant")
    assert architect is not None
    assert "software/agenticos-guide" not in architect.skills
    assert skill_library.gallery_get("software/agenticos-guide") is not None


def test_new_architect_templates_include_the_runtime_projects_guidance() -> None:
    from app.services import agent_templates

    architect = agent_templates.get("general/platform-assistant")
    assert architect is not None
    guidance = (
        agent_templates.TEMPLATES_ROOT / "general/platform-assistant/PROJECTS.md"
    ).read_text()
    assert guidance.strip() in architect.instructions


def test_architect_uses_curated_procedures_instead_of_duplicate_api_guides() -> None:
    from app.services import agent_templates

    architect = agent_templates.get("general/platform-assistant")
    assert architect is not None
    assert {"platform-workflows", "platform-automation"}.issubset(architect.skills)
    assert not {"software/workflow-builder", "software/virtual-tables", "platform-tables"} & set(
        architect.skills
    )
    for skill_id in ("software/workflow-builder", "software/virtual-tables"):
        assert skill_library.gallery_get(skill_id) is not None
    guidance = (
        agent_templates.TEMPLATES_ROOT / "general/platform-assistant/WORKFLOWS.md"
    ).read_text()
    assert guidance.strip() in architect.instructions
