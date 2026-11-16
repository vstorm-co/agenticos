"""The platform's nightly look at one person's week (#2301).

One model call per person, early in their morning, that does four things at
once because each is a reading of the same material - what they asked this
week, what their agent noted about them, who their profile says they are:

- **Requests they keep repeating**, proposed as a routine (or, for something
  that would rather be its own assistant, as an agent the Architect builds).
- **Their profile**, where the notes say something it does not - a role, what
  they work on, when they work - proposed with a card to save it.
- **Their first messages**: the four an empty chat with the starter agent
  offers, written for them.
- **A role pack**, where their role matches one.

Skipped, at no cost, when nothing happened since the last look and their first
messages are already written. What it proposes waits as a `Suggestion`; one
notification says how many are new.
"""

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.guardrails import GuardrailBlocked
from app.agents.person_briefing import LANGUAGE_NAMES
from app.agents.spec import AgentSpec
from app.core.memory_keys import person_owner_key
from app.core.permissions import AuthContext
from app.db.models.agent_run import AgentRun, RunStatus
from app.db.models.organization import OrganizationMember
from app.db.models.suggestion import SuggestionKind
from app.db.models.user import User
from app.repositories import (
    agent_repo,
    agent_run_repo,
    agent_trigger_repo,
    conversation_repo,
    mcp_connection_repo,
    member_repo,
    memory_repo,
    suggestion_repo,
    user_repo,
)
from app.repositories.conversation import PersonRequest
from app.schemas.user import WorkingHours
from app.services.agent_runner import input_screen_for
from app.services.notifications import NotificationService
from app.services.proactive._thinker import ProactiveThinker
from app.services.role_packs import PACKS

logger = logging.getLogger(__name__)

WINDOW = timedelta(days=7)
MAX_REQUESTS = 80
MAX_NOTES = 20
STARTERS = 4
STARTER_CHARS = 80
# Long enough to read a request, short enough that a pasted document does not
# fill the call: what is repeated is the ask, not the attachment.
_CLIP = 400


class RepeatedRequest(BaseModel):
    title: str = Field(max_length=120, description="The card's title, in the person's language.")
    why: str = Field(
        max_length=300, description="One sentence: what they asked, and how often this week."
    )
    prompt: str = Field(
        max_length=2000,
        description="What the routine or agent should do, written as the person would ask it.",
    )
    cron: str | None = Field(
        default=None,
        max_length=60,
        description="A UTC cron for a routine, e.g. '0 7 * * 1-5'; null for an agent.",
    )
    as_agent: bool = Field(
        description="True when it needs judgement each time rather than a fixed schedule."
    )


class ProfileUpdate(BaseModel):
    job_title: str | None = Field(default=None, max_length=120)
    about: str | None = Field(default=None, max_length=500)
    working_hours: WorkingHours | None = None
    title: str = Field(max_length=120, description="The card's title, in the person's language.")
    why: str = Field(max_length=300, description="What in their notes says so.")


class NightlyReading(BaseModel):
    repeats: list[RepeatedRequest] = Field(default_factory=list, max_length=2)
    profile: ProfileUpdate | None = None
    starters: list[str] = Field(default_factory=list, max_length=STARTERS)
    role_pack: str | None = Field(
        default=None, description="The id of the role pack that fits their role, or null."
    )
    role_pack_title: str | None = Field(
        default=None,
        max_length=120,
        description="The card's title for that pack, in the person's language.",
    )


_INSTRUCTIONS = f"""\
You read one person's last week with their AI agents and propose what would save
them time. You answer only with the structured result; nothing you write is shown
to them except the card titles and sentences, which you write in their language.

- repeats: requests they made three or more times this week in different words,
  which a schedule or an agent of their own would take off their hands. Skip
  anything already among their routines. Two at most; none is a fine answer.
- profile: only what their notes state and their profile lacks or contradicts.
  Never guess a role from a single message. Leave every field you are not sure
  of empty, and the whole thing null when nothing is new.
- starters: {STARTERS} first messages for their empty chat, each at most
  {STARTER_CHARS} characters, written as they would type them, in their
  language: about their own work, their connected services and what they asked
  lately - never generic.
- role_pack: the pack that fits their role, by id, only when their role clearly
  matches one.
"""


