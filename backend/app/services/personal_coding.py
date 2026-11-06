"""Run a person's coding grant only in a disposable container owned by their task."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import anyio
from pydantic_ai.tools import RunContext
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.coding_agent._harness import Harness
from app.agents.capabilities.coding_agent._personal import PersonalCodingTask
from app.agents.capabilities.sandbox import SandboxConfig
from app.agents.capabilities.sandbox._identity import WorkspaceIdentity
from app.agents.deps import AgentDeps
from app.agents.spec import AgentSpec, CapabilityBindingSpec
from app.clients.redis import RedisClient
from app.core.audit import record_audit
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, OpenAICodexSecret, SecretKind, unseal_secret
from app.core.vault import VaultScope
from app.db.models.coding_account import CodingAccount
from app.db.session import get_db_context
from app.repositories import coding_account as account_repo
from app.repositories import conversation_share_repo, member_repo
from app.services.coding_account_lease import account_lease
from app.services.coding_accounts import account_owner
from app.services.personal_codex import PersonalCodexCredentials
from app.services.personal_coding_snapshot import populate, snapshot
from app.services.project_workspace_guard import project_for_workspace
from app.services.sandbox_workspace import SandboxWorkspaceService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersonalCodingSessionFactory:
    ctx: AuthContext
    spec: AgentSpec
    config: SandboxConfig
    agent_id: UUID
    redis: RedisClient | None = None
    project_id: UUID | None = None

    async def _active(
        self, account_id: UUID, generation: UUID, conversation_id: UUID | None = None
    ) -> bool:
        async with get_db_context() as db:
            return await self._active_in(db, account_id, generation, conversation_id)

    async def _active_in(
        self,
        db: AsyncSession,
        account_id: UUID,
        generation: UUID,
        conversation_id: UUID | None = None,
        *,
        lock: bool = False,
    ) -> bool:
        membership = await member_repo.get(
            db,
            organization_id=self.ctx.organization_id,
            user_id=account_owner(self.ctx),
            for_update=lock,
        )
        if membership is None:
            return False
        row = await account_repo.get(
            db,
            organization_id=self.ctx.organization_id,
            user_id=account_owner(self.ctx),
            account_id=account_id,
            locked=lock,
        )
        if row is None or not row.enabled or row.generation != generation:
            return False
        if self.project_id is not None:
            fresh = AuthContext(
                user_id=self.ctx.user_id,
                organization_id=self.ctx.organization_id,
                role=membership.role,
            )
            try:
                await project_for_workspace(db, fresh, self.project_id)
            except NotFoundError, AuthorizationError:
                return False
        if conversation_id is not None:
            shares = await conversation_share_repo.get_shares_for_conversation(
                db, conversation_id, organization_id=self.ctx.organization_id
            )
            if any(
                share.shared_with is not None and share.permission == "edit" for share in shares
            ):
                return False
        return True

    async def _account(self, harness: Harness) -> CodingAccount:
        async with get_db_context() as db:
            row = await account_repo.get(
                db,
                organization_id=self.ctx.organization_id,
                user_id=account_owner(self.ctx),
                harness=harness,
            )
            if row is None or not row.enabled:
                raise BadRequestError(
                    message="Connect and enable your own coding account in Settings → Profile first",
                    details={"harness": harness},
                )
            db.expunge(row)
            return row

    @asynccontextmanager
    async def session(
        self, ctx: RunContext[AgentDeps], *, harness: Harness, timeout_seconds: int
    ) -> AsyncGenerator[PersonalCodingTask]:
        owner = account_owner(self.ctx)
        if ctx.deps.user_id != str(owner) or ctx.deps.organization_id != self.ctx.organization_id:
            raise AuthorizationError(
                message="The coding task does not belong to this personal account"
            )
        if self.config.backend != "service" or ctx.deps.conversation_id is None:
            raise BadRequestError(
                message="Personal cloud coding requires a server sandbox and a conversation"
            )
        if (
            self.project_id is not None
            or self.config.session_scope in {"agent", "channel"}
            or (ctx.deps.audience is not None and ctx.deps.audience.room_key is not None)
        ):
            raise AuthorizationError(
                message="Personal coding accounts require a private unshared source workspace"
            )
        async with get_db_context() as db:
            shares = await conversation_share_repo.get_shares_for_conversation(
                db, ctx.deps.conversation_id, organization_id=self.ctx.organization_id
            )
        if any(share.shared_with is not None and share.permission == "edit" for share in shares):
            raise AuthorizationError(
                message="Personal coding accounts cannot use a conversation collaborators can edit"
            )
        account = await self._account(harness)
        lease_key = f"personal-coding:{self.ctx.organization_id}:{owner}:{account.id}"
        async with (
            account_lease(lease_key, timeout_seconds, redis=self.redis),
            self._isolated(ctx, account, harness) as task,
        ):
            yield task

    @asynccontextmanager
    async def _isolated(
        self, ctx: RunContext[AgentDeps], account: CodingAccount, harness: Harness
    ) -> AsyncGenerator[PersonalCodingTask]:
        owner = account_owner(self.ctx)
        if not await self._active(account.id, account.generation, ctx.deps.conversation_id):
            raise AuthorizationError(message="Permission to use this coding account was revoked")
        value = unseal_secret(
            account.sealed_secret,
            kind=SecretKind(account.secret_kind),
            scope=VaultScope.user(owner),
            key_version=account.key_version,
        )
        if not isinstance(value, (ApiKeySecret, OpenAICodexSecret)):
            raise TypeError("A personal coding account has an unsupported credential")
        if isinstance(value, OpenAICodexSecret) and harness != "codex":
            raise BadRequestError(message="A ChatGPT account can only run Codex")
        source = await snapshot(ctx.workspace)
        task_id = uuid4()
        bindings = [binding for binding in self.spec.capabilities if binding.id != "sandbox"]
        private_config = self.config.model_copy(update={"session_scope": "run"})
        bindings.append(
            CapabilityBindingSpec(id="sandbox", config=private_config.model_dump(mode="json"))
        )
        private_spec = self.spec.model_copy(update={"capabilities": bindings})
        async with get_db_context() as db:
            workspaces = SandboxWorkspaceService(db)
            opened = await workspaces.open(
                private_spec,
                ctx=self.ctx,
                identity=WorkspaceIdentity(
                    organization_id=self.ctx.organization_id,
                    user_id=str(owner),
                    agent_id=self.agent_id,
                    run_id=task_id,
                    conversation_id=ctx.deps.conversation_id,
                ),
                scope_override="run",
            )
            if opened is None:
                raise RuntimeError("A personal coding task did not obtain its isolated workspace")
            succeeded = False
            try:
                await record_audit(
                    db,
                    actor_user_id=owner,
                    organization_id=self.ctx.organization_id,
                    action="coding_account.task_started",
                    target_type="coding_account",
                    target_id=str(account.id),
                    details={
                        "run_id": str(ctx.deps.run_id),
                        "conversation_id": str(ctx.deps.conversation_id),
                        "task_id": str(task_id),
                        "harness": harness,
                        "base_revision": source.revision,
                        "execution": "isolated_task",
                        "connection_id": str(opened.connection_id),
                    },
                )
                await db.commit()
                await populate(opened.workspace, source)
                codex = PersonalCodexCredentials(
                    self.ctx.organization_id, owner, account.id, account.generation
                )
                task = PersonalCodingTask(
                    workspace=opened.workspace,
                    account_id=account.id,
                    label=account.label,
                    base_revision=source.revision,
                    result_archive=f"coding-results/{task_id}.zip",
                    redactions=(value.api_key,)
                    if isinstance(value, ApiKeySecret)
                    else (value.access_token, value.refresh_token),
                    api_key=value.api_key if isinstance(value, ApiKeySecret) else None,
                    sign_in=(lambda _organization: codex)
                    if isinstance(value, OpenAICodexSecret)
                    else None,
                )
                revoked = False
                async with anyio.create_task_group() as group:

                    async def watch() -> None:
                        nonlocal revoked
                        while True:
                            await anyio.sleep(2)
                            if not await self._active(
                                account.id, account.generation, ctx.deps.conversation_id
                            ):
                                revoked = True
                                group.cancel_scope.cancel()
                                return

                    group.start_soon(watch)
                    task_error: BaseException | None = None
                    try:
                        yield task
                    except BaseException as error:
                        task_error = error
                    finally:
                        group.cancel_scope.cancel()
                if task_error is not None and not revoked:
                    raise task_error
                if revoked or not await self._active(
                    account.id, account.generation, ctx.deps.conversation_id
                ):
                    raise AuthorizationError(
                        message="The personal coding account was revoked while the task ran"
                    )
                result = await snapshot(opened.workspace)
                forbidden = (
                    (value.api_key.get_secret_value(),)
                    if isinstance(value, ApiKeySecret)
                    else (
                        value.access_token.get_secret_value(),
                        value.refresh_token.get_secret_value(),
                    )
                )
                if isinstance(value, OpenAICodexSecret):
                    current = await codex.load()
                    forbidden += (current.access_token, current.refresh_token)
                archive = result.archive(forbidden)
                async with get_db_context() as publication_db:
                    conversation_id = ctx.deps.conversation_id
                    if not await self._active_in(
                        publication_db, account.id, account.generation, conversation_id, lock=True
                    ):
                        raise AuthorizationError(
                            message="The personal coding account was revoked before publication"
                        )
                    if (
                        conversation_id is not None
                        and not await conversation_share_repo.lock_private_publication(
                            publication_db, conversation_id, self.ctx.organization_id
                        )
                    ):
                        raise AuthorizationError(message="The coding conversation no longer exists")
                    if not await self._active(account.id, account.generation, conversation_id):
                        raise AuthorizationError(
                            message="The coding workspace is no longer private or its account was revoked"
                        )
                    await ctx.workspace.write_bytes(task.result_archive, archive)
                succeeded = True
            finally:
                with anyio.CancelScope(shield=True):
                    failure = await workspaces.close(opened)
                    if failure is not None:
                        if succeeded:
                            raise failure.error
                        logger.error(
                            "personal_coding_workspace_cleanup_failed",
                            extra={"task_id": str(task_id)},
                        )
