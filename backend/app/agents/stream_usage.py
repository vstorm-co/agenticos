"""Keep final stream accounting on the usage object consumers subsequently read."""

from pydantic_ai.models import StreamedResponse
from pydantic_ai.usage import RequestUsage


def final_stream_usage(stream: StreamedResponse) -> RequestUsage:
    """Freeze usage after consumption, including streams closed before the final event.

    The pinned SDK synthesizes a copy for an exhausted stream without usage, so
    mutating `stream.usage` alone loses cost metadata. These SDK fields retain
    that snapshot without synthesizing another omission marker on later reads.
    """
    usage = stream.usage
    if stream._usage_received is False:
        usage.unmeasured_requests = max(1, usage.unmeasured_requests)
    stream._usage = usage
    stream._usage_received = None
    return usage
