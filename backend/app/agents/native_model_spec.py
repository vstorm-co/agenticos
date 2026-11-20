"""Credential-free model selection and run context for native primary conversations."""

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapModelRequestHandler
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import Model, ModelRequestContext

from app.agents.deps import AgentDeps
from app.agents.isolation import ToolClass
from app.agents.model_resolver import ModelRequestSpec
from app.schemas.local_target import NativeConversationTarget, NativeHarness

NATIVE_RUNTIME_LABELS: Mapping[NativeHarness, str] = {
    "codex": "Codex",
    "claude_code": "Claude Agent",
    "external": "External agent",
}
"""Display names; "Claude Agent" is the name the SDK branding rules permit."""

_BOUND: ContextVar[RunContext[AgentDeps] | None] = ContextVar(
    "native_conversation_context", default=None
)


def current_native_context() -> RunContext[AgentDeps] | None:
    return _BOUND.get()


class NativeContext(AbstractCapability[AgentDeps]):
    """Bind the run for the non-streaming SDK signature, which carries no context argument."""

    async def wrap_model_request(
        self,
        ctx: RunContext[AgentDeps],
        *,
        request_context: ModelRequestContext,
        handler: WrapModelRequestHandler,
    ) -> ModelResponse:
        token = _BOUND.set(ctx)
        try:
            return await handler(request_context)
        finally:
            _BOUND.reset(token)


@dataclass(frozen=True, kw_only=True)
class NativeModelSpec(ModelRequestSpec):
    """Credential-free attribution for a native primary conversation."""

    target: NativeConversationTarget
    readonly_tools: Mapping[str, ToolClass]

    def build(self) -> Model:
        from app.agents.native_conversation import NativeConversationModel

        return NativeConversationModel(
            harness=self.target.harness,
            registration_id=self.target.registration_id,
            secret_id=self.target.secret_id,
            epoch=str(self.target.session_epoch),
            access=self.target.access,
            native_model=self.target.model_id,
            readonly_tools=self.readonly_tools,
            timeout_seconds=self.target.timeout_minutes * 60,
        )
