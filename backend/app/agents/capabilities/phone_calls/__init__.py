"""Calls to the member's opted-in number and allowlisted handoff of this live call."""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID, uuid5

from pydantic import Field
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.agents.deps import AgentDeps
from app.core.exceptions import AppException
from app.db.session import get_db_context
from app.schemas.telephony import PhoneCallCreate, PhoneCallsConfig
from app.services.access import acting_member


@dataclass
class PhoneCalls(AbstractCapability[AgentDeps]):
    endpoint_id: UUID

    def get_instructions(self) -> str:
        return "Telephone calls require separate contact consent, quiet hours and available budget. call_me queues a call to the admitted member's own verified number; a report may play to their voicemail only with report opt-in. Never claim a queued or provider-accepted call was heard. transfer_phone_call only hands this active telephone call to an endpoint-allowlisted, opted-in contact. These tools do not grant access to a private account based on caller ID."

    def get_toolset(self) -> FunctionToolset[AgentDeps]:
        tools = FunctionToolset[AgentDeps]()
        tools.add_function(self.call_me)
        tools.add_function(self.list_phone_transfer_contacts)
        tools.add_function(self.transfer_phone_call)
        tools.add_function(self.end_phone_call)
        return tools

    async def call_me(
        self,
        ctx: RunContext[AgentDeps],
        report: Annotated[str, Field(min_length=1, max_length=5000)] | None = None,
    ) -> str:
        """Queue a call to the member's own verified and opted-in number.

        With report text, read that text as a spoken report (may reach voicemail
        only with separate report consent). Without it, call this agent for a
        realtime conversation. Never accepts a phone number or another member id.
        Scheduled reports use the ordinary routine queue and action approvals.
        """
        from app.services.telephony.calls import PhoneCallService

        deps = ctx.deps
        if (
            deps.organization_id is None
            or deps.run_person is None
            or deps.run_id is None
            or not ctx.tool_call_id
            or deps.impersonated
        ):
            return "A call needs an admitted member and a stable run/tool identity."
        async with get_db_context() as db:
            actor = await acting_member(db, deps.organization_id, str(deps.run_person))
            if actor is None:
                return "The member is no longer active."
            try:
                receipt = await PhoneCallService(db).create(
                    actor,
                    PhoneCallCreate(
                        request_key=uuid5(deps.run_id, ctx.tool_call_id),
                        endpoint_id=self.endpoint_id,
                        agent_id=deps.agent_id if report is None else None,
                        mode="conversation" if report is None else "report",
                        report=report,
                        source_conversation_id=deps.conversation_id,
                    ),
                    source_run_id=deps.run_id,
                )
                await db.commit()
            except AppException as exc:
                return f"Call refused: {exc.message}"
        return receipt.model_dump_json()

    async def list_phone_transfer_contacts(self, ctx: RunContext[AgentDeps]) -> str:
        """List this live call's allowlisted contacts currently accepting transfers, without phone numbers."""
        from app.services.telephony.runtime import transfer_options

        deps = ctx.deps
        if deps.phone_call_id is None or deps.run_id is None:
            return "This run is not holding a telephone call."
        async with get_db_context() as db:
            try:
                choices = await transfer_options(
                    db, deps.phone_call_id, source_run_id=deps.run_id, endpoint_id=self.endpoint_id
                )
            except AppException as exc:
                return f"Transfer contacts unavailable: {exc.message}"
        return (
            "\n".join(f"{item.id}: {item.label}" for item in choices)
            or "No transfer contacts are currently available."
        )

    async def transfer_phone_call(self, ctx: RunContext[AgentDeps], contact_id: UUID) -> str:
        """Transfer this live telephone call to one explicitly allowlisted contact.

        The contact must have opted into transfers, be outside quiet hours and
        have daily capacity. Remaining call time and prepaid leg budget still
        apply. The id comes from the operator's configured transfer contacts.
        """
        from app.services.telephony.runtime import transfer

        deps = ctx.deps
        if deps.phone_call_id is None or deps.run_id is None:
            return "This run is not holding a telephone call."
        async with get_db_context() as db:
            try:
                await transfer(
                    db,
                    deps.phone_call_id,
                    contact_id,
                    source_run_id=deps.run_id,
                    endpoint_id=self.endpoint_id,
                )
            except AppException as exc:
                return f"Transfer refused or awaiting provider confirmation: {exc.message}"
        return "The provider accepted the transfer. The call's original time limit still applies."

    async def end_phone_call(self, ctx: RunContext[AgentDeps]) -> str:
        """End only the telephone call this live run owns."""
        from app.services.telephony.runtime import end_from_agent

        deps = ctx.deps
        if deps.phone_call_id is None or deps.run_id is None:
            return "This run is not holding a telephone call."
        async with get_db_context() as db:
            try:
                await end_from_agent(
                    db, deps.phone_call_id, source_run_id=deps.run_id, endpoint_id=self.endpoint_id
                )
            except AppException as exc:
                return f"Call ending needs attention: {exc.message}"
        return "The call is ending."


@register(
    id="phone_calls",
    name="Telephone calls",
    category="channels",
    description="Call the member's opted-in number, read spoken reports and transfer a live call to authorized contacts.",
    config_schema=PhoneCallsConfig,
    voice="live",
    tools=(
        CapabilityToolInfo(
            id="list_phone_transfer_contacts",
            description="List this live call's allowlisted contacts currently accepting transfers, without phone numbers.",
        ),
        CapabilityToolInfo(
            id="call_me",
            description="Queue a call to the member's own verified and opted-in number.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="transfer_phone_call",
            description="Transfer this live telephone call to one explicitly allowlisted contact.",
            side_effecting=True,
        ),
        CapabilityToolInfo(
            id="end_phone_call",
            description="End only the telephone call this live run owns.",
            side_effecting=False,
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> PhoneCalls:
    config = ctx.config
    if not isinstance(config, PhoneCallsConfig):
        raise TypeError("Telephone calls need a validated endpoint binding")
    return PhoneCalls(endpoint_id=config.endpoint_id)
