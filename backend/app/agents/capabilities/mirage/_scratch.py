"""Carry RAM folders across a parked run, without persisting remote credentials."""

from collections.abc import Sequence
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from pydantic_ai.messages import ModelMessage

KEY = "agenticos_mirage_scratch"
MAX_BYTES = 16 * 1024 * 1024


class ScratchFolder(BaseModel):
    model_config = ConfigDict(ser_json_bytes="base64", val_json_bytes="base64")

    files: dict[str, bytes] = Field(default_factory=dict, max_length=10000)
    dirs: list[str] = Field(default_factory=list, max_length=10000)
    modified: dict[str, str] = Field(default_factory=dict, max_length=20000)
    attrs: dict[str, dict[str, JsonValue]] = Field(default_factory=dict, max_length=20000)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if sum(map(len, self.files.values())) > MAX_BYTES:
            raise ValueError("Mirage scratch files exceed the memory limit")
        return self


class ScratchState(BaseModel):
    folders: dict[str, ScratchFolder] = Field(default_factory=dict, max_length=10)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if (
            sum(len(data) for folder in self.folders.values() for data in folder.files.values())
            > MAX_BYTES
        ):
            raise ValueError("Mirage scratch files exceed the memory limit")
        return self


def restore(messages: Sequence[ModelMessage]) -> ScratchState:
    for message in reversed(messages):
        if message.metadata is not None and KEY in message.metadata:
            state = ScratchState.model_validate(message.metadata[KEY])
            # The continuation consumes the snapshot. A later conversation turn
            # must not resurrect the RAM folders from an old approval.
            message.metadata = {key: value for key, value in message.metadata.items() if key != KEY}
            return state
    return ScratchState()


def keep(messages: Sequence[ModelMessage], state: ScratchState) -> None:
    if messages:
        messages[-1].metadata = {
            **(messages[-1].metadata or {}),
            KEY: state.model_dump(mode="json"),
        }
