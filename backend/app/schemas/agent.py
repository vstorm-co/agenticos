"""Schemas for the agent registry and the tool catalog."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field

from app.agents.capabilities import CapabilityToolInfo
from app.agents.spec import AgentSpec, SpecialistSpec
from app.core.secret_kinds import SecretRequirement
from app.schemas.base import BaseSchema


class AgentRead(BaseSchema):
    """An agent as the Builder lists it."""

    id: UUID
    slug: str
    name: str
    description: str | None = None
    status: str
    visibility: str
    owner_user_id: UUID | None = None
    current_version_id: UUID | None = None
    has_avatar: bool = Field(
        default=False,
        description=(
            "Whether GET /agents/{id}/avatar will answer with an image. The storage path "
            "itself is never sent: it is a server-side location, and a client that had it "
            "would be holding a second, unchecked way to name the file."
        ),
    )
    avatar_color: int | None = Field(
        default=None,
        description=(
            "Chosen default-avatar colour, slot 1-10; null is auto (derived from the id). "
            "Only shown when the agent has no picture. A display choice, not the spec."
        ),
    )
    shared_user_count: int = Field(
        default=0,
        description=(
            "How many members hold an explicit grant on this agent. Filled by the "
            "listing, which is the one place a card says 'shared with 3'; write "
            "endpoints answer with the default rather than paying a count nobody reads."
        ),
    )
    channels: list[str] = Field(
        default_factory=list,
        description=(
            "Surfaces with an active binding - 'slack', 'telegram', 'mattermost'. "
            "Filled by the listing, same bargain as shared_user_count."
        ),
    )
    budget_monthly_usd: float | None = Field(
        default=None,
        description=(
            "The published version's monthly cap - the one the runner actually "
            "enforces, read off the frozen spec rather than the draft, which may "
            "promise a different number than the agent runs under. Null for a "
            "draft agent and for a published one with no cap. Filled by the "
            "listing, same bargain as shared_user_count."
        ),
    )
    context_window_tokens: int | None = Field(
        default=None,
        description=(
            "How many tokens the model this agent publishes on accepts. What a chat "
            "draws its context gauge against - the share is resolved where the model is "
            "known, because the window belongs to the model answering next and that can "
            "be switched between turns. Read off the profile the frozen spec names, "
            "falling back to the pricing registry; null when neither can say, and a "
            "surface then draws no share rather than one against a guess. Filled by the "
            "listing, same bargain as shared_user_count."
        ),
    )
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AgentDetail(AgentRead):
    """An agent plus the spec currently being edited."""

    draft_spec: AgentSpec


class AgentList(BaseSchema):
    items: list[AgentRead]
    total: int


class AgentCreate(BaseSchema):
    """Create an agent from a spec. The handle is derived from the name."""

    spec: AgentSpec


class AgentDraftUpdate(BaseSchema):
    spec: AgentSpec


class AgentAvatarColorRequest(BaseSchema):
    """The chosen default-avatar colour for an agent, or null to reset to auto.

    A command body, not a partial `*Update`: its one field is always meant, and
    a null is the reset rather than "unspecified".
    """

    color: int | None = Field(
        default=None,
        ge=1,
        le=10,
        description="Default-avatar colour, slot 1-10; null resets to auto.",
    )


class AgentPublish(BaseSchema):
    note: str | None = Field(
        default=None,
        max_length=500,
        description="Why this version exists - a commit message for agents",
    )


class AgentRollback(BaseSchema):
    version_id: UUID


class AgentClone(BaseSchema):
    """Copy an agent's draft into a new one.

    The name is optional because the useful default - "<name> (copy)" - is the
    one nobody wants to type, and the handle is derived from whatever name wins.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)


class SpecialistPromote(BaseSchema):
    """Turn a specialist into a draft agent the caller owns.

    The specialist is sent whole rather than referenced, because the two surfaces
    that promote one hold it whole and neither can be looked up server-side: the
    Builder holds an inline specialist's `SpecialistSpec` in the draft being edited,
    possibly unsaved, and chat holds a dynamic one only in the delegation frame that
    announced it - nothing persists a specialist a model invented. So the conversion
    (`SpecialistSpec.to_agent_spec`) runs on what the client sends, which is exactly
    the same trust boundary `import` already crosses: a draft is not validated, and
    publish checks the promoter's own access to everything it names.
    """

    specialist: SpecialistSpec
    fallback_model_profile_id: UUID | None = Field(
        default=None,
        description=(
            "The parent agent's model profile, used when an inline specialist runs on "
            "'the same model as its parent' (a null `model_profile_id`): a standalone "
            "agent has no parent to fall back to, so the parent's is resolved now. A "
            "dynamic specialist always names its own model, so this is null for one."
        ),
    )


class AgentVersionRead(BaseSchema):
    id: UUID
    version: int
    note: str | None = None
    published_by_user_id: UUID | None = None
    published_by_email: str | None = Field(
        default=None,
        description=(
            "Who published it. A uuid answers 'who changed this' with another "
            "question; null means that account has since left the organization, "
            "which is itself the answer somebody is looking for."
        ),
    )
    created_at: datetime | None = None


class AgentVersionDetail(AgentVersionRead):
    """One published version, with the spec it froze.

    Separate from the list entry because the list is a timeline - fifty rows of
    it - and a spec is the whole configuration of an agent. Sending every spec
    to render a row of dates would be a page-load per publish anybody ever made.
    """

    spec: AgentSpec


class AgentVersionList(BaseSchema):
    items: list[AgentVersionRead]
    total: int


class AgentSpecImport(BaseSchema):
    """Import a spec written by hand or exported from another deployment."""

    yaml: str = Field(min_length=1)


