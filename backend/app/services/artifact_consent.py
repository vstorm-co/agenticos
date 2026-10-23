"""A page owner's consent to share its data, and which version each viewer is served.

A bound page's data is read with its owner's access, so who else reads it is the
owner's decision, made per version: a consent is to that version's page queries,
their reach included (`query_fingerprint`), and is given under the owner's
membership. It holds while that membership is still the page owner's and no editor
has withdrawn it since (`Artifact.consent_withdrawn_at`, a cut-off voiding every
consent given before it).

Who is served what:

- The **owner**, anyone who may **edit** the page, and the roles that read every
  table (`tables:view` at scope `ALL` - Owner, Admin, Builder, Operator) are served
  the latest version, so an editor's agent keeps editing what is current. Its data
  goes to the owner and those roles whatever the consent, and to an editor only
  while it holds.
- Everyone else - the page's **audience** - is served the newest version that was
  ever consented or reads no data (`not_needed`): the whole page, even when that
  consent no longer holds. Its data only while it does; otherwise every binding is
  `awaiting_consent`. A page with no such version is not available to them yet.

A version's state is set when it is published (:func:`consent_for`): `not_needed`
without bindings; `consented` automatically when its page queries match the newest
consent that still holds, or when the owner's own run publishes it with the page's
auto-consent on, or when the person publishing it holds `edit_data` on the page (their own
grant or a group's; `consent_via_grant` names them, and the owner's membership is the one
that consents); `pending` otherwise.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import current_impersonator
from app.core.exceptions import NotFoundError
from app.core.permissions import ROLE_PERMS, AuthContext, Perm, Scope
from app.db.models.artifact import Artifact, ArtifactVersion, ConsentState
from app.db.models.resource_grant import GrantLevel
from app.repositories import artifact_repo, member_repo, resource_grant_repo
from app.schemas.artifact import ArtifactBinding
from app.services.access import ARTIFACT, accessible_ids
from app.services.virtual_tables import VirtualTableService

PAGE_ROLES: tuple[str, ...] = tuple(
    role for role, perms in ROLE_PERMS.items() if perms.get(Perm.ARTIFACTS_VIEW) is Scope.ALL
)
"""The roles that open every page, whatever its visibility and grants - part of any
page's audience, and named in every disclosure."""

AUTO_CONSENT_WORDING = "auto_consent.v2"
"""The id of the text a person confirms to turn auto-consent on, a key of
:data:`AUTO_CONSENT_TEXTS`. The console shows the text and sends this id back."""

AUTO_CONSENT_TEXTS: dict[str, str] = {
    "auto_consent.v1": (
        "Any change your runs make to this page's data, new columns and tables included, "
        "reaches everyone who can open it without asking you - API runs too."
    ),
    AUTO_CONSENT_WORDING: (
        "Any data change your runs make to this page, including new tables and columns, "
        "reaches everyone who can open it without asking you. This includes API runs."
    ),
}
"""Every wording ever offered, by id, in English: the single source of what a confirmed id
meant. The audit entry records the text itself, so what was agreed to stays readable after
the wording changes; the console's English string must equal it. Only the current id is
accepted; older ids stay so audit rows that name them still resolve."""


EDIT_DATA_PERSON_WORDING = "edit_data.person.v2"
EDIT_DATA_GROUP_WORDING = "edit_data.group.v2"
"""The ids of the texts an owner confirms to give one person, or one group, the
`edit_data` level; keys of :data:`EDIT_DATA_TEXTS`."""

EDIT_DATA_TEXTS: dict[str, str] = {
    "edit_data.person.v1": (
        "{name} can change what data this page shows to everyone who can open it, including "
        "new tables and columns, without asking you; that includes their API runs."
    ),
    "edit_data.group.v1": (
        "Everyone in {name}, now and later, can change what data this page shows to everyone "
        "who can open it, including new tables and columns, without asking you; that "
        "includes their API runs."
    ),
    EDIT_DATA_PERSON_WORDING: (
        "{name} can change the data everyone sees on this page, including new tables and "
        "columns, without asking you. This also covers their API runs."
    ),
    EDIT_DATA_GROUP_WORDING: (
        "Anyone in {name}, now or later, can change the data everyone sees on this page, "
        "including new tables and columns, without asking you. This also covers their API runs."
    ),
}
"""Every wording ever offered for `edit_data`, by id, in English, with `{name}` for the person
or group. The audit entry records the text with the name filled in; the console's English
strings must read the same. Older ids stay so audit rows that name them still resolve."""


@dataclass(frozen=True)
class Served:
    """The version one viewer is served, and whether its data may be read for them."""

    version: ArtifactVersion | None
    """`None` when nothing of the page is available to them yet."""
    data: bool
    """Whether its bindings are read for them, as far as consent goes."""
    latest: bool
    """Whether they are served the latest version, whatever its state."""


