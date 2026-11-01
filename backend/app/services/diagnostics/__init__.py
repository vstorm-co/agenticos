"""Pseudonymous deployment diagnostics. Explicit opt-out is checked before work."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.core.config import settings
from app.core.vault import VaultScope, seal, unseal
from app.db.models.diagnostics import DiagnosticsIdentity
from app.repositories import diagnostics as repo
from app.schemas.diagnostics import (
    Bucket,
    DiagnosticsStatusRead,
    ErrorEvent,
    FeatureUsage,
    Health,
    Heartbeat,
    Presence,
    PresenceRead,
    Registration,
    SignedError,
    SignedHeartbeat,
    SignedPresence,
    SignedRegistration,
    Surface,
)
from app.services.diagnostics.client import deliver
from app.services.diagnostics.identity import Identity


def usage_bucket(count: int) -> Bucket:
    if count == 0:
        return "0"
    if count < 10:
        return "1-9"
    if count < 100:
        return "10-99"
    if count < 1000:
        return "100-999"
    return "1000+"


def _identity(row: DiagnosticsIdentity) -> Identity:
    seed = unseal(
        row.sealed_seed, scope=VaultScope.deployment(), key_version=row.secret_key_version
    )
    return Identity(base64.b64decode(seed, validate=True))


class DiagnosticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def status(self) -> DiagnosticsStatusRead:
        row = await repo.get(self.db)
        error = None
        if row is not None and row.last_error in {"transport", "rejected"}:
            error = "transport" if row.last_error == "transport" else "rejected"
        return DiagnosticsStatusRead(
            enabled=settings.DIAGNOSTICS_ENABLED,
            collector=settings.DIAGNOSTICS_PUBLIC_URL,
            instance_id=_identity(row).instance_id if row else None,
            last_attempt=int(row.last_attempt.timestamp()) if row and row.last_attempt else None,
            last_success=int(row.last_success.timestamp()) if row and row.last_success else None,
            last_error=error,
        )

    async def presence(self, *, user_id: UUID, surface: Surface) -> PresenceRead | None:
        if not settings.DIAGNOSTICS_ENABLED:
            return None
        row = await repo.get(self.db)
        if row is None or row.last_success is None:
            return None
        identity = _identity(row)
        now = int(datetime.now(UTC).timestamp())
        event = Presence(
            instance_id=identity.instance_id,
            event_id=secrets.token_hex(16),
            at=now,
            user_id=identity.user_id(user_id),
            surface=surface,
            expires_at=now + 60,
        )
        return PresenceRead(
            endpoint=f"{settings.DIAGNOSTICS_PUBLIC_URL}/v1/presence",
            event=SignedPresence(payload=event, signature=identity.sign(event)),
        )

    async def initialize(self) -> None:
        """Commit this operation before contacting the collector for the first time."""
        if settings.DIAGNOSTICS_ENABLED and await repo.get(self.db) is None:
            sealed = seal(
                base64.b64encode(secrets.token_bytes(32)).decode(), scope=VaultScope.deployment()
            )
            await repo.initialize(
                self.db, sealed_seed=sealed.ciphertext, key_version=sealed.key_version
            )

    async def send(
        self, *, transport: httpx.AsyncBaseTransport | None = None, now: datetime | None = None
    ) -> str:
        if not settings.DIAGNOSTICS_ENABLED:
            return "disabled"
        now = now or datetime.now(UTC)
        row = await repo.get(self.db, lock=True)
        if row is None:
            return "busy"
        slot = int(now.timestamp()) // 3600
        if row.last_success and int(row.last_success.timestamp()) // 3600 == slot:
            return "already_sent"
        identity = _identity(row)
        timestamp = int(now.timestamp())
        registration = Registration(
            instance_id=identity.instance_id,
            event_id=identity.event_id("registration"),
            at=timestamp,
            public_key=identity.public_key,
        )
        counts = await repo.feature_counts(self.db, since=now - timedelta(days=30))
        health = [
            Health(component="database", status="healthy"),
            Health(component="redis", status="unknown"),
            Health(
                component="worker",
                status="healthy" if await repo.worker_alive(self.db, now=now) else "degraded",
            ),
        ]
        heartbeat = Heartbeat(
            instance_id=identity.instance_id,
            event_id=identity.event_id(f"heartbeat:{slot}"),
            at=timestamp,
            version=__version__,
            health=health,
            features=[
                FeatureUsage(name=name, enabled=count > 0, usage=usage_bucket(count))
                for name, count in counts.items()
            ],
        )
        until = now.replace(minute=0, second=0, microsecond=0)
        failures = await repo.failures(self.db, since=until - timedelta(hours=1), until=until)
        events: list[tuple[str, SignedRegistration | SignedHeartbeat | SignedError]] = [
            (
                "installations",
                SignedRegistration(payload=registration, signature=identity.sign(registration)),
            ),
            ("heartbeat", SignedHeartbeat(payload=heartbeat, signature=identity.sign(heartbeat))),
        ]
        for component, code, count in failures:
            # Only a closed category is hashed: no exception text, filenames or arguments.
            fingerprint = hashlib.sha256(f"v1:{component}:{code}".encode()).hexdigest()
            event = ErrorEvent(
                instance_id=identity.instance_id,
                event_id=identity.event_id(f"error:{slot}:{code}"),
                at=timestamp,
                component=component,
                code=code,
                fingerprint=fingerprint,
                count=min(1000, count),
            )
            events.append(("errors", SignedError(payload=event, signature=identity.sign(event))))
        row.last_attempt = now
        # Total time is bounded by the durable job's timeout as well as per-request timeouts.
        async with httpx.AsyncClient(
            timeout=5, follow_redirects=False, trust_env=False, transport=transport
        ) as client:
            for path, envelope in events:
                result = await deliver(
                    client, f"{settings.DIAGNOSTICS_COLLECTOR_URL}/v1/{path}", envelope
                )
                if result != "sent":
                    row.last_error = result
                    await repo.save(self.db, row=row)
                    return result
        row.last_success = now
        row.last_error = None
        await repo.save(self.db, row=row)
        return "sent"
