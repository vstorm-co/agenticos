"""Which version of a page each viewer is served, and the consent a version starts with.

The database is stubbed at the repository edge; `tests/integration/test_artifact_consent.py`
proves the same rules on real rows. What is pinned here is the decision itself: the
owner, editors and the roles that read every table get the latest version, everyone
else the newest consented one, and a consent holds only under the owner's membership
now and only until it is withdrawn.
"""

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit import current_impersonator, set_impersonator
from app.core.permissions import AuthContext, OrgRoleName, Perm
from app.db.models.artifact import Artifact, ArtifactVersion, ConsentState
from app.db.models.resource_grant import GrantLevel, Visibility
from app.schemas.artifact import ArtifactBinding, BindingReach
from app.schemas.virtual_table import ColumnDef
from app.services import artifact_consent as consent
from app.services.virtual_tables import TableSource

pytestmark = pytest.mark.anyio

PATH = "app.services.artifact_consent"
MEMBERSHIP = uuid.uuid4()
CONSENTED_AT = datetime(2026, 10, 10, tzinfo=UTC)


def _ctx(role: str = OrgRoleName.MEMBER, *, user_id: uuid.UUID | None = None) -> AuthContext:
    return AuthContext(user_id=user_id or uuid.uuid4(), organization_id=uuid.uuid4(), role=role)


def _artifact(owner: uuid.UUID | None = None, **values: Any) -> Artifact:
    return Artifact(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        owner_user_id=owner or uuid.uuid4(),
        visibility=Visibility.ORG.value,
        auto_consent=values.pop("auto_consent", False),
        consent_withdrawn_at=values.pop("consent_withdrawn_at", None),
        **values,
    )


def _binding(table_id: uuid.UUID, *columns: uuid.UUID) -> dict[str, Any]:
    return ArtifactBinding(
        name="deals",
        table_id=table_id,
        limit=10,
        fields={"stage": columns[0]},
        reach=BindingReach(tables={table_id: dict.fromkeys(columns, 0)}),
    ).model_dump(mode="json")


def _version(
    artifact: Artifact,
    *,
    number: int = 1,
    state: ConsentState = ConsentState.PENDING,
    bound: bool = True,
    membership: uuid.UUID | None = MEMBERSHIP,
    bindings: list[dict[str, Any]] | None = None,
) -> ArtifactVersion:
    consented = state == ConsentState.CONSENTED
    return ArtifactVersion(
        id=uuid.uuid4(),
        artifact_id=artifact.id,
        number=number,
        bindings=bindings or ([_binding(uuid.uuid4(), uuid.uuid4())] if bound else []),
        consent_state=state.value,
        query_fingerprint="f" * 64 if bound else None,
        consented_at=CONSENTED_AT if consented else None,
        consented_by_membership_id=membership if consented else None,
        consent_automatic=False,
    )


def _owner_is(membership: uuid.UUID | None) -> Any:
    return patch(
        f"{PATH}.member_repo.get_active",
        new=AsyncMock(return_value=MagicMock(id=membership) if membership else None),
    )


class TestAConsentHolds:
    def test_under_the_owner_s_membership_and_never_withdrawn(self) -> None:
        artifact = _artifact()
        version = _version(artifact, state=ConsentState.CONSENTED)
        assert consent.consent_holds(version, artifact, MEMBERSHIP)
        assert consent.shown_state(version, artifact, MEMBERSHIP) is ConsentState.CONSENTED

    @pytest.mark.security
    def test_not_under_a_membership_the_owner_no_longer_holds(self) -> None:
        """A removed and re-invited owner is a new membership: old consents stay void."""
        artifact = _artifact()
        version = _version(artifact, state=ConsentState.CONSENTED)
        assert not consent.consent_holds(version, artifact, uuid.uuid4())
        assert not consent.consent_holds(version, artifact, None)
        assert consent.shown_state(version, artifact, None) is ConsentState.WITHDRAWN

    @pytest.mark.security
    def test_not_once_withdrawn_but_a_consent_given_after_the_withdrawal_does(self) -> None:
        artifact = _artifact(consent_withdrawn_at=CONSENTED_AT)
        before = _version(artifact, state=ConsentState.CONSENTED)
        after = _version(artifact, state=ConsentState.CONSENTED)
        after.consented_at = datetime(2026, 10, 11, tzinfo=UTC)
        assert not consent.consent_holds(before, artifact, MEMBERSHIP)
        assert consent.consent_holds(after, artifact, MEMBERSHIP)

    def test_a_pending_version_holds_none_and_reads_as_pending(self) -> None:
        artifact = _artifact()
        version = _version(artifact)
        assert not consent.consent_holds(version, artifact, MEMBERSHIP)
        assert consent.shown_state(version, artifact, MEMBERSHIP) is ConsentState.PENDING


