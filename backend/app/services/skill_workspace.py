"""Skills as files in the workspace, and what the agent writes back.

Until now a skill reached the model only through `load_skill`, as text in the
conversation. That is enough to *read* a checklist and not enough to use one: a
skill whose resource is `reconcile.py` was handing an agent a script it could
quote and not run, while the same agent had a shell one tool call away.

So when a run has both skills and a workspace, the skills are also files:

    /skills/<name>/SKILL.md      the body, with its name and description
    /skills/<name>/<resource>    each resource, beside it

`SKILL.md` is the format `pydantic-ai-skills` already reads, and the frontmatter
is parsed with that library's own parser rather than a second one of ours - two
parsers for one format is how a skill starts meaning different things in two
places.

**No second way to run things.** There is deliberately no `run_skill_script`
here. The sandbox already has `execute`, with the workspace's permission rules
and the operator's ceilings behind it; a second execution path would be a second
set of rules to get wrong. Putting the script on disk is the whole feature - the
agent runs it with the shell it already has.

**Writes come back as proposals, not as edits.** `collect_changes` reports what
differs from what was written; `SkillProposalService` turns that into something a
person accepts. See `app/db/models/skill_proposal.py` for why that indirection
is not ceremony.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai_backends import BackendProtocol
from pydantic_ai_skills._parsing import parse_skill_md

from app.db.models.skill import Skill

logger = logging.getLogger(__name__)

SKILLS_ROOT = "/skills"
BODY_FILE = "SKILL.md"

# A ceiling on what one turn may propose, per file. Skills are instructions and
# checklists measured in kilobytes; a megabyte of them is a model that has lost
# the thread, and storing it would put that in a reviewer's browser.
MAX_PROPOSED_BYTES = 256 * 1024


@dataclass(frozen=True)
class SkillChange:
    """One skill the agent left different from how it found it."""

    name: str
    """The directory name, which is the skill's handle."""

    skill_id: Any | None
    """The stored skill this edits, or `None` for one the agent created."""

    description: str
    content: str
    resources: dict[str, str]

    @property
    def is_new(self) -> bool:
        return self.skill_id is None


@dataclass
class MaterialisedSkills:
    """What was written, so what the agent changed can be told apart from it."""

    #: `path -> content`, exactly as written.
    written: dict[str, str] = field(default_factory=dict)
    #: `directory name -> skill id`, for attributing a change back to a row.
    owners: dict[str, Any] = field(default_factory=dict)


def skill_dir(name: str) -> str:
    return f"{SKILLS_ROOT}/{name}"


def render_body(skill: Skill) -> str:
    """The skill as `SKILL.md`, in the format the library parses.

    The name and description are in the frontmatter rather than implied by the
    directory, because they are what the agent edits when it improves a skill's
    one-line summary - and a summary is the only thing other agents read before
    deciding whether to load the body at all.
    """
    return f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n\n{skill.content}\n"


def materialise(backend: BackendProtocol, skills: list[Skill]) -> MaterialisedSkills:
    """Write each skill into the workspace, and remember what was written.

    Never raises. A workspace that refuses a write - past its storage ceiling,
    holding a path the backend rejects - must not stop the run: the skills are
    still in the prompt, which is how they worked before this existed.
    """
    state = MaterialisedSkills()
    for skill in skills:
        state.owners[skill.name] = skill.id
        files = {f"{skill_dir(skill.name)}/{BODY_FILE}": render_body(skill)}
        for resource in skill.resources:
            files[f"{skill_dir(skill.name)}/{resource.name}"] = resource.content
        for path, content in files.items():
            if _write(backend, path, content):
                state.written[path] = content
    return state


def _write(backend: BackendProtocol, path: str, content: str) -> bool:
    """Whether the file made it. A refusal is logged rather than raised."""
    try:
        result = backend.write(path, content)
    except Exception:
        logger.warning("skill_materialise_failed", extra={"path": path}, exc_info=True)
        return False
    error = getattr(result, "error", None)
    if error:
        logger.warning("skill_materialise_refused", extra={"path": path, "reason": error})
        return False
    return True


