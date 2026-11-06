"""Three-way merging of shipped prompts and tools, independent of model choice."""

import json
from functools import cache
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, JsonValue

from app.agents.spec import AgentSpec

type DefaultField = Literal[
    "instructions", "capabilities", "mcp_servers", "skill_ids", "starters", "subagents"
]
FIELDS: tuple[DefaultField, ...] = (
    "instructions",
    "capabilities",
    "mcp_servers",
    "skill_ids",
    "starters",
    "subagents",
)
ARCHITECT = "general/platform-assistant"
STARTER = "general/agenticos"


def digest(value: JsonValue) -> str:
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fingerprint(spec: AgentSpec, field: DefaultField) -> str:
    value = spec.model_dump(mode="json")[field]
    if field == "instructions":
        return sha256(spec.instructions.strip().encode()).hexdigest()
    return digest(value)


def baseline(key: str, spec: AgentSpec) -> dict[str, str]:
    return {"key": key, **{field: fingerprint(spec, field) for field in FIELDS}}


def previous_fingerprint(previous: dict[str, str], field: DefaultField) -> str | None:
    # Older tracked releases had no shipped delegate pins; custom pins stay protected.
    return previous.get(field, digest([]) if field == "subagents" else None)


def merge_defaults(spec: AgentSpec, target: AgentSpec, previous: dict[str, str]) -> AgentSpec:
    """Refresh each untouched field; a custom prompt does not authorize changing it."""
    update = {
        field: target.model_dump()[field]
        for field in FIELDS
        if fingerprint(spec, field) == previous_fingerprint(previous, field)
    }
    return AgentSpec.model_validate({**spec.model_dump(), **update})


class LegacyDefaults(BaseModel):
    instructions: str
    instruction_variants: list[str] = Field(default_factory=list)
    capabilities: list[dict[str, JsonValue]]
    mcp_servers: list[dict[str, JsonValue]]
    skills: list[str]
    starters: list[str]

    def recognizes_prompt(self, value: str) -> bool:
        return value == self.instructions or value in self.instruction_variants


@cache
def legacy_defaults() -> dict[str, list[LegacyDefaults]]:
    path = Path(__file__).with_name("agent_defaults_history.json")
    # A release-owned artifact: malformed history is a build defect, not an empty baseline.
    from pydantic import TypeAdapter

    return TypeAdapter(dict[str, list[LegacyDefaults]]).validate_json(path.read_text())


@cache
def template_release(key: str, deployment: str) -> str:
    """A process ships immutable catalog files, including the guide's resources."""
    from app.services import agent_templates, skill_library

    template = agent_templates.get(key)
    if template is None:
        raise ValueError(f"Missing shipped agent template: {key}")
    skills = ";".join(
        f"{skill_key}:{entry.fingerprint}"
        for skill_key in template.skills
        if (entry := skill_library.get(skill_key) or skill_library.gallery_get(skill_key))
        is not None
    )
    return digest(
        {
            "manifest": (
                agent_templates.TEMPLATES_ROOT / key / agent_templates.MANIFEST
            ).read_text(),
            "deployment": deployment,
            "skills": skills,
            "library": {entry.key: entry.fingerprint for entry in skill_library.library()},
        }
    )
