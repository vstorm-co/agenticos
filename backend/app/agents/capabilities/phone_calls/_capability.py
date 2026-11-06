"""Telephone capability bound to one published endpoint."""

from dataclasses import dataclass
from uuid import UUID

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import FunctionToolset

from app.agents.deps import AgentDeps

from ._toolset import PhoneCallTools


@dataclass
class PhoneCalls(AbstractCapability[AgentDeps]):
    endpoint_id: UUID

    def get_instructions(self) -> str:
        return "Telephone calls require separate contact consent, quiet hours and available budget. call_me queues a call to the admitted member's own verified number; a report may play to their voicemail only with report opt-in. Never claim a queued or provider-accepted call was heard. transfer_phone_call only hands this active telephone call to an endpoint-allowlisted, opted-in contact. These tools do not grant access to a private account based on caller ID."

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        return PhoneCallTools(self.endpoint_id).get_toolset()
