"""Review a routine's source ceiling without probing providers or granting actions.

The ceiling is half of a routine's access review; the tool half is
`app.services.routine_access`. See `docs/design/routine-access.md`.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import all_capabilities
from app.agents.mcp import McpSourceIdentity, tool_prefix
from app.agents.spec import AgentSpec, OrgMcpServerRef, PersonalMcpServerRef, PlatformMcpServerRef
from app.core.audit import current_impersonator, record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.db.models.agent_trigger import AgentTrigger
from app.db.models.context import ContextFile
from app.db.models.external_agent import ExternalAgent
from app.db.models.knowledge_base import KBScope
from app.db.models.project import Project
from app.db.models.skill import Skill
from app.db.models.virtual_table import VirtualTable
from app.repositories import (
    agent_repo,
    context_repo,
    knowledge_base_repo,
    mcp_connection_repo,
    organization_repo,
    organization_secret_repo,
    project_repo,
    skill_repo,
    virtual_table_repo,
)
from app.repositories import external_agent as external_repo
from app.schemas.mcp_connection import McpToolRead
from app.schemas.routine_sources import (
    RoutineSourceAccount,
    RoutineSourceItem,
    RoutineSourcePolicy,
)
from app.schemas.routine_tool_keys import (
    RoutineAccessMode,
    RoutineDelegateSetting,
    RoutineToolSetting,
    TrustBlockedReason,
)
from app.services.access import (
    AGENT,
    COLLECTION,
    CONTEXT,
    SECRET,
    SKILL,
    TABLE,
    OwnedResource,
    ResourceType,
    accessible_ids,
)
from app.services.agent_registry import AgentRegistryService
from app.services.collection_access import readable_kb
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
        "show_starters",
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


def compatible_spec_fingerprints(spec: AgentSpec) -> frozenset[str]:
    """Recognize the three historical encodings of the chat-only starter switch.

    Every other source-bearing value remains in the hashed material. This does
    not admit a changed binding, account, approval policy or capability.
    """
    material = spec.model_dump(mode="json", exclude=set(_NON_SOURCE_FIELDS))
    if not spec.table_bindings:
        material.pop("table_bindings", None)
    return frozenset(
        _fingerprint(value)
        for value in (
            material,
            {**material, "show_starters": True},
            {**material, "show_starters": False},
        )
    )


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def materialized_behavior(
    skills: list[Skill], contexts: list[ContextFile], *, namespace: str = "root"
) -> dict[str, str]:
    result: dict[str, str] = {}
    for skill in skills:
        digest = _fingerprint(
            {
                "name": skill.name,
                "description": skill.description,
                "content": skill.content,
                "resources": sorted((r.name, r.description, r.content) for r in skill.resources),
            }
        )
        result[f"{namespace}:skill:{skill.id}:{digest}"] = digest
    for context in contexts:
        digest = _fingerprint(
            {
                "name": context.name,
                "description": context.description,
                "content": context.content,
                "mode": context.mode,
                "format": context.format,
            }
        )
        result[f"{namespace}:context:{context.id}:{digest}"] = digest
    return result


def _within_behavior(
    current: dict[str, str],
    approved: dict[str, str],
    compatible: Mapping[str, frozenset[str]] | None = None,
    aliases: Mapping[str, str] | None = None,
) -> bool:
    """Whether every piece of behavior now was reviewed, under its key or a former one.

    `aliases` names the key a binding had when its fingerprint still covered its
    approval settings, so a review saved then still recognises it.
    """
    return all(
        approved.get(key) == value
        or approved.get(key) in (compatible or {}).get(key, frozenset())
        or (key in (aliases or {}) and (aliases or {})[key] in approved)
        for key, value in current.items()
    )


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
        "The AgenticOS platform MCP server requires Run as me. Turn it on or remove "
        "the platform binding from this agent and its delegates."
    )
    code = "ROUTINE_PLATFORM_IDENTITY_REQUIRED"


class RoutineTrustRefused(RoutineSourcesRequired):
    message = "This routine trusts its agent, which is no longer allowed for it. Review its access."
    code = "ROUTINE_TRUST_NOT_ALLOWED"


PLATFORM_NEEDS_CREATOR = "AgenticOS platform MCP (needs Run as me)"
"""How the platform binding is named in a source list while the routine does not run as its creator.

