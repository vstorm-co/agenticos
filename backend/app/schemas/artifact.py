"""Schemas for published artifacts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.schemas.base import BaseSchema
from app.schemas.virtual_table import (
    MAX_FILTERS,
    Aggregate,
    ColumnTypeName,
    FilterOp,
    FilterValue,
    RecordFilter,
    RecordSort,
    SortDirection,
)

ArtifactMediaTypeLiteral = Literal["text/html", "text/markdown"]
ConsentStateLiteral = Literal["not_needed", "pending", "consented", "declined", "withdrawn"]


class BindingFilter(BaseModel):
    """One condition of a page query as the model writes it, before resolution."""

    # Not `BaseSchema`: a filter's operand is a cell value, kept exactly as sent.
    model_config = ConfigDict(extra="forbid")

    column: str = Field(description="The column's id or label")
    op: FilterOp
    value: FilterValue = Field(
        default=None,
        description=(
            "A value of the column's type; a list for `in`; true or false for `is_null`. "
            "A choice by its label"
        ),
    )


class BindingSort(BaseSchema):
    """A page query's order as the model writes it."""

    model_config = ConfigDict(extra="forbid")

    by: str = Field(description="`created_at`, `updated_at`, or a column's id or label")
    direction: SortDirection = "asc"


class BindingRequest(BaseSchema):
    """A page query as the model asks for it, before resolution.

    The table is named by `view` or by `table`, never both. A view's filters and
    sort are copied into the query when it is published: editing the view later
    changes nothing on the page.
    """

    model_config = ConfigDict(extra="forbid")

    view: UUID | str | None = Field(
        default=None, description="A saved view's id from `list_views`, or its exact name"
    )
    table: UUID | str | None = Field(
        default=None, description="A table's id from `list_tables`, or its exact name"
    )
    fields: dict[str, str] = Field(
        description="Field name to the table column it reads, given as a column id or a label"
    )
    filters: list[BindingFilter] = Field(default_factory=list, max_length=MAX_FILTERS)
    sort: BindingSort | None = None
    limit: int | None = Field(default=None, ge=1)


class BindingReach(BaseSchema):
    """Everything a page query reaches, as the tables stood when it was resolved.

    What a page load compares with the tables now: a column whose revision moved or
    that was archived, an archived table, or a linked table now labelling its records
    by another column, and the binding is served nothing until it is published again.
    """

    tables: dict[UUID, dict[UUID, int]] = Field(
        description=(
            "Every table reached - the query's own and each linked one - to the revision "
            "of each column reached there"
        )
    )
    named_by: dict[UUID, UUID | None] = Field(
        default_factory=dict,
        description=(
            "For each linked table a link field of the page labels records from, the "
            "column it labels them by; null for one with no text column"
        ),
    )


class ArtifactBinding(BaseSchema):
    """A page query as a version stores it, every name resolved to an id.

    Read with the page owner's access on every load, the same records for everyone
    who opens the page.
    """

    name: str
    table_id: UUID
    filters: list[RecordFilter] = Field(default_factory=list)
    sort: RecordSort = Field(default_factory=RecordSort)
    limit: int
    fields: dict[str, UUID]
    reach: BindingReach


class ArtifactBindingRead(BaseSchema):
    """A binding as an API client sees it: its table and its field names, no column ids."""

    name: str
    table_id: UUID
    fields: list[str]


class DisclosedDerivation(BaseSchema):
    """Where a worked-out column's values come from, so the console can say it in its own words."""

    kind: Literal["formula", "lookup", "rollup", "link"]
    inputs: list[str] = Field(
        default_factory=list, description="A formula's input columns, by label"
    )
    table: str | None = Field(
        default=None, description="The linked table a link, lookup or rollup reads"
    )
    column: str | None = Field(
        default=None,
        description=(
            "The column it reads there, by label: a link's label column (none: the record "
            "ids), a lookup's or a rollup's target (none for a count)"
        ),
    )
    aggregate: Aggregate | None = Field(default=None, description="A rollup's aggregate")


class DisclosedFilter(BaseSchema):
    """One condition of a page query, as its parts."""

    column: str = Field(description="The column's label")
    op: FilterOp
    value: FilterValue = Field(
        default=None,
        description=(
            "The operand with a choice shown by its label; `true` for `is_null` means the "
            "cell is empty"
        ),
    )


