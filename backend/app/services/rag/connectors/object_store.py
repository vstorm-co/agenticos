"""What every object store's connector does identically.

S3, Azure Blob Storage and Google Cloud Storage are one connector with three
clients: a container, a prefix, a credential, and a flat listing of objects with
a size and a modified time. #938 put the other two fifth on the list with a
condition attached - *"if `S3Connector` is refactored to an object-store shape,
these are configuration rather than code"* - and this is that shape, written
before either of them rather than after, because the alternative is three
connectors sharing a form by resemblance (#988).

What a subclass supplies is a client and its SDK's vocabulary: how a listing
paginates, and how one object is written to a path. What it inherits is
everything a reader of three connectors would otherwise have to check three
times - that a key ending in `/` is a directory marker and not a document, that
`source_path` is `<scheme>://<container>/<key>` and is the dedup key the whole
sync path matches on, and that the destination is the base class's answer rather
than the connector's (`BaseSyncConnector.download_file`, which is inherited for
the reason its own docstring gives).
"""

import asyncio
import logging
from abc import abstractmethod
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

from app.core.secret_kinds import StorableSecret
from app.services.rag.connectors import BaseSyncConnector, ConnectorConfig, RemoteFile

logger = logging.getLogger(__name__)


class StoredObject(BaseModel):
    """One object in a listing, in the terms all three stores describe one in.

    Deliberately not an `etag`. Every object store offers one and the sync path
    reads none: it compares a `content_hash` of the bytes it downloaded (#990),
    so an `etag` carried here would be a field nothing reads. A connector that
    can answer "changed?" *without* the bytes is worth having - it saves the
    transfer, not just the embedding - and `docs/file-processing.md` says so under
    what a new connector owes; the place to add it is there and then, with the
    caller that reads it.

    `modified_at` is carried because `RemoteFile` already has somewhere to put
    it.
    """

    key: str
    size: int | None = None
    modified_at: datetime | None = None


class ObjectStoreConnector(BaseSyncConnector):
    """A connector for a store addressed by container and key.

    Two hooks, and both are **blocking**, run on a worker thread by the methods
    below: boto3, `azure-storage-blob` and `google-cloud-storage` all ship
    synchronous clients, and a hook declared `async` over one of those would
    either block the event loop or be wrapped twice.
    """

    SCHEME: ClassVar[str] = ""
    """What a `source_path` from this store starts with - `s3`, `gs`, `azblob`."""

    CONTAINER_FIELD: ClassVar[str] = "bucket"
    """Which `CONFIG_SCHEMA` field names the container. S3 and GCS call it a
    bucket; Azure calls it a container, and the form should say what the store's
    own console says."""

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> list[RemoteFile]:
        """Every document under the configured prefix, newest state as listed.

        A key ending in `/` is skipped here rather than in each client: a
        console that creates a "folder" writes a zero-byte object with that name,
        and ingesting one is a document with no bytes and a name of `''`.
        """
        container = config[self.CONTAINER_FIELD]
        objects = await asyncio.to_thread(
            self._objects, container, config.get("prefix", ""), config, credential
        )
        return [
            RemoteFile(
                id=obj.key,
                name=Path(obj.key).name,
                size=obj.size,
                modified_at=obj.modified_at,
                source_path=f"{self.SCHEME}://{container}/{obj.key}",
            )
            for obj in objects
            if not obj.key.endswith("/")
        ]

    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        """Write one object to the path the base class chose."""
        container = file.source_path.removeprefix(f"{self.SCHEME}://").split("/", 1)[0]
        await asyncio.to_thread(self._download, container, file.id, dest_path, config, credential)
        logger.info(
            "Downloaded %s://%s/%s (%d bytes)",
            self.SCHEME,
            container,
            file.id,
            dest_path.stat().st_size,
        )

    @abstractmethod
    def _objects(
        self,
        container: str,
        prefix: str,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> list[StoredObject]:
        """This store's listing, paginated the way its SDK paginates.

        Blocking, and called on a worker thread by `list_files`.
        """

    @abstractmethod
    def _download(
        self,
        container: str,
        key: str,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        """Write one object's bytes to `dest_path`. Blocking, on a worker thread."""