A name, not a sentence: the console puts it inside its own sentence.
"""


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
    if policy.channel_sources:
        from app.repositories import agent_exposure_repo, channel_bot_repo
        from app.services.channel_actions import grant_fingerprint

        for identifier, expected in policy.channel_sources.items():
            exposure = await agent_exposure_repo.get(
                db, identifier, organization_id=organization_id
            )
            bot = (
                None
                if exposure is None
                else await channel_bot_repo.get_for_org(
                    db, exposure.channel_bot_id, organization_id=organization_id
                )
            )
            if (
                exposure is None
                or bot is None
                or not exposure.is_active
                or not bot.is_active
                or grant_fingerprint(exposure, bot) != expected
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


def _distinct(items: list[RoutineSourceItem]) -> list[RoutineSourceItem]:
    """Each source once, grouped by kind and sorted by name, as the review lists them."""
    unique = {(item.kind, item.id, item.detail): item for item in items}
    return sorted(
        unique.values(), key=lambda item: (item.kind, (item.name or "").lower(), item.id or "")
    )


@dataclass(frozen=True)
class RoutineSourceSnapshot:
    policy: RoutineSourcePolicy
    accounts: list[str]
    unavailable: list[str]
    resources: list[str]
    requires_creator_identity: bool = False
    optional_unavailable: frozenset[str] = frozenset()
    items: list[RoutineSourceItem] = field(default_factory=list)
    behavior_fingerprints: dict[str, str] = field(default_factory=dict)
    compatible_spec_hashes: frozenset[str] = frozenset()
    compatible_behavior: dict[str, frozenset[str]] = field(default_factory=dict)
    behavior_aliases: dict[str, str] = field(default_factory=dict)

    def token(self) -> str:
        content = self.policy.model_dump(mode="json", exclude={"id", "reviewed_at"})
        content["behavior_fingerprints"] = self.behavior_fingerprints
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

    async def _review(
        self,
        ctx: AuthContext,
        trigger: AgentTrigger,
        *,
        version_id: UUID | None = None,
    ) -> RoutineSourceSnapshot:
        pinned = version_id or trigger.pinned_version_id
        if pinned is not None:
            _, spec, version = await self.agents.get_pinned_spec(ctx, trigger.agent_id, pinned)
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
        platform = False
        optional_unavailable: set[str] = set()
        specs = [spec]
        spec_namespaces = ["root"]
        seen: set[UUID] = set()
        resources: set[str] = set()
        # The same sources, named: the ids above stay the review's identity.
        items: list[RoutineSourceItem] = []
        delegates: list[UUID] = []
        credentials: set[UUID] = set()
        for current in specs:
            resources.update(
                f"Knowledge · {identifier}" for identifier in current.served_collection_ids
            )
            resources.update(f"Context · {identifier}" for identifier in current.served_context_ids)
            resources.update(f"Skill · {identifier}" for identifier in current.served_skill_ids)
            resources.update(
                f"Capability · {binding.id}" for binding in current.capabilities if binding.enabled
            )
            resources.update(
                f"Table · {grant.table_id} · {'/'.join(operation.value for operation in grant.operations)}"
                for grant in current.table_bindings
            )
            for delegate in current.served_subagents:
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
                spec_namespaces.append(f"delegate:{delegate.agent_version_id}")
                resources.add(f"Delegate · {delegate.agent_id} · {delegate.agent_version_id}")
                delegates.append(delegate.agent_id)
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
                        items.append(
                            RoutineSourceItem(
                                kind="terminal_account",
                                id=str(account.id),
                                name=account.label or account.name,
                            )
                        )
                    for identifier in mount.secrets.values():
                        generation = await organization_secret_repo.authorization_generation(
                            self.db, identifier, organization_id=ctx.organization_id
                        )
                        resources.add(f"Terminal credential · {identifier}")
                        credentials.add(identifier)
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
                items.append(
                    RoutineSourceItem(
                        kind="phone",
                        id=str(config.endpoint_id),
                        name=None if bot is None else bot.name,
                    )
                )
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
        for ref in (ref for current in specs for ref in current.served_external_agents):
            remote = await external_repo.get(
                self.db, ref.external_agent_id, organization_id=ctx.organization_id
            )
            if remote is None:
                unavailable.add(f"Remote agent · {ref.external_agent_id}")
            else:
                external_sources[remote.id] = await external_fingerprint(self.db, remote)
                resources.add(f"Remote agent · {remote.name} · {remote.id}")
                items.append(
                    RoutineSourceItem(kind="remote_agent", id=str(remote.id), name=remote.name)
                )
        if len(external_sources) > 100:
            raise RoutineSourcesRequired(message="A routine can review at most 100 remote agents")
        required_unavailable = set(unavailable)
        for ref in (ref for current in specs for ref in current.mcp_servers):
            if isinstance(ref, PlatformMcpServerRef):
                resources.add("AgenticOS platform MCP")
                items.append(RoutineSourceItem(kind="platform"))
                platform = True
                if not trigger.runs_as_creator:
                    requires_creator_identity = True
                    unavailable.add(PLATFORM_NEEDS_CREATOR)
                    required_unavailable.add(PLATFORM_NEEDS_CREATOR)
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
                optional_unavailable.add(missing_name)
            for account in accounts:
                name = account.label or account.name
                names.add(f"{name} · {account.id}")
                items.append(RoutineSourceItem(kind="mcp_account", id=str(account.id), name=name))
                if not account.is_enabled or account.last_tools is None:
                    unavailable.add(name)
                    optional_unavailable.add(name)
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
                        account=account.account_email,
                        personal=isinstance(ref, PersonalMcpServerRef),
                    )
                except ValidationError:
                    unavailable.add(name)
                    optional_unavailable.add(name)
                    continue
                if ref in spec.mcp_servers:
                    root_sources.add(account.id)
                sources[account.id] = candidate
        from app.services.channel_actions import grant_fingerprint, granted_connections

        channel_sources: dict[UUID, str] = {}
        for exposure, bot in (
            await granted_connections(
                self.db, organization_id=ctx.organization_id, agent_id=trigger.agent_id
            )
        ).values():
            resources.add(f"Chat connection · {bot.name}")
            items.append(
                RoutineSourceItem(kind="chat_connection", id=str(exposure.id), name=bot.name)
            )
            channel_sources[exposure.id] = grant_fingerprint(exposure, bot)
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
                required_unavailable.add("event source")
            else:
                input_source = RoutineSourceAccount(
                    endpoint_hash=hashlib.sha256(connection.url.encode()).hexdigest(),
                    authorization_generation=connection.authorization_generation,
                    account=connection.account_email,
                )
                names.add(f"{connection.label or connection.name} · {connection.id}")
                items.append(
                    RoutineSourceItem(
                        kind="event_source",
                        id=str(connection.id),
                        name=connection.label or connection.name,
                    )
                )
        if len(sources) > 100:
            raise RoutineSourcesRequired(message="A routine can review at most 100 source accounts")
        behavior, compatible_behavior, aliases = await self._behavior(ctx, specs, spec_namespaces)
        return RoutineSourceSnapshot(
            behavior_fingerprints=behavior,
            compatible_behavior=compatible_behavior,
            behavior_aliases=aliases,
            compatible_spec_hashes=compatible_spec_fingerprints(spec),
            policy=RoutineSourcePolicy(
                id=uuid4(),
                consented_by=ctx.subject_id,
                reviewed_at=datetime.now(UTC),
                version_id=version,
                scope_hash=source_scope(trigger),
                spec_hash=spec_fingerprint(spec),
                behavior=behavior,
                platform=platform,
                project_id=trigger.project_id,
                project_hash=project_hash,
                mcp_sources=sources,
                root_mcp_ids=tuple(sorted(root_sources)),
                external_sources=external_sources,
                phone_sources=phone_sources,
                channel_sources=channel_sources,
                secret_sources=secret_sources,
                mirage_accounts=mirage_accounts,
                input_connection_id=trigger.connection_id if input_source is not None else None,
                input_source=input_source,
            ),
            accounts=sorted(names),
            unavailable=sorted(unavailable),
            resources=sorted(resources),
            requires_creator_identity=requires_creator_identity,
            optional_unavailable=frozenset(optional_unavailable - required_unavailable),
            items=_distinct(
                [
                    *await self._named(
                        ctx,
                        specs,
                        delegates=delegates,
                        credentials=sorted(credentials),
                    ),
                    *items,
                ]
            ),
        )

    async def _behavior(
        self, ctx: AuthContext, specs: list[AgentSpec], namespaces: list[str]
    ) -> tuple[dict[str, str], dict[str, frozenset[str]], dict[str, str]]:
        from app.agents.capabilities.context import context_config
        from app.agents.capabilities.subagents import SubagentsConfig
        from app.services.context import ContextService
        from app.services.skills import SkillService

        lists = {
            "capabilities",
            "mcp_servers",
            "skill_ids",
            "skill_bindings",
            "context_ids",
            "collection_ids",
            "table_bindings",
            "subagents",
            "external_agents",
        }
        metadata = {
            "spec_version",
            "name",
            "description",
            "starters",
            "model_profile_id",
            "model_settings",
        }
        result: dict[str, str] = {}
        compatible: dict[str, frozenset[str]] = {}
        aliases: dict[str, str] = {}
        for prefix, spec in zip(namespaces, specs, strict=True):
            # The rest of the spec, less what a review does not cover: instructions,
            # model settings and the like may change without a new review.
            material = spec.model_dump(
                mode="json", exclude=lists | metadata | {"show_starters"} | _NON_SOURCE_FIELDS
            )
            # How a review saved before that recorded it, instructions included.
            legacy = spec.model_dump(mode="json", exclude=lists | metadata | {"show_starters"})
            key = prefix + ":instructions"
            result[key] = _fingerprint(material)
            compatible[key] = frozenset(
                _fingerprint(value)
                for base in (material, legacy)
                for value in (
                    base,
                    {**base, "show_starters": True},
                    {**base, "show_starters": False},
                )
            )
            dumped = spec.model_dump(mode="json")
            # What a switched-off capability would reach is not behavior a run has.
            served = spec.model_copy(
                update={
                    "collection_ids": spec.served_collection_ids,
                    "subagents": spec.served_subagents,
                    "external_agents": spec.served_external_agents,
                }
            ).model_dump(mode="json", include={"collection_ids", "subagents", "external_agents"})
            dumped.update(served)
            for name in (
                "capabilities",
                "mcp_servers",
                "collection_ids",
                "table_bindings",
                "subagents",
                "external_agents",
            ):
                for value in dumped[name]:
                    if name == "capabilities" and value.get("enabled") is False:
                        continue
                    if name == "mcp_servers" and value.get("allowed_tools") == []:
                        continue
                    if name in ("capabilities", "mcp_servers"):
                        # Approval settings are enforced on every call and a routine
                        # cannot release one, so changing them grants nothing to review.
                        reviewed = {
                            field: item
                            for field, item in value.items()
                            if field not in ("approval", "tool_approval")
                        }
                        fingerprint = _fingerprint(reviewed)
                        former = _fingerprint(value)
                        aliases[f"{prefix}:{name}:{fingerprint}"] = f"{prefix}:{name}:{former}"
                    else:
                        fingerprint = _fingerprint(value)
                    result[f"{prefix}:{name}:{fingerprint}"] = fingerprint
            resource_specs = [(prefix, spec)]
            for binding in spec.capabilities:
                if binding.id == "subagents" and binding.enabled:
                    resource_specs.extend(
                        (
                            f"{prefix}:inline:{inline.name}",
                            inline.to_agent_spec(fallback_model_profile_id=spec.model_profile_id),
                        )
                        for inline in SubagentsConfig.model_validate(binding.config).inline
                    )
            for resource_namespace, resource_spec in resource_specs:
                skills = await SkillService(self.db).resolve_for_agent(
                    ctx, resource_spec.served_skill_ids, bindings=resource_spec.skill_bindings
                )
                contexts = await ContextService(self.db).resolve_for_agent(
                    ctx,
                    resource_spec.served_context_ids,
                    config=context_config(resource_spec.capabilities),
                )
                result.update(materialized_behavior(skills, contexts, namespace=resource_namespace))
        return result, compatible, aliases

    async def require_behavior(
        self, ctx: AuthContext, trigger: AgentTrigger, policy: RoutineSourcePolicy
    ) -> None:
        """Refuse a run whose skills or context changed since it was admitted.

        A trusting routine follows its agent, and a review saved before behavior
        was recorded has none to compare.
        """
        if policy.mode == "trust_agent" or policy.behavior is None:
            return
        try:
            current = await self._review(ctx, trigger, version_id=policy.version_id)
        except BadRequestError, NotFoundError:
            raise RoutineSourcesRequired() from None
        if not _within_behavior(
            current.behavior_fingerprints,
            policy.behavior,
            current.compatible_behavior,
            current.behavior_aliases,
        ):
            raise RoutineSourcesRequired()

    async def _named(
        self,
        ctx: AuthContext,
        specs: list[AgentSpec],
        *,
        delegates: list[UUID],
        credentials: list[UUID],
    ) -> list[RoutineSourceItem]:
        """The agent's own sources and its delegates', by name, each read in one query.

        A source that no longer exists, or that the reviewer may not view,
        keeps its id and has no name: running a shared agent does not reveal
        the name of a private skill, table or credential it uses, and never
        another organization's.
        """
        organization_id = ctx.organization_id
        skill_ids = sorted({identifier for spec in specs for identifier in spec.served_skill_ids})
        context_ids = sorted(
            {identifier for spec in specs for identifier in spec.served_context_ids}
        )
        collection_ids = sorted(
            {identifier for spec in specs for identifier in spec.served_collection_ids}
        )
        table_ids = sorted({grant.table_id for spec in specs for grant in spec.table_bindings})
        skills = await self._viewable(
            ctx,
            await skill_repo.get_many(self.db, skill_ids, organization_id=organization_id),
            SKILL,
        )
        contexts = await self._viewable(
            ctx,
            await context_repo.get_many(self.db, context_ids, organization_id=organization_id),
            CONTEXT,
        )
        found_collections = await knowledge_base_repo.get_by_ids(self.db, collection_ids)
        special_scopes = {KBScope.APP.value, KBScope.PERSONAL.value}
        collections = await self._viewable(
            ctx,
            {key: kb for key, kb in found_collections.items() if kb.scope not in special_scopes},
            COLLECTION,
        )
        # App/personal visibility is independent of organization grants and does no I/O.
        for key, kb in found_collections.items():
            if kb.scope in special_scopes and await readable_kb(self.db, ctx, kb):
                collections[key] = kb
        agents = await self._viewable(
            ctx,
            await agent_repo.get_many(self.db, delegates, organization_id=organization_id),
            AGENT,
        )
        secrets = await self._viewable(
            ctx,
            await organization_secret_repo.get_many(
                self.db, credentials, organization_id=organization_id
            ),
            SECRET,
        )
        found_tables: dict[UUID, VirtualTable] = {}
        for table_id in table_ids:
            table = await virtual_table_repo.get_table(
                self.db, table_id, organization_id=organization_id
            )
            if table is not None:
                found_tables[table_id] = table
        tables = await self._viewable(ctx, found_tables, TABLE)
        # A capability this deployment no longer ships keeps its id and no name.
        labels = {definition.id: definition.name for definition in all_capabilities()}
        named: list[RoutineSourceItem] = []
        for spec in specs:
            named.extend(
                RoutineSourceItem(kind="capability", id=binding.id, name=labels.get(binding.id))
                for binding in spec.capabilities
                if binding.enabled
            )
            for grant in spec.table_bindings:
                table = tables.get(grant.table_id)
                named.append(
                    RoutineSourceItem(
                        kind="table",
                        id=str(grant.table_id),
                        name=None if table is None else table.name,
                        detail="/".join(operation.value for operation in grant.operations),
                    )
                )
        for kind, identifiers, found in (
            ("skill", skill_ids, skills),
            ("context", context_ids, contexts),
            ("knowledge", collection_ids, collections),
            ("delegate", delegates, agents),
            ("terminal_credential", credentials, secrets),
        ):
            for identifier in identifiers:
                row = found.get(identifier)
                named.append(
                    RoutineSourceItem(
                        kind=kind,
                        id=str(identifier),
                        name=None if row is None else row.name,
                    )
                )
        return named

    async def _viewable[Row: OwnedResource](
        self, ctx: AuthContext, rows: Mapping[UUID, Row], resource_type: ResourceType
    ) -> dict[UUID, Row]:
        """The rows `ctx` may view, as the resource's own page decides it."""
        allowed = await accessible_ids(
            self.db, ctx, rows.values(), resource_type.view, resource_type=resource_type
        )
        return {identifier: row for identifier, row in rows.items() if row.id in allowed}

    async def initial(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineSourceSnapshot:
        """Capture available sources as a new routine's ceiling, never granting new access."""
        review = await self._review(ctx, trigger)
        require_available(review)
        return review

    async def snapshot(self, ctx: AuthContext, trigger: AgentTrigger) -> RoutineSourceSnapshot:
        """A single metadata snapshot for a console-owned review or preset confirmation."""
        self._human(ctx, trigger)
        return await self._review(ctx, trigger)

    async def require_current(
        self, ctx: AuthContext, trigger: AgentTrigger, *, expected_id: UUID | None
    ) -> RoutineSourcePolicy:
        """Check metadata before opening a provider, preserving the admitted review.

        A trusting routine whose organization sources grew moves its ceiling here,
        once, and tells its creator; `current` only reports it.
        """
        admission = await self.current(ctx, trigger, expected_id=expected_id)
        if admission.refreshed:
            trigger.approved_sources = admission.policy.model_dump(mode="json")
            await self.db.flush()
        if admission.expanded:
            await record_audit(
                self.db,
                actor_user_id=trigger.created_by_user_id,
                organization_id=trigger.organization_id,
                action="routine.access_expanded",
                target_type="agent",
                target_id=str(trigger.agent_id),
                details={"trigger_id": str(trigger.id), "sources": admission.expanded},
            )
            from app.services.notifications import NotificationService

            await NotificationService(self.db).routine_access_expanded(
                trigger, sources=admission.expanded
            )
        return admission.policy

    async def current(
        self, ctx: AuthContext, trigger: AgentTrigger, *, expected_id: UUID | None
    ) -> Admission:
        """The admitted review as a fire would use it.

        Writes nothing, so a read can ask whether the next fire would be admitted.
        Within its ceiling the review comes back refreshed: an account reconnected
        as itself, a source removed. A trusting review comes back with the
        organization sources it grew into and without personal ones nobody reviewed.

        Raises:
            RoutineSourcesRequired: The review is missing, stale or exceeded.
            RoutineTrustRefused: The routine trusts its agent where that is no longer allowed.
        """
        policy = read_policy(trigger.approved_sources)
        if (
            policy.id != expected_id
            or policy.consented_by != trigger.created_by_user_id
            or policy.scope_hash != source_scope(trigger)
            or (policy.intent_hash is not None and policy.intent_hash != routine_intent(trigger))
        ):
            raise RoutineSourcesRequired()
        if policy.mode == "trust_agent":
            blocked = await trust_blocked(self.db, ctx, trigger)
            if blocked is not None:
                raise RoutineTrustRefused(details={"reason": blocked})
        review = await self._review(ctx, trigger)
        require_available(review)
        ceiling = policy.approved_ceiling or ceiling_of(policy)
        expanded: list[str] = []
        if policy.mode == "trust_agent":
            current = _trusted(review.policy, ceiling)
            if not _within_ceiling(current, ceiling, review):
                expanded = _grown(current, ceiling, review)
        else:
            current = review.policy
            if not _within_ceiling(current, ceiling, review):
                raise RoutineSourcesRequired()
        # Refresh only at admission. A parked run retains its own immutable
        # snapshot, so reconnecting or rotating an account cannot retarget it.
        refreshed = current.model_copy(
            update={
                "id": policy.id,
                "consented_by": policy.consented_by,
                "reviewed_at": policy.reviewed_at,
                "mode": policy.mode,
                "tools": policy.tools,
                "delegates": policy.delegates,
                "intent_hash": policy.intent_hash,
                "grandfathered": policy.grandfathered,
                "approved_ceiling": ceiling_of(current) if expanded else ceiling,
            }
        )
        excluded = {"reviewed_at", "version_id"}
        if policy.model_dump(exclude=excluded) == refreshed.model_dump(exclude=excluded):
            return Admission(policy=policy)
        return Admission(policy=refreshed, refreshed=True, expanded=expanded)


@dataclass(frozen=True)
class Admission:
    """What `RoutineSourceService.current` admits a fire with."""

    policy: RoutineSourcePolicy
    refreshed: bool = False
    expanded: list[str] = field(default_factory=list)
    """Organization sources a trusting routine grew into; its ceiling moves to include them."""


def require_available(review: RoutineSourceSnapshot) -> None:
    """Refuse when a source every run needs is unavailable; an optional one is left out."""
    blocked = set(review.unavailable) - review.optional_unavailable
    if blocked:
        refusal = (
            PlatformRoutineIdentityRequired
            if review.requires_creator_identity
            else RoutineSourcesRequired
        )
        raise refusal(details={"unavailable_sources": sorted(blocked)})


def ceiling_of(policy: RoutineSourcePolicy) -> RoutineSourcePolicy:
    """The sources half of a review, as its ceiling stores it."""
    return policy.model_copy(
        update={
            "approved_ceiling": None,
            "tools": (),
            "delegates": "ask",
            "intent_hash": None,
            "grandfathered": False,
        }
    )


def stored_review(
    review: RoutineSourceSnapshot,
    *,
    mode: RoutineAccessMode,
    tools: tuple[RoutineToolSetting, ...],
    delegates: RoutineDelegateSetting,
    intent_hash: str,
) -> RoutineSourcePolicy:
    """A freshly reviewed policy: the snapshot is both its ceiling and its current state."""
    policy = review.policy.model_copy(
        update={
            "mode": mode,
            "tools": tools,
            "delegates": delegates,
            "intent_hash": intent_hash,
            "grandfathered": False,
        }
    )
    return policy.model_copy(update={"approved_ceiling": ceiling_of(policy)})


def _same_account(current: RoutineSourceAccount, approved: RoutineSourceAccount) -> bool:
    """The reviewed account at the reviewed endpoint, possibly reconnected as itself.

    A reconnect issues a new authorization generation and may sign in as anyone;
    only a provider account named both times, and the same, keeps the review.
    """
    return (
        current.endpoint_hash == approved.endpoint_hash
        and current.tool_prefix == approved.tool_prefix
        and (
            current.authorization_generation == approved.authorization_generation
            or (approved.account is not None and current.account == approved.account)
        )
    )


def _within_ceiling(
    current: RoutineSourcePolicy, approved: RoutineSourcePolicy, review: RoutineSourceSnapshot
) -> bool:
    if approved.behavior is None:
        # A review saved before behavior was recorded: its spec is its ceiling.
        if approved.spec_hash not in review.compatible_spec_hashes | {current.spec_hash}:
            return False
    elif current.behavior is None or not _within_behavior(
        current.behavior, approved.behavior, review.compatible_behavior, review.behavior_aliases
    ):
        return False
    for now, before in (
        (current.mirage_accounts, approved.mirage_accounts),
        (current.secret_sources, approved.secret_sources),
        (current.channel_sources, approved.channel_sources),
        (current.phone_sources, approved.phone_sources),
        (current.external_sources, approved.external_sources),
    ):
        if any(before.get(key) != value for key, value in now.items()):
            return False
    for key, source in current.mcp_sources.items():
        previous = approved.mcp_sources.get(key)
        if (
            previous is None
            or not _same_account(source, previous)
            or not set(source.tool_ids).issubset(previous.tool_ids)
        ):
            return False
    if current.input_connection_id != approved.input_connection_id or (
        current.input_source is not None
        and (
            approved.input_source is None
            or not _same_account(current.input_source, approved.input_source)
        )
    ):
        return False
    return (
        current.project_id == approved.project_id
        and current.project_hash == approved.project_hash
        and set(current.root_mcp_ids).issubset(approved.root_mcp_ids)
    )


def _trusted(current: RoutineSourcePolicy, approved: RoutineSourcePolicy) -> RoutineSourcePolicy:
    """The agent's current sources, less the creator's own that nobody reviewed.

    A personal MCP account or tool outside the ceiling is left out of the run; a
    terminal account or the platform acting as the creator cannot be, so either
    one newly reached stops the routine for review.

    Raises:
        RoutineSourcesRequired: A personal source that cannot be left out grew.
    """
    if any(
        approved.mirage_accounts.get(key) != value for key, value in current.mirage_accounts.items()
    ) or (current.platform and not approved.platform):
        raise RoutineSourcesRequired()
    kept: dict[UUID, RoutineSourceAccount] = {}
    for key, source in current.mcp_sources.items():
        if not source.personal:
            kept[key] = source
            continue
        previous = approved.mcp_sources.get(key)
        if previous is None or not _same_account(source, previous):
            continue
        tools = tuple(tool for tool in source.tool_ids if tool in previous.tool_ids)
        kept[key] = source.model_copy(update={"tool_ids": tools})
    return current.model_copy(
        update={
            "mcp_sources": kept,
            "root_mcp_ids": tuple(key for key in current.root_mcp_ids if key in kept),
        }
    )


def _grown(
    current: RoutineSourcePolicy, approved: RoutineSourcePolicy, review: RoutineSourceSnapshot
) -> list[str]:
    """What a trusting routine reaches beyond its ceiling, by the names the review shows."""
    names = {str(item.id): item.name or item.id for item in review.items if item.id is not None}
    grown: set[str] = set()
    for key, source in current.mcp_sources.items():
        previous = approved.mcp_sources.get(key)
        if previous is None or not set(source.tool_ids).issubset(previous.tool_ids):
            grown.add(names.get(str(key)) or str(key))
    for now, before in (
        (current.secret_sources, approved.secret_sources),
        (current.channel_sources, approved.channel_sources),
        (current.phone_sources, approved.phone_sources),
        (current.external_sources, approved.external_sources),
    ):
        grown.update(
            names.get(str(key)) or str(key)
            for key, value in now.items()
            if before.get(key) != value
        )
    if not grown:
        # Capabilities, skills, context, knowledge or delegates: the agent itself changed.
        grown.add("agent configuration")
    return sorted(grown)


def routine_intent(trigger: AgentTrigger) -> str:
    """What the routine does: a title or cadence edit changes nothing reviewed; the work does."""
    content = {
        name: getattr(trigger, name)
        for name in (
            "agent_id",
            "prompt",
            "environment_id",
            "pinned_version_id",
            "runs_as_creator",
            "event_source",
            "event_config",
            "answer_to",
            "delivery_conversation_id",
            "teams_conversation_id",
            "local_target",
        )
    }
    if trigger.result_mode == "inbox":
        content["result_mode"] = "inbox"
    if trigger.project_id is not None:
        content["project_id"] = trigger.project_id
    return hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()


def activation_intent(trigger: AgentTrigger) -> str:
    """A waiting activation cannot borrow access granted after it was queued.

    The review's decisions, not its refreshed identities: an admission that only
    found an account reconnected as itself grants nothing, so it must not make
    an activation waiting for its device obsolete.
    """
    stored = trigger.approved_sources
    try:
        policy = RoutineSourcePolicy.model_validate(stored)
    except ValidationError:
        decided: object = stored
    else:
        decided = policy.model_dump(
            mode="json",
            include={"id", "mode", "tools", "delegates", "intent_hash", "grandfathered"},
        )
    return hashlib.sha256(
        json.dumps([routine_intent(trigger), decided], sort_keys=True, default=str).encode()
    ).hexdigest()


async def trust_blocked(
    db: AsyncSession, ctx: AuthContext, trigger: AgentTrigger
) -> TrustBlockedReason | None:
    """Why this routine may not trust its agent, as `ctx` (its creator) would run it."""
    if trigger.trigger_type != "schedule":
        return "event"
    if not ctx.has(Perm.APPROVALS_DECIDE):
        return "permission"
    organization = await organization_repo.get_by_id(db, ctx.organization_id)
    if organization is None or not organization.routines_may_trust_agent:
        return "organization"
    return None
