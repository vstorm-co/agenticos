"""The runner supplies personal credentials and an isolated workspace, never the model."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic import SecretStr
from pydantic_ai.providers.openai_codex import OpenAICodexCredentials
from pydantic_ai.tools import RunContext
from pydantic_ai.workspaces import Workspace

from app.agents.capabilities.coding_agent._harness import Harness
from app.agents.deps import AgentDeps


class CodexSignIn(Protocol):
    async def load(self) -> OpenAICodexCredentials: ...
    async def swap(
        self, previous: OpenAICodexCredentials, rotated: OpenAICodexCredentials
    ) -> bool: ...
    async def visible_to(self, user_id: UUID) -> bool: ...


SignIn = Callable[[UUID], CodexSignIn]
PERSONAL_EXECUTOR = "coding_agent.personal_executor"


@dataclass(frozen=True)
class PersonalCodingTask:
    workspace: Workspace
    account_id: UUID
    label: str
    base_revision: str
    result_archive: str
    redactions: tuple[SecretStr, ...] = field(default=(), repr=False)
    api_key: SecretStr | None = field(default=None, repr=False)
    sign_in: SignIn | None = field(default=None, repr=False)


@runtime_checkable
class PersonalCodingExecutor(Protocol):
    def session(
        self,
        ctx: RunContext[AgentDeps],
        *,
        harness: Harness,
        timeout_seconds: int,
    ) -> AbstractAsyncContextManager[PersonalCodingTask]: ...
