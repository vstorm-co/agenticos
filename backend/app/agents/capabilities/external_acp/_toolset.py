"""The model chooses a task, never a program, arguments or account."""

from uuid import UUID

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import RequestUsage
from pydantic_ai.workspaces import WorkspaceError

from app.agents.capabilities._failures import steer
from app.agents.capabilities.budget import assert_ambient_budget, record_ambient_usage
from app.agents.capabilities.coding_agent._acp import AcpError, DevicePipe, private_state_scope
from app.agents.capabilities.coding_agent._task import MAIN_SESSION, SESSION_NAME
from app.agents.capabilities.coding_agent._toolset import run_local_task
from app.agents.capabilities.external_acp._catalog import inspect_session
from app.agents.deps import AgentDeps
from app.agents.pi_keys import NativeKeyProvider
from app.services.device_hub import (
    DeviceCallFailed,
    DeviceCallTimedOut,
    DeviceUnavailable,
    DeviceWorkspace,
)

from ._credentials import probe_credentials
from ._keys import catalog_json, selected_key

INSPECT_DESCRIPTION = (
    "Read model and reasoning choices from the registered ACP agent on this account."
)

RUN_DESCRIPTION = "Hand a task to the external ACP agent registered on this computer."


def build_acp_toolset(
    agent_id: str,
    timeout_seconds: int,
    *,
    auth_method: str | None = None,
    model_id: str | None = None,
    api_provider: NativeKeyProvider | None = None,
    secret_id: UUID | None = None,
    platform_tools: bool = False,
) -> FunctionToolset[AgentDeps]:
    async def run_acp_agent(
        ctx: RunContext[AgentDeps],
        task: str,
        session: str = MAIN_SESSION,
        fresh_session: bool = False,
        folder: str | None = None,
    ) -> str:
        """Hand a task to the external ACP agent registered on this computer.

        Use for whole tasks with a goal, constraints and a way to verify the result.
        The program uses its own login and tools with local account access.

        Args:
            task: The complete task; this agent sees it and its own session history.
            session: Up to 40 lower-case letters, digits, hyphens or underscores.
                The same name continues earlier work; a new name starts independent work.
            fresh_session: Start this named session over instead of resuming it.
            folder: A folder inside the chat's approved folder. Empty uses the chat's folder.

        Returns:
            JSON with outcome, answer, steps and files_changed, or an explicit refusal.
            Use answer to explain the result; a failure does not mean no work occurred.
        """
        if not SESSION_NAME.fullmatch(session):
            return steer(
                ctx,
                "Use a session name of up to 40 lower-case letters, digits, hyphens or underscores, starting with a letter or digit.",
            )
        if platform_tools:
            audience = ctx.deps.audience
            workspace = ctx.workspace.backend if ctx.workspace.attached else None
            if (
                audience is None
                or audience.room_key is not None
                or audience.shared_transcript
                or audience.user_id != ctx.deps.run_person
                or ctx.deps.run_person is None
                or ctx.deps.impersonated
                or not isinstance(workspace, DeviceWorkspace)
                or workspace.owner_id != ctx.deps.run_person
                or ctx.deps.user_id != str(ctx.deps.run_person)
            ):
                return steer(
                    ctx, "Platform tools require the initiating member's private approved computer"
                )
        key = await selected_key(ctx, api_provider, secret_id)
        return await run_local_task(
            ctx,
            task,
            session,
            fresh_session,
            "custom",
            folder,
            access="edit",
            timeout_seconds=timeout_seconds,
            custom_agent_id=agent_id,
            auth_method=auth_method,
            model=model_id,
            credential_probe=probe_credentials,
            pi_key=key,
            platform_tools=platform_tools,
        )

    async def inspect_acp_agent(ctx: RunContext[AgentDeps]) -> str:
        """Read model and reasoning choices from the registered ACP agent on this account.

        Opens a native-approved session without submitting an inference prompt.
        Use its exact IDs to configure External model ID. Availability in this
        catalog does not prove subscription entitlement or remaining quota.

        Returns:
            JSON with models_exposed, models, current_model, efforts and
            current_effort, or an explicit connection, login or protocol refusal.
        """
        workspace = ctx.workspace.backend if ctx.workspace.attached else None
        if not isinstance(workspace, DeviceWorkspace):
            return "Model discovery needs Work on set to This computer with an approved full-access folder."
        if not workspace.local_coding_allowed:
            return "Model discovery starts a native ACP program and requires an approved full-access folder. Choose full access explicitly first."
        await assert_ambient_budget()
        key = await selected_key(ctx, api_provider, secret_id)
        pipe = DevicePipe(
            workspace,
            "custom",
            custom_agent_id=agent_id,
            pi_key=key,
            pi_model=model_id,
            runtime_model=model_id,
            state_scope=private_state_scope(ctx.deps),
        )
        try:
            root = await workspace.working_dir()
            await pipe.open()
            if pipe.protocol == "pi_rpc":
                from ._pi import inspect_pi

                catalog = await inspect_pi(
                    pipe,
                    timeout_seconds=min(timeout_seconds, 60),
                    key_provider=key.pi_provider if key is not None else None,
                )
                return catalog_json(catalog, key)
            catalog = await inspect_session(
                pipe,
                root=root,
                auth_method=pipe.auth_method or auth_method,
                model_prefix=pipe.model_prefix,
                wait_for_updates=pipe.refresh_catalog,
                credential_probe=probe_credentials,
                timeout_seconds=min(timeout_seconds, 60),
            )
            catalog.configuration_policy = pipe.configuration_policy
            return catalog.model_dump_json()
        except AcpError as error:
            return f"ACP model discovery failed: {error.message} Check the program's own login and model access. For Antigravity, run agy acp --login. No alternate billing mode was selected."
        except (
            WorkspaceError,
            DeviceCallFailed,
            DeviceUnavailable,
            DeviceCallTimedOut,
            TimeoutError,
            OSError,
        ):
            return "ACP model discovery failed. Check the Desktop connection, registered command and login. For Antigravity, run agy acp --login in a terminal. No alternate billing mode was selected."
        finally:
            record_ambient_usage("external-acp:discovery", RequestUsage())

    toolset = FunctionToolset([run_acp_agent, inspect_acp_agent])
    if platform_tools:
        toolset.tools["run_acp_agent"].sequential = True
    return toolset