def _key(kind: SuggestionKind, *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(part.strip().lower() for part in parts).encode())
    return f"{kind.value}:{digest.hexdigest()[:40]}"


def _person(user: User) -> dict[str, object]:
    return {
        "language": LANGUAGE_NAMES.get(user.locale or "", "English"),
        "time_zone": user.time_zone,
        "role": user.job_title,
        "work": user.about,
        "working_hours": user.working_hours,
    }


def _reached_a_model(run: AgentRun) -> bool:
    """Whether a run's first request went out, so its input edge let the prompt through.

    The tokens rather than the status for a run that stopped later: a budget stop
    on a third request is a prompt the edge accepted, and the same status on the
    first is one it never read.
    """
    return run.status == RunStatus.COMPLETED.value or run.input_tokens > 0


def _passes(stored_spec: Mapping[str, object], text: str) -> bool:
    """Whether the input edge of `stored_spec` lets `text` through.

    A spec written by an older version of this code may no longer validate. Then
    nothing can vouch for the prompt, and it must not take the person's whole look
    with it, night after night, until it leaves the window.
    """
    try:
        screen = input_screen_for(AgentSpec.model_validate(stored_spec))
        if screen is not None:
            screen(text)
    except GuardrailBlocked:
        return False
    except ValidationError:
        logger.warning("nightly_look_unreadable_spec")
        return False
    return True


