"""Skills - an organization's reusable know-how, stored in the database.

A skill is a piece of know-how written once and attached to many agents: how
refunds are handled, what the house style is, which checks a report must pass.
This module owns storage and access; turning skills into something an agent can
read is the skills *capability*.
"""

import logging
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import StringConstraints, TypeAdapter
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills import SkillBody, SkillBodyFile
from app.agents.spec import AgentSpec, SkillBindingSpec
from app.core import catalog
from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    InUseError,
    NotFoundError,
)
from app.core.excerpt import excerpt
from app.core.permissions import AuthContext, Perm
from app.db.models.resource_grant import Visibility
from app.db.models.skill import Skill, SkillResource
from app.db.models.skill_proposal import ProposalStatus
from app.db.models.skill_version import SkillVersion, SkillVersionSource
from app.db.updates import writable
from app.repositories import (
    agent_repo,
    audit_log_repo,
    resource_grant_repo,
    skill_proposal_repo,
    skill_repo,
    skill_usage_repo,
    skill_version_repo,
)
from app.repositories.skill import SkillSort
from app.schemas.agent_run import RunSkillUseRead
from app.schemas.skill import (
    GalleryIndustryRead,
    GalleryInstallResult,
    GallerySkillPreview,
    GallerySkillRead,
    SkillGallery,
    SkillList,
    SkillRead,
    SkillResourceUpdate,
    SkillSummary,
    SkillUpdate,
    skill_name_refusal,
)
from app.schemas.skill_usage import (
    SkillUsageAgent,
    SkillUsageDay,
    SkillUsageRead,
    SkillUsageVersion,
)
from app.services import skill_library
from app.services.access import AGENT, SKILL, accessible_ids, resolve_access, visible_resource_ids
from app.services.resource_usage import (
    agents_serving_skills,
    agents_using,
    agents_using_skill,
    groups_sharing,
    in_use_by,
    shared_with_group,
)
from app.services.sharing import SharingService
from app.services.skill_versions import SkillVersionService

logger = logging.getLogger(__name__)

# The shelf names the pickers suggest before an organization has invented its
# own. Data, not behaviour - a deployment edits the catalog file - and bounded
# like `SkillCreate.category`, so a suggestion is never something the create
# endpoint would then refuse.
SUGGESTED_CATEGORIES: tuple[str, ...] = catalog.load(
    "skill_categories.json",
    TypeAdapter(tuple[Annotated[str, StringConstraints(min_length=1, max_length=64)], ...]),
)

# What a skill's files may be. They are handed to a model as text, so a format
# it cannot read is not a smaller feature - it is a file the agent is told
# about and then cannot use.
MAX_RESOURCE_BYTES = 512 * 1024

SKILL_BODY_CHARS = 4000
"""How much of one skill's body an agent's improver reads."""


def improver_skill_chars(skills: Sequence[Skill], used: Mapping[UUID, set[UUID]]) -> int:
    """How much skill text an agent's improver is shown: the bodies its evidence used."""
    return sum(min(len(skill.content), SKILL_BODY_CHARS) for skill in skills if skill.id in used)


def _summary(
    skill: Skill, bundled_names: frozenset[str], architect_names: frozenset[str]
) -> SkillSummary:
    """A skill as the listing shows it.

    `built_in` is a name match against the shipped library and gallery because that is
    all installing keeps: an install copies the folder into an ordinary row,
    and the name - unique per organization, never editable - is the one trace
    of where it came from.
    """
    return SkillSummary(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        category=skill.category,
        visibility=skill.visibility,
        file_count=len(skill.resources),
        version=skill.version,
        built_in=skill.name in bundled_names,
        architect=skill.name in architect_names,
        excerpt=excerpt(skill.content),
    )


def _clean_resource_path(raw: str) -> str:
    """A resource name from an uploaded path, or a refusal.

    Uploads arrive with whatever the browser sent: a leading folder from a
    directory picker, Windows separators, and - from an archive somebody
    crafted - `..`. The name is a key in a table rather than a location on
    disk, so nothing here can escape anything; it is refused anyway, because a
    name that *reads* as an escape is a name nobody can reason about.
    """
    parts = [segment for segment in raw.replace("\\", "/").split("/") if segment not in ("", ".")]
    if any(segment == ".." for segment in parts):
        raise BadRequestError(
            message=f"'{raw}' is not a usable file name - a path cannot step outside the skill",
            details={"name": raw},
        )
    name = "/".join(parts)
    if not name:
        raise BadRequestError(message="A file needs a name", details={"name": raw})
    if len(name) > 128:
        raise BadRequestError(
            message=f"'{name}' is too long a path - 128 characters is the limit",
            details={"name": name},
        )
    return name


def _decode_text(name: str, raw: bytes) -> str:
    """The file as text, or a refusal that says which file and why.

    Skills are read by a model, and what it receives is a string. A PDF stored
    here would be handed over as mojibake - a file the agent is told it has and
    cannot use, which is worse than not having it.
    """
    if len(raw) > MAX_RESOURCE_BYTES:
        raise BadRequestError(
            message=f"'{name}' is over {MAX_RESOURCE_BYTES // 1024} KB",
            details={"name": name},
        )
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BadRequestError(
            message=(
                f"'{name}' is not text. A skill's files are handed to the model as text, so a "
                "binary one would arrive as noise - keep it somewhere the agent can fetch and "
                "reference it by URL instead."
            ),
            details={"name": name},
        ) from exc


class LibraryRefresh(StrEnum):
    """What `seed-skills` does, or would do, with one bundled skill."""

    INSTALL = "install"
    """The organization has no skill by that name."""
    CURRENT = "current"
    """Its copy already says what the shipped folder says."""
    UPDATE = "update"
    """An unedited copy of an earlier version - or an edited one, when asked to."""
    EDITED = "edited"
    """Edited here since it was copied; left alone."""
    UNTRACKED = "untracked"
    """Copied before fingerprints were kept and different now; left alone."""
    WAITING = "waiting"
    """An update agents follow: it waits as a proposal until it is checked on them."""


def _fingerprint_of(skill: Skill) -> str:
    """The fingerprint of what the organization's copy says now."""
    return skill_library.fingerprint(
        description=skill.description,
        category=skill.category,
        content=skill.content,
        resources=(
            (resource.name, resource.content, resource.description) for resource in skill.resources
        ),
    )


