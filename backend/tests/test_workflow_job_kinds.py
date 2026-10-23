"""The workflow engine's six job kinds, their handlers and their schedules.

The engine's position lives in `dispatch_outbox`; these kinds only wake workers for
it. This pins the declarations the engine's timing guarantees lean on: the node job
runs once on the agent pool, the sweeps run on the intervals the docs promise, and
the reconcile outlasts a dispatch lease.
"""

from datetime import timedelta

from app.core.config import settings
from app.worker import handlers, jobs
from app.worker.schedules import SCHEDULES, Overlap

WORKFLOW_KINDS = {
    "workflow-dispatch-node",
    "workflow-dispatch-poll",
    "workflow-reconcile",
    "workflow-schedules-check",
    "workflow-table-triggers",
    "workflow-run-retention",
}


def test_every_workflow_kind_is_declared_and_has_a_production_handler():
    assert set(jobs.TASKS) >= WORKFLOW_KINDS
    assert set(handlers.production()) >= WORKFLOW_KINDS


def test_a_child_process_of_the_ingest_pool_loads_no_workflow_handler():
    assert not WORKFLOW_KINDS & set(handlers.ingest())


def test_a_node_runs_once_on_its_own_pool_and_is_not_withdrawn_from_the_panel():
    task = jobs.WORKFLOW_DISPATCH_NODE

    assert task.pool is jobs.Pool.WORKFLOW
    # One crash ends every node the worker held; the retry ceiling is the loop-breaker.
    assert task.counts_deaths is False
    # The outbox row holds the node's position: a second attempt could only find
    # its claim held, and the reconciler decides whether to run a node again.
    assert task.max_attempts == 1
    assert task.timeout == timedelta(hours=3)
    assert task.cancellable is False


def test_the_sweeps_run_on_the_system_pool_once_each():
    for kind in WORKFLOW_KINDS - {"workflow-dispatch-node"}:
        task = jobs.TASKS[kind]
        assert task.pool is jobs.Pool.SYSTEM and task.max_attempts == 1


def test_the_schedules_fire_at_the_intervals_the_engine_promises():
    every = {schedule.name: schedule for schedule in SCHEDULES if schedule.name in WORKFLOW_KINDS}

    assert {name: schedule.every for name, schedule in every.items()} == {
        "workflow-dispatch-poll": timedelta(minutes=1),
        "workflow-reconcile": timedelta(seconds=30),
        "workflow-schedules-check": timedelta(minutes=1),
        "workflow-table-triggers": timedelta(seconds=10),
        "workflow-run-retention": timedelta(days=1),
    }
    # One at a time, so a slow sweep is never run twice beside itself.
    assert {schedule.overlap for schedule in every.values()} == {Overlap.SKIP}
    for name, schedule in every.items():
        assert schedule.task is jobs.TASKS[name]


def test_the_reconcile_outlasts_a_dispatch_lease_by_a_wide_margin():
    reconcile = next(s for s in SCHEDULES if s.name == "workflow-reconcile")

    assert reconcile.every.total_seconds() * 2 < settings.WORKFLOW_DISPATCH_LEASE_SECONDS
