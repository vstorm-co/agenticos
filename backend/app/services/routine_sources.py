"""Review recurring work's source ceiling without probing providers or granting actions."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp import McpSourceIdentity, tool_prefix
from app.agents.spec import AgentSpec, OrgMcpServerRef, PersonalMcpServerRef, PlatformMcpServerRef
from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.external_agent import ExternalAgent
from app.db.models.project import Project
from app.repositories import agent_repo, agent_trigger_repo, mcp_connection_repo, project_repo
from app.repositories import external_agent as external_repo
from app.schemas.mcp_connection import McpToolRead
from app.schemas.routine_sources import (
    RoutineSourceAccount,
    RoutineSourceConsent,
    RoutineSourcePolicy,
    RoutineSourceReview,
)
from app.services.agent_registry import AgentRegistryService
from app.services.mcp_connection import reviewed_personal_sources
from app.services.project import ProjectService

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
    material = spec.model_dump(mode="json", exclude=set(_NON_SOURCE_FIELDS))
    # An empty app-binding field grants nothing new to a pre-version-14 routine.
    if not spec.table_bindings:
        material.pop("table_bindings", None)
    return hashlib.sha256(
        json.dumps(
            material,
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
        "provider_target",
        "delivery_mode",
        "answer_to",
        "delivery_conversation_id",
        "teams_conversation_id",
    )
    return hashlib.sha256(
        json.dumps(
            {
                **{name: getattr(trigger, name) for name in fields},
                **(
                    {"project_id": str(trigger.project_id)}
                    if trigger.project_id is not None
                    else {}
                ),
            },
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class RoutineSourcesRequired(AuthorizationError):
    message = "Review this routine's sources before running it again"
    code = "ROUTINE_SOURCES_REVIEW_REQUIRED"


class PlatformRoutineIdentityRequired(RoutineSourcesRequired):
    message = (
        "The AgenticOS platform MCP server requires Act as creator. Enable it or remove "
        "the platform binding from this agent and its delegates."
    )
    code = "ROUTINE_PLATFORM_IDENTITY_REQUIRED"


def read_policy(value: object) -> RoutineSourcePolicy:
    try:
        return RoutineSourcePolicy.model_validate(value)
    except ValidationError:
        raise RoutineSourcesRequired() from None


def project_fingerprint(project: Project) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                project.backend,
                str(project.sandbox_connection_id),
                str(project.workspace_generation),
                project.runtime,
                str(project.workspace_move_job_id),
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


async def external_fingerprint(db: AsyncSession, agent: ExternalAgent) -> str:
    from app.repositories import organization_secret_repo

    generation = None
    if agent.secret_id is not None:
        generation = await organization_secret_repo.authorization_generation(
            db, agent.secret_id, organization_id=agent.organization_id
        )
        if generation is None:
            raise RoutineSourcesRequired(message="The remote agent's credential is unavailable")
    return hashlib.sha256(
        json.dumps(
            [agent.endpoint_url, agent.card_url, agent.card, str(agent.secret_id), str(generation)],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


async def require_bound_sources(
    db: AsyncSession, *, organization_id: UUID, policy: RoutineSourcePolicy
) -> None:
    from app.repositories import organization_secret_repo

    for identifier, expected in policy.mirage_accounts.items():
        account = await mcp_connection_repo.get_account(db, identifier)
        if (
            account is None
            or not account.is_enabled
            or account.authorization_generation != expected
        ):
            raise RoutineSourcesRequired()
    for identifier, expected in policy.secret_sources.items():
        if (
            await organization_secret_repo.authorization_generation(
                db, identifier, organization_id=organization_id
            )
            != expected
        ):
            raise RoutineSourcesRequired()
    if policy.phone_sources:
        from app.repositories import channel_bot_repo
        from app.repositories import telephony as phone_repo
        from app.services.telephony.policy import endpoint_fingerprint

        for identifier, expected in policy.phone_sources.items():
            endpoint = await phone_repo.endpoint(db, identifier, organization_id=organization_id)
            bot = (
                await channel_bot_repo.get_for_org(
                    db, endpoint.bot_id, organization_id=organization_id
                )
                if endpoint is not None
                else None
            )
            if (
                endpoint is None
                or not endpoint.enabled
                or bot is None
                or not bot.is_active
                or bot.authorization_generation != endpoint.bot_generation
                or endpoint_fingerprint(endpoint, bot) != expected
            ):
                raise RoutineSourcesRequired()
    if policy.project_id is not None:
        project = await project_repo.get(db, policy.project_id, organization_id=organization_id)
        if project is None or project_fingerprint(project) != policy.project_hash:
            raise RoutineSourcesRequired()
    for identifier, expected in policy.external_sources.items():
        source = await external_repo.get(db, identifier, organization_id=organization_id)
        if source is None or await external_fingerprint(db, source) != expected:
            raise RoutineSourcesRequired()

    bindings = list(policy.mcp_sources.items())
    if policy.input_connection_id is not None and policy.input_source is not None:
        bindings.append((policy.input_connection_id, policy.input_source))
    for identifier, expected_account in bindings:
        account = await mcp_connection_repo.get_by_id(db, identifier, fresh=True)
        if (
            account is None
            or not account.is_enabled
            or hashlib.sha256(account.url.encode()).hexdigest() != expected_account.endpoint_hash
            or account.authorization_generation != expected_account.authorization_generation
        ):
            raise RoutineSourcesRequired()


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
class RoutineSourceSnapshot:
    policy: RoutineSourcePolicy
    accounts: list[str]
    unavailable: list[str]
    resources: list[str]
    requires_creator_identity: bool = False

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
            or not ctx.acts_in_person
            or current_impersonator() is not None
        ):
            raise AuthorizationError(message="Only the routine's owner can review its sources")

    async def _review(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineSourceSnapshot:
        if trigger.pinned_version_id is not None:
            _, spec, version = await self.agents.get_pinned_spec(
                ctx, trigger.agent_id, trigger.pinned_version_id
            )
        else:
            _, spec, version = await self.agents.get_runnable_spec(
                ctx, trigger.agent_id, environment_id=trigger.environment_id
            )
        project_hash = None
        if trigger.project_id is not None:
            project = await ProjectService(self.db).source_for_routine(ctx, trigger.project_id)
            project_hash = project_fingerprint(project)
        sources: dict[UUID, RoutineSourceAccount] = {}
        root_sources: set[UUID] = set()
        names: set[str] = set()
        unavailable: set[str] = set()
        requires_creator_identity = False
        specs = [spec]
        seen: set[UUID] = set()
        resources: set[str] = set()
        for current in specs:
            resources.update(f"Knowledge · {identifier}" for identifier in current.collection_ids)
            resources.update(f"Context · {identifier}" for identifier in current.context_ids)
            resources.update(f"Skill · {identifier}" for identifier in current.skill_ids)
            resources.update(f"Capability · {binding.id}" for binding in current.capabilities)
            resources.update(
                f"Table · {grant.table_id} · {'/'.join(operation.value for operation in grant.operations)}"
                for grant in current.table_bindings
            )
            for delegate in current.subagents:
                if delegate.agent_version_id in seen:
                    continue
                if len(seen) >= 64:
                    raise RoutineSourcesRequired(
                        message="A routine can review at most 64 delegate versions"
                    )
                seen.add(delegate.agent_version_id)
                # Published parents lend their pinned delegates. Requiring a new
                # direct run grant here would contradict the delegate runner.
                child_agent = await agent_repo.get(
                    self.db, delegate.agent_id, organization_id=ctx.organization_id
                )
                child_version = await agent_repo.get_version(
                    self.db, delegate.agent_version_id, organization_id=ctx.organization_id
                )
                if (
                    child_agent is None
                    or child_agent.status == "archived"
                    or child_version is None
                    or child_version.agent_id != delegate.agent_id
                ):
                    raise RoutineSourcesRequired()
                specs.append(AgentSpec.model_validate(child_version.spec))
                resources.add(f"Delegate · {delegate.agent_id} · {delegate.agent_version_id}")
        from app.agents.capabilities.mirage import MirageConfig, OrganizationAccount
        from app.repositories import channel_bot_repo, organization_secret_repo
        from app.repositories import telephony as phone_repo
        from app.schemas.telephony import PhoneCallsConfig
        from app.services.mcp_connection import account_client_identity
        from app.services.portals import google_oauth
        from app.services.telephony.policy import endpoint_fingerprint

        secret_sources: dict[UUID, UUID] = {}
        mirage_accounts: dict[UUID, UUID] = {}
        for candidate in specs:
            for binding in candidate.capabilities:
                if not binding.enabled or binding.id != "mirage":
                    continue
                config = MirageConfig.model_validate(binding.config)
                for mount in config.mounts:
                    accounts = []
                    if isinstance(mount.account, OrganizationAccount):
                        account = await mcp_connection_repo.get_account(
                            self.db, mount.account.connection_id
                        )
                        if account is not None and account.organization_id == ctx.organization_id:
                            accounts = [account]
                        else:
                            unavailable.add(f"Terminal account · {mount.account.connection_id}")
                    elif mount.account is not None:
                        accounts = await mcp_connection_repo.list_accounts(
                            self.db, provider=google_oauth.PROVIDER, user_id=ctx.subject_id
                        )
                        accounts = [
                            a
                            for a in accounts
                            if a.account_source_organization_id == ctx.organization_id
                        ]
                        if not accounts:
                            unavailable.add(f"Terminal account · {mount.path}")
                    for account in accounts:
                        client = account_client_identity(account)
                        if client is None or client[0] != ctx.organization_id:
                            unavailable.add(f"Terminal account · {account.id}")
                            continue
                        current_client = await organization_secret_repo.authorization_generation(
                            self.db, client[1], organization_id=ctx.organization_id
                        )
                        if not account.is_enabled or current_client != client[2]:
                            unavailable.add(f"Terminal account · {account.id}")
                            continue
                        mirage_accounts[account.id] = account.authorization_generation
                        secret_sources[client[1]] = client[2]
                        resources.add(f"Terminal account · {account.id}")
                    for identifier in mount.secrets.values():
                        generation = await organization_secret_repo.authorization_generation(
                            self.db, identifier, organization_id=ctx.organization_id
                        )
                        resources.add(f"Terminal credential · {identifier}")
                        if generation is None:
                            unavailable.add(f"Terminal credential · {identifier}")
                        else:
                            secret_sources[identifier] = generation
        if len(secret_sources) > 100 or len(mirage_accounts) > 100:
            raise RoutineSourcesRequired()
        phone_sources: dict[UUID, str] = {}
        for candidate in specs:
            for binding in candidate.capabilities:
                if not binding.enabled or binding.id != "phone_calls":
                    continue
                config = PhoneCallsConfig.model_validate(binding.config)
                endpoint = await phone_repo.endpoint(
                    self.db, config.endpoint_id, organization_id=ctx.organization_id
                )
                bot = (
                    await channel_bot_repo.get_for_org(
                        self.db, endpoint.bot_id, organization_id=ctx.organization_id
                    )
                    if endpoint is not None
                    else None
                )
                resources.add(f"Telephone endpoint · {config.endpoint_id}")
                if (
                    endpoint is None
                    or not endpoint.enabled
                    or bot is None
                    or not bot.is_active
                    or bot.authorization_generation != endpoint.bot_generation
                ):
                    unavailable.add(f"Telephone endpoint · {config.endpoint_id}")
                else:
                    phone_sources[endpoint.id] = endpoint_fingerprint(endpoint, bot)
        external_sources: dict[UUID, str] = {}
        for ref in (ref for current in specs for ref in current.external_agents):
            remote = await external_repo.get(
                self.db, ref.external_agent_id, organization_id=ctx.organization_id
            )
            if remote is None:
                unavailable.add(f"Remote agent · {ref.external_agent_id}")
            else:
                external_sources[remote.id] = await external_fingerprint(self.db, remote)
                resources.add(f"Remote agent · {remote.name} · {remote.id}")
        if len(external_sources) > 100:
            raise RoutineSourcesRequired(message="A routine can review at most 100 remote agents")
        for ref in (ref for current in specs for ref in current.mcp_servers):
            if isinstance(ref, PlatformMcpServerRef):
                resources.add("AgenticOS platform MCP")
                if not trigger.runs_as_creator:
                    requires_creator_identity = True
                    unavailable.add(PlatformRoutineIdentityRequired.message)
                continue
            if isinstance(ref, OrgMcpServerRef):
                connection = await mcp_connection_repo.get_org_scoped_by_id(
                    self.db,
                    connection_id=ref.connection_id,
                    organization_id=ctx.organization_id,
                    fresh=True,
                )
                accounts = [] if connection is None else [connection]
                identities = {
                    account.id: McpSourceIdentity(
                        endpoint_hash=hashlib.sha256(account.url.encode()).hexdigest(),
                        authorization_generation=account.authorization_generation,
                        tool_prefix=tool_prefix(account.name),
                    )
                    for account in accounts
                }
                missing_name = str(ref.connection_id)
            elif isinstance(ref, PersonalMcpServerRef) and trigger.runs_as_creator:
                accounts = await mcp_connection_repo.list_user_scoped_by_catalog_key(
                    self.db, user_id=ctx.subject_id, catalog_key=ref.catalog_key, fresh=True
                )
                identities = reviewed_personal_sources(ref.catalog_key, accounts)
                missing_name = ref.catalog_key
            else:
                continue
            if not accounts:
                unavailable.add(missing_name)
            for account in accounts:
                if ref in spec.mcp_servers:
                    root_sources.add(account.id)
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
                    previous = sources.get(account.id)
                    if previous is not None:
                        allowed.update(previous.tool_ids)
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
                sources[account.id] = candidate
        input_source = None
        if trigger.connection_id is not None:
            connection = await mcp_connection_repo.get_by_id(
                self.db, trigger.connection_id, fresh=True
            )
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
        if len(sources) > 100:
            raise RoutineSourcesRequired(message="A routine can review at most 100 source accounts")
        return RoutineSourceSnapshot(
            policy=RoutineSourcePolicy(
                id=uuid4(),
                consented_by=ctx.subject_id,
                reviewed_at=datetime.now(UTC),
                version_id=version,
                scope_hash=source_scope(trigger),
                spec_hash=spec_fingerprint(spec),
                project_id=trigger.project_id,
                project_hash=project_hash,
                mcp_sources=sources,
                root_mcp_ids=tuple(sorted(root_sources)),
                external_sources=external_sources,
                phone_sources=phone_sources,
                secret_sources=secret_sources,
                mirage_accounts=mirage_accounts,
                input_connection_id=trigger.connection_id if input_source is not None else None,
                input_source=input_source,
            ),
            accounts=sorted(names),
            unavailable=sorted(unavailable),
            resources=sorted(resources),
            requires_creator_identity=requires_creator_identity,
        )

    async def initial(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineSourcePolicy:
        """Creating the responsibility freezes its configured sources, never new grants."""
        review = await self._review(ctx, trigger)
        self._require_available(review)
        return review.policy

    @staticmethod
    def _require_available(review: RoutineSourceSnapshot) -> None:
        if review.unavailable:
            refusal = (
                PlatformRoutineIdentityRequired
                if review.requires_creator_identity
                else RoutineSourcesRequired
            )
            raise refusal(details={"unavailable_sources": review.unavailable})

    async def snapshot(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineSourceSnapshot:
        """A single metadata snapshot for a console-owned preset confirmation."""
        self._human(ctx, trigger)
        return await self._review(ctx, trigger)

    async def options(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineSourceReview:
        review = await self.snapshot(ctx, trigger)
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
            resources=review.resources,
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

    async def require_current(
        self, ctx: AuthContext, trigger: AgentTrigger, *, expected_id: UUID | None
    ) -> RoutineSourcePolicy:
        """Check metadata before opening a provider, preserving the admitted review."""
        policy = read_policy(trigger.approved_sources)
        if (
            policy.id != expected_id
            or policy.consented_by != trigger.created_by_user_id
            or policy.scope_hash != source_scope(trigger)
        ):
            raise RoutineSourcesRequired()
        review = await self._review(ctx, trigger)
        self._require_available(review)
        excluded = {"id", "reviewed_at", "version_id"}
        if policy.model_dump(exclude=excluded) != review.policy.model_dump(exclude=excluded):
            raise RoutineSourcesRequired()
        return policy