@dataclass(frozen=True)
class VersionConsent:
    """Who published a version, and the consent it starts with."""

    published_by_user_id: UUID | None
    published_by_membership_id: UUID | None
    query_fingerprint: str | None
    consent_state: ConsentState
    consented_at: datetime | None = None
    consented_by_membership_id: UUID | None = None
    consent_automatic: bool = False
    consent_via_grant: UUID | None = None

    def columns(self) -> dict[str, object]:
        return {
            "published_by_user_id": self.published_by_user_id,
            "published_by_membership_id": self.published_by_membership_id,
            "query_fingerprint": self.query_fingerprint,
            "consent_state": self.consent_state.value,
            "consented_at": self.consented_at,
            "consented_by_membership_id": self.consented_by_membership_id,
            "consent_automatic": self.consent_automatic,
            "consent_via_grant": self.consent_via_grant,
        }


def reads_every_table(ctx: AuthContext) -> bool:
    """Whether `ctx`'s role reads every table anyway, so a page's data hides nothing from it."""
    return ctx.user_id is not None and ctx.scope_for(Perm.TABLES_VIEW) is Scope.ALL


def as_themselves(ctx: AuthContext) -> bool:
    """Whether a person is acting in their own name: signed in, and nobody impersonating them.

    There is no API-key identity on `AuthContext` on this branch; when organization
    API keys arrive, a key acting for a member must be refused here too.
    """
    return ctx.user_id is not None and current_impersonator() is None


def may_confirm(ctx: AuthContext, artifact: Artifact) -> bool:
    """Whether `ctx` may confirm a version's data: the owner, or `artifacts:edit` at scope
    `ALL` for them - each as themselves. A grant to edit the page is not enough."""
    if not as_themselves(ctx):
        return False
    return ctx.user_id == artifact.owner_user_id or ctx.scope_for(Perm.ARTIFACTS_EDIT) is Scope.ALL


def may_grant_edit_data(ctx: AuthContext, artifact: Artifact) -> bool:
    """Whether `ctx` may grant or raise a grant to `edit_data`: the same people who may
    confirm the page's data, since it is a standing consent to its editor's republishes.
    Lowering or revoking it is any editor's."""
    return may_confirm(ctx, artifact)


def consent_holds(version: ArtifactVersion, artifact: Artifact, membership_id: UUID | None) -> bool:
    """Whether `version`'s consent stands: given under the owner's membership now, and
    not voided by a withdrawal since."""
    if version.consent_state != ConsentState.CONSENTED.value or membership_id is None:
        return False
    if version.consented_by_membership_id != membership_id:
        return False
    withdrawn = artifact.consent_withdrawn_at
    return withdrawn is None or (
        version.consented_at is not None and version.consented_at > withdrawn
    )


def shown_state(
    version: ArtifactVersion, artifact: Artifact, membership_id: UUID | None
) -> ConsentState:
    """A version's state as a person reads it: a consent that no longer holds reads as
    withdrawn."""
    if version.consent_state == ConsentState.CONSENTED.value and not consent_holds(
        version, artifact, membership_id
    ):
        return ConsentState.WITHDRAWN
    return ConsentState(version.consent_state)


async def owner_membership_id(db: AsyncSession, artifact: Artifact) -> UUID | None:
    """The page owner's active membership, which a consent must have been given under."""
    if artifact.owner_user_id is None:
        return None
    membership = await member_repo.get_active(
        db, organization_id=artifact.organization_id, user_id=artifact.owner_user_id
    )
    return membership.id if membership is not None else None


async def _data_holds(db: AsyncSession, artifact: Artifact, version: ArtifactVersion) -> bool:
    """Whether `version`'s data may go to a viewer who holds no standing of their own."""
    if not version.bindings:
        return True
    if version.consent_state != ConsentState.CONSENTED.value:
        return False
    return consent_holds(version, artifact, await owner_membership_id(db, artifact))


async def served(
    db: AsyncSession, ctx: AuthContext | None, artifact: Artifact, *, can_edit: bool
) -> Served:
    """The version `ctx` is served, by the rules in this module's docstring.

    `ctx` is `None` for the page's audience at large - a public link, a group chat -
    and `can_edit` is whether `ctx` may edit the page, which the caller has decided.
    """
    owner = ctx is not None and ctx.user_id is not None and ctx.user_id == artifact.owner_user_id
    sees_everything = owner or (ctx is not None and reads_every_table(ctx))
    if ctx is not None and (sees_everything or can_edit):
        latest = await artifact_repo.latest_version(db, artifact.id)
        data = latest is not None and (sees_everything or await _data_holds(db, artifact, latest))
        return Served(version=latest, data=data, latest=True)
    version = await artifact_repo.latest_served(db, artifact.id)
    data = version is not None and await _data_holds(db, artifact, version)
    return Served(version=version, data=data, latest=False)


