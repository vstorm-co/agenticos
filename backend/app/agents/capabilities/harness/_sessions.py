"""Where a conversation's harness sessions live, and how they are remembered.

A harness session is the CLI's own session - the id Claude Code or Codex
prints - kept beside the work, per conversation and per session name, so a
follow-up prompt continues the same work without the model carrying ids
around. The id is not a credential: it names a conversation the CLI already
holds, and it is stored in the workspace rather than the database because the
workspace is what a conversation's runs already share.

This deliberately does not reuse the coding agent's session files: a harness
session is the agent's working backend for a stream of prompts, not one task
handed off, and the two must never continue each other's sessions.
"""

import re
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities.coding_agent._harness import Harness, TaskFiles
from app.agents.capabilities.coding_agent._task import MAIN_SESSION, SESSION_NAME

WORK_DIR = ".agenticos/harness"
"""Where a conversation's harness sessions are kept, inside its workspace."""

_SESSION_FILE = re.compile(
    r"^(claude_code|codex|opencode|gemini|pi)-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:-(.+))?\.session$"
)
"""A session file's name: harness, conversation, and the session's name when named."""


@dataclass(frozen=True)
class HarnessSession:
    """One named session a conversation has open, and which harness backs it."""

    name: str
    harness: Harness


def session_path(harness: Harness, conversation_id: UUID, session: str = MAIN_SESSION) -> str:
    """Where one session's id is kept.

    The unnamed session keeps the name conversations used before names existed.
    """
    if session == MAIN_SESSION:
        return f"{WORK_DIR}/{harness}-{conversation_id}.session"
    return f"{WORK_DIR}/{harness}-{conversation_id}-{session}.session"


async def _read(ctx: Any, path: str) -> str:
    try:
        return (await ctx.workspace.read_bytes(path)).decode("utf-8", errors="replace")
    except FileNotFoundError, WorkspaceError:
        return ""


async def remembered_session(ctx: Any, harness: Harness, session: str = MAIN_SESSION) -> str | None:
    """The session id this conversation's last prompt in `session` left, if any.

    `None` for a run in no conversation: there is nothing it could continue.
    """
    if not valid_session_name(session):
        return None
    conversation_id = ctx.deps.conversation_id
    if conversation_id is None:
        return None
    text = (await _read(ctx, session_path(harness, conversation_id, session))).strip()
    return text or None


async def remember_session(
    ctx: Any, harness: Harness, session_id: str, session: str = MAIN_SESSION
) -> None:
    """Keep a session id for the conversation's next prompt in `session`."""
    conversation_id = ctx.deps.conversation_id
    if conversation_id is None:
        return
    await ctx.workspace.make_dir(WORK_DIR)
    await ctx.workspace.write_bytes(
        session_path(harness, conversation_id, session), session_id.encode()
    )


async def forget_session(ctx: Any, session: str = MAIN_SESSION) -> Harness | None:
    """Forget a named session, whatever harness backed it.

    Returns the harness it belonged to, or `None` when the conversation had no
    session by that name. The CLI's own session ends with its process, which
    already exited after the prompt; nothing is left running to stop.
    """
    if not valid_session_name(session):
        return None
    conversation_id = ctx.deps.conversation_id
    if conversation_id is None:
        return None
    for harness in ("claude_code", "codex", "opencode", "gemini", "pi"):
        path = session_path(harness, conversation_id, session)
        if (await _read(ctx, path)).strip():
            await ctx.workspace.remove(path)
            return harness
    return None


async def list_sessions(ctx: Any) -> list[HarnessSession]:
    """The named sessions this conversation has open, in the order they were found.

    Reads the session files themselves, so a session is listed exactly when its
    id is stored - no second index to drift from them.
    """
    conversation_id = ctx.deps.conversation_id
    if conversation_id is None:
        return []
    try:
        entries = await ctx.workspace.list_dir(WORK_DIR)
    except FileNotFoundError, WorkspaceError:
        return []
    found: list[HarnessSession] = []
    for entry in entries:
        if entry.is_dir:
            continue
        match = _SESSION_FILE.fullmatch(entry.name)
        if match is None or match.group(2) != str(conversation_id):
            continue
        found.append(
            # The file name's first group is one of the two harness ids by the
            # regex above; the type checker cannot see that.
            HarnessSession(
                name=match.group(3) or MAIN_SESSION, harness=cast(Harness, match.group(1))
            )
        )
    return found


def task_files(name: str) -> TaskFiles:
    """Where one prompt's events, errors and exit code are written."""
    base = f"{WORK_DIR}/{name}"
    return TaskFiles(events=f"{base}.jsonl", errors=f"{base}.err", status=f"{base}.exit")


def valid_session_name(session: str) -> bool:
    """Whether `session` is a name a session file can carry."""
    return SESSION_NAME.fullmatch(session) is not None
