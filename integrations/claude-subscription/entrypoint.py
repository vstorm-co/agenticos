"""Apply the native users' network boundary before starting the private RPC server."""

import os

from network_guard import install_network_guard

install_network_guard()
os.execvp(
    "python",
    [
        "python",
        "-m",
        "uvicorn",
        "server:from_environment",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
        "--no-access-log",
    ],
)