class TestWhoMayConfirm:
    def test_the_owner_and_an_admin_each_as_themselves(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner.user_id)
        assert consent.may_confirm(owner, artifact)
        assert consent.may_confirm(_ctx(OrgRoleName.ADMIN), artifact)
        assert consent.may_confirm(_ctx(OrgRoleName.OWNER), artifact)

    @pytest.mark.security
    def test_not_an_editor_by_grant_nor_a_builder(self) -> None:
        artifact = _artifact()
        assert not consent.may_confirm(_ctx(OrgRoleName.MEMBER), artifact)
        assert not consent.may_confirm(_ctx(OrgRoleName.BUILDER), artifact)

    @pytest.mark.security
    def test_not_an_owner_being_impersonated(self) -> None:
        owner = _ctx()
        with patch(f"{PATH}.current_impersonator", return_value=uuid.uuid4()):
            assert not consent.may_confirm(owner, _artifact(owner.user_id))
            assert not consent.as_themselves(owner)

    @pytest.mark.security
    @pytest.mark.parametrize("role", [OrgRoleName.MEMBER, OrgRoleName.ADMIN, OrgRoleName.OWNER])
    def test_an_owners_key_cannot_consent_even_with_edit_scope(self, role: str) -> None:
        ctx = replace(
            _ctx(role),
            api_key_id=uuid.uuid4(),
            key_scopes=frozenset({Perm.ARTIFACTS_VIEW, Perm.ARTIFACTS_EDIT}),
        )
        artifact = _artifact(ctx.user_id)
        assert not consent.as_themselves(ctx)
        assert not consent.may_confirm(ctx, artifact)
        assert not consent.may_grant_edit_data(ctx, artifact)

    def test_not_nobody(self) -> None:
        assert not consent.as_themselves(AuthContext.anonymous(uuid.uuid4()))


