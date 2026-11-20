"""The foreground adapter must never construct the shared-gateway default."""

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "owned_hermes", Path(__file__).with_name("hermes_owned.py")
)
assert spec is not None and spec.loader is not None
owned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned)


class ForegroundContract(unittest.IsolatedAsyncioTestCase):
    async def test_transport_failure_still_ends_owned_sessions(self) -> None:
        seen: list[str] = []

        class Manager:
            def end_all_sessions(self) -> None:
                seen.append("ended")

        class Agent:
            def __init__(self, *, session_manager: Manager) -> None:
                self.manager = session_manager
                seen.append("foreground")

        async def run(agent: Agent, *, use_unstable_protocol: bool) -> None:
            self.assertTrue(use_unstable_protocol)
            self.assertIsInstance(agent.manager, Manager)
            seen.append("running")
            raise RuntimeError("transport failure")

        modules: dict[str, types.ModuleType] = {}
        for name, fields in {
            "acp": {"run_agent": run},
            "acp_adapter.entry": {"_setup_logging": lambda: None, "_load_env": lambda: None},
            "acp_adapter.server": {"HermesACPAgent": Agent},
            "acp_adapter.session": {"SessionManager": Manager},
            "agent.ssl_verify": {"install_truststore": lambda: None},
            "hermes_constants": {"get_hermes_home": Path.cwd},
        }.items():
            module = types.ModuleType(name)
            for key, value in fields.items():
                setattr(module, key, value)
            modules[name] = module
        with (
            patch.dict(sys.modules, modules),
            patch.dict("os.environ", {"HERMES_HOME": str(Path.cwd())}),
            patch.object(owned, "verify_sources"),
            self.assertRaisesRegex(RuntimeError, "transport failure"),
        ):
            await owned.serve()
        self.assertEqual(seen, ["foreground", "running", "ended"])

    async def test_a_home_is_required_before_import_or_vendor_launch(self) -> None:
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.object(owned, "verify_sources") as verify,
        ):
            with self.assertRaisesRegex(RuntimeError, "isolated"):
                await owned.serve()
            verify.assert_not_called()

    def test_changed_vendor_source_is_refused_before_inference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.py"
            path.write_text("altered source")
            fake_spec = types.SimpleNamespace(origin=str(path))
            with (
                patch.object(owned.importlib.util, "find_spec", return_value=fake_spec),
                self.assertRaisesRegex(RuntimeError, "compatibility"),
            ):
                owned.verify_sources()
        with (
            patch.object(owned.importlib.util, "find_spec", return_value=None),
            self.assertRaisesRegex(RuntimeError, "Install"),
        ):
            owned.verify_sources()


if __name__ == "__main__":
    unittest.main()