class DisclosedSort(BaseSchema):
    """The order of a page query, as its parts."""

    record_time: Literal["created_at", "updated_at"] | None = Field(
        default=None, description="Set when it orders by when a record was created or changed"
    )
    column: str | None = Field(default=None, description="The column's label, otherwise")
    derived: DisclosedDerivation | None = None
    direction: SortDirection


class DisclosedField(BaseSchema):
    """One field of a page query, as its parts."""

    name: str = Field(description="The name the page reads it by")
    column: str = Field(description="The column's label")
    type: ColumnTypeName
    derived: DisclosedDerivation | None = None


class BindingParts(BaseSchema):
    """A page query as structured parts, for the console to put into words of its own.

    The same facts as :class:`BindingDisclosure`, which is built from them.
    """

    table: str
    filters: list[DisclosedFilter]
    sort: DisclosedSort
    limit: int
    fields: list[DisclosedField]
    linked: list[str] = Field(
        description="The other tables the query reaches through its links, by name"
    )


class BindingDisclosure(BaseSchema):
    """A page query in words: what everyone who opens the page reads through it."""

    table: str = Field(description="The table's name")
    filters: list[str] = Field(description="Each condition a record meets, all of them together")
    sort: str = Field(description="The order the records come in")
    limit: int = Field(description="The most records served")
    fields: dict[str, str] = Field(
        description=(
            "Each field and what it reads: `Status (single_select)`, or for a worked-out "
            "column what it is worked out from, as `Pay band: formula over Salary, Level`"
        )
    )


class BoundField(BaseSchema):
    """What one field of a binding reads now: its column's current label and type."""

    label: str = Field(description="The column's label now; the field name for a missing column")
    type: ColumnTypeName = Field(description="The column's type now; `text` for a missing column")
    options: list[str] | None = Field(
        default=None, description="A select column's live choices, by label"
    )
    state: Literal["ok", "archived", "missing"] = Field(
        description="`archived` or `missing` when the column no longer serves values"
    )


class BindingData(BaseSchema):
    """One binding's records for a page load, its page query read with the owner's access."""

    status: Literal["ok", "unavailable"]
    reason: str | None = Field(
        default=None,
        description=(
            "Why the binding is unavailable. Only for a viewer who may edit the page, but "
            "`awaiting_consent` - the owner hasn't confirmed sharing it - and `not_current` "
            "- a newer version is served - for everyone"
        ),
    )
    changed: str | None = Field(
        default=None,
        description=(
            "With `source_changed`: the column, by its current label, or the table that "
            "changed since the page was published. Only for a viewer who may edit the page"
        ),
    )
    truncated: bool = Field(description="Whether a limit left records out")
    limit: Literal["records", "bytes"] | None = Field(
        default=None, description="Which limit left records out"
    )
    count: int = Field(description="How many records are served, not how many the query matches")
    fields: dict[str, BoundField]
    # Any: a cell is a string, number, boolean, list or link list, by its column's type.
    records: list[dict[str, Any]] = Field(
        description="Each record as its `id` and every named field, `null` when empty"
    )


class ArtifactData(BaseSchema):
    """A page version's live data: every binding's page query, read with the owner's access."""

    bindings: dict[str, BindingData]
    current: bool = Field(
        description=(
            "Whether the version asked about is still the artifact's current one. "
            "False once a newer version was published: every binding is then unavailable, "
            "and the viewer moves to the current version"
        )
    )
    read_at: datetime


class ArtifactVersionRead(BaseSchema):
    id: UUID
    number: int
    media_type: ArtifactMediaTypeLiteral
    size_bytes: int
    run_id: UUID | None = Field(
        default=None, description="The run that published it, while that run is still kept"
    )
    restored_from: int | None = Field(
        default=None,
        description="The number of the version restored to make this one; null for a publish",
    )
    consent_state: ConsentStateLiteral = Field(
        description=(
            "Where its data stands with the page's owner: `not_needed` (it reads none), "
            "`pending`, `consented`, `declined`, or `withdrawn` for a consent that no longer "
            "holds - taken back by an editor, or given by an owner the page no longer has"
        )
    )
    created_at: datetime


class ArtifactVersionList(BaseSchema):
    items: list[ArtifactVersionRead]
    total: int


