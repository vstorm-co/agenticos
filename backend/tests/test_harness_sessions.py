"""A harness session's id, kept beside the work and resumed by name.

No harness runs here: the session files are written and read in a document
workspace, which is all these helpers touch.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities.harness._sessions import (
    WORK_DIR,
    forget_session,
    list_sessions,
    remember_session,
    remembered_session,
    session_path,
    task_files,
    valid_session_name,
)
from tests.workspaces import document_workspace

pytestmark = pytest.mark.anyio


def _ctx(conversation_id, workspace):
    return SimpleNamespace(
        deps=SimpleNamespace(conversation_id=conversation_id), workspace=workspace
    )


def test_session_files_are_named_for_their_conversation_and_session() -> None:
    conversation = uuid4()
    assert session_path("claude_code", conversation) == (
        f"{WORK_DIR}/claude_code-{conversation}.session"
    )
    assert session_path("codex", conversation, "api") == (
        f"{WORK_DIR}/codex-{conversation}-api.session"
    )
    files = task_files("abc123")
    assert files.events == f"{WORK_DIR}/abc123.jsonl"
    assert files.errors == f"{WORK_DIR}/abc123.err"
    assert files.status == f"{WORK_DIR}/abc123.exit"


async def test_a_remembered_session_is_resumed_and_a_forgotten_one_is_not() -> None:
    workspace = document_workspace()
    conversation = uuid4()
    ctx = _ctx(conversation, workspace)

    assert await remembered_session(ctx, "claude_code") is None
    await remember_session(ctx, "claude_code", "s-1")
    assert await remembered_session(ctx, "claude_code") == "s-1"

    assert await forget_session(ctx) == "claude_code"
    assert await remembered_session(ctx, "claude_code") is None


async def test_forgetting_a_session_that_was_never_opened_returns_none() -> None:
    ctx = _ctx(uuid4(), document_workspace())
    assert await forget_session(ctx) is None
    assert await forget_session(ctx, "api") is None


async def test_listing_names_only_this_conversations_sessions() -> None:
    workspace = document_workspace()
    conversation, other = uuid4(), uuid4()
    ctx = _ctx(conversation, workspace)
    await remember_session(ctx, "claude_code", "s-1")
    await remember_session(ctx, "codex", "th-1", "api")
    await remember_session(_ctx(other, workspace), "claude_code", "s-2")
    await workspace.write_bytes(f"{WORK_DIR}/notes.txt", b"not a session")
    await workspace.make_dir(session_path("gemini", conversation, "not-a-session"))

    found = await list_sessions(ctx)
    assert {(session.name, session.harness) for session in found} == {
        ("main", "claude_code"),
        ("api", "codex"),
    }


async def test_a_run_in_no_conversation_remembers_nothing() -> None:
    ctx = _ctx(None, document_workspace())
    await remember_session(ctx, "claude_code", "s-1")
    assert await remembered_session(ctx, "claude_code") is None
    assert await list_sessions(ctx) == []
    assert await forget_session(ctx) is None


def test_session_names_are_lower_case_short_names() -> None:
    assert valid_session_name("main")
    assert valid_session_name("api-2")
    assert valid_session_name("review_v2")
    assert not valid_session_name("Bad Name")
    assert not valid_session_name("a" * 41)
    assert not valid_session_name("")
    assert not valid_session_name("../x")
    assert not valid_session_name("a/b")
    assert not valid_session_name("../escape")


async def test_forgetting_an_invalid_session_name_is_none() -> None:
    ctx = _ctx(uuid4(), document_workspace())
    assert await forget_session(ctx, session="../x") is None
    assert await forget_session(ctx, session="a/b") is None
    assert await forget_session(ctx, session="") is None


@pytest.mark.security
@pytest.mark.parametrize("name", ["../other-room", "a/b", ""])
async def test_an_invalid_session_name_never_reads_a_workspace_path(name: str) -> None:
    workspace = SimpleNamespace(read_bytes=AsyncMock())
    assert await remembered_session(_ctx(uuid4(), workspace), "claude_code", name) is None
    workspace.read_bytes.assert_not_awaited()


@pytest.mark.parametrize("failure", [FileNotFoundError, WorkspaceError])
async def test_a_missing_or_unavailable_session_directory_lists_nothing(failure) -> None:
    workspace = SimpleNamespace(list_dir=AsyncMock(side_effect=failure("gone")))
    assert await list_sessions(_ctx(uuid4(), workspace)) == []
    workspace.list_dir.assert_awaited_once_with(WORK_DIR)
