"""Skills - an organization's reusable know-how, stored in the database.

A skill is a piece of know-how written once and attached to many agents: how
refunds are handled, what the house style is, which checks a report must pass.
This module owns storage and access; turning skills into something an agent can
read is the skills *capability*.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import StringConstraints, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import catalog
from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.skill import Skill, SkillResource
from app.repositories import resource_grant_repo, skill_repo
from app.repositories.skill import SkillSort
from app.schemas.skill import (
    LibrarySkillList,
    LibrarySkillRead,
    SkillList,
    SkillResourceSummary,
    SkillSummary,
)
from app.services import skill_library
from app.services.access import SKILL, resolve_access, visible_resource_ids

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


def _summary(skill: Skill, bundled_names: frozenset[str]) -> SkillSummary:
    """A skill as the listing shows it.

    `built_in` is a name match against the shipped library because that is
    all installing keeps: an install copies the folder into an ordinary row,
    and the name - unique per organization, never editable - is the one trace
    of where it came from.
    """
    return SkillSummary(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        category=skill.category,
        enabled=skill.enabled,
        file_count=len(skill.resources),
        built_in=skill.name in bundled_names,
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


class SkillService:
    """Manage an organization's skills."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(
        self, ctx: AuthContext, skill_id: UUID, *, perm: Perm = Perm.SKILLS_VIEW
    ) -> Skill:
        skill = await skill_repo.get(self.db, skill_id, organization_id=ctx.organization_id)
        if skill is None:
            raise NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
        if not await resolve_access(self.db, ctx, skill, perm, resource_type=SKILL):
            raise NotFoundError(message="Skill not found", details={"skill_id": str(skill_id)})
        return skill

    async def list_skills(
        self,
        ctx: AuthContext,
        *,
        shared_with_me: bool = False,
        search: str | None = None,
        categories: Sequence[str] | None = None,
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
        or explicitly granted, and not their own.
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
        """
        items, total = await self.list_skills(
            ctx,
            shared_with_me=shared_with_me,
            search=search,
            categories=categories,
            sort=sort,
            skip=skip,
            limit=limit,
        )
        bundled_names = frozenset(entry.name for entry in skill_library.library())
        return SkillList(
            items=[_summary(skill, bundled_names) for skill in items],
            total=total,
            categories=await self.list_categories(ctx),
            suggested_categories=list(SUGGESTED_CATEGORIES),
        )

    async def list_library(self, ctx: AuthContext) -> LibrarySkillList:
        """The skills this deployment ships with, each marked installed or not.

        `installed` answers exactly one question - is this name already taken in
        this organization - because that is the only question the Install button
        leads to. It used to be derived from `list_skills(ctx, limit=100)`, which
        is a *page* of what *this caller may see*, and both halves of that were
        wrong:

        - a page. An organization past its alphabetically hundredth skill lost
          every name after it, so a taken name read as free.
        - visibility-scoped. An install lands `private`
          (:class:`app.db.models.skill.Skill`), so a skill another member
          installed is invisible to anyone whose `SKILLS_VIEW` scope is not
          `ALL`. Their gallery offered an Install, and
          :meth:`install_from_library` refused it with a 409 naming a skill they
          cannot open.

        The rule behind that refusal is `skill_repo.get_by_name` - organization
        wide, visibility-blind - so this asks the same query rather than a
        listing that happens to overlap with it.

        The gallery drops what is installed rather than greying it out, so a name
        somebody else took simply stops being offered. There is deliberately no
        link to the existing skill: the caller may have no access to it, and a
        card that leads to a 404 is a worse answer than no card.
        """
        taken = await skill_repo.names_in_use(self.db, organization_id=ctx.organization_id)
        items = [
            LibrarySkillRead(
                key=bundled.key,
                name=bundled.name,
                description=bundled.description,
                category=bundled.category,
                content=bundled.content,
                resources=[
                    SkillResourceSummary(
                        id=uuid5(NAMESPACE_URL, f"{bundled.key}/{resource.name}"),
                        name=resource.name,
                        description=None,
                        size_bytes=resource.size_bytes,
                    )
                    for resource in bundled.resources
                ],
                installed=bundled.name in taken,
            )
            for bundled in skill_library.library()
        ]
        return LibrarySkillList(items=items, total=len(items))

    async def list_categories(self, ctx: AuthContext) -> list[str]:
        """Every distinct category in this organization, for the listing's filter."""
        return await skill_repo.list_categories(self.db, organization_id=ctx.organization_id)

    async def resolve_for_agent(self, ctx: AuthContext, skill_ids: list[UUID]) -> list[Skill]:
        """The enabled skills an agent is bound to.

        Scoped to the run's organization and **not** to the runner's own access,
        which is deliberate and is the same rule delegates and collections follow:
        the binding is checked once, against the publisher, when the agent is
        published, and the agent then reads it for everyone who may run it. See
        `_skill_problems` in `app/services/agent_registry.py` for the check.

        Re-checking here would be wrong twice over. `resolve_access` refuses every
        context with no subject, so an API key, an embedded widget and a channel
        message - the surfaces this platform exists to serve - would each lose
        every skill the agent has. And where there *is* a subject, an agent's
        instructions would change with who asked: a member or a viewer, whose role
        gives `SKILLS_VIEW: Scope.SHARED`, would get a thinner answer out of the
        same published version than a builder does, with the difference visible
        nowhere.

        A skill deleted or disabled after publish is skipped rather than failing
        the run: the agent is less capable, not broken. Named in the log with the
        organization, because from inside one tenant a row that was deleted and a
        row that belongs to another tenant leave the same absence - and the second
        is a spec somebody should look at rather than a skill somebody removed.
        """
        if not skill_ids:
            return []
        found = await skill_repo.get_many(self.db, skill_ids, organization_id=ctx.organization_id)
        resolved = []
        for skill_id in skill_ids:
            skill = found.get(skill_id)
            if skill is None or not skill.enabled:
                logger.warning(
                    "Agent references skill %s which is disabled, deleted, or not org %s's",
                    skill_id,
                    ctx.organization_id,
                )
                continue
            resolved.append(skill)
        return resolved

    async def create(
        self,
        ctx: AuthContext,
        *,
        name: str,
        description: str,
        content: str,
        category: str | None = None,
    ) -> Skill:
        """Create a skill.

        Raises:
            AlreadyExistsError: If the name is taken. Names are how the model
                refers to a skill, so two with one name is an ambiguity the
                agent cannot resolve.
        """
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
        return skill

    async def update(self, ctx: AuthContext, skill_id: UUID, update_data: dict) -> Skill:
        """Edit a skill, bumping its version.

        The version is informational - agents bind to a skill, not a version, so
        an edit reaches every agent immediately. That is the point of skills:
        fix the policy once.
        """
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        update_data = {**update_data, "version": skill.version + 1}
        updated = await skill_repo.update(self.db, skill=skill, update_data=update_data)
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

        Raises:
            NotFoundError: If no such skill ships with this deployment.
            AlreadyExistsError: If the organization already has one by that
                name - installing twice would otherwise produce a second skill
                the model cannot tell from the first.
        """
        bundled = skill_library.get(key)
        if bundled is None:
            raise NotFoundError(message="No such bundled skill", details={"key": key})

        skill = await self.create(
            ctx,
            name=bundled.name,
            description=bundled.description,
            content=bundled.content,
            category=bundled.category,
        )
        for resource in bundled.resources:
            await skill_repo.create_resource(
                self.db,
                skill_id=skill.id,
                name=resource.name,
                description=None,
                content=resource.content,
            )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.installed",
            target_type="skill",
            target_id=str(skill.id),
            details={"key": key, "name": bundled.name, "resources": len(bundled.resources)},
        )
        return skill

    # -- resources -------------------------------------------------------

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

        Editing a skill bumps its version, and so does this: every bound agent
        executes against the new set of files from its next run, which is the
        same fact an edit to the body reports.

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
                details={"name": name, "field": "name"},
            )
        resource = await skill_repo.create_resource(
            self.db,
            skill_id=skill.id,
            name=name,
            description=description,
            content=content,
        )
        await self._bump_version(skill)
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

        await self._bump_version(skill)
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
        self, ctx: AuthContext, skill_id: UUID, resource_id: UUID, update_data: dict
    ) -> SkillResource:
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
        resource = await skill_repo.get_resource(self.db, resource_id, skill_id=skill.id)
        if resource is None:
            raise NotFoundError(message="File not found", details={"resource_id": str(resource_id)})
        updated = await skill_repo.update_resource(
            self.db, resource=resource, update_data=update_data
        )
        await self._bump_version(skill)
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
        await self._bump_version(skill)
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.resource_removed",
            target_type="skill",
            target_id=str(skill.id),
            details={"name": skill.name, "resource": name},
        )

    async def _bump_version(self, skill: Skill) -> None:
        """Record that what bound agents execute has changed.

        A file is part of the skill as far as an agent is concerned, so adding,
        editing or removing one is the same kind of event as editing the body -
        and a version that only moved for the body would say an agent was
        unchanged when its reference table had been rewritten.
        """
        await skill_repo.update(self.db, skill=skill, update_data={"version": skill.version + 1})

    async def delete(self, ctx: AuthContext, skill_id: UUID) -> None:
        skill = await self.get(ctx, skill_id, perm=Perm.SKILLS_EDIT)
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
