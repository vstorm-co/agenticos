"""When a page's data may reach an anonymous visitor (#1975): the predicate, alone."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.artifact import Artifact, ArtifactVersion, ConsentState
from app.db.models.organization import Organization
from app.services.artifact_public_data import public_data_holds, public_data_not_holding

FINGERPRINT = "a" * 64
OWNER = uuid.uuid4()
NOW = datetime(2026, 10, 23, tzinfo=UTC)


def _page(**changes: object) -> Artifact:
    page = Artifact(
        id=uuid.uuid4(),
        public_data_fingerprint=FINGERPRINT,
        public_data_membership_id=OWNER,
        consent_withdrawn_at=None,
    )
    for name, value in changes.items():
        setattr(page, name, value)
    return page


def _version(**changes: object) -> ArtifactVersion:
    version = ArtifactVersion(
        id=uuid.uuid4(),
        number=1,
        bindings=[{"name": "orders"}],
        query_fingerprint=FINGERPRINT,
        consent_state=ConsentState.CONSENTED.value,
        consented_by_membership_id=OWNER,
        consented_at=NOW,
    )
    for name, value in changes.items():
        setattr(version, name, value)
    return version


def _org(on: bool = True) -> Organization:
    return Organization(public_live_data=on)


def test_it_holds_when_every_part_does() -> None:
    assert public_data_holds(_page(), _version(), OWNER, _org()) is True


@pytest.mark.security
@pytest.mark.parametrize(
    ("page", "version", "membership", "org"),
    [
        pytest.param(_page(), _version(), OWNER, _org(False), id="switch off"),
        pytest.param(_page(), None, OWNER, _org(), id="nothing served"),
        pytest.param(
            _page(public_data_fingerprint=None, public_data_membership_id=None),
            _version(),
            OWNER,
            _org(),
            id="no public consent",
        ),
        pytest.param(
            _page(), _version(query_fingerprint="b" * 64), OWNER, _org(), id="queries moved"
        ),
        pytest.param(_page(), _version(query_fingerprint=None), OWNER, _org(), id="no queries"),
        pytest.param(_page(), _version(), None, _org(), id="no owner membership"),
        pytest.param(_page(), _version(), uuid.uuid4(), _org(), id="another owner"),
        pytest.param(
            _page(), _version(consent_state=ConsentState.PENDING.value), OWNER, _org(), id="pending"
        ),
        pytest.param(
            _page(),
            _version(consented_by_membership_id=uuid.uuid4()),
            OWNER,
            _org(),
            id="members' consent given under another owner",
        ),
        pytest.param(
            _page(consent_withdrawn_at=NOW + timedelta(hours=1)),
            _version(),
            OWNER,
            _org(),
            id="members' consent withdrawn",
        ),
    ],
)
def test_any_missing_part_refuses(
    page: Artifact, version: ArtifactVersion | None, membership: uuid.UUID | None, org: Organization
) -> None:
    assert public_data_holds(page, version, membership, org) is False


def test_the_switch_is_the_only_part_it_takes_on_and_off_again() -> None:
    page, version, org = _page(), _version(), _org()
    outcomes = []
    for on in (True, False, True):
        org.public_live_data = on
        outcomes.append(public_data_holds(page, version, OWNER, org))
    assert outcomes == [True, False, True]


@pytest.mark.parametrize(
    ("page", "version", "membership", "org", "reason"),
    [
        pytest.param(_page(), _version(), OWNER, _org(), None, id="holds"),
        pytest.param(
            _page(public_data_fingerprint=None), _version(), OWNER, _org(False), None, id="nothing"
        ),
        pytest.param(_page(), _version(), OWNER, _org(False), "switch_off", id="switch"),
        pytest.param(_page(), None, OWNER, _org(), "no_served_version", id="no version"),
        pytest.param(
            _page(), _version(query_fingerprint="b" * 64), OWNER, _org(), "queries_changed", id="q"
        ),
        pytest.param(
            _page(), _version(query_fingerprint=None), OWNER, _org(), "queries_changed", id="none"
        ),
        pytest.param(_page(), _version(), None, _org(), "owner_gone", id="gone"),
        pytest.param(
            _page(), _version(), uuid.uuid4(), _org(), "owner_membership_changed", id="changed"
        ),
        pytest.param(
            _page(),
            _version(consent_state=ConsentState.PENDING.value),
            OWNER,
            _org(),
            "member_consent_missing",
            id="members",
        ),
        pytest.param(
            _page(public_expires_at=datetime(2020, 1, 1, tzinfo=UTC)),
            _version(),
            OWNER,
            _org(),
            "link_expired",
            id="expired",
        ),
        pytest.param(
            _page(public_expires_at=datetime(2999, 1, 1, tzinfo=UTC)),
            _version(),
            OWNER,
            _org(),
            None,
            id="later",
        ),
    ],
)
def test_it_names_the_first_gate_that_fails(
    page: Artifact,
    version: ArtifactVersion | None,
    membership: uuid.UUID | None,
    org: Organization,
    reason: str | None,
) -> None:
    assert public_data_not_holding(page, version, membership, org) == reason
    assert public_data_holds(page, version, membership, org) is (
        reason is None and page.public_data_fingerprint is not None
    )
