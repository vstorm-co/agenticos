"""Resolve each chat reader's spend disclosure without changing accounting."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chat_costs import chat_cost_policy
from app.core.exceptions import NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.organization import OrganizationMember
from app.repositories import deployment_settings_repo, member_repo, organization_repo, user_repo
from app.schemas.agent import AgentRunResult
from app.schemas.console_experience import ChatCostRead, resolve_chat_costs
from app.schemas.conversation import ConversationReadWithMessages, MessageList, MessageRead

_FRAME = TypeAdapter(dict[str, JsonValue])
_FINANCIAL_FIELDS = frozenset(
    {"cost_usd", "cost_is_partial", "budget_percent", "agent_budget_percent"}
)


@dataclass(frozen=True)
class CostBearingChatFrame:
    data: dict[str, JsonValue]
    nested: tuple[Literal["usage", "result"], dict[str, JsonValue]] | None

    def redacted(self) -> dict[str, JsonValue]:
        data = {key: value for key, value in self.data.items() if key not in _FINANCIAL_FIELDS}
        if self.nested is not None:
            name, fields = self.nested
            data[name] = {
                key: value for key, value in fields.items() if key not in _FINANCIAL_FIELDS
            }
        return data


def cost_bearing_chat_frame(kind: str, payload: object) -> CostBearingChatFrame | None:
    """Inspect owned accounting frames, never an agent's text or arbitrary tool output."""
    if kind not in {"complete", "subagent_complete", "run_answer_result"}:
        return None
    data = _FRAME.validate_python(payload, strict=True)
    nested_key: Literal["usage", "result"] | None = (
        "usage" if kind == "complete" else "result" if kind == "run_answer_result" else None
    )
    nested = data.get(nested_key) if nested_key is not None else None
    if nested is not None and not isinstance(nested, dict):
        raise ValueError("A chat accounting payload must be an object")
    has_cost = any(data.get(field) is not None for field in _FINANCIAL_FIELDS)
    if nested is not None:
        has_cost = has_cost or any(nested.get(field) is not None for field in _FINANCIAL_FIELDS)
    return (
        CostBearingChatFrame(
            data, (nested_key, nested) if nested_key is not None and nested is not None else None
        )
        if has_cost
        else None
    )


class ChatCostVisibilityService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def read(self, ctx: AuthContext) -> ChatCostRead:
        member = (
            await member_repo.get_active(
                self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
            )
            if not ctx.is_anonymous and not ctx.subject_is_publisher_fallback
            else None
        )
        return await self._resolve(ctx, member)

    async def message(self, ctx: AuthContext, data: MessageRead) -> MessageRead:
        if (await self.read(ctx)).effective:
            return data
        return data.model_copy(update={"cost_usd": None, "cost_is_partial": None})

    async def conversation(
        self, ctx: AuthContext, data: ConversationReadWithMessages
    ) -> ConversationReadWithMessages:
        if (await self.read(ctx)).effective:
            return data
        return data.model_copy(
            update={
                "messages": [
                    message.model_copy(update={"cost_usd": None, "cost_is_partial": None})
                    for message in data.messages
                ]
            }
        )

    async def transcript(self, ctx: AuthContext, data: MessageList) -> MessageList:
        if (await self.read(ctx)).effective:
            return data
        return data.model_copy(
            update={
                "items": [
                    message.model_copy(update={"cost_usd": None, "cost_is_partial": None})
                    for message in data.items
                ],
                "cost": data.cost.model_copy(update={"cost_usd": None, "cost_is_partial": None})
                if data.cost is not None
                else None,
            }
        )

    async def run_result(self, ctx: AuthContext, data: AgentRunResult) -> AgentRunResult:
        if (await self.read(ctx)).effective:
            return data
        return data.model_copy(update={"cost_usd": None, "cost_is_partial": None})

    async def visible_for_user(self, *, organization_id: UUID, user_id: UUID) -> bool:
        """Refresh a socket reader's role and administrator flag before disclosing spend."""
        user = await user_repo.get_by_id(self.db, user_id)
        if user is None or not user.is_active:
            return False
        member = await member_repo.get_active(
            self.db, organization_id=organization_id, user_id=user_id
        )
        if member is None and not user.is_app_admin:
            return False
        ctx = AuthContext(
            user_id=user.id,
            organization_id=organization_id,
            role=member.role if member else "",
            is_app_admin=user.is_app_admin,
        )
        return (await self._resolve(ctx, member)).effective

    async def _resolve(self, ctx: AuthContext, member: OrganizationMember | None) -> ChatCostRead:
        organization = await organization_repo.get_by_id(self.db, ctx.organization_id)
        if organization is None:
            raise NotFoundError(message="Organization not found", details={})
        deployment = await deployment_settings_repo.get(self.db)
        return resolve_chat_costs(
            deployment.chat_costs_available if deployment else None,
            chat_cost_policy(organization.chat_cost_visibility),
            member.chat_costs_visible if member is not None else None,
            eligible=(
                not ctx.is_anonymous
                and not ctx.subject_is_publisher_fallback
                and (member is not None or ctx.is_app_admin)
            ),
            spend_privileged=ctx.has(Perm.BUDGETS_MANAGE) or ctx.has(Perm.RUNS_VIEW),
        )
