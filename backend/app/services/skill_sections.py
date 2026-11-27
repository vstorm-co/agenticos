"""Arranging the skills listing into sections - by agent, by origin or by category.

Arranging orders what a caller may already see and nothing else. The skills it
sorts are `skill_repo.list_visible_keys`, the flat listing's own predicate, and
the agents it names come from `agents_serving_skills` and `agents_using`, which
leave out every agent the caller cannot view. So a section can neither show a
skill nor name an agent the flat listing would not, and no section stands for a
folder: who a skill reaches is still its audience and its grants.
"""

from collections.abc import Iterable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from uuid import UUID

from app.repositories.skill import SkillKey
from app.schemas.resource_usage import AgentUsage
from app.schemas.skill import SkillArrangement, SkillSectionKind

DRAFTED = "drafted"
UNUSED = "unused"
_ORIGINS = ("origin:org", "origin:private", "origin:platform")


@dataclass(slots=True)
class Section:
    """One section: its key, what it is, and its skills in listing order."""

    key: str
    kind: SkillSectionKind
    skill_ids: list[UUID] = field(default_factory=list)
    agent: AgentUsage | None = None
    industry: str | None = None
    category: str | None = None


def arrangement_of(key: str) -> SkillArrangement | None:
    """Which arrangement a section key belongs to, or None for a key that names no section."""
    if key in (DRAFTED, UNUSED) or key.startswith("agent:"):
        return "agent"
    if key in _ORIGINS or key.startswith("origin:gallery:"):
        return "origin"
    if key.startswith("category:"):
        return "category"
    return None


def by_agent(
    keys: Sequence[SkillKey],
    *,
    serving: Mapping[UUID, AbstractSet[UUID]],
    drafting: Mapping[UUID, AbstractSet[UUID]],
    agents: Mapping[UUID, AgentUsage],
) -> list[Section]:
    """One section per agent that serves a skill, then the drafted-only and the unused.

    `serving` and `drafting` map each agent the caller may see to the skills it
    binds, all of them among `keys`, and `agents` names every one of them. A
    skill several agents serve sits under each of them: the section answers
    "what does this agent use", and a shared skill is part of every answer. A
    skill falls to the drafted-only section only when no agent serves it, and to
    the unused one when no agent binds it at all - relative to the caller, since
    an agent they cannot view is in neither map.
    """
    position = {key.id: index for index, key in enumerate(keys)}
    served = {skill_id for ids in serving.values() for skill_id in ids}
    drafted = {skill_id for ids in drafting.values() for skill_id in ids}
    by_name = sorted(
        (agents[agent_id] for agent_id in serving),
        key=lambda agent: (agent.name.casefold(), str(agent.id)),
    )
    drafted_only = Section(
        key=DRAFTED,
        kind="drafted",
        skill_ids=[key.id for key in keys if key.id not in served and key.id in drafted],
    )
    unused = Section(
        key=UNUSED,
        kind="unused",
        skill_ids=[key.id for key in keys if key.id not in served and key.id not in drafted],
    )
    return [
        *(
            Section(
                key=f"agent:{agent.id}",
                kind="agent",
                agent=agent,
                skill_ids=sorted(serving[agent.id], key=position.__getitem__),
            )
            for agent in by_name
        ),
        *(section for section in (drafted_only, unused) if section.skill_ids),
    ]


def by_origin(
    keys: Sequence[SkillKey],
    *,
    bundled_names: frozenset[str],
    gallery_industries: Mapping[str, str],
) -> list[Section]:
    """The organization's own skills, the private ones, then what shipped with the deployment.

    "The organization's own" is every skill written here that is not private -
    one shared with the whole organization or only with chosen groups (`team`),
    since both are the organization's work rather than one person's.

    Shipped skills split into the bundled platform library and one section per
    gallery industry. Both are recognised by name, because installing copies a
    folder into an ordinary row and the name is all that stays of where it came
    from - so an organization's own skill that happens to reuse a shipped name
    reads as shipped, as its `built_in` badge already does.
    """
    org = Section(key="origin:org", kind="org")
    private = Section(key="origin:private", kind="private")
    platform = Section(key="origin:platform", kind="platform")
    galleries: dict[str, Section] = {}
    for skill in keys:
        industry = gallery_industries.get(skill.name)
        if industry is not None:
            galleries.setdefault(
                industry,
                Section(key=f"origin:gallery:{industry}", kind="gallery", industry=industry),
            ).skill_ids.append(skill.id)
        elif skill.name in bundled_names:
            platform.skill_ids.append(skill.id)
        elif skill.visibility == "private":
            private.skill_ids.append(skill.id)
        else:
            org.skill_ids.append(skill.id)
    shipped = [galleries[industry] for industry in sorted(galleries)]
    return [section for section in (org, private, platform, *shipped) if section.skill_ids]


def by_category(keys: Sequence[SkillKey], *, suggested: Sequence[str]) -> list[Section]:
    """One section per shelf, letter case folded, then the uncategorized.

    The filter matches a category in any letter case, so `Security` and
    `security` are one shelf here too, shown by `category_label`'s spelling.
    """
    shelves: dict[str, list[tuple[str, UUID]]] = {}
    uncategorized = Section(key="category:", kind="uncategorized")
    for skill in keys:
        spelling = (skill.category or "").strip()
        if spelling:
            shelves.setdefault(spelling.lower(), []).append((spelling, skill.id))
        else:
            uncategorized.skill_ids.append(skill.id)
    sections = [
        Section(
            key=f"category:{folded}",
            kind="category",
            category=category_label([spelling for spelling, _ in shelf], suggested),
            skill_ids=[skill_id for _, skill_id in shelf],
        )
        for folded, shelf in sorted(shelves.items())
    ]
    return [*sections, *([uncategorized] if uncategorized.skill_ids else [])]


def category_label(spellings: Iterable[str], suggested: Sequence[str]) -> str:
    """The one spelling a shelf is shown by.

    The suggested shelf's own spelling when one matches, so an organization's
    `Security` and `security` show as the `security` it was offered; otherwise
    the first spelling in sort order, which is stable however the rows arrive.
    """
    first = min(spelling.strip() for spelling in spellings)
    return next((name for name in suggested if name.lower() == first.lower()), first)


def fold_categories(spellings: Iterable[str], suggested: Sequence[str]) -> list[str]:
    """Distinct spellings reduced to one per shelf, in shelf order - the filter's choices."""
    shelves: dict[str, list[str]] = {}
    for spelling in spellings:
        if spelling.strip():
            shelves.setdefault(spelling.strip().lower(), []).append(spelling)
    return [category_label(shelves[folded], suggested) for folded in sorted(shelves)]
