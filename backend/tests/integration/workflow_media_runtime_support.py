"""Real workflow claims and isolated storage with synthetic provider transport only."""

import base64
import io
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

import httpx2
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import settings
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret
from app.db.models.workflow_run import NodeRun
from app.repositories import workflow_media_operation as media_repo
from app.repositories import workflow_run as run_repo
from app.services import image_generation, video_models
from app.services.file_storage import LocalFileStorage
from app.services.organization_secret import OrganizationSecretService
from app.services.workflow_execution import dispatcher
from app.workflows.contracts.io import Binding, LiteralValue
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from app.workflows.nodes._media_config import (
    ImageGenerateConfig,
    MediaGenerateInput,
    VideoGenerateConfig,
)
from tests.integration.workflow_run_support import SeededRun, seed_member, seed_run, start_attempt


@dataclass
class RuntimeRows:
    seeded: SeededRun
    begun: dispatcher.BegunAttempt
    config: ImageGenerateConfig | VideoGenerateConfig
    supplied: MediaGenerateInput
    storage: LocalFileStorage

    async def operation(self):
        async with self.seeded.factory() as db:
            return await media_repo.current_for_node(
                db, organization_id=self.seeded.org.id, node_run_id=self.begun.node_run_id
            )


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (12, 8), "blue").save(output, format="PNG")
    return output.getvalue()


async def seed_generation(engine, monkeypatch, tmp_path, *, kind="image", **overrides):
    monkeypatch.setattr(settings, "WORKFLOW_IMAGE_GENERATION_ENABLED", True)
    monkeypatch.setattr(settings, "WORKFLOW_VIDEO_GENERATION_ENABLED", True)
    storage = LocalFileStorage(tmp_path)
    monkeypatch.setattr("app.workflows.files.get_file_storage", lambda: storage)
    monkeypatch.setattr("app.services.workflow_media._output.get_file_storage", lambda: storage)
    provider, model = "openai", "gpt-image-1.5"
    if kind == "video":
        provider, model = next(
            (p.provider, m.id)
            for p in video_models.providers()
            for m in p.models
            if m.duration_choosable and p.api != "gemini_interactions"
        )
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        member = await seed_member(db)
        user, org = member
        ctx = AuthContext(user_id=user.id, organization_id=org.id, role="owner")
        secret = await OrganizationSecretService(db).create(
            ctx,
            name="Synthetic workflow key",
            purpose=provider,
            value=ApiKeySecret(api_key="synthetic-generation-key"),
        )
        await db.commit()
    model_type = ImageGenerateConfig if kind == "image" else VideoGenerateConfig
    config = model_type.model_validate(
        {
            "provider": provider,
            "model": model,
            "secret_id": secret.id,
            "max_output_bytes": 100_000,
            **overrides,
        }
    )
    supplied = MediaGenerateInput(prompt="A synthetic geometric sample")
    node = NodeInstance(
        id=uuid4(),
        definition_id=f"{kind}.generate",
        definition_version=1,
        config=config.model_dump(mode="json"),
        layout=NodePosition(x=0, y=0),
    )
    graph = WorkflowGraph(
        entry_node_id=node.id,
        nodes=(node,),
        bindings=(
            Binding(
                target_node_id=node.id,
                target_field="prompt",
                source=LiteralValue(value=supplied.prompt),
            ),
        ),
    )
    seeded = await seed_run(engine, graph, member=member)
    async with seeded.factory() as db:
        await run_repo.update_run(db, run=seeded.run, update_data={"budget_limit": Decimal("20")})
        node_id = (
            await db.execute(select(NodeRun.id).where(NodeRun.workflow_run_id == seeded.run.id))
        ).scalar_one()
        await db.commit()
    begun = await start_attempt(seeded, node_id)
    return RuntimeRows(seeded, begun, config, supplied, storage)


def image_transport(
    monkeypatch, data, *, before_response=None, missing_image=False, service_tier="default"
):
    requests = []

    async def answer(request):
        requests.append(request)
        if before_response is not None:
            await before_response(request)
        output = [
            {
                "id": "ig_synthetic",
                "type": "image_generation_call",
                "status": "completed",
                "output_format": "png",
                "result": base64.b64encode(data).decode(),
            }
        ]
        if missing_image:
            output = [
                {
                    "id": "msg_synthetic",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "No image", "annotations": []}],
                }
            ]
        return httpx2.Response(
            200,
            json={
                "id": "resp_synthetic",
                "object": "response",
                "created_at": 1,
                "model": "gpt-5.4",
                "status": "completed",
                "output": output,
                "service_tier": service_tier,
                "usage": {"input_tokens": 7, "output_tokens": 1, "total_tokens": 8},
            },
        )

    client = image_generation.ImageHTTPClient
    monkeypatch.setattr(
        image_generation,
        "ImageHTTPClient",
        lambda **kwargs: client(**kwargs, transport=httpx2.MockTransport(answer)),
    )
    return requests
