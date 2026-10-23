"""Every job kind bound to the function that runs it, as a production worker loads them (#2219).

A child process of the ingest pool loads these too (`app.worker.child`), so
this module is where the heavy imports happen - once per process, at start-up,
never per job.
"""

from collections.abc import Awaitable, Callable
from functools import cache

from pydantic import JsonValue

from app.worker import jobs
from app.worker.jobs import Payload, Task, Tick
from app.worker.registry import Handler, Handlers, by_kind


def _each_tick(sweep: Callable[[], Awaitable[object]]) -> Callable[[Tick], Awaitable[object]]:
    """A sweep that looks at the current state, as a schedule's job: the occurrence is not its business."""

    async def run(_tick: Tick) -> object:
        return await sweep()

    return run


def ingest() -> Handlers:
    """What an ingest child loads: its pool's three kinds, and nothing that runs an agent.

    A child holds its imports for its whole life, once per child, so loading
    only the parsing and embedding stack - not the agent runtime the other pools
    need - is a quarter of its memory and half its start-up (#2229).
    """
    from app.worker.tasks import rag_tasks

    return by_kind(
        [
            Handler(jobs.INGEST_DOCUMENT, rag_tasks.ingest_document),
            Handler(jobs.SYNC_COLLECTION, rag_tasks.sync_collection),
            Handler(jobs.SYNC_SOURCE, rag_tasks.sync_source),
        ]
    )


def production() -> Handlers:
    """Every kind, for a worker that runs the agent and system pools on its own loop."""
    from app.services.sandbox_workspace import retry_pending_destroys
    from app.worker.tasks import (
        approval_tasks,
        generated_media_tasks,
        invitation_tasks,
        mcp_tasks,
        notification_tasks,
        proactive_tasks,
        rag_tasks,
        report_tasks,
        run_tasks,
        teardown_tasks,
        trigger_tasks,
        voice_tasks,
    )
    from app.worker.tasks.background_tasks import sweep_background_jobs

    return by_kind(
        [
            *ingest().values(),
            Handler(jobs.FIRE_TRIGGER, trigger_tasks.fire_trigger),
            Handler(jobs.RUN_AGENT, run_tasks.run_agent),
            Handler(jobs.THINK_FOR_PERSON, proactive_tasks.think_for_person),
            Handler(jobs.LOOK_THROUGH_WATCH, proactive_tasks.look_through_watch),
            Handler(jobs.BRIEF_PERSON, proactive_tasks.brief_person),
            Handler(jobs.INSTALL_ROLE_PACK, proactive_tasks.install_role_pack),
            Handler(jobs.WELCOME_MEMBER, proactive_tasks.welcome_member),
            Handler(jobs.CLEANUP_EXTERNAL_STATE, teardown_tasks.run_external_state_cleanup),
            Handler(jobs.CHECK_AGENT_TRIGGERS, _each_tick(trigger_tasks.check_agent_triggers)),
            Handler(jobs.POLL_PORTAL_GRANTS, _each_tick(trigger_tasks.poll_portal_grants)),
            Handler(
                jobs.DELIVER_NOTIFICATIONS, _each_tick(notification_tasks.deliver_due_notifications)
            ),
            Handler(jobs.DISPATCH_DUE_SYNCS, _each_tick(rag_tasks.dispatch_due_syncs)),
            Handler(jobs.RETRY_SANDBOX_DESTROYS, _each_tick(retry_pending_destroys)),
            Handler(
                jobs.SWEEP_SANDBOX_OPERATIONS, _each_tick(trigger_tasks.sweep_sandbox_operations)
            ),
            Handler(jobs.SWEEP_MCP_CONNECTIONS, _each_tick(mcp_tasks.sweep_mcp_connections)),
            Handler(jobs.EXPIRE_APPROVALS, _each_tick(approval_tasks.expire_approvals)),
            Handler(jobs.EXPIRE_INVITATIONS, _each_tick(invitation_tasks.expire_invitations)),
            Handler(jobs.REAP_STALE_RUNS, _each_tick(run_tasks.reap_stale_runs)),
            Handler(
                jobs.SWEEP_TEARDOWN_RESERVATIONS,
                _each_tick(teardown_tasks.sweep_teardown_reservations),
            ),
            Handler(jobs.APPLY_RETENTION, _each_tick(rag_tasks.apply_retention)),
            Handler(jobs.SWEEP_NOTIFICATIONS, _each_tick(notification_tasks.sweep_notifications)),
            Handler(jobs.SWEEP_BACKGROUND_JOBS, _each_tick(sweep_background_jobs)),
            Handler(jobs.REAP_VOICE_CALLS, _each_tick(voice_tasks.reap_voice_calls)),
            Handler(
                jobs.SWEEP_GENERATED_MEDIA,
                _each_tick(generated_media_tasks.sweep_generated_media),
            ),
            Handler(jobs.PROACTIVE_SWEEP, proactive_tasks.proactive_sweep),
            Handler(jobs.WATCH_SWEEP, proactive_tasks.watch_sweep),
            Handler(jobs.WEEKLY_USAGE_REPORT, report_tasks.weekly_usage_report),
            Handler(jobs.MONTHLY_USAGE_REPORT, report_tasks.monthly_usage_report),
        ]
    )


Settler = Callable[[dict[str, JsonValue], str], Awaitable[None]]


def _settler[P: Payload](task: Task[P], settle: Callable[[P, str], Awaitable[None]]) -> Settler:
    async def run(payload: dict[str, JsonValue], why: str) -> None:
        await settle(task.load(payload), why)

    return run


@cache
def _settlers() -> dict[str, Settler]:
    from app.worker.tasks import rag_tasks

    return {
        jobs.INGEST_DOCUMENT.kind: _settler(jobs.INGEST_DOCUMENT, rag_tasks.settle_lost_ingest),
        jobs.SYNC_COLLECTION.kind: _settler(
            jobs.SYNC_COLLECTION, rag_tasks.settle_lost_collection_sync
        ),
        jobs.SYNC_SOURCE.kind: _settler(jobs.SYNC_SOURCE, rag_tasks.settle_lost_source_sync),
    }


async def settle_ended(kind: str, payload: dict[str, JsonValue], why: str) -> None:
    """Close what a job left outside the queue, now that no attempt of it is coming.

    The ingestion kinds leave a document `processing` or a sync log `running`
    when their process dies - the handler never reaches its own cleanup - and
    nothing else would ever finish them (Codex, #2248). Every other kind leaves
    nothing behind.
    """
    settle = _settlers().get(kind)
    if settle is not None:
        await settle(payload, why)
