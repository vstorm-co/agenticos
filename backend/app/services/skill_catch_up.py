"""Catching pinned agents and forks up with main, and moving a fork's changes to main.

Nothing here runs by itself. Every catch-up costs a check on the agents it moves,
so main moving on only marks who it left behind; a person decides which of them
to bring along, and when.

A fork catches up, or moves to main, in an improvement session whose purpose says
so. The session merges the three texts here when it starts, the model proposes a
text for each conflict, a person settles the rest at Changes, and the check measures
what the merge says. Accepting refuses once either line moved past the merge.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

import anyio
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.skills import SkillBodyFile
from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.spec import AgentSpec
from app.core.audit import record_audit
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    ConflictError,
    NotFoundError,
)
from app.core.exceptions import ValidationError as TooLargeToMerge
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, Perm
from app.db.models.agent import Agent, AgentStatus, AgentVersion
from app.db.models.agent_environment import AgentEnvironment
from app.db.models.improvement import ImprovementStage, ImprovementStatus
from app.db.models.skill import Skill
from app.db.models.skill_improvement import SkillImprovementPurpose, SkillImprovementRun
from app.db.models.skill_merge import MergedFile, MergedPart, SkillMerge
from app.db.models.skill_version import ManifestEntry, SkillFork, SkillVersion, SkillVersionSource
from app.repositories import (
    agent_environment_repo,
    agent_repo,
    skill_improvement_repo,
    skill_merge_repo,
    skill_repo,
    skill_version_repo,
)
from app.schemas.resource_usage import AgentUsage
from app.schemas.skill_merge import (
    MergeDescriptionEdit,
    MergeFilePick,
    MergeFileRead,
    MergeFileSide,
    MergePartEdit,
    MergeTextRead,
    SkillMergeRead,
)
from app.schemas.skill_version import (
    BehindMain,
    BehindMainList,
    ForkRef,
    ReturnedAgent,
    ReturnedToMain,
    ReturnToMain,
    SkillBindingChange,
    SkillRef,
    VersionNumberRef,
)
from app.services.access import AGENT, SKILL, accessible_ids, resolve_access
from app.services.agent_registry import delegation_binding
from app.services.skill_agents import Line, SkillAgentService, lines_of
from app.services.skill_merge import (
    MAX_LINES,
    MergePart,
    MergeTooLarge,
    PartState,
    merge_files,
    merge_text,
    merge_value,
)
from app.services.skill_versions import SkillVersionService, changes_since


@dataclass(frozen=True)
class _Read:
    """One agent reading one skill off main's newest: pinned to a version, or a fork."""

    agent_id: UUID
    skill_id: UUID
    line: Line


_DESCRIPTION_CHARS = 500
"""What a version's description holds, as an edit of the merge's is bounded."""


@dataclass(frozen=True)
class MergeSides:
    """The three versions a merge reads, and the merge before anything is settled.

    Attributes:
        base: The main version the fork is based on.
        fork: The fork's newest version.
        main: Main's newest version.
        description: The merged description.
        parts: The merged instructions, in order.
        files: Every file named on any side.
    """

    base: SkillVersion
    fork: SkillVersion
    main: SkillVersion
    description: MergedPart
    parts: list[MergedPart]
    files: list[MergedFile]

    @property
    def conflicts(self) -> int:
        """How many texts the model is asked to combine."""
        return len(_conflicts(self.description, self.parts))

    @property
    def prompt(self) -> str:
        """The conflicts as `conflicts_prompt` puts them; empty with none."""
        return _prompt(self.description, self.parts)


@dataclass(frozen=True)
class MergedSkill:
    """What a settled merge says: the text a check measures and accepting writes.

    Attributes:
        description: The merged description.
        content: The merged instructions.
        resources: Every file the merge keeps, as a version's manifest lists it.
        files: The same files with their bodies, the whole set the skill is served with.
    """

    description: str
    content: str
    resources: dict[str, ManifestEntry]
    files: tuple[SkillBodyFile, ...]


