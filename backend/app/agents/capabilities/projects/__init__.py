"""Project discovery, scoped context and files without granting code execution."""

from pydantic_ai.capabilities import Toolset

from app.agents.capabilities._registry import CapabilityBuildContext, CapabilityToolInfo, register
from app.agents.capabilities.projects._capability import build_projects
from app.agents.capabilities.projects._toolset import PROJECT_CONTEXT_RESOURCE, ProjectContextPort
from app.agents.deps import AgentDeps

PROJECTS_CAPABILITY_ID = "projects"


@register(
    id=PROJECTS_CAPABILITY_ID,
    name="Projects",
    category="knowledge",
    description="Find a project, use its shared files and guidance, and keep command execution separate.",
    scopes=("projects:read", "projects:write"),
    tools=(
        CapabilityToolInfo(
            id="search_projects",
            description="Find accessible projects by name or description before choosing one.",
            side_effecting=False,
            read_only=True,
        ),
        CapabilityToolInfo(
            id="select_project_context",
            description="Select shared project files and scoped guidance for this run without changing the executor.",
            side_effecting=False,
            read_only=True,
        ),
        CapabilityToolInfo(
            id="list_project_files",
            description="List one directory of the selected project's authoritative shared files.",
            side_effecting=False,
            read_only=True,
        ),
        CapabilityToolInfo(
            id="read_project_file",
            description="Read a bounded UTF-8 text file from the selected project.",
            side_effecting=False,
            read_only=True,
        ),
        CapabilityToolInfo(
            id="write_project_file",
            description="Save agreed UTF-8 text in the selected project's shared files.",
            side_effecting=True,
            read_only=False,
        ),
        CapabilityToolInfo(
            id="transfer_project_file",
            description="Transfer one file as bytes between the selected project and the agent workspace.",
            side_effecting=True,
            read_only=False,
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> Toolset[AgentDeps]:
    port = ctx.resources.get(PROJECT_CONTEXT_RESOURCE)
    return build_projects(port if isinstance(port, ProjectContextPort) else None)
