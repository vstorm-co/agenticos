"""Source-checked Kimi ACP host with an in-memory model default per process."""

import asyncio
import hashlib
import importlib.util
import os
from pathlib import Path

SOURCE_REVISION = "9ab1286b8fe4e6bcd116949a27ce5e0ac3389c82"
SOURCE_HASHES = {
    "kimi_cli.acp.server": "1d640f85080ff422b4bf4774b4b6d4f2e5d2d15abbc83226adc37053b1c66476",
    "kimi_cli.app": "51bfd939959c492e63ef3d327385ac5511ee35e83cd118fb5c83d6ffa09bf76f",
    "kimi_cli.config": "77802fce6b65addf061e1607e04de0646ffa06d1d4c38d807a4cff6635a791c9",
}


def verify_sources() -> None:
    for name, expected in SOURCE_HASHES.items():
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            raise RuntimeError("Use the documented Python-installed Kimi CLI environment")
        if (
            hashlib.sha256(Path(spec.origin).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            != expected
        ):
            raise RuntimeError(
                "This Kimi version has not passed the session-model compatibility contract"
            )


async def serve() -> None:
    verify_sources()
    import acp
    from kimi_cli.acp import server
    from kimi_cli.app import KimiCLI, enable_logging
    from kimi_cli.config import load_config
    from kimi_cli.session import Session

    selected = os.environ["AGENTICOS_KIMI_MODEL"]

    class SessionCLI:
        @staticmethod
        async def create(
            session: Session,
            *,
            mcp_configs: list[dict[str, object]],
            ui_mode: str,
            resumed: bool = False,
        ) -> KimiCLI:
            config = load_config()
            choices = {choice.model_id for choice in server._expand_llm_models(config.models)}
            if selected not in choices:
                raise RuntimeError("The selected Kimi model is absent from this account's catalog")
            model = server._ModelIDConv.from_acp_model_id(selected)
            # Only this process's loaded object changes. Vendor-owned credentials,
            # refresh and configuration files stay with Kimi and are never copied.
            config.default_model = model.model_key
            config.default_thinking = model.thinking
            return await KimiCLI.create(
                session,
                config=config,
                model_name=model.model_key,
                thinking=model.thinking,
                mcp_configs=mcp_configs,
                ui_mode=ui_mode,
                resumed=resumed,
            )

    # ACPServer's source-checked construction seam has no injectable factory.
    # Its new/load paths call only create(session, mcp_configs=..., ui_mode=...).
    server.KimiCLI = SessionCLI
    enable_logging()
    await acp.run_agent(server.ACPServer(), use_unstable_protocol=True)


if __name__ == "__main__":
    asyncio.run(serve())
