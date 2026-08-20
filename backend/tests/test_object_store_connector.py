"""What an object store's connector inherits rather than repeats (#988).

S3, Azure Blob and GCS are one connector with three clients, and #938 made the
other two conditional on this shape existing first - the alternative being three
connectors sharing a form by resemblance, where a fix to the listing loop lands
in one of them.

So these tests are written against a **subclass that is not S3**: what they hold
shut is the shared half - the `/`-terminated key that is a console's folder and
not a document, the `source_path` the whole sync path matches on, and the
container coming from whichever field the store's own console calls it. A test
that used `S3Connector` for this would prove the same code twice and say nothing
about the next store.

`TestTheS3ConnectorStillListsWhatItListed` is the other half: the refactor is
only correct if a stored source syncs exactly the way it did before it.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.exceptions import BadRequestError
from app.core.secret_kinds import AwsCredentialsSecret, StorableSecret
from app.schemas.sync_source import ConnectorConfigField
from app.services.rag.connectors import ConnectorConfig, RemoteFile
from app.services.rag.connectors.object_store import ObjectStoreConnector, StoredObject
from app.services.rag.connectors.s3 import S3Connector

pytestmark = pytest.mark.anyio


class BlobConnector(ObjectStoreConnector):
    """A store that calls its container a container, as Azure's console does."""

    CONNECTOR_TYPE: ClassVar[str] = "blob"
    SCHEME: ClassVar[str] = "azblob"
    CONTAINER_FIELD: ClassVar[str] = "container"
    CONFIG_SCHEMA: ClassVar[dict[str, ConnectorConfigField]] = {
        "container": ConnectorConfigField(type="string", label="Container", required=True),
    }

    def __init__(self, objects: list[StoredObject] | None = None) -> None:
        self.objects = objects or []
        self.listed: list[tuple[str, str]] = []
        self.downloaded: list[tuple[str, str, Path]] = []

    def _objects(
        self,
        container: str,
        prefix: str,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> list[StoredObject]:
        self.listed.append((container, prefix))
        return self.objects

    def _download(
        self,
        container: str,
        key: str,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        self.downloaded.append((container, key, dest_path))
        dest_path.write_bytes(b"contents")


class TestWhatEveryObjectStoreGetsForFree:
    async def test_the_container_comes_from_the_field_the_store_names(self):
        """`bucket` is S3's and GCS's word; Azure's is `container`. A shared
        listing that read `config["bucket"]` would make the next store's form
        lie about itself."""
        connector = BlobConnector([StoredObject(key="a.md")])

        await connector.list_files({"container": "docs", "prefix": "legal/"}, None)

        assert connector.listed == [("docs", "legal/")]

    async def test_a_key_ending_in_a_slash_is_not_a_document(self):
        """A console that creates a "folder" writes a zero-byte object with that
        name. Ingested, it is a document with no bytes and no filename."""
        connector = BlobConnector(
            [StoredObject(key="legal/"), StoredObject(key="legal/nda.pdf", size=12)]
        )

        files = await connector.list_files({"container": "docs"}, None)

        assert [f.name for f in files] == ["nda.pdf"]

    async def test_the_dedup_key_is_scheme_container_and_key(self):
        """`source_path` is what the sync path matches a stored row on (#996), so
        it is built once here rather than per client."""
        connector = BlobConnector([StoredObject(key="legal/nda.pdf")])

        files = await connector.list_files({"container": "docs"}, None)

        assert files[0].source_path == "azblob://docs/legal/nda.pdf"
        assert files[0].id == "legal/nda.pdf"

    async def test_two_containers_holding_one_basename_stay_two_documents(self):
        """The collision #990 removed on the vector side, reached from here: the
        name is a display name and the key is the identity."""
        connector = BlobConnector(
            [StoredObject(key="a/readme.md"), StoredObject(key="b/readme.md")]
        )

        files = await connector.list_files({"container": "docs"}, None)

        assert {f.source_path for f in files} == {
            "azblob://docs/a/readme.md",
            "azblob://docs/b/readme.md",
        }

    async def test_a_listing_carries_the_size_and_the_modified_time(self):
        when = datetime.datetime(2026, 8, 20, 9, 30, tzinfo=datetime.UTC)
        connector = BlobConnector([StoredObject(key="a.md", size=41, modified_at=when)])

        files = await connector.list_files({"container": "docs"}, None)

        assert (files[0].size, files[0].modified_at) == (41, when)

    async def test_the_download_reads_the_container_back_out_of_the_source_path(
        self, tmp_path: Path
    ):
        """A `RemoteFile` reaches `_fetch` from a listing made earlier, and the
        config it is handed need not be the one that listed it - the address is."""
        connector = BlobConnector()

        landed = await connector.download_file(
            RemoteFile(
                id="legal/nda.pdf", name="nda.pdf", source_path="azblob://docs/legal/nda.pdf"
            ),
            tmp_path,
            config={"container": "ignored-here"},
        )

        assert connector.downloaded == [("docs", "legal/nda.pdf", tmp_path / "nda.pdf")]
        assert landed.read_bytes() == b"contents"

    async def test_a_name_climbing_out_of_the_sync_directory_is_refused(self, tmp_path: Path):
        """Inherited from `BaseSyncConnector.download_file`, and asserted here
        because it is the property a new store most easily loses: the destination
        is not the connector's to choose."""
        connector = BlobConnector()

        with pytest.raises(BadRequestError):
            await connector.download_file(
                RemoteFile(id="docs/..", name="..", source_path="azblob://docs/docs/.."),
                tmp_path,
                config={"container": "docs"},
            )

        assert connector.downloaded == []


class TestTheS3ConnectorStillListsWhatItListed:
    """The refactor is only correct if a stored source syncs unchanged."""

    @staticmethod
    def _client(pages: list[dict[str, Any]]) -> MagicMock:
        client = MagicMock()
        client.get_paginator.return_value.paginate.return_value = pages
        return client

    @staticmethod
    def _credential() -> AwsCredentialsSecret:
        return AwsCredentialsSecret(
            aws_access_key_id="AKIATENANT",
            aws_secret_access_key=SecretStr("tenant-secret"),
            region_name="eu-west-1",
        )

    async def test_a_bucket_listing_is_s3_addressed_and_skips_folder_markers(self):
        client = self._client(
            [
                {
                    "Contents": [
                        {"Key": "legal/", "Size": 0},
                        {
                            "Key": "legal/nda.pdf",
                            "Size": 12,
                            "LastModified": "2026-08-20T09:30:00+00:00",
                        },
                    ]
                }
            ]
        )
        with patch.object(S3Connector, "_get_s3_client", return_value=client):
            files = await S3Connector().list_files(
                {"bucket": "acme", "prefix": "legal/"}, self._credential()
            )

        assert [f.source_path for f in files] == ["s3://acme/legal/nda.pdf"]
        assert files[0].modified_at == datetime.datetime(2026, 8, 20, 9, 30, tzinfo=datetime.UTC)
        client.get_paginator.assert_called_once_with("list_objects_v2")
        client.get_paginator.return_value.paginate.assert_called_once_with(
            Bucket="acme", Prefix="legal/"
        )

    async def test_an_empty_prefix_is_omitted_rather_than_sent_empty(self):
        """What the connector did before it was a subclass, kept deliberately: a
        stored source with no prefix must make the same call it made yesterday."""
        client = self._client([{"Contents": []}])
        with patch.object(S3Connector, "_get_s3_client", return_value=client):
            await S3Connector().list_files({"bucket": "acme", "prefix": ""}, self._credential())

        client.get_paginator.return_value.paginate.assert_called_once_with(Bucket="acme")

    async def test_a_download_asks_the_client_for_the_key_it_listed(self, tmp_path: Path):
        client = MagicMock()
        client.download_file.side_effect = lambda bucket, key, path: Path(path).write_bytes(b"pdf")
        with patch.object(S3Connector, "_get_s3_client", return_value=client):
            landed = await S3Connector().download_file(
                RemoteFile(
                    id="legal/nda.pdf", name="nda.pdf", source_path="s3://acme/legal/nda.pdf"
                ),
                tmp_path,
                config={"bucket": "acme"},
                credential=self._credential(),
            )

        client.download_file.assert_called_once_with("acme", "legal/nda.pdf", str(landed))
        assert landed.read_bytes() == b"pdf"
