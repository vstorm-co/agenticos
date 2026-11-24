import asyncio
import json
import os
from base64 import b64decode, b64encode
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import runtime as native
from conftest import wait_for_state
from isolation import (
    Home,
    Homes,
    Owner,
    RuntimeFailure,
    native_environment,
    within_home_limit,
)
from pydantic import ValidationError
from runtime import ClaudeRuntime, authorization_url
from schemas import CodeRequest, ConnectionStatus, ImageInput, InferRequest

pytestmark = pytest.mark.anyio


def request_for(owner: Owner, prompt: str = "hello") -> InferRequest:
    return InferRequest(
        organization_id=owner.organization_id,
        user_id=owner.user_id,
        model="sonnet",
        prompt=prompt,
        output_schema={"type": "object"},
    )


def connected(engine: ClaudeRuntime, owner: Owner) -> Home:
    home = engine.homes.get(owner, create=True)
    assert home is not None
    (home.path / ".fake-connected").write_text("claude.ai")
    return home


@pytest.mark.parametrize(
    "text",
    [
        b"https://claude.ai/oauth/authorize?state=x\n",
        b"Paste code https://claude.ai/oauth/authorize?state=partial",
        b"Paste code https://claude.ai.evil.example/oauth/authorize?state=x\n",
        b"Paste code https://user@claude.ai/oauth/authorize?state=x\n",
        b"Paste code https://claude.ai:9443/oauth/authorize?state=x\n",
        b"Paste code https://claude.ai/other?state=x\n",
        b"Paste code https://claude.com/oauth/authorize?state=x\n",
        b"Paste code https://claude.ai/cai/oauth/authorize?state=x\n",
        b"Paste code https://claude.com.evil.example/cai/oauth/authorize?state=x\n",
        b"Paste code https://user@claude.com/cai/oauth/authorize?state=x\n",
        b"Paste code https://claude.com:9443/cai/oauth/authorize?state=x\n",
        b"Paste code https://claude.com/cai/oauth/authorize#bad\n",
        b"Paste code https://claude.ai/oauth/authorize#bad\n",
    ],
)
def test_prompt_requires_complete_allowlisted_provider_url(text: bytes) -> None:
    assert authorization_url(text) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://claude.ai/oauth/authorize?state=x",
        "https://claude.com/cai/oauth/authorize?state=x",
    ],
)
def test_prompt_handles_terminal_colors_and_link_wrapper(url: str) -> None:
    output = f"\x1b]8;;{url}\x1b\\{url}\x1b]8;;\x1b\\\r\n\x1b[32mPaste code:\x1b[0m"
    assert authorization_url(output.encode()) == url


