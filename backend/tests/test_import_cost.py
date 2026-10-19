"""What importing the application must not load (#2225).

Every API worker, every restart and every Prefect flow run imports `app.main`
before doing anything: 4.3 s on a laptop, 14 s on the production host, and over a
minute when that host was short of CPU. Some of that was SDKs only one optional
capability or connector ever calls. They are imported where they are used now,
and this keeps them there - an eager import added anywhere puts the cost back on
every process, silently.

Run in a fresh interpreter: the test session has long since imported all of
these, so `sys.modules` here would say nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

DEFERRED = {
    "mem0": "the mem0 memory capability - pulls in qdrant-client and numpy",
    "qdrant_client": "mem0's vector client",
    "pymupdf": "parsing a PDF",
    "docx": "parsing a .docx",
    "boto3": "an S3 source",
    "googleapiclient": "a Google Drive source",
}


def test_importing_the_app_loads_none_of_the_deferred_sdks() -> None:
    probe = (
        "import json, sys; import app.main; "
        f"print(json.dumps([name for name in {sorted(DEFERRED)!r} if name in sys.modules]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )

    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    assert loaded == [], {name: DEFERRED[name] for name in loaded}
