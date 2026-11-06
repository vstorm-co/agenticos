"""Long references are read in bounded ranges rather than filling every model request."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.agents.capabilities.skills._capability import _resource_content, to_toolkit_skill
from app.db.models.skill import Skill, SkillResource

pytestmark = pytest.mark.anyio


def test_small_resources_keep_their_content_and_long_references_expose_next_offset() -> None:
    assert _resource_content("") == ""
    assert _resource_content("small") == "small"
    body = "a" * 8000 + "b" * 3000
    read = _resource_content(body)
    assert callable(read)
    first = read(0, 8000)
    assert '"offset":8000' in first and first.endswith("a" * 8000)
    assert read(8000, 8000).endswith("b" * 3000)
    assert read(len(body), 8000).startswith("End of resource")


async def test_the_skills_sdk_validates_page_arguments_and_loads_the_selected_range() -> None:
    skill = MagicMock(spec=Skill)
    skill.id = uuid4()
    skill.name = "reference"
    skill.description = "A long reference"
    skill.content = "Use its resource."
    resource = MagicMock(spec=SkillResource)
    resource.name = "guide.md"
    resource.description = "Reference"
    resource.content = "a" * 8000 + "target section"
    skill.resources = [resource]
    converted = to_toolkit_skill(skill)
    ctx = RunContext(deps=None, model=TestModel(), usage=RunUsage())
    content = await converted.resources[0].load(ctx, {"offset": 8000, "limit": 2000})
    assert isinstance(content, str) and content.endswith("target section")
    first = await converted.resources[0].load(ctx)
    assert isinstance(first, str) and len(first) < 8200 and "target section" not in first
    with pytest.raises(ModelRetry):
        await converted.resources[0].load(ctx, {"offset": -1})
