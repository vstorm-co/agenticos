"""`import app.main` stays cheap - the channel SDKs and the worker's tasks are not pulled in.

#520. `aiogram` (Telegram) and the worker's task modules - the parsers, the
connectors, the ingestion pipeline - are import time the API pays once per
process and the unit suite once per worker, and neither the request path nor
the tests need them: the adapters are imported inside `lifespan`, which
`ASGITransport` never runs, and a service queues a job through the light
declarations in `app.worker.jobs` rather than the module that runs it. Add back
a single top-level `from ...channels.telegram import TelegramAdapter` or
`from ...worker.tasks.rag_tasks import ingest_document` and that cost returns
with no other signal - so this is the signal.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_importing_the_app_does_not_pull_in_the_channel_sdks_or_the_workers_tasks() -> None:
    """A subprocess so the import is genuinely cold, not one a fixture warmed.

    `python -c` puts the working directory first on `sys.path`, so `import app`
    resolves from `backend/` the way the sibling reloader probe relies on it.
    """
    probe = (
        "import app.main, sys; print('aiogram' in sys.modules, "
        "'app.worker.tasks.rag_tasks' in sys.modules)"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT / "backend",
        capture_output=True,
        text=True,
        check=True,
    )

    assert loaded.stdout.strip() == "False False", (
        "importing `app.main` pulled in a channel SDK or the worker's tasks - a "
        "top-level adapter or task import has crept back and restored the cost this "
        f"defends (#520). stdout={loaded.stdout!r} stderr={loaded.stderr!r}"
    )
