"""Skills as files in the workspace, and what the agent writes back.

A skill reaches the model as instructions it pulls in with `read_skill`, and
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

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import yaml
from pydantic_ai.workspaces import Workspace

from app.agents.capabilities.skills import SkillBody, served_files
from app.core.exceptions import ExternalServiceError
from app.core.skill_files import ResourceEncoding, decode_skill_file
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

    base_version: int | None
    """The version of the skill the agent was given, or `None` for one it created."""

    base_version_id: UUID | None
    """That version exactly, and through it the line - main or a fork - it is on."""

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
    binary: set[str] = field(default_factory=set)
    """Binary assets are available to scripts, never decoded into text proposals."""
    #: `directory name -> skill id`, for attributing a change back to a row.
    owners: dict[str, Any] = field(default_factory=dict)
    #: `directory name -> skill version` written, so a change applies only onto it.
    versions: dict[str, int] = field(default_factory=dict)
    #: `directory name -> skill version id` written, the exact version a change is onto.
    version_ids: dict[str, UUID | None] = field(default_factory=dict)


def skill_dir(name: str) -> str:
    return f"{SKILLS_ROOT}/{name}"


def render_body(skill: Skill, body: SkillBody | None = None) -> str:
    """The skill as `SKILL.md`, in the format `split_frontmatter` reads back, with `body` in its place.

    The name and description are in the frontmatter rather than implied by the
    directory, because they are what the agent edits when it improves a skill's
    one-line summary - and a summary is the only thing other agents read before
    deciding whether to load the body at all.
    """
    description = skill.description if body is None else body.description
    content = skill.content if body is None else body.content
    metadata = dict(skill.manifest_metadata or {})
    if body is not None and body.manifest_metadata is not None:
        metadata = dict(body.manifest_metadata)
    metadata.update({"name": skill.name, "description": description})
    header = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)
    return f"---\n{header}---\n\n{content}\n"


async def materialise(
    workspace: Workspace, skills: list[Skill], bodies: Mapping[UUID, SkillBody] | None = None
) -> MaterialisedSkills:
    """Write each skill into the workspace, and remember what was written.

    A skill in `bodies` is written with that body instead of its stored one - the
    same candidate the capability serves, so the file and `load_capability` agree.

    Text writes remain best-effort because instructions can still be read
    through the skill capability. A required binary asset has no prompt fallback;
    refusing its materialization fails preparation instead of promising a
    sandbox file that does not exist. Cancellation always propagates.

    Awaited, and that matters more here than anywhere else: this runs inside
    `prepare`, once per file per skill, before the model has seen a token - so on
    a container-backed workspace an agent with five skills and three resources
    each pays fifteen round trips before its first word, and they must not block
    the event loop.
    """
    state = MaterialisedSkills()
    for skill in skills:
        state.owners[skill.name] = skill.id
        state.versions[skill.name] = skill.version
        state.version_ids[skill.name] = skill.latest_version_id
        body = (bodies or {}).get(skill.id)
        files = {f"{skill_dir(skill.name)}/{BODY_FILE}": render_body(skill, body)}
        for file in served_files(skill, body):
            path = f"{skill_dir(skill.name)}/{file.name}"
            if file.encoding == "base64":
                if not await _write(workspace, path, file.content, encoding=file.encoding):
                    raise ExternalServiceError(
                        message="The sandbox could not materialize a required binary skill asset",
                        details={"skill": skill.name, "resource": file.name},
                    )
                state.binary.add(path)
            else:
                files[path] = file.content
        for path, content in files.items():
            if await _write(workspace, path, content):
                state.written[path] = content
    return state


async def _write(
    workspace: Workspace, path: str, content: str, *, encoding: ResourceEncoding = "utf8"
) -> bool:
    """Whether the file made it. A refusal is logged rather than raised."""
    try:
        if encoding == "base64":
            await workspace.write_bytes(path, decode_skill_file(content, encoding))
        else:
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
        present = await _read_tree(workspace, binary=state.binary)
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
        change = _to_change(
            name,
            files,
            state.owners.get(name),
            state.versions.get(name),
            state.version_ids.get(name),
        )
        if change is not None:
            changes.append(change)
    return changes


async def _read_tree(
    workspace: Workspace, *, binary: Collection[str] | None = None
) -> dict[str, dict[str, str]]:
    """Read bounded text proposals recursively without interpreting binary assets.

    Binary assets remain available in the sandbox. Their edits are not text
    proposals: replacing undecodable bytes would corrupt templates, and unchanged
    binary files must not make every turn appear to have rewritten a skill.
    """
    tree: dict[str, dict[str, str]] = {}
    try:
        skills = await workspace.list_dir(SKILLS_ROOT)
    except FileNotFoundError:
        return tree
    for skill in sorted(skills, key=lambda entry: entry.path):
        if not skill.is_dir:
            continue
        pending = [(skill.path, 0)]
        visited: set[str] = set()
        count = 0
        while pending:
            directory, depth = pending.pop()
            if directory in visited or depth > 32:
                logger.warning("skill_proposal_tree_limit", extra={"path": directory})
                continue
            visited.add(directory)
            for entry in sorted(await workspace.list_dir(directory), key=lambda e: e.path):
                count += 1
                if count > 1024:
                    logger.warning("skill_proposal_file_limit", extra={"skill": skill.name})
                    pending.clear()
                    break
                if entry.is_dir:
                    pending.append((entry.path, depth + 1))
                    continue
                if binary is not None and entry.path in binary:
                    continue
                size = (
                    entry.size
                    if entry.size is not None
                    else (await workspace.stat(entry.path)).size
                )
                if size is not None and size > MAX_PROPOSED_BYTES:
                    logger.warning("skill_proposal_too_large", extra={"path": entry.path})
                    continue
                raw = await workspace.read_bytes(entry.path)
                if len(raw) > MAX_PROPOSED_BYTES:
                    logger.warning("skill_proposal_too_large", extra={"path": entry.path})
                    continue
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    logger.warning("skill_binary_proposal_unsupported", extra={"path": entry.path})
                    continue
                if "\0" in text:
                    logger.warning("skill_binary_proposal_unsupported", extra={"path": entry.path})
                    continue
                tree.setdefault(skill.name, {})[entry.path] = text
    return tree


def _skill_of(path: str) -> str | None:
    """The skill owning a direct or nested supporting file."""
    rest = path[len(SKILLS_ROOT) + 1 :] if path.startswith(f"{SKILLS_ROOT}/") else ""
    parts = rest.split("/")
    return (
        parts[0] if len(parts) >= 2 and all(part not in ("", ".", "..") for part in parts) else None
    )


def _to_change(
    name: str,
    files: dict[str, str],
    skill_id: Any | None,
    base_version: int | None,
    base_version_id: UUID | None,
) -> SkillChange | None:
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

    description = str(frontmatter.get("description") or "")
    if not 1 <= len(name) <= 64 or len(description) > 500:
        # Keep the original file intact: shortening a directory could collide
        # with another skill, and silently truncating metadata changes its meaning.
        logger.warning(
            "skill_change_metadata_out_of_bounds",
            extra={"name_length": len(name), "description_length": len(description)},
        )
        return None
    return SkillChange(
        name=name,
        skill_id=skill_id,
        base_version=base_version,
        base_version_id=base_version_id,
        description=description,
        content=instructions.strip(),
        resources={
            path[len(skill_dir(name)) + 1 :]: content
            for path, content in files.items()
            if path != body_path
        },
    )
