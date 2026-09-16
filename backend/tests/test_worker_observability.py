"""Tracing in a process that is not the API.

`serve()` gives each flow run its own subprocess, which imports the flow's
module and runs none of the API's startup. So the question worth pinning is not
that Logfire works - it is that the one flow which runs a whole agent sets
tracing up for itself, and under a name a dashboard can tell apart from the
API's.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.core.logfire_setup import WORKER_SERVICE_SUFFIX, setup_worker_observability

pytestmark = pytest.mark.anyio

MODULE = "app.core.logfire_setup"


class TestTheWorkersOwnConfiguration:
    def test_it_configures_logfire_under_a_name_of_its_own(self):
        """One project, two processes. A slow scheduled run and a slow chat turn
        are different problems, and a service name shared between them says
        nothing about either."""
        with patch(f"{MODULE}.logfire") as logfire:
            setup_worker_observability()

        kwargs = logfire.configure.call_args.kwargs
        assert kwargs["service_name"] == f"{settings.LOGFIRE_SERVICE_NAME}{WORKER_SERVICE_SUFFIX}"
        assert kwargs["environment"] == settings.LOGFIRE_ENVIRONMENT
        logfire.instrument_pydantic_ai.assert_called_once_with()

    def test_the_api_keeps_the_deployments_own_service_name(self):
        """The suffix belongs to the worker, not to `setup_logfire`."""
        from app.core.logfire_setup import setup_logfire

        with patch(f"{MODULE}.logfire") as logfire:
            setup_logfire()

        assert logfire.configure.call_args.kwargs["service_name"] == settings.LOGFIRE_SERVICE_NAME


class TestAFiredRunSetsItselfUp:
    async def test_the_flow_configures_tracing_before_it_runs_the_agent(self):
        """The whole of #1700: without this the deployment-wide token instruments
        every run the API serves and no fired one, and the run's
        `logfire_trace_id` is null because nothing was tracing to read an id
        from. Redaction is set up in the same breath and for the same reason -
        the process ran neither (#440)."""
        from app.worker.tasks import trigger_tasks

        service = MagicMock()
        service.return_value.fire = MagicMock(return_value=None)

        with (
            patch(f"{trigger_tasks.__name__}.setup_worker_observability") as observability,
            patch(f"{trigger_tasks.__name__}.setup_logging") as logging_setup,
            patch(f"{trigger_tasks.__name__}.get_worker_db_context") as db_context,
            patch("app.services.agent_trigger.AgentTriggerService") as trigger_service,
        ):
            db_context.return_value.__aenter__.return_value = MagicMock()
            trigger_service.return_value.fire = _noop
            await trigger_tasks.run_scheduled_trigger_flow.fn(
                "11111111-1111-1111-1111-111111111111"
            )

        observability.assert_called_once_with()
        logging_setup.assert_called_once_with()


async def _noop(*args: object, **kwargs: object) -> None:
    return None
