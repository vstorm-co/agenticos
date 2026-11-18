"""Revision header and ETag helpers for rich browser procedure teaching."""

import re
from typing import Annotated

from fastapi import Depends, Header, Response

from app.core.exceptions import BadRequestError
from app.schemas.browser_procedure_teaching import BrowserProcedureTeachingRead


def _revision(value: Annotated[str, Header(alias="If-Match", max_length=32)]) -> int:
    if re.fullmatch(r'(?:[1-9][0-9]{0,9}|"[1-9][0-9]{0,9}")', value) is None:
        raise BadRequestError(message="Provide the current teaching revision in If-Match")
    return int(value.strip('"'))


Revision = Annotated[int, Depends(_revision)]


def with_etag(
    response: Response, data: BrowserProcedureTeachingRead
) -> BrowserProcedureTeachingRead:
    response.headers["ETag"] = f'"{data.revision}"'
    return data
