"""A sync source's names and identifiers are not this system's to trust.

Two refusals, both reachable by anyone who can put a file in a folder somebody
synced - which on a shared Drive folder is not necessarily the tenant:

- a file name is a label, not a path component, so `../../evil` must land inside
  the sync directory or not be written at all (#370);
- a folder id reaches the Drive query language, where a single quote closes the
  parent literal and the rest of the value is read as query (#369).

The assertions are on the consequence - what exists on disk afterwards, and the
query string the Drive client was handed - rather than on a helper having been
called.
"""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import AwsCredentialsSecret, GcpServiceAccountSecret

REPO_ROOT = Path(__file__).resolve().parents[2]
from app.services.rag.connectors import CONNECTOR_REGISTRY, BaseSyncConnector, RemoteFile
from app.services.rag.connectors.google_drive import GoogleDriveConnector
from app.services.rag.connectors.s3 import S3Connector
from app.services.rag.remote_names import checked_drive_folder_id, destination_within
from app.services.rag.sources.google_drive import GoogleDriveSource
from app.services.rag.sources.s3 import S3Source

pytestmark = pytest.mark.anyio


class _RecordingConnector(BaseSyncConnector):
    """A connector that writes a payload wherever the base class tells it to."""

    CONNECTOR_TYPE = "recording"

    async def list_files(self, config: dict, credential: object = None) -> list[RemoteFile]:
        return []

    async def _fetch(
        self, file: RemoteFile, dest_path: Path, config: dict, credential: object = None
    ) -> None:
        dest_path.write_bytes(b"payload")


class _Downloader:
    """Stands in for `MediaIoBaseDownload`: writes one chunk into the open handle."""

    def __init__(self, handle: Any, request: Any) -> None:
        self._handle = handle

    def next_chunk(self) -> tuple[None, bool]:
        self._handle.write(b"payload")
        return None, True


def _remote(name: str) -> RemoteFile:
    return RemoteFile(id="f1", name=name, source_path=f"gdrive://{name}")


class TestWhereARemoteFileMayBeWritten:
    def test_a_name_carrying_a_traversal_is_reduced_to_one_component(self, tmp_path: Path) -> None:
        assert destination_within(tmp_path, "../../evil.pdf") == tmp_path / "evil.pdf"

    def test_an_absolute_name_is_reduced_to_one_component(self, tmp_path: Path) -> None:
        assert (
            destination_within(tmp_path, "/home/app/.ssh/authorized_keys")
            == tmp_path / "authorized_keys"
        )

    @pytest.mark.parametrize("name", ["..", ".", "/", "", "../"])
    def test_a_name_that_is_no_component_at_all_is_refused(self, tmp_path: Path, name: str) -> None:
        """These resolve onto the directory itself, which is not a file to write."""
        with pytest.raises(BadRequestError) as exc:
            destination_within(tmp_path, name)
        # No field, and no copy of the name: whoever can drop a file in the
        # folder chose it, and this runs inside a sync where the reader is a
        # log rather than a form (#891).
        assert exc.value.details is None

    def test_a_name_with_a_null_byte_is_refused(self, tmp_path: Path) -> None:
        """`resolve()` raises `ValueError` on one, which is not an answer a caller can act on."""
        with pytest.raises(BadRequestError):
            destination_within(tmp_path, "quarterly\x00.pdf")

    def test_a_symlink_already_pointing_out_of_the_directory_is_refused(
        self, tmp_path: Path
    ) -> None:
        """The check is after `resolve()`, so the escape does not have to be in the name."""
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (sync_dir / "notes.md").symlink_to(outside / "notes.md")

        with pytest.raises(BadRequestError):
            destination_within(sync_dir, "notes.md")

    def test_an_ordinary_name_is_untouched(self, tmp_path: Path) -> None:
        """Reduction, not sanitizing: the spaces, the brackets and the suffix all survive."""
        assert (
            destination_within(tmp_path, "Q1 report (final).pdf")
            == tmp_path / "Q1 report (final).pdf"
        )