class SkillCatchUpService:
    """What main has left behind, and bringing it along on request."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.versions = SkillVersionService(db)
        self.agents = SkillAgentService(db)

    async def behind_main(self, ctx: AuthContext) -> BehindMainList:
        """The pinned agents and the forks main has moved past, as the caller may see them.

        An agent counts by what its default environment serves, as on the skill page.
        A fork is listed when an agent reads it: one nobody reads is behind nobody,
        and is offered for archiving instead. A skill the caller may not view is left
        out whole; a pinned agent the caller may not view is counted, never named.
        """
        org = ctx.organization_id
        reads = _served_reads(await agent_environment_repo.served(self.db, organization_id=org))
        skills = await skill_repo.get_many(
            self.db, sorted({read.skill_id for read in reads}), organization_id=org
        )
        viewable = await accessible_ids(
            self.db, ctx, skills.values(), Perm.SKILLS_VIEW, resource_type=SKILL
        )
        agents = {
            agent.id: agent
            for agent in (
                await agent_repo.get_many(
                    self.db, sorted({read.agent_id for read in reads}), organization_id=org
                )
            ).values()
            if agent.status != AgentStatus.ARCHIVED.value
        }
        reads = [read for read in reads if read.skill_id in viewable and read.agent_id in agents]
        pinned = [read for read in reads if read.line.state == "pinned"]
        items, hidden = await self._pinned(ctx, skills, agents, pinned)
        items += await self._forks(ctx, skills, [read for read in reads if read.line.fork_id])
        items.sort(key=_order)
        return BehindMainList(items=items, total=len(items), hidden=hidden)

    async def return_to_main(
        self, ctx: AuthContext, skill_id: UUID, fork_id: UUID, data: ReturnToMain
    ) -> ReturnedToMain:
        """Move a fork's agents back to main's newest version, then archive the fork once
        nobody reads it.

        Each agent moves as Change version moves it - published with `agents:publish`,
        otherwise in its draft - and one that cannot be moved stays on the fork with the
        reason: an agent the caller may not change (a system agent or the Architect
        without `org:settings` among them), one that reads the fork only through a
        specialist, or one whose new version does not publish. The fork is archived
        only for a caller who may edit the skill.

        Raises:
            NotFoundError: The skill, or the fork, is not one the caller may reach.
        """
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        # The skill, the fork and then each agent by id: the order a decision on the fork's
        # check takes. The fork is held shared, as a publish reading it holds it, so such a
        # publish takes its turn on its agent; archiving locks it for update at the end.
        await skill_repo.lock(self.db, skill.id)
        fork = (
            await skill_version_repo.hold_forks(
                self.db, [fork_id], organization_id=ctx.organization_id
            )
        ).get(fork_id)
        if fork is not None and fork.skill_id != skill.id:
            fork = None
        if fork is None:
            raise NotFoundError(message="Fork not found", details={"fork_id": fork_id})
        readers = sorted(await self.agents.fork_users(skill, fork.id), key=lambda agent: agent.id)
        visible = await accessible_ids(self.db, ctx, readers, Perm.AGENTS_VIEW, resource_type=AGENT)
        wanted = None if data.agent_ids is None else set(data.agent_ids)
        returned: list[ReturnedAgent] = []
        for agent in readers:
            if agent.id not in visible or (wanted is not None and agent.id not in wanted):
                continue
            try:
                moved = await self.agents.change_binding(
                    ctx, skill.id, agent.id, SkillBindingChange(state="main")
                )
            except (NotFoundError, BadRequestError, AuthorizationError) as refusal:
                returned.append(
                    ReturnedAgent(agent=_usage(agent), published=False, refused=refusal.message)
                )
                continue
            returned.append(
                ReturnedAgent(
                    agent=_usage(agent),
                    published=moved.published,
                    agent_version=moved.agent_version,
                )
            )
        remaining = await self.agents.fork_users(skill, fork.id)
        archived = not remaining and skill.id in await accessible_ids(
            self.db, ctx, [skill], Perm.SKILLS_EDIT, resource_type=SKILL
        )
        if archived:
            await self.versions.archive_fork(ctx, skill.id, fork.id)
        return ReturnedToMain(
            agents=sorted(returned, key=lambda row: row.agent.name),
            hidden=len(readers) - len(visible),
            remaining=len(remaining),
            archived=archived,
        )

    async def merge_sides(
        self,
        ctx: AuthContext,
        *,
        skill: Skill,
        fork: SkillFork,
        kind: SkillImprovementPurpose,
    ) -> MergeSides:
        """The three versions a catch-up or a move to main would merge, or why there is
        nothing to merge.

        Raises:
            ConflictError: The fork is archived, has no version of its own - its agents
                return to main instead - or the merge would change nothing.
            TooLargeToMerge: The texts are too long to merge (422).
        """
        self.versions.refuse_archived(fork)
        if fork.latest_version_id is None:
            raise ConflictError(
                message=(
                    f"The fork '{fork.name}' has no changes of its own. Return its agents to "
                    "main instead"
                ),
                details={"fork_id": fork.id},
            )
        assert skill.latest_version_id is not None, "every skill has a main version"
        found = await skill_version_repo.get_versions(
            self.db,
            {fork.base_version_id, fork.latest_version_id, skill.latest_version_id},
            organization_id=ctx.organization_id,
        )
        base = found[fork.base_version_id]
        ours = found[fork.latest_version_id]
        main = found[skill.latest_version_id]
        unchanged = main if kind is SkillImprovementPurpose.CATCH_UP else ours
        if _says(unchanged) == _says(base) or _says(ours) == _says(main):
            raise ConflictError(
                message=(
                    f"Main has nothing the fork '{fork.name}' does not have"
                    if kind is SkillImprovementPurpose.CATCH_UP
                    else f"The fork '{fork.name}' has nothing main does not have"
                ),
                details={"fork_id": fork.id},
            )
        try:
            # Seconds of CPU for a long text: off the event loop, which serves every tenant.
            parts = await anyio.to_thread.run_sync(
                merge_text, base.content, ours.content, main.content
            )
        except MergeTooLarge as exc:
            raise TooLargeToMerge(
                message=(
                    f"The fork '{fork.name}' and main are too long to merge "
                    "automatically. Bring the changes over by hand in the editor."
                ),
                details={"fork_id": fork.id, "max_lines": MAX_LINES},
            ) from exc
        return MergeSides(
            base=base,
            fork=ours,
            main=main,
            description=_text_row(
                merge_value(base.description, ours.description, main.description)
            ),
            parts=[_text_row(part) for part in parts],
            files=_file_rows(base, ours, main),
        )

    async def build_merge(
        self,
        ctx: AuthContext,
        *,
        run: SkillImprovementRun,
        skill: Skill,
        fork: SkillFork,
        sides: MergeSides | None = None,
    ) -> SkillMerge:
        """Merge the session's three versions, without the model, and keep the parts;
        `sides` is a merge of them already made in this transaction.

        Raises:
            ConflictError: There is nothing to merge; see `merge_sides`.
        """
        kind = SkillImprovementPurpose(run.purpose)
        assert kind is not SkillImprovementPurpose.IMPROVE, "only a catch-up or a move merges"
        if sides is None:
            sides = await self.merge_sides(ctx, skill=skill, fork=fork, kind=kind)
        return await skill_merge_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            merge=SkillMerge(
                skill_id=skill.id,
                fork_id=fork.id,
                run_id=run.id,
                kind=kind.value,
                base_version_id=sides.base.id,
                fork_version_id=sides.fork.id,
                main_version_id=sides.main.id,
                description=sides.description,
                parts=sides.parts,
                files=sides.files,
                conflicts=sides.conflicts,
                unresolved=_unresolved(sides.description, sides.parts, sides.files),
            ),
        )

    async def merge_for_run(self, run_id: UUID, *, organization_id: UUID) -> SkillMerge | None:
        """A session's merge; `None` for a session that improves rather than merges."""
        return await skill_merge_repo.for_run(self.db, run_id, organization_id=organization_id)

    async def candidate_of(self, merge: SkillMerge) -> MergedSkill | None:
        """What the merge says, or `None` while a text or a file waits for a person."""
        if merge.unresolved:
            return None
        texts = [merge.description, *merge.parts]
        assert all(row["result"] is not None for row in texts), "nothing is left unresolved"
        resources: dict[str, ManifestEntry] = {}
        for row in merge.files:
            assert row["take"] is not None, "nothing is left unresolved"
            entry = row["fork"] if row["take"] == "fork" else row["main"]
            if entry is not None:
                resources[row["name"]] = entry
        bodies = await skill_version_repo.get_files(
            self.db,
            organization_id=merge.organization_id,
            skill_id=merge.skill_id,
            hashes=[entry["sha256"] for entry in resources.values()],
        )
        return MergedSkill(
            description=merge.description["result"] or "",
            content="".join(row["result"] or "" for row in merge.parts),
            resources=resources,
            files=tuple(
                SkillBodyFile(
                    name=name, description=entry["description"], content=bodies[entry["sha256"]]
                )
                for name, entry in sorted(resources.items())
            ),
        )

    @staticmethod
    def conflicts_prompt(merge: SkillMerge) -> str:
        """The texts both sides changed differently, numbered in the order
        `fill_conflicts` takes their combined texts; empty with none."""
        return _prompt(merge.description, merge.parts)

    async def fill_conflicts(self, merge: SkillMerge, proposed: Sequence[str]) -> None:
        """Settle each conflict with the model's text for it, in `conflicts_prompt`'s order.

        The merge is read again under its lock, since the model answers long after it was
        asked. A text a person already wrote stands, with the model's beside it, and a
        description outside 1 to 500 characters stays for a person to write.

        Raises:
            ValueError: `proposed` does not hold one text per conflict.
        """
        locked = await skill_merge_repo.for_run(
            self.db, merge.run_id, organization_id=merge.organization_id, lock=True
        )
        assert locked is not None, "a merge stays with its session"
        description = MergedPart(**locked.description)
        parts = [MergedPart(**row) for row in locked.parts]
        conflicts = _conflicts(description, parts)
        if len(proposed) != len(conflicts):
            raise ValueError(f"{len(conflicts)} conflicts, {len(proposed)} texts")
        for row, text in zip(conflicts, proposed, strict=True):
            if row is description:
                text = text.strip()
                if not 1 <= len(text) <= _DESCRIPTION_CHARS:
                    continue
            else:
                text = _line_ended(row, text)
            row["proposed"] = text
            if not row["edited"]:
                row["result"] = text
        await self._store(locked, description, parts, locked.files)

    async def accept_catch_up(
        self, ctx: AuthContext, *, skill: Skill, fork: SkillFork, merge: SkillMerge
    ) -> SkillVersion:
        """Make the merge the fork's newest version and base the fork on main's newest.

        Takes the skill and then the fork, as every writer of a fork does.

        Raises:
            ConflictError: The fork is archived.
            ConcurrentChangeError: Main or the fork moved since the merge.
            BadRequestError: A text or a file still waits for a person.
        """
        locked = await skill_repo.lock(self.db, skill.id)
        held = await skill_version_repo.get_fork(
            self.db, fork.id, organization_id=ctx.organization_id, skill_id=skill.id, lock=True
        )
        assert locked is not None and held is not None, "the session holds its skill and fork"
        self.versions.refuse_archived(held)
        _refuse_moved(merge, locked, held)
        merged = await self.candidate_of(merge)
        if merged is None:
            raise BadRequestError(
                message="Settle every conflict before accepting the merge",
                details={"unresolved": merge.unresolved},
            )
        version = await self.versions.record_fork(
            ctx,
            held,
            description=merged.description,
            content=merged.content,
            resources=merged.resources,
            source=SkillVersionSource.CATCH_UP,
            merged_from_id=merge.main_version_id,
        )
        await skill_version_repo.update_fork(
            self.db, fork=held, update_data={"base_version_id": merge.main_version_id}
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="skill.fork_caught_up",
            target_type="skill",
            target_id=str(skill.id),
            details={"name": skill.name, "fork": held.name, "version": version.number},
        )
        return version

    async def read_merge(self, ctx: AuthContext, skill_id: UUID, run_id: UUID) -> SkillMergeRead:
        """A session's merge, as the Changes step shows it.

        Raises:
            AuthorizationError: The caller may not read runs.
            NotFoundError: The skill or the session is not one the caller may reach, or
                the session merges nothing.
        """
        _require_runs_view(ctx)
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        await self._run(ctx, skill, run_id, lock=False)
        return await self._read_merge(ctx, await self._merge(ctx, run_id, lock=False))

    async def edit_description(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: MergeDescriptionEdit
    ) -> SkillMergeRead:
        """Write the merged description, while the session waits at Changes."""
        merge = await self._editable(ctx, skill_id, run_id)
        description = MergedPart(**merge.description)
        description["result"], description["edited"] = data.result, True
        await self._store(merge, description, merge.parts, merge.files)
        return await self._read_merge(ctx, merge)

    async def edit_part(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, index: int, data: MergePartEdit
    ) -> SkillMergeRead:
        """Write one part of the merged instructions, while the session waits at Changes.

        Raises:
            NotFoundError: The merge has no part `index`.
        """
        merge = await self._editable(ctx, skill_id, run_id)
        if not 0 <= index < len(merge.parts):
            raise NotFoundError(message="The merge has no such part", details={"index": index})
        parts = [MergedPart(**row) for row in merge.parts]
        parts[index]["result"] = _line_ended(parts[index], data.result)
        parts[index]["edited"] = True
        await self._store(merge, merge.description, parts, merge.files)
        return await self._read_merge(ctx, merge)

    async def pick_file(
        self, ctx: AuthContext, skill_id: UUID, run_id: UUID, data: MergeFilePick
    ) -> SkillMergeRead:
        """Keep one side's file, while the session waits at Changes. Taking the side the
        file is absent from drops it."""
        merge = await self._editable(ctx, skill_id, run_id)
        files = [MergedFile(**row) for row in merge.files]
        picked = next((row for row in files if row["name"] == data.name), None)
        if picked is None:
            raise refused_field("name", "The merge has no file by that name")
        picked["take"] = data.take
        await self._store(merge, merge.description, merge.parts, files)
        return await self._read_merge(ctx, merge)

    async def _editable(self, ctx: AuthContext, skill_id: UUID, run_id: UUID) -> SkillMerge:
        """The merge of a session waiting at Changes, locked after its session.

        Raises:
            AuthorizationError: The caller may not read runs, or edit the skill.
            NotFoundError: The skill or the session is out of reach, or merges nothing.
            BadRequestError: The session is not waiting at Changes.
        """
        _require_runs_view(ctx)
        skill = await self.versions.skill_for(ctx, skill_id, Perm.SKILLS_VIEW)
        if not await resolve_access(self.db, ctx, skill, Perm.SKILLS_EDIT, resource_type=SKILL):
            raise AuthorizationError(
                message="Editing a merge needs edit access to the skill",
                details={"permission": Perm.SKILLS_EDIT.value},
            )
        run = await self._run(ctx, skill, run_id, lock=True)
        if (
            run.status != ImprovementStatus.WAITING.value
            or run.stage != ImprovementStage.FILTERING.value
        ):
            raise BadRequestError(
                message="A merge is edited only while its session waits at Changes",
                details={"status": run.status, "stage": run.stage},
            )
        return await self._merge(ctx, run_id, lock=True)

    async def _run(
        self, ctx: AuthContext, skill: Skill, run_id: UUID, *, lock: bool
    ) -> SkillImprovementRun:
        run = await skill_improvement_repo.get_run(
            self.db, run_id, organization_id=ctx.organization_id, lock=lock
        )
        if run is None or run.skill_id != skill.id:
            raise NotFoundError(
                message="Improvement session not found", details={"improvement_run_id": run_id}
            )
        return run

    async def _merge(self, ctx: AuthContext, run_id: UUID, *, lock: bool) -> SkillMerge:
        merge = await skill_merge_repo.for_run(
            self.db, run_id, organization_id=ctx.organization_id, lock=lock
        )
        if merge is None:
            raise NotFoundError(
                message="This session merges nothing", details={"improvement_run_id": run_id}
            )
        return merge

    async def _store(
        self,
        merge: SkillMerge,
        description: MergedPart,
        parts: list[MergedPart],
        files: list[MergedFile],
    ) -> None:
        await skill_merge_repo.update(
            self.db,
            merge=merge,
            values={
                "description": description,
                "parts": parts,
                "files": files,
                "unresolved": _unresolved(description, parts, files),
            },
        )

    async def _read_merge(self, ctx: AuthContext, merge: SkillMerge) -> SkillMergeRead:
        versions = await skill_version_repo.get_versions(
            self.db,
            {merge.base_version_id, merge.fork_version_id, merge.main_version_id},
            organization_id=ctx.organization_id,
        )

        def ref(version_id: UUID) -> VersionNumberRef:
            return VersionNumberRef(id=version_id, number=versions[version_id].number)

        return SkillMergeRead(
            id=merge.id,
            run_id=merge.run_id,
            skill_id=merge.skill_id,
            fork_id=merge.fork_id,
            kind="catch_up" if merge.kind == SkillImprovementPurpose.CATCH_UP.value else "to_main",
            base=ref(merge.base_version_id),
            fork=ref(merge.fork_version_id),
            main=ref(merge.main_version_id),
            description=MergeTextRead.model_validate(merge.description),
            parts=[MergeTextRead.model_validate(row) for row in merge.parts],
            files=[
                MergeFileRead.model_validate(
                    {
                        "name": row["name"],
                        "state": row["state"],
                        "base": _file_side(row["base"]),
                        "fork": _file_side(row["fork"]),
                        "main": _file_side(row["main"]),
                        "take": row["take"],
                    }
                )
                for row in merge.files
            ],
            conflicts=merge.conflicts,
            unresolved=merge.unresolved,
            updated_at=merge.updated_at,
        )

    async def _pinned(
        self,
        ctx: AuthContext,
        skills: dict[UUID, Skill],
        agents: dict[UUID, Agent],
        reads: Sequence[_Read],
    ) -> tuple[list[BehindMain], int]:
        """The pinned agents behind main the caller may see, and how many it may not."""
        older = [
            read
            for read in reads
            if read.line.version is not None and read.line.version < skills[read.skill_id].version
        ]
        firsts: dict[UUID, int] = {}
        for read in older:
            assert read.line.version is not None, "a pinned line names its version"
            firsts[read.skill_id] = min(
                read.line.version, firsts.get(read.skill_id, read.line.version)
            )
        changed = await self._changes(ctx, skills, firsts)
        behind = [
            read
            for read in older
            if read.line.version is not None and changed[read.skill_id].get(read.line.version, 0)
        ]
        listed = [agents[read.agent_id] for read in behind]
        visible = await accessible_ids(self.db, ctx, listed, Perm.AGENTS_VIEW, resource_type=AGENT)
        editable = await accessible_ids(self.db, ctx, listed, Perm.AGENTS_EDIT, resource_type=AGENT)
        numbers: dict[UUID, set[int]] = {}
        for read in behind:
            assert read.line.version is not None, "a pinned line names its version"
            numbers.setdefault(read.skill_id, set()).add(read.line.version)
        versions = {
            skill_id: await skill_version_repo.get_by_numbers(
                self.db,
                organization_id=ctx.organization_id,
                skill_id=skill_id,
                fork_id=None,
                numbers=wanted,
            )
            for skill_id, wanted in numbers.items()
        }
        items: list[BehindMain] = []
        for read in behind:
            assert read.line.version is not None, "a pinned line names its version"
            version = versions[read.skill_id].get(read.line.version)
            if read.agent_id not in visible or version is None:
                continue
            skill, agent = skills[read.skill_id], agents[read.agent_id]
            items.append(
                BehindMain(
                    kind="pinned",
                    skill=SkillRef(id=skill.id, name=skill.name),
                    agent=_usage(agent),
                    via_specialist=read.line.via_specialist,
                    agents=1,
                    version=VersionNumberRef(id=version.id, number=version.number),
                    main_latest=_main_latest(skill),
                    behind_main=changed[skill.id][version.number],
                    # A specialist's pin changes in the agent's Builder, not here.
                    can_act=agent.id in editable and read.line.via_specialist is None,
                )
            )
        return items, len({read.agent_id for read in behind if read.agent_id not in visible})

    async def _changes(
        self, ctx: AuthContext, skills: dict[UUID, Skill], firsts: dict[UUID, int]
    ) -> dict[UUID, dict[int, int]]:
        """For each skill, how many main versions after each changed what it says, from the
        oldest one asked about; counted as the skill page counts it."""
        return {
            skill_id: changes_since(
                await skill_version_repo.main_digests(
                    self.db,
                    organization_id=ctx.organization_id,
                    skill_id=skill_id,
                    first=first,
                    last=skills[skill_id].version,
                )
            )
            for skill_id, first in firsts.items()
        }

    async def _forks(
        self, ctx: AuthContext, skills: dict[UUID, Skill], reads: Sequence[_Read]
    ) -> list[BehindMain]:
        """The forks main has moved past, each with how many agents read it."""
        readers: dict[UUID, set[UUID]] = {}
        for read in reads:
            assert read.line.fork_id is not None, "a fork line names its fork"
            readers.setdefault(read.line.fork_id, set()).add(read.agent_id)
        forks = {
            fork.id: fork
            for fork in (
                await skill_version_repo.get_forks(
                    self.db, list(readers), organization_id=ctx.organization_id
                )
            ).values()
            if fork.archived_at is None and fork.skill_id in skills
        }
        bases = await skill_version_repo.get_versions(
            self.db,
            {fork.base_version_id for fork in forks.values()},
            organization_id=ctx.organization_id,
        )
        changes = await skill_version_repo.count_versions(
            self.db, organization_id=ctx.organization_id, fork_ids=list(forks)
        )
        editable = await accessible_ids(
            self.db,
            ctx,
            [skills[fork.skill_id] for fork in forks.values()],
            Perm.SKILLS_EDIT,
            resource_type=SKILL,
        )
        firsts: dict[UUID, int] = {}
        for fork in forks.values():
            number = bases[fork.base_version_id].number
            firsts[fork.skill_id] = min(number, firsts.get(fork.skill_id, number))
        changed = await self._changes(ctx, skills, firsts)
        items: list[BehindMain] = []
        for fork in forks.values():
            skill, base = skills[fork.skill_id], bases[fork.base_version_id]
            if not changed[skill.id].get(base.number, 0):
                continue
            items.append(
                BehindMain(
                    kind="fork",
                    skill=SkillRef(id=skill.id, name=skill.name),
                    fork=ForkRef(
                        id=fork.id,
                        name=fork.name,
                        base_number=base.number,
                        changes=changes[fork.id],
                    ),
                    agents=len(readers[fork.id]),
                    version=VersionNumberRef(id=base.id, number=base.number),
                    main_latest=_main_latest(skill),
                    behind_main=changed[skill.id][base.number],
                    can_act=skill.id in editable,
                )
            )
        return items


