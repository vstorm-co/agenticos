"""Bounded filesystem RPC used by an authorized live Project mount."""

import base64
import binascii
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CHUNK_BYTES = 131_072
MAX_FILE_BYTES = 2**31 - 1


class FsPath(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(default=".", max_length=4096)


class FsStat(FsPath):
    op: Literal["stat"]


class FsList(FsPath):
    op: Literal["list"]


class FsRead(FsPath):
    op: Literal["read"]
    offset: int = Field(default=0, ge=0, le=MAX_FILE_BYTES)
    count: int = Field(default=CHUNK_BYTES, ge=0, le=CHUNK_BYTES)


class FsWrite(FsPath):
    op: Literal["write"]
    offset: int = Field(default=0, ge=0, le=MAX_FILE_BYTES)
    data: str = Field(max_length=4 * ((CHUNK_BYTES + 2) // 3))


class FsCreate(FsPath):
    op: Literal["create"]
    exclusive: bool = False
    verifier: str | None = Field(default=None, max_length=12)

    @field_validator("verifier")
    @classmethod
    def valid_verifier(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                decoded = base64.b64decode(value, validate=True)
            except binascii.Error as error:
                raise ValueError("Create verifier must be base64") from error
            if len(decoded) != 8:
                raise ValueError("Create verifier must contain exactly eight bytes")
            return base64.b64encode(decoded).decode()
        return value

    @model_validator(mode="after")
    def exclusive_verifier(self) -> FsCreate:
        if self.verifier is not None and not self.exclusive:
            raise ValueError("A create verifier requires exclusive creation")
        return self

    mode: int = Field(default=0o644, ge=0, le=0o777)
    size: int | None = Field(default=None, ge=0, le=MAX_FILE_BYTES)
    modified_at: datetime | None = None

    @field_validator("modified_at")
    @classmethod
    def aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Filesystem timestamps require a timezone")
        return value


class FsMkdir(FsPath):
    op: Literal["mkdir"]
    mode: int = Field(default=0o755, ge=0, le=0o777)
    modified_at: datetime | None = None

    @field_validator("modified_at")
    @classmethod
    def aware_timestamp(cls, value: datetime | None) -> datetime | None:
        return FsCreate.aware_timestamp(value)


class FsRemove(FsPath):
    op: Literal["remove"]
    directory: bool = False


class FsRename(FsPath):
    op: Literal["rename"]
    destination: str = Field(max_length=4096)


class FsTruncate(FsPath):
    op: Literal["truncate"]
    size: int = Field(ge=0, le=MAX_FILE_BYTES)


class FsSetattr(FsPath):
    op: Literal["setattr"]
    mode: int | None = Field(default=None, ge=0, le=0o777)
    modified_at: datetime | None = None
    guard_modified_at: datetime | None = None
    size: int | None = Field(default=None, ge=0, le=MAX_FILE_BYTES)

    @model_validator(mode="after")
    def timezone(self) -> FsSetattr:
        for value in (self.modified_at, self.guard_modified_at):
            if value is not None and value.utcoffset() is None:
                raise ValueError("Filesystem timestamps require a timezone")
        return self


FsRequest = Annotated[
    FsStat
    | FsList
    | FsRead
    | FsWrite
    | FsCreate
    | FsMkdir
    | FsRemove
    | FsRename
    | FsTruncate
    | FsSetattr,
    Field(discriminator="op"),
]


class FsAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: int = Field(ge=0, le=0o777)
    modified_at: datetime | None = None


class FsStoredAttributes(FsAttributes):
    creation_verifier: str | None = None
    creation_marker: str | None = None


class FsEntry(FsAttributes):
    path: str
    is_dir: bool
    size: int = Field(ge=0)


class FsSuccess(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[True] = True
    entry: FsEntry | None = None
    entries: list[FsEntry] | None = None
    data: str | None = None
    written: int | None = Field(default=None, ge=0, le=CHUNK_BYTES)
    eof: bool | None = None


class FsFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: Literal[False] = False
    errno: int = Field(ge=1)
    message: str


FsResponse = Annotated[FsSuccess | FsFailure, Field(discriminator="ok")]
