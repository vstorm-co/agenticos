"""`import app.main` stays cheap - the channel SDKs and Prefect are not pulled in.

#520. `aiogram` (Telegram) and `prefect` together are the better part of three
seconds of import that the API pays once per process and the unit suite pays
once per worker, and neither the request path nor the tests touch them: the
adapters are imported inside `lifespan`, which `ASGITransport` never runs, and
the sync flows are imported by the dispatcher method that queues them, not at
module top. Add back a single top-level `from ...channels.telegram import
TelegramAdapter` or `from ...worker.tasks.rag_tasks import sync_collection_flow`
and that cost returns with no other signal - so this is the signal.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_importing_the_app_does_not_pull_in_the_channel_sdks_or_prefect() -> None:
    """A subprocess so the import is genuinely cold, not one a fixture warmed.

    `python -c` puts the working directory first on `sys.path`, so `import app`
    resolves from `backend/` the way the sibling reloader probe relies on it.
    """
    probe = "import app.main, sys; print('aiogram' in sys.modules, 'prefect' in sys.modules)"
    loaded = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT / "backend",
        capture_output=True,
        text=True,
        check=True,
    )

    assert loaded.stdout.strip() == "False False", (
        "importing `app.main` pulled in a channel SDK or Prefect - a top-level "
        "adapter or flow import has crept back and restored the import cost this "
        f"defends (#520). stdout={loaded.stdout!r} stderr={loaded.stderr!r}"
    )