def _bound_off_main(spec: AgentSpec) -> set[UUID]:
    """The skills a spec binds to anything but main's newest, its inline specialists' too.

    A spec whose specialists no longer read as a delegation config contributes only
    its own bindings, as the runtime would run it.
    """
    named = {binding.skill_id for binding in spec.skill_bindings}
    delegation = delegation_binding(spec)
    if delegation is None:
        return named
    try:
        inline = SubagentsConfig.model_validate(delegation.config).inline
    except ValidationError:
        return named
    return named | {
        binding.skill_id for specialist in inline for binding in specialist.skill_bindings
    }


def _served_reads(served: Sequence[tuple[AgentEnvironment, AgentVersion]]) -> list[_Read]:
    """What each agent's default environment reads off main: one read per skill for
    the agent itself and one for each inline specialist that reads it its own way.

    Only a spec with a binding is parsed, and one that no longer parses reads main.
    """
    by_agent: dict[UUID, AgentVersion] = {}
    for environment, version in served:
        if environment.is_default or environment.agent_id not in by_agent:
            by_agent[environment.agent_id] = version
    reads: list[_Read] = []
    for agent_id, version in by_agent.items():
        if '"skill_bindings": [{' not in json.dumps(version.spec):
            continue
        try:
            spec = AgentSpec.model_validate(version.spec)
        except ValidationError:
            continue
        for skill_id in sorted(_bound_off_main(spec)):
            reads += [
                _Read(agent_id, skill_id, line)
                for line in lines_of(version.spec, skill_id)
                if line.state != "main"
            ]
    return reads


