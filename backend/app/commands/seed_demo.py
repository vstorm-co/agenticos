"""Seed a curated demo workspace for the guided first run.

Usage:
    agenticos cmd seed-demo <org-id-or-name>
    agenticos cmd seed-demo <org-id-or-name> --clear
    agenticos cmd seed-demo <org-id-or-name> --dry-run

What it creates, in the named organization:

- one project, "Demo — first-run example", visible to the whole organization,
  stored without a sandbox (`backend="state"`), so it needs no container;
- one conversation in it, "Demo — meeting notes into an action plan", with a
  user question and an assistant answer.

The content is the fictional Northwind example the guided first run shows as
"what a finished result looks like" (`frontend/messages/en.json`,
`start.examples.meeting`), so the seed and the start hub agree word for word.

What it deliberately does NOT create:

- no connected app: a connection row without credentials would be a fake, and
  the connections UI would try to refresh it and fail. The start hub's connect
  step is skippable for exactly this reason;
- no agent run: the assistant answer is stored with `model_name="demo"` and
  no `run_id`, so it can never count as a real completed run. The start hub
  only completes on `GET /me/onboarding` reporting `has_result`, which a
  seeded conversation cannot produce;
- no task board and no solution bundle: boards need a Virtual Table and the
  solutions backend is not on this branch yet (it arrives with the 1.86.1
  sync). Both are follow-ups, not silent omissions.

The organization is an id or an exact name: `scripts/quickstart.sh --demo`
only knows the name it just bootstrapped, so a name resolves here rather than
in the shell. A name that matches nothing, or more than one organization, is
refused — pass the id then. Taken from draft PR #209's `seed-demo` with only
that resolution added; the wizard #209 also built is parked and not revived
here.

Idempotent: running it twice reports the existing workspace and creates
nothing. `--clear` removes exactly what it created and nothing else. Seeded
rows are recognised by what the seed wrote, not by a title a person can edit:
a project by its name, its fixed description and `backend="state"`; a
conversation by the assistant message stored with `model_name="demo"`, so a
renamed demo chat is still removed. If duplicates exist (a person created a
look-alike, or a race seeded twice), every match is cleared. The conversations
go first (deleting the project alone would only detach them, leaving ordinary
chats behind), then each project through `ProjectService.delete`, which also
clears grants, tasks, triggers and writes the audit entry.

An unknown or ambiguous organization exits non-zero, so `quickstart.sh --demo`
reports the failure instead of printing a green summary.
"""

import asyncio
from typing import NoReturn
from uuid import UUID

import click
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.commands import command, error, info, success
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.conversation import Conversation, Message
from app.db.models.organization import Organization
from app.db.models.project import Project
from app.db.models.resource_grant import Visibility
from app.db.session import get_db_context
from app.repositories import conversation as conversation_repo
from app.repositories import member_repo, organization_repo
from app.repositories import project as project_repo
from app.services.project import ProjectService

DEMO_PROJECT_NAME = "Demo — first-run example"
DEMO_PROJECT_DESCRIPTION = (
    "Demo workspace seeded by `agenticos cmd seed-demo`. Nothing here is real: "
    "the example conversation is fictional, no model ran, and no app is connected. "
    "Safe to delete."
)
DEMO_PROJECT_INSTRUCTIONS = (
    "This is the demo workspace for the guided first run. Treat its content as fictional examples."
)
DEMO_CONVERSATION_TITLE = "Demo — meeting notes into an action plan"
DEMO_MODEL_NAME = "demo"
DEMO_USER_PROMPT = (
    "Turn these fictional meeting notes into an action plan with an owner and due date "
    "for each item. Flag missing information rather than inventing it.\n\n"
    "Northwind demo team: Maya will prepare the proposal by Friday. Leo will check "
    "the budget. The client needs a status update on Wednesday. We have not assigned "
    "the update or a budget deadline."
)
DEMO_ASSISTANT_REPLY = (
    "Maya — prepare proposal — Friday.\n"
    "Leo — check budget — deadline not specified.\n"
    "Client update — Wednesday — owner not assigned.\n"
    "Confirm the budget deadline and who will send the update."
)


def _refuse(message: str) -> NoReturn:
    """Report the problem and exit non-zero, so a calling script sees the failure."""
    error(message)
    raise click.exceptions.Exit(1)


async def _resolve_organization(db: AsyncSession, value: str) -> Organization:
    """An organization by id, or by exact name when the value is not a UUID.

    Exits non-zero when the id or name matches nothing, or a name matches several.
    """
    try:
        org_id = UUID(value)
    except ValueError:
        org_id = None
    if org_id is not None:
        org = await organization_repo.get_by_id(db, org_id)
        if org is None:
            _refuse(f"No organization with id {org_id}")
        return org
    result = await db.execute(select(Organization).where(Organization.name == value))
    matches = result.scalars().all()
    if not matches:
        _refuse(f"No organization named {value!r}")
    if len(matches) > 1:
        _refuse(f"More than one organization is named {value!r}; pass its id instead")
    return matches[0]


