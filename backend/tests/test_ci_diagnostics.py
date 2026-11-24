"""Ephemeral test deployments must not register or report to the live collector."""

from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, Field, JsonValue

GITHUB = Path(__file__).resolve().parents[2] / ".github"


class EnvironmentScope(BaseModel):
    env: dict[str, JsonValue] = Field(default_factory=dict)


class Job(EnvironmentScope):
    steps: list[EnvironmentScope] = Field(default_factory=list)


class Workflow(EnvironmentScope):
    jobs: dict[str, Job]


@pytest.mark.parametrize(
    ("directory", "filename"),
    [
        ("workflows", "ci.yml"),
        ("workflows-disabled", "load.yml"),
        ("workflows-disabled", "dependency-freshness.yml"),
    ],
)
def test_test_workflows_disable_live_diagnostics_at_every_environment_scope(
    directory: str, filename: str
) -> None:
    workflow = Workflow.model_validate(yaml.safe_load((GITHUB / directory / filename).read_text()))
    assert workflow.env.get("DIAGNOSTICS_ENABLED") == "false"
    for name, job in workflow.jobs.items():
        enabled = job.env.get("DIAGNOSTICS_ENABLED", workflow.env["DIAGNOSTICS_ENABLED"])
        assert enabled == "false", f"{filename}: {name} enables live diagnostics"
        for step in job.steps:
            assert step.env.get("DIAGNOSTICS_ENABLED", enabled) == "false", (
                f"{filename}: {name} has a step that enables live diagnostics"
            )
