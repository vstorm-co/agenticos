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

import datetime
import inspect
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field, SecretStr

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import AwsCredentialsSecret, StorableSecret
from app.services.rag import remote_limits
from app.services.rag.connectors import ConnectorConfig, RemoteFile
from app.services.rag.connectors.object_store import ObjectStoreConnector, StoredObject
from app.services.rag.connectors.s3 import S3Connector
from app.services.rag.remote_limits import DownloadAllowance, ListingBudget

pytestmark = pytest.mark.anyio


class BlobConfig(BaseModel):
    container: str = Field(title="Container")


class BlobConnector(ObjectStoreConnector):
    """A store that calls its container a container, as Azure's console does."""

    CONNECTOR_TYPE: ClassVar[str] = "blob"
    SCHEME: ClassVar[str] = "azblob"
    CONTAINER_FIELD: ClassVar[str] = "container"
    CONFIG_MODEL: ClassVar[type[BaseModel]] = BlobConfig

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
        budget: ListingBudget,
    ) -> list[StoredObject]:
        self.listed.append((container, prefix))
        budget.observe_page()
        return self.objects

    def _download(
        self,
        container: str,
        key: str,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
        allowance: DownloadAllowance,
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

        files = (await connector.list_files({"container": "docs"}, None)).files

        assert [f.name for f in files] == ["nda.pdf"]

    async def test_the_dedup_key_is_scheme_container_and_key(self):
        """`source_path` is what the sync path matches a stored row on (#996), so
        it is built once here rather than per client."""
        connector = BlobConnector([StoredObject(key="legal/nda.pdf")])

        files = (await connector.list_files({"container": "docs"}, None)).files

        assert files[0].source_path == "azblob://docs/legal/nda.pdf"
        assert files[0].id == "legal/nda.pdf"

    async def test_two_containers_holding_one_basename_stay_two_documents(self):
        """The collision #990 removed on the vector side, reached from here: the
        name is a display name and the key is the identity."""
        connector = BlobConnector(
            [StoredObject(key="a/readme.md"), StoredObject(key="b/readme.md")]
        )

        files = (await connector.list_files({"container": "docs"}, None)).files

        assert {f.source_path for f in files} == {
            "azblob://docs/a/readme.md",
            "azblob://docs/b/readme.md",
        }

    async def test_a_listing_carries_the_size_and_the_modified_time(self):
        when = datetime.datetime(2026, 8, 20, 9, 30, tzinfo=datetime.UTC)
        connector = BlobConnector([StoredObject(key="a.md", size=41, modified_at=when)])

        files = (await connector.list_files({"container": "docs"}, None)).files

        assert (files[0].size, files[0].modified_at) == (41, when)

    @pytest.mark.security
    async def test_a_listing_stops_before_materializing_more_than_its_entry_ceiling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(remote_limits, "MAX_SYNC_ITEMS", 2)
        connector = BlobConnector(
            [StoredObject(key="a.md"), StoredObject(key="b.md"), StoredObject(key="c.md")]
        )

        with pytest.raises(BadRequestError):
            await connector.list_files({"container": "docs"}, None)

    @pytest.mark.security
    async def test_a_listing_refuses_declared_sync_work_over_its_byte_ceiling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(remote_limits, "MAX_SYNC_BYTES", 3)
        connector = BlobConnector(
            [StoredObject(key="a.md", size=2), StoredObject(key="b.md", size=2)]
        )

        with pytest.raises(BadRequestError):
            await connector.list_files({"container": "docs"}, None)

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
            listing = await S3Connector().list_files(
                {"bucket": "acme", "prefix": "legal/"}, self._credential()
            )
        files = listing.files

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

    @pytest.mark.security
    async def test_empty_provider_pages_cannot_bypass_the_listing_work_ceiling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(remote_limits, "MAX_SYNC_PAGES", 1)
        client = self._client([{"Contents": []}, {"Contents": []}])

        with (
            patch.object(S3Connector, "_get_s3_client", return_value=client),
            pytest.raises(BadRequestError),
        ):
            await S3Connector().list_files({"bucket": "acme", "prefix": ""}, self._credential())

    def test_the_listing_is_never_materialized_beside_the_one_it_builds(self):
        """`_objects` yields, and this is the guard on that.

        The shared `_listing` builds the bounded `RemoteFile` list the sync path
        reads; a `_objects` that returned a list of `StoredObject` would still
        materialize the provider's unbounded answer before the shared budget saw
        one entry. Asserted on the function rather than on a measurement, because
        the shape is what is easy to revert by accident.
        """
        assert inspect.isgeneratorfunction(S3Connector._objects)

    async def test_a_download_asks_the_client_for_the_key_it_listed(self, tmp_path: Path):
        client = MagicMock()
        body = MagicMock()
        body.iter_chunks.return_value = [b"pdf"]
        client.get_object.return_value = {"Body": body, "ContentLength": 3}
        with patch.object(S3Connector, "_get_s3_client", return_value=client):
            landed = await S3Connector().download_file(
                RemoteFile(
                    id="legal/nda.pdf", name="nda.pdf", source_path="s3://acme/legal/nda.pdf"
                ),
                tmp_path,
                config={"bucket": "acme"},
                credential=self._credential(),
            )

        client.get_object.assert_called_once_with(Bucket="acme", Key="legal/nda.pdf")
        body.iter_chunks.assert_called_once_with(chunk_size=remote_limits.DOWNLOAD_CHUNK_BYTES)
        body.close.assert_called_once_with()
        assert landed.read_bytes() == b"pdf"

    @pytest.mark.security
    async def test_a_declared_oversized_object_is_refused_before_s3_is_called(
        self, tmp_path: Path
    ) -> None:
        client = MagicMock()
        file = RemoteFile(
            id="large.pdf",
            name="large.pdf",
            size=settings.MAX_UPLOAD_SIZE_MB * remote_limits.MIB + 1,
            source_path="s3://acme/large.pdf",
        )

        with (
            patch.object(S3Connector, "_get_s3_client", return_value=client),
            pytest.raises(BadRequestError),
        ):
            await S3Connector().download_file(
                file,
                tmp_path,
                config={"bucket": "acme"},
                credential=self._credential(),
            )

        client.get_object.assert_not_called()

    @pytest.mark.security
    async def test_an_s3_object_with_no_size_is_stopped_at_the_streamed_ceiling(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(remote_limits, "MAX_SYNC_BYTES", 3)
        client = MagicMock()
        body = MagicMock()
        body.iter_chunks.return_value = [b"ab", b"cd"]
        client.get_object.return_value = {"Body": body}
        connector = S3Connector()

        with patch.object(S3Connector, "_get_s3_client", return_value=client):
            with pytest.raises(BadRequestError):
                await connector.download_file(
                    RemoteFile(
                        id="unknown.pdf",
                        name="unknown.pdf",
                        source_path="s3://acme/unknown.pdf",
                    ),
                    tmp_path,
                    config={"bucket": "acme"},
                    credential=self._credential(),
                )

            with pytest.raises(BadRequestError):
                await connector.download_file(
                    RemoteFile(
                        id="second.pdf",
                        name="second.pdf",
                        source_path="s3://acme/second.pdf",
                    ),
                    tmp_path,
                    config={"bucket": "acme"},
                    credential=self._credential(),
                )

        assert not (tmp_path / "unknown.pdf").exists()
        client.get_object.assert_called_once_with(Bucket="acme", Key="unknown.pdf")
        body.close.assert_called_once_with()


class TestTheS3EndpointIsChecked:
    """A source's own `endpoint_url` meets the address check, on the form and at sync."""

    @pytest.fixture(autouse=True)
    def _dns(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
        answers: dict[str, str] = {}

        def fake_getaddrinfo(host: str, port: int, **_kwargs: object) -> list[tuple[Any, ...]]:
            return [(2, 1, 6, "", (answers.get(host, "93.184.216.34"), port))]

        monkeypatch.setattr("app.core.sanitize.socket.getaddrinfo", fake_getaddrinfo)
        return answers

    @staticmethod
    def _config(endpoint: str | None) -> ConnectorConfig:
        return {"bucket": "acme", "endpoint_url": endpoint}

    async def test_a_public_endpoint_and_none_at_all_are_accepted(self) -> None:
        assert await S3Connector().validate_config(self._config("https://s3.example.com")) is None
        assert await S3Connector().validate_config(self._config(None)) is None
        assert await S3Connector().validate_config({"bucket": "acme"}) is None

    async def test_a_private_endpoint_is_refused(self, _dns: dict[str, str]) -> None:
        _dns["minio"] = "10.0.0.9"

        refusal = await S3Connector().validate_config(self._config("http://minio:9000"))

        assert refusal is not None
        assert refusal.field == "endpoint_url"

    async def test_a_listed_private_endpoint_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch, _dns: dict[str, str]
    ) -> None:
        monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", ["minio"])
        _dns["minio"] = "10.0.0.9"

        assert await S3Connector().validate_config(self._config("http://minio:9000")) is None

    @pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254"])
    async def test_a_loopback_or_metadata_endpoint_is_refused_even_when_listed(
        self, monkeypatch: pytest.MonkeyPatch, _dns: dict[str, str], address: str
    ) -> None:
        monkeypatch.setattr(settings, "OUTBOUND_PRIVATE_ALLOWLIST", ["minio"])
        _dns["minio"] = address

        refusal = await S3Connector().validate_config(self._config("http://minio:9000"))

        assert refusal is not None
        assert refusal.field == "endpoint_url"

    async def test_a_config_the_model_refuses_is_reported_on_its_field(self) -> None:
        refusal = await S3Connector().validate_config({"bucket": "acme", "prefix": 3})

        assert refusal is not None
        assert refusal.field == "prefix"

    async def test_building_a_client_checks_the_endpoint_again(self, _dns: dict[str, str]) -> None:
        _dns["minio"] = "10.0.0.9"
        credential = TestTheS3ConnectorStillListsWhatItListed._credential()

        with pytest.raises(BadRequestError):
            S3Connector()._get_s3_client(self._config("http://minio:9000"), credential)

    async def test_building_a_client_for_a_public_endpoint_passes_it_on(self) -> None:
        credential = TestTheS3ConnectorStillListsWhatItListed._credential()

        client = S3Connector()._get_s3_client(self._config("https://s3.example.com"), credential)

        assert client.meta.endpoint_url == "https://s3.example.com"