async def test_real_pipes_login_code_status_and_disconnect(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    assert not (await native_runtime.status(owner)).connected
    started = await native_runtime.start_login(owner)
    assert started.login_id
    waiting = await wait_for_state(native_runtime, owner, "awaiting_code")
    assert (
        waiting.authorization_url
        and "claude.com/cai/oauth/authorize" in waiting.authorization_url
    )
    assert "fake-challenge" not in repr(waiting)
    verifying = await native_runtime.submit_code(owner, started.login_id, "test-code")
    assert verifying.state == "verifying" and verifying.authorization_url is None
    signed_in = await wait_for_state(native_runtime, owner, "connected")
    assert signed_in.connected and signed_in.login_id is None
    assert not native_runtime.processes and owner not in native_runtime.active
    result = await native_runtime.disconnect(owner)
    assert not result.connected
    assert not (await native_runtime.status(owner)).connected


async def test_prompt_can_take_longer_than_one_poll(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    home = native_runtime.homes.get(owner, create=True)
    assert home
    (home.path / ".delay-prompt").touch()
    started = await native_runtime.start_login(owner)
    await wait_for_state(native_runtime, owner, "awaiting_code")
    assert started.login_id
    await native_runtime.cancel_login(owner, started.login_id)


async def test_cancel_before_login_task_first_runs_releases_owner(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    started = await native_runtime.start_login(owner)
    assert started.login_id
    result = await native_runtime.cancel_login(owner, started.login_id)
    assert result.state == "disconnected"
    assert owner not in native_runtime.active
    retried = await native_runtime.start_login(owner)
    assert retried.login_id != started.login_id


async def test_cancel_running_login_clears_process_and_rejects_stale_code(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    started = await native_runtime.start_login(owner)
    assert started.login_id
    await wait_for_state(native_runtime, owner, "awaiting_code")
    process = native_runtime.account(owner).login_process
    assert process
    await native_runtime.cancel_login(owner, started.login_id)
    assert process.returncode is not None
    assert not native_runtime.processes
    await native_runtime.start_login(owner)
    with pytest.raises(RuntimeFailure, match="CLAUDE_LOGIN_STALE"):
        await native_runtime.submit_code(owner, started.login_id, "test-code")


async def test_other_owner_cannot_submit_or_cancel(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    started = await native_runtime.start_login(owner)
    assert started.login_id
    other = Owner(owner.organization_id, uuid4())
    for operation in (
        native_runtime.submit_code(other, started.login_id, "test-code"),
        native_runtime.cancel_login(other, started.login_id),
    ):
        with pytest.raises(RuntimeFailure, match="CLAUDE_LOGIN_STALE"):
            await operation
    assert native_runtime.account(owner).status.login_id == started.login_id


async def test_rejected_code_never_reaches_public_error(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    started = await native_runtime.start_login(owner)
    assert started.login_id
    await wait_for_state(native_runtime, owner, "awaiting_code")
    await native_runtime.submit_code(owner, started.login_id, "private-bad-code")
    failed = await wait_for_state(native_runtime, owner, "error")
    assert failed.error_code == "CLAUDE_LOGIN_FAILED"
    assert "private-bad-code" not in failed.model_dump_json()
    assert failed.authorization_url is None and failed.login_id is None


async def test_native_inference_returns_structured_output_and_actual_usage(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    connected(native_runtime, owner)
    result = await native_runtime.infer(owner, request_for(owner))
    assert result.structured_output == {"text": "Answer", "tool_calls": []}
    assert result.usage.input_tokens == 12 and result.usage.output_tokens == 8
    assert (
        result.usage.cache_read_input_tokens == 3
        and result.usage.cache_creation_input_tokens == 4
    )
    assert result.model == "claude-sonnet-test"
    assert not native_runtime.processes and not native_runtime.active


async def test_api_key_authentication_is_not_a_subscription(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    home = connected(native_runtime, owner)
    (home.path / ".fake-connected").write_text("api_key")
    assert not (await native_runtime.status(owner)).connected
    with pytest.raises(RuntimeFailure, match="CLAUDE_SIGN_IN_REQUIRED"):
        await native_runtime.infer(owner, request_for(owner))


@pytest.mark.parametrize(
    "prompt,code",
    [
        ("invalid", "CLAUDE_OUTPUT_INVALID"),
        ("error", "CLAUDE_REQUEST_FAILED"),
        ("json-array", "CLAUDE_OUTPUT_INVALID"),
        ("json-scalar", "CLAUDE_OUTPUT_INVALID"),
    ],
)
async def test_invalid_native_results_fail_without_raw_output(
    native_runtime: ClaudeRuntime, owner: Owner, prompt: str, code: str
) -> None:
    connected(native_runtime, owner)
    with pytest.raises(RuntimeFailure, match=code) as caught:
        await native_runtime.infer(owner, request_for(owner, prompt))
    assert "private provider error" not in str(caught.value)
    assert not native_runtime.active and not native_runtime.processes


async def test_stopping_model_request_reaps_its_process(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    connected(native_runtime, owner)
    await native_runtime.status(owner)
    task = asyncio.create_task(native_runtime.infer(owner, request_for(owner, "hang")))
    async with asyncio.timeout(3):
        while not native_runtime.processes:
            await asyncio.sleep(0.01)
    process = next(iter(native_runtime.processes))
    with pytest.raises(RuntimeFailure, match="CLAUDE_BUSY"):
        await native_runtime.disconnect(owner)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode is not None
    assert not native_runtime.active and not native_runtime.processes


async def test_output_limit_stops_process(
    native_runtime: ClaudeRuntime, owner: Owner
) -> None:
    home = connected(native_runtime, owner)
    with pytest.raises(RuntimeFailure, match="CLAUDE_OUTPUT_INVALID"):
        await native_runtime.command(
            home,
            [
                "--print",
                "--tools",
                "",
                "--safe-mode",
                "--strict-mcp-config",
                "--no-session-persistence",
            ],
            payload=b"overflow",
            output_limit=100,
            timeout=3,
        )
    assert not native_runtime.processes


def test_native_environment_has_no_inherited_provider_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-be-inherited")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "must-not-be-inherited")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "must-not-be-inherited")
    environment = native_environment(Home(tmp_path, 20001))
    assert set(environment) == {
        "PATH",
        "HOME",
        "CLAUDE_CONFIG_DIR",
        "USER",
        "LOGNAME",
        "LANG",
        "TERM",
        "BROWSER",
        "DISABLE_AUTOUPDATER",
    }
    assert environment["CLAUDE_CONFIG_DIR"] == str(tmp_path / ".claude")


def test_home_quota_does_not_follow_symlink(tmp_path: Path) -> None:
    root = tmp_path / "home"
    root.mkdir()
    (root / "cycle").symlink_to(root, target_is_directory=True)
    assert within_home_limit(Home(root, 20001))


def test_homes_require_container_supervisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(RuntimeError, match="container supervisor"):
        Homes(tmp_path)


@pytest.mark.parametrize(
    "code", ["", "a\nb", "a\rb", "a\x1bb", "a\x7fb", "a b", "x" * 2049]
)
def test_code_rejects_terminal_input_and_keeps_repr_private(code: str) -> None:
    with pytest.raises(ValidationError):
        CodeRequest(
            organization_id=UUID(int=1),
            user_id=UUID(int=2),
            login_id=UUID(int=3),
            code=code,
        )
    valid = CodeRequest(
        organization_id=UUID(int=1),
        user_id=UUID(int=2),
        login_id=UUID(int=3),
        code="private-code",
    )
    assert "private-code" not in repr(valid)


async def test_failed_status_process_cannot_mark_account_connected(
    native_runtime: ClaudeRuntime, owner: Owner, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = connected(native_runtime, owner)
    monkeypatch.setattr(
        native_runtime,
        "command",
        AsyncMock(return_value=(b'{"loggedIn":true,"authMethod":"claude.ai"}', 7)),
    )
    assert not await native_runtime.probe(home)


@pytest.mark.parametrize(
    "subtype,is_error",
    [("error_max_turns", False), ("success", True), ("success", None)],
)
async def test_partial_or_failed_native_envelope_cannot_complete_agent_step(
    native_runtime: ClaudeRuntime,
    owner: Owner,
    monkeypatch: pytest.MonkeyPatch,
    subtype: str,
    is_error: bool | None,
) -> None:
    connected(native_runtime, owner)
    account = native_runtime.account(owner)
    account.checked = True
    account.status = ConnectionStatus(connected=True, state="connected")
    payload = {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "structured_output": {"text": "Incomplete", "tool_calls": []},
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }
    monkeypatch.setattr(
        native_runtime,
        "command",
        AsyncMock(return_value=(json.dumps(payload).encode(), 0)),
    )
    with pytest.raises(RuntimeFailure, match="CLAUDE_REQUEST_FAILED"):
        await native_runtime.infer(owner, request_for(owner))
    assert owner not in native_runtime.active


@pytest.mark.parametrize("before_prompt", [True, False])
async def test_login_expiry_cleans_up_and_allows_retry(
    native_runtime: ClaudeRuntime,
    owner: Owner,
    monkeypatch: pytest.MonkeyPatch,
    before_prompt: bool,
) -> None:
    home = native_runtime.homes.get(owner, create=True)
    assert home
    if before_prompt:
        (home.path / ".delay-prompt").touch()
        monkeypatch.setattr(native, "PROMPT_SECONDS", 0.05)
    else:
        monkeypatch.setattr(native, "LOGIN_SECONDS", 0.3)
    first = await native_runtime.start_login(owner)
    failed = await wait_for_state(native_runtime, owner, "error")
    assert failed.error_code == "CLAUDE_LOGIN_TIMEOUT"
    assert failed.authorization_url is None and failed.login_id is None
    assert not native_runtime.active and not native_runtime.processes
    retry = await native_runtime.start_login(owner)
    assert retry.login_id is not None and retry.login_id != first.login_id


@pytest.mark.parametrize(
    "thinking,effort,enabled,budget",
    [
        (None, None, None, None),
        (True, None, True, None),
        (False, "low", False, "0"),
        ("minimal", "low", True, None),
        ("low", "low", True, None),
        ("medium", "medium", True, None),
        ("high", "high", True, None),
        ("xhigh", "xhigh", True, None),
        ("max", "max", True, None),
    ],
)
async def test_reasoning_reaches_native_argv_and_private_process_environment(
    native_runtime, owner, thinking, effort, enabled, budget
):
    home = connected(native_runtime, owner)
    request = request_for(owner).model_copy(update={"thinking": thinking})
    await native_runtime.infer(owner, request)
    sent = json.loads((home.path / ".inference.json").read_text())
    args = sent["arguments"]
    if enabled is None:
        assert "--settings" not in args
    else:
        assert json.loads(args[args.index("--settings") + 1]) == {
            "alwaysThinkingEnabled": enabled
        }
    if effort is None:
        assert "--effort" not in args
    else:
        assert args[args.index("--effort") + 1] == effort
    assert sent["thinking_budget"] == budget
    assert sent["max_output_tokens"] == "8192"
    assert sent["payload"] == request.prompt
    assert args[args.index("--output-format") + 1] == "json"


async def test_images_use_one_native_user_event_and_keep_security_flags(
    native_runtime, owner
):
    home = connected(native_runtime, owner)
    raw_images = [b"\x89PNG\r\n\x1a\nleft-image", b"\x89PNG\r\n\x1a\nright-image"]
    images = [
        ImageInput(media_type="image/png", data=b64encode(raw).decode())
        for raw in raw_images
    ]
    request = request_for(owner, "Compare [image:1] and [image:2]").model_copy(
        update={"images": images}
    )
    result = await native_runtime.infer(owner, request)
    assert result.structured_output["text"] == "Answer"
    sent = json.loads((home.path / ".inference.json").read_text())
    args = sent["arguments"]
    for flag, value in [
        ("--tools", ""),
        ("--mcp-config", '{"mcpServers":{}}'),
        ("--permission-mode", "dontAsk"),
        ("--setting-sources", ""),
        ("--max-turns", "3"),
        ("--input-format", "stream-json"),
        ("--output-format", "stream-json"),
    ]:
        assert args[args.index(flag) + 1] == value
    assert {
        "--safe-mode",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--no-chrome",
        "--verbose",
    } <= set(args)
    assert "--replay-user-messages" not in args
    [line] = sent["payload"].splitlines()
    event = json.loads(line)
    assert event["type"] == "user" and event["parent_tool_use_id"] is None
    content = event["message"]["content"]
    assert content[0] == {"type": "text", "text": request.prompt}
    for number, offset in [(1, 1), (2, 3)]:
        assert content[offset] == {"type": "text", "text": f"[image:{number}]"}
        source = content[offset + 1]["source"]
        assert source["type"] == "base64" and source["media_type"] == "image/png"
        assert b64decode(source["data"], validate=True) == raw_images[number - 1]
    assert not native_runtime.active and not native_runtime.processes


@pytest.mark.parametrize(
    "output",
    [
        b"",
        b"[]\n",
        b"private-invalid-output\n",
        b'{"type":"assistant"}\n',
        b'{"type":"result"}\n{"type":"result"}\n',
        b'{"type":"result"}\n{"type":"assistant"}\n',
    ],
)
async def test_stream_result_must_be_valid_unique_and_terminal(
    native_runtime, owner, monkeypatch, output
):
    connected(native_runtime, owner)
    account = native_runtime.account(owner)
    account.checked = True
    account.status = ConnectionStatus(connected=True, state="connected")
    monkeypatch.setattr(native_runtime, "command", AsyncMock(return_value=(output, 0)))
    request = request_for(owner).model_copy(
        update={"images": [ImageInput(media_type="image/png", data="eA==")]}
    )
    with pytest.raises(RuntimeFailure, match="CLAUDE_OUTPUT_INVALID") as caught:
        await native_runtime.infer(owner, request)
    assert "private-invalid-output" not in str(caught.value)
    assert not native_runtime.active


def test_stream_result_allows_nonresult_events_and_blank_lines_before_terminal_result():
    output = b'\n{"type":"assistant"}\n \n{"type":"result"}\n\n'
    assert native._inference_result(output, streamed=True) == {"type": "result"}


@pytest.mark.parametrize(
    "thinking", [0, 1, 4096, "true", "ultracode", {"budget_tokens": 4096}]
)
def test_native_thinking_contract_refuses_budgets_and_unrecognized_controls(
    owner, thinking
):
    with pytest.raises(ValidationError):
        InferRequest.model_validate(
            {**request_for(owner).model_dump(), "thinking": thinking}
        )


@pytest.mark.parametrize(
    "image",
    [
        {"media_type": "image/png", "data": ""},
        {"media_type": "image/png", "data": "private-not-base64"},
        {"media_type": "image/png", "data": "é"},
        {"media_type": "image/png", "data": "eA==\n"},
        {
            "media_type": "image/png",
            "data": "eA==",
            "url": "https://example.com/private",
        },
        {"media_type": "application/pdf", "data": "eA=="},
    ],
)
def test_native_image_contract_refuses_remote_and_malformed_input(image):
    with pytest.raises(ValidationError):
        ImageInput.model_validate(image)


def test_native_image_payload_is_omitted_from_repr(owner):
    image = ImageInput(media_type="image/jpeg", data="cHJpdmF0ZS1pbWFnZQ==")
    request = request_for(owner).model_copy(update={"images": [image]})
    assert "cHJpdmF0ZS1pbWFnZQ==" not in repr(image)
    assert "cHJpdmF0ZS1pbWFnZQ==" not in repr(request)