class ArtifactRead(BaseSchema):
    id: UUID
    name: str = Field(
        description="The handle the agent republishes it by; unique per agent and environment"
    )
    title: str
    visibility: str
    owner_user_id: UUID | None = None
    agent_id: UUID | None = Field(
        default=None, description="The agent whose runs publish it; null once that agent is gone"
    )
    environment_id: UUID | None = Field(
        default=None,
        description="The named environment whose runs publish it; null for the default one",
    )
    environment_name: str | None = Field(
        default=None, description="That environment's name, while it exists"
    )
    public_url: str | None = Field(
        default=None,
        description="The 'anyone with the link' address, when one is on. Unguessable, revocable",
    )
    published_at: datetime
    current_version: ArtifactVersionRead | None = None
    live: bool = Field(
        default=False, description="Whether the current version reads live data through bindings"
    )
    archived_at: datetime | None = Field(
        default=None,
        description=(
            "When it was archived, or null. An archived page serves nothing - no view, data, "
            "public link or embed - until someone who may edit it restores it"
        ),
    )
    created_at: datetime
    updated_at: datetime | None = None


class ArtifactPublicLinkRead(BaseSchema):
    """The public link's settings, which hold whether or not the link is on."""

    expires_at: datetime | None = Field(
        default=None, description="After this, the link opens nothing"
    )
    pinned_version_id: UUID | None = Field(
        default=None, description="The version the link shows instead of the newest one"
    )
    pinned_version: int | None = Field(default=None, description="That version's number")
    password_protected: bool = Field(
        description="Whether a visitor must give a password before the page is shown"
    )
    view_count: int = Field(description="How many times the public link was opened")
    last_viewed_at: datetime | None = None
    embed_origins: list[str] = Field(
        description="The sites allowed to frame the public page, as `https://host` origins"
    )
    embed_url: str | None = Field(
        default=None,
        description="The address to put in another site's `<iframe>`, while the link is on",
    )


class ArtifactConsentRead(BaseSchema):
    """Where the latest version's data stands with the page's owner, for a caller served it."""

    version: int = Field(description="The latest version's number")
    state: ConsentStateLiteral = Field(description="Its state, as on `ArtifactVersionRead`")
    fingerprint: str | None = Field(
        default=None,
        description="The digest of its page queries; what confirming it sends back",
    )
    automatic: bool = Field(description="Whether it was consented without anyone confirming")
    grown: list[str] = Field(
        default_factory=list,
        description=(
            "For an automatic consent, what it reaches that the version served before it "
            "did not - `+Deals` for a table, `+Salary` for a column. Only for a caller who "
            "may confirm"
        ),
    )
    via: str | None = Field(
        default=None,
        description=(
            "For an automatic consent given by an `edit_data` grant, the name of the editor "
            "whose grant it was. Only for a caller who may confirm"
        ),
    )
    audience_version: int | None = Field(
        default=None,
        description=(
            "The version everyone else who opens the page is served; null when nothing of it "
            "is available to them yet"
        ),
    )
    shared: bool = Field(
        description="Whether the audience is served that version's data now: its consent holds"
    )
    owner_name: str | None = Field(default=None, description="Who owns the page's data")
    withdrawn_at: datetime | None = Field(
        default=None,
        description="When an editor last withdrew consent; every consent before it is void",
    )
    auto_consent: bool = Field(
        description="Whether the owner's own republishes are consented without asking"
    )
    may_confirm: bool = Field(
        description="Whether the caller may confirm a version's data: its owner, or an admin"
    )
    may_withdraw: bool = Field(description="Whether the caller may withdraw consent: any editor")
    may_enable_auto_consent: bool = Field(description="Only the owner, as themselves")
    may_disable_auto_consent: bool = Field(description="The owner, or an admin")


PublicDataNotHolding = Literal[
    "switch_off",
    "no_served_version",
    "queries_changed",
    "owner_gone",
    "owner_membership_changed",
    "member_consent_missing",
    "link_expired",
]


