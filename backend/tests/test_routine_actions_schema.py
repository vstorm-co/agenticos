"""Large consent requests are bounded without silently truncating actions."""

import pytest
from pydantic import ValidationError

from app.schemas.routine_actions import MAX_ROUTINE_ACTIONS, RoutineActionKey, RoutineActions

pytestmark = pytest.mark.security


@pytest.mark.parametrize("count", [100, 101, MAX_ROUTINE_ACTIONS])
def test_a_supported_selection_keeps_every_action(count: int) -> None:
    actions = [
        RoutineActionKey(capability_id="sandbox", tool_id=f"tool_{index}") for index in range(count)
    ]
    request = RoutineActions(actions=actions)
    assert len(request.actions) == count
    assert request.actions == actions


def test_a_selection_beyond_the_limit_is_refused_instead_of_truncated() -> None:
    with pytest.raises(ValidationError, match="at most"):
        RoutineActions(
            actions=[RoutineActionKey(capability_id="sandbox", tool_id="execute")]
            * (MAX_ROUTINE_ACTIONS + 1)
        )
