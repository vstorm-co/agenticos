"""Attach project tools to the run-owned, live-authorized context port."""

from pydantic_ai.capabilities import Toolset

from app.agents.capabilities.projects._toolset import ProjectContextPort, project_tools
from app.agents.deps import AgentDeps


def build_projects(port: ProjectContextPort | None) -> Toolset[AgentDeps]:
    return Toolset(project_tools(port))