async def served_many(
    db: AsyncSession, ctx: AuthContext | None, artifacts: Sequence[Artifact]
) -> dict[UUID, ArtifactVersion]:
    """The version each page is served to `ctx`, in a few queries for a whole listing.

    The pages it sees the latest of are decided in one grant query rather than one
    `resolve_access` per page; a page with nothing available to `ctx` is left out.
    """
    if not artifacts:
        return {}
    latest_for: set[UUID] = set()
    if ctx is not None and ctx.user_id is not None:
        if reads_every_table(ctx):
            latest_for = {artifact.id for artifact in artifacts}
        else:
            editable = await accessible_ids(
                db, ctx, artifacts, Perm.ARTIFACTS_EDIT, resource_type=ARTIFACT
            )
            latest_for = editable | {
                artifact.id for artifact in artifacts if artifact.owner_user_id == ctx.user_id
            }
    rest = [artifact.id for artifact in artifacts if artifact.id not in latest_for]
    found = await artifact_repo.latest_versions(db, sorted(latest_for)) if latest_for else {}
    if rest:
        found |= await artifact_repo.latest_served_versions(db, rest)
    return found


def visible_versions(view: Served, versions: Sequence[ArtifactVersion]) -> list[ArtifactVersion]:
    """Which of a page's `versions` a viewer `view` was decided for may open: all of them
    when served the latest; for the audience, the consented or unbound ones up to the
    one it is served."""
    if view.latest:
        return list(versions)
    if view.version is None:
        return []
    ceiling = view.version.number
    return [
        version
        for version in versions
        if version.number <= ceiling
        and version.consent_state in (ConsentState.CONSENTED.value, ConsentState.NOT_NEEDED.value)
    ]


async def consent_for(
    db: AsyncSession,
    artifact: Artifact,
    *,
    fingerprint: str | None,
    person: AuthContext | None,
    impersonated: bool = False,
) -> VersionConsent:
    """The consent a version publishing these page queries starts with.

    `person` is the member behind the run - never the identity a widget run stands
    in for its visitor - or the person restoring a version; `None` for a run with
    nobody behind it.

    `impersonated` says the run was started while an administrator impersonated
    `person`: carried on the run, since the request that knew is gone by the time a
    spawned task, a worker or a resumed approval publishes. A request under
    impersonation is refused whichever way it says. Impersonation never consents on
    the person's behalf, so only a republish of queries they already confirmed
    stands.
    """
    impersonated = impersonated or current_impersonator() is not None
    publisher = (
        await member_repo.get_active(
            db, organization_id=artifact.organization_id, user_id=person.user_id
        )
        if person is not None and person.user_id is not None
        else None
    )
    membership = await owner_membership_id(db, artifact) if fingerprint is not None else None

    def made(
        state: ConsentState, *, automatic: bool = False, via: UUID | None = None
    ) -> VersionConsent:
        return VersionConsent(
            published_by_user_id=person.user_id if person is not None else None,
            published_by_membership_id=publisher.id if publisher is not None else None,
            query_fingerprint=fingerprint,
            consent_state=state,
            consented_at=datetime.now(UTC) if automatic else None,
            consented_by_membership_id=membership if automatic else None,
            consent_automatic=automatic,
            consent_via_grant=via,
        )

    if fingerprint is None:
        return made(ConsentState.NOT_NEEDED)
    if membership is None:
        return made(ConsentState.PENDING)
    prior = await artifact_repo.latest_consent(
        db, artifact.id, membership_id=membership, after=artifact.consent_withdrawn_at
    )
    owners_own = (
        person is not None
        and person.user_id == artifact.owner_user_id
        and artifact.auto_consent
        and not impersonated
    )
    if (prior is not None and prior.query_fingerprint == fingerprint) or owners_own:
        return made(ConsentState.CONSENTED, automatic=True)
    if (
        person is not None
        and person.user_id is not None
        and person.user_id != artifact.owner_user_id
        and not impersonated
        and await resource_grant_repo.get_level(
            db,
            organization_id=artifact.organization_id,
            subject_user_id=person.user_id,
            resource_type=ARTIFACT.key,
            resource_id=artifact.id,
        )
        is GrantLevel.EDIT_DATA
    ):
        return made(ConsentState.CONSENTED, automatic=True, via=person.user_id)
    return made(ConsentState.PENDING)


def _bindings(version: ArtifactVersion) -> list[ArtifactBinding]:
    return [ArtifactBinding.model_validate(binding) for binding in version.bindings]


def _reached(version: ArtifactVersion) -> dict[UUID, set[UUID]]:
    reached: dict[UUID, set[UUID]] = {}
    for binding in _bindings(version):
        for table_id, revisions in binding.reach.tables.items():
            reached.setdefault(table_id, set()).update(revisions)
    return reached


async def grown(
    db: AsyncSession, ctx: AuthContext, artifact: Artifact, version: ArtifactVersion
) -> list[str]:
    """What `version` reaches that the version the audience was served before it did not:
    `+Deals` for a table, `+Salary` for a column of a table it already read.

    Read as `ctx`; a table `ctx` cannot read is left out.
    """
    before = await artifact_repo.served_before(db, artifact.id, version.number)
    was = _reached(before) if before is not None else {}
    service = VirtualTableService(db)
    added: list[str] = []
    for table_id, columns in _reached(version).items():
        try:
            source = await service.table_source(ctx, table_id)
        except NotFoundError:
            continue
        if table_id not in was:
            added.append(f"+{source.name}")
            continue
        labels = {column.id: column.label for column in source.columns}
        added += [f"+{labels[column]}" for column in columns - was[table_id] if column in labels]
    return added
