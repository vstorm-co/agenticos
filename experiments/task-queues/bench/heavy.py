"""Import what an AgenticOS worker imports, so starting a task process costs what it does in production.

Prefect's `serve` starts a new Python process for every flow run, and that process
imports the module the flow lives in - in AgenticOS, most of the application. A
benchmark whose tasks import nothing would hide exactly the cost under study, so
every backend's task module imports this first. `BENCH_IMPORT_APP=0` turns it off,
to measure the queue alone.
"""

import time

from bench import config

IMPORT_SECONDS = 0.0

if config.IMPORT_APP:
    _started = time.perf_counter()
    import app.services.agent_runner  # noqa: F401
    import app.worker.tasks.rag_tasks  # noqa: F401
    import app.worker.tasks.trigger_tasks  # noqa: F401

    IMPORT_SECONDS = time.perf_counter() - _started