class TestWhichVersionIsServed:
    async def _served(
        self,
        ctx: AuthContext | None,
        artifact: Artifact,
        *,
        latest: ArtifactVersion | None,
        audience: ArtifactVersion | None,
        can_edit: bool = False,
        membership: uuid.UUID | None = MEMBERSHIP,
    ) -> consent.Served:
        with (
            patch(f"{PATH}.artifact_repo.latest_version", new=AsyncMock(return_value=latest)),
            patch(f"{PATH}.artifact_repo.latest_served", new=AsyncMock(return_value=audience)),
            _owner_is(membership),
        ):
            return await consent.served(MagicMock(), ctx, artifact, can_edit=can_edit)

    async def test_the_owner_gets_the_latest_with_its_data_whatever_its_consent(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner.user_id)
        latest = _version(artifact, number=2)
        served = await self._served(owner, artifact, latest=latest, audience=None)
        assert (served.version, served.data, served.latest) == (latest, True, True)

    @pytest.mark.parametrize("role", [OrgRoleName.BUILDER, OrgRoleName.OPERATOR, OrgRoleName.ADMIN])
    async def test_a_role_that_reads_every_table_gets_the_latest_with_its_data(
        self, role: str
    ) -> None:
        artifact = _artifact()
        latest = _version(artifact, number=2)
        served = await self._served(_ctx(role), artifact, latest=latest, audience=None)
        assert (served.version, served.data) == (latest, True)

    @pytest.mark.security
    async def test_an_editor_gets_the_latest_but_its_data_only_once_consented(self) -> None:
        artifact = _artifact()
        pending = _version(artifact, number=2)
        consented = _version(artifact, number=2, state=ConsentState.CONSENTED)
        waiting = await self._served(_ctx(), artifact, latest=pending, audience=None, can_edit=True)
        shared = await self._served(
            _ctx(), artifact, latest=consented, audience=consented, can_edit=True
        )
        assert (waiting.version, waiting.data, waiting.latest) == (pending, False, True)
        assert (shared.version, shared.data) == (consented, True)

    @pytest.mark.security
    async def test_the_audience_gets_the_newest_consented_version_not_the_pending_one(
        self,
    ) -> None:
        artifact = _artifact()
        latest = _version(artifact, number=3)
        consented = _version(artifact, number=2, state=ConsentState.CONSENTED)
        served = await self._served(_ctx(), artifact, latest=latest, audience=consented)
        assert (served.version, served.data, served.latest) == (consented, True, False)

    @pytest.mark.security
    async def test_the_audience_keeps_the_page_but_not_the_data_once_withdrawn(self) -> None:
        """Never an older version's data: the newest consented page, awaiting consent."""
        artifact = _artifact(consent_withdrawn_at=datetime(2026, 10, 12, tzinfo=UTC))
        consented = _version(artifact, number=2, state=ConsentState.CONSENTED)
        served = await self._served(None, artifact, latest=None, audience=consented)
        assert (served.version, served.data) == (consented, False)

    async def test_an_unbound_version_needs_no_consent(self) -> None:
        artifact = _artifact()
        plain = _version(artifact, state=ConsentState.NOT_NEEDED, bound=False)
        served = await self._served(None, artifact, latest=None, audience=plain, membership=None)
        assert (served.version, served.data) == (plain, True)
        editor = await self._served(_ctx(), artifact, latest=plain, audience=plain, can_edit=True)
        assert editor.data is True

    async def test_nothing_consented_is_nothing_served_to_the_audience(self) -> None:
        artifact = _artifact()
        served = await self._served(_ctx(), artifact, latest=_version(artifact), audience=None)
        assert (served.version, served.data, served.latest) == (None, False, False)


class TestServedToAListing:
    async def test_one_grant_query_for_a_page_of_artifacts(self) -> None:
        member = _ctx()
        mine = _artifact(member.user_id)
        granted, other = _artifact(), _artifact()
        latest = {page.id: _version(page, number=5) for page in (mine, granted)}
        served = {other.id: _version(other, number=2, state=ConsentState.CONSENTED)}
        with (
            patch(f"{PATH}.accessible_ids", new=AsyncMock(return_value={granted.id})) as accessible,
            patch(
                f"{PATH}.artifact_repo.latest_versions", new=AsyncMock(return_value=dict(latest))
            ) as newest,
            patch(
                f"{PATH}.artifact_repo.latest_served_versions",
                new=AsyncMock(return_value=dict(served)),
            ) as consented,
        ):
            found = await consent.served_many(MagicMock(), member, [mine, granted, other])
        accessible.assert_awaited_once()
        assert sorted(newest.await_args.args[1]) == sorted([mine.id, granted.id])
        assert consented.await_args.args[1] == [other.id]
        assert {key: version.number for key, version in found.items()} == {
            mine.id: 5,
            granted.id: 5,
            other.id: 2,
        }

    async def test_a_role_that_reads_every_table_lists_every_latest_version(self) -> None:
        pages = [_artifact(), _artifact()]
        with (
            patch(f"{PATH}.accessible_ids", new=AsyncMock()) as accessible,
            patch(f"{PATH}.artifact_repo.latest_versions", new=AsyncMock(return_value={})),
            patch(f"{PATH}.artifact_repo.latest_served_versions", new=AsyncMock()) as served,
        ):
            await consent.served_many(MagicMock(), _ctx(OrgRoleName.BUILDER), pages)
        accessible.assert_not_awaited()
        served.assert_not_awaited()

    async def test_a_room_lists_what_the_audience_is_served(self) -> None:
        pages = [_artifact()]
        with (
            patch(f"{PATH}.artifact_repo.latest_versions", new=AsyncMock()) as newest,
            patch(f"{PATH}.artifact_repo.latest_served_versions", new=AsyncMock(return_value={})),
        ):
            assert await consent.served_many(MagicMock(), None, pages) == {}
        newest.assert_not_awaited()

    async def test_an_empty_page_asks_nothing(self) -> None:
        assert await consent.served_many(MagicMock(), _ctx(), []) == {}