class ArtifactPublicDataRead(BaseSchema):
    """Where the owner's consent to show the page's data to anyone with its link stands.

    Only for a caller who may edit the page. Names no row: a consent is to page queries.
    """

    switch_on: bool = Field(
        description="Whether the organization lets a page's data reach anonymous visitors"
    )
    consented: bool = Field(
        description="Whether the owner confirmed it, and it has not been voided"
    )
    fingerprint: str | None = Field(
        default=None, description="The digest of the page queries the consent was given to"
    )
    version: int | None = Field(
        default=None, description="The version the public link serves: pinned, else the audience's"
    )
    by_name: str | None = Field(default=None, description="Who confirmed it")
    at: datetime | None = Field(default=None, description="When it was confirmed")
    holds: bool = Field(
        description=(
            "Whether the public link shows the data now: the switch is on and the consent is "
            "to the served version's queries, under the owner, with their consent holding"
        )
    )
    not_holding: PublicDataNotHolding | None = Field(
        default=None,
        description=(
            "Why a consented page's data is not shown now, in the order the gates are taken; "
            "none when it holds or nothing is consented"
        ),
    )


class ArtifactDetail(ArtifactRead):
    """One artifact as its own page reads it, with what the caller may do to it.

    `current_version` is the version the caller is served: the latest for its owner,
    its editors and the roles that read every table, the newest consented one for
    everyone else - null when none is available to them yet.
    """

    can_edit: bool = Field(
        description=(
            "Whether the caller may retitle, share, link, restore or delete it - the role "
            "scope and any grant on this artifact, decided by the server"
        )
    )
    may_change_owner: bool = Field(
        default=False,
        description=(
            "Whether the caller may hand the page to another member: its owner, or an Owner "
            "or Admin, each signed in as themselves - decided by the server"
        ),
    )
    may_grant_edit_data: bool = Field(
        default=False,
        description=(
            "Whether the caller may give someone the `edit_data` level on this page: its "
            "owner, or an Owner or Admin, each signed in as themselves - decided by the server"
        ),
    )
    may_confirm_public_data: bool = Field(
        default=False,
        description=(
            "Whether the caller may confirm the page's data for anyone with its link: its "
            "owner, or an Owner or Admin, each signed in as themselves - decided by the server"
        ),
    )
    public_link: ArtifactPublicLinkRead
    public_data: ArtifactPublicDataRead | None = Field(
        default=None,
        description="Where the page's public data consent stands. Only for a caller who may edit it",
    )
    bindings: list[ArtifactBindingRead] = Field(
        default_factory=list,
        description=(
            "The current version's bindings: each one's table and field names. Only for a "
            "caller who may edit it; empty otherwise"
        ),
    )
    consent: ArtifactConsentRead | None = Field(
        default=None,
        description=(
            "Where the latest version's data stands. Only for a caller served the latest "
            "version, and only when it reads data"
        ),
    )


class ArtifactList(BaseSchema):
    items: list[ArtifactRead]
    total: int


class ArtifactAgent(BaseSchema):
    """An agent behind at least one artifact the caller may open."""

    id: UUID
    name: str


class ArtifactAgentList(BaseSchema):
    items: list[ArtifactAgent]


class ArtifactUpdate(BaseSchema):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class ArtifactPublicLinkUpdate(BaseSchema):
    """Change the public link's settings. A field left out is left as it is.

    `null` clears `expires_at`, `pinned_version_id` and `password`.
    """

    # Aware, so a datetime sent without an offset is refused at the door instead
    # of failing the comparison with now() as a 500.
    expires_at: AwareDatetime | None = Field(
        default=None,
        description="When the link stops opening anything; in the future, with a UTC offset",
    )
    pinned_version_id: UUID | None = Field(
        default=None, description="A kept version the link shows instead of the newest one"
    )
    password: str | None = Field(
        default=None,
        min_length=6,
        max_length=128,
        description="What a visitor must type first. Stored hashed; never returned",
    )
    embed_origins: list[str] | None = Field(
        default=None,
        max_length=20,
        description=(
            "The sites allowed to frame the public page - `https://intranet.example.com`, "
            "or `https://*.example.com` for its subdomains. Scheme and host only"
        ),
    )


class ArtifactConsentCreate(BaseSchema):
    """Confirm a version's data: the digest of the page queries the person was shown."""

    fingerprint: str = Field(min_length=64, max_length=64)


