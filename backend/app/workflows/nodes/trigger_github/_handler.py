"""`trigger.github`: a workflow something happening in a GitHub repository starts.

Publishing a version with this trigger gives it a webhook address and a signing
secret. With the organization's GitHub account connected for webhooks, the
publish registers the hook on the repository itself; otherwise the trigger's
panel shows what to paste into the repository's webhook settings. Each delivery
GitHub signs, for one of the events this node names and - when it names any -
one of its actions, starts one run as the member who published it.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.workflows.contracts.results import Completed, Failed, NodeResult
from app.workflows.nodes._triggers import GithubTriggerOutput, run_input_as

GithubEvent = Literal[
    "issues",
    "issue_comment",
    "pull_request",
    "pull_request_review",
    "push",
    "release",
    "workflow_run",
]

REPOSITORY = r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$"

GithubAction = Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,40}$")]


class GithubTriggerConfig(BaseModel):
    """Which repository, and which of its events, start the workflow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repository: str = Field(
        pattern=REPOSITORY, description="The repository, as owner/name", examples=["acme/api"]
    )
    events: tuple[GithubEvent, ...] = Field(
        default=("issues",),
        min_length=1,
        max_length=7,
        title="Starts on",
        description="The GitHub events that start it",
        json_schema_extra={
            "x-enum-labels": {
                "issues": "Issues",
                "issue_comment": "Issue and pull request comments",
                "pull_request": "Pull requests",
                "pull_request_review": "Pull request reviews",
                "push": "Pushes",
                "release": "Releases",
                "workflow_run": "Actions workflow runs",
            }
        },
    )
    actions: tuple[GithubAction, ...] = Field(
        default=(),
        max_length=20,
        title="Only these actions",
        description="Such as opened or closed; any action when empty. A push has none",
    )
    register_with_account: bool = Field(
        default=True,
        title="Set up the webhook for me",
        description="Register it on the repository through the organization's connected "
        "GitHub account, when one is connected with permission to manage webhooks",
    )

    @field_validator("events", "actions")
    @classmethod
    def _each_once(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(names)) != len(names):
            raise ValueError("Each is named once")
        return names

    def takes(self, *, event: str, action: str | None, repository: str) -> bool:
        """Whether a delivery of `event` and `action` on `repository` starts the workflow."""
        if repository.casefold() != self.repository.casefold() or event not in self.events:
            return False
        return not self.actions or action in self.actions


async def handle(config: BaseModel | None, node_input: BaseModel | None) -> NodeResult:
    """Hand on the delivery the run was started with."""
    delivery = run_input_as(GithubTriggerOutput)
    if isinstance(delivery, Failed):
        return delivery
    return Completed[GithubTriggerOutput](output=delivery)
