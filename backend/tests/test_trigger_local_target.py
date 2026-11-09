"""A routine reaches only its creator's computer with their standing consent."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import JsonValue

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.schemas.local_target import LocalOperations, LocalTarget
from app.services.agent_trigger import AgentTriggerService

pytestmark = pytest.mark.security


def test_creator_can_select_a_folder_and_disabling_authority_clears_it() -> None:
    owner = uuid4()
    ctx = AuthContext(user_id=owner, organization_id=uuid4(), role="owner")
    trigger = MagicMock(
        id=uuid4(), created_by_user_id=owner, runs_as_creator=True, local_target={"folder": "/old"}
    )
    changes: dict[str, JsonValue] = {"local_target": {"folder": "/approved"}}
    target = LocalTarget(
        folder="/approved",
        device_id=uuid4(),
        routine_grant=uuid4(),
        operations=LocalOperations(write=True),
    )
    AgentTriggerService._guard_local_target(ctx, trigger, changes, target)
    assert changes["local_target"] == target.model_dump(mode="json")
    changes = {"runs_as_creator": False}
    AgentTriggerService._guard_local_target(ctx, trigger, changes, None)
    assert changes["local_target"] is None
    changes = {"prompt": "new prompt"}
    AgentTriggerService._guard_local_target(ctx, trigger, changes, None)
    assert "local_target" not in changes


@pytest.mark.parametrize("caller", ["another-user", "key", "not-acting"])
def test_no_other_identity_can_grant_local_access(caller: str) -> None:
    owner = uuid4()
    ctx = AuthContext(
        user_id=uuid4() if caller == "another-user" else owner,
        organization_id=uuid4(),
        role="owner",
        api_key_id=uuid4() if caller == "key" else None,
        key_internal=caller == "key",
    )
    trigger = MagicMock(
        id=uuid4(),
        created_by_user_id=owner,
        runs_as_creator=caller != "not-acting",
        local_target=None,
    )
    with pytest.raises(BadRequestError if caller == "not-acting" else AuthorizationError):
        AgentTriggerService._guard_local_target(
            ctx, trigger, {"local_target": {}}, LocalTarget(folder="/approved")
        )


def test_an_unbound_legacy_folder_requires_fresh_native_consent():
    from app.services.routine_devices import RoutineLocalConsentRequired

    owner = uuid4()
    ctx = AuthContext(user_id=owner, organization_id=uuid4(), role="owner")
    trigger = MagicMock(
        id=uuid4(), created_by_user_id=owner, runs_as_creator=True, local_target=None
    )
    with pytest.raises(RoutineLocalConsentRequired, match="Review this routine"):
        AgentTriggerService._guard_local_target(
            ctx, trigger, {"local_target": {}}, LocalTarget(folder="/work")
        )
