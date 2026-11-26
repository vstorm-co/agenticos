"""A model selection changes a loaded Kimi config, never the vendor's saved defaults."""

import copy
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "kimi_session", Path(__file__).with_name("kimi_session.py")
)
assert spec is not None and spec.loader is not None
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


class SessionModelContract(unittest.IsolatedAsyncioTestCase):
    async def exercise(
        self, model: str, resumed: bool
    ) -> tuple[types.SimpleNamespace, list[dict[str, object]]]:
        stored = types.SimpleNamespace(
            default_model="original", default_thinking=False, models={"selected": object()}
        )
        calls: list[dict[str, object]] = []

        class CLI:
            @staticmethod
            async def create(session: object, **options: object) -> object:
                calls.append(options)
                return session

        class Server:
            pass

        server = types.ModuleType("kimi_cli.acp.server")
        server.ACPServer = Server
        server.KimiCLI = CLI
        server._expand_llm_models = lambda _models: [
            types.SimpleNamespace(model_id="selected,thinking")
        ]
        server._ModelIDConv = types.SimpleNamespace(
            from_acp_model_id=lambda value: types.SimpleNamespace(
                model_key=value.split(",")[0], thinking=value.endswith(",thinking")
            )
        )
        acp_package = types.ModuleType("kimi_cli.acp")
        acp_package.server = server
        app = types.ModuleType("kimi_cli.app")
        app.KimiCLI = CLI
        app.enable_logging = lambda: None
        config = types.ModuleType("kimi_cli.config")
        config.load_config = lambda: copy.deepcopy(stored)
        session_module = types.ModuleType("kimi_cli.session")
        session_module.Session = object
        protocol = types.ModuleType("acp")

        async def run_agent(_server: object, *, use_unstable_protocol: bool) -> None:
            self.assertTrue(use_unstable_protocol)
            await server.KimiCLI.create(object(), mcp_configs=[], ui_mode="acp", resumed=resumed)

        protocol.run_agent = run_agent
        modules = {
            "acp": protocol,
            "kimi_cli": types.ModuleType("kimi_cli"),
            "kimi_cli.acp": acp_package,
            "kimi_cli.acp.server": server,
            "kimi_cli.app": app,
            "kimi_cli.config": config,
            "kimi_cli.session": session_module,
        }
        with (
            patch.dict(sys.modules, modules),
            patch.dict(os.environ, {"AGENTICOS_KIMI_MODEL": model}),
            patch.object(host, "verify_sources"),
        ):
            await host.serve()
        return stored, calls

    async def test_new_and_restored_sessions_use_only_an_in_memory_selected_model(self) -> None:
        for resumed in [False, True]:
            stored, calls = await self.exercise("selected,thinking", resumed)
            self.assertEqual(stored.default_model, "original")
            self.assertFalse(stored.default_thinking)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["model_name"], "selected")
            self.assertTrue(calls[0]["thinking"])
            self.assertEqual(calls[0]["resumed"], resumed)
            self.assertEqual(calls[0]["config"].default_model, "selected")

    async def test_missing_catalog_choice_refuses_before_constructing_a_model(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "absent"):
            await self.exercise("missing", False)

    def test_incompatible_source_is_refused_before_importing_the_vendor_transport(self) -> None:
        with (
            patch.object(host.importlib.util, "find_spec", return_value=None),
            self.assertRaisesRegex(RuntimeError, "Python-installed"),
        ):
            host.verify_sources()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "server.py"
            source.write_text("changed source")
            with (
                patch.object(
                    host.importlib.util,
                    "find_spec",
                    return_value=types.SimpleNamespace(origin=str(source)),
                ),
                self.assertRaisesRegex(RuntimeError, "compatibility"),
            ):
                host.verify_sources()


if __name__ == "__main__":
    unittest.main()
