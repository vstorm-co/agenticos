"""Skills as files in the workspace, and what the agent writes back.

A skill reaches the model as instructions it pulls in with `load_capability`, and
its files through `read_skill_resource`. That is enough to *read* a checklist and
not enough to use one: a skill whose resource is `reconcile.py` was handing an
agent a script it could quote and not run, while the same agent had a shell one
tool call away.

So when a run has both skills and a workspace, the skills are also files:

    /workspace/skills/<name>/SKILL.md      the body, with its name and description
    /workspace/skills/<name>/<resource>    each resource, beside it

`SKILL.md` is the Agent Skills format, and the frontmatter is read back with
`skill_library.split_frontmatter` - the same reader the bundled skill gallery and
the agent templates go through. One parser for one format is what keeps a skill
from meaning different things in two places; the shelf that reads `SKILL.md` off
disk is where it lives, and `pydantic-ai-skills` stopped publishing one of its
own at 2.0.

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

from pydantic_ai.workspaces import Workspace

from app.db.models.skill import Skill
from app.services.skill_library import split_frontmatter

logger = logging.getLogger(__name__)

# Inside the workspace, not beside it. The container runtimes run as an unprivileged user
# (`_image.py` refuses root), and `/` is root's: `mkdir -p /skills` fails with "Permission
# denied", every write is refused, and the agent that was promised its scripts on disk finds
# no /skills at all (2026-09-14, first live run of a skill with 81 resources). `/workspace` is
# the one directory every backend guarantees writable, so the skills live under it.
SKILLS_ROOT = "/workspace/skills"

LEGACY_SKILLS_ROOT = "/skills"
"""Where skills were written before they moved inside the workspace.

Nothing writes here. It is named so the two listing filters still recognise a
workspace that predates the move, and so a flush can drop that tree instead of
persisting a second copy of every skill beside the new one.
"""

RESERVED_SKILL_PREFIXES = ("workspace/skills/", "skills/")
"""Every spelling a materialised skill path arrives in, the leading slash stripped.

`workspace/skills/...` from a `state` backend and from a container that lists
absolute in-container paths; `skills/...` from a container that lists relative to
its own workspace root, and from a workspace written before the move. Matched
after `lstrip("/")` for the reason `_NOT_THE_AGENTS` documents: the two backends
disagree about the leading slash, so one spelling with the slash stripped at the
match is the only form that catches both.

Read by `channels.attachments` and `sandbox_workspace`, which is why it lives
beside the root rather than in either of them - a filter that knows a different
set of prefixes than the writer uses is how skill files reached a channel reply.
"""

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
    """The skill as `SKILL.md`, in the format `split_frontmatter` reads back.

    The name and description are in the frontmatter rather than implied by the
    directory, because they are what the agent edits when it improves a skill's
    one-line summary - and a summary is the only thing other agents read before
    deciding whether to load the body at all.
    """
    return f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n\n{skill.content}\n"


async def materialise(workspace: Workspace, skills: list[Skill]) -> MaterialisedSkills:
    """Write each skill into the workspace, and remember what was written.

    Never raises. A workspace that refuses a write - past its storage ceiling,
    holding a path the backend rejects - must not stop the run: the skills are
    still in the prompt, which is how they worked before this existed.

    Awaited, and that matters more here than anywhere else: this runs inside
    `prepare`, once per file per skill, before the model has seen a token - so on
    a container-backed workspace an agent with five skills and three resources
    each pays fifteen round trips before its first word, and they must not block
    the event loop.
    """
    state = MaterialisedSkills()
    for skill in skills:
        state.owners[skill.name] = skill.id
        files = {f"{skill_dir(skill.name)}/{BODY_FILE}": render_body(skill)}
        for resource in skill.resources:
            files[f"{skill_dir(skill.name)}/{resource.name}"] = resource.content
        for path, content in files.items():
            if await _write(workspace, path, content):
                state.written[path] = content
    return state


async def _write(workspace: Workspace, path: str, content: str) -> bool:
    """Whether the file made it. A refusal is logged rather than raised."""
    try:
        await workspace.write_text(path, content)
    except OSError as refused:
        # The workspace said no - past its storage ceiling, a path it rejects.
        logger.warning("skill_materialise_refused", extra={"path": path, "reason": str(refused)})
        return False
    except Exception:
        logger.warning("skill_materialise_failed", extra={"path": path}, exc_info=True)
        return False
    return True


async def collect_changes(workspace: Workspace, state: MaterialisedSkills) -> list[SkillChange]:
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
        present = await _read_tree(workspace)
    except Exception:
        # A remote workspace that cannot be listed is a run that proposes
        # nothing, which is the same as one that changed nothing.
        logger.warning("skill_collect_failed", exc_info=True)
        return []

    changes: list[SkillChange] = []
    for name, files in present.items():
        if files == {
            path: content for path, content in state.written.items() if _skill_of(path) == name
        }:
            continue
        change = _to_change(name, files, state.owners.get(name))
        if change is not None:
            changes.append(change)
    return changes


async def _read_tree(workspace: Workspace) -> dict[str, dict[str, str]]:
    """Every file one level inside a skill's directory under `SKILLS_ROOT`, by skill and path.

    Two levels and no further, because that is the format: a skill is a directory
    of files, and `_skill_of` reads nothing deeper. Listed rather than globbed, so a
    dot-prefixed resource - a `.gitignore` the agent gave a skill - is in the
    proposal like any other file; a proposal is supposed to be everything the
    agent left different.

    Oversized files are dropped rather than truncated: half a script is not a
    script, and storing it as a proposal would offer a reviewer something that
    cannot be right.
    """
    tree: dict[str, dict[str, str]] = {}
    try:
        skills = await workspace.list_dir(SKILLS_ROOT)
    except FileNotFoundError:
        return tree
    for skill in sorted(skills, key=lambda entry: entry.path):
        if not skill.is_dir:
            continue
        for entry in sorted(await workspace.list_dir(skill.path), key=lambda e: e.path):
            if entry.is_dir:
                continue
            # `or 0`: a host that did not measure the file lists its size as `None`.
            if (entry.size or 0) > MAX_PROPOSED_BYTES:
                logger.warning("skill_proposal_too_large", extra={"path": entry.path})
                continue
            tree.setdefault(skill.name, {})[entry.path] = (
                await workspace.read_bytes(entry.path)
            ).decode("utf-8", errors="replace")
    return tree


def _skill_of(path: str) -> str | None:
    """The directory a path sits in, which is the skill's name.

    `None` for anything not exactly one level deep. A skill is a directory of
    files; nesting is not part of the format, and treating `/workspace/skills/a/b/c` as
    belonging to `a` would flatten two files onto one name.
    """
    rest = path[len(SKILLS_ROOT) + 1 :] if path.startswith(f"{SKILLS_ROOT}/") else ""
    parts = [part for part in rest.split("/") if part]
    return parts[0] if len(parts) == 2 else None


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
        frontmatter, instructions = split_frontmatter(body)
    except ValueError:
        # Malformed frontmatter the model wrote. Refused rather than guessed at,
        # because the description is what every other agent reads first.
        logger.warning("skill_frontmatter_unparsable", extra={"skill": name})
        return None

    return SkillChange(
        name=name,
        skill_id=skill_id,
        description=str(frontmatter.get("description") or ""),
        content=instructions.strip(),
        resources={
            path.rsplit("/", 1)[1]: content for path, content in files.items() if path != body_path
        },
    )
