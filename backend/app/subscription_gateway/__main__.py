"""Run the gateway: `python -m app.subscription_gateway`.

Reads `SUBSCRIPTION_GATEWAY_TOKEN` (required, shared with the backend),
`SUBSCRIPTION_GATEWAY_DATA` (sign-ins, default /data/subscription-gateway),
`CLIPROXYAPI_BINARY`, `SUBSCRIPTION_GATEWAY_IDLE_SECONDS` and
`SUBSCRIPTION_GATEWAY_MAX_PROCESSES`.
"""

import os
from collections.abc import Mapping
from pathlib import Path

import uvicorn

from ._instances import Supervisor
from ._server import create_app


def main(environ: Mapping[str, str] = os.environ) -> None:
    token = environ.get("SUBSCRIPTION_GATEWAY_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("SUBSCRIPTION_GATEWAY_TOKEN must be at least 32 characters")
    root = Path(environ.get("SUBSCRIPTION_GATEWAY_DATA", "/data/subscription-gateway"))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    supervisor = Supervisor(
        root=root,
        binary=environ.get("CLIPROXYAPI_BINARY", "/usr/local/bin/cliproxyapi"),
        idle_seconds=float(environ.get("SUBSCRIPTION_GATEWAY_IDLE_SECONDS", "600")),
        max_instances=int(environ.get("SUBSCRIPTION_GATEWAY_MAX_PROCESSES", "64")),
    )
    uvicorn.run(create_app(supervisor, token), host="0.0.0.0", port=8400)  # noqa: S104 - a compose-internal service


if __name__ == "__main__":  # pragma: no cover - the process entry point
    main()
