"""Organization API key repository (PostgreSQL async)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, String, cast, delete, exists, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.api_key import ApiKey
from app.db.models.authoring import AuthoringRequest, AuthoringStatus
from app.db.models.background_job import BackgroundJob
from app.db.models.case_generation import CaseGeneration, GenerationStatus
from app.db.models.eval_run import EvalRun, EvalRunStatus
from app.db.models.improvement import UNSETTLED_STATUSES, ImprovementRun
from app.db.models.skill_check import CheckStatus, SkillCheck
from app.db.models.skill_improvement import SkillImprovementRun
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun, WorkflowRunStatus


async def create(
    db: AsyncSession,
    *,
    organization_id: UUID,
    user_id: UUID,
    name: str,
    prefix: str,
    key_hash: str,
    scopes: list[str],
    expires_at: datetime | None,
    oauth_grant_id: UUID | None = None,
    internal: bool = False,
) -> ApiKey:
    key = ApiKey(
        organization_id=organization_id,
        user_id=user_id,
        name=name,
        prefix=prefix,
        key_hash=key_hash,
        scopes=scopes,
        expires_at=expires_at,
        oauth_grant_id=oauth_grant_id,
        internal=internal,
    )
    db.add(key)
    await db.flush()
    await db.refresh(key)
    return key


async def get_by_prefix(db: AsyncSession, prefix: str) -> ApiKey | None:
    result = await db.execute(select(ApiKey).where(ApiKey.prefix == prefix))
    return result.scalar_one_or_none()


async def prefix_taken(db: AsyncSession, prefix: str) -> bool:
    """Whether a row already carries this visible prefix - it is unique across every key."""
    result = await db.execute(select(ApiKey.id).where(ApiKey.prefix == prefix).limit(1))
    return result.first() is not None


async def get(db: AsyncSession, key_id: UUID, *, organization_id: UUID) -> ApiKey | None:
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.organization_id == organization_id)
    )
    return result.scalar_one_or_none()


async def list_for_organization(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID | None
) -> list[tuple[ApiKey, str]]:
    """Each key a person issued, with their email, newest first; one issuer's when
    `user_id` is set. OAuth access tokens are left out - they are listed as their
    grant, under connected applications - and so are the platform's own."""
    query = (
        select(ApiKey, User.email)
        .join(User, User.id == ApiKey.user_id)
        .where(
            ApiKey.organization_id == organization_id,
            ApiKey.oauth_grant_id.is_(None),
            ApiKey.internal.is_(False),
        )
        .order_by(ApiKey.created_at.desc())
    )
    if user_id is not None:
        query = query.where(ApiKey.user_id == user_id)
    result = await db.execute(query)
    return [(key, email) for key, email in result.all()]


async def update(db: AsyncSession, *, key: ApiKey, update_data: dict[str, Any]) -> ApiKey:
    for field, value in update_data.items():
        setattr(key, field, value)
    await db.flush()
    await db.refresh(key)
    return key


async def touch(db: AsyncSession, key_id: UUID, *, at: datetime, stale_before: datetime) -> None:
    """Record a use, at most once per window - a write per request is not worth it."""
    await db.execute(
        sql_update(ApiKey)
        .where(
            ApiKey.id == key_id,
            (ApiKey.last_used_at.is_(None)) | (ApiKey.last_used_at < stale_before),
        )
        .values(last_used_at=at)
    )


def _backs_unfinished_run() -> ColumnElement[bool]:
    """A key unfinished runs or queued background work rebuild authority from.

    Such a run goes on after the key lapses, so the row has to outlive it: a run
    whose key row is gone stops, as one whose key was revoked does.
    """
    workflow_ended = [status.value for status in WorkflowRunStatus if status.is_terminal]
    return or_(
        exists().where(
            AuthoringRequest.organization_id == ApiKey.organization_id,
            AuthoringRequest.created_by_api_key_id == ApiKey.id,
            AuthoringRequest.status.in_(
                [AuthoringStatus.QUEUED.value, AuthoringStatus.RUNNING.value]
            ),
        ),
        exists().where(
            SkillCheck.organization_id == ApiKey.organization_id,
            SkillCheck.created_by_api_key_id == ApiKey.id,
            SkillCheck.status == CheckStatus.RUNNING.value,
        ),
        exists().where(
            SkillImprovementRun.organization_id == ApiKey.organization_id,
            or_(
                SkillImprovementRun.created_by_api_key_id == ApiKey.id,
                SkillImprovementRun.actor_api_key_id == ApiKey.id,
            ),
            SkillImprovementRun.status.in_([status.value for status in UNSETTLED_STATUSES]),
        ),
        exists().where(
            CaseGeneration.organization_id == ApiKey.organization_id,
            CaseGeneration.created_by_api_key_id == ApiKey.id,
            CaseGeneration.status == GenerationStatus.RUNNING.value,
        ),
        exists().where(
            BackgroundJob.organization_id == ApiKey.organization_id,
            BackgroundJob.status.in_(["queued", "running"]),
            BackgroundJob.payload["api_key_id"].astext == cast(ApiKey.id, String),
        ),
        exists().where(
            WorkflowRun.execution_api_key_id == ApiKey.id,
            WorkflowRun.status.not_in(workflow_ended),
        ),
        exists().where(
            EvalRun.created_by_api_key_id == ApiKey.id,
            EvalRun.status.in_([EvalRunStatus.QUEUED.value, EvalRunStatus.RUNNING.value]),
        ),
        exists().where(
            or_(
                ImprovementRun.created_by_api_key_id == ApiKey.id,
                ImprovementRun.actor_api_key_id == ApiKey.id,
            ),
            ImprovementRun.status.in_([status.value for status in UNSETTLED_STATUSES]),
        ),
    )


async def delete_expired_for_grant(db: AsyncSession, *, grant_id: UUID, before: datetime) -> None:
    """Drop one OAuth grant's lapsed access tokens - one is issued per refresh -
    except one an unfinished run still acts with."""
    await db.execute(
        delete(ApiKey).where(
            ApiKey.oauth_grant_id == grant_id,
            ApiKey.expires_at < before,
            ~_backs_unfinished_run(),
        )
    )


async def delete_expired_internal(db: AsyncSession, *, user_id: UUID, before: datetime) -> None:
    """Drop one person's lapsed internal credentials - one is minted per run - except
    one an unfinished run still acts with."""
    await db.execute(
        delete(ApiKey).where(
            ApiKey.user_id == user_id,
            ApiKey.internal.is_(True),
            ApiKey.expires_at < before,
            ~_backs_unfinished_run(),
        )
    )


async def revoke_for_member(
    db: AsyncSession, *, organization_id: UUID, user_id: UUID, at: datetime
) -> None:
    """Revoke every key one person holds in one organization, a connected app's included."""
    await db.execute(
        sql_update(ApiKey)
        .where(
            ApiKey.organization_id == organization_id,
            ApiKey.user_id == user_id,
            ApiKey.revoked_at.is_(None),
        )
        .values(revoked_at=at)
    )
    await db.flush()
