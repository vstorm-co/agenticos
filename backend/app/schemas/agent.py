"""Schemas for the agent registry and the tool catalog."""

import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.agents.capabilities import CapabilityToolInfo
from app.agents.spec import AgentSpec, DelegationMode, SpecialistSpec
from app.core.secret_kinds import SecretRequirement
from app.db.models.resource_grant import Visibility
from app.schemas.base import BaseSchema

# The longest a single category/tag may be, matching the `String(32)` array
# column that stores it. Measured on the *folded* value, since `casefold()` can
# expand text.
LABEL_MAX_LENGTH = 32
# How many of each facet an agent may carry - a discovery aid, not a taxonomy.
MAX_CATEGORIES = 10
MAX_TAGS = 20


def _fold_labels(values: list[str]) -> list[str]:
    """Canonicalize discovery labels: trim, fold case, drop empties, dedupe.

    The pure value-shaping core both entry points share. In order: collapse
    internal whitespace runs to one space and trim, NFC-normalize, fold case with
    `str.casefold()`, then NFC-normalize *again* so visually identical spellings
    (composed vs. decomposed, the full Unicode case map) become one canonical
    form the plain GIN index can match, drop anything empty after trimming, and
    de-duplicate preserving first-seen order. Idempotent: re-folding a folded
    list changes nothing.

    `casefold()` rather than `lower()` because `lower()` leaves `"ß"`/`"ss"` and
    NFC/NFD variants distinct, splitting one tag into several. The second
    normalization matters because `casefold()` can itself produce a decomposed
    sequence even from NFC input - Greek `"ΐ"` folds to a byte-distinct but
    canonically equivalent spelling depending on which precomposed or combining
    form of the letter it started from - so skipping it leaves two case-fold
    outputs that array-overlap compares as different strings.
    """
    seen: dict[str, None] = {}
    for value in values:
        collapsed = " ".join(value.split())
        if not collapsed:
            continue
        folded = unicodedata.normalize("NFC", unicodedata.normalize("NFC", collapsed).casefold())
        if folded not in seen:
            seen[folded] = None
    return list(seen)


def normalize_labels_strict(values: list[str]) -> list[str]:
    """Fold labels for the write path, raising on an item too long to store.

    Called inside a Pydantic `field_validator`, so a `ValueError` surfaces as a
    clean 422 rather than reaching the `String(32)` column as a database error.
    The length check is on the final folded value that will actually be stored,
    not the trimmed input, because `casefold()` can expand text (`"ß"` -> `"ss"`):
    a 32-char input can fold past the column width.
    """
    folded = _fold_labels(values)
    for label in folded:
        if len(label) > LABEL_MAX_LENGTH:
            raise ValueError(
                f"A category or tag may be at most {LABEL_MAX_LENGTH} characters after "
                f"normalization; {label!r} is {len(label)}."
            )
    return folded


def normalize_labels_query(values: list[str], *, max_items: int) -> list[str] | None:
    """Fold labels for the filter path: tolerant, bounded, never raising.

    A bad or oversized discovery query param should quietly narrow the result on
    that item, not 400 the page. So an over-length item is **dropped** (measured
    on the same folded value the write path checks) rather than raised on, and
    never truncated - truncating could turn an invalid label into a
    valid-but-unintended match. The folded, de-duplicated list is then capped to
    `max_items`, the same bound the write path enforces, so a runaway filter is
    trimmed rather than executed. The cap is a parameter because the one helper
    cannot otherwise know it is folding categories (10) or tags (20).

    Returns `None`, not `[]`, when the caller supplied at least one non-blank
    value and every one of them was dropped for being too long: that facet is
    unsatisfiable (no stored label can be over the column width), which the
    caller must treat as "match nothing" rather than "no predicate" - the two
    read the same as an empty list, but only a blank/absent facet means the
    latter.
    """
    folded = _fold_labels(values)
    kept = [label for label in folded if len(label) <= LABEL_MAX_LENGTH]
    if folded and not kept:
        return None
    return kept[:max_items]


