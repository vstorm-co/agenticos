"""A chat's question list includes the child workflows it is synchronously waiting on."""

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.db.models.conversation import Conversation, Message
from app.db.models.workflow import Workflow
from app.repositories import workflow_run as workflow_run_repo
from app.schemas.workflow import WorkflowPublish
from app.services.workflow_execution import WorkflowExecutionService, delivery
from app.services.workflow_registry import WorkflowRegistryService
from app.workflows.contracts.io import LiteralValue
from tests.integration.test_workflow_calls import _called_run, _caller
from tests.integration.test_workflow_questions import _ANSWER, _seed
from tests.integration.workflow_run_support import drive, seed_run

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("wait", [False, True])
async def test_nested_questions_keep_their_owner_and_deliver_only_one_final_chat_message(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch, wait: bool
) -> None:
    leaf, planner = await _seed(engine, monkeypatch, rounds=1)
    graph = leaf.graph.model_copy(
        update={
            "nodes": (
                leaf.graph.nodes[0].model_copy(update={"definition_id": "trigger.workflow_call"}),
                *leaf.graph.nodes[1:],
            )
        }
    )
    async with leaf.factory() as db:
        workflow = await db.get(Workflow, leaf.run.workflow_id)
        assert workflow is not None
        workflow.draft_graph = graph.model_dump(mode="json")
        await WorkflowRegistryService(db).publish(
            leaf.ctx, workflow.id, WorkflowPublish(expected_revision=workflow.draft_revision)
        )
        await db.commit()
    parent_graph, call = _caller(leaf.run.workflow_id, wait=wait)
    parent_graph = parent_graph.model_copy(
        update={
            "bindings": (
                parent_graph.bindings[0].model_copy(
                    update={"source": LiteralValue(value={"q": "Plan for my team"})}
                ),
                *parent_graph.bindings[1:],
            )
        }
    )
    parent = await seed_run(engine, parent_graph, member=(leaf.principal, leaf.org))
    async with parent.factory() as db:
        conversation = Conversation(organization_id=parent.org.id, user_id=parent.principal.id)
        db.add(conversation)
        await db.flush()
        parent.run.reply_conversation_id = conversation.id
        await db.merge(parent.run)
        await delivery.deliver_started(
            db,
            run=await WorkflowExecutionService(db).get(parent.ctx, parent.run.id),
            conversation_id=conversation.id,
            organization_id=parent.org.id,
        )
        conversation_id = conversation.id
        await db.commit()

    assert (await drive(parent)).status == ("running" if wait else "succeeded")
    child = await _called_run(parent, call)
    assert child.run.reply_conversation_id is None
    assert (await drive(child)).status == "waiting_for_user"
    async with parent.factory() as db:
        service = WorkflowExecutionService(db)
        if wait:
            [pending] = await service.questions(parent.ctx, parent.run.id)
        else:
            assert await service.questions(parent.ctx, parent.run.id) == []
            assert (
                await workflow_run_repo.list_waited_child_runs(
                    db, workflow_run_id=parent.run.id, organization_id=parent.org.id
                )
                == []
            )
            [pending] = await service.questions(parent.ctx, child.run.id)
        assert pending.workflow_run_id == child.run.id
        await service.answer_questions(
            parent.ctx, pending.workflow_run_id, pending.node_run_id, {"question-1": _ANSWER}
        )
        await db.commit()

    assert (await drive(child)).status == "succeeded"
    assert (await drive(parent)).status == "succeeded"
    assert planner.returns == [[], [{"Audience": ["My team"]}]]
    async with parent.factory() as db:
        messages = (
            (await db.execute(select(Message).where(Message.conversation_id == conversation_id)))
            .scalars()
            .all()
        )
        assert len(messages) == 1
        assert messages[0].parts[0]["run_id"] == str(parent.run.id)
        assert messages[0].parts[0]["status"] == "succeeded"
