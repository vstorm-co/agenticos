"""`notification.send`: tell members of the organization something, in the app or by email.

Recipients are members, named by id - never a free-text address - and each one
is checked when the step runs: still an active member of the organization, and
able to see this workflow. A recipient who fails either is dropped, the way an
agent's alert audience drops a member who left; if nobody is left the step
fails with `NO_PERMITTED_RECIPIENTS` rather than claiming to have told anyone.
Publishing refuses a recipient who is not a member at all.

The rows go through `NotificationCenterService.write`, so each recipient's own
channel preferences still decide what reaches them. `Completed` means the rows
were written, not that anyone read them or that mail went out: email is sent by
the delivery sweep, which retries on its own and can fail on its own. The write
is not in a savepoint - it *is* this step's effect, so a failure fails the step
instead of being absorbed the way a run's terminal notice is.

A retry after a crash writes nothing twice: the occurrence id is the attempt's
idempotency key, and the notification center's `(recipient, event_type,
occurrence_id)` uniqueness turns a second write into a no-op.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.db.models.notification import NotificationChannel, NotificationEventType
from app.db.session import get_worker_db_context
from app.repositories import member as member_repo
from app.repositories import user as user_repo
from app.repositories import workflow as workflow_repo
from app.services.access import WORKFLOW, resolve_access
from app.services.notification_center import NotificationCenterService
from app.services.workflow_execution import context
from app.workflows.contracts.results import Completed, Failed, NodeResult, WorkflowError


class NotificationSendConfig(BaseModel):
    """Who to tell, the headline, and which channels it may use."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recipients: tuple[UUID, ...] = Field(
        min_length=1,
        max_length=50,
        json_schema_extra={"x-resource": "member"},
        description="Members of the organization to notify.",
    )
    subject: str = Field(min_length=1, max_length=200, description="The notification's headline.")
    channels: tuple[Literal["in_app", "email"], ...] = Field(
        default=("in_app",),
        min_length=1,
        description="Where it may reach them. Each person's own preferences still apply.",
    )


class NotificationSendInput(BaseModel):
    """The body, bound from an earlier step."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str | None = Field(default=None, max_length=4000)


class NotificationSendOutput(BaseModel):
    """Who the rows were written for. Not proof anyone read them or got an email."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    notified_member_ids: tuple[UUID, ...]


async def _member_ids(
    db: AsyncSession, organization_id: UUID, user_ids: tuple[UUID, ...]
) -> set[UUID]:
    """The ones among `user_ids` who are active members of the organization."""
    members: set[UUID] = set()
    for user_id in user_ids:
        member = await member_repo.get_active(db, organization_id=organization_id, user_id=user_id)
        if member is not None:
            members.add(user_id)
    return members


async def check_resources(
    db: AsyncSession, ctx: AuthContext, config: BaseModel
) -> list[tuple[str, str]]:
    """Refuse a recipient who is not a member of the organization."""
    if not isinstance(config, NotificationSendConfig):
        return []
    members = await _member_ids(db, ctx.organization_id, config.recipients)
    return [
        (f"recipients.{index}", "This person is not a member of the organization")
        for index, user_id in enumerate(config.recipients)
        if user_id not in members
    ]


async def _permitted(
    db: AsyncSession, organization_id: UUID, workflow_id: UUID | None, user_ids: tuple[UUID, ...]
) -> list[UUID]:
    """Recipients still active in the organization who may see this workflow."""
    workflow = (
        None
        if workflow_id is None
        else await workflow_repo.get(db, workflow_id, organization_id=organization_id)
    )
    if workflow is None:
        return []
    permitted: list[UUID] = []
    for user_id in dict.fromkeys(user_ids):
        member = await member_repo.get_active(db, organization_id=organization_id, user_id=user_id)
        user = await user_repo.get_by_id(db, user_id) if member is not None else None
        if member is None or user is None:
            continue
        reach = AuthContext(
            user_id=user_id,
            organization_id=organization_id,
            role=member.role,
            is_app_admin=user.is_app_admin,
        )
        if await resolve_access(db, reach, workflow, Perm.WORKFLOWS_VIEW, resource_type=WORKFLOW):
            permitted.append(user_id)
    return permitted


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Write a notification for every recipient the workflow may still reach."""
    if not isinstance(config, NotificationSendConfig):
        return Failed(
            error=WorkflowError(
                code="NOTIFICATION_NOT_CONFIGURED", message="This step has no recipients"
            )
        )
    current = context.current()
    message = node_input.message if isinstance(node_input, NotificationSendInput) else None
    summary = config.subject if not message else f"{config.subject}\n\n{message}"
    async with get_worker_db_context() as db:
        recipients = await _permitted(
            db, current.organization_id, current.workflow_id, config.recipients
        )
        if not recipients:
            return Failed(
                error=WorkflowError(
                    code="NO_PERMITTED_RECIPIENTS",
                    message="None of this step's recipients may be notified by this workflow",
                )
            )
        await NotificationCenterService(db).write(
            recipients=recipients,
            event_type=NotificationEventType.WORKFLOW_NOTIFICATION,
            occurrence_id=current.idempotency_key,
            summary=summary,
            organization_id=current.organization_id,
            actor_user_id=current.auth.user_id,
            channels={NotificationChannel(channel) for channel in config.channels},
        )
    return Completed[NotificationSendOutput](
        output=NotificationSendOutput(notified_member_ids=tuple(recipients))
    )
