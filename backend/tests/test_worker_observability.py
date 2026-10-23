"""Tracing in a process that is not the API.

The worker runs none of the API's startup, so the question worth pinning is not
that Logfire works - it is that the worker sets tracing up for itself, under a
name a dashboard can tell apart from the API's. That it does so on start is
`test_worker_main.py`.
"""

from unittest.mock import patch

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
