"""Browser teaching services without a database: the hold lease, the proposal text, and authority.

The recording and review paths that need Postgres are in
`tests/integration/test_browser_teaching_*.py`. These cover what a redis outage,
a stale hold, an unfinished review or a changed membership does to a recording.
"""

import hashlib
import uuid
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from redis.exceptions import RedisError

from app.core.audit import set_impersonator
from app.core.browser_teaching import (
    CapturedStep,
    ReviewedStep,
    StructuralTarget,
    TeachingReason,
    TeachingRefused,
)
from app.core.config import settings
from app.core.permissions import Perm
from app.db.models.agent_run import RunStatus, RunSurface
from app.services.browser_teaching import _access, _hold, _jobs, _propose

pytestmark = pytest.mark.anyio

ORG, USER, RUN, AGENT = (uuid.uuid4() for _ in range(4))
FINGERPRINT = "sha256:" + "a" * 64


class _Script:
    """A Redis whose `eval` honours the compare-and-act contract of the renew and release scripts."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.fail: Exception | None = None
        self.raw = self

    async def get(self, key: str) -> str | None:
        if self.fail:
            raise self.fail
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ttl: int, nx: bool) -> bool:
        if self.fail:
            raise self.fail
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def eval(self, script: str, _count: int, key: str, expected: str, *rest: object) -> int:
        if self.fail:
            raise self.fail
        if self.values.get(key) != expected:
            return 0
        if script == _hold._RELEASE:
            del self.values[key]
        return 1


def _hold_for(call_id: str = "call-1") -> _hold.Hold:
    return _hold.Hold(
        organization_id=ORG,
        run_id=RUN,
        agent_id=AGENT,
        user_id=USER,
        call_id=call_id,
        tab_id="main",
        hold_id=uuid.uuid4(),
    )


async def test_a_hold_is_claimed_once_renewed_by_its_owner_and_released_by_it() -> None:
    redis, hold = _Script(), _hold_for()
    assert await _hold.claim(cast(Any, redis), hold) is True
    assert await _hold.claim(cast(Any, redis), _hold_for()) is False
    assert await _hold.renew(cast(Any, redis), hold) is True
    assert await _hold.renew(cast(Any, redis), _hold_for()) is False
    assert await _hold.current(cast(Any, redis), RUN, "call-1") == hold
    await _hold.release(cast(Any, redis), _hold_for())
    assert await _hold.current(cast(Any, redis), RUN, "call-1") == hold
    await _hold.release(cast(Any, redis), hold)
    assert await _hold.current(cast(Any, redis), RUN, "call-1") is None


@pytest.mark.parametrize("failure", [RedisError("down"), OSError("reset"), TimeoutError()])
async def test_a_redis_outage_is_a_lost_hold_never_an_exception(failure: Exception) -> None:
    redis, hold = _Script(), _hold_for()
    redis.fail = failure
    assert await _hold.claim(cast(Any, redis), hold) is False
    assert await _hold.renew(cast(Any, redis), hold) is False
    assert await _hold.current(cast(Any, redis), RUN, "call-1") is None
    await _hold.release(cast(Any, redis), hold)


async def test_an_unreadable_or_foreign_hold_is_not_a_hold() -> None:
    redis, hold = _Script(), _hold_for()
    await _hold.claim(cast(Any, redis), hold)
    key = _hold._key(RUN, "call-1")
    redis.values[key] = "not json"
    assert await _hold.current(cast(Any, redis), RUN, "call-1") is None
    redis.values[key] = "x" * 3000
    assert await _hold.current(cast(Any, redis), RUN, "call-1") is None
    redis.values[key] = _hold_for("other-call").model_dump_json()
    assert await _hold.current(cast(Any, redis), RUN, "call-1") is None


async def test_the_proposal_job_builds_in_one_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    built = AsyncMock()
    seen: list[object] = []

    class _Context:
        async def __aenter__(self) -> str:
            return "db"

        async def __aexit__(self, *_: object) -> None:
            return None

    class _Service:
        def __init__(self, db: object, redis: object) -> None:
            seen.append((db, redis))

        build_proposal = built

    monkeypatch.setattr(_jobs, "get_db_context", _Context)
    monkeypatch.setattr(_jobs, "BrowserTeachingService", _Service)
    job = SimpleNamespace(organization_id=ORG, session_id=RUN, source_hash="h")
    await _jobs.build_teaching_proposal(cast(Any, job))
    assert seen == [("db", None)]
    built.assert_awaited_once_with(ORG, RUN, "h")


def _step(sequence: int, action: str, **fields: Any) -> CapturedStep:
    target = None
    if action in ("click", "select", "input_parameter"):
        target = StructuralTarget(role=fields.pop("role", "button"), fingerprint=FINGERPRINT)
    return CapturedStep(
        sequence=sequence,
        input_id=uuid.uuid4(),
        action=cast(Any, action),
        origin="https://portal.example.com",
        target=target,
        **fields,
    )


def _row(events: list[CapturedStep], review: list[ReviewedStep]) -> Any:
    return SimpleNamespace(
        id=uuid.UUID(int=7),
        allowed_origins=["https://portal.example.com"],
        sanitized_events=[event.model_dump(mode="json") for event in events],
        review=[step.model_dump(mode="json") for step in review],
    )


def test_a_review_naming_a_missing_step_or_a_parameter_on_a_plain_click_is_refused() -> None:
    events = (_step(1, "click"), _step(2, "input_parameter", role="textbox"))
    assert _propose.review_refusal(events, (ReviewedStep(sequence=2, parameter="invoice"),)) is None
    assert (
        _propose.review_refusal(events, (ReviewedStep(sequence=9, label="Save"),))
        is TeachingReason.REVIEW_UNKNOWN_STEP
    )
    assert (
        _propose.review_refusal(events, (ReviewedStep(sequence=1, parameter="invoice"),))
        is TeachingReason.REVIEW_UNKNOWN_STEP
    )
    human = (_step(1, "checkpoint", human_step=True),)
    assert (
        _propose.review_refusal(human, (ReviewedStep(sequence=1, parameter="code"),))
        is TeachingReason.REVIEW_UNKNOWN_STEP
    )


def test_a_proposal_needs_a_label_on_every_control_and_a_parameter_on_every_typed_input() -> None:
    click, typed = _step(1, "click"), _step(2, "input_parameter", role="textbox")
    human = _step(3, "checkpoint", human_step=True)
    labelled = {1: ReviewedStep(sequence=1, label="Save")}
    full = {**labelled, 2: ReviewedStep(sequence=2, label="Invoice", parameter="invoice")}
    unnamed = {**labelled, 2: ReviewedStep(sequence=2, label="Invoice")}
    assert _propose.proposal_refusal((), {}) is TeachingReason.REVIEW_INCOMPLETE
    assert _propose.proposal_refusal((click,), {}) is TeachingReason.REVIEW_INCOMPLETE
    assert _propose.proposal_refusal((click, typed), unnamed) is TeachingReason.REVIEW_INCOMPLETE
    assert _propose.proposal_refusal((click, typed), labelled) is TeachingReason.REVIEW_INCOMPLETE
    assert _propose.proposal_refusal((click, typed, human), full) is None


def test_the_source_hash_changes_with_the_review_and_the_name() -> None:
    events = [_step(1, "click"), _step(2, "scroll", direction="down")]
    plain = _row(events, [])
    labelled = _row(events, [ReviewedStep(sequence=1, label="Save")])
    assert _propose.source_hash(plain, "n") == _propose.source_hash(plain, "n")
    assert _propose.source_hash(plain, "n") != _propose.source_hash(plain, "m")
    assert _propose.source_hash(plain, "n") != _propose.source_hash(labelled, "n")
    assert len(_propose.source_hash(labelled, "n")) == len(hashlib.sha256().hexdigest())
    assert _propose.job_key(RUN, "d") == f"browser-teaching:{RUN}:d"


def test_the_rendered_procedure_names_origins_parameters_and_each_kind_of_step() -> None:
    events = [
        _step(1, "navigate"),
        _step(2, "navigate"),
        _step(3, "scroll", direction="up"),
        _step(4, "scroll", direction="down"),
        _step(5, "checkpoint"),
        _step(6, "checkpoint"),
        _step(7, "input_parameter", role="textbox"),
        _step(8, "select", role="combobox"),
        _step(9, "select", role="combobox"),
        _step(10, "click"),
        _step(11, "checkpoint", human_step=True),
    ]
    review = [
        ReviewedStep(sequence=2, label="Invoices"),
        ReviewedStep(sequence=4, label="the totals"),
        ReviewedStep(sequence=6, label="Total"),
        ReviewedStep(sequence=7, label="Invoice number", parameter="invoice_number"),
        ReviewedStep(sequence=8, label="Status", parameter="status"),
        ReviewedStep(sequence=9, label="Region"),
        ReviewedStep(sequence=10, label="Save"),
        ReviewedStep(sequence=11, label="Sign in"),
    ]
    description, body = _propose.render(_row(events, review), "Close invoice")
    assert description == "Reviewed browser procedure for https://portal.example.com"
    assert "- `invoice_number`\n- `status`" in body
    for line in (
        "1. Open a page on https://portal.example.com.",
        '2. Go to "Invoices" on https://portal.example.com.',
        "3. Scroll up.",
        '4. Scroll down to "the totals".',
        "5. Check that the page shows the expected state.",
        '6. Check that "Total" is shown.',
        '7. Enter `{invoice_number}` in "Invoice number" (textbox).',
        '8. Choose `{status}` in "Status" (combobox).',
        '9. Choose "Region" (combobox).',
        '10. Click "Save" (button).',
        '11. Stop and ask the person to complete "Sign in" themselves',
    ):
        assert line in body
    _, bare = _propose.render(_row([_step(1, "click")], []), "n")
    assert "## Parameters" not in bare
    assert "1. Click the step (button)." in bare


def _ctx(**fields: Any) -> Any:
    return SimpleNamespace(**{"personal_user_id": USER, "api_key_id": None, **fields})


@pytest.fixture
def no_impersonator() -> Iterator[None]:
    yield
    set_impersonator(None)


def test_only_a_signed_in_person_without_a_key_or_impersonation_may_teach(
    no_impersonator: None,
) -> None:
    assert _access.human_subject(_ctx()) == USER
    for ctx in (_ctx(personal_user_id=None), _ctx(api_key_id=uuid.uuid4())):
        with pytest.raises(TeachingRefused) as refused:
            _access.human_subject(ctx)
        assert refused.value.reason is TeachingReason.UNAVAILABLE
    set_impersonator(uuid.uuid4())
    with pytest.raises(TeachingRefused):
        _access.human_subject(_ctx())


def test_the_deployment_flag_is_narrowed_to_the_named_organizations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ENABLED", True)
    monkeypatch.setattr(settings, "BROWSER_TEACHING_ORGANIZATION_IDS", [ORG])
    _access.require_enabled(ORG)
    with pytest.raises(TeachingRefused) as refused:
        _access.require_enabled(uuid.uuid4())
    assert refused.value.reason is TeachingReason.DISABLED


def _run(**fields: Any) -> Any:
    base: dict[str, Any] = {
        "user_id": USER,
        "surface": RunSurface.WEB.value,
        "parent_run_id": None,
        "key_scopes": None,
        "trigger_id": None,
        "system_role": None,
        "initiated_by_publisher_fallback": False,
        "status": RunStatus.RUNNING.value,
        "agent_id": AGENT,
    }
    return SimpleNamespace(**{**base, **fields})


_EDITOR = SimpleNamespace(has=lambda perm: perm is Perm.SKILLS_EDIT)
_VIEWER = SimpleNamespace(has=lambda _perm: False)


def _world(
    monkeypatch: pytest.MonkeyPatch, *, run: Any, member: Any = _EDITOR, may_run: bool = True
) -> AsyncMock:
    monkeypatch.setattr(_access, "member_context", AsyncMock(return_value=member))
    monkeypatch.setattr(_access.run_repo, "get_run", AsyncMock(return_value=run))
    monkeypatch.setattr(_access, "_may_run_agent", AsyncMock(return_value=may_run))
    return AsyncMock()


@pytest.mark.parametrize(
    ("run", "member", "may_run", "reason"),
    [
        (_run(), None, True, TeachingReason.AUTHORITY_CHANGED),
        (_run(), _VIEWER, True, TeachingReason.AUTHORITY_CHANGED),
        (None, _EDITOR, True, TeachingReason.UNAVAILABLE),
        (_run(status=RunStatus.COMPLETED.value), _EDITOR, True, TeachingReason.UNAVAILABLE),
        (_run(user_id=uuid.uuid4()), _EDITOR, True, TeachingReason.UNAVAILABLE),
        (_run(trigger_id=uuid.uuid4()), _EDITOR, True, TeachingReason.UNAVAILABLE),
        (_run(), _EDITOR, False, TeachingReason.AUTHORITY_CHANGED),
    ],
)
async def test_recording_authority_is_refused_with_the_reason_that_changed(
    monkeypatch: pytest.MonkeyPatch, run: Any, member: Any, may_run: bool, reason: TeachingReason
) -> None:
    db = _world(monkeypatch, run=run, member=member, may_run=may_run)
    with pytest.raises(TeachingRefused) as refused:
        await _access.authority(db, ORG, USER, RUN)
    assert refused.value.reason is reason


async def test_a_running_personal_web_run_may_be_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run()
    db = _world(monkeypatch, run=run)
    assert await _access.authority(db, ORG, USER, RUN) is run
    db.refresh.assert_awaited_once_with(run)


@pytest.mark.parametrize(
    ("run", "member", "may_run"),
    [
        (_run(), None, True),
        (None, _EDITOR, True),
        (_run(agent_id=uuid.uuid4()), _EDITOR, True),
        (_run(surface=RunSurface.API.value), _EDITOR, True),
        (_run(), _EDITOR, False),
    ],
)
async def test_review_authority_is_refused_when_the_owner_lost_it(
    monkeypatch: pytest.MonkeyPatch, run: Any, member: Any, may_run: bool
) -> None:
    db = _world(monkeypatch, run=run, member=member, may_run=may_run)
    with pytest.raises(TeachingRefused) as refused:
        await _access.reviewer(db, ORG, USER, RUN, AGENT)
    assert refused.value.reason is TeachingReason.AUTHORITY_CHANGED


async def test_a_finished_run_may_still_be_reviewed_by_its_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _world(monkeypatch, run=_run(status=RunStatus.COMPLETED.value))
    member = await _access.reviewer(db, ORG, USER, RUN, AGENT)
    assert member.has(Perm.SKILLS_EDIT)
