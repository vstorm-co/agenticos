"""Authenticated presence claims and administrator-only diagnostic status."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import CurrentAppAdmin, CurrentUser, DiagnosticsSvc
from app.schemas.diagnostics import DiagnosticsStatusRead, PresenceCreate, PresenceRead

router = APIRouter()


@router.get("/admin/diagnostics", response_model=DiagnosticsStatusRead)
async def diagnostics_status(service: DiagnosticsSvc, _user: CurrentAppAdmin) -> Any:
    """Read operational status. Configuration changes belong exclusively in .env."""
    return await service.status()


@router.post("/diagnostics/presence", response_model=PresenceRead | None)
async def presence_claim(data: PresenceCreate, service: DiagnosticsSvc, user: CurrentUser) -> Any:
    """Mint a 60-second presence claim for the authenticated account, never a supplied ID.

    Null means diagnostics is disabled or the collector has not acknowledged an
    installation heartbeat. Browsers send claims directly without session cookies
    so the collector can derive coarse geography from their connection.
    """
    return await service.presence(user_id=user.id, surface=data.surface)
