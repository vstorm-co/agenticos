"""Run-local workspace selection, injected by the runner rather than database-aware tools."""

from typing import Protocol, runtime_checkable
from uuid import UUID

from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._registry import CapabilityToolInfo
from app.core.exceptions import AppException

PROJECT_WORKSPACE_RESOURCE = "project_workspace_selector"
PROJECT_TOOL = CapabilityToolInfo(
    id="select_project_workspace",
    description="Use an accessible project's files and shell for the rest of this run.",
    side_effecting=False,
    read_only=True,
)


@runtime_checkable
class ProjectWorkspacePort(Protocol):
    @property
    def project_id(self) -> UUID | None: ...

    async def select(self, project_id: UUID | None) -> str: ...


def project_tools(port: ProjectWorkspacePort | None) -> FunctionToolset[object]:
    tools: FunctionToolset[object] = FunctionToolset()

    async def select_project_workspace(project_id: UUID | None = None) -> str:
        """Use an accessible project's files and shell for the rest of this run.

        Find the project's id with the platform's project listing first. All file,
        Apps and shell tools then use that workspace. Omit project_id to restore
        the original workspace. This never moves the conversation or copies its
        private files into a project. A new user turn starts in its original
        workspace; approval continuations retain this selection. Select before
        doing file work, never in the same parallel batch as file operations.

        Returns:
            The selected project's name and backend, or a refusal. Access is
            checked again on every file operation. Existing write and shell
            approval settings still apply; file-only projects cannot run commands.
        """
        if port is None:
            return "Project workspace selection is unavailable on this run."
        try:
            return await port.select(project_id)
        except AppException as error:
            return error.message

    tools.add_function(select_project_workspace, sequential=True)
    return tools
