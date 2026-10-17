"""Round-robin CS pick for Shop widget live-agent queue (D3 B53)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

POOL_SHOP_LIVE_AGENT_CS = "shop_ai.live_agent.customer_care"


async def pick_round_robin_user_id(
    db: AsyncSession,
    *,
    organization_id: UUID,
    candidate_ids: list[UUID],
) -> UUID | None:
    if not candidate_ids:
        return None
    if len(candidate_ids) == 1:
        return candidate_ids[0]
    ordered = sorted(candidate_ids, key=str)
    row = await db.execute(
        text(
            """
            INSERT INTO shop_live_agent_round_robin_state (organization_id, pool_key, last_index, updated_at)
            VALUES (:organization_id, :pool_key, 0, now())
            ON CONFLICT (organization_id, pool_key) DO UPDATE
            SET last_index = shop_live_agent_round_robin_state.last_index + 1,
                updated_at = now()
            RETURNING last_index
            """
        ),
        {"organization_id": str(organization_id), "pool_key": POOL_SHOP_LIVE_AGENT_CS},
    )
    idx_row = row.fetchone()
    if not idx_row:
        return ordered[0]
    idx = int(idx_row[0]) % len(ordered)
    return ordered[idx]
