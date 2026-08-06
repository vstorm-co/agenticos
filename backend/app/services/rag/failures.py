"""What a failed ingest is allowed to say, and where the rest of it goes.

`rag_documents.error_message` and `sync_logs.error_message` are stored columns,
rendered on the documents page and in a source's sync history to every member
who can see the collection. Both used to hold `str(exc)` from whatever raised -
an embedding client, `httpx`, `boto3`, the Google Drive client - and a provider
SDK puts the failing request in its message, which routinely means an endpoint,
an internal host, a bucket, or a URL with a key in its query string. That is the
leak #342 fixed in an HTTP body, with a longer life and a wider audience: a body
is read once by the caller, a column is read by anyone who opens a failed ingest
weeks later (#423).

So the exception's own text stays in the `logger.exception` beside the call and
goes no further, and what is stored says which stage gave up, what class of
thing raised, and what the reader can do about it. Nothing is deleted: the log
is where an operator already looks, and a flow that re-raises still puts the
whole traceback in its Prefect run.

The log is a smaller audience than the column, not a safe one. `setup_logging`
puts `PiiRedactionFilter` on the *root logger*, where it never sees a record
from a module logger, and the Prefect worker does not call it at all - so
nothing scrubs these lines today (#440). That is why the rule here is where the
text may go, rather than what it is allowed to contain.
"""

from __future__ import annotations

from enum import Enum

from app.agents.capabilities.budget import BudgetExceeded
from app.core.exceptions import AppException


class IngestionStage(Enum):
    """Which stage of an ingest gave up, and what its reader can do about it.

    The stage is named by the call site rather than inferred, because by the
    time an exception is caught the only thing that still knows whether the
    file was being parsed or embedded is the `try` it came out of. Each member
    carries the sentence stored for it and the advice that follows: two strings
    on the member rather than two lookup tables, so a stage cannot be added
    with nothing to say.
    """

    PARSE = (
        "The file could not be read",
        "check that it opens, and that this collection's parser handles the format",
    )
    INDEX = (
        "The document could not be indexed",
        "check the collection's embedding credential, then retry the upload",
    )
    RECORD = (
        "The document was indexed but its record was not updated",
        "retry the upload",
    )
    INGEST = (
        "The document could not be ingested",
        "retry the upload",
    )
    SYNC = (
        "The sync did not finish",
        "check the source's credential, then run it again",
    )

    def __init__(self, summary: str, advice: str) -> None:
        self.summary = summary
        self.advice = advice


def failure_summary(exc: BaseException, *, stage: IngestionStage) -> str:
    """The sentence a failed ingest may store, for an exception it may not.

    Ours is kept whole. An `AppException` and a `BudgetExceeded` are written in
    this repository, so their messages are controlled strings - and they are the
    most useful thing an operator can be shown: "No embedding credential is
    configured for this collection", "$12.03 spent of a $10.00 limit". Losing
    those to a generic sentence would answer the question the issue asks about
    ("is it a credential, the file, or the upstream?") with a shrug.

    Anything else is a foreign `__str__` and only its *type* is safe to store. A
    class name still carries the diagnosis a reader can act on - whether the
    upstream timed out, refused the credential or could not open the file - and
    a class name has never carried an endpoint, a bucket or a key. Note that our
    own bare `RuntimeError`s count as foreign here, and rightly: the LiteParse
    wrapper interpolates the absolute path of a temporary file into one.

    A group is unwrapped to its first cause first. The connector and MCP clients
    run on anyio task groups, so a failure arrives as "unhandled errors in a
    TaskGroup", which names nothing at all - the same unwrapping
    `probe_error_message` does in `app/agents/mcp.py`.
    """
    cause = _root_cause(exc)
    if isinstance(cause, AppException | BudgetExceeded):
        return str(cause)
    return (
        f"{stage.summary} ({type(cause).__name__}) - {stage.advice}. "
        "The worker log has the full error."
    )


def _root_cause(exc: BaseException) -> BaseException:
    """The first leaf of a nested `BaseExceptionGroup`, or *exc* itself.

    No guard on the group being empty: `BaseExceptionGroup` refuses an empty
    sequence at construction, so a group always has a first leaf.
    """
    while isinstance(exc, BaseExceptionGroup):
        exc = exc.exceptions[0]
    return exc
