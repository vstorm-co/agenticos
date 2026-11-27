"""A routine's source ceiling: what passes within it, what stops the routine, and what a trusting one grows into.

See `docs/design/routine-access.md#when-a-review-goes-stale-reviewed`. The
database-backed admission paths are in `tests/integration/`.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from app.core.permissions import AuthContext
from app.db.models.agent_trigger import AgentTrigger
from app.schemas.routine_sources import RoutineSourceAccount, RoutineSourceItem, RoutineSourcePolicy
from app.schemas.routine_tool_keys import RoutineCapabilityToolSetting
from app.services import routine_sources
from app.services.routine_sources import (
    RoutineSourceService,
    RoutineSourceSnapshot,
    RoutineSourcesRequired,
    RoutineTrustRefused,
    _grown,
    _same_account,
    _trusted,
    _within_behavior,
    _within_ceiling,
    activation_intent,
    ceiling_of,
    routine_intent,
    source_scope,
    stored_review,
    trust_blocked,
)

pytestmark = [pytest.mark.anyio, pytest.mark.security]

ALLOW = RoutineCapabilityToolSetting(capability_id="sandbox", tool_id="execute", setting="allow")


def _policy(**update: object) -> RoutineSourcePolicy:
    return RoutineSourcePolicy(
        id=uuid4(),
        consented_by=uuid4(),
        reviewed_at=datetime.now(UTC),
        version_id=uuid4(),
        scope_hash="a" * 64,
        spec_hash="b" * 64,
        behavior={"capability:sandbox": "c" * 64},
    ).model_copy(update=update)


def _account(**update: object) -> RoutineSourceAccount:
    return RoutineSourceAccount(
        endpoint_hash="d" * 64,
        authorization_generation=uuid4(),
        tool_ids=("list_issues", "create_issue"),
    ).model_copy(update=update)


def _snapshot(policy: RoutineSourcePolicy, **fields: object) -> RoutineSourceSnapshot:
    return RoutineSourceSnapshot(
        **{"policy": policy, "accounts": [], "unavailable": [], "resources": [], **fields}
    )


def _trigger(**fields: object) -> AgentTrigger:
    return AgentTrigger(
        **{
            "agent_id": uuid4(),
            "organization_id": uuid4(),
            "created_by_user_id": uuid4(),
            "trigger_type": "schedule",
            "prompt": "Summarize the week",
            "result_mode": "report",
            "runs_as_creator": False,
            **fields,
        }
    )


@pytest.mark.parametrize(
    ("change", "same"),
    [
        ("nothing", True),
        ("reconnected_as_itself", True),
        ("reconnected_as_someone_else", False),
        ("reconnected_unknown", False),
        ("approved_unknown", False),
        ("other_endpoint", False),
        ("other_prefix", False),
    ],
)
def test_only_the_reviewed_account_at_the_reviewed_endpoint_passes(change: str, same: bool) -> None:
    approved = _account(account="ops@example.com")
    if change == "approved_unknown":
        approved = approved.model_copy(update={"account": None})
    current = {
        "nothing": approved,
        "reconnected_as_itself": approved.model_copy(update={"authorization_generation": uuid4()}),
        "reconnected_as_someone_else": approved.model_copy(
            update={"authorization_generation": uuid4(), "account": "intruder@example.com"}
        ),
        "reconnected_unknown": approved.model_copy(
            update={"authorization_generation": uuid4(), "account": None}
        ),
        "approved_unknown": approved.model_copy(update={"authorization_generation": uuid4()}),
        "other_endpoint": approved.model_copy(update={"endpoint_hash": "e" * 64}),
        "other_prefix": approved.model_copy(update={"tool_prefix": "gh"}),
    }[change]
    assert _same_account(current, approved) is same


@pytest.mark.parametrize(
    ("spec_hash", "compatible", "within"),
    [
        ("b" * 64, frozenset(), True),
        ("f" * 64, frozenset({"b" * 64}), True),
        ("f" * 64, frozenset(), False),
    ],
)
def test_a_review_saved_before_behavior_compares_its_spec(
    spec_hash: str, compatible: frozenset[str], within: bool
) -> None:
    approved = _policy(behavior=None)
    current = _policy(spec_hash=spec_hash, behavior={"capability:sandbox": "c" * 64})
    assert (
        _within_ceiling(current, approved, _snapshot(current, compatible_spec_hashes=compatible))
        is within
    )


def test_behavior_passes_when_removed_or_compatible_and_stops_when_it_grows_or_changes() -> None:
    approved = _policy(behavior={"capability:sandbox": "c" * 64, "skill:x": "c" * 64})
    within = lambda behavior, **fields: _within_ceiling(  # noqa: E731
        _policy(behavior=behavior), approved, _snapshot(approved, **fields)
    )
    assert within({"capability:sandbox": "c" * 64})
    assert not within({"capability:sandbox": "c" * 64, "capability:web": "c" * 64})
    assert not within({"capability:sandbox": "9" * 64})
    assert within(
        {"capability:sandbox": "9" * 64},
        compatible_behavior={"capability:sandbox": frozenset({"c" * 64})},
    )
    assert not _within_ceiling(_policy(behavior=None), approved, _snapshot(approved))


@pytest.mark.parametrize(
    "field",
    ["mirage_accounts", "secret_sources", "channel_sources", "phone_sources", "external_sources"],
)
def test_a_new_or_changed_keyed_source_stops_the_routine_and_a_removed_one_passes(
    field: str,
) -> None:
    key = uuid4()
    value: object = uuid4() if field in {"mirage_accounts", "secret_sources"} else "e" * 64
    other: object = uuid4() if field in {"mirage_accounts", "secret_sources"} else "f" * 64
    approved = _policy(**{field: {key: value}})
    assert _within_ceiling(_policy(**{field: {key: value}}), approved, _snapshot(approved))
    assert _within_ceiling(_policy(), approved, _snapshot(approved))
    assert not _within_ceiling(_policy(**{field: {key: other}}), approved, _snapshot(approved))
    assert not _within_ceiling(_policy(**{field: {uuid4(): value}}), approved, _snapshot(approved))


def test_an_mcp_account_passes_within_its_reviewed_tools_only() -> None:
    key = uuid4()
    reviewed = _account()
    approved = _policy(mcp_sources={key: reviewed}, root_mcp_ids=(key,))
    within = lambda current: _within_ceiling(current, approved, _snapshot(approved))  # noqa: E731
    assert within(
        _policy(
            mcp_sources={key: reviewed.model_copy(update={"tool_ids": ("list_issues",)})},
            root_mcp_ids=(key,),
        )
    )
    assert within(_policy())
    assert not within(
        _policy(
            mcp_sources={
                key: reviewed.model_copy(update={"tool_ids": (*reviewed.tool_ids, "delete_repo")})
            }
        )
    )
    assert not within(_policy(mcp_sources={uuid4(): reviewed}))
    assert not within(
        _policy(
            mcp_sources={key: reviewed.model_copy(update={"authorization_generation": uuid4()})}
        )
    )
    assert not within(_policy(mcp_sources={key: reviewed}, root_mcp_ids=(key, uuid4())))


def test_an_event_routines_input_account_must_be_the_reviewed_one() -> None:
    connection = uuid4()
    source = _account()
    approved = _policy(input_connection_id=connection, input_source=source)
    within = lambda current: _within_ceiling(current, approved, _snapshot(approved))  # noqa: E731
    assert within(_policy(input_connection_id=connection, input_source=source))
    assert not within(_policy(input_connection_id=uuid4(), input_source=source))
    assert not within(
        _policy(
            input_connection_id=connection,
            input_source=source.model_copy(update={"authorization_generation": uuid4()}),
        )
    )
    unreviewed = _policy()
    assert not _within_ceiling(
        _policy(input_connection_id=None, input_source=None).model_copy(
            update={"input_source": source}
        ),
        unreviewed,
        _snapshot(unreviewed),
    )


def test_the_project_workspace_must_be_the_reviewed_one() -> None:
    project = uuid4()
    approved = _policy(project_id=project, project_hash="e" * 64)
    assert _within_ceiling(
        _policy(project_id=project, project_hash="e" * 64), approved, _snapshot(approved)
    )
    assert not _within_ceiling(
        _policy(project_id=project, project_hash="f" * 64), approved, _snapshot(approved)
    )
    assert not _within_ceiling(_policy(), approved, _snapshot(approved))


def test_a_trusting_routine_keeps_organization_sources_and_only_reviewed_personal_ones() -> None:
    organization, reviewed, unreviewed, elsewhere = uuid4(), uuid4(), uuid4(), uuid4()
    personal = _account(personal=True)
    approved = _policy(
        mcp_sources={
            reviewed: personal.model_copy(update={"tool_ids": ("list_issues",)}),
            elsewhere: personal,
        }
    )
    current = _policy(
        mcp_sources={
            organization: _account(),
            reviewed: personal,
            unreviewed: personal,
            elsewhere: personal.model_copy(update={"authorization_generation": uuid4()}),
        },
        root_mcp_ids=(organization, reviewed, unreviewed, elsewhere),
    )
    trusted = _trusted(current, approved)
    assert set(trusted.mcp_sources) == {organization, reviewed}
    assert trusted.mcp_sources[reviewed].tool_ids == ("list_issues",)
    assert trusted.root_mcp_ids == (organization, reviewed)


@pytest.mark.parametrize("grown", ["terminal_account", "platform"])
def test_a_trusting_routine_stops_for_personal_sources_it_cannot_leave_out(grown: str) -> None:
    approved = _policy()
    current = (
        _policy(mirage_accounts={uuid4(): uuid4()})
        if grown == "terminal_account"
        else _policy(platform=True)
    )
    with pytest.raises(RoutineSourcesRequired):
        _trusted(current, approved)
    assert _trusted(_policy(platform=True), _policy(platform=True)).platform


def test_growth_is_reported_by_the_names_the_review_shows() -> None:
    known, unnamed, grown_tools, secret, kept = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    generation = uuid4()
    approved = _policy(
        mcp_sources={grown_tools: _account(tool_ids=("list_issues",))},
        secret_sources={kept: generation},
    )
    current = _policy(
        mcp_sources={known: _account(), unnamed: _account(), grown_tools: _account()},
        secret_sources={secret: uuid4(), kept: generation},
    )
    review = _snapshot(
        current,
        items=[
            RoutineSourceItem(kind="mcp_account", id=str(known), name="Linear"),
            RoutineSourceItem(kind="mcp_account", id=str(grown_tools), name=None),
            RoutineSourceItem(kind="capability", id=None, name="Sandbox"),
        ],
    )
    assert _grown(current, approved, review) == sorted(
        {"Linear", str(unnamed), str(grown_tools), str(secret)}
    )
    assert _grown(_policy(), _policy(), _snapshot(_policy())) == ["agent configuration"]


def test_a_stored_review_is_its_own_ceiling_without_the_tool_half() -> None:
    snapshot = _snapshot(_policy(grandfathered=True, mode="trust_agent"))
    stored = stored_review(
        snapshot, mode="reviewed", tools=(ALLOW,), delegates="allow", intent_hash="e" * 64
    )
    assert (
        stored.mode,
        stored.tools,
        stored.delegates,
        stored.intent_hash,
        stored.grandfathered,
    ) == (
        "reviewed",
        (ALLOW,),
        "allow",
        "e" * 64,
        False,
    )
    assert stored.approved_ceiling == ceiling_of(stored)
    ceiling = ceiling_of(stored)
    assert (ceiling.approved_ceiling, ceiling.tools, ceiling.delegates, ceiling.intent_hash) == (
        None,
        (),
        "ask",
        None,
    )
    assert ceiling.mode == "reviewed" and ceiling.behavior == stored.behavior
    # A stored review validates back from what the column holds.
    assert RoutineSourcePolicy.model_validate(stored.model_dump(mode="json")) == stored


def test_the_routines_intent_follows_its_work_not_its_title() -> None:
    trigger = _trigger(name="Weekly")
    intent = routine_intent(trigger)
    trigger.name = "Renamed"
    trigger.interval_seconds = 7200
    assert routine_intent(trigger) == intent
    trigger.prompt = "Delete every stale branch"
    assert routine_intent(trigger) != intent
    changed = routine_intent(trigger)
    trigger.result_mode = "inbox"
    assert routine_intent(trigger) != changed
    inbox = routine_intent(trigger)
    trigger.project_id = uuid4()
    assert routine_intent(trigger) != inbox


def test_a_queued_activation_cannot_borrow_access_reviewed_after_it() -> None:
    trigger = _trigger(approved_sources=_policy().model_dump(mode="json"))
    queued = activation_intent(trigger)
    assert activation_intent(trigger) == queued
    trigger.approved_sources = _policy().model_dump(mode="json")
    assert activation_intent(trigger) != queued


def test_an_admission_refreshing_an_account_keeps_a_queued_activation() -> None:
    """A reconnect as the same account grants nothing, so a device wait survives it."""
    reviewed = _policy(mcp_sources={uuid4(): _account()}, tools=(ALLOW,))
    trigger = _trigger(approved_sources=reviewed.model_dump(mode="json"))
    queued = activation_intent(trigger)
    refreshed = reviewed.model_copy(
        update={
            "mcp_sources": {
                key: account.model_copy(update={"authorization_generation": uuid4()})
                for key, account in reviewed.mcp_sources.items()
            },
            "spec_hash": "e" * 64,
        }
    )
    trigger.approved_sources = refreshed.model_dump(mode="json")
    assert activation_intent(trigger) == queued
    trigger.approved_sources = refreshed.model_copy(update={"tools": ()}).model_dump(mode="json")
    assert activation_intent(trigger) != queued
    trigger.approved_sources = {"pending_review": True}
    assert activation_intent(trigger) != queued


@pytest.mark.parametrize(
    ("trigger_type", "role", "organization", "reason"),
    [
        ("event", "owner", SimpleNamespace(routines_may_trust_agent=True), "event"),
        ("schedule", "builder", SimpleNamespace(routines_may_trust_agent=True), "permission"),
        ("schedule", "owner", None, "organization"),
        ("schedule", "owner", SimpleNamespace(routines_may_trust_agent=False), "organization"),
        ("schedule", "owner", SimpleNamespace(routines_may_trust_agent=True), None),
    ],
)
async def test_trusting_the_agent_needs_a_schedule_the_permission_and_the_organization(
    monkeypatch: pytest.MonkeyPatch,
    trigger_type: str,
    role: str,
    organization: object,
    reason: str | None,
) -> None:
    monkeypatch.setattr(
        routine_sources.organization_repo, "get_by_id", AsyncMock(return_value=organization)
    )
    trigger = _trigger(trigger_type=trigger_type)
    ctx = AuthContext(
        user_id=trigger.created_by_user_id, organization_id=trigger.organization_id, role=role
    )
    assert await trust_blocked(AsyncMock(), ctx, trigger) == reason


def _admitted(policy: RoutineSourcePolicy, trigger: AgentTrigger) -> RoutineSourcePolicy:
    """A stored review that matches `trigger` as it stands."""
    assert trigger.created_by_user_id is not None
    stored = policy.model_copy(
        update={
            "consented_by": trigger.created_by_user_id,
            "scope_hash": source_scope(trigger),
            "intent_hash": routine_intent(trigger),
        }
    )
    stored = stored.model_copy(update={"approved_ceiling": ceiling_of(stored)})
    trigger.approved_sources = stored.model_dump(mode="json")
    return stored


async def _current(
    trigger: AgentTrigger, review: RoutineSourcePolicy, expected: UUID, **snapshot: object
) -> routine_sources.Admission:
    assert trigger.created_by_user_id is not None
    ctx = AuthContext(
        user_id=trigger.created_by_user_id, organization_id=trigger.organization_id, role="owner"
    )
    service = RoutineSourceService(AsyncMock())
    with patch.object(service, "_review", AsyncMock(return_value=_snapshot(review, **snapshot))):
        return await service.current(ctx, trigger, expected_id=expected)


@pytest.mark.parametrize("stale", ["id", "consented_by", "scope", "intent"])
async def test_a_review_of_another_routine_state_is_not_admitted(stale: str) -> None:
    trigger = _trigger()
    stored = _admitted(_policy(), trigger)
    expected = stored.id
    if stale == "id":
        expected = uuid4()
    elif stale == "consented_by":
        trigger.created_by_user_id = uuid4()
    elif stale == "scope":
        trigger.runs_as_creator = True
    else:
        trigger.prompt = "Something else entirely"
    with pytest.raises(RoutineSourcesRequired):
        await _current(trigger, stored, expected)


async def test_a_review_migrated_without_an_intent_does_not_see_a_prompt_change() -> None:
    trigger = _trigger()
    stored = _admitted(_policy(), trigger).model_copy(update={"intent_hash": None})
    trigger.approved_sources = stored.model_dump(mode="json")
    trigger.prompt = "Something else entirely"
    assert (await _current(trigger, ceiling_of(stored), stored.id)).policy == stored


async def test_a_reviewed_routine_passes_within_its_ceiling_and_refreshes_a_reconnect() -> None:
    key = uuid4()
    account = _account(account="ops@example.com")
    trigger = _trigger()
    stored = _admitted(
        _policy(mcp_sources={key: account}, root_mcp_ids=(key,), tools=(ALLOW,)), trigger
    )
    same = await _current(trigger, ceiling_of(stored), stored.id)
    assert same == routine_sources.Admission(policy=stored)
    reconnected = account.model_copy(update={"authorization_generation": uuid4()})
    current = ceiling_of(stored).model_copy(update={"mcp_sources": {key: reconnected}})
    admission = await _current(trigger, current, stored.id)
    assert admission.refreshed and not admission.expanded
    assert admission.policy.mcp_sources[key] == reconnected
    assert (admission.policy.id, admission.policy.tools) == (stored.id, stored.tools)
    # The ceiling is still what the creator reviewed.
    assert admission.policy.approved_ceiling == stored.approved_ceiling


async def test_a_reviewed_routine_stops_beyond_its_ceiling() -> None:
    trigger = _trigger()
    stored = _admitted(_policy(), trigger)
    grown = ceiling_of(stored).model_copy(update={"mcp_sources": {uuid4(): _account()}})
    with pytest.raises(RoutineSourcesRequired):
        await _current(trigger, grown, stored.id)


async def test_a_required_unavailable_source_stops_the_routine_and_an_optional_one_does_not() -> (
    None
):
    trigger = _trigger()
    stored = _admitted(_policy(), trigger)
    with pytest.raises(RoutineSourcesRequired) as refused:
        await _current(trigger, ceiling_of(stored), stored.id, unavailable=["GitHub"])
    assert refused.value.details == {"unavailable_sources": ["GitHub"]}
    admission = await _current(
        trigger,
        ceiling_of(stored),
        stored.id,
        unavailable=["GitHub"],
        optional_unavailable=frozenset({"GitHub"}),
    )
    assert admission.policy == stored


async def test_a_trusting_routine_refused_trust_is_told_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        routine_sources.organization_repo,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(routines_may_trust_agent=False)),
    )
    trigger = _trigger()
    stored = _admitted(_policy(mode="trust_agent"), trigger)
    with pytest.raises(RoutineTrustRefused) as refused:
        await _current(trigger, ceiling_of(stored), stored.id)
    assert refused.value.details == {"reason": "organization"}


async def test_a_trusting_routine_grows_into_organization_sources_and_moves_its_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        routine_sources.organization_repo,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(routines_may_trust_agent=True)),
    )
    organization, personal = uuid4(), uuid4()
    trigger = _trigger()
    stored = _admitted(_policy(mode="trust_agent"), trigger)
    grown = ceiling_of(stored).model_copy(
        update={
            "mcp_sources": {organization: _account(), personal: _account(personal=True)},
            "root_mcp_ids": (organization, personal),
        }
    )
    admission = await _current(trigger, grown, stored.id)
    assert admission.refreshed
    assert admission.expanded == [str(organization)]
    # The creator's own account nobody reviewed is left out of the run.
    assert set(admission.policy.mcp_sources) == {organization}
    assert admission.policy.root_mcp_ids == (organization,)
    assert admission.policy.approved_ceiling is not None
    assert set(admission.policy.approved_ceiling.mcp_sources) == {organization}
    assert admission.policy.mode == "trust_agent"

    db = AsyncMock()
    service = RoutineSourceService(db)
    ctx = AuthContext(
        user_id=trigger.created_by_user_id, organization_id=trigger.organization_id, role="owner"
    )
    audit = AsyncMock()
    notify = AsyncMock()
    monkeypatch.setattr(routine_sources, "record_audit", audit)
    with (
        patch.object(service, "_review", AsyncMock(return_value=_snapshot(grown))),
        patch("app.services.notifications.NotificationService.routine_access_expanded", notify),
    ):
        admitted = await service.require_current(ctx, trigger, expected_id=stored.id)
    assert admitted == admission.policy
    assert trigger.approved_sources == admission.policy.model_dump(mode="json")
    assert audit.await_args.kwargs["action"] == "routine.access_expanded"
    assert audit.await_args.kwargs["details"] == {
        "trigger_id": str(trigger.id),
        "sources": [str(organization)],
    }
    assert notify.await_args.kwargs == {"sources": [str(organization)]}

    # Admitted again, the moved ceiling covers it: nothing is reported twice.
    audit.reset_mock()
    notify.reset_mock()
    with (
        patch.object(service, "_review", AsyncMock(return_value=_snapshot(grown))),
        patch("app.services.notifications.NotificationService.routine_access_expanded", notify),
    ):
        await service.require_current(ctx, trigger, expected_id=stored.id)
    audit.assert_not_awaited()
    notify.assert_not_awaited()


@pytest.mark.parametrize("invalid", ["nested", "tools"])
def test_an_approved_ceiling_is_one_snapshot_of_sources(invalid: str) -> None:
    from pydantic import ValidationError

    child = _policy().model_dump(mode="json")
    if invalid == "nested":
        child["approved_ceiling"] = _policy().model_dump(mode="json")
    else:
        child["tools"] = [ALLOW.model_dump(mode="json")]
    with pytest.raises(ValidationError, match="one non-nested snapshot of sources"):
        RoutineSourcePolicy.model_validate(
            {**_policy().model_dump(mode="json"), "approved_ceiling": child}
        )


@pytest.mark.parametrize("mode", ["follow_agent", "restricted"])
def test_a_removed_source_mode_no_longer_reads(mode: str) -> None:
    with pytest.raises(RoutineSourcesRequired):
        routine_sources.read_policy({**_policy().model_dump(mode="json"), "mode": mode})


def test_a_binding_reviewed_with_its_former_fingerprint_is_still_recognised() -> None:
    """Reviews saved while binding fingerprints covered approvals keep matching."""
    current = {"root:capabilities:" + "1" * 64: "1" * 64}
    former = {"root:capabilities:" + "2" * 64: "2" * 64}
    aliases = {"root:capabilities:" + "1" * 64: "root:capabilities:" + "2" * 64}
    assert _within_behavior(current, former, aliases=aliases)
    assert not _within_behavior(current, former)
    assert not _within_behavior(current, {}, aliases=aliases)
