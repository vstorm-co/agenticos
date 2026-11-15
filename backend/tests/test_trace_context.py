"""Keep the tracing dependency's parser bounded for untrusted JSON carriers."""

import subprocess
import sys

import pytest
from opentelemetry.trace import get_current_span
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator


@pytest.mark.security
def test_an_oversized_traceparent_is_refused_without_blocking_the_process() -> None:
    # A subprocess gives a regressed parser a hard deadline without wedging
    # pytest's own event loop. JSON carriers can preserve this embedded newline.
    subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "from opentelemetry.trace import get_current_span; "
            "from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator; "
            "value = '01-' + '1' * 32 + '-' + '2' * 16 + '-01-' + ' ' * 100000 + '\\nx'; "
            "context = TraceContextTextMapPropagator().extract({'traceparent': value}); "
            "assert not get_current_span(context).get_span_context().is_valid",
        ],
        check=True,
        timeout=10,
    )


def test_a_valid_remote_parent_keeps_its_trace_and_span_ids() -> None:
    context = TraceContextTextMapPropagator().extract(
        {"traceparent": "00-" + "1" * 32 + "-" + "2" * 16 + "-01"}
    )
    span = get_current_span(context).get_span_context()
    assert span.is_valid and span.is_remote
    assert span.trace_id == int("1" * 32, 16)
    assert span.span_id == int("2" * 16, 16)