def _order(item: BehindMain) -> tuple[int, str, str]:
    """Furthest behind first, then by skill, then by the agent or fork."""
    if item.agent is not None:
        named = item.agent.name
    else:
        assert item.fork is not None, "an item is a pinned agent or a fork"
        named = item.fork.name
    return (-item.behind_main, item.skill.name.lower(), named.lower())


def _main_latest(skill: Skill) -> VersionNumberRef:
    assert skill.latest_version_id is not None, "every skill has a main version"
    return VersionNumberRef(id=skill.latest_version_id, number=skill.version)


def _usage(agent: Agent) -> AgentUsage:
    return AgentUsage(
        id=agent.id,
        name=agent.name,
        slug=agent.slug,
        has_avatar=agent.has_avatar,
        avatar_color=agent.avatar_color,
    )


def _says(version: SkillVersion) -> tuple[str, str, dict[str, ManifestEntry]]:
    return version.description, version.content, version.resources


def _text_row(part: MergePart) -> MergedPart:
    return MergedPart(
        state=part.state.value,
        base=part.base,
        fork=part.fork,
        main=part.main,
        result=part.merged,
        proposed=None,
        edited=False,
    )


def _file_rows(base: SkillVersion, fork: SkillVersion, main: SkillVersion) -> list[MergedFile]:
    """Each file by name; two entries are the same file when body and description match."""

    def keys(version: SkillVersion) -> dict[str, str]:
        return {
            name: f"{entry['sha256']}\x1e{entry['description'] or ''}"
            for name, entry in version.resources.items()
        }

    rows: list[MergedFile] = []
    for merged in merge_files(keys(base), keys(fork), keys(main)):
        take = {
            PartState.SAME: "main",
            PartState.BOTH: "main",
            PartState.MAIN: "main",
            PartState.FORK: "fork",
        }.get(merged.state)
        rows.append(
            MergedFile(
                name=merged.name,
                state=merged.state.value,
                base=base.resources.get(merged.name),
                fork=fork.resources.get(merged.name),
                main=main.resources.get(merged.name),
                take=take,
            )
        )
    return rows


