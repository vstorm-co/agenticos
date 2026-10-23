"""Confirming, withdrawing and auto-consent on a page's data, and what each viewer opens.

The service's decisions with the database stubbed at the repository edge;
`tests/integration/test_artifact_consent.py` proves them on real rows. The refusals
carry the weight: an editor by grant cannot confirm, nobody impersonated can, a
confirm for page queries other than the ones shown is a conflict, and the page's
audience never opens a version that waits for consent.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.capabilities.artifacts._toolset import _audience_note
from app.core.exceptions import (
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.permissions import AuthContext, OrgRoleName
from app.db.models.artifact import Artifact, ArtifactMediaType, ArtifactVersion, ConsentState
from app.db.models.resource_grant import Visibility
from app.schemas.artifact import (
    ArtifactAutoConsentUpdate,
    ArtifactBinding,
    ArtifactConsentCreate,
    ArtifactPublicLinkUpdate,
    BindingReach,
)
from app.schemas.virtual_table import ColumnDef
from app.services import artifact as artifacts
from app.services.artifact import ArtifactService
from app.services.artifact_consent import AUTO_CONSENT_TEXTS, AUTO_CONSENT_WORDING, Served
from app.services.virtual_tables import TableSource

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_public_data_state() -> Any:
    """`_detail` asks the public-data service for the link's state; these tests stub the
    database, so it answers nothing."""
    with patch(
        "app.services.artifact_public_data.ArtifactPublicDataService.state",
        AsyncMock(return_value=None),
    ):
        yield


PATH = "app.services.artifact"
MEMBERSHIP = uuid.uuid4()
FINGERPRINT = "f" * 64
TABLE = uuid.uuid4()
STAGE = uuid.uuid4()
GRANTEE, GONE, SALES = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _ctx(role: str = OrgRoleName.MEMBER, *, org: uuid.UUID | None = None) -> AuthContext:
    return AuthContext(user_id=uuid.uuid4(), organization_id=org or uuid.uuid4(), role=role)


def _artifact(owner: AuthContext, **values: Any) -> Artifact:
    return Artifact(
        id=uuid.uuid4(),
        organization_id=owner.organization_id,
        owner_user_id=owner.user_id,
        visibility=Visibility.ORG.value,
        agent_id=uuid.uuid4(),
        name="pipeline",
        title="Pipeline",
        public_key=None,
        public_view_count=0,
        embed_origins=[],
        auto_consent=values.pop("auto_consent", False),
        consent_withdrawn_at=values.pop("consent_withdrawn_at", None),
        published_at=datetime(2026, 10, 1, tzinfo=UTC),
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        **values,
    )


def _version(
    artifact: Artifact,
    *,
    number: int = 2,
    state: ConsentState = ConsentState.PENDING,
    bound: bool = True,
) -> ArtifactVersion:
    binding = ArtifactBinding(
        name="deals",
        table_id=TABLE,
        limit=10,
        fields={"stage": STAGE},
        reach=BindingReach(tables={TABLE: {STAGE: 0}}),
    ).model_dump(mode="json")
    consented = state == ConsentState.CONSENTED
    return ArtifactVersion(
        id=uuid.uuid4(),
        artifact_id=artifact.id,
        number=number,
        media_type=ArtifactMediaType.HTML.value,
        size_bytes=10,
        sha256="0" * 64,
        storage_path="artifacts/x.html",
        run_id=None,
        bindings=[binding] if bound else [],
        query_fingerprint=FINGERPRINT if bound else None,
        consent_state=state.value,
        consented_at=datetime(2026, 10, 2, tzinfo=UTC) if consented else None,
        consented_by_membership_id=MEMBERSHIP if consented else None,
        consent_automatic=False,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


_DEALS = TableSource(
    id=TABLE,
    name="Deals",
    archived=False,
    columns=[ColumnDef(id=STAGE, label="Stage", type="text")],
)


@contextmanager
def _stubs(
    artifact: Artifact,
    *,
    latest: ArtifactVersion | None,
    served: ArtifactVersion | None = None,
    owner: AuthContext | None = None,
    owner_reads: bool = True,
    can_edit: bool = True,
    membership: uuid.UUID | None = MEMBERSHIP,
) -> Iterator[dict[str, Any]]:
    """The repository edge for one page, recording what the service wrote."""
    audit = AsyncMock()
    settled = AsyncMock()
    written: dict[str, Any] = {}

    async def update_version(_db: object, *, version: ArtifactVersion, update_data: dict) -> Any:
        written.update(update_data)
        for key, value in update_data.items():
            setattr(version, key, value)
        return version

    async def update(_db: object, *, artifact: Artifact, update_data: dict) -> Artifact:
        written.update(update_data)
        for key, value in update_data.items():
            setattr(artifact, key, value)
        return artifact

    async def access(_db: Any, ctx: AuthContext, row: Artifact, perm: Any, **_kw: Any) -> bool:
        return perm.value == "artifacts:view" or can_edit or ctx.user_id == row.owner_user_id

    async def table_source(_self: Any, _ctx: Any, table_id: uuid.UUID, **_kw: Any) -> Any:
        if not owner_reads and _ctx is owner:
            raise NotFoundError(message="Table not found", details={"table_id": table_id})
        return _DEALS

    by_id = {version.id: version for version in (latest, served) if version is not None}

    async def get_version(_db: object, version_id: uuid.UUID, **_kw: Any) -> Any:
        return by_id.get(version_id)

    with ExitStack() as stack:
        for target, value in {
            "artifact_repo.get": AsyncMock(return_value=artifact),
            "artifact_repo.lock": AsyncMock(return_value=artifact),
            "artifact_repo.latest_version": AsyncMock(return_value=latest),
            "artifact_repo.latest_served": AsyncMock(return_value=served),
            "artifact_repo.get_version": get_version,
            "artifact_repo.update_version": update_version,
            "artifact_repo.update": update,
            "artifact_repo.environment_names": AsyncMock(return_value={}),
            "member_repo.get_active": AsyncMock(
                return_value=MagicMock(id=membership) if membership else None
            ),
            "member_context": AsyncMock(return_value=owner),
            "user_repo.get_by_id": AsyncMock(return_value=MagicMock(full_name="Olga Owner")),
            "resource_grant_repo.list_for_resource": AsyncMock(
                return_value=[
                    MagicMock(subject_user_id=GRANTEE, subject_group_id=None),
                    MagicMock(subject_user_id=None, subject_group_id=SALES),
                    MagicMock(subject_user_id=GONE, subject_group_id=None),
                ]
            ),
            "member_repo.get_emails_for_users": AsyncMock(
                return_value={GRANTEE: "ann@example.com", GONE: None}
            ),
            "group_repo.get_names": AsyncMock(return_value={SALES: "Sales"}),
            "resource_grant_repo.lower_edit_data": AsyncMock(return_value=2),
            "resolve_access": access,
            "record_audit": audit,
            "settle_version_request": settled,
        }.items():
            stack.enter_context(patch(f"{PATH}.{target}", new=value))
        stack.enter_context(patch(f"{PATH}.VirtualTableService.table_source", new=table_source))
        yield {"audit": audit, "written": written, "settled": settled}


def _service() -> ArtifactService:
    return ArtifactService(MagicMock())


class TestConfirmingData:
    async def test_the_owner_confirms_under_their_membership(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        latest = _version(artifact)
        with _stubs(artifact, latest=latest, served=latest, owner=owner) as seen:
            detail = await _service().confirm_data(
                owner, artifact.id, latest.id, ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )
        assert seen["written"]["consent_state"] == "consented"
        assert seen["written"]["consented_by_membership_id"] == MEMBERSHIP
        assert seen["written"]["consented_by_user_id"] == owner.user_id
        audit = seen["audit"].await_args.kwargs
        assert audit["action"] == "artifact.data_consented"
        assert audit["details"] == {"version": 2, "fingerprint": FINGERPRINT, "automatic": False}
        assert detail.consent is not None
        assert (detail.consent.state, detail.consent.shared) == ("consented", True)
        # The owner's own confirmation answers the version's pending request, if it has one.
        settled = seen["settled"].await_args
        assert (settled.args[2], settled.kwargs["by_user_id"]) == (latest, owner.user_id)

    @pytest.mark.security
    async def test_an_admin_confirms_for_the_owner_and_the_entry_says_so(self) -> None:
        owner = _ctx()
        admin = _ctx(OrgRoleName.ADMIN, org=owner.organization_id)
        artifact = _artifact(owner)
        latest = _version(artifact)
        with _stubs(artifact, latest=latest, owner=owner) as seen:
            await _service().confirm_data(
                admin, artifact.id, latest.id, ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )
        assert seen["written"]["consented_by_user_id"] == admin.user_id
        assert seen["written"]["consented_by_membership_id"] == MEMBERSHIP
        details = seen["audit"].await_args.kwargs["details"]
        assert details["for_owner"] == str(owner.user_id)
        assert "records" not in details

    @pytest.mark.security
    async def test_an_editor_by_grant_cannot_confirm(self) -> None:
        owner = _ctx()
        editor = _ctx(org=owner.organization_id)
        artifact = _artifact(owner)
        latest = _version(artifact)
        with (
            _stubs(artifact, latest=latest, owner=owner) as seen,
            pytest.raises(AuthorizationError),
        ):
            await _service().confirm_data(
                editor, artifact.id, latest.id, ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )
        assert seen["written"] == {}

    @pytest.mark.security
    async def test_an_impersonated_owner_cannot_confirm(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        latest = _version(artifact)
        with (
            _stubs(artifact, latest=latest, owner=owner) as seen,
            patch("app.services.artifact_consent.current_impersonator", return_value=uuid.uuid4()),
            pytest.raises(AuthorizationError),
        ):
            await _service().confirm_data(
                owner, artifact.id, latest.id, ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )
        assert seen["written"] == {}

    @pytest.mark.security
    async def test_page_queries_other_than_the_ones_shown_are_a_conflict(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        latest = _version(artifact)
        with (
            _stubs(artifact, latest=latest, owner=owner) as seen,
            pytest.raises(ConcurrentChangeError),
        ):
            await _service().confirm_data(
                owner, artifact.id, latest.id, ArtifactConsentCreate(fingerprint="e" * 64)
            )
        assert seen["written"] == {}

    async def test_a_version_no_longer_the_latest_is_a_conflict(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        older, latest = _version(artifact, number=1), _version(artifact, number=2)
        with (
            _stubs(artifact, latest=latest, served=older, owner=owner),
            pytest.raises(ConcurrentChangeError),
        ):
            await _service().confirm_data(
                owner, artifact.id, older.id, ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )

    async def test_a_version_not_kept_is_not_found(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        with (
            _stubs(artifact, latest=_version(artifact), owner=owner),
            pytest.raises(NotFoundError),
        ):
            await _service().confirm_data(
                owner, artifact.id, uuid.uuid4(), ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )

    async def test_a_version_reading_no_data_has_nothing_to_confirm(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        latest = _version(artifact, state=ConsentState.NOT_NEEDED, bound=False)
        latest.query_fingerprint = FINGERPRINT
        with _stubs(artifact, latest=latest, owner=owner), pytest.raises(BadRequestError):
            await _service().confirm_data(
                owner, artifact.id, latest.id, ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )

    @pytest.mark.security
    async def test_an_owner_who_can_no_longer_read_a_table_cannot_share_it(self) -> None:
        owner = _ctx()
        admin = _ctx(OrgRoleName.ADMIN, org=owner.organization_id)
        artifact = _artifact(owner)
        latest = _version(artifact)
        with (
            _stubs(artifact, latest=latest, owner=owner, owner_reads=False) as seen,
            pytest.raises(AuthorizationError, match="can't read 1 of the tables"),
        ):
            await _service().confirm_data(
                admin, artifact.id, latest.id, ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )
        assert seen["written"] == {}

    @pytest.mark.security
    async def test_a_page_whose_owner_left_cannot_be_confirmed(self) -> None:
        owner = _ctx()
        admin = _ctx(OrgRoleName.ADMIN, org=owner.organization_id)
        artifact = _artifact(owner)
        latest = _version(artifact)
        with (
            _stubs(artifact, latest=latest, owner=None, membership=None),
            pytest.raises(AuthorizationError, match="no longer an active member"),
        ):
            await _service().confirm_data(
                admin, artifact.id, latest.id, ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )

    async def test_confirming_a_consent_that_holds_changes_nothing(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        latest = _version(artifact, state=ConsentState.CONSENTED)
        with _stubs(artifact, latest=latest, served=latest, owner=owner) as seen:
            await _service().confirm_data(
                owner, artifact.id, latest.id, ArtifactConsentCreate(fingerprint=FINGERPRINT)
            )
        assert seen["written"] == {}
        seen["audit"].assert_not_awaited()


class TestWithdrawing:
    @pytest.mark.security
    async def test_any_editor_withdraws_every_consent_and_auto_consent_goes_off(self) -> None:
        owner = _ctx()
        editor = _ctx(org=owner.organization_id)
        artifact = _artifact(owner, auto_consent=True)
        consented = _version(artifact, state=ConsentState.CONSENTED)
        with _stubs(artifact, latest=consented, served=consented, owner=owner) as seen:
            detail = await _service().withdraw_consent(editor, artifact.id)
        assert seen["written"]["auto_consent"] is False
        assert artifact.consent_withdrawn_at is not None
        audit = seen["audit"].await_args.kwargs
        assert audit["action"] == "artifact.data_withdrawn"
        assert audit["details"] == {
            "audience_version": 2,
            "auto_consent_was_on": True,
            "edit_data_lowered": 2,
        }
        assert detail.consent is not None
        assert (detail.consent.state, detail.consent.shared) == ("withdrawn", False)

    @pytest.mark.security
    async def test_nobody_withdraws_on_somebody_s_behalf(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        with (
            _stubs(artifact, latest=_version(artifact), owner=owner) as seen,
            patch("app.services.artifact_consent.current_impersonator", return_value=uuid.uuid4()),
            pytest.raises(AuthorizationError),
        ):
            await _service().withdraw_consent(owner, artifact.id)
        assert seen["written"] == {}


class TestAutoConsent:
    async def test_the_owner_turns_it_on_having_confirmed_the_text(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        with _stubs(artifact, latest=_version(artifact), owner=owner) as seen:
            detail = await _service().set_auto_consent(
                owner,
                artifact.id,
                ArtifactAutoConsentUpdate(enabled=True, confirmed=AUTO_CONSENT_WORDING),
            )
        assert artifact.auto_consent is True
        audit = seen["audit"].await_args.kwargs
        assert audit["action"] == "artifact.auto_consent_changed"
        assert audit["details"] == {
            "enabled": True,
            "wording": AUTO_CONSENT_WORDING,
            "wording_text": AUTO_CONSENT_TEXTS[AUTO_CONSENT_WORDING],
        }
        assert detail.consent is not None
        assert detail.consent.auto_consent is True

    async def test_on_without_confirming_the_current_text_is_refused(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        with (
            _stubs(artifact, latest=_version(artifact), owner=owner),
            pytest.raises(BadRequestError) as refused,
        ):
            await _service().set_auto_consent(
                owner, artifact.id, ArtifactAutoConsentUpdate(enabled=True, confirmed="v0")
            )
        assert refused.value.details["fields"][0]["field"] == "confirmed"
        assert artifact.auto_consent is False

    @pytest.mark.security
    @pytest.mark.parametrize("role", [OrgRoleName.ADMIN, OrgRoleName.MEMBER])
    async def test_nobody_but_the_owner_turns_it_on(self, role: str) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        other = _ctx(role, org=owner.organization_id)
        with (
            _stubs(artifact, latest=_version(artifact), owner=owner),
            pytest.raises(AuthorizationError),
        ):
            await _service().set_auto_consent(
                other,
                artifact.id,
                ArtifactAutoConsentUpdate(enabled=True, confirmed=AUTO_CONSENT_WORDING),
            )

    @pytest.mark.security
    async def test_not_the_owner_impersonated(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        with (
            _stubs(artifact, latest=_version(artifact), owner=owner),
            patch("app.services.artifact_consent.current_impersonator", return_value=uuid.uuid4()),
            pytest.raises(AuthorizationError),
        ):
            await _service().set_auto_consent(
                owner,
                artifact.id,
                ArtifactAutoConsentUpdate(enabled=True, confirmed=AUTO_CONSENT_WORDING),
            )

    async def test_an_admin_turns_it_off_but_an_editor_may_not(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner, auto_consent=True)
        admin = _ctx(OrgRoleName.ADMIN, org=owner.organization_id)
        with _stubs(artifact, latest=_version(artifact), owner=owner) as seen:
            with pytest.raises(AuthorizationError):
                await _service().set_auto_consent(
                    _ctx(org=owner.organization_id),
                    artifact.id,
                    ArtifactAutoConsentUpdate(enabled=False),
                )
            await _service().set_auto_consent(
                admin, artifact.id, ArtifactAutoConsentUpdate(enabled=False)
            )
            await _service().set_auto_consent(
                admin, artifact.id, ArtifactAutoConsentUpdate(enabled=False)
            )
        assert artifact.auto_consent is False
        assert seen["audit"].await_count == 1


class TestTheDisclosure:
    async def test_it_says_the_query_the_tables_and_the_roles_that_open_every_page(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        latest = _version(artifact)
        with _stubs(artifact, latest=latest, owner=owner):
            disclosure = await _service().disclosure(owner, artifact.id, latest.id)
        assert disclosure.fingerprint == FINGERPRINT
        assert disclosure.bindings["deals"].table == "Deals"
        assert disclosure.parts["deals"].table == "Deals"
        assert disclosure.tables == ["Deals"]
        assert disclosure.roles == ["owner", "admin", "builder", "operator"]
        assert (disclosure.visibility, disclosure.problem) == ("org", None)
        assert (disclosure.people, disclosure.groups) == (["ann@example.com"], ["Sales"])

    async def test_an_admin_sees_the_words_beside_why_the_owner_cannot_share_them(self) -> None:
        owner = _ctx()
        admin = _ctx(OrgRoleName.ADMIN, org=owner.organization_id)
        artifact = _artifact(owner)
        latest = _version(artifact)
        with _stubs(artifact, latest=latest, owner=owner, owner_reads=False):
            disclosure = await _service().disclosure(admin, artifact.id, latest.id)
        assert disclosure.problem is not None
        assert disclosure.bindings["deals"].table == "Deals"

    async def test_with_the_owner_gone_it_says_so(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        artifact.owner_user_id = None
        admin = _ctx(OrgRoleName.ADMIN, org=owner.organization_id)
        latest = _version(artifact)
        with _stubs(artifact, latest=latest, owner=None, membership=None):
            disclosure = await _service().disclosure(admin, artifact.id, latest.id)
        assert disclosure.problem is not None
        assert "no longer an active member" in disclosure.problem
        assert disclosure.bindings == {}

    @pytest.mark.security
    async def test_an_editor_by_grant_is_not_shown_it(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        latest = _version(artifact)
        with _stubs(artifact, latest=latest, owner=owner), pytest.raises(AuthorizationError):
            await _service().disclosure(_ctx(org=owner.organization_id), artifact.id, latest.id)


class TestWhatTheAudienceOpens:
    @pytest.mark.security
    async def test_a_member_opens_the_consented_version_not_the_pending_one(self) -> None:
        owner = _ctx()
        member = _ctx(org=owner.organization_id)
        artifact = _artifact(owner)
        consented = _version(artifact, number=1, state=ConsentState.CONSENTED)
        pending = _version(artifact, number=2)
        with _stubs(artifact, latest=pending, served=consented, owner=owner, can_edit=False):
            view = await _service().view(member, artifact.id)
            detail = await _service().read(member, artifact.id)
            with pytest.raises(NotFoundError):
                await _service().view(member, artifact.id, version_id=pending.id)
            older = await _service().view(member, artifact.id, version_id=consented.id)
        assert (view.version.number, view.live) == (1, True)
        assert detail.current_version is not None
        assert detail.current_version.number == 1
        assert detail.consent is None
        assert older.version.number == 1

    async def test_an_older_version_the_audience_may_open_is_served_without_data(self) -> None:
        owner = _ctx()
        member = _ctx(org=owner.organization_id)
        artifact = _artifact(owner)
        older = _version(artifact, number=1, state=ConsentState.CONSENTED)
        served = _version(artifact, number=2, state=ConsentState.CONSENTED)
        with (
            _stubs(artifact, latest=served, served=served, owner=owner, can_edit=False),
            patch(f"{PATH}.artifact_repo.get_version", new=AsyncMock(return_value=older)),
        ):
            view = await _service().view(member, artifact.id, version_id=older.id)
        assert (view.version.number, view.live) == (1, False)

    @pytest.mark.security
    async def test_a_page_with_nothing_consented_is_not_available_yet(self) -> None:
        owner = _ctx()
        member = _ctx(org=owner.organization_id)
        artifact = _artifact(owner)
        with (
            _stubs(artifact, latest=_version(artifact), owner=owner, can_edit=False),
            pytest.raises(NotFoundError) as refused,
        ):
            await _service().view(member, artifact.id)
        assert refused.value.details["reason"] == "not_available_yet"

    @pytest.mark.security
    async def test_the_audience_s_history_holds_no_pending_version(self) -> None:
        owner = _ctx()
        member = _ctx(org=owner.organization_id)
        artifact = _artifact(owner, consent_withdrawn_at=datetime(2026, 10, 3, tzinfo=UTC))
        consented = _version(artifact, number=1, state=ConsentState.CONSENTED)
        pending = _version(artifact, number=2)
        with (
            _stubs(artifact, latest=pending, served=consented, owner=owner, can_edit=False),
            patch(
                f"{PATH}.artifact_repo.list_versions",
                new=AsyncMock(return_value=[pending, consented]),
            ),
        ):
            listed = await _service().versions(member, artifact.id)
        assert [(item.number, item.consent_state) for item in listed.items] == [(1, "withdrawn")]

    async def test_an_editor_sees_every_version_and_where_each_stands(self) -> None:
        owner = _ctx()
        editor = _ctx(org=owner.organization_id)
        artifact = _artifact(owner)
        consented = _version(artifact, number=1, state=ConsentState.CONSENTED)
        pending = _version(artifact, number=2)
        with (
            _stubs(artifact, latest=pending, served=consented, owner=owner),
            patch(
                f"{PATH}.artifact_repo.list_versions",
                new=AsyncMock(return_value=[pending, consented]),
            ),
        ):
            listed = await _service().versions(editor, artifact.id)
            detail = await _service().read(editor, artifact.id)
        assert [(item.number, item.consent_state) for item in listed.items] == [
            (2, "pending"),
            (1, "consented"),
        ]
        assert detail.consent is not None
        assert (detail.consent.audience_version, detail.consent.may_confirm) == (1, False)
        assert (detail.consent.may_withdraw, detail.consent.owner_name) == (True, "Olga Owner")

    async def test_the_owner_is_told_what_an_automatic_consent_added(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        latest = _version(artifact, state=ConsentState.CONSENTED)
        latest.consent_automatic = True
        with (
            _stubs(artifact, latest=latest, served=latest, owner=owner),
            patch(f"{PATH}.grown", new=AsyncMock(return_value=["+Deals"])),
        ):
            detail = await _service().read(owner, artifact.id)
        assert detail.consent is not None
        assert (detail.consent.automatic, detail.consent.grown) == (True, ["+Deals"])


class TestThePublicLinkPin:
    @pytest.mark.security
    async def test_a_version_waiting_for_consent_cannot_be_pinned(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        pending = _version(artifact)
        with _stubs(artifact, latest=pending, owner=owner), pytest.raises(BadRequestError) as no:
            await _service().update_public_link(
                owner, artifact.id, ArtifactPublicLinkUpdate(pinned_version_id=pending.id)
            )
        assert no.value.details["fields"][0]["field"] == "pinned_version_id"


class TestAPublishResult:
    async def test_a_pending_version_names_the_owner_and_what_the_audience_sees(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        pending = _version(artifact, number=3)
        with _stubs(artifact, latest=pending, served=_version(artifact, number=2), owner=owner):
            published = await artifacts._published(
                MagicMock(),
                artifact,
                pending,
                created=False,
                unchanged=False,
                bindings={},
                actions=[],
            )
        assert published.consent is ConsentState.PENDING
        assert (published.audience_version, published.owner_name) == (2, "Olga Owner")

    async def test_an_unbound_version_is_the_audience_s(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        plain = _version(artifact, state=ConsentState.NOT_NEEDED, bound=False)
        published = await artifacts._published(
            MagicMock(), artifact, plain, created=True, unchanged=False, bindings={}, actions=[]
        )
        assert (published.consent, published.audience_version) == (ConsentState.NOT_NEEDED, 2)

    async def test_a_consented_version_is_the_audience_s_and_waits_for_nobody(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        consented = _version(artifact, number=3, state=ConsentState.CONSENTED)
        with _stubs(artifact, latest=consented, owner=owner):
            published = await artifacts._published(
                MagicMock(),
                artifact,
                consented,
                created=False,
                unchanged=False,
                bindings={},
                actions=[],
            )
        assert published.consent is ConsentState.CONSENTED
        assert (published.audience_version, published.owner_name) == (3, None)
        assert _audience_note(published) is None

    def test_the_tool_result_names_the_owner_and_what_the_audience_still_sees(self) -> None:
        waiting = self._result(audience_version=2, owner_name="Olga Owner")
        assert _audience_note(waiting) == (
            "The audience still sees v2 until Olga Owner confirms this version's data in the "
            "console."
        )
        first = _audience_note(self._result(audience_version=None, owner_name=None))
        assert first is not None
        assert first.startswith("Only its owner, its editors and the roles that open every page")
        assert "(Owner, Admin, Builder, Operator)" in first
        assert first.endswith("until the page's owner confirms its data in the console.")

    @staticmethod
    def _result(**values: Any) -> artifacts.PublishedArtifact:
        return artifacts.PublishedArtifact(
            artifact_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            version_number=3,
            name="pipeline",
            title="Pipeline",
            created=False,
            unchanged=False,
            visibility="org",
            public=False,
            consent=ConsentState.PENDING,
            **values,
        )

    async def test_an_owner_less_page_names_nobody(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        artifact.owner_user_id = None
        assert await artifacts._owner_name(MagicMock(), artifact) is None
        with patch(f"{PATH}.user_repo.get_by_id", new=AsyncMock(return_value=None)):
            assert await artifacts._owner_name(MagicMock(), _artifact(owner)) is None


class TestWhatARunReadsBack:
    async def _served_to(
        self, artifact: Artifact, user_id: uuid.UUID | None, *, room: bool = False, **kw: Any
    ) -> Served:
        return await artifacts._served_to(MagicMock(), artifact, user_id, room=room)

    async def test_a_room_is_served_what_the_audience_is(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        consented = _version(artifact, number=1, state=ConsentState.CONSENTED)
        with _stubs(artifact, latest=_version(artifact), served=consented, owner=owner):
            served = await self._served_to(artifact, owner.user_id, room=True)
        assert served.version is consented

    async def test_the_owner_reads_the_latest(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        latest = _version(artifact)
        with _stubs(artifact, latest=latest, owner=owner):
            served = await self._served_to(artifact, owner.user_id)
        assert served.version is latest

    @pytest.mark.security
    async def test_a_member_who_left_is_served_what_the_audience_is(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner)
        with (
            _stubs(artifact, latest=_version(artifact), owner=owner),
            patch(f"{PATH}._member_auth", new=AsyncMock(return_value=None)),
        ):
            served = await self._served_to(artifact, uuid.uuid4())
        assert served.version is None

    async def test_an_editor_reads_the_latest_so_an_edit_lands_on_it(self) -> None:
        owner = _ctx()
        editor = _ctx(org=owner.organization_id)
        artifact = _artifact(owner)
        latest = _version(artifact)
        with (
            _stubs(artifact, latest=latest, owner=owner),
            patch(f"{PATH}._member_auth", new=AsyncMock(return_value=editor)),
        ):
            served = await self._served_to(artifact, editor.user_id)
        assert (served.version, served.data) == (latest, False)