class CapabilityToolContract(BaseSchema):
    """One tool as the *model* meets it, rather than as the catalog names it.

    `CapabilityToolInfo` carries the summary line, which is what a list needs.
    This is the rest: the whole docstring the model reads before deciding to
    call, and the schema of the arguments it has to fill in. An author rewording
    a tool for their agent is rewriting against this text, and reading only its
    first sentence is how a reword loses the half that mattered.

    Read off the built toolset, never restated - see
    :mod:`app.services.capability_contracts`.
    """

    tool_id: str
    description: str = Field(description="The whole docstring, as handed to the model")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema of the arguments the model fills in"
    )


class CapabilityCatalogEntry(BaseSchema):
    """One registered capability as the Builder's picker shows it."""

    id: str
    name: str
    category: str
    description: str
    side_effecting: bool = Field(
        description="The default answer for every tool below: gate it unless waived"
    )
    tools: list[CapabilityToolInfo] = Field(
        description=(
            "The tools this capability contributes, with the name and description code "
            "declares for each. Deployment-wide, so no agent's overrides are applied: a "
            "binding decides approval per tool id via tool_approval, and reworks the name "
            "and description the model sees via tool_overrides, both keyed by the id here."
        )
    )
    scopes: list[str]
    contracts: list[CapabilityToolContract] = Field(
        default_factory=list,
        description=(
            "What each tool above tells the model, in full. Empty for a capability "
            "that contributes no tools."
        ),
    )
    config_schema: dict[str, Any] | None = Field(
        default=None, description="JSON Schema the configuration form is generated from"
    )
    requires_secret: SecretRequirement | None = Field(
        default=None,
        description=(
            "The credential this capability cannot work without, declared as a kind. "
            "A binding picks which of the organization's secrets of that kind to use "
            "and stores its id in secret_id; the value itself never reaches the spec, "
            "the API or the model."
        ),
    )


class McpCatalogEntry(BaseSchema):
    """One connectable MCP server in the curated catalog."""

    key: str
    name: str
    description: str
    category: str
    auth: str = Field(description="none, token or oauth - the only thing that really varies")
    url: str | None = Field(
        default=None, description="Null when the client self-hosts and supplies the URL"
    )
    docs_url: str | None = None
    token_hint: str | None = Field(
        default=None, description="What to tell the person pasting a credential"
    )
    icon: str | None = Field(
        default=None,
        description="Brand mark to draw, by name. Null falls back to a monogram in the client.",
    )


class McpCatalog(BaseSchema):
    items: list[McpCatalogEntry]
    total: int


class CapabilityCatalog(BaseSchema):
    items: list[CapabilityCatalogEntry]
    total: int


class AgentRunRequest(BaseSchema):
    """Ask a published agent a question."""

    prompt: str = Field(min_length=1)
    conversation_id: UUID | None = Field(
        default=None, description="Continue an existing conversation"
    )
    environment_id: UUID | None = Field(
        default=None,
        description=(
            "Run the version this named environment pins instead of the "
            "default - how a dev environment is exercised before promotion"
        ),
    )


class ParkedCall(BaseSchema):
    """A tool call a run is waiting on a decision for."""

    id: UUID = Field(description="The approval to decide, which is what a client posts to.")
    tool_call_id: str | None = Field(
        default=None,
        description=(
            "The step in the transcript this parked, so a surface can mark it. Null "
            "for a run parked before the mapping was stored on the row."
        ),
    )
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)


class RunStep(BaseSchema):
    """One tool call an execution of a run made, and what came back from it."""

    tool_call_id: str = Field(
        description="The provider's id for the call, so a surface can match it to a step it drew."
    )
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: str | None = Field(
        default=None,
        description=(
            "What the tool returned, or the retry message when it failed. Null on the "
            "call the run is parked on - it has not run yet, and it is the one being "
            "decided."
        ),
    )


class SettledCall(BaseSchema):
    """What a call the run had already made finally returned."""

    tool_call_id: str = Field(
        description="The step a surface already drew, which is the one to update rather than add."
    )
    result: str


class AgentRunResult(BaseSchema):
    """What the agent answered, and what the run cost."""

    run_id: UUID
    output: str
    status: str
    cost_usd: Decimal
    cost_is_partial: bool = Field(
        default=False,
        description=(
            "Whether `cost_usd` is a floor - true when the run reached a model with no "
            "price entry, whose request the ledger books at zero. The chat draws the "
            "resumed turn's cost from here, so without it a continuation reports a "
            "figure that lies where the parked half did not."
        ),
    )
    input_tokens: int
    output_tokens: int
    steps: list[RunStep] = Field(
        default_factory=list,
        description=(
            "What *this* execution called, in order. A resumed run streams nothing - the "
            "continuation runs over HTTP - so without this a surface could show the answer "
            "and none of the work behind it: approving a call appeared to do nothing, and "
            "a second approval request arrived for a step that had never been drawn. Empty "
            "on a run that called nothing."
        ),
    )
    settled: list[SettledCall] = Field(
        default_factory=list,
        description=(
            "What the calls this execution *inherited* returned - on a resume, the very "
            "call somebody approved. It was made by the previous execution, so it is not "
            "in `steps`; it belongs to a step the caller already drew. Empty on a run "
            "that inherited nothing."
        ),
    )
    parked: list[ParkedCall] = Field(
        default_factory=list,
        description=(
            "What the run is *now* waiting on, which is empty unless it stopped again. "
            "A resume runs the agent, and the agent can reach a second gated call - so "
            "a client that only read `status` was told 'still awaiting approval' and "
            "handed nothing to approve, leaving the run unfinishable from the surface "
            "that started it. The continuation runs over HTTP rather than the socket a "
            "conversation streams, so this response is the only place the new calls can "
            "arrive."
        ),
    )