class TestTheHistoryAViewerMayOpen:
    def test_the_audience_sees_served_versions_up_to_its_own(self) -> None:
        artifact = _artifact()
        v1 = _version(artifact, number=1, state=ConsentState.NOT_NEEDED, bound=False)
        v2 = _version(artifact, number=2, state=ConsentState.CONSENTED)
        v3 = _version(artifact, number=3, state=ConsentState.DECLINED)
        v4 = _version(artifact, number=4, state=ConsentState.CONSENTED)
        v5 = _version(artifact, number=5)
        view = consent.Served(version=v2, data=True, latest=False)
        assert consent.visible_versions(view, [v5, v4, v3, v2, v1]) == [v2, v1]

    def test_one_served_the_latest_sees_all_and_one_served_nothing_none(self) -> None:
        artifact = _artifact()
        versions = [_version(artifact, number=2), _version(artifact, number=1)]
        latest = consent.Served(version=versions[0], data=False, latest=True)
        nothing = consent.Served(version=None, data=False, latest=False)
        assert consent.visible_versions(latest, versions) == versions
        assert consent.visible_versions(nothing, versions) == []


class TestTheConsentAVersionStartsWith:
    async def _decide(
        self,
        artifact: Artifact,
        *,
        fingerprint: str | None,
        person: AuthContext | None,
        prior: ArtifactVersion | None = None,
        membership: uuid.UUID | None = MEMBERSHIP,
        grant: GrantLevel | None = None,
        impersonated: bool = False,
    ) -> consent.VersionConsent:
        with (
            _owner_is(membership),
            patch(f"{PATH}.artifact_repo.latest_consent", new=AsyncMock(return_value=prior)),
            patch(f"{PATH}.resource_grant_repo.get_level", new=AsyncMock(return_value=grant)),
        ):
            return await consent.consent_for(
                MagicMock(),
                artifact,
                fingerprint=fingerprint,
                person=person,
                impersonated=impersonated,
            )

    async def test_an_unbound_version_needs_none_and_names_who_published_it(self) -> None:
        person = _ctx()
        decided = await self._decide(_artifact(), fingerprint=None, person=person)
        assert decided.consent_state is ConsentState.NOT_NEEDED
        assert decided.columns()["published_by_user_id"] == person.user_id
        assert decided.columns()["published_by_membership_id"] == MEMBERSHIP

    async def test_an_edit_data_holder_s_changed_queries_are_consented_via_their_grant(
        self,
    ) -> None:
        person = _ctx()
        decided = await self._decide(
            _artifact(), fingerprint="e" * 64, person=person, grant=GrantLevel.EDIT_DATA
        )
        assert decided.consent_state is ConsentState.CONSENTED
        assert decided.consent_automatic is True
        assert decided.consent_via_grant == person.user_id
        assert decided.consented_by_membership_id == MEMBERSHIP
        assert decided.columns()["consent_via_grant"] == person.user_id

    @pytest.mark.security
    @pytest.mark.parametrize("grant", [None, GrantLevel.EDIT])
    async def test_a_plain_editor_s_changed_queries_wait(self, grant: GrantLevel | None) -> None:
        decided = await self._decide(_artifact(), fingerprint="e" * 64, person=_ctx(), grant=grant)
        assert (decided.consent_state, decided.consent_via_grant) == (ConsentState.PENDING, None)

    @pytest.mark.security
    async def test_an_impersonated_holder_s_changed_queries_wait(self) -> None:
        set_impersonator(uuid.uuid4())
        try:
            decided = await self._decide(
                _artifact(), fingerprint="e" * 64, person=_ctx(), grant=GrantLevel.EDIT_DATA
            )
        finally:
            set_impersonator(None)
        assert decided.consent_state is ConsentState.PENDING

    @pytest.mark.security
    async def test_a_holder_s_changed_queries_wait_when_the_run_started_impersonating(
        self,
    ) -> None:
        """The request that knew is gone when a spawned task, a worker or a resumed approval
        publishes: the run carries it, and nothing ambient says otherwise."""
        assert current_impersonator() is None
        decided = await self._decide(
            _artifact(),
            fingerprint="e" * 64,
            person=_ctx(),
            grant=GrantLevel.EDIT_DATA,
            impersonated=True,
        )
        assert (decided.consent_state, decided.consent_via_grant) == (ConsentState.PENDING, None)

    async def test_the_same_page_queries_as_a_consent_that_holds_are_consented(self) -> None:
        artifact = _artifact()
        prior = _version(artifact, state=ConsentState.CONSENTED)
        decided = await self._decide(artifact, fingerprint="f" * 64, person=_ctx(), prior=prior)
        assert decided.consent_state is ConsentState.CONSENTED
        assert decided.consent_automatic is True
        assert decided.consented_by_membership_id == MEMBERSHIP
        assert decided.consented_at is not None

    async def test_changed_page_queries_wait_for_the_owner(self) -> None:
        artifact = _artifact()
        prior = _version(artifact, state=ConsentState.CONSENTED)
        decided = await self._decide(artifact, fingerprint="e" * 64, person=_ctx(), prior=prior)
        assert decided.consent_state is ConsentState.PENDING
        assert decided.columns()["consented_by_membership_id"] is None

    async def test_the_owner_s_own_run_with_auto_consent_on_is_consented(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner.user_id, auto_consent=True)
        decided = await self._decide(artifact, fingerprint="e" * 64, person=owner)
        assert (decided.consent_state, decided.consent_automatic) == (ConsentState.CONSENTED, True)

    @pytest.mark.security
    async def test_auto_consent_is_the_run_s_person_never_the_stand_in(self) -> None:
        """A widget run passes the owner as `owner_user_id`, but nobody is behind it."""
        artifact = _artifact(auto_consent=True)
        anonymous = await self._decide(artifact, fingerprint="e" * 64, person=None)
        editor = await self._decide(artifact, fingerprint="e" * 64, person=_ctx())
        assert anonymous.consent_state is ConsentState.PENDING
        assert anonymous.columns()["published_by_user_id"] is None
        assert editor.consent_state is ConsentState.PENDING

    @pytest.mark.security
    async def test_auto_consent_is_not_the_owner_impersonated(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner.user_id, auto_consent=True)
        with patch(f"{PATH}.current_impersonator", return_value=uuid.uuid4()):
            decided = await self._decide(artifact, fingerprint="e" * 64, person=owner)
        assert decided.consent_state is ConsentState.PENDING

    @pytest.mark.security
    async def test_auto_consent_is_not_the_owner_s_run_that_started_impersonating(self) -> None:
        owner = _ctx()
        artifact = _artifact(owner.user_id, auto_consent=True)
        assert current_impersonator() is None
        decided = await self._decide(
            artifact, fingerprint="e" * 64, person=owner, impersonated=True
        )
        assert (decided.consent_state, decided.consent_automatic) == (ConsentState.PENDING, False)

    @pytest.mark.security
    async def test_queries_the_owner_already_confirmed_stay_consented_under_impersonation(
        self,
    ) -> None:
        """Consent covers the queries, not the person who republished them (design I3)."""
        artifact = _artifact()
        prior = _version(artifact, state=ConsentState.CONSENTED)
        decided = await self._decide(
            artifact, fingerprint="f" * 64, person=_ctx(), prior=prior, impersonated=True
        )
        assert decided.consent_state is ConsentState.CONSENTED

    async def test_a_page_whose_owner_is_gone_waits(self) -> None:
        artifact = _artifact(auto_consent=True)
        decided = await self._decide(artifact, fingerprint="e" * 64, person=None, membership=None)
        assert decided.consent_state is ConsentState.PENDING

    async def test_an_owner_less_page_has_no_owner_membership(self) -> None:
        artifact = _artifact()
        artifact.owner_user_id = None
        assert await consent.owner_membership_id(MagicMock(), artifact) is None