class TestNoConnectorChoosesItsOwnDestination:
    async def test_a_traversing_name_lands_inside_the_sync_directory(self, tmp_path: Path) -> None:
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()

        local = await _RecordingConnector().download_file(_remote("../pwned.txt"), sync_dir)

        assert local == sync_dir / "pwned.txt"
        assert local.read_bytes() == b"payload"
        assert list(tmp_path.iterdir()) == [sync_dir]

    async def test_a_name_that_is_no_component_writes_nothing(self, tmp_path: Path) -> None:
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()

        with pytest.raises(BadRequestError):
            await _RecordingConnector().download_file(_remote(".."), sync_dir)

        assert list(sync_dir.iterdir()) == []

    def test_no_shipped_connector_overrides_the_destination(self) -> None:
        """A connector added later inherits the answer because it cannot pick a path."""
        for connector_cls in CONNECTOR_REGISTRY.values():
            assert connector_cls.download_file is BaseSyncConnector.download_file


class TestTheGoogleDriveConnector:
    async def test_a_drive_file_named_with_a_traversal_stays_in_the_sync_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        service = MagicMock()
        service.files.return_value.get.return_value.execute.return_value = {
            "mimeType": "text/plain"
        }
        monkeypatch.setattr(
            "app.services.rag.connectors.google_drive.MediaIoBaseDownload", _Downloader
        )
        connector = GoogleDriveConnector()
        monkeypatch.setattr(connector, "_get_drive_service", lambda credential: service)

        local = await connector.download_file(_remote("../authorized_keys"), sync_dir, config={})

        assert local == sync_dir / "authorized_keys"
        assert local.read_bytes() == b"payload"
        assert not (tmp_path / "authorized_keys").exists()

    async def test_the_listing_query_constrains_to_one_parent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = MagicMock()
        service.files.return_value.list.return_value.execute.return_value = {"files": []}
        connector = GoogleDriveConnector()
        monkeypatch.setattr(connector, "_get_drive_service", lambda credential: service)

        await connector.list_files({"folder_id": "1AbC-dEf_2", "include_subfolders": False}, None)

        assert service.files.return_value.list.call_args.kwargs["q"] == (
            "'1AbC-dEf_2' in parents and trashed = false"
        )

    async def test_a_folder_id_carrying_a_quote_never_reaches_the_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        service = MagicMock()
        connector = GoogleDriveConnector()
        monkeypatch.setattr(connector, "_get_drive_service", lambda credential: service)

        with pytest.raises(BadRequestError) as exc:
            await connector.list_files(
                {"folder_id": "x' in parents or name contains 'salary"}, None
            )

        assert exc.value.details is None
        assert "salary" not in exc.value.message
        service.files.return_value.list.assert_not_called()

    async def test_a_hostile_sub_folder_id_is_refused_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The check sits where the query is built, so the recursion passes through it."""
        service = MagicMock()
        service.files.return_value.list.return_value.execute.return_value = {
            "files": [
                {"id": "x' or name contains 'pay", "mimeType": "application/vnd.google-apps.folder"}
            ]
        }
        connector = GoogleDriveConnector()
        monkeypatch.setattr(connector, "_get_drive_service", lambda credential: service)

        with pytest.raises(BadRequestError):
            await connector.list_files({"folder_id": "1AbC", "include_subfolders": True}, None)

    @pytest.mark.parametrize(
        "folder_id",
        # The last two are what `dict[str, object]` lets a JSON body carry into
        # a field the form calls a string. Both are truthy, so they reach the
        # allowlist rather than stopping at the required-field check that `""`
        # is here to pin.
        [
            "x' in parents or name contains 'salary",
            "1AbC dEf",
            "",
            "a" * 257,
            "../1AbC",
            1234,
            {"id": "1AbC"},
        ],
    )
    async def test_a_source_with_a_hostile_folder_id_is_refused_at_creation(
        self, folder_id: object
    ) -> None:
        refusal = await GoogleDriveConnector().validate_config(
            {"service_account_json": "{}", "folder_id": folder_id}
        )
        assert refusal is not None
        assert refusal.message

    async def test_a_refused_folder_id_names_the_input_it_was_typed_into(self) -> None:
        """The wizard draws four inputs; a sentence about one of them marks none (#897)."""
        refusal = await GoogleDriveConnector().validate_config(
            {"service_account_json": "{}", "folder_id": "x' in parents"}
        )
        assert refusal is not None
        assert refusal.field == "folder_id"

    async def test_a_source_with_a_real_folder_id_is_accepted(self) -> None:
        assert (
            await GoogleDriveConnector().validate_config(
                {"service_account_json": "{}", "folder_id": "1AbC-dEf_2"}
            )
            is None
        )

    async def test_a_missing_required_field_is_still_refused_first(self) -> None:
        """`folder_id` is the only required field left. The credential used to be
        one and is now a vault secret the source references, so there is nothing
        for `validate_config` to say about it (#937)."""
        refusal = await GoogleDriveConnector().validate_config({})
        assert refusal is not None
        assert "Google Drive Folder ID" in refusal.message
        assert refusal.field == "folder_id"

        assert await GoogleDriveConnector().validate_config({"folder_id": "1AbC"}) is None

    def test_a_source_without_its_own_credential_is_refused(self) -> None:
        """There is no deployment-wide fallback for a tenant's query to run under."""
        with pytest.raises(BadRequestError) as exc:
            GoogleDriveConnector()._get_drive_service(None)
        assert exc.value.details is None


class TestTheS3Connector:
    async def test_a_key_naming_no_file_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = MagicMock()
        connector = S3Connector()
        monkeypatch.setattr(connector, "_get_s3_client", lambda config: client)

        with pytest.raises(BadRequestError):
            await connector.download_file(
                RemoteFile(id="docs/..", name="..", source_path="s3://bucket/docs/.."),
                tmp_path,
                config={},
            )

        client.download_file.assert_not_called()


class TestTheLegacyCliSources:
    """`rag-sync-gdrive` and `rag-sync-s3` reach `sources/`, which had both defects."""

    async def test_the_drive_source_refuses_a_folder_id_from_the_shell(self) -> None:
        source = GoogleDriveSource.__new__(GoogleDriveSource)
        source.service = MagicMock()

        with pytest.raises(BadRequestError):
            await source.list_files(path="x' in parents or name contains 'salary")

        source.service.files.return_value.list.assert_not_called()

    async def test_the_drive_source_constrains_to_one_parent(self) -> None:
        source = GoogleDriveSource.__new__(GoogleDriveSource)
        source.service = MagicMock()
        source.service.files.return_value.list.return_value.execute.return_value = {"files": []}

        await source.list_files(path="1AbC-dEf_2")

        assert source.service.files.return_value.list.call_args.kwargs["q"] == (
            "trashed = false and '1AbC-dEf_2' in parents "
            "and mimeType != 'application/vnd.google-apps.folder'"
        )

    async def test_the_drive_source_writes_a_traversing_name_inside_the_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        source = GoogleDriveSource.__new__(GoogleDriveSource)
        source.service = MagicMock()
        source.service.files.return_value.get.return_value.execute.return_value = {
            "name": "../../evil.txt",
            "mimeType": "text/plain",
        }
        monkeypatch.setattr(
            "app.services.rag.sources.google_drive.MediaIoBaseDownload", _Downloader
        )

        local = await source.download_file("f1", sync_dir)

        assert local == sync_dir / "evil.txt"
        assert not (tmp_path / "evil.txt").exists()

    async def test_the_s3_source_writes_a_traversing_key_inside_the_directory(
        self, tmp_path: Path
    ) -> None:
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        source = S3Source.__new__(S3Source)
        source.bucket = "docs"
        source.client = MagicMock()
        source.client.download_file.side_effect = lambda bucket, key, path: Path(path).write_bytes(
            b"payload"
        )

        local = await source.download_file("../../evil.txt", sync_dir)

        assert local == sync_dir / "evil.txt"
        assert not (tmp_path / "evil.txt").exists()


class TestTheDriveIdentifierItself:
    @pytest.mark.parametrize("folder_id", ["root", "1AbC-dEf_2", "a" * 256])
    def test_an_identifier_google_could_have_issued_is_answered_unchanged(
        self, folder_id: str
    ) -> None:
        assert checked_drive_folder_id(folder_id) == folder_id

    @pytest.mark.parametrize(
        "folder_id",
        # The homoglyph is U+0410, Cyrillic capital A - ruff flags the
        # confusable, which is exactly why it belongs in this list. `None` and
        # the number are what a JSON body can put in a `dict[str, object]`.
        ["", "a" * 257, "1AbC'", "1AbC\\", "1AbC dEf", "1AbC\n", "1AbC/dEf", "1АbC", None, 1],  # noqa: RUF001
    )
    def test_anything_else_is_refused(self, folder_id: object) -> None:
        """A homoglyph is refused without the allowlist having to know it is one."""
        with pytest.raises(BadRequestError):
            checked_drive_folder_id(folder_id)


class TestEveryWritePathJudgesTheConfig:
    """A value refused at creation cannot be reached by patching it in later.

    `create_source` asked the connector; `update_source` and `clone_source` did
    not, so the checks this module adds were reachable only on one of the three
    routes that persist a config. The sink check inside the connector still
    caught a hostile value, but it answered in a background sync log rather than
    to the caller who sent it - which is the half of #369 that made the refusal
    worth having at the route.
    """

    async def test_patching_in_a_hostile_folder_id_is_refused(self) -> None:
        from app.services.sync_source import _refuse_an_invalid_config

        with pytest.raises(BadRequestError):
            await _refuse_an_invalid_config(
                {
                    "service_account_json": "{}",
                    "folder_id": "x' in parents or name contains 'salary",
                },
                "gdrive",
            )

    async def test_a_config_the_connector_accepts_passes(self) -> None:
        from app.services.sync_source import _refuse_an_invalid_config

        await _refuse_an_invalid_config(
            {"service_account_json": "{}", "folder_id": "1AbC_-def"}, "gdrive"
        )


# The shape `GcpServiceAccountSecret` insists on: a service account key, not any
# JSON document. The validator is why - it refuses a file somebody grabbed by
# mistake rather than storing it and failing at the first API call.
_SERVICE_ACCOUNT_JSON = json.dumps(
    {
        "type": "service_account",
        "project_id": "a-project",
        "client_email": "sync@a-project.iam.gserviceaccount.com",
        # Present but not PEM-shaped: the validator asks for the field, and a
        # fixture that looked like a real key would trip `detect-private-key`.
        "private_key": "not-a-key",
    }
)


def test_the_s3_connector_refuses_when_the_source_names_no_credential() -> None:
    """No deployment-wide fallback, which is the Drive removal applied to S3.

    Both settings default to empty, so the old `or settings.S3_RAG_ACCESS_KEY`
    resolved to `None` and boto3 fell through to the container's own credential
    chain - the caller's `bucket` then chose what was read under whatever the
    task role could reach.

    Since #937 the credential is a vault secret rather than a config field, and
    the absence of one is a refusal rather than a client signed with nothing:
    building a client that would have been signed by the container's role is the
    thing worth not doing, and `None` keys only failed later, at the API call.
    """
    connector = S3Connector()
    with (
        patch("app.services.rag.connectors.s3.boto3.client") as client,
        patch.object(settings, "S3_RAG_ACCESS_KEY", "operator-key"),
        patch.object(settings, "S3_RAG_SECRET_KEY", "operator-secret"),
        pytest.raises(BadRequestError, match="no credential"),
    ):
        connector._get_s3_client({"bucket": "somebody-elses"}, None)

    client.assert_not_called()


def test_the_s3_connector_signs_with_the_vault_credential_it_was_given() -> None:
    """And with nothing else: the operator's settings are not consulted."""
    connector = S3Connector()
    credential = AwsCredentialsSecret(
        aws_access_key_id="AKIATENANT",
        aws_secret_access_key=SecretStr("tenant-secret"),
        region_name="eu-west-1",
    )
    with (
        patch("app.services.rag.connectors.s3.boto3.client") as client,
        patch.object(settings, "S3_RAG_ACCESS_KEY", "operator-key"),
        patch.object(settings, "S3_RAG_SECRET_KEY", "operator-secret"),
    ):
        connector._get_s3_client({"bucket": "ours"}, credential)

    kwargs = client.call_args.kwargs
    assert kwargs["aws_access_key_id"] == "AKIATENANT"
    assert kwargs["aws_secret_access_key"] == "tenant-secret"
    assert kwargs["region_name"] == "eu-west-1"


def test_the_s3_connector_refuses_a_credential_of_the_wrong_kind() -> None:
    """A service account is not an AWS key pair, and failing here says so - where
    failing at the API call says `InvalidAccessKeyId` in a sync log."""
    connector = S3Connector()
    wrong = GcpServiceAccountSecret(service_account_json=SecretStr(_SERVICE_ACCOUNT_JSON))

    with (
        patch("app.services.rag.connectors.s3.boto3.client") as client,
        pytest.raises(BadRequestError, match="AWS key pair"),
    ):
        connector._get_s3_client({"bucket": "ours"}, wrong)

    client.assert_not_called()
