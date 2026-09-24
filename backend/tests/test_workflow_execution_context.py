"""`app.services.workflow_execution.context`: the in/out channel a node handler runs under.

`NodeHandler` (`(config, input) -> NodeResult`) is frozen by #1786; this is
the out-of-band context a handler reads (`current()`) and reports through
(`report_waiting_agent_run`) instead of a parameter every other node would
have to ignore - see the module's own docstring.
"""

import uuid
from decimal import Decimal

import pytest

from app.core.permissions import AuthContext, OrgRoleName
from app.services.workflow_execution import context


def _context(**overrides: object) -> context.DispatchContext:
    defaults: dict[str, object] = {
        "organization_id": uuid.uuid4(),
        "workflow_run_id": uuid.uuid4(),
        "node_run_id": uuid.uuid4(),
        "node_instance_id": uuid.uuid4(),
        "attempt_no": 1,
        "auth": AuthContext(
            user_id=uuid.uuid4(), organization_id=uuid.uuid4(), role=OrgRoleName.OWNER.value
        ),
        "resumed_agent_run_id": None,
    }
    defaults.update(overrides)
    return context.DispatchContext(**defaults)  # type: ignore[arg-type]


class TestCurrentOutsideDispatch:
    def test_raises_when_nothing_is_dispatching(self):
        with pytest.raises(RuntimeError):
            context.current()


class TestDispatchScopeDirectly:
    def test_exiting_a_scope_that_was_never_entered_is_a_no_op(self):
        # Defensive: `__exit__` is only ever called by `with`, after
        # `__enter__` has set both tokens - but it must not explode if that
        # invariant is somehow violated.
        scope = context.DispatchScope(_context())
        scope.__exit__(None, None, None)


class TestDispatchingAs:
    def test_current_returns_the_active_context_inside_the_block(self):
        given = _context()
        with context.dispatching_as(given):
            assert context.current() is given

    def test_current_raises_again_once_the_block_exits(self):
        with context.dispatching_as(_context()):
            pass
        with pytest.raises(RuntimeError):
            context.current()

    def test_nested_dispatch_scopes_restore_the_outer_context_on_exit(self):
        outer = _context()
        inner = _context()
        with context.dispatching_as(outer):
            with context.dispatching_as(inner):
                assert context.current() is inner
            assert context.current() is outer

    def test_an_exception_inside_the_block_still_restores_the_previous_context(self):
        with pytest.raises(ValueError), context.dispatching_as(_context()):
            raise ValueError("boom")
        with pytest.raises(RuntimeError):
            context.current()


class TestReportWaitingAgentRun:
    def test_a_report_inside_dispatching_as_is_visible_on_the_scope_after_exit(self):
        agent_run_id = uuid.uuid4()
        scope = context.dispatching_as(_context())
        with scope:
            context.report_waiting_agent_run(agent_run_id)
        assert scope.waiting_agent_run_id == agent_run_id

    def test_no_report_leaves_the_scope_with_none(self):
        scope = context.dispatching_as(_context())
        with scope:
            pass
        assert scope.waiting_agent_run_id is None

    def test_a_report_outside_any_dispatch_scope_is_a_no_op(self):
        # A handler under test, with no dispatcher around it, should not have
        # to stub this out to exercise its own approval path.
        context.report_waiting_agent_run(uuid.uuid4())

    def test_only_the_innermost_scopes_report_is_visible_to_it(self):
        outer_agent_run = uuid.uuid4()
        inner_agent_run = uuid.uuid4()
        outer_scope = context.dispatching_as(_context())
        with outer_scope:
            context.report_waiting_agent_run(outer_agent_run)
            inner_scope = context.dispatching_as(_context())
            with inner_scope:
                context.report_waiting_agent_run(inner_agent_run)
            assert inner_scope.waiting_agent_run_id == inner_agent_run
        assert outer_scope.waiting_agent_run_id == outer_agent_run


class TestReportCost:
    def test_reports_add_up_and_one_partial_report_marks_the_total_a_floor(self):
        scope = context.dispatching_as(_context())
        with scope:
            context.report_cost(Decimal("0.10"))
            context.report_cost(Decimal("0.05"), partial=True)
            context.report_cost(Decimal("0.01"))
        assert scope.cost == Decimal("0.16")
        assert scope.cost_is_partial is True

    def test_no_report_leaves_the_scope_at_zero(self):
        scope = context.dispatching_as(_context())
        with scope:
            pass
        assert (scope.cost, scope.cost_is_partial) == (Decimal(0), False)

    def test_a_negative_cost_is_refused(self):
        with context.dispatching_as(_context()), pytest.raises(ValueError):
            context.report_cost(Decimal("-0.01"))

    def test_a_report_outside_any_dispatch_scope_is_a_no_op(self):
        context.report_cost(Decimal("1"))
