"""Skill versions and forks: the one place a version is written, and how they are read.

Every change to a skill that an agent would notice - its text, its description or a
file - ends in :meth:`SkillVersionService.record_main` or
:meth:`SkillVersionService.record_fork`. Main-line changes are written to the
`skills` row first, by `SkillService`, which then records the row as it stands; a
fork has no row of its own, so its text goes straight into the version. Both lock
the line before numbering, so two saves at once get consecutive numbers instead of
one losing to the unique index.

See `app/db/models/skill_version.py` for the model.
"""

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.exceptions import (
    AlreadyExistsError,
    ConcurrentChangeError,
    ConflictError,
    InUseError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.skill import Skill
from app.db.models.skill_version import (
    ManifestEntry,
    SkillFork,
    SkillVersion,
    SkillVersionSource,
)
from app.repositories import member_repo, skill_repo, skill_version_repo
from app.schemas.skill import SkillUpdate
from app.schemas.skill_version import (
    PersonRef,
    SkillForkCreate,
    SkillForkList,
    SkillForkRead,
    SkillForkUpdate,
    SkillVersionCreate,
    SkillVersionList,
    SkillVersionRead,
    SkillVersionRestore,
    SkillVersionSummary,
    VersionNumberRef,
    VersionRef,
    VersionResourceRead,
    VersionResourceSummary,
)
from app.services.access import AGENT, SKILL, accessible_ids, resolve_access
from app.services.resource_usage import in_use_by

ARCHIVE_AFTER = timedelta(days=30)
"""How long a fork goes unread before it is offered for archiving. Never archived by itself."""


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def manifest_of(
    files: Iterable[tuple[str, str | None, str]],
) -> tuple[dict[str, ManifestEntry], dict[str, str]]:
    """Files given as `(name, description, content)`, as a version records them, and
    the bodies to store by hash."""
    manifest: dict[str, ManifestEntry] = {}
    bodies: dict[str, str] = {}
    for name, description, content in files:
        sha256 = _sha256(content)
        manifest[name] = ManifestEntry(
            sha256=sha256, description=description, size_bytes=len(content.encode("utf-8"))
        )
        bodies[sha256] = content
    return manifest, bodies


def changes_since(main: Sequence[tuple[int, str]]) -> dict[int, int]:
    """For each of main's versions, how many after it changed what the skill says.

    `main` is main's versions with the hash of what each says, oldest first, up to the
    newest. A version saying what the one before it said - a restore of the same text -
    is no change, and a version saying what the newest says is behind by none.
    """
    behind: dict[int, int] = {}
    changes = 0
    later: str | None = None
    for number, said in reversed(main):
        if later is not None and said != later:
            changes += 1
        later = said
        behind[number] = 0 if said == main[-1][1] else changes
    return behind


def _ref(version: SkillVersion | None) -> VersionRef | None:
    if version is None:
        return None
    return VersionRef(id=version.id, number=version.number, fork_id=version.fork_id)


class SkillVersionService:
    """Write versions and forks of an organization's skills, and read them back."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_main(
        self,
        ctx: AuthContext,
        skill: Skill,
        *,
        source: SkillVersionSource,
        proposal_id: UUID | None = None,
        restored_from_id: UUID | None = None,
        merged_from_id: UUID | None = None,
    ) -> SkillVersion:
        """Record the `skills` row as it stands now as the next main version.

        Locks the row, which also re-reads it with its files: the version is what
        the row says once every write before this one in the transaction landed.
        """
        locked = await skill_repo.lock(self.db, skill.id)
        if locked is None:
            raise NotFoundError(message="Skill not found", details={"skill_id": skill.id})
        manifest, bodies = manifest_of(
            (resource.name, resource.description, resource.content) for resource in locked.resources
        )
        await skill_version_repo.put_files(
            self.db, organization_id=locked.organization_id, skill_id=locked.id, bodies=bodies
        )
        number = (
            await skill_version_repo.latest_number(
                self.db, organization_id=locked.organization_id, skill_id=locked.id, fork_id=None
            )
            + 1
        )
        version = await skill_version_repo.create_version(
            self.db,
            organization_id=locked.organization_id,
            skill_id=locked.id,
            fork_id=None,
            number=number,
            description=locked.description,
            content=locked.content,
            resources=manifest,
            source=source.value,
            restored_from_id=restored_from_id,
            merged_from_id=merged_from_id,
            proposal_id=proposal_id,
            library_fingerprint=(
                locked.library_fingerprint if source is SkillVersionSource.LIBRARY else None
            ),
            created_by_user_id=ctx.user_id,
        )
        await skill_repo.update(
            self.db,
            skill=locked,
            update_data={"version": number, "latest_version_id": version.id},
        )
        return version

    async def record_fork(
        self,
        ctx: AuthContext,
        fork: SkillFork,
        *,
        description: str,
        content: str,
        resources: dict[str, ManifestEntry],
        source: SkillVersionSource,
        proposal_id: UUID | None = None,
        restored_from_id: UUID | None = None,
        merged_from_id: UUID | None = None,
    ) -> SkillVersion:
        """Record the next version of a fork, whose row the caller holds locked."""
        number = (
            await skill_version_repo.latest_number(
                self.db,
                organization_id=fork.organization_id,
                skill_id=fork.skill_id,
                fork_id=fork.id,
            )
            + 1
        )
        version = await skill_version_repo.create_version(
            self.db,
            organization_id=fork.organization_id,
            skill_id=fork.skill_id,
            fork_id=fork.id,
            number=number,
            description=description,
            content=content,
            resources=resources,
            source=source.value,
            restored_from_id=restored_from_id,
            merged_from_id=merged_from_id,
            proposal_id=proposal_id,
            library_fingerprint=None,
            created_by_user_id=ctx.user_id,
        )
        await skill_version_repo.update_fork(
            self.db, fork=fork, update_data={"latest_version_id": version.id}
        )
        # Imported here: the eval suites reach the agent runner, which reads skills.
        from app.services.eval_suite import EvalSuiteService

        await EvalSuiteService(self.db).dependency_changed(
            organization_id=fork.organization_id,
            kind="skill",
            resource_id=fork.skill_id,
            fork_id=fork.id,
        )
        return version

    @staticmethod
    def line_latest(skill: Skill, fork: SkillFork | None) -> UUID | None:
        """The version a line serves now: main's newest, or the fork's, or its base."""
        if fork is None:
            return skill.latest_version_id
        return fork.latest_version_id or fork.base_version_id

    async def skill_for(self, ctx: AuthContext, skill_id: UUID, perm: Perm) -> Skill:
        """The skill, or 404 - for a missing one and one the caller may not `perm` alike."""
        skill = await skill_repo.get(self.db, skill_id, organization_id=ctx.organization_id)
        if skill is None or not await resolve_access(
            self.db, ctx, skill, perm, resource_type=SKILL
        ):
            raise NotFoundError(message="Skill not found", details={"skill_id": skill_id})
        return skill

    async def _version(self, ctx: AuthContext, skill: Skill, version_id: UUID) -> SkillVersion:
        version = await skill_version_repo.get_version(
            self.db, version_id, organization_id=ctx.organization_id, skill_id=skill.id
        )
        if version is None:
            raise NotFoundError(message="Version not found", details={"version_id": version_id})
        return version

    async def _fork(
        self, ctx: AuthContext, skill: Skill, fork_id: UUID, *, lock: bool = False
    ) -> SkillFork:
        """The skill's fork, or 404. Locked, it is taken after the skill itself.

        Applying a proposal locks the skill and then the fork, so every writer of a
        fork takes the two in that order: two of them wait for each other instead of
        deadlocking.
        """
        if lock:
            await skill_repo.lock(self.db, skill.id)
        fork = await skill_version_repo.get_fork(
            self.db, fork_id, organization_id=ctx.organization_id, skill_id=skill.id, lock=lock
        )
        if fork is None:
            raise NotFoundError(message="Fork not found", details={"fork_id": fork_id})
        return fork

    async def people(
        self, ctx: AuthContext, user_ids: Sequence[UUID | None]
    ) -> dict[UUID, PersonRef]:
        """Who made what, for a caller who may read the member directory. Somebody who
        is no longer a member keeps their id and loses their name."""
        wanted = sorted({user_id for user_id in user_ids if user_id is not None})
        if not wanted or not ctx.has(Perm.MEMBERS_VIEW):
            return {}
        names = await member_repo.get_names_for_users(
            self.db, organization_id=ctx.organization_id, user_ids=wanted
        )
        return {user_id: PersonRef(id=user_id, name=names.get(user_id)) for user_id in wanted}

    async def _summaries(
        self, ctx: AuthContext, skill: Skill, versions: Sequence[SkillVersion]
    ) -> list[SkillVersionSummary]:
        """One line's versions with what each points at: the one before it, and what
        it restored. A fork's first version comes after the main version it started from."""
        if not versions:
            return []
        fork_id = versions[0].fork_id
        before = await skill_version_repo.get_by_numbers(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            fork_id=fork_id,
            numbers={version.number - 1 for version in versions if version.number > 1},
        )
        fork_base = None
        if fork_id is not None and any(version.number == 1 for version in versions):
            fork = await self._fork(ctx, skill, fork_id)
            fork_base = await self._version(ctx, skill, fork.started_from_id)
        others = await skill_version_repo.get_versions(
            self.db,
            {version.restored_from_id for version in versions if version.restored_from_id}
            | {version.merged_from_id for version in versions if version.merged_from_id},
            organization_id=ctx.organization_id,
        )
        people = await self.people(ctx, [version.created_by_user_id for version in versions])
        by_version, _ = await self._counts(skill)
        return [
            SkillVersionSummary(
                id=version.id,
                skill_id=version.skill_id,
                fork_id=version.fork_id,
                number=version.number,
                source=SkillVersionSource(version.source),
                previous=_ref(fork_base if version.number == 1 else before.get(version.number - 1)),
                restored_from=_ref(
                    others.get(version.restored_from_id) if version.restored_from_id else None
                ),
                merged_from=_ref(
                    others.get(version.merged_from_id) if version.merged_from_id else None
                ),
                proposal_id=version.proposal_id,
                created_by=(
                    people.get(version.created_by_user_id) if version.created_by_user_id else None
                ),
                created_at=version.created_at,
                agents=by_version[version.id],
            )
            for version in versions
        ]

    async def list_versions(
        self,
        ctx: AuthContext,
        skill_id: UUID,
        *,
        fork_id: UUID | None,
        skip: int = 0,
        limit: int = 50,
    ) -> SkillVersionList:
        """One line's versions, newest first: main's, or a fork's own."""
        skill = await self.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        if fork_id is not None:
            await self._fork(ctx, skill, fork_id)
        versions, total = await skill_version_repo.list_versions(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            fork_id=fork_id,
            skip=skip,
            limit=limit,
        )
        return SkillVersionList(items=await self._summaries(ctx, skill, versions), total=total)

    async def read_version(
        self, ctx: AuthContext, skill_id: UUID, version_id: UUID
    ) -> SkillVersionRead:
        """One version with its text and the list of its files."""
        skill = await self.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        version = await self._version(ctx, skill, version_id)
        return await self._read(ctx, skill, version)

    async def _read(
        self, ctx: AuthContext, skill: Skill, version: SkillVersion
    ) -> SkillVersionRead:
        [summary] = await self._summaries(ctx, skill, [version])
        return SkillVersionRead(
            **summary.model_dump(),
            description=version.description,
            content=version.content,
            resources=[
                VersionResourceSummary(
                    name=name,
                    description=entry["description"],
                    size_bytes=entry["size_bytes"],
                    digest=entry["sha256"],
                )
                for name, entry in sorted(version.resources.items())
            ],
        )

    async def read_resource(
        self, ctx: AuthContext, skill_id: UUID, version_id: UUID, name: str
    ) -> VersionResourceRead:
        """One file of a version, as that version had it."""
        skill = await self.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        version = await self._version(ctx, skill, version_id)
        entry = version.resources.get(name)
        bodies = (
            {}
            if entry is None
            else await skill_version_repo.get_files(
                self.db,
                organization_id=ctx.organization_id,
                skill_id=skill.id,
                hashes=[entry["sha256"]],
            )
        )
        if entry is None or entry["sha256"] not in bodies:
            raise NotFoundError(message="File not found", details={"name": name})
        return VersionResourceRead(
            name=name, description=entry["description"], content=bodies[entry["sha256"]]
        )

    async def files_of(self, version: SkillVersion) -> dict[str, str]:
        """A version's file bodies by name."""
        bodies = await skill_version_repo.get_files(
            self.db,
            organization_id=version.organization_id,
            skill_id=version.skill_id,
            hashes=[entry["sha256"] for entry in version.resources.values()],
        )
        return {name: bodies[entry["sha256"]] for name, entry in version.resources.items()}

    async def edit(
        self, ctx: AuthContext, skill_id: UUID, data: SkillVersionCreate
    ) -> SkillVersionRead:
        """Save an edit of the text as a new version on one line.

        Raises:
            ConcurrentChangeError: The line has a newer version than the one read.
            ConflictError: The fork is archived.
        """
        from app.services.skills import SkillService

        skill = await self.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        if data.fork_id is None:
            locked = await skill_repo.lock(self.db, skill.id)
            assert locked is not None, "the skill was read in this transaction"
            self._refuse_moved(data.base_version_id, locked.latest_version_id)
            updated = await SkillService(self.db).update(
                ctx, skill.id, SkillUpdate(description=data.description, content=data.content)
            )
            assert updated.latest_version_id is not None, "a skill always has a main version"
            return await self._read(
                ctx, skill, await self._version(ctx, skill, updated.latest_version_id)
            )
        fork = await self._fork(ctx, skill, data.fork_id, lock=True)
        self.refuse_archived(fork)
        latest = self.line_latest(skill, fork)
        self._refuse_moved(data.base_version_id, latest)
        assert latest is not None, "a fork serves at least its base"
        current = await self._version(ctx, skill, latest)
        if (data.description, data.content) == (current.description, current.content):
            return await self._read(ctx, skill, current)
        version = await self.record_fork(
            ctx,
            fork,
            description=data.description,
            content=data.content,
            resources=current.resources,
            source=SkillVersionSource.EDIT,
        )
        await self._audit(ctx, skill, "skill.fork_edited", fork=fork, version=version)
        return await self._read(ctx, skill, version)

    async def restore(
        self, ctx: AuthContext, skill_id: UUID, version_id: UUID, data: SkillVersionRestore
    ) -> SkillVersionRead:
        """Bring an earlier version back as the newest of its own line.

        Raises:
            ConcurrentChangeError: The line has a newer version than the one read.
            ConflictError: The version's fork is archived.
        """
        from app.services.skills import SkillService

        skill = await self.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        earlier = await self._version(ctx, skill, version_id)
        if earlier.fork_id is None:
            locked = await skill_repo.lock(self.db, skill.id)
            assert locked is not None, "the skill was read in this transaction"
            self._refuse_moved(data.base_version_id, locked.latest_version_id)
            version = await SkillService(self.db).restore_main(
                ctx, locked, earlier, await self.files_of(earlier)
            )
            return await self._read(ctx, skill, version)
        fork = await self._fork(ctx, skill, earlier.fork_id, lock=True)
        self.refuse_archived(fork)
        self._refuse_moved(data.base_version_id, self.line_latest(skill, fork))
        version = await self.record_fork(
            ctx,
            fork,
            description=earlier.description,
            content=earlier.content,
            resources=earlier.resources,
            source=SkillVersionSource.RESTORE,
            restored_from_id=earlier.id,
        )
        await self._audit(ctx, skill, "skill.restored", fork=fork, version=version)
        return await self._read(ctx, skill, version)

    @staticmethod
    def _refuse_moved(read: UUID, latest: UUID | None) -> None:
        if read != latest:
            raise ConcurrentChangeError(
                message=(
                    "This skill has a newer version than the one you read. Open the newest "
                    "version and make your change there."
                ),
                details={"base_version_id": read, "latest_version_id": latest},
            )

    @staticmethod
    def refuse_archived(fork: SkillFork) -> None:
        if fork.archived_at is not None:
            raise ConflictError(
                message=f"The fork '{fork.name}' is archived, so it takes no new versions",
                details={"fork_id": fork.id},
            )

    async def list_forks(
        self, ctx: AuthContext, skill_id: UUID, *, archived: bool = False
    ) -> SkillForkList:
        skill = await self.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        forks = await skill_version_repo.list_forks(
            self.db, organization_id=ctx.organization_id, skill_id=skill.id, archived=archived
        )
        items = await self._fork_reads(ctx, skill, forks)
        return SkillForkList(items=items, total=len(items))

    async def _fork_reads(
        self, ctx: AuthContext, skill: Skill, forks: Sequence[SkillFork]
    ) -> list[SkillForkRead]:
        ids = [fork.id for fork in forks]
        changes = await skill_version_repo.count_versions(
            self.db, organization_id=ctx.organization_id, fork_ids=ids
        )
        versions = await skill_version_repo.get_versions(
            self.db,
            {fork.base_version_id for fork in forks}
            | {fork.started_from_id for fork in forks}
            | {fork.latest_version_id for fork in forks if fork.latest_version_id},
            organization_id=ctx.organization_id,
        )
        now = datetime.now(UTC)
        served = await skill_version_repo.forks_served_since(
            self.db, organization_id=ctx.organization_id, fork_ids=ids, since=now - ARCHIVE_AFTER
        )
        people = await self.people(ctx, [fork.created_by_user_id for fork in forks])
        _, by_fork = await self._counts(skill)
        behind = changes_since(
            await skill_version_repo.main_digests(
                self.db,
                organization_id=ctx.organization_id,
                skill_id=skill.id,
                first=min(versions[fork.base_version_id].number for fork in forks),
                last=skill.version,
            )
            if forks
            else []
        )
        reads = []
        for fork in forks:
            base, started = versions[fork.base_version_id], versions[fork.started_from_id]
            latest = versions.get(fork.latest_version_id) if fork.latest_version_id else None
            reads.append(
                SkillForkRead(
                    id=fork.id,
                    skill_id=fork.skill_id,
                    name=fork.name,
                    base=VersionNumberRef(id=base.id, number=base.number),
                    started_from=VersionNumberRef(id=started.id, number=started.number),
                    latest=None
                    if latest is None
                    else VersionNumberRef(id=latest.id, number=latest.number),
                    changes=changes[fork.id],
                    behind_main=behind.get(base.number, 0),
                    agents=by_fork[fork.id],
                    archive_candidate=(
                        fork.archived_at is None
                        and fork.created_at < now - ARCHIVE_AFTER
                        and fork.id not in served
                        and not by_fork[fork.id]
                    ),
                    archived_at=fork.archived_at,
                    created_by=(
                        people.get(fork.created_by_user_id) if fork.created_by_user_id else None
                    ),
                    created_at=fork.created_at,
                )
            )
        return reads

    async def create_fork(
        self, ctx: AuthContext, skill_id: UUID, data: SkillForkCreate
    ) -> SkillForkRead:
        """Start a fork from a main version. It serves that version until it has its own.

        Raises:
            BadRequestError: The version is a fork's - a fork starts only from main.
            AlreadyExistsError: The skill already has a fork of that name.
        """
        skill = await self.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        base = await self._version(ctx, skill, data.from_version_id)
        if base.fork_id is not None:
            raise refused_field(
                "from_version_id",
                "A fork starts from a version of the main line, not from another fork",
            )
        await skill_repo.lock(self.db, skill.id)
        await self._refuse_taken(ctx, skill, data.name)
        fork = await skill_version_repo.create_fork(
            self.db,
            organization_id=ctx.organization_id,
            skill_id=skill.id,
            name=data.name,
            base_version_id=base.id,
            created_for_agent_id=None,
            created_by_user_id=ctx.user_id,
        )
        await self._audit(ctx, skill, "skill.fork_created", fork=fork, version=base)
        [read] = await self._fork_reads(ctx, skill, [fork])
        return read

    async def rename_fork(
        self, ctx: AuthContext, skill_id: UUID, fork_id: UUID, data: SkillForkUpdate
    ) -> SkillForkRead:
        skill = await self.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        fork = await self._fork(ctx, skill, fork_id, lock=True)
        if data.name != fork.name:
            await self._refuse_taken(ctx, skill, data.name)
            fork = await skill_version_repo.update_fork(
                self.db, fork=fork, update_data={"name": data.name}
            )
        [read] = await self._fork_reads(ctx, skill, [fork])
        return read

    async def archive_fork(self, ctx: AuthContext, skill_id: UUID, fork_id: UUID) -> SkillForkRead:
        """Archive a fork: it takes no new versions, and no agent can be moved onto it.

        Raises:
            InUseError: An agent reads the fork, in a served version or its draft;
                it is moved first, so no agent is left on a line that takes no fix.
        """
        from app.services.skill_agents import SkillAgentService

        skill = await self.skill_for(ctx, skill_id, Perm.SKILLS_EDIT)
        fork = await self._fork(ctx, skill, fork_id, lock=True)
        using = await SkillAgentService(self.db).fork_users(skill, fork.id)
        if fork.archived_at is None and using:
            visible = await accessible_ids(
                self.db, ctx, using, Perm.AGENTS_VIEW, resource_type=AGENT
            )
            named = [agent for agent in using if agent.id in visible]
            raise InUseError(
                message=(
                    f"'{fork.name}' is read by {in_use_by(named, len(using) - len(named))}. "
                    "Move them to another version before archiving it."
                ),
                details={
                    "agents": [{"id": agent.id, "name": agent.name} for agent in named],
                    "hidden": len(using) - len(named),
                },
            )
        if fork.archived_at is None:
            fork = await skill_version_repo.update_fork(
                self.db,
                fork=fork,
                update_data={"archived_at": datetime.now(UTC), "archived_by_user_id": ctx.user_id},
            )
            await self._audit(ctx, skill, "skill.fork_archived", fork=fork, version=None)
        [read] = await self._fork_reads(ctx, skill, [fork])
        return read

    async def _counts(self, skill: Skill) -> tuple[Counter[UUID], Counter[UUID]]:
        """How many agents' served versions read each version and each fork."""
        # Imported here: the agents of a skill read the registry, which reads skills.
        from app.services.skill_agents import SkillAgentService

        return await SkillAgentService(self.db).counts(skill)

    async def _refuse_taken(self, ctx: AuthContext, skill: Skill, name: str) -> None:
        """Refuse a fork name the skill has. The caller holds the skill locked, so two
        requests for one name serialize here instead of the second hitting the index."""
        if await skill_version_repo.get_fork_by_name(
            self.db, name, organization_id=ctx.organization_id, skill_id=skill.id
        ):
            raise AlreadyExistsError(
                message=f"'{skill.name}' already has a fork called '{name}'",
                details={"name": name},
            )

    async def _audit(
        self,
        ctx: AuthContext,
        skill: Skill,
        action: str,
        *,
        fork: SkillFork | None,
        version: SkillVersion | None,
    ) -> None:
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action=action,
            target_type="skill",
            target_id=str(skill.id),
            details={
                "name": skill.name,
                "fork": None if fork is None else fork.name,
                "version": None if version is None else version.number,
            },
        )
