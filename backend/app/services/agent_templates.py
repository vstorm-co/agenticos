"""The agent templates this platform ships with, read off disk.

A template is what a skill folder is, one level up: `AGENT.md` carries the
name, description and the assembly in YAML frontmatter, and the body below it is
the agent's instructions. Same shape and the same parser as the
[skill gallery][app.services.skill_library], for the same reason - the format a
thing is stored in should be the format somebody reads it in.

**What a template cannot carry is the whole difficulty.** An `AgentSpec` names
its skills, collections, context files and MCP servers by UUID, and a folder
shipped in an image knows none of them. So a template names skills by their
*gallery key*, MCP servers by their *catalog key*, and says which things a person
has to attach themselves. Installing resolves what it can and leaves the rest
visible rather than guessing.

Which is also why an installed template is a **draft**. An agent whose knowledge
collection has not been attached yet would answer its first question from the
model's own memory, confidently and from nowhere - so the last step is a person
reading the instructions and pressing Publish.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from app.services.skill_library import split_frontmatter

logger = logging.getLogger(__name__)

TEMPLATES_ROOT = Path(__file__).resolve().parent.parent / "core" / "catalog" / "agent_templates"

MANIFEST = "AGENT.md"


@dataclass(frozen=True, slots=True)
class AgentTemplate:
    """One folder under an industry - an agent somebody can start from."""

    key: str
    """`<industry>/<folder>`, how an install request names it."""

    name: str
    description: str
    instructions: str

    capabilities: tuple[dict[str, Any], ...]
    """Capability bindings, as the spec takes them. Ids only - code registered them."""

    skills: tuple[str, ...] = ()
    """Gallery keys this agent expects. Installed with it, if missing."""

    mcp: tuple[str, ...] = ()
    """Catalog keys worth connecting. Suggestions - a connection needs somebody to authorise it."""

    attach: tuple[str, ...] = ()
    """What a person still has to provide: `collection`, `context`, `sandbox`."""

    budget_usd: float | None = None


@dataclass(frozen=True, slots=True)
class TemplateIndustry:
    """One directory under the templates root, and the templates in it."""

    id: str
    templates: tuple[AgentTemplate, ...] = field(default_factory=tuple)


@cache
def catalog() -> tuple[TemplateIndustry, ...]:
    """Every shipped template, grouped by the industry directory holding it.

    Cached for the process, like the skill library: the directory ships with the
    image and changes on redeploy rather than between requests. A folder that
    cannot be read is logged and skipped - one malformed manifest must not cost
    the industry it sits in.
    """
    if not TEMPLATES_ROOT.is_dir():
        logger.warning("Agent template directory is missing: %s", TEMPLATES_ROOT)
        return ()

    industries: list[TemplateIndustry] = []
    for folder in sorted(TEMPLATES_ROOT.iterdir()):
        if not folder.is_dir() or folder.name.startswith((".", "_")):
            continue
        templates: list[AgentTemplate] = []
        for entry in sorted(folder.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            try:
                templates.append(_read(entry, industry=folder.name))
            except Exception:
                logger.exception("Could not read the agent template in %s", entry)
        if templates:
            industries.append(TemplateIndustry(id=folder.name, templates=tuple(templates)))
    return tuple(industries)


def get(key: str) -> AgentTemplate | None:
    """One template by its `<industry>/<folder>` key."""
    return next(
        (t for industry in catalog() for t in industry.templates if t.key == key),
        None,
    )


def _read(folder: Path, *, industry: str) -> AgentTemplate:
    manifest = folder / MANIFEST
    metadata, body = split_frontmatter(manifest.read_text(encoding="utf-8"))

    instructions = body.strip()
    if not instructions:
        raise ValueError(f"{manifest} has no instructions, which is the whole of the agent")
    description = str(metadata.get("description") or "").strip()
    if not description:
        raise ValueError(f"{manifest} has no description, which is what the picker shows")

    capabilities = metadata.get("capabilities") or []
    if not isinstance(capabilities, list):
        raise TypeError(f"{manifest} has a `capabilities` that is not a list")

    budget = metadata.get("budget_usd")
    return AgentTemplate(
        key=f"{industry}/{folder.name}",
        name=str(metadata.get("name") or folder.name),
        description=description,
        instructions=instructions,
        capabilities=tuple(_binding(item) for item in capabilities),
        skills=_strings(metadata.get("skills")),
        mcp=_strings(metadata.get("mcp")),
        attach=_strings(metadata.get("attach")),
        budget_usd=float(budget) if isinstance(budget, int | float) else None,
    )


def _strings(value: Any) -> tuple[str, ...]:
    """A YAML list of names, or nothing. Anything else is a manifest to fix."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise TypeError(f"Expected a list of names, got {value!r}")
    return tuple(str(item) for item in value)


def _binding(item: Any) -> dict[str, Any]:
    """One capability binding, however the manifest wrote it.

    A bare string is the common case and the readable one, so `- clock` and
    `- {id: clock}` both mean the same thing. Validation of the id itself belongs
    to the spec, which refuses one the registry does not know at publish.
    """
    if isinstance(item, str):
        return {"id": item}
    if isinstance(item, dict) and "id" in item:
        return dict(item)
    raise TypeError(f"A capability binding must be an id or carry one: {item!r}")