def _refresh_plan(
    existing: Skill | None, bundled: skill_library.LibrarySkill, *, replace_edited: bool
) -> LibraryRefresh:
    if existing is None:
        return LibraryRefresh.INSTALL
    here = _fingerprint_of(existing)
    if here == bundled.fingerprint:
        return LibraryRefresh.CURRENT
    if here == existing.library_fingerprint or replace_edited:
        return LibraryRefresh.UPDATE
    if existing.library_fingerprint is None:
        return LibraryRefresh.UNTRACKED
    return LibraryRefresh.EDITED


class SkillService:
    """Manage an organization's skills."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.versions = SkillVersionService(db)

    async def get(
        self, ctx: AuthContext, skill_id: UUID, *, perm: Perm = Perm.SKILLS_VIEW
    ) -> Skill:
        skill = await skill_repo.get(self.db, skill_id, organization_id=ctx.organization_id)
        if skill is None:
            raise NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
        if not await resolve_access(self.db, ctx, skill, perm, resource_type=SKILL):
            raise NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
        return skill

    async def usage(self, ctx: AuthContext, skill_id: UUID, *, days: int) -> SkillUsageRead:
        """How often each agent used the skill over the last `days`, as the skill page shows it.

        Read off runs, so it needs `runs:view` as every run reader does. An agent
        the caller may not see is counted in `hidden_*` and never named.

        Raises:
            NotFoundError: No such skill, or one the caller may not see.
            AuthorizationError: A caller without `runs:view`.
        """
        skill = await self.get(ctx, skill_id)
        if not ctx.has(Perm.RUNS_VIEW):
            raise AuthorizationError(
                message="Skill usage is read off runs, which needs runs:view",
                details={"permission": Perm.RUNS_VIEW.value},
            )
        since = datetime.now(UTC) - timedelta(days=days)
        rows = await skill_usage_repo.usage_by_agent(
            self.db, organization_id=ctx.organization_id, skill_id=skill.id, since=since
        )
        agents = await agent_repo.get_many(
            self.db, [row.agent_id for row in rows], organization_id=ctx.organization_id
        )
        visible = await accessible_ids(
            self.db, ctx, agents.values(), Perm.AGENTS_VIEW, resource_type=AGENT
        )
        shown = [row for row in rows if row.agent_id in visible]
        hidden = [row for row in rows if row.agent_id not in visible]
        versions: dict[UUID, list[SkillUsageVersion]] = {}
        for version in await skill_usage_repo.usage_by_version(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            since=since,
            agent_ids=[row.agent_id for row in shown],
        ):
            versions.setdefault(version.agent_id, []).append(
                SkillUsageVersion(skill_version_id=version.skill_version_id, loads=version.loads)
            )
        by_day: dict[UUID, dict[date, int]] = {}
        for per_day in await skill_usage_repo.usage_by_day(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            since=since,
            agent_ids=[row.agent_id for row in shown],
        ):
            by_day.setdefault(per_day.agent_id, {})[per_day.day] = per_day.loads
        first = since.date()
        window = [first + timedelta(days=offset) for offset in range(days + 1)]
        return SkillUsageRead(
            days=days,
            since=since,
            loads=sum(row.loads for row in shown),
            agents=[
                SkillUsageAgent(
                    agent_id=row.agent_id,
                    agent_name=agents[row.agent_id].name,
                    slug=agents[row.agent_id].slug,
                    has_avatar=agents[row.agent_id].has_avatar,
                    avatar_color=agents[row.agent_id].avatar_color,
                    loads=row.loads,
                    resource_reads=row.resource_reads,
                    workspace_reads=row.workspace_reads,
                    last_loaded_at=row.last_loaded_at,
                    versions=versions.get(row.agent_id, []),
                    daily=[
                        SkillUsageDay(date=day, loads=by_day.get(row.agent_id, {}).get(day, 0))
                        for day in window
                    ],
                )
                for row in shown
            ],
            hidden_agents=len(hidden),
            hidden_loads=sum(row.loads for row in hidden),
        )

    async def list_skills(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        search: str | None = None,
        categories: Sequence[str] | None = None,
        group_id: UUID | None = None,
        sort: SkillSort = "name",
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Skill], int]:
        """A page of the skills this caller may see, and how many there are in all.

        Scoped like every shared resource: a role that reaches the whole
        organization lists everything, anyone else lists their own skills, the
        org-visible ones and those explicitly shared with them - the same set
        :func:`resolve_access` would admit one row at a time. `shared_with_me`
        narrows to what was deliberately shared with the caller - org-visible
        or explicitly granted, and not their own. `group_id` narrows to the
        skills shared with one group.
        """
        # `None` is `visible_resource_ids` saying the role already reaches every
        # skill, which is exactly what `see_all` tells the query - so both come
        # from the one call rather than from the scope being read twice and the
        # two answers being trusted to agree.
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=SKILL, perm=Perm.SKILLS_VIEW
        )
        grant_ids = [] if shared is None else shared
        if shared_with_me and shared is None:
            # A role that reaches everything never looks its grants up - but
            # "shared with me" is a question about grants and visibility, not
            # reach, and without them the answer would degenerate into "the
            # whole organization minus mine".
            grant_ids = await resource_grant_repo.list_shared_ids(
                self.db,
                organization_id=ctx.organization_id,
                subject_user_id=ctx.subject_id,
                resource_type=SKILL.key,
            )
        return await skill_repo.list_visible(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=grant_ids,
            shared_with_me=shared_with_me,
            only_ids=await shared_with_group(self.db, ctx, resource_type=SKILL, group_id=group_id),
            search=search,
            categories=categories,
            sort=sort,
            skip=skip,
            limit=limit,
        )

    async def list_readable(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        search: str | None = None,
        categories: Sequence[str] | None = None,
        group_id: UUID | None = None,
        sort: SkillSort = "name",
        skip: int = 0,
        limit: int = 50,
    ) -> SkillList:
        """The listing: a page of skills, and everything the page around it needs.

        Three things that are not the page itself travel with it. `total` is the
        count before paging, which a pager needs and a page cannot supply.
        `categories` is the whole organization's rather than the page's - a
        filter chip that vanished with the page it filtered would strand
        whoever pressed it. `suggested_categories` is the shipped list, for an
        organization that has not invented its own yet.

        `categories` stays the organization's under `shared_with_me` too: the
        chips describe what can be filtered to, and narrowing them to the
        shared subset would make the filter disappear as soon as it was used.

        The listing used to top itself up, copying in any bundled skill the
        organization did not have. That made a deleted one come back on the
        next visit, so the only way to retire a shipped skill was to disable it
        - which is a workaround for a listing that refused to let go. An
        organization is seeded at creation and `agenticos cmd seed-skills`
        re-runs that deliberately; the gallery is where a skill is chosen. None
        of those needs a page that quietly writes rows while it reads.
        """
        items, total = await self.list_skills(
            ctx,
            shared_with_me=shared_with_me,
            search=search,
            categories=categories,
            group_id=group_id,
            sort=sort,
            skip=skip,
            limit=limit,
        )
        bundled_names = frozenset(entry.name for entry in skill_library.library()) | frozenset(
            skill.name for industry in skill_library.gallery() for skill in industry.skills
        )
        architect_names = skill_library.architect_names()
        used = await agents_serving_skills(self.db, ctx, skill_ids=[skill.id for skill in items])
        drafted = await agents_using(
            self.db, ctx, field="skill_ids", resource_ids=[skill.id for skill in items]
        )
        groups = await groups_sharing(
            self.db, ctx, resource_type=SKILL, resource_ids=[skill.id for skill in items]
        )
        editable = await accessible_ids(self.db, ctx, items, Perm.SKILLS_EDIT, resource_type=SKILL)
        forks = await skill_version_repo.count_active_forks(
            self.db, organization_id=ctx.organization_id, skill_ids=[skill.id for skill in items]
        )
        return SkillList(
            items=[
                _summary(skill, bundled_names, architect_names).model_copy(
                    update={
                        "used_by": used[skill.id],
                        "drafted_by": [
                            agent
                            for agent in drafted[skill.id]
                            if agent.id not in {serving.id for serving in used[skill.id]}
                        ],
                        "shared_groups": groups[skill.id],
                        "can_edit": skill.id in editable,
                        "forks": forks[skill.id],
                    }
                )
                for skill in items
            ],
            total=total,
            categories=await self.list_categories(ctx),
            suggested_categories=list(SUGGESTED_CATEGORIES),
        )

    async def list_categories(self, ctx: AuthContext) -> list[str]:
        """Every distinct category in this organization, for the listing's filter."""
        return await skill_repo.list_categories(self.db, organization_id=ctx.organization_id)

    async def resolve_for_agent(
        self,
        ctx: AuthContext,
        skill_ids: list[UUID],
        *,
        bindings: Sequence[SkillBindingSpec] = (),
        projected: Mapping[UUID, SkillBody] | None = None,
    ) -> list[Skill]:
        """The skills an agent is bound to, each as the version its binding names.

        A skill with no binding is its row, which is its main line's newest version;
        one pinned to a main version or following a fork is a detached copy of that
        version, text and files, so every reader below treats both alike. Each one's
        `latest_version_id` is the version it serves.

        Scoped to the run's organization and **not** to the runner's own access,
        which is deliberate and is the same rule delegates and collections follow:
        the binding is checked once, against the publisher, when the agent is
        published, and the agent then reads it for everyone who may run it. See
        `skill_problems` in `app/services/agent_registry.py` for the check.

        Re-checking here would be wrong twice over. `resolve_access` refuses every
        context with no subject, so an API key, an embedded widget and a channel
        message - the surfaces this platform exists to serve - would each lose
        every skill the agent has. And where there *is* a subject, an agent's
        instructions would change with who asked: a member or a viewer, whose role
        gives `SKILLS_VIEW: Scope.SHARED`, would get a thinner answer out of the
        same published version than a builder does, with the difference visible
        nowhere.

        A skill deleted after publish is skipped rather than failing
        the run: the agent is less capable, not broken. Named in the log with the
        organization, because from inside one tenant a row that was deleted and a
        row that belongs to another tenant leave the same absence - and the second
        is a spec somebody should look at rather than a skill somebody removed.
        """
        if not skill_ids:
            return []
        virtual = {
            key: body
            for key, body in (projected or {}).items()
            if body.name is not None and key in skill_ids
        }
        found = await skill_repo.get_many(
            self.db,
            [key for key in skill_ids if key not in virtual],
            organization_id=ctx.organization_id,
        )
        pinned = {binding.skill_id: binding for binding in bindings}
        resolved = []
        for skill_id in skill_ids:
            body = virtual.get(skill_id)
            skill = (
                Skill(
                    id=skill_id,
                    organization_id=ctx.organization_id,
                    name=body.name,
                    description=body.description,
                    content=body.content,
                    resources=[],
                    version=1,
                    visibility=Visibility.PRIVATE.value,
                    owner_user_id=ctx.user_id,
                )
                if body is not None
                else found.get(skill_id)
            )
            if skill is None:
                logger.warning(
                    "Agent references skill %s which is deleted or not org %s's",
                    skill_id,
                    ctx.organization_id,
                )
                continue
            binding = pinned.get(skill_id) if body is None else None
            served = skill if binding is None else await self._as_bound(skill, binding)
            if served is None:
                logger.warning(
                    "Agent binds skill %s to a version or fork it no longer has", skill_id
                )
                continue
            resolved.append(served)
        return resolved

    async def read_by_improver(
        self, ctx: AuthContext, agent_id: UUID, spec: AgentSpec, run_ids: Sequence[UUID]
    ) -> tuple[list[Skill], dict[UUID, set[UUID]]]:
        """The skills an agent's improver reads, and the runs that used each as the agent reads it.

        A run served another version of a skill - before a pin moved, on an older
        main or on another fork - does not count for it: the body the improver reads
        is not the one that run answered with.

        Unlike a run, the improver answers the person who started it, so a skill they
        may not view is left out: its text would reach them through what is proposed.
        """
        bound = await self.resolve_for_agent(ctx, spec.skill_ids, bindings=spec.skill_bindings)
        visible = await accessible_ids(self.db, ctx, bound, Perm.SKILLS_VIEW, resource_type=SKILL)
        skills = [skill for skill in bound if skill.id in visible]
        used = await skill_usage_repo.skills_in_runs(
            self.db,
            organization_id=ctx.organization_id,
            agent_id=agent_id,
            run_ids=run_ids,
            versions={skill.id: skill.latest_version_id for skill in skills},
        )
        return skills, used

    async def _as_bound(self, skill: Skill, binding: SkillBindingSpec) -> Skill | None:
        """The skill as a pinned main version or a fork's newest says it, detached."""
        if binding.version is not None:
            version = (
                await skill_version_repo.get_by_numbers(
                    self.db,
                    organization_id=skill.organization_id,
                    skill_id=skill.id,
                    fork_id=None,
                    numbers=[binding.version],
                )
            ).get(binding.version)
        else:
            assert binding.fork_id is not None, "a binding names a version or a fork"
            fork = await skill_version_repo.get_fork(
                self.db,
                binding.fork_id,
                organization_id=skill.organization_id,
                skill_id=skill.id,
            )
            latest = None if fork is None else fork.latest_version_id or fork.base_version_id
            version = (
                None
                if latest is None
                else (
                    await skill_version_repo.get_versions(
                        self.db, [latest], organization_id=skill.organization_id
                    )
                ).get(latest)
            )
        if version is None:
            return None
        files = await self.versions.files_of(version)
        return Skill(
            id=skill.id,
            organization_id=skill.organization_id,
            owner_user_id=skill.owner_user_id,
            visibility=skill.visibility,
            name=skill.name,
            description=version.description,
            content=version.content,
            version=version.number,
            latest_version_id=version.id,
            resources=[
                SkillResource(name=name, description=entry["description"], content=files[name])
                for name, entry in sorted(version.resources.items())
            ],
        )

    async def create(
        self,
        ctx: AuthContext,
        *,
        name: str,
        description: str,
        content: str,
        category: str | None = None,
        visibility: Visibility = Visibility.PRIVATE,
        library_fingerprint: str | None = None,
        group_ids: list[UUID] | None = None,
        user_ids: list[UUID] | None = None,
        source: SkillVersionSource | None = SkillVersionSource.CREATED,
        proposal_id: UUID | None = None,
    ) -> Skill:
        """Create a skill and its main v1.

        `source` is what v1 records; `None` leaves v1 to a caller that adds files
        first, so the skill's first version already carries them.

        Raises:
            BadRequestError: If the name is not one a model can load the skill
                by. `SkillCreate` refuses it too, but an applied skill proposal
                arrives here with an agent's directory name and no schema.
            AlreadyExistsError: If the name is taken. Names are how the model
                refers to a skill, so two with one name is an ambiguity the
                agent cannot resolve.
        """
        refusal = skill_name_refusal(name)
        if refusal is not None:
            raise BadRequestError(message=refusal, details={"name": name})
        if await skill_repo.get_by_name(self.db, name, organization_id=ctx.organization_id):
            raise AlreadyExistsError(
                message=(
                    f"A skill named '{name}' already exists. The name is how a model refers to a "
                    "skill and cannot be changed afterwards, so choose a different one - or open "
                    "the existing skill and edit it, which reaches every agent bound to it."
                ),
                details={"name": name},
            )
        skill = await skill_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            owner_user_id=ctx.user_id,
            name=name,
            description=description,
            content=content,
            category=category,
            visibility=visibility.value,
            library_fingerprint=library_fingerprint,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.created",
            target_type="skill",
            target_id=str(skill.id),
            details={"name": name},
        )
        if group_ids or user_ids:
            await SharingService(self.db).restrict_to(
                ctx,
                skill,
                resource_type=SKILL,
                group_ids=group_ids or [],
                user_ids=user_ids or [],
            )
        if source is not None:
            await self.versions.record_main(ctx, skill, source=source, proposal_id=proposal_id)
        return skill

    async def update(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        data: SkillUpdate,
        *,
        source: SkillVersionSource | None = SkillVersionSource.EDIT,
        proposal_id: UUID | None = None,
    ) -> Skill:
        """Edit a skill's main line. A changed text or description is a new main version.

        Only the text and the description are what an agent reads, so a new
        category changes no version. `source` is what the version records; `None`
        leaves it to a caller about to change the files too, so one decision is one
        version.
        """
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        update_data = writable(data, over=Skill)
        text_changed = any(
            field in update_data and update_data[field] != getattr(skill, field)
            for field in ("description", "content")
        )
        updated = await skill_repo.update(self.db, skill=skill, update_data=update_data)
        if text_changed and source is not None:
            await self.versions.record_main(ctx, updated, source=source, proposal_id=proposal_id)
        if text_changed:
            await self._changed(updated)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.updated",
            target_type="skill",
            target_id=str(skill.id),
            # An edit changes the instructions every bound agent executes on its
            # next run - the highest-consequence of the three skill events, and
            # the one most worth being able to attribute afterwards.
            details={"name": skill.name, "version": updated.version, "fields": sorted(update_data)},
        )
        return updated

    async def install_from_library(self, ctx: AuthContext, key: str) -> Skill:
        """Copy a bundled skill into this organization, files and all.

        A copy, not a link. From this moment it is an ordinary skill the
        organization owns and can edit - which is the whole point of skills, and
        would be taken away by a live reference back to the shipped folder.

        Always organization-visible, set at creation rather than by a follow-up
        edit: a bundled skill is for everybody, and the only callers left are
        the seeding paths - organization creation and `seed-skills` - since the
        per-person Install button was dropped (#281).

        Both seed as the organization's first owner, so the audit entry's
        actor is an attribution rather than a person who acted. `seeded: true`
        in its details is what keeps that honest - it is how a reader tells
        "the platform seeded this as the owner" from a write the owner made.

        Raises:
            NotFoundError: If no such skill ships with this deployment.
            AlreadyExistsError: If the organization already has one by that
                name - seeding twice would otherwise produce a second skill
                the model cannot tell from the first.
        """
        bundled = skill_library.get(key)
        if bundled is None:
            raise NotFoundError(message="No such bundled skill", details={"key": key})
        return await self._copy_library_skill(ctx, bundled, seeded=True)

    async def plan_library_refresh(
        self, ctx: AuthContext, key: str, *, replace_edited: bool = False
    ) -> LibraryRefresh:
        """What `refresh_from_library` would do with one bundled skill, writing nothing.

        Raises:
            NotFoundError: If no such skill ships with this deployment.
        """
        bundled, existing = await self._library_pair(ctx, key)
        plan = _refresh_plan(existing, bundled, replace_edited=replace_edited)
        if (
            plan is LibraryRefresh.UPDATE
            and existing is not None
            and await self._followed(existing)
        ):
            return LibraryRefresh.WAITING
        return plan

    async def refresh_from_library(
        self, ctx: AuthContext, key: str, *, replace_edited: bool = False
    ) -> LibraryRefresh:
        """Bring the organization's copy of a bundled skill up to the shipped version.

        Missing, it is installed. An unedited copy of an earlier version - one
        that still matches the fingerprint it was written with - is replaced,
        files and all, as a new main version, because nobody chose what it
        says: the platform did, and the platform now says something better.
        Unless agents follow its main line: then the update waits as a proposal,
        and goes live once a check on those agents allows it. A
        copy edited here is the organization's and is left alone unless
        `replace_edited` says to take the bundled version over the edits, and so
        is one copied before fingerprints were kept, since nothing can tell
        whether it was edited.

        Raises:
            NotFoundError: If no such skill ships with this deployment.
            AlreadyExistsError: If another writer installed it between the check
                and the copy - the listing's top-up, racing a seed.
        """
        bundled, existing = await self._library_pair(ctx, key)
        return await self._refresh_bundled(
            ctx, bundled, existing, replace_edited=replace_edited, wait_for_check=True
        )

    async def synchronize_library(self, ctx: AuthContext) -> None:
        """Deliver new built-ins and untouched updates under the organization install lock.

        Called by the trusted shipped-agent installer as the organization's owner.
        Installation receipts distinguish a never-delivered skill from one somebody
        deleted. Edited and untracked copies retain the normal refresh protection.
        """
        installed = await audit_log_repo.installed_skill_keys(
            self.db, organization_id=ctx.organization_id
        )
        for bundled in skill_library.library():
            existing = await skill_repo.get_by_name(
                self.db, bundled.name, organization_id=ctx.organization_id
            )
            if existing is None and bundled.key in installed:
                continue
            await self._refresh_bundled(
                ctx, bundled, existing, replace_edited=False, wait_for_check=True
            )

    async def refresh_gallery(
        self, ctx: AuthContext, key: str, *, dry_run: bool = False, replace_edited: bool = False
    ) -> LibraryRefresh:
        """Refresh a gallery copy using the same edit protection as seeded skills.

        Written at once even when agents follow it: the one caller is the Architect's
        refresh, whose guide travels with the platform's own template and has no
        test questions an organization wrote.
        """
        bundled = skill_library.gallery_get(key)
        if bundled is None:
            raise NotFoundError(message="No such gallery skill", details={"key": key})
        existing = await skill_repo.get_by_name(
            self.db, bundled.name, organization_id=ctx.organization_id
        )
        if existing is not None:
            await self.get(ctx, existing.id, perm=Perm.SKILLS_EDIT)
        if dry_run:
            return _refresh_plan(existing, bundled, replace_edited=replace_edited)
        return await self._refresh_bundled(
            ctx, bundled, existing, replace_edited=replace_edited, wait_for_check=False
        )

    async def _followed(self, skill: Skill) -> bool:
        """Whether any agent's served version follows the skill's main line."""
        from app.services.skill_agents import SkillAgentService

        return bool(await SkillAgentService(self.db).line_agents(skill, None))

    async def _refresh_bundled(
        self,
        ctx: AuthContext,
        bundled: skill_library.LibrarySkill,
        existing: Skill | None,
        *,
        replace_edited: bool,
        wait_for_check: bool,
    ) -> LibraryRefresh:
        if existing is not None:
            # Locked and re-read before deciding: an edit a member commits between
            # the lookup and the overwrite would otherwise be judged on the copy as
            # it was, found unedited, and replaced. Every edit writes the skill row
            # (a file edit records a version on it), so the lock serializes with each.
            existing = await skill_repo.lock(self.db, existing.id)
        plan = _refresh_plan(existing, bundled, replace_edited=replace_edited)
        if existing is None:
            await self._copy_library_skill(ctx, bundled, seeded=True)
        elif plan is LibraryRefresh.UPDATE and wait_for_check and await self._followed(existing):
            await self._propose_from_library(ctx, existing, bundled)
            return LibraryRefresh.WAITING
        elif plan is LibraryRefresh.UPDATE:
            await self._overwrite_from_library(
                ctx,
                existing,
                bundled,
                replaced_edits=_fingerprint_of(existing) != existing.library_fingerprint,
            )
        elif plan is LibraryRefresh.CURRENT and existing.library_fingerprint != bundled.fingerprint:
            # Says what the folder says, but was never stamped as saying it -
            # copied before fingerprints were kept. Stamp it, so the next release
            # can tell an untouched copy from an edited one.
            await skill_repo.update(
                self.db, skill=existing, update_data={"library_fingerprint": bundled.fingerprint}
            )
        return plan

    async def _propose_from_library(
        self, ctx: AuthContext, skill: Skill, bundled: skill_library.LibrarySkill
    ) -> None:
        """Leave the bundled version waiting as a proposal, once per bundled version.

        An earlier bundled version still waiting is withdrawn: the newer one says
        everything it did. One a person already decided is not offered again. The
        category is metadata no agent reads, so it follows the library at once.
        """
        earlier = await skill_proposal_repo.from_source(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            source=SkillVersionSource.LIBRARY.value,
        )
        if skill.category != bundled.category:
            unedited = _fingerprint_of(skill) == skill.library_fingerprint
            skill = await skill_repo.update(
                self.db, skill=skill, update_data={"category": bundled.category}
            )
            if unedited:
                await skill_repo.update(
                    self.db,
                    skill=skill,
                    update_data={"library_fingerprint": _fingerprint_of(skill)},
                )
        resources = {resource.name: resource.content for resource in bundled.resources}
        if any(
            (item.description, item.content, item.resources)
            == (bundled.description, bundled.content, resources)
            for item in earlier
        ):
            return
        from app.services.skill_check import SkillCheckService

        checks = SkillCheckService(self.db)
        for item in earlier:
            if item.status == ProposalStatus.PENDING.value:
                await skill_proposal_repo.decide_if(
                    self.db,
                    proposal_id=item.id,
                    organization_id=ctx.organization_id,
                    revision=item.revision,
                    status=ProposalStatus.DISCARDED,
                    decided_by=None,
                )
                await checks.stop_for_proposal(ctx, skill.id, item.id)
        proposal = await skill_proposal_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            agent_id=None,
            conversation_id=None,
            name=skill.name,
            description=bundled.description,
            content=bundled.content,
            resources=resources,
            base_version=skill.version,
            base_version_id=skill.latest_version_id,
            fork_id=None,
        )
        await skill_proposal_repo.annotate(
            self.db, proposal=proposal, values={"source": SkillVersionSource.LIBRARY.value}
        )

    async def _library_pair(
        self, ctx: AuthContext, key: str
    ) -> tuple[skill_library.LibrarySkill, Skill | None]:
        bundled = skill_library.get(key)
        if bundled is None:
            raise NotFoundError(message="No such bundled skill", details={"key": key})
        existing = await skill_repo.get_by_name(
            self.db, bundled.name, organization_id=ctx.organization_id
        )
        return bundled, existing

    async def _overwrite_from_library(
        self,
        ctx: AuthContext,
        skill: Skill,
        bundled: skill_library.LibrarySkill,
        *,
        replaced_edits: bool,
    ) -> None:
        for resource in list(skill.resources):
            await skill_repo.delete_resource(self.db, resource)
        # The loaded collection still holds the rows just deleted, and the update
        # below refreshes the skill - see `remove_resource` for what that did.
        self.db.expire(skill, ["resources"])
        for resource in bundled.resources:
            await skill_repo.create_resource(
                self.db,
                skill_id=skill.id,
                name=resource.name,
                description=None,
                content=resource.content,
            )
        updated = await skill_repo.update(
            self.db,
            skill=skill,
            update_data={
                "description": bundled.description,
                "content": bundled.content,
                "category": bundled.category,
                "library_fingerprint": bundled.fingerprint,
            },
        )
        await self.versions.record_main(ctx, updated, source=SkillVersionSource.LIBRARY)
        await self._changed(updated)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.refreshed",
            target_type="skill",
            target_id=str(skill.id),
            # What every bound agent executes changed, and `replaced_edits` is
            # the part somebody may go looking for: whether an operator chose to
            # take the bundled version over what the organization had written.
            details={
                "key": bundled.key,
                "name": bundled.name,
                "version": updated.version,
                "resources": len(bundled.resources),
                "seeded": True,
                "replaced_edits": replaced_edits,
            },
        )

    async def _copy_library_skill(
        self,
        ctx: AuthContext,
        bundled: skill_library.LibrarySkill,
        *,
        seeded: bool,
    ) -> Skill:
        """Write one library or gallery folder in as an ordinary skill.

        Shared by the seeding paths and by the gallery, because a copy is a copy
        - what differs is who is recorded as having made it. `seeded` is that
        difference and it is the audit entry's honesty: true means the platform
        wrote this as the organization's owner, false means a person chose it.
        """
        skill = await self.create(
            ctx,
            name=bundled.name,
            description=bundled.description,
            content=bundled.content,
            category=bundled.category,
            visibility=Visibility.ORG,
            library_fingerprint=bundled.fingerprint,
            source=None,
        )
        for resource in bundled.resources:
            await skill_repo.create_resource(
                self.db,
                skill_id=skill.id,
                name=resource.name,
                description=None,
                content=resource.content,
            )
        await self.versions.record_main(ctx, skill, source=SkillVersionSource.LIBRARY)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.installed",
            target_type="skill",
            target_id=str(skill.id),
            details={
                "key": bundled.key,
                "name": bundled.name,
                "resources": len(bundled.resources),
                "seeded": seeded,
            },
        )
        return skill

    async def gallery(self, ctx: AuthContext) -> SkillGallery:
        """The opt-in gallery, with what this organization already has marked.

        `installed` is matched on *name* rather than on key, which is the same
        rule installing uses: the organization owns its copy from the moment it
        lands, so a renamed folder in a later release must not offer a second
        copy of a skill somebody is already editing.
        """
        ids = await skill_repo.ids_by_name(self.db, organization_id=ctx.organization_id)
        return SkillGallery(
            industries=[
                GalleryIndustryRead(
                    id=industry.id,
                    skills=[
                        GallerySkillRead(
                            key=entry.key,
                            name=entry.name,
                            description=entry.description,
                            category=entry.category,
                            installed=entry.name in ids,
                            installed_id=ids.get(entry.name),
                        )
                        for entry in industry.skills
                    ],
                )
                for industry in skill_library.gallery()
            ]
        )

    async def used_in_run(self, ctx: AuthContext, run_id: UUID) -> list[RunSkillUseRead]:
        """The skills one run opened or read, by name and version, that the caller may see.

        The caller's access to the run itself is the route's to check.
        """
        uses = await skill_usage_repo.skills_of_run(
            self.db, organization_id=ctx.organization_id, run_id=run_id
        )
        skills = await skill_repo.get_many(
            self.db, [use.skill_id for use in uses], organization_id=ctx.organization_id
        )
        visible = await accessible_ids(
            self.db, ctx, list(skills.values()), Perm.SKILLS_VIEW, resource_type=SKILL
        )
        return [
            RunSkillUseRead(
                skill_id=use.skill_id,
                name=use.name,
                version=use.version,
                fork=use.fork,
                loaded=use.loaded,
            )
            for use in uses
            if use.skill_id in visible
        ]

    async def gallery_preview(self, key: str) -> GallerySkillPreview:
        """One gallery skill's body and files, read before it is installed.

        Raises:
            NotFoundError: No gallery skill has that key.
        """
        entry = skill_library.gallery_get(key)
        if entry is None:
            raise NotFoundError(message="No gallery skill has that key", details={"key": key})
        return GallerySkillPreview(
            key=entry.key,
            name=entry.name,
            description=entry.description,
            category=entry.category,
            content=entry.content,
            files=[resource.name for resource in entry.resources],
        )

    async def install_gallery(self, ctx: AuthContext, keys: Sequence[str]) -> GalleryInstallResult:
        """Copy gallery skills into this organization, as the caller.

        Not as the organization's owner, which is what the seeding paths do:
        somebody clicked this, so the audit entry names them and the skill is
        theirs to have chosen. There is no `seeded` flag on it for the same
        reason.

        Every outcome is reported rather than raised. A shelf of ten where one
        is already present must install the other nine, so an existing name is
        `skipped` and an unrecognised key is `unknown` - and a request that
        installs nothing is still a 200 describing why.
        """
        names = set(await skill_repo.list_names(self.db, organization_id=ctx.organization_id))
        installed: list[str] = []
        skipped: list[str] = []
        unknown: list[str] = []

        for key in dict.fromkeys(keys):
            entry = skill_library.gallery_get(key)
            if entry is None:
                unknown.append(key)
                continue
            if entry.name in names:
                skipped.append(entry.name)
                continue
            # Inside a SAVEPOINT, because the name check above is a read and two
            # members installing one shelf at the same time both pass it. The
            # loser's insert then violated `uq_skill_org_name` as an unhandled
            # IntegrityError, which rolled back every skill that request had
            # already copied - where the endpoint promises the shelf continues
            # and this entry is reported as `skipped`. The savepoint makes that
            # promise true: the conflict undoes this copy and nothing else.
            try:
                async with self.db.begin_nested():
                    await self._copy_library_skill(ctx, entry, seeded=False)
            except IntegrityError:
                logger.warning(
                    "Gallery skill %r was installed concurrently; reported as skipped", entry.key
                )
                skipped.append(entry.name)
                names.add(entry.name)
                continue
            # Two keys in one request can carry the same name only if the
            # gallery ships a duplicate; tracking it here keeps that a skip
            # rather than a unique-name violation mid-request.
            names.add(entry.name)
            installed.append(entry.name)

        return GalleryInstallResult(installed=installed, skipped=skipped, unknown=unknown)

    async def add_resource(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        *,
        name: str,
        description: str | None,
        content: str,
    ) -> SkillResource:
        """Attach a file to a skill.

        A skill is not only its body. The body says how the work is done; the
        files are the reference table, the template, the worked example - the
        detail that would bury the instructions if it were inlined and that the
        model loads only when it decides it needs it.

        Editing a skill makes a new main version, and so does this: every agent
        on main executes against the new set of files from its next run, which is
        the same fact an edit to the body reports.

        Raises:
            AlreadyExistsError: If a file of that name is already attached. The
                name is what the model asks for, so two of them is a reference
                nothing can resolve.
        """
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        if await skill_repo.get_resource_by_name(self.db, name, skill_id=skill.id):
            raise AlreadyExistsError(
                message=(
                    f"'{skill.name}' already has a file called '{name}'. The name is how the "
                    "model asks for it, so it has to be unique within the skill."
                ),
                details={"name": name},
            )
        resource = await skill_repo.create_resource(
            self.db,
            skill_id=skill.id,
            name=name,
            description=description,
            content=content,
        )
        await self._files_changed(ctx, skill)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.resource_added",
            target_type="skill",
            target_id=str(skill.id),
            details={"name": skill.name, "resource": name},
        )
        return resource

    async def put_resources(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        files: Sequence[tuple[str, bytes]],
        *,
        source: SkillVersionSource = SkillVersionSource.RESOURCES,
        proposal_id: UUID | None = None,
    ) -> list[SkillResource]:
        """Write a set of files at once - an upload of a folder, or of several.

        Named by relative path, so a folder keeps its shape: ``references/
        workflows.md`` is one resource whose name says where it sits. There are
        no folder rows and there is deliberately no folder table - a folder is
        a prefix that some file has, which means an empty one cannot exist and
        nothing has to keep the two in step.

        A path that already exists is replaced rather than refused. This is the
        upload path: somebody dragging a corrected folder in means the corrected
        version, and asking them to delete the old one first is asking them to
        do the merge by hand.

        Raises:
            BadRequestError: If a file is not text, or a path escapes the skill.
                Both are refused for the same reason - what the model is handed
                has to be readable, and a name is a key rather than a location
                on anybody's disk.
        """
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)

        written: list[SkillResource] = []
        for raw_name, raw_content in files:
            name = _clean_resource_path(raw_name)
            content = _decode_text(name, raw_content)

            existing = await skill_repo.get_resource_by_name(self.db, name, skill_id=skill.id)
            if existing is not None:
                written.append(
                    await skill_repo.update_resource(
                        self.db, resource=existing, update_data={"content": content}
                    )
                )
                continue
            written.append(
                await skill_repo.create_resource(
                    self.db,
                    skill_id=skill.id,
                    name=name,
                    description=None,
                    content=content,
                )
            )

        await self._files_changed(ctx, skill, source=source, proposal_id=proposal_id)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.resources_uploaded",
            target_type="skill",
            target_id=str(skill.id),
            details={"name": skill.name, "files": [resource.name for resource in written]},
        )
        return written

    async def get_resource(
        self, ctx: AuthContext, skill_id: UUID, resource_id: UUID
    ) -> SkillResource:
        """One file, with its body. Reached only through the skill that owns it."""
        skill = await self.get(ctx, skill_id)
        resource = await skill_repo.get_resource(self.db, resource_id, skill_id=skill.id)
        if resource is None:
            raise NotFoundError(message="File not found", details={"resource_id": str(resource_id)})
        return resource

    async def update_resource(
        self, ctx: AuthContext, skill_id: UUID, resource_id: UUID, data: SkillResourceUpdate
    ) -> SkillResource:
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        resource = await skill_repo.get_resource(self.db, resource_id, skill_id=skill.id)
        if resource is None:
            raise NotFoundError(message="File not found", details={"resource_id": str(resource_id)})
        updated = await skill_repo.update_resource(
            self.db, resource=resource, update_data=writable(data, over=SkillResource)
        )
        await self._files_changed(ctx, skill)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.resource_updated",
            target_type="skill",
            target_id=str(skill.id),
            details={"name": skill.name, "resource": resource.name},
        )
        return updated

    async def remove_resource(self, ctx: AuthContext, skill_id: UUID, resource_id: UUID) -> None:
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        resource = await skill_repo.get_resource(self.db, resource_id, skill_id=skill.id)
        if resource is None:
            raise NotFoundError(message="File not found", details={"resource_id": str(resource_id)})
        name = resource.name
        await skill_repo.delete_resource(self.db, resource)
        # `skill.resources` was loaded with the skill and still holds the row just deleted;
        # recording the version below refreshes the skill and SQLAlchemy refuses to refresh a
        # collection carrying a deleted instance ("Instance ... has been deleted"), which
        # answered every DELETE of a resource with a 500 and rolled the delete back
        # (2026-09-14). Expiring the collection makes the refresh reload it from the table.
        self.db.expire(skill, ["resources"])
        await self._files_changed(ctx, skill)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.resource_removed",
            target_type="skill",
            target_id=str(skill.id),
            details={"name": skill.name, "resource": name},
        )

    async def drop_resources(
        self, ctx: AuthContext, skill_id: UUID, *, keep: Collection[str]
    ) -> list[str]:
        """Delete every file not named in `keep`, recording no version: the caller writes
        the rest of the change and records it, so the set is one version.

        For a library update, whose files are the whole set the skill should have.
        """
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        stale = [resource for resource in skill.resources if resource.name not in keep]
        for resource in stale:
            await skill_repo.delete_resource(self.db, resource)
        if not stale:
            return []
        self.db.expire(skill, ["resources"])
        names = sorted(resource.name for resource in stale)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.resources_removed",
            target_type="skill",
            target_id=str(skill.id),
            details={"name": skill.name, "resources": names},
        )
        return names

    async def record_files(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        *,
        source: SkillVersionSource,
        proposal_id: UUID | None,
    ) -> None:
        """Record the skill's files as they stand as a main version."""
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        await self._files_changed(ctx, skill, source=source, proposal_id=proposal_id)

    async def _files_changed(
        self,
        ctx: AuthContext,
        skill: Skill,
        *,
        source: SkillVersionSource = SkillVersionSource.RESOURCES,
        proposal_id: UUID | None = None,
    ) -> None:
        """Record the new set of files as a main version.

        A file is part of the skill as far as an agent is concerned, so adding,
        editing or removing one is the same kind of event as editing the body -
        and a version that only moved for the body would say an agent was
        unchanged when its reference table had been rewritten.
        """
        await self.versions.record_main(ctx, skill, source=source, proposal_id=proposal_id)
        await self._changed(skill)

    async def _changed(self, skill: Skill) -> None:
        """Queue the eval suites of the agents that read this skill.

        A skill has no draft: an edit reaches every bound agent on its next run,
        so the suites watching for that change are the only check it gets.
        """
        from app.services.eval_suite import EvalSuiteService

        await EvalSuiteService(self.db).dependency_changed(
            organization_id=skill.organization_id, kind="skill", resource_id=skill.id
        )

    async def restore_main(
        self, ctx: AuthContext, skill: Skill, earlier: SkillVersion, files: dict[str, str]
    ) -> SkillVersion:
        """Make an earlier main version the newest one again, files and all.

        `skill` is locked by the caller, which has checked the person read the newest
        version. `files` are the earlier version's file bodies by name.
        """
        return await self._replace_main(
            ctx,
            skill,
            description=earlier.description,
            content=earlier.content,
            files=[
                SkillBodyFile(name=name, description=entry["description"], content=files[name])
                for name, entry in sorted(earlier.resources.items())
            ],
            source=SkillVersionSource.RESTORE,
            restored_from_id=earlier.id,
            action="skill.restored",
        )

    async def take_in(
        self,
        ctx: AuthContext,
        skill: Skill,
        *,
        description: str,
        content: str,
        files: Sequence[SkillBodyFile] | None,
        merged_from_id: UUID,
    ) -> SkillVersion:
        """Make a fork's changes, merged with main, main's newest version.

        `skill` is locked by the caller, which has checked main did not move since the
        merge. `files` is the whole set main has afterwards; `None` keeps main's own.
        """
        return await self._replace_main(
            ctx,
            skill,
            description=description,
            content=content,
            files=files,
            source=SkillVersionSource.FROM_FORK,
            merged_from_id=merged_from_id,
            action="skill.fork_taken_in",
        )

    async def _replace_main(
        self,
        ctx: AuthContext,
        skill: Skill,
        *,
        description: str,
        content: str,
        files: Sequence[SkillBodyFile] | None,
        source: SkillVersionSource,
        action: str,
        restored_from_id: UUID | None = None,
        merged_from_id: UUID | None = None,
    ) -> SkillVersion:
        if files is not None:
            for resource in list(skill.resources):
                await skill_repo.delete_resource(self.db, resource)
            # See `remove_resource`: the loaded collection still holds the deleted rows.
            self.db.expire(skill, ["resources"])
            for item in files:
                await skill_repo.create_resource(
                    self.db,
                    skill_id=skill.id,
                    name=item.name,
                    description=item.description,
                    content=item.content,
                )
        await skill_repo.update(
            self.db, skill=skill, update_data={"description": description, "content": content}
        )
        version = await self.versions.record_main(
            ctx,
            skill,
            source=source,
            restored_from_id=restored_from_id,
            merged_from_id=merged_from_id,
        )
        await self._changed(skill)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=action,
            target_type="skill",
            target_id=str(skill.id),
            details={"name": skill.name, "fork": None, "version": version.number},
        )
        return version

    async def read(self, ctx: AuthContext, skill: Skill) -> SkillRead:
        """A skill as its page reads it: what the caller may do, and how many forks it has."""
        forks = await skill_version_repo.count_active_forks(
            self.db, organization_id=ctx.organization_id, skill_ids=[skill.id]
        )
        return SkillRead.model_validate(skill).model_copy(
            update={
                "can_edit": await resolve_access(
                    self.db, ctx, skill, Perm.SKILLS_EDIT, resource_type=SKILL
                ),
                "forks": forks[skill.id],
            }
        )

    async def delete(
        self, ctx: AuthContext, skill_id: UUID, *, remove_from_agents: bool = False
    ) -> None:
        """Delete a skill nobody uses, with every version and fork it has.

        With `remove_from_agents`, the skill is first taken out of every agent that
        uses it, as :meth:`SkillAgentService.remove_skill` says, in the same
        transaction: either every agent loses it and it is deleted, or nothing
        changes.

        Raises:
            InUseError: A live agent's draft or a version an environment serves
                binds it. Those agents name the versions they run, which must not
                disappear from under them; the caller is told which agents, and
                how many more they may not see. With `remove_from_agents`, also
                which agents it could not be removed from, and why; or
                `reason: agents_changed` when an agent started using it while the
                agents were being locked.
        """
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        locked: set[UUID] = set()
        if remove_from_agents:
            # The skill first, then its agents, then the skill for the delete: the order a
            # check decision takes when it pins or moves an agent. A draft save locks its
            # agent and then holds the skill shared, which this first lock leaves free, so
            # the save finishes before the agent is locked here.
            await skill_repo.lock(self.db, skill.id)
            for agent in sorted(
                await agents_using_skill(
                    self.db, organization_id=ctx.organization_id, skill_id=skill.id
                ),
                key=lambda agent: agent.id,
            ):
                await agent_repo.get(
                    self.db, agent.id, organization_id=ctx.organization_id, for_update=True
                )
                locked.add(agent.id)
        # Locked before the in-use check: an agent binding the skill holds it shared
        # (`skill_repo.hold`), so a binding is either seen here or written after it is gone.
        await skill_repo.lock_for_delete(self.db, skill.id)
        using = await agents_using_skill(
            self.db, organization_id=ctx.organization_id, skill_id=skill.id
        )
        if using and remove_from_agents:
            if {agent.id for agent in using} - locked:
                raise InUseError(
                    message=(
                        f"Another agent started using '{skill.name}' while it was being "
                        "removed. Nothing changed; try again."
                    ),
                    details={"reason": "agents_changed"},
                )
            # Imported here: the agent registry reads skills through this service.
            from app.services.skill_agents import SkillAgentService

            await SkillAgentService(self.db).remove_skill(ctx, skill, using)
            using = await agents_using_skill(
                self.db, organization_id=ctx.organization_id, skill_id=skill.id
            )
        if using:
            visible = await accessible_ids(
                self.db, ctx, using, Perm.AGENTS_VIEW, resource_type=AGENT
            )
            named = [agent for agent in using if agent.id in visible]
            raise InUseError(
                message=(
                    f"'{skill.name}' is used by {in_use_by(named, len(using) - len(named))}. "
                    "Remove it from them, or let their owners do it, before deleting it."
                ),
                details={
                    "agents": [{"id": agent.id, "name": agent.name} for agent in named],
                    "hidden": len(using) - len(named),
                },
            )
        await resource_grant_repo.delete_for_resource(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=SKILL.key,
            resource_id=skill.id,
        )
        await skill_repo.delete(self.db, skill)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.deleted",
            target_type="skill",
            target_id=str(skill_id),
        )
