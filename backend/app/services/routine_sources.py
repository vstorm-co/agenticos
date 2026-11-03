"""Review recurring work's source ceiling without probing providers or granting actions."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp import McpSourceIdentity
from app.agents.spec import AgentSpec, OrgMcpServerRef, PersonalMcpServerRef
from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.agent_trigger import AgentTrigger
from app.repositories import agent_trigger_repo, mcp_connection_repo
from app.schemas.mcp_connection import McpToolRead
from app.schemas.routine_sources import (
    RoutineSourceAccount,
    RoutineSourceConsent,
    RoutineSourcePolicy,
    RoutineSourceReview,
)
from app.services.agent_registry import AgentRegistryService
from app.services.mcp_connection import reviewed_personal_sources

_TOOLS = TypeAdapter(list[McpToolRead])
# A future spec field is conservatively source-bearing unless deliberately
# excluded here. Publishing instructions or model settings alone may still follow.
_NON_SOURCE_FIELDS = frozenset(
    {
        "name",
        "description",
        "instructions",
        "variables",
        "starters",
        "time_zone",
        "model_profile_id",
        "model_settings",
        "max_steps",
        "output_schema",
        "loop_guard",
        "reviewers",
        "budget",
        "notifications",
        "observability",
    }
)


def spec_fingerprint(spec: AgentSpec) -> str:
    return hashlib.sha256(
        json.dumps(
            spec.model_dump(mode="json", exclude=set(_NON_SOURCE_FIELDS)),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def source_scope(trigger: AgentTrigger) -> str:
    """Reprioritizing work grants no source; changing actor, origin or audience does.

    Local target changes have their separate native grant and live fingerprint.
    """
    fields = (
        "agent_id",
        "environment_id",
        "pinned_version_id",
        "runs_as_creator",
        "event_source",
        "event_config",
        "connection_id",
        "portal_key",
        "delivery_mode",
        "answer_to",
        "delivery_conversation_id",
        "teams_conversation_id",
    )
    return hashlib.sha256(
        json.dumps(
            {name: getattr(trigger, name) for name in fields},
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class RoutineSourcesRequired(AuthorizationError):
    message = "Review this routine's sources before running it again"
    code = "ROUTINE_SOURCES_REVIEW_REQUIRED"


def read_policy(value: object) -> RoutineSourcePolicy:
    try:
        return RoutineSourcePolicy.model_validate(value)
    except ValidationError:
        raise RoutineSourcesRequired() from None


def account_identities(policy: RoutineSourcePolicy) -> dict[UUID, McpSourceIdentity]:
    return {
        identifier: McpSourceIdentity(
            endpoint_hash=source.endpoint_hash,
            authorization_generation=source.authorization_generation,
            tool_prefix=source.tool_prefix,
        )
        for identifier, source in policy.mcp_sources.items()
    }


@dataclass(frozen=True)
class _Review:
    policy: RoutineSourcePolicy
    accounts: list[str]
    unavailable: list[str]

    def token(self) -> str:
        content = self.policy.model_dump(mode="json", exclude={"id", "reviewed_at"})
        return hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class RoutineSourceService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.agents = AgentRegistryService(db)

    @staticmethod
    def _human(ctx: AuthContext, trigger: AgentTrigger) -> None:
        if (
            ctx.organization_id != trigger.organization_id
            or ctx.user_id is None
            or ctx.user_id != trigger.created_by_user_id
            or ctx.api_key_id is not None
            or ctx.routine_id is not None
            or ctx.fired_as_creator is not None
            or ctx.subject_is_publisher_fallback
            or current_impersonator() is not None
        ):
            raise AuthorizationError(
                message="Only the routine's owner can review its sources in the console"
            )

    async def _review(self, ctx: AuthContext, trigger: AgentTrigger) -> _Review:
        if trigger.pinned_version_id is not None:
            _, spec, version = await self.agents.get_pinned_spec(
                ctx, trigger.agent_id, trigger.pinned_version_id
            )
        else:
            _, spec, version = await self.agents.get_runnable_spec(
                ctx, trigger.agent_id, environment_id=trigger.environment_id
            )
        sources: dict[UUID, RoutineSourceAccount] = {}
        names: set[str] = set()
        unavailable: set[str] = set()
        for ref in spec.mcp_servers:
            if isinstance(ref, OrgMcpServerRef):
                connection = await mcp_connection_repo.get_org_scoped_by_id(
                    self.db, connection_id=ref.connection_id, organization_id=ctx.organization_id
                )
                accounts = [] if connection is None else [connection]
                identities = {
                    account.id: McpSourceIdentity(
                        endpoint_hash=hashlib.sha256(account.url.encode()).hexdigest(),
                        authorization_generation=account.authorization_generation,
                        tool_prefix=account.name,
                    )
                    for account in accounts
                }
                missing_name = str(ref.connection_id)
            elif isinstance(ref, PersonalMcpServerRef) and trigger.runs_as_creator:
                accounts = await mcp_connection_repo.list_user_scoped_by_catalog_key(
                    self.db, user_id=ctx.subject_id, catalog_key=ref.catalog_key
                )
                identities = reviewed_personal_sources(ref.catalog_key, accounts)
                missing_name = ref.catalog_key
            else:
                continue
            if not accounts:
                unavailable.add(missing_name)
            for account in accounts:
                name = account.label or account.name
                names.add(f"{name} · {account.id}")
                if not account.is_enabled or account.last_tools is None:
                    unavailable.add(name)
                    continue
                try:
                    tools = _TOOLS.validate_python(account.last_tools)
                    allowed = {
                        tool.name
                        for tool in tools
                        if (
                            (ref.allowed_tools is None or tool.name in ref.allowed_tools)
                            and (
                                account.allowed_tools is None or tool.name in account.allowed_tools
                            )
                        )
                    }
                    identity = identities[account.id]
                    candidate = RoutineSourceAccount(
                        endpoint_hash=identity.endpoint_hash,
                        authorization_generation=identity.authorization_generation,
                        tool_prefix=identity.tool_prefix,
                        tool_ids=tuple(sorted(allowed)),
                    )
                except ValidationError:
                    unavailable.add(name)
                    continue
                previous = sources.get(account.id)
                if previous is not None:
                    candidate = candidate.model_copy(
                        update={
                            "tool_ids": tuple(
                                sorted(set(previous.tool_ids) | set(candidate.tool_ids))
                            )
                        }
                    )
                sources[account.id] = candidate
        input_source = None
        if trigger.connection_id is not None:
            connection = await mcp_connection_repo.get_by_id(self.db, trigger.connection_id)
            if (
                connection is None
                or connection.organization_id != ctx.organization_id
                or not connection.is_enabled
            ):
                unavailable.add("event source")
            else:
                input_source = RoutineSourceAccount(
                    endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
                    authorization_generation=connection.authorization_generation,
                )
                names.add(f"{connection.label or connection.name} · {connection.id}")
        return _Review(
            policy=RoutineSourcePolicy(
                id=uuid4(),
                consented_by=ctx.subject_id,
                reviewed_at=datetime.now(UTC),
                version_id=version,
                scope_hash=source_scope(trigger),
                spec_hash=spec_fingerprint(spec),
                mcp_sources=sources,
                input_connection_id=trigger.connection_id,
                input_source=input_source,
            ),
            accounts=sorted(names),
            unavailable=sorted(unavailable),
        )

    async def initial(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineSourcePolicy:
        """Creating the responsibility freezes its configured sources, never new grants."""
        review = await self._review(ctx, trigger)
        if review.unavailable:
            raise RoutineSourcesRequired(details={"unavailable_sources": review.unavailable})
        return review.policy

    async def options(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineSourceReview:
        self._human(ctx, trigger)
        review = await self._review(ctx, trigger)
        try:
            previous = RoutineSourcePolicy.model_validate(trigger.approved_sources)
        except ValidationError:
            previous = None
        current = previous is not None and (
            previous.model_dump(exclude={"id", "reviewed_at", "version_id"})
            == review.policy.model_dump(exclude={"id", "reviewed_at", "version_id"})
        )
        return RoutineSourceReview(
            review_token=review.token(),
            version_id=review.policy.version_id,
            current=current and not review.unavailable,
            accounts=review.accounts,
            resources=[
                "Published capability configuration, knowledge, context, skills and delegation bindings"
            ],
            unavailable_sources=review.unavailable,
        )

    async def replace(
        self, ctx: AuthContext, trigger: AgentTrigger, data: RoutineSourceConsent
    ) -> RoutineSourceReview:
        self._human(ctx, trigger)
        current = await agent_trigger_repo.get_by_id(
            self.db, trigger.id, fresh=True, for_update=True
        )
        if current is None:
            raise RoutineSourcesRequired()
        self._human(ctx, current)
        review = await self._review(ctx, current)
        if review.unavailable or data.review_token != review.token():
            raise ConflictError(
                message="The routine or its sources changed. Review them again before consenting."
            )
        await agent_trigger_repo.update(
            self.db,
            trigger=current,
            update_data={"approved_sources": review.policy.model_dump(mode="json")},
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="routine.sources_reviewed",
            target_type="agent",
            target_id=str(current.agent_id),
            details={
                "trigger_id": str(current.id),
                "version_id": str(review.policy.version_id),
                "accounts": len(review.policy.mcp_sources),
            },
        )
        return await self.options(ctx, current)
