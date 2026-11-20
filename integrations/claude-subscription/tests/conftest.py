"""Exercise the real subprocess protocol with a local fake CLI, without signing in."""

import asyncio
import sys
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import runtime as native
from isolation import Home, Homes, Owner

FAKE_CLI = r"""
import json, os, pathlib, sys, time
root = pathlib.Path.cwd()
args = sys.argv[1:]
if args[:2] == ["auth", "status"]:
    value = root / ".fake-connected"
    print(json.dumps({"loggedIn": value.exists(), "authMethod": value.read_text() if value.exists() else None}))
elif args[:2] == ["auth", "logout"]:
    (root / ".fake-connected").unlink(missing_ok=True)
    print("Signed out")
elif args[:2] == ["auth", "login"]:
    if (root / ".delay-prompt").exists():
        time.sleep(1.2)
    print("Open https://claude.com/cai/oauth/authorize?state=fake-state&code_challenge=fake-challenge", flush=True)
    print("Paste code here: ", end="", flush=True)
    code = sys.stdin.readline().strip()
    if code != "test-code":
        print("Bad authorization code: " + code, flush=True)
        sys.exit(1)
    (root / ".fake-connected").write_text("claude.ai")
    print("Signed in", flush=True)
else:
    payload = sys.stdin.read()
    prompt = payload
    (root / ".inference.json").write_text(json.dumps({
        "arguments": args, "payload": payload,
        "max_output_tokens": os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS"),
        "thinking_budget": os.environ.get("MAX_THINKING_TOKENS"),
    }))
    if "--input-format" in args:
        assert args[args.index("--input-format") + 1] == "stream-json"
        assert args[args.index("--output-format") + 1] == "stream-json"
        assert "--verbose" in args
        [line] = payload.splitlines()
        event = json.loads(line)
        assert event["type"] == "user" and event["message"]["role"] == "user"
        prompt = event["message"]["content"][0]["text"]
        print(json.dumps({"type": "system", "subtype": "init"}))
    assert args[args.index("--tools") + 1] == ""
    assert "--safe-mode" in args and "--bare" not in args
    assert "--strict-mcp-config" in args and "--no-session-persistence" in args
    print("A harmless native warning", file=sys.stderr)
    if prompt == "hang":
        time.sleep(60)
    if prompt == "error":
        print(json.dumps({"is_error": True, "result": "private provider error"}))
        sys.exit(1)
    if prompt == "invalid":
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "no structured response"}))
    elif prompt == "json-array":
        print(json.dumps(["private provider error"]))
    elif prompt == "json-scalar":
        print(json.dumps("private provider error"))
    elif prompt == "overflow":
        print("x" * 100000)
    else:
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                          "structured_output": {"text": "Answer", "tool_calls": []},
                          "usage": {"input_tokens": 12, "output_tokens": 8,
                                    "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4},
                          "modelUsage": {"claude-sonnet-test": {}}}))
"""


class MemoryHomes(Homes):
    def __init__(self, root: Path) -> None:
        self.root = root
        self.items: dict[Owner, Home] = {}

    def get(self, owner: Owner, *, create: bool = False) -> Home | None:
        if owner not in self.items and create:
            path = self.root / owner.key
            path.mkdir(mode=0o700)
            self.items[owner] = Home(path, 20001 + len(self.items))
        return self.items.get(owner)

    def close(self) -> None:
        pass


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def owner() -> Owner:
    return Owner(UUID(int=1), UUID(int=2))


@pytest.fixture
async def native_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cli = tmp_path / "fake-claude"
    cli.write_text(f"#!{sys.executable}\n" + FAKE_CLI)
    cli.chmod(0o700)
    homes = MemoryHomes(tmp_path)
    engine = native.ClaudeRuntime(homes, cli_path=str(cli))
    real_spawn = asyncio.create_subprocess_exec

    async def spawn_as_test_user(*args, **kwargs):
        # This unprivileged test process cannot assume production UIDs. Assert the
        # isolation contract, then run only our fake executable as the test user.
        assert kwargs.pop("user") >= 20001
        assert kwargs.pop("group") >= 20001
        assert kwargs.pop("extra_groups") == ()
        assert kwargs["umask"] == 0o077
        assert kwargs["start_new_session"] is True
        return await real_spawn(*args, **kwargs)

    monkeypatch.setattr(native.asyncio, "create_subprocess_exec", spawn_as_test_user)
    monkeypatch.setattr(native, "signal_native_user", lambda _uid, _signal: None)
    try:
        yield engine
    finally:
        await engine.close()


async def wait_for_state(engine: native.ClaudeRuntime, owner: Owner, expected: str):
    async with asyncio.timeout(5):
        while True:
            status = await engine.status(owner)
            if status.state == expected:
                return status
            if status.state == "error" and expected != "error":
                pytest.fail(status.error_code)
            await asyncio.sleep(0.01)
