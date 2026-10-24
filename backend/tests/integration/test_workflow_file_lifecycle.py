"""Stored file references outlive their producer's retention/deletion request."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.workflow import Workflow, WorkflowVersion
from app.db.models.workflow_file import WorkflowFile
from app.db.models.workflow_run import WorkflowRun
from app.repositories import workflow_run as run_repo
from app.services.workflow_registry import WorkflowInUseError, WorkflowRegistryService
from app.workflows.graph.model import NodeInstance, NodePosition, WorkflowGraph
from tests.integration.workflow_run_support import seed_run

pytestmark = pytest.mark.anyio


def _graph() -> WorkflowGraph:
    node = NodeInstance(
        id=uuid.uuid4(),
        definition_id="core.input",
        definition_version=1,
        layout=NodePosition(x=0, y=0),
    )
    return WorkflowGraph(entry_node_id=node.id, nodes=(node,))


@pytest.mark.security
@pytest.mark.parametrize("reference", ["run", "draft", "version", "own-version"])
async def test_file_references_hold_producers_until_their_consumers_are_removed(engine, reference):
    producer = await seed_run(engine, _graph())
    consumer = await seed_run(engine, _graph(), member=(producer.principal, producer.org))
    now = datetime.now(UTC)
    identifier = uuid.uuid4()
    async with producer.factory() as db:
        source = await db.get(WorkflowRun, producer.run.id)
        other = await db.get(WorkflowRun, consumer.run.id)
        workflow = await db.get(Workflow, producer.run.workflow_id)
        target = await db.get(Workflow, consumer.run.workflow_id)
        assert (
            source is not None and other is not None and workflow is not None and target is not None
        )
        source.status, source.ended_at = "succeeded", now - timedelta(days=3)
        other.status, other.ended_at = "succeeded", now
        workflow.settings = {"run_retention_days": 1}
        db.add(
            WorkflowFile(
                id=identifier,
                organization_id=producer.org.id,
                workflow_run_id=source.id,
                storage_path=f"synthetic/{identifier}",
                content_type="text/plain",
                byte_size=1,
            )
        )
        await db.flush()
        if reference == "run":
            await run_repo.create_resource_ref(
                db,
                organization_id=producer.org.id,
                workflow_run_id=other.id,
                kind="file",
                ref={"file_id": str(identifier)},
            )
        else:
            graph = _graph()
            graph = graph.model_copy(
                update={
                    "nodes": (
                        graph.nodes[0].model_copy(
                            update={
                                "pinned_output": {
                                    "payload": {
                                        "kind": "file",
                                        "file_id": str(identifier),
                                        "content_type": "text/plain",
                                        "byte_size": 1,
                                    }
                                }
                            }
                        ),
                    )
                }
            )
            if reference == "draft":
                target.draft_graph = graph.model_dump(mode="json")
            else:
                parent = workflow if reference == "own-version" else target
                db.add(
                    WorkflowVersion(
                        organization_id=producer.org.id,
                        workflow_id=parent.id,
                        version=1,
                        graph=graph.model_dump(mode="json"),
                        published_by_user_id=producer.principal.id,
                    )
                )
        await db.commit()
    async with producer.factory() as db:
        assert await run_repo.take_expired_runs(db, now=now, limit=10) == []
        assert await db.get(WorkflowFile, identifier) is not None
        if reference == "own-version":
            await WorkflowRegistryService(db).delete(producer.ctx, producer.run.workflow_id)
            assert await db.get(Workflow, producer.run.workflow_id) is None
        else:
            with pytest.raises(WorkflowInUseError, match="uses files"):
                await WorkflowRegistryService(db).delete(producer.ctx, producer.run.workflow_id)
            assert await db.get(WorkflowFile, identifier) is not None
