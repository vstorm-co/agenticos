"""First-account authority is claimed once across password and OAuth signup."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.exceptions import AuthorizationError
from app.db.locks import LockScope, hold_name
from app.db.models.deployment_settings import DeploymentSettings
from app.db.models.user import User
from app.repositories import user_repo
from app.schemas.user import UserCreate
from app.services.user import UserService

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("mode", ["open", "closed"])
@pytest.mark.parametrize("oauth", [False, True])
async def test_simultaneous_signup_claims_exactly_one_administrator(
    db: AsyncSession, engine: AsyncEngine, mode: str, oauth: bool
) -> None:
    db.add(DeploymentSettings(signup_mode=mode))
    await db.commit()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    contenders = asyncio.Barrier(2)

    async def lock(session: AsyncSession, scope: LockScope, name: str) -> None:
        await contenders.wait()
        await hold_name(session, scope, name)

    async def signup(index: int) -> User:
        async with factory() as session:
            try:
                service = UserService(session)
                email = f"signup-{index}@example.com"
                if oauth and index == 0:
                    user = await service.get_or_create_oauth_user(
                        provider="google", provider_id="first", email=email
                    )
                else:
                    user = await service.register(UserCreate(email=email, password="password123"))
                await session.commit()
                return user
            except BaseException:
                await session.rollback()
                raise

    with (
        patch("app.repositories.user.hold_name", side_effect=lock),
        patch("app.services.user.OrganizationService.settle_new_account", AsyncMock()),
        patch(
            "app.services.user.get_email_service", return_value=MagicMock(send_welcome=AsyncMock())
        ),
        patch("app.services.user.get_password_hash", return_value="hashed-for-test"),
    ):
        async with asyncio.timeout(10):
            results = await asyncio.gather(signup(0), signup(1), return_exceptions=True)
    users = list(await db.scalars(select(User)))
    assert len(users) == (2 if mode == "open" else 1)
    assert sum(user.is_app_admin for user in users) == 1
    failures = [result for result in results if isinstance(result, BaseException)]
    assert len(failures) == (0 if mode == "open" else 1)
    assert all(isinstance(failure, AuthorizationError) for failure in failures)


async def test_first_oauth_account_gets_bootstrap_authority_on_a_closed_deployment(
    db: AsyncSession,
) -> None:
    db.add(DeploymentSettings(signup_mode="closed"))
    await db.flush()
    with (
        patch("app.services.user.OrganizationService.settle_new_account", AsyncMock()),
        patch(
            "app.services.user.get_email_service", return_value=MagicMock(send_welcome=AsyncMock())
        ),
    ):
        user = await UserService(db).get_or_create_oauth_user(
            provider="google", provider_id="first", email="owner@example.com"
        )
    assert user.is_app_admin


async def test_a_rolled_back_bootstrap_leaves_the_next_account_eligible(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    assert await user_repo.claim_first_account(db)
    db.add(User(email="rollback@example.com", hashed_password="x"))
    await db.flush()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as waiting:
        task = asyncio.create_task(user_repo.claim_first_account(waiting))
        try:
            done, _ = await asyncio.wait({task}, timeout=0.05)
            assert not done
            await db.rollback()
            assert await asyncio.wait_for(task, timeout=5)
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
