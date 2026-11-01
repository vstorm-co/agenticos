"""The desktop's live view, and a person taking it over (#2305).

Every desktop a run works is also published where a browse is (#2128), under
the run and the window's call id, so the console's live view and the chat's
browse window draw it and offer Take over - for a sandbox, a daemon, an E2B
desktop and the person's own computer alike.

A take-over lands between the agent's calls: the call that finds it hands the
desktop to the person, relays what they do at the coordinates of the picture
they see, and gives it back when they do - or after `HOLD_LIMIT`. The model is
then told a person had the desktop and to look again; what the person typed is
never recorded, only that somebody took over.
"""

import base64
import logging
from collections.abc import Awaitable, Callable

import anyio

from app.agents.browser_events import BrowserCommand, BrowserControl, BrowserEvent
from app.agents.capabilities.computer_use._actions import (
    Click,
    Key,
    Screen,
    Scroll,
    TypeText,
    to_native,
)
from app.agents.capabilities.computer_use._backends import Computer, ComputerError, NativeAction

logger = logging.getLogger(__name__)

HOLD_LIMIT = 900.0
"""How long a person may hold the desktop before it is handed back to the agent."""

FRAME_EVERY = 1.0
"""Seconds between pictures while a person holds the desktop and is not acting."""

SCROLL_STEP = 100.0
"""Wheel pixels a viewer's scroll counts as one notch of the desktop's wheel."""

_KEYS = {
    "Enter": "enter",
    "Tab": "tab",
    "Backspace": "backspace",
    "Delete": "delete",
    "Escape": "escape",
    "ArrowUp": "up",
    "ArrowDown": "down",
    "ArrowLeft": "left",
    "ArrowRight": "right",
    "Home": "home",
    "End": "end",
    "PageUp": "pageup",
    "PageDown": "pagedown",
}

TOLD = (
    "A person took the desktop over and handed it back. Nothing you sent was done; "
    "look at this screenshot before acting again."
)


def person_action(command: BrowserCommand, screen: Screen) -> NativeAction | None:
    """What a viewer did, as an action on the desktop; `None` for one that says nothing."""
    if command.type == "click" and command.x is not None and command.y is not None:
        x, y = min(int(command.x), screen.width - 1), min(int(command.y), screen.height - 1)
        return to_native(Click(x=max(x, 0), y=max(y, 0)), screen)
    if command.type == "type" and command.text:
        return TypeText(text=command.text)
    if command.type == "key" and command.key is not None:
        return Key(keys=_KEYS[command.key])
    if command.type == "scroll" and command.dy:
        notches = max(1, min(20, round(abs(command.dy) / SCROLL_STEP)))
        middle = Scroll(
            x=screen.width // 2,
            y=screen.height // 2,
            direction="down" if command.dy > 0 else "up",
            amount=notches,
        )
        return to_native(middle, screen)
    return None


async def take_over_waiting(control: BrowserControl | None) -> BrowserCommand | None:
    """The take-over that arrived since the last call, if one did; other input is dropped."""
    if control is None:
        return None
    while (command := await control.poll()) is not None:
        if command.type == "take_over":
            return command
    return None


async def held(
    computer: Computer,
    control: BrowserControl,
    command: BrowserCommand,
    *,
    look: Callable[[], Awaitable[tuple[bytes, Screen]]],
    emit: Callable[[BrowserEvent], Awaitable[None]],
    call_id: str,
    step: int,
) -> None:
    """Hand the desktop to the person who asked, until they give it back.

    Only their own input and give-back are acted on; a second viewer's click must
    not land on a screen somebody else is holding.
    """
    by_user_id = command.by_user_id
    await emit(
        BrowserEvent(
            kind="browser_held", call_id=call_id, step=step, by=command.by, by_user_id=by_user_id
        )
    )
    _, screen = await look()
    with anyio.move_on_after(HOLD_LIMIT):
        while True:
            received = await control.wait(FRAME_EVERY)
            if (
                received is not None
                and by_user_id is not None
                and received.by_user_id != by_user_id
            ):
                received = None
            if received is not None and received.type == "give_back":
                break
            action = None if received is None else person_action(received, screen)
            if action is not None:
                try:
                    await computer.perform(action)
                except ComputerError as exc:
                    # The person sees the next picture either way; one refused
                    # click is not a reason to take the desktop from them.
                    logger.warning("computer_use_person_input_failed: %s", exc)
            try:
                image, screen = await look()
            except ComputerError as exc:
                logger.warning("computer_use_held_frame_failed: %s", exc)
                continue
            await emit(
                BrowserEvent(
                    kind="browser_frame",
                    call_id=call_id,
                    step=step,
                    title=computer.label,
                    image=f"data:image/jpeg;base64,{base64.b64encode(image).decode()}",
                )
            )
    await emit(BrowserEvent(kind="browser_released", call_id=call_id, step=step))
