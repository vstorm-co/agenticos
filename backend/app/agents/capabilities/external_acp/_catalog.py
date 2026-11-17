"""Bounded model choices advertised by the current ACP session, never a static catalog."""

from collections.abc import Mapping

import anyio
from pydantic import BaseModel, ConfigDict, Field

from app.agents.capabilities.coding_agent._acp import (
    AcpError,
    Conversation,
    Pipe,
    _Collector,
    initialize_session,
)
from app.agents.capabilities.coding_agent._harness import LiveItem


class AcpChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)


class AcpCatalog(BaseModel):
    models_exposed: bool = False
    models: list[AcpChoice] = Field(default_factory=list, max_length=128)
    current_model: str | None = None
    efforts: list[AcpChoice] = Field(default_factory=list, max_length=128)
    current_effort: str | None = None


def _choices(value: object) -> list[AcpChoice]:
    if not isinstance(value, list):
        raise AcpError("The agent returned a malformed model or reasoning catalog.")
    choices: list[AcpChoice] = []
    for item in value:
        if not isinstance(item, dict):
            raise AcpError("The agent returned a malformed model or reasoning choice.")
        if "options" in item:
            # ACP supports a single group layer, not recursive arbitrary trees.
            nested = item["options"]
            if not isinstance(nested, list) or any(
                isinstance(choice, dict) and "options" in choice for choice in nested
            ):
                raise AcpError("The agent returned unsupported nested model groups.")
            choices.extend(_choices(nested))
        else:
            identifier, name = item.get("value"), item.get("name")
            if (
                not isinstance(identifier, str)
                or not identifier
                or len(identifier) > 256
                or not isinstance(name, str)
                or not name
                or len(name) > 256
            ):
                raise AcpError("The agent returned an invalid model or reasoning choice.")
            choices.append(AcpChoice(id=identifier, name=name))
        if len(choices) > 128:
            raise AcpError(
                "The agent advertised more than 128 choices. Narrow its model catalog before continuing."
            )
    if len({choice.id for choice in choices}) != len(choices):
        raise AcpError("The agent advertised ambiguous duplicate choices.")
    return choices


def session_catalog(opened: Mapping[str, object]) -> AcpCatalog:
    catalog = AcpCatalog()
    options = opened.get("configOptions", [])
    if not isinstance(options, list):
        raise AcpError("The agent returned malformed session settings.")
    seen: set[str] = set()
    for option in options:
        if not isinstance(option, dict):
            continue
        category = option.get("category")
        if not isinstance(category, str) or category not in {"model", "thought_level"}:
            continue
        if category in seen:
            raise AcpError("The agent advertised ambiguous session settings.")
        seen.add(category)
        choices = _choices(option.get("options"))
        current = option.get("currentValue")
        if current is not None and (
            not isinstance(current, str) or current not in {choice.id for choice in choices}
        ):
            raise AcpError("The agent's selected option is missing from its advertised choices.")
        if category == "model":
            catalog.models_exposed, catalog.models, catalog.current_model = True, choices, current
        else:
            catalog.efforts, catalog.current_effort = choices, current
    return catalog


async def inspect_session(
    pipe: Pipe, *, root: str, auth_method: str | None, timeout_seconds: int
) -> AcpCatalog:
    async def ignore(_items: list[LiveItem]) -> None:
        return None

    conversation = Conversation(pipe, access="read_only", collector=_Collector(), shown=ignore)
    try:
        with anyio.fail_after(timeout_seconds):
            await initialize_session(conversation, auth_method=auth_method)
            opened = await conversation.request("session/new", {"cwd": root, "mcpServers": []})
            if not isinstance(opened, dict) or not isinstance(opened.get("sessionId"), str):
                raise AcpError("The agent did not open a session for model discovery.")
            return session_catalog(opened)
    finally:
        with anyio.CancelScope(shield=True):
            await pipe.close()