async def _find_demo_projects(db: AsyncSession, organization_id: UUID) -> list[Project]:
    """Every project this seed could have written, oldest first.

    Matches the name, the fixed description and the stateless backend together,
    so an unrelated project that only shares the name is left alone.
    """
    result = await db.execute(
        select(Project)
        .where(
            Project.organization_id == organization_id,
            Project.name == DEMO_PROJECT_NAME,
            Project.description == DEMO_PROJECT_DESCRIPTION,
            Project.backend == "state",
        )
        .order_by(Project.created_at.asc(), Project.id.asc())
    )
    return list(result.scalars().all())


async def _find_demo_conversations(
    db: AsyncSession, *, organization_id: UUID, project_ids: list[UUID]
) -> list[Conversation]:
    """The seeded chats in these projects, found by the stored demo answer.

    The title is editable and the answer is not, so a renamed chat still matches.
    """
    result = await db.execute(
        select(Conversation)
        .where(
            Conversation.organization_id == organization_id,
            Conversation.project_id.in_(project_ids),
            Conversation.id.in_(
                select(Message.conversation_id).where(
                    Message.role == "assistant",
                    Message.model_name == DEMO_MODEL_NAME,
                    Message.run_id.is_(None),
                )
            ),
        )
        .order_by(Conversation.created_at.asc(), Conversation.id.asc())
    )
    return list(result.scalars().all())


@command("seed-demo", help="Seed a curated demo workspace for the guided first run")
@click.argument("organization")
@click.option("--clear", is_flag=True, help="Remove the demo workspace instead of creating it")
@click.option("--dry-run", is_flag=True, help="Show what would be created without making changes")
def seed_demo(organization: str, clear: bool, dry_run: bool) -> None:
    asyncio.run(_run(organization, clear, dry_run))


async def _run(organization: str, clear: bool, dry_run: bool) -> None:
    async with get_db_context() as db:
        org = await _resolve_organization(db, organization)
        projects = await _find_demo_projects(db, org.id)
        project = projects[0] if projects else None

        if clear:
            if not projects:
                info("No demo workspace to remove.")
                return
            owner_id = await member_repo.first_owner_id(db, organization_id=org.id)
            if owner_id is None:
                _refuse(f"{org.name} has no owner to remove the demo workspace as")
            conversations = await _find_demo_conversations(
                db, organization_id=org.id, project_ids=[p.id for p in projects]
            )
            for conversation in conversations:
                await db.delete(conversation)
            await db.flush()
            ctx = AuthContext(user_id=owner_id, organization_id=org.id, role=OrgRoleName.OWNER)
            service = ProjectService(db)
            for demo_project in projects:
                await service.delete(ctx, demo_project.id)
            success(f"Removed {len(projects)} demo workspace(s) from {org.name}")
            return

        if dry_run:
            info(f"[DRY RUN] Would create in {org.name}:")
            info(f"[DRY RUN]   project {DEMO_PROJECT_NAME!r}")
            info(f"[DRY RUN]   conversation {DEMO_CONVERSATION_TITLE!r} (2 messages)")
            if project is not None:
                info("[DRY RUN] Demo workspace already exists; nothing would be created.")
            return

        if project is not None:
            info(f"Demo workspace already exists in {org.name}; nothing created.")
            return

        owner_id = await member_repo.first_owner_id(db, organization_id=org.id)
        project = await project_repo.create(
            db,
            organization_id=org.id,
            owner_user_id=owner_id,
            name=DEMO_PROJECT_NAME,
            description=DEMO_PROJECT_DESCRIPTION,
            instructions=DEMO_PROJECT_INSTRUCTIONS,
            default_agent_id=None,
            backend="state",
            visibility=Visibility.ORG.value,
        )
        conversation = await conversation_repo.create_conversation(
            db,
            organization_id=org.id,
            user_id=owner_id,
            title=DEMO_CONVERSATION_TITLE,
            project_id=project.id,
        )
        await conversation_repo.create_message(
            db,
            conversation_id=conversation.id,
            role="user",
            content=DEMO_USER_PROMPT,
            author_user_id=owner_id,
        )
        await conversation_repo.create_message(
            db,
            conversation_id=conversation.id,
            role="assistant",
            content=DEMO_ASSISTANT_REPLY,
            model_name=DEMO_MODEL_NAME,
        )
        success(
            f"Created demo workspace in {org.name}: "
            f"project {DEMO_PROJECT_NAME!r}, conversation {DEMO_CONVERSATION_TITLE!r}"
        )
