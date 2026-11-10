"""No paid run starts until its exact device confirms the routine-specific grant."""

from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.exceptions import AuthorizationError
from app.core.permissions import AuthContext, OrgRoleName
from app.schemas.local_target import LocalTarget, target_fingerprint
from app.services import device_hub
from app.services import routine_devices as module
from app.services.device_hub._protocol import Capabilities

pytestmark = pytest.mark.anyio


def target() -> LocalTarget:
    return LocalTarget(
        folder="/work",
        mode="read_only",
        device_id=uuid4(),
        routine_grant=uuid4(),
        operations={"read": True, "write": False, "execute": False},
    )


def context() -> AuthContext:
    return AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=OrgRoleName.OWNER,
        routine_id=uuid4(),
        fired_as_creator="schedule",
    )


def test_general_grants_remain_readable_but_cannot_supply_routine_authority() -> None:
    local = LocalTarget(folder="/work")
    assert module.local_scope(replace(context(), routine_id=None), local) is None
    with pytest.raises(module.RoutineLocalConsentRequired):
        module.local_scope(context(), local)


@pytest.mark.parametrize(
    "change",
    [
        {"routine_id": None},
        {"user_id": None},
        {"fired_as_creator": None},
        {"subject_is_publisher_fallback": True},
    ],
)
def test_routine_grants_cannot_be_borrowed_by_other_runs(change: dict[str, object]) -> None:
    with pytest.raises(AuthorizationError):
        module.local_scope(replace(context(), **change), target())