class TestWhatAnAutomaticConsentAdded:
    async def test_new_tables_and_new_columns_by_name(self) -> None:
        artifact = _artifact()
        deals, people = uuid.uuid4(), uuid.uuid4()
        stage, amount, salary = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        before = _version(
            artifact, number=1, state=ConsentState.CONSENTED, bindings=[_binding(deals, stage)]
        )
        now = _version(
            artifact,
            number=2,
            state=ConsentState.CONSENTED,
            bindings=[
                _binding(deals, stage, amount),
                {**_binding(people, salary), "name": "people"},
            ],
        )
        tables = {
            deals: TableSource(
                id=deals,
                name="Deals",
                archived=False,
                columns=[
                    ColumnDef(id=stage, label="Stage", type="text"),
                    ColumnDef(id=amount, label="Amount", type="number"),
                ],
            ),
            people: TableSource(
                id=people,
                name="People",
                archived=False,
                columns=[ColumnDef(id=salary, label="Salary", type="number")],
            ),
        }

        async def table_source(_self: Any, _ctx: Any, table_id: uuid.UUID) -> TableSource:
            return tables[table_id]

        with (
            patch(f"{PATH}.artifact_repo.served_before", new=AsyncMock(return_value=before)),
            patch(f"{PATH}.VirtualTableService.table_source", new=table_source),
        ):
            added = await consent.grown(MagicMock(), _ctx(), artifact, now)
        assert sorted(added) == ["+Amount", "+People"]

    async def test_a_first_version_adds_everything_and_unreadable_tables_are_left_out(
        self,
    ) -> None:
        from app.core.exceptions import NotFoundError

        artifact = _artifact()
        now = _version(artifact, number=1, state=ConsentState.CONSENTED)

        async def table_source(_self: Any, _ctx: Any, table_id: uuid.UUID) -> TableSource:
            raise NotFoundError(message="gone", details={"table_id": table_id})

        with (
            patch(f"{PATH}.artifact_repo.served_before", new=AsyncMock(return_value=None)),
            patch(f"{PATH}.VirtualTableService.table_source", new=table_source),
        ):
            assert await consent.grown(MagicMock(), _ctx(), artifact, now) == []


