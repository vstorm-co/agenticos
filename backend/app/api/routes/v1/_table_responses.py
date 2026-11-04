"""How a record write is answered on the wire, kept out of the endpoint module."""

from fastapi import Response, status

from app.schemas.virtual_table import RecordRead
from app.services.virtual_tables import RecordWrite


def answer(response: Response, written: RecordWrite) -> RecordRead:
    """The record, with 201 when the write created it and a header when it was a replay.

    A replayed create is still a 201: the caller asked for a record to exist and
    told the same story the first time. `Idempotent-Replayed` is how it can tell
    the two apart.
    """
    response.status_code = status.HTTP_201_CREATED if written.created else status.HTTP_200_OK
    if written.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return written.record
