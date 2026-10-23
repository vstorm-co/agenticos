"""The Architect's guide carries the documentation as it is, not as it was.

`scripts/gen_architect_guide.py` copies a handful of pages from `docs/` into the
`agenticos-guide` skill, because the backend image has no `docs/`. A copy that
drifted would have the Architect quote a command the page no longer gives.
"""

import importlib.util
from pathlib import Path

import pytest

from app.services import skill_library

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GENERATOR = REPO_ROOT / "scripts/gen_architect_guide.py"


@pytest.fixture(scope="module")
def gen():
    spec = importlib.util.spec_from_file_location("gen_architect_guide", GENERATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_copied_page_matches_its_source(gen) -> None:
    stale = [
        page for page in gen.PAGES if gen.target(page).read_text() != (gen.DOCS / page).read_text()
    ]
    assert stale == [], "run: python3 scripts/gen_architect_guide.py"


def test_the_skill_offers_every_copied_page_by_name(gen) -> None:
    skill = skill_library.gallery_get("software/agenticos-guide")
    assert skill is not None
    names = {resource.name for resource in skill.resources}
    for page in gen.PAGES:
        relative = str(gen.target(page).relative_to(gen.SKILL))
        assert relative in names
        # The map in SKILL.md points at the file the skill actually holds.
        assert f"`{relative}`" in skill.content


def test_the_architect_template_installs_the_guide() -> None:
    from app.services import agent_templates

    architect = agent_templates.get("general/platform-assistant")
    assert architect is not None
    assert "software/agenticos-guide" in architect.skills