class PublishedModel(BaseSchema):
    """The model an agent's published version runs on.

    Enough for the chat's model picker to open showing what the conversation is
    on and to offer a way back to it after an override: the profile's id (what an
    override is set to), its provider, the model id, and the label a person reads.
    """

    profile_id: UUID
    provider: str
    model: str
    label: str


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
    categories: list[str] = Field(
        description=(
            "Editable, org-local discovery categories, normalized (trimmed, case-folded, "
            "de-duplicated) and stored on the row - not part of the spec, so retagging "
            "needs no publish. Required, not defaulted: both array columns are NOT NULL, "
            "so a missing value means a hand-built path forgot them rather than 'none'."
        ),
    )
    tags: list[str] = Field(
        description=(
            "Editable, org-local discovery tags, normalized the same way as categories. "
            "Required for the same reason - a false empty list would hide a regression."
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
    can_run: bool = Field(
        default=False,
        description=(
            "Whether THIS caller may run the agent - the floor for creating a trigger, "
            "schedule or event on it. Resolved per caller from their role scope and any "
            "explicit run grant, so a Viewer granted run on one agent reads true here "
            "where the role-level check would say false. Hides create controls; it is "
            "not a security boundary, since every create endpoint re-checks server-side."
        ),
    )
    published_model: PublishedModel | None = Field(
        default=None,
        description=(
            "The model the published version runs on, so the chat's model picker can "
            "open showing what the conversation is on and offer a way back to it after "
            "an override. Read off the frozen spec's profile, not the draft's, which may "
            "name a different model than the agent runs; null for a draft agent and when "
            "that profile has been deleted. Filled by the listing, same bargain as "
            "shared_user_count."
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
    visibility: Visibility = Field(
        default=Visibility.ORG,
        description=(
            "Who can find this agent. `org` - the default - is everyone in the "
            "organization; `private` is the owner and whoever they grant it to. "
            "A draft cannot run either way, so this decides who sees it, not "
            "what it does."
        ),
    )


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


class AgentMetadataRequest(BaseSchema):
    """Editable discovery metadata for an agent - its categories and tags.

    A command body, not a partial `*Update`: both fields are always meant, and an
    empty list clears that facet. The validator folds each list (trim, case-fold,
    drop empties, dedupe) and raises on an item longer than the stored width,
    which surfaces as a 422; `max_length` caps how many of each facet may be sent.
    """

    categories: list[str] = Field(default_factory=list, max_length=MAX_CATEGORIES)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)

    @field_validator("categories", "tags", mode="after")
    @classmethod
    def _normalize(cls, v: list[str]) -> list[str]:
        return normalize_labels_strict(v)


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


class DelegationTreeNode(BaseSchema):
    """One hop of the delegation tree, as the agent map draws it.

    A node is what the walk could honestly say about a pin, and the `status`
    says how far it got. `ok` resolved: the caller may see the delegate and the
    pinned version exists, so `children` holds what *it* delegates to - to the
    depth the policy lets a run actually reach. `restricted` is a delegate the
    caller may not see: deliberately indistinguishable from one that does not
    exist, carrying no name and no children, so a parent's map cannot be used to
    probe the organization's private agents one pin at a time. `unpinned` is a
    pin whose version is gone - the delegate is named, because the caller can
    see the row, but there is no frozen spec left to walk. `cycle` is a pin that
    returns to an agent already on this branch; it is named and never expanded,
    which is what keeps an already-stored loop from hanging the walk. `archived`
    is a delegate somebody has since retired: the pin was valid when it was
    published, the row and the frozen spec are both still there, and every run
    that reaches this hop is refused - so it is named and not expanded, the same
    lifecycle check `_resolve_pins` makes at publish and `_resolve_delegate`
    makes at run time.

    `truncated` marks a delegate that has a roster of its own which no run
    starting here would ever reach - the depth budget ran out, or its own
    delegation binding is switched off - so the map can say "more below" without
    pretending the levels beyond the cap would run.
    """

    key: str = Field(description="Stable within one response - what the map focuses by.")
    kind: Literal["delegate", "specialist"]
    status: Literal["ok", "restricted", "unpinned", "cycle", "archived"]
    agent_id: UUID | None = Field(
        default=None,
        description=(
            "The delegate's agent row - present on every delegate, including a "
            "restricted one, because the id already sits in a spec the caller "
            "may read. A specialist has no row and no id."
        ),
    )
    name: str | None = Field(
        default=None,
        description="Absent exactly when the caller may not see the delegate.",
    )
    mode: DelegationMode | None = None
    pinned_version: int | None = Field(
        default=None,
        description="The version number the pin froze, when it still exists.",
    )
    stale: bool = Field(
        default=False,
        description="The delegate has published past the pinned version.",
    )
    truncated: bool = Field(
        default=False,
        description="Has delegates of its own that a run from this root cannot reach.",
    )
    children: list["DelegationTreeNode"] = Field(default_factory=list)


class DelegationTree(BaseSchema):
    """The whole delegation tree under one agent's draft, in one response.

    The map used to walk this a page at a time - one hop per click-through -
    which is also N+1 requests if a client scripts it. One response, bounded the
    same way publish's cycle walk is, replaces that (#276).

    The root's own `max_depth` and `max_fanout` are deliberately absent. They
    are on the draft the caller is editing, so the Builder already has them and
    already renders them beside the hub; answering with a second copy read out
    of the *stored* draft is two numbers for one setting, and the one that
    disagrees is the one nobody is looking at.
    """

    truncated: bool = Field(
        default=False,
        description="The walk stopped at its node bound rather than at the bottom.",
    )
    nodes: list[DelegationTreeNode]


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
    reviewed: bool = Field(
        default=True,
        description=(
            "Whether somebody here checked this entry - that the auth flow works and "
            "the description is honest. False for a server mirrored from the public "
            "registry, where the description is the publisher's and there is no token "
            "hint because the registry has no such field."
        ),
    )


class McpCatalog(BaseSchema):
    items: list[McpCatalogEntry]
    total: int
    registry_total: int = Field(
        default=0,
        description=(
            "How many servers the mirrored public registry holds, for a console that "
            "has to say what searching reaches. Zero on the registry's own responses - "
            "there `total` is the result count and this would be the same number twice."
        ),
    )


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
    file_ids: list[UUID] = Field(
        default_factory=list,
        description=(
            "Files already uploaded through `POST /files/upload`, to attach to this "
            "turn. Where each one goes is the agent's to decide - written into its "
            "workspace when it has one, read into the prompt when it does not - which "
            "is the same routing the chat and the widget get. They must be the "
            "caller's own uploads"
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


class AgentTemplateRead(BaseSchema):
    """One shipped template as the picker shows it - never the instructions."""

    key: str = Field(description="`<industry>/<folder>`, how an install request names it")
    name: str
    description: str
    capabilities: list[str] = Field(description="Capability ids it switches on")
    skills: list[str] = Field(description="Gallery keys installed with it, if missing")
    mcp: list[str] = Field(description="Catalog keys worth connecting - suggestions, not bindings")
    attach: list[str] = Field(
        description="What a person still has to provide before publishing: collection, context"
    )
    budget_usd: float | None = None
    installed: bool = Field(
        description="Whether this organization already has an agent by that name"
    )


class TemplateIndustryRead(BaseSchema):
    id: str
    templates: list[AgentTemplateRead]


class AgentTemplateCatalog(BaseSchema):
    industries: list[TemplateIndustryRead]


class TemplateInstallRequest(BaseSchema):
    key: str = Field(min_length=1, max_length=128)


class TemplateInstallResult(BaseSchema):
    """What was created, and what the person still has to do.

    An installed template is a **draft**: it names no model, because this
    platform has no organization-wide default on purpose, and it may name no
    collection. Both are decisions the spec refuses to make on somebody's
    behalf, so the result carries them back rather than publishing something
    that would answer its first question from nowhere.
    """

    agent_id: UUID
    slug: str
    name: str
    skills_installed: list[str] = Field(description="Gallery skills copied in for this agent")
    attach: list[str] = Field(description="What to attach before publishing")
    suggested_mcp: list[str] = Field(description="Catalog keys worth connecting")