def collect_changes(backend: BackendProtocol, state: MaterialisedSkills) -> list[SkillChange]:
    """What the agent left under `/skills` that is not what was put there.

    Compared against what this run wrote rather than against the database: the
    workspace may be older than this turn - a conversation-scoped one carries
    yesterday's files - and diffing against the rows would re-propose every
    change the reviewer already discarded, every turn, forever.

    A deleted file is deliberately not a change. Removing a resource is the one
    edit whose intent cannot be read off the workspace: a model that never
    touched the file and one that meant to delete it leave the same absence, and
    guessing wrong silently drops organizational know-how.
    """
    try:
        present = _read_tree(backend)
    except Exception:
        # A remote workspace that cannot be listed is a run that proposes
        # nothing, which is the same as one that changed nothing.
        logger.warning("skill_collect_failed", exc_info=True)
        return []

    changes: list[SkillChange] = []
    for name, files in _by_skill(present).items():
        if files == {
            path: content for path, content in state.written.items() if _skill_of(path) == name
        }:
            continue
        change = _to_change(name, files, state.owners.get(name))
        if change is not None:
            changes.append(change)
    return changes


def _read_tree(backend: BackendProtocol) -> dict[str, str]:
    """Every file under `/skills`, by path.

    Oversized files are dropped rather than truncated: half a script is not a
    script, and storing it as a proposal would offer a reviewer something that
    cannot be right.
    """
    tree: dict[str, str] = {}
    for entry in backend.glob_info(f"{SKILLS_ROOT}/**/*"):
        path = entry["path"]
        if entry.get("is_dir"):
            continue
        # `or 0`, not a default on `get`: `size` is `int | None` and a listing that
        # carries the key with `None` - a host that did not measure the file - would
        # otherwise compare `None` to an int and raise inside the ingestion of a
        # skill proposal.
        if (entry.get("size") or 0) > MAX_PROPOSED_BYTES:
            logger.warning("skill_proposal_too_large", extra={"path": path})
            continue
        # `read_bytes`, not `read`: the toolset's `read` numbers lines for a
        # model to quote, and a proposal built from that would store the line
        # numbers as part of the skill.
        tree[path] = backend.read_bytes(path).decode("utf-8", errors="replace")
    return tree


def _skill_of(path: str) -> str | None:
    """The directory a path sits in, which is the skill's name.

    `None` for anything not exactly one level deep. A skill is a directory of
    files; nesting is not part of the format, and treating `/skills/a/b/c` as
    belonging to `a` would flatten two files onto one name.
    """
    rest = path[len(SKILLS_ROOT) + 1 :] if path.startswith(f"{SKILLS_ROOT}/") else ""
    parts = [part for part in rest.split("/") if part]
    return parts[0] if len(parts) == 2 else None


def _by_skill(tree: dict[str, str]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    for path, content in tree.items():
        name = _skill_of(path)
        if name is None:
            continue
        grouped.setdefault(name, {})[path] = content
    return grouped


def _to_change(name: str, files: dict[str, str], skill_id: Any | None) -> SkillChange | None:
    """One skill's files as a proposal, or `None` if they are not a skill.

    A directory with no `SKILL.md` is refused rather than filled in: the body is
    the skill, and inventing an empty one would propose replacing real
    instructions with nothing.
    """
    body_path = f"{skill_dir(name)}/{BODY_FILE}"
    body = files.get(body_path)
    if body is None:
        logger.info("skill_change_without_body", extra={"skill": name})
        return None

    try:
        frontmatter, instructions = parse_skill_md(body)
    except ValueError:
        # Malformed frontmatter the model wrote. Refused rather than guessed at,
        # because the description is what every other agent reads first.
        logger.warning("skill_frontmatter_unparsable", extra={"skill": name})
        return None

    return SkillChange(
        name=name,
        skill_id=skill_id,
        description=str(frontmatter.get("description") or ""),
        content=instructions,
        resources={
            path.rsplit("/", 1)[1]: content for path, content in files.items() if path != body_path
        },
    )
