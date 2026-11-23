"""Bounded model choices advertised by the current ACP session, never a static catalog."""

from collections.abc import Mapping
from typing import Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field

from app.agents.capabilities.coding_agent._acp import (
    AcpError,
    Conversation,
    CredentialProbe,
    Pipe,
    _Collector,
    initialize_session,
)
from app.agents.capabilities.coding_agent._harness import LiveItem, RuntimeCredentials


class AcpChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=256)


class AcpCatalog(BaseModel):
    configuration_policy: Literal["session", "cli", "launch"] = "session"
    credentials: RuntimeCredentials | None = None
    refresh_pending: bool = False
    model_prefix: str | None = None
    models_exposed: bool = False
    models_truncated: bool = False
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
    legacy = opened.get("models")
    if isinstance(legacy, dict):
        models = legacy.get("availableModels")
        if not isinstance(models, list):
            raise AcpError("The agent returned malformed legacy model settings")
        choices = _choices(
            [
                {"value": item.get("modelId"), "name": item.get("name")}
                if isinstance(item, dict)
                else item
                for item in models
            ]
        )
        current = legacy.get("currentModelId")
        if not isinstance(current, str) or current not in {choice.id for choice in choices}:
            raise AcpError("The agent's current model is absent from its catalog")
        return AcpCatalog(models_exposed=True, models=choices, current_model=current)
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
            continue
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


def _scoped_catalog(opened: Mapping[str, object], model_prefix: str | None) -> AcpCatalog:
    catalog = session_catalog(opened)
    if model_prefix is not None:
        catalog.model_prefix = model_prefix
        catalog.models = [
            model
            for model in catalog.models
            if model.id.startswith(model_prefix) and model.id != model_prefix
        ]
        if catalog.current_model not in {model.id for model in catalog.models}:
            catalog.current_model = None
            catalog.efforts = []
            catalog.current_effort = None
    return catalog


async def inspect_session(
    pipe: Pipe,
    *,
    root: str,
    auth_method: str | None,
    timeout_seconds: int,
    model_prefix: str | None = None,
    wait_for_updates: bool = False,
    refresh_seconds: float = 2.0,
    credential_probe: CredentialProbe | None = None,
) -> AcpCatalog:
    async def ignore(_items: list[LiveItem]) -> None:
        return None

    collector = _Collector()
    conversation = Conversation(pipe, access="read_only", collector=collector, shown=ignore)
    try:
        with anyio.fail_after(timeout_seconds):
            await initialize_session(conversation, auth_method=auth_method)
            credentials = (
                await credential_probe(conversation, auth_method)
                if credential_probe is not None
                else None
            )
            opened = await conversation.request("session/new", {"cwd": root, "mcpServers": []})
            if not isinstance(opened, dict) or not isinstance(opened.get("sessionId"), str):
                raise AcpError("The agent did not open a session for model discovery.")
            if wait_for_updates and collector.config_generation == 0:
                with anyio.move_on_after(refresh_seconds):
                    while collector.config_generation == 0:
                        await conversation.receive_update()
            state = (
                {**opened, "configOptions": collector.config_options}
                if collector.config_generation
                else opened
            )
            catalog = _scoped_catalog(state, model_prefix)
            catalog.credentials = credentials
            catalog.refresh_pending = wait_for_updates and not catalog.models
            return catalog
    finally:
        with anyio.CancelScope(shield=True):
            await pipe.close()
