"""The skills this platform ships with, read off disk.

A skill is a folder: `SKILL.md` carries the name and description in YAML
frontmatter and the body below it, and every other file beside it is a resource
the model can load when it decides it needs the detail. That is the shape the
skills capability already consumes - a body plus named files - so the library
is stored the way it is used rather than in a format that has to be translated.

Bundled in the repository rather than fetched from a registry. The alternative
was importing from a git URL, and it costs more than it looks: outbound network
from the backend, a parser pointed at somebody else's repository, and a promise
about content nobody here has read. Each folder in this directory is the same
small promise the MCP catalog makes - that we looked at it. What it costs is
that adding one is a deploy.

Installing copies. A library skill becomes an ordinary skill owned by the
organization, editable from that moment: the point of a skill is that a support
lead can fix the refund policy without a deploy, and a live link back to this
directory would take that away.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Bundled skills live with the rest of the deployment's curated data
# (app/core/catalog) - they are content shipped with the platform, not code,
# and `app/` keeps no top-level packages beyond the framework's own.
LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "core" / "catalog" / "skills"

# The file that makes a directory a skill. Named for the convention rather than
# `index.md` so a folder is recognisable as a skill on disk.
MANIFEST = "SKILL.md"

_FRONTMATTER = "---"


@dataclass(frozen=True, slots=True)
class LibraryResource:
    """One file beside the manifest."""

    name: str
    content: str

    @property
    def size_bytes(self) -> int:
        return len(self.content.encode("utf-8"))


@dataclass(frozen=True, slots=True)
class LibrarySkill:
    """One folder in the library, as the gallery shows it."""

    key: str
    """The directory name - how an install request names it."""

    name: str
    description: str
    category: str | None
    content: str
    resources: tuple[LibraryResource, ...]


@cache
def library() -> tuple[LibrarySkill, ...]:
    """Every bundled skill, by folder name.

    Cached for the process: the directory ships with the image and changes on
    redeploy, not between requests.

    A folder that cannot be read is logged and skipped rather than failing the
    gallery - one malformed manifest must not take the other skills with it.
    """
    if not LIBRARY_ROOT.is_dir():
        logger.warning("Skill library directory is missing: %s", LIBRARY_ROOT)
        return ()

    skills: list[LibrarySkill] = []
    for folder in sorted(LIBRARY_ROOT.iterdir()):
        if not folder.is_dir() or folder.name.startswith((".", "_")):
            continue
        try:
            skills.append(_read(folder))
        except Exception:
            logger.exception("Could not read the bundled skill in %s", folder)
    return tuple(skills)


def get(key: str) -> LibrarySkill | None:
    return next((skill for skill in library() if skill.key == key), None)


def _read(folder: Path) -> LibrarySkill:
    manifest = folder / MANIFEST
    metadata, body = _split_frontmatter(manifest.read_text(encoding="utf-8"))

    name = str(metadata.get("name") or folder.name)
    description = str(metadata.get("description") or "").strip()
    if not description:
        raise ValueError(f"{manifest} has no description, which is what the model reads first")
    # Optional: a shelf label for the listing, not something the model reads.
    raw_category = str(metadata.get("category") or "").strip()
    category = raw_category or None

    resources = tuple(
        LibraryResource(
            # Relative, so a folder of templates keeps its shape: the model asks
            # for `forms/w9.md`, which is what the file is called.
            name=str(path.relative_to(folder)),
            content=path.read_text(encoding="utf-8"),
        )
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != MANIFEST and not path.name.startswith(".")
    )
    return LibrarySkill(
        key=folder.name,
        name=name,
        description=description,
        category=category,
        content=body.strip(),
        resources=resources,
    )


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """The YAML header and the body below it.

    A manifest with no frontmatter is not an error: the folder name and the
    first paragraph are enough to install from, and refusing would turn a
    missing header into a missing skill.
    """
    if not text.startswith(_FRONTMATTER):
        return {}, text

    _, _, rest = text.partition(f"{_FRONTMATTER}\n")
    header, separator, body = rest.partition(f"\n{_FRONTMATTER}")
    if not separator:
        return {}, text

    parsed = yaml.safe_load(header) or {}
    if not isinstance(parsed, dict):
        raise TypeError("Frontmatter must be a mapping of keys to values")
    return parsed, body