def _line_ended(part: MergedPart, text: str) -> str:
    """`text` for a part of the instructions, ending its last line as the part's sides do.

    Parts are whole lines, so the next part starts on a line of its own; a text written
    without its final line break would run into it.
    """
    ended = any(side.endswith("\n") for side in (part["base"], part["fork"], part["main"]))
    return text + "\n" if ended and text and not text.endswith("\n") else text


def _conflicts(description: MergedPart, parts: Sequence[MergedPart]) -> list[MergedPart]:
    """The texts both sides changed differently: the description first, then the parts."""
    return [row for row in (description, *parts) if row["state"] == PartState.CONFLICT.value]


def _prompt(description: MergedPart, parts: Sequence[MergedPart]) -> str:
    conflicts = _conflicts(description, parts)
    return "\n\n".join(
        "\n".join(
            (
                f"Conflict {number} of {len(conflicts)} - "
                + ("the description" if row is description else "the instructions"),
                f"<base>\n{row['base']}\n</base>",
                f"<fork>\n{row['fork']}\n</fork>",
                f"<main>\n{row['main']}\n</main>",
            )
        )
        for number, row in enumerate(conflicts, start=1)
    )


def _unresolved(
    description: MergedPart, parts: Sequence[MergedPart], files: Sequence[MergedFile]
) -> int:
    return sum(row["result"] is None for row in (description, *parts)) + sum(
        row["take"] is None for row in files
    )