def test_the_roles_that_open_every_page_are_named_by_the_catalog() -> None:
    assert consent.PAGE_ROLES == ("owner", "admin", "builder", "operator")


def test_the_consoles_english_wording_is_the_one_the_audit_records() -> None:
    """The text a person confirms in the console is the one the audit entry keeps."""
    messages = json.loads(
        (Path(__file__).parents[2] / "frontend" / "messages" / "en.json").read_text("utf-8")
    )
    assert (
        messages["artifacts"]["consent"]["autoConsentConfirm"]
        == consent.AUTO_CONSENT_TEXTS[consent.AUTO_CONSENT_WORDING]
    )


def test_the_consoles_english_edit_data_wording_is_the_one_the_audit_records() -> None:
    messages = json.loads(
        (Path(__file__).parents[2] / "frontend" / "messages" / "en.json").read_text("utf-8")
    )["sharing"]
    for key, wording in (
        ("editDataConfirmPerson", consent.EDIT_DATA_PERSON_WORDING),
        ("editDataConfirmGroup", consent.EDIT_DATA_GROUP_WORDING),
    ):
        assert messages[key] == consent.EDIT_DATA_TEXTS[wording]


def test_retired_wording_ids_still_resolve_but_are_not_the_current_ones() -> None:
    """An audit row that names `v1` must still be readable; only `v2` is offered."""
    for old, current in (
        ("auto_consent.v1", consent.AUTO_CONSENT_WORDING),
        ("edit_data.person.v1", consent.EDIT_DATA_PERSON_WORDING),
        ("edit_data.group.v1", consent.EDIT_DATA_GROUP_WORDING),
    ):
        texts = consent.AUTO_CONSENT_TEXTS if old.startswith("auto") else consent.EDIT_DATA_TEXTS
        assert old in texts
        assert old != current
        assert texts[old] != texts[current]
