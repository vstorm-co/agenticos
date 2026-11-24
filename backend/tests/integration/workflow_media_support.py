"""Native rows for media durability tests; no generation or provider calls."""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.secret_kinds import ApiKeySecret
from app.db.models.workflow_run import NodeAttempt, NodeRun
from app.repositories import workflow_run as run_repo
from app.repositories.workflow_media_operation import MediaAdmission
from app.services.organization_secret import OrganizationSecretService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import SeededRun, seed_run


@dataclass(frozen=True)
class MediaRows:
    seeded: SeededRun
    node: NodeRun
    attempt: NodeAttempt
    secret_id: UUID
    generation: UUID

    def admission(self) -> MediaAdmission:
        return MediaAdmission(
            id=uuid4(),
            organization_id=self.seeded.org.id,
            workflow_run_id=self.seeded.run.id,
            node_run_id=self.node.id,
            attempt_id=self.attempt.id,
            collector_token=uuid4(),
            request_hash="a" * 64,
            media_kind="video",
            provider="google",
            provider_api="gemini_interactions",
            model="synthetic-video",
            pricing_snapshot={
                "kind": "video",
                "pricing_as_of": "2026-11-16",
                "usd_per_second": "0.4",
                "resolution": "720p",
                "reserved_seconds": 5,
            },
            secret_id=self.secret_id,
            secret_generation=self.generation,
            reserved_usd=Decimal("2"),
            reserved_bytes=1024,
            output_file_id=uuid4(),
            output_filename="clip.mp4",
        )


async def seed_media(engine: AsyncEngine) -> MediaRows:
    node = NodeInstance(
        id=uuid4(),
        definition_id="core.input",
        definition_version=1,
        config={},
        layout=NodePosition(x=0, y=0),
    )
    seeded = await seed_run(engine, WorkflowGraph(entry_node_id=node.id, nodes=(node,)))
    async with seeded.factory() as db:
        row = (
            await db.execute(select(NodeRun).where(NodeRun.workflow_run_id == seeded.run.id))
        ).scalar_one()
        attempt = await run_repo.create_attempt(
            db,
            organization_id=seeded.org.id,
            node_run_id=row.id,
            attempt_no=1,
            idempotency_key=str(uuid4()),
            retry_guarantee="none",
            started_at=datetime.now(UTC),
            reserved_usd=Decimal("2"),
        )
        secret = await OrganizationSecretService(db).create(
            seeded.ctx,
            name="Synthetic media",
            purpose="google",
            value=ApiKeySecret(api_key="synthetic-media-operation-key"),
        )
        await run_repo.update_run(db, run=seeded.run, update_data={"budget_limit": Decimal("10")})
        await db.commit()
        return MediaRows(seeded, row, attempt, secret.id, secret.authorization_generation)