def _refuse_moved(merge: SkillMerge, skill: Skill, fork: SkillFork) -> None:
    if skill.latest_version_id != merge.main_version_id:
        raise ConcurrentChangeError(
            message="Main has a newer version than the merge read. Start the merge again",
            details={
                "main_version_id": merge.main_version_id,
                "latest_version_id": skill.latest_version_id,
            },
        )
    if (fork.latest_version_id, fork.base_version_id) != (
        merge.fork_version_id,
        merge.base_version_id,
    ):
        raise ConcurrentChangeError(
            message=(
                f"The fork '{fork.name}' has a newer version than the merge read. Start the "
                "merge again"
            ),
            details={
                "fork_version_id": merge.fork_version_id,
                "latest_version_id": fork.latest_version_id,
                "base_version_id": merge.base_version_id,
                "fork_base_version_id": fork.base_version_id,
            },
        )


def _file_side(entry: ManifestEntry | None) -> MergeFileSide | None:
    if entry is None:
        return None
    return MergeFileSide(description=entry["description"], size_bytes=entry["size_bytes"])


def _require_runs_view(ctx: AuthContext) -> None:
    if not ctx.has(Perm.RUNS_VIEW):
        raise AuthorizationError(
            message="A skill session reads runs, which needs runs:view",
            details={"permission": Perm.RUNS_VIEW.value},
        )