@pytest.mark.parametrize(
    "change",
    [
        {"device_id": None},
        {"folder": None},
        {"mode": "full_access"},
        {"browser": True},
        {"computer": True},
        {"computer_grant": uuid4()},
        {"model_service": "local"},
        {"mcp_services": ["local"]},
        {"operations": None},
        {"operations": {"read": True, "write": False, "execute": True}},
        {"operations": {"read": "true", "write": False, "execute": False}},
    ],
)
def test_routine_target_rejects_ambiguous_or_broader_authority(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LocalTarget.model_validate(target().model_dump() | change)


def test_fingerprint_is_normalized_and_binds_every_native_limit() -> None:
    local = target()
    assert target_fingerprint(None) is None
    assert target_fingerprint(local.model_dump(exclude_defaults=True)) == local.fingerprint()
    for change in (
        {"folder": "/different"},
        {"device_id": uuid4()},
        {"routine_grant": uuid4()},
        {"mode": "workspace_write", "operations": {"read": True, "write": True, "execute": False}},
    ):
        assert (
            LocalTarget.model_validate(local.model_dump() | change).fingerprint()
            != local.fingerprint()
        )


@pytest.fixture
def admission(monkeypatch: pytest.MonkeyPatch):
    local, ctx = target(), context()
    session = AsyncMock(return_value=object())
    device = device_hub.Device(
        user_id=ctx.user_id,
        session_id=local.device_id,
        platform="macos",
        capabilities=Capabilities(routine_grants=True, sandbox_modes=["read_only"]),
    )
    presence = AsyncMock(return_value=device)
    call = AsyncMock(return_value={"allowed": True})
    monkeypatch.setattr(module.session_repo, "active_device", session)
    monkeypatch.setattr(device_hub, "wait_for", presence)
    monkeypatch.setattr(device_hub, "call", call)
    return local, ctx, session, presence, call, device


async def test_ready_binds_all_identity_dimensions_without_model_or_filesystem_effects(
    admission,
) -> None:
    local, ctx, session, presence, call, device = admission
    assert await module.ready(AsyncMock(), ctx, local) is device
    session.assert_awaited_once()
    presence.assert_awaited_once_with(ctx.user_id, local.device_id, timeout=0)
    args = call.call_args.args
    assert args[:2] == (local.device_id, "routine.check")
    assert args[2] == {
        "root": "/work",
        "mode": "read_only",
        "work_context": local.routine_scope(
            organization_id=ctx.organization_id, routine_id=ctx.routine_id, user_id=ctx.user_id
        ).model_dump(mode="json"),
    }


async def test_ended_session_waits_without_using_cached_online_presence(admission) -> None:
    local, ctx, session, presence, call, _ = admission
    session.return_value = None
    with pytest.raises(module.RoutineDeviceOffline):
        await module.ready(AsyncMock(), ctx, local)
    presence.assert_not_awaited()
    call.assert_not_awaited()


async def test_offline_device_waits_before_any_native_operation(admission) -> None:
    local, ctx, _, presence, call, _ = admission
    presence.return_value = None
    with pytest.raises(module.RoutineDeviceOffline):
        await module.ready(AsyncMock(), ctx, local)
    call.assert_not_awaited()


@pytest.mark.parametrize("exception", [device_hub.DeviceUnavailable, device_hub.DeviceCallTimedOut])
async def test_uncertain_readiness_is_safe_to_repeat_because_it_has_no_effects(
    admission, exception
) -> None:
    local, ctx, _, _, call, _ = admission
    call.side_effect = exception(message="offline")
    with pytest.raises(module.RoutineDeviceOffline):
        await module.ready(AsyncMock(), ctx, local)


@pytest.mark.parametrize("response", [{"allowed": False}, {"allowed": "true"}, {}, None])
async def test_missing_or_nonboolean_native_consent_never_admits_a_run(admission, response) -> None:
    local, ctx, _, _, call, _ = admission
    call.return_value = response
    with pytest.raises(module.RoutineLocalConsentRequired):
        await module.ready(AsyncMock(), ctx, local)


async def test_native_revocation_requires_review_instead_of_automatic_retry(admission) -> None:
    local, ctx, _, _, call, _ = admission
    call.side_effect = device_hub.DeviceCallFailed(message="revoked")
    with pytest.raises(module.RoutineLocalConsentRequired):
        await module.ready(AsyncMock(), ctx, local)


@pytest.mark.parametrize(
    "change",
    [
        {"user_id": uuid4()},
        {"session_id": uuid4()},
        {"capabilities": Capabilities()},
        {"capabilities": Capabilities(routine_grants=True)},
    ],
)
async def test_another_device_or_older_native_binary_is_not_an_alternative(
    admission, change
) -> None:
    local, ctx, _, presence, call, device = admission
    presence.return_value = device.model_copy(update=change)
    with pytest.raises(module.RoutineLocalConsentRequired):
        await module.ready(AsyncMock(), ctx, local)
    call.assert_not_awaited()


async def test_admission_without_an_activation_does_nothing() -> None:
    db = AsyncMock()
    await module.admit_activation(db, context())
    assert db.mock_calls == []


@pytest.mark.parametrize("change", [{"routine_id": None}, {"user_id": None}])
async def test_activation_needs_its_trusted_routine_and_owner(change: dict[str, object]) -> None:
    with pytest.raises(AuthorizationError):
        await module.admit_activation(
            AsyncMock(), replace(context(), routine_activation_id=uuid4(), **change)
        )


async def test_interactive_context_cannot_use_routine_readiness() -> None:
    with pytest.raises(AuthorizationError):
        await module.ready(
            AsyncMock(), replace(context(), routine_id=None), LocalTarget(folder="/work")
        )


@pytest.mark.parametrize(
    "value",
    [
        {"folder": "/work", "operations": {"read": True}},
        {"folder": "/work", "computer_grant": uuid4(), "mode": "read_only"},
    ],
)
def test_legacy_targets_cannot_claim_unbound_operations_or_whole_computer_authority(
    value: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        LocalTarget.model_validate(value)


async def test_atomic_admission_refuses_a_lost_compare_and_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    ctx = replace(context(), routine_activation_id=uuid4())
    local = target()
    trigger = SimpleNamespace(
        is_active=True,
        runs_as_creator=True,
        created_by_user_id=ctx.user_id,
        local_target=local.model_dump(mode="json"),
        ends_at=None,
    )
    wait = SimpleNamespace(
        id=ctx.routine_activation_id,
        organization_id=ctx.organization_id,
        trigger_id=ctx.routine_id,
        user_id=ctx.user_id,
        device_id=local.device_id,
        status="waiting",
        intent_hash="intent",
    )
    monkeypatch.setattr(module.agent_trigger_repo, "get", AsyncMock(return_value=trigger))
    monkeypatch.setattr(module.device_wait_repo, "get", AsyncMock(return_value=wait))
    monkeypatch.setattr(module, "activation_intent", lambda _trigger: "intent")
    monkeypatch.setattr(module.session_repo, "active_device", AsyncMock(return_value=object()))
    monkeypatch.setattr(module.device_wait_repo, "settle", AsyncMock(return_value=False))
    with pytest.raises(module.RoutineActivationObsolete):
        await module.admit_activation(AsyncMock(), ctx)


def test_empty_local_selection_cannot_silently_choose_a_device_folder() -> None:
    with pytest.raises(ValidationError):
        LocalTarget()


class TestFollowingTheSignedInSession:
    pytestmark = pytest.mark.security

    """A new sign-in on the same computer moves the routine; the app still decides."""

    @pytest.fixture(autouse=True)
    def rebind_dependencies(self, monkeypatch):
        monkeypatch.setattr(module, "ready", AsyncMock())
        monkeypatch.setattr(module, "activation_intent", lambda trigger: str(trigger.local_target))
        monkeypatch.setattr(module.agent_trigger_repo, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(module.device_wait_repo, "rebind_device", AsyncMock())

    @staticmethod
    def _context(trigger):
        return replace(
            context(),
            user_id=trigger.created_by_user_id,
            organization_id=trigger.organization_id,
            routine_id=trigger.id,
        )

    @staticmethod
    def _trigger(local: LocalTarget | None = None, *, acting: bool = True):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=uuid4(),
            organization_id=uuid4(),
            local_target=None if local is None else local.model_dump(mode="json"),
            runs_as_creator=acting,
            created_by_user_id=uuid4(),
        )

    @staticmethod
    def _device(session_id):
        return device_hub.Device(
            user_id=uuid4(),
            session_id=session_id,
            platform="macos",
            capabilities=Capabilities(routine_grants=True, sandbox_modes=["read_only"]),
        )

    async def test_an_ended_session_moves_to_the_connected_one(self, monkeypatch) -> None:
        local = target()
        trigger = self._trigger(local)
        current = uuid4()
        active = AsyncMock(side_effect=lambda _db, *, session_id, **_: session_id == current)
        monkeypatch.setattr(module.session_repo, "active_device", active)
        monkeypatch.setattr(
            device_hub, "connected", AsyncMock(return_value=[self._device(current)])
        )
        db = AsyncMock()
        monkeypatch.setattr(module.agent_trigger_repo, "get", AsyncMock(return_value=trigger))
        before_intent = str(trigger.local_target)

        await module.follow_signed_in_session(db, trigger, self._context(trigger))

        moved = LocalTarget.model_validate(trigger.local_target)
        assert moved.device_id == current
        assert moved.routine_grant == local.routine_grant
        db.flush.assert_awaited_once()
        module.device_wait_repo.rebind_device.assert_awaited_once_with(
            db,
            trigger_id=trigger.id,
            user_id=trigger.created_by_user_id,
            previous_device_id=local.device_id,
            device_id=current,
            previous_intent=before_intent,
            intent=str(trigger.local_target),
        )

    @pytest.mark.parametrize("case", ["live", "nothing-connected", "not-acting", "no-folder"])
    async def test_nothing_moves_otherwise(self, monkeypatch, case) -> None:
        local = target()
        trigger = self._trigger(None if case == "no-folder" else local, acting=case != "not-acting")
        before = trigger.local_target
        monkeypatch.setattr(
            module.session_repo, "active_device", AsyncMock(return_value=case == "live")
        )
        monkeypatch.setattr(
            device_hub,
            "connected",
            AsyncMock(return_value=[] if case == "nothing-connected" else [self._device(uuid4())]),
        )
        db = AsyncMock()

        await module.follow_signed_in_session(db, trigger, self._context(trigger))

        assert trigger.local_target == before
        db.flush.assert_not_awaited()

    async def test_a_legacy_folder_without_a_routine_grant_is_left_alone(self, monkeypatch) -> None:
        trigger = self._trigger()
        trigger.local_target = {"folder": "/work", "mode": "read_only", "device_id": str(uuid4())}
        active = AsyncMock()
        monkeypatch.setattr(module.session_repo, "active_device", active)

        await module.follow_signed_in_session(AsyncMock(), trigger, self._context(trigger))

        active.assert_not_awaited()

    async def test_an_unreadable_folder_is_left_for_admission_to_block(self, monkeypatch) -> None:
        trigger = self._trigger()
        trigger.local_target = {"folder": "/work", "operations": {"read": False}}
        active = AsyncMock()
        monkeypatch.setattr(module.session_repo, "active_device", active)

        await module.follow_signed_in_session(AsyncMock(), trigger, self._context(trigger))

        active.assert_not_awaited()

    @pytest.mark.parametrize(
        "refusal", [module.RoutineLocalConsentRequired, module.RoutineDeviceOffline]
    )
    async def test_it_probes_other_computers_before_rebinding(self, monkeypatch, refusal):
        trigger = self._trigger(target())
        first, second = self._device(uuid4()), self._device(uuid4())
        monkeypatch.setattr(module.session_repo, "active_device", AsyncMock(return_value=None))
        monkeypatch.setattr(device_hub, "connected", AsyncMock(return_value=[first, second]))
        probe = AsyncMock(side_effect=[refusal("unavailable"), second])
        monkeypatch.setattr(module, "ready", probe)
        monkeypatch.setattr(module.agent_trigger_repo, "get", AsyncMock(return_value=trigger))
        await module.follow_signed_in_session(AsyncMock(), trigger, self._context(trigger))
        assert trigger.local_target["device_id"] == str(second.session_id)
        assert probe.await_count == 2

    @pytest.mark.parametrize("offline_first", [False, True])
    async def test_a_transient_candidate_preserves_waiting_despite_another_refusal(
        self, monkeypatch, offline_first
    ):
        trigger = self._trigger(target())
        before = trigger.local_target
        monkeypatch.setattr(module.session_repo, "active_device", AsyncMock(return_value=None))
        monkeypatch.setattr(
            device_hub,
            "connected",
            AsyncMock(return_value=[self._device(uuid4()), self._device(uuid4())]),
        )
        outcomes = [
            module.RoutineLocalConsentRequired("wrong computer"),
            module.RoutineDeviceOffline("disconnected"),
        ]
        probe = AsyncMock(side_effect=list(reversed(outcomes)) if offline_first else outcomes)
        monkeypatch.setattr(module, "ready", probe)
        db = AsyncMock()
        await module.follow_signed_in_session(db, trigger, self._context(trigger))
        assert trigger.local_target == before
        assert probe.await_count == 2
        db.flush.assert_not_awaited()

    async def test_no_session_is_saved_without_its_native_grant(self, monkeypatch):
        trigger = self._trigger(target())
        before = trigger.local_target
        monkeypatch.setattr(module.session_repo, "active_device", AsyncMock(return_value=None))
        monkeypatch.setattr(
            device_hub, "connected", AsyncMock(return_value=[self._device(uuid4())])
        )
        monkeypatch.setattr(
            module, "ready", AsyncMock(side_effect=module.RoutineLocalConsentRequired("revoked"))
        )
        db = AsyncMock()
        with pytest.raises(module.RoutineLocalConsentRequired, match="Connected computers refused"):
            await module.follow_signed_in_session(db, trigger, self._context(trigger))
        assert trigger.local_target == before
        db.flush.assert_not_awaited()

    async def test_a_deleted_routine_is_not_rebound(self, monkeypatch):
        trigger = self._trigger(target())
        monkeypatch.setattr(module.session_repo, "active_device", AsyncMock(return_value=None))
        monkeypatch.setattr(
            device_hub, "connected", AsyncMock(return_value=[self._device(uuid4())])
        )
        db = AsyncMock()
        await module.follow_signed_in_session(db, trigger, self._context(trigger))
        module.device_wait_repo.rebind_device.assert_not_awaited()
        db.flush.assert_not_awaited()

    @pytest.mark.parametrize("dimension", ["user_id", "organization_id", "routine_id"])
    async def test_an_unrelated_authority_cannot_rebind_the_session(self, dimension):
        trigger = self._trigger(target())
        ctx = replace(self._context(trigger), **{dimension: uuid4()})
        with pytest.raises(AuthorizationError, match="owner"):
            await module.follow_signed_in_session(AsyncMock(), trigger, ctx)

    @pytest.mark.parametrize("change", ["owner", "consent", "folder"])
    async def test_a_routine_edited_while_the_device_answers_is_not_rebound(
        self, monkeypatch, change
    ):
        trigger = self._trigger(target())
        ctx = self._context(trigger)
        monkeypatch.setattr(module.session_repo, "active_device", AsyncMock(return_value=None))
        monkeypatch.setattr(
            device_hub, "connected", AsyncMock(return_value=[self._device(uuid4())])
        )

        async def locked(*_args, **_kwargs):
            if change == "owner":
                trigger.created_by_user_id = uuid4()
            elif change == "consent":
                trigger.runs_as_creator = False
            else:
                trigger.local_target = {**trigger.local_target, "folder": "/changed"}
            return trigger

        monkeypatch.setattr(module.agent_trigger_repo, "get", locked)
        await module.follow_signed_in_session(AsyncMock(), trigger, ctx)
        module.device_wait_repo.rebind_device.assert_not_awaited()
