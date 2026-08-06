"""What a sync source is not allowed to decide: where a file lands, and what is queried.

A remote file's name and a folder's identifier both arrive from outside the
deployment, and the name is not even the tenant's: sharing a Drive folder with
people outside the organization is what folder sharing is *for*, so whoever can
drop a file in it chooses what the next sync writes to disk. Both are labels
until something promotes one to a path component or to a fragment of a query,
and this module is the one place that promotion is refused.

Kept outside `connectors/` because `sources/` needs the same two answers and
must not import from its sibling.
"""

import re
from pathlib import Path

from app.core.exceptions import BadRequestError

# Drive issues base64url identifiers. The upper bound is generous - the longest
# id Google has issued is well under 64 characters - and exists so a refusal
# reads as a refusal rather than as a regex walking a megabyte of config.
_DRIVE_ID = re.compile(r"[A-Za-z0-9_-]{1,256}")


def checked_drive_folder_id(folder_id: object) -> str:
    """Answer `folder_id` if Google could have issued it, and refuse it otherwise.

    The Drive query language wraps a parent id in single quotes, so an id
    carrying one closes the literal and everything after it is read as query:
    `x' in parents or name contains 'salary` is well-formed and lists whatever
    the credential can reach. An allowlist rather than an escape, because a real
    identifier needs nothing the allowlist withholds, and an escape leaves every
    future sink to remember what this one remembered.

    Takes an `object` because a source's config is `dict[str, object]` and JSON
    carries numbers and nested structures - the field arrives as whatever was
    posted, and a value that is not a string is refused here rather than
    stringified into one somewhere on the way.

    Raises:
        BadRequestError: the value is not a Drive identifier.
    """
    if not isinstance(folder_id, str) or not _DRIVE_ID.fullmatch(folder_id):
        raise BadRequestError(
            message="A Google Drive folder ID may contain only letters, digits, '-' and '_'.",
            details={"field": "folder_id"},
        )
    return folder_id


def destination_within(directory: Path, remote_name: str) -> Path:
    """Answer where a file called `remote_name` may be written inside `directory`.

    `../../../../home/app/.ssh/authorized_keys` is a legal Drive file name, so
    `directory / remote_name` writes wherever the worker's uid can reach - and
    the sync then ingests from there. The name is reduced to its final
    component, and the result is *resolved and confirmed* to be a child of
    `directory` rather than cleaned of the spellings we happened to think of:
    `..`, its percent-encodings, its unicode lookalikes and a symlink already
    sitting in the directory are one question after `resolve()`, and an
    enumeration of separators is a list that is always one entry short.

    A name that is no component at all - `..`, `.`, `/`, the empty string -
    resolves onto the directory itself and is refused rather than silently
    renamed, because a file with no name is nothing this pipeline can ingest.

    Raises:
        BadRequestError: the name does not name a file inside `directory`.
    """
    if "\x00" in remote_name:
        raise BadRequestError(
            message="A remote file name may not contain a NULL byte.",
            details={"field": "name"},
        )

    base = directory.resolve()
    destination = (base / Path(remote_name).name).resolve()
    if destination.parent != base:
        raise BadRequestError(
            message="A remote file name must name one file inside the sync directory.",
            details={"field": "name"},
        )
    return destination