class NightlyLook:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.thinker = ProactiveThinker(db)

    async def due(self, organization_id: UUID, user_id: UUID, *, now: datetime) -> bool:
        """Whether this person has not been looked at for most of a day."""
        last = await agent_run_repo.last_nightly_run_at(
            self.db, organization_id=organization_id, user_id=user_id
        )
        return last is None or now - last >= timedelta(hours=20)

    async def look(self, organization_id: UUID, user_id: UUID) -> int:
        """Read one person's week and record what to propose. Returns how many proposals are new."""
        user = await user_repo.get_by_id(self.db, user_id)
        member = await member_repo.get_active(
            self.db, organization_id=organization_id, user_id=user_id
        )
        if user is None or member is None or not user.is_active:
            return 0
        agent = await self.thinker.starter_agent(organization_id)
        if agent is None:
            return 0
        now = datetime.now(UTC)
        requests = await self._past_the_input_edge(
            organization_id,
            await conversation_repo.person_requests_since(
                self.db,
                organization_id=organization_id,
                user_id=user_id,
                since=now - WINDOW,
                limit=MAX_REQUESTS,
            ),
        )
        content_hashes = {
            request.message.id: hashlib.sha256(request.message.content.encode()).hexdigest()
            for request in requests
        }
        has_unread = any(
            (request.message.nightly_read_by_user_id, request.message.nightly_read_content_hash)
            != (user_id, content_hashes[request.message.id])
            for request in requests
        )
        if not has_unread and member.personal_starters:
            return 0

        notes = await memory_repo.list_for_owner(
            self.db,
            organization_id=organization_id,
            agent_id=agent.id,
            owner_key=person_owner_key(user_id),
            limit=MAX_NOTES,
        )
        routines = await agent_trigger_repo.routine_prompts_for_screening(
            self.db, organization_id=organization_id, user_id=user_id
        )
        connections, _ = await mcp_connection_repo.list_for_user(
            self.db, user_id=user_id, enabled_only=True
        )
        material = {
            "person": _person(user),
            "requests_this_week": [request.message.content[:_CLIP] for request in requests],
            "notes_about_them": [
                {
                    "name": note.name,
                    "description": note.description,
                    "content": note.content[:_CLIP],
                }
                for note in notes
            ],
            "their_routines": [
                routine.prompt[:_CLIP]
                for routine in routines
                if _passes(routine.spec, routine.prompt)
            ],
            "connected_services": sorted({connection.name for connection in connections}),
            "role_packs": [
                {"id": pack.id, "name": pack.name, "description": pack.description}
                for pack in PACKS
            ],
        }
        ctx = AuthContext(user_id=user_id, organization_id=organization_id, role=member.role)
        reading = await self.thinker.think(
            ctx,
            feature="nightly",
            output_type=NightlyReading,
            instructions=_INSTRUCTIONS,
            prompt=json.dumps(material, ensure_ascii=False, default=str),
            # Due time belongs to this look; per-message receipts decide what
            # was read, including prompts whose verdict arrives after this read.
            started_at=now,
        )
        if reading is None:
            return 0
        await conversation_repo.mark_nightly_reads(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            content_hashes=content_hashes,
        )
        return await self._record(organization_id, user, member, reading, now=now)

    async def _past_the_input_edge(
        self, organization_id: UUID, requests: list[PersonRequest]
    ) -> list[PersonRequest]:
        """`requests` without the ones the input edge of their own agent would have stopped.

        A run that ended before its first request left nothing to read a verdict
        from, so the edge it never reached is asked now, the way a steer is. It
        has the version the run was on; with that version gone there is nothing
        to vouch for the prompt, and it is left out.
        """
        passed: list[PersonRequest] = []
        for request in requests:
            run = request.run
            if run is None or _reached_a_model(run):
                passed.append(request)
                continue
            stored = run.test_spec
            if stored is None and run.agent_version_id is not None:
                version = await agent_repo.get_version(
                    self.db, run.agent_version_id, organization_id=organization_id
                )
                stored = None if version is None else version.spec
            if stored is not None and _passes(stored, request.message.content):
                passed.append(request)
        return passed

    async def _record(
        self,
        organization_id: UUID,
        user: User,
        member: OrganizationMember,
        reading: NightlyReading,
        *,
        now: datetime,
    ) -> int:
        starters = [text.strip()[:STARTER_CHARS] for text in reading.starters if text.strip()]
        if starters:
            # On the membership: they are drawn from this organization's
            # conversations, and another organization's chat must not offer them.
            await member_repo.set_personal_starters(self.db, member, starters=starters, at=now)
        proposed = 0
        for repeat in reading.repeats:
            kind = SuggestionKind.AGENT if repeat.as_agent else SuggestionKind.ROUTINE
            payload: dict[str, object] = (
                {"request": repeat.prompt}
                if repeat.as_agent
                else {"prompt": repeat.prompt, "cron": repeat.cron}
            )
            proposed += await self._propose(
                organization_id, user.id, kind, repeat.title, repeat.why, payload, repeat.prompt
            )
        profile = reading.profile
        if profile is not None:
            fields = {
                name: value
                for name, value in (
                    ("job_title", profile.job_title),
                    ("about", profile.about),
                    (
                        "working_hours",
                        profile.working_hours.model_dump() if profile.working_hours else None,
                    ),
                )
                if value is not None and value != getattr(user, name)
            }
            if fields:
                proposed += await self._propose(
                    organization_id,
                    user.id,
                    SuggestionKind.PROFILE,
                    profile.title,
                    profile.why,
                    fields,
                    json.dumps(fields, sort_keys=True, default=str),
                )
        known_pack = {pack.id: pack for pack in PACKS}.get(reading.role_pack or "")
        if known_pack is not None:
            proposed += await self._propose(
                organization_id,
                user.id,
                SuggestionKind.ROLE_PACK,
                reading.role_pack_title or known_pack.name,
                known_pack.description,
                {"pack": known_pack.id},
                known_pack.id,
            )
        if proposed:
            await NotificationService(self.db).suggestions_ready(
                organization_id=organization_id, user_id=user.id, count=proposed, now=now
            )
        return proposed

    async def _propose(
        self,
        organization_id: UUID,
        user_id: UUID,
        kind: SuggestionKind,
        title: str,
        detail: str | None,
        payload: Mapping[str, object],
        identity: str,
    ) -> int:
        created = await suggestion_repo.propose(
            self.db,
            organization_id=organization_id,
            user_id=user_id,
            kind=kind.value,
            title=title,
            detail=detail,
            payload=dict(payload),
            dedupe_key=_key(kind, identity),
        )
        return 0 if created is None else 1
