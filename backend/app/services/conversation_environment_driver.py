"""Fenced physical GUI drivers, independently of private environment viewers."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.background import spawn
from app.core.exceptions import ConflictError
from app.core.permissions import AuthContext
from app.db.session import get_db_context
from app.repositories import conversation_environment as environments

logger = logging.getLogger(__name__)
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 15


class EnvironmentDriver:
    """Own one GUI token; a stale process cannot act again after a failed renewal."""

    def __init__(
        self,
        resource_key: str,
        ctx: AuthContext,
        control: Literal["human", "agent"],
        check_authority: Callable[[AsyncSession], Awaitable[None]],
        *,
        on_acquired: Callable[[AsyncSession], Awaitable[None]] | None = None,
    ) -> None:
        self.resource_key = resource_key
        self.ctx = ctx
        self.control = control
        self.token = uuid4()
        self._check_authority = check_authority
        self._on_acquired = on_acquired
        self._heartbeat: asyncio.Task[None] | None = None
        self._failure: Exception | None = None
        self._closed = False
        self._close_lock = asyncio.Lock()

    async def acquire(self) -> None:
        now = datetime.now(UTC)
        async with get_db_context() as db:
            await self._check_authority(db)
            claimed = await environments.claim_driver(
                db,
                self.resource_key,
                organization_id=self.ctx.organization_id,
                user_id=self.ctx.user_id,
                token=self.token,
                control=self.control,
                now=now,
                lease_until=now + timedelta(seconds=LEASE_SECONDS),
            )
            if claimed and self._on_acquired is not None:
                await self._on_acquired(db)
        if not claimed:
            raise ConflictError(
                message="This environment is already being controlled. Wait until it is released."
            )
        self._heartbeat = spawn(self._beat(), name=f"environment-driver:{self.token}")

    async def require(self) -> None:
        """Check before every input, never only when the transport was attached."""
        if self._closed or self._failure is not None:
            raise ConflictError(
                message="Control of this environment was lost. Take control again."
            ) from self._failure
        if not await self._renew():
            raise ConflictError(message="Control of this environment expired. Take control again.")

    async def _renew(self) -> bool:
        now = datetime.now(UTC)
        async with get_db_context() as db:
            await self._check_authority(db)
            return await environments.renew_driver(
                db,
                self.resource_key,
                token=self.token,
                now=now,
                lease_until=now + timedelta(seconds=LEASE_SECONDS),
            )

    async def _beat(self) -> None:
        while True:
            await anyio.sleep(HEARTBEAT_SECONDS)
            try:
                renewed = await self._renew()
            except Exception as exc:
                self._failure = exc
                logger.warning(
                    "environment_driver_renewal_failed",
                    extra={"driver": str(self.token), "error_type": type(exc).__name__},
                )
                return
            if not renewed:
                self._failure = ConflictError(message="The environment driver lease expired")
                return

    async def close(self) -> None:
        """Release only this token, even if another process already took ownership."""
        with anyio.move_on_after(15, shield=True) as cleanup:
            async with self._close_lock:
                if self._closed:
                    return
                self._closed = True
                if self._heartbeat is not None:
                    self._heartbeat.cancel()
                    with suppress(asyncio.CancelledError):
                        await self._heartbeat
                async with get_db_context() as db:
                    await environments.release_driver(db, self.resource_key, token=self.token)
        if cleanup.cancel_called:
            logger.warning(
                "environment_driver_release_timed_out", extra={"driver": str(self.token)}
            )
