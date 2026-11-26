"""Owned foreground Hermes ACP host; deliberately never calls the gateway entry point."""

import asyncio
import hashlib
import importlib.util
import os
import sys
from pathlib import Path

# Compatibility is checked before importing vendor transport or admitting a model call.
SOURCE_REVISION = "91cb42b51bddc6841c4e50183c41c96d59e48516"
SOURCE_HASHES = {
    "acp_adapter.server": "aa5ac9f6540b61e0ddddf210e68ef2cfc92dfc3bc631b4a422f9086a1456ee29",
    "acp_adapter.session": "fb64f8c725c4cc20d4fc4561148b1b4b7ca9a5cc4654fce9ed8959ac5313fe84",
    "acp_adapter.entry": "867719e0f4b7aa2f0cdce2995c7b458a55e05ed2b749837998a14d4a71571967",
}


def verify_sources() -> None:
    for name, expected in SOURCE_HASHES.items():
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise RuntimeError("Install the documented Hermes checkout in this Python environment")
        content = Path(spec.origin).read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(content).hexdigest() != expected:
            raise RuntimeError(
                "This Hermes version has not passed the owned foreground compatibility contract"
            )


async def serve() -> None:
    home = os.environ.get("HERMES_HOME")
    if not home or not Path(home).is_absolute():
        raise RuntimeError("An isolated native Hermes home is required")
    verify_sources()
    import acp
    from acp_adapter.entry import _load_env, _setup_logging
    from acp_adapter.server import HermesACPAgent
    from acp_adapter.session import SessionManager
    from agent.ssl_verify import install_truststore
    from hermes_constants import get_hermes_home

    _setup_logging()
    _load_env()
    if get_hermes_home().resolve() != Path(home).resolve():
        raise RuntimeError("Hermes configuration changed the private profile boundary")
    install_truststore()
    manager = SessionManager()
    agent = HermesACPAgent(session_manager=manager)
    if type(agent) is not HermesACPAgent:
        raise RuntimeError("Hermes tried to attach a gateway instead of the owned foreground host")
    try:
        await acp.run_agent(agent, use_unstable_protocol=True)
    finally:
        await asyncio.to_thread(manager.end_all_sessions)


def main() -> None:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_absolute():
        raise RuntimeError("An app-owned Hermes home is required")
    os.environ["HERMES_HOME"] = sys.argv[1]
    for key in (
        "HERMES_PROFILE",
        "HERMES_TUI_GATEWAY_URL",
        "HERMES_GATEWAY_DETACHED",
        "HERMES_GATEWAY_EXTERNAL_SUPERVISOR",
    ):
        os.environ.pop(key, None)
    sys.argv = ["agenticos-hermes-acp"]
    asyncio.run(serve())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Vendor diagnostics can contain credential paths and server bodies.
        sys.stderr.write(
            "The isolated Hermes host refused setup or stopped without a known result.\n"
        )
        raise SystemExit(1) from None
