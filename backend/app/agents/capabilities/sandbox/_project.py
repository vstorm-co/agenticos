"""Run-local workspace selection, injected by the runner rather than database-aware tools."""

from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.workspaces import Workspace

from app.agents.capabilities._registry import CapabilityToolInfo
from app.core.exceptions import AppException

PROJECT_WORKSPACE_RESOURCE = "project_workspace_selector"
PROJECT_TOOL = CapabilityToolInfo(
    id="select_project_workspace",
    description="Select an accessible project's shared files without changing the command target.",
    side_effecting=False,
    read_only=True,
)


@runtime_checkable
class ProjectWorkspacePort(Protocol):
    @property
    def project_id(self) -> UUID | None: ...

    async def select(self, project_id: UUID | None) -> str: ...


@runtime_checkable
class ProjectExecutionState(Protocol):
    @property
    def project_context_observed(self) -> bool: ...

    @property
    def split_execution_namespace(self) -> bool: ...


@runtime_checkable
class ProjectWorkspaceSnapshot(Protocol):
    def snapshot_for_delegate(self) -> Workspace: ...


@runtime_checkable
class ExecutionWorkspacePort(Protocol):
    async def select_execution(self, target: Literal["agent", "project"]) -> str: ...


EXECUTION_TOOL = CapabilityToolInfo(
    id="select_execution_target",
    description="Choose whether shell commands run in the agent's workspace or the selected project's runtime.",
    side_effecting=False,
    read_only=True,
)


def project_tools(port: ProjectWorkspacePort | None) -> FunctionToolset[object]:
    tools: FunctionToolset[object] = FunctionToolset()

    async def select_project_workspace(project_id: UUID | None = None) -> str:
        """Select an accessible project's shared files without changing the command target.

        Find the ID with Projects search or the platform's project listing first.
        File tools use that project. Commands keep their selected executor; choose
        select_execution_target explicitly when commands need the project files.
        No files are copied, mounted or synchronized into the agent's own runtime.
        Omit project_id to clear project context and restore agent execution.
        This never moves the conversation. A new user turn starts fresh;
        approval continuations retain selection and recheck current access.
        Shared-workspace delegation pins context and execution until the run ends;
        changing targets then requires a new user turn.

        Args:
            project_id: An accessible project ID, or null to clear the context.

        Returns:
            Project reference guidance, generation and truthful executor status,
            or a refusal. File-only projects provide no command executor.
        """
        if port is None:
            return "Project workspace selection is unavailable on this run."
        try:
            return await port.select(project_id)
        except AppException as error:
            return error.message

    async def select_execution_target(target: Literal["agent", "project"]) -> str:
        """Choose whether shell commands run in the agent's workspace or the selected project's runtime.

        Use project only after choosing a service-backed project and when a
        command must operate directly on its shared files. Use agent for the
        agent's configured toolchain. Project file tools remain in their separate
        namespace; no files or dependencies are copied between command targets.
        Choosing a target opens no container and does not run a command. Existing
        shell approval settings still apply. Local computer access cannot be
        silently replaced by project execution in the same turn.

        Args:
            target: agent for its existing workspace, project for the selected
                project's own service runtime; a files-only project is refused.

        Returns:
            The selected command target or an actionable refusal.
        """
        if not isinstance(port, ExecutionWorkspacePort):
            return "Command target selection is unavailable on this run."
        try:
            return await port.select_execution(target)
        except AppException as error:
            return error.message

    tools.add_function(select_project_workspace, sequential=True)
    tools.add_function(select_execution_target, sequential=True)
    return tools