class ArtifactPublicDataCreate(BaseSchema):
    """Confirm the page's data for anyone with its link: the digest of the page queries the
    person was shown, and that they confirmed what the screen says."""

    fingerprint: str = Field(min_length=64, max_length=64)
    audience_digest: str = Field(
        min_length=64,
        max_length=64,
        description="The digest of who the link reaches, as the disclosure showed it",
    )
    confirmed: bool = Field(description="Must be true: the person confirmed the screen")


class ArtifactOwnerUpdate(BaseSchema):
    """Hand a page to another member of its organization."""

    user_id: UUID = Field(description="The member who becomes the page's owner")


class ArtifactAutoConsentUpdate(BaseSchema):
    """Turn "don't ask for consent on republish" on or off."""

    enabled: bool
    confirmed: str | None = Field(
        default=None,
        max_length=64,
        description=(
            "Turning it on: the version of the text the person confirmed, as the console "
            "names it. Recorded in the audit entry"
        ),
    )


class ArtifactDisclosure(BaseSchema):
    """What confirming a version shares, and with whom - shown before it is confirmed."""

    version: int
    fingerprint: str | None = None
    bindings: dict[str, BindingDisclosure] = Field(
        description="Each binding's page query in words, as its owner reads the tables now"
    )
    parts: dict[str, BindingParts] = Field(
        description="The same queries as structured parts, for the console to word itself"
    )
    tables: list[str] = Field(description="Every table the queries read, linked ones included")
    visibility: str
    people: list[str] = Field(
        default_factory=list, description="The addresses of the people the page is shared with"
    )
    groups: list[str] = Field(
        default_factory=list, description="The names of the groups the page is shared with"
    )
    roles: list[str] = Field(
        description="The roles that open every page, whatever its visibility and grants"
    )
    problem: str | None = Field(
        default=None,
        description="Why it cannot be confirmed now: its owner left, or can't read a table",
    )


class ArtifactPublicDataDisclosure(BaseSchema):
    """What confirming a page's data for anyone with its link shares, and with whom."""

    switch_on: bool = Field(
        description="Whether the organization lets a page's data reach anonymous visitors"
    )
    link_on: bool = Field(description="Whether the page has a public link")
    password_protected: bool
    expires_at: datetime | None = None
    embed_origins: list[str] = Field(
        description="Every site that may frame the public page, as `https://host` origins"
    )
    version: int | None = Field(
        default=None, description="The version the link serves: pinned, else the audience's"
    )
    fingerprint: str | None = Field(
        default=None, description="Its page queries' digest; what confirming sends back"
    )
    audience_digest: str = Field(
        description="Digest of the embedding sites, the password and the link being on; "
        "what confirming sends back, so it binds the audience that was shown"
    )
    member_consent: bool = Field(
        description="Whether that version's consent from the owner holds; confirming needs it"
    )
    data: ArtifactDisclosure | None = Field(
        default=None,
        description="That version's page queries in words, as for the members' consent",
    )
    confirmable: bool = Field(description="Whether confirming would be accepted now")
    problem: str | None = Field(
        default=None, description="Why confirming would be refused now; none when it would not"
    )


class ArtifactView(BaseSchema):
    """Where a frame loads one version from, and until when that address holds."""

    url: str = Field(description="Signed, short-lived; served under a sandbox policy")
    expires_at: datetime
    version: ArtifactVersionRead
    nonce: str = Field(description="What the page and the console match their messages on")
    live: bool = Field(description="Whether the page asks the console for its bindings' data")
    injected: bool = Field(
        default=False,
        description=(
            "Whether the page is served with its bindings' data written in, so the console "
            "need not read it for the first load. Only when the caller asked for data"
        ),
    )
    awaiting_consent: bool = Field(
        default=False,
        description=(
            "Whether the version this viewer is served reads data its owner has not "
            "confirmed sharing with them, so every binding is empty for them"
        ),
    )
    bindings: int = Field(
        default=0, description="How many bindings the version has, whoever is asking"
    )


class PublicArtifactRead(BaseSchema):
    """What a stranger holding the link learns: the page, and nothing about who made it.

    Behind a password, nothing at all until the password is given: `password_required`
    is true and the other fields are empty.
    """

    password_required: bool = False
    title: str | None = None
    published_at: datetime | None = None
    view: ArtifactView | None = None


class PublicArtifactUnlock(BaseSchema):
    password: str = Field(min_length=1, max_length=128)
