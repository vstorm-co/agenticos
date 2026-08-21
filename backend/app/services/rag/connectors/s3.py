"""S3/MinIO sync connector for RAG ingestion.

The credential is an `AwsCredentialsSecret` in the organization's vault, named
by the source's `secret_id` and unsealed by whoever runs the sync. It used to be
`access_key_id` and `secret_access_key` fields inside the source's own `config`,
encrypted with one deployment-wide Fernet key (#937).

`endpoint_url` and `region` stay in the config and still fall back to the
`S3_RAG_*` settings: neither names a principal.

What is left here is boto3's vocabulary and nothing else - the listing loop, the
`source_path` shape and the destination are `ObjectStoreConnector`'s, so an Azure
or GCS connector is a client rather than a second copy of them (#988).
"""

import logging
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

import boto3
from botocore.client import BaseClient
from botocore.config import Config

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.core.secret_kinds import AwsCredentialsSecret, SecretKind, StorableSecret
from app.schemas.sync_source import ConnectorConfigField
from app.services.rag.connectors import ConnectorConfig
from app.services.rag.connectors.object_store import ObjectStoreConnector, StoredObject

logger = logging.getLogger(__name__)


class S3Connector(ObjectStoreConnector):
    """S3-compatible sync connector.

    Works with AWS S3, MinIO, and any S3-compatible storage.

    The key pair is an `AwsCredentialsSecret` unsealed from the organization's
    vault, named by the source's `secret_id`. It used to sit in the per-source
    `config` dict encrypted with one deployment-wide key (#937). The endpoint and
    region still fall back to `S3_RAG_*`: neither names a principal, they say
    where the store is rather than who is asking.
    """

    CONNECTOR_TYPE: ClassVar[str] = "s3"
    DISPLAY_NAME: ClassVar[str] = "S3 / MinIO"
    SECRET_KIND: ClassVar[SecretKind] = SecretKind.AWS_CREDENTIALS
    SCHEME: ClassVar[str] = "s3"
    CONTAINER_FIELD: ClassVar[str] = "bucket"
    CONFIG_SCHEMA: ClassVar[dict[str, ConnectorConfigField]] = {
        "bucket": ConnectorConfigField(type="string", label="Bucket Name", required=True),
        "prefix": ConnectorConfigField(
            type="string",
            label="Path Prefix",
            help="e.g. 'documents/legal/' - leave empty for entire bucket",
            default="",
        ),
        "endpoint_url": ConnectorConfigField(
            type="string",
            label="Custom Endpoint URL",
            help="For MinIO or compatible services (e.g., http://minio:9000). Leave empty for AWS S3.",
        ),
        "region": ConnectorConfigField(type="string", label="Region", default="us-east-1"),
    }

    def _get_s3_client(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> BaseClient:
        """Build a boto3 S3 client from the vault secret the source names.

        The key and secret come from the organization's vault and nowhere else.
        They used to fall back to `S3_RAG_ACCESS_KEY` / `S3_RAG_SECRET_KEY`, and
        that is the same shape removed from the Drive connector alongside it: a
        fallback means the caller's `bucket` chooses what is read under the
        *operator's* identity rather than their own, which turns one field of a
        source's configuration into a reach across organizations. Worse than the
        Drive case, because both settings default to empty - so the fallback
        resolved to `None`, boto3 fell through to the container's own credential
        chain, and the reach was whatever the task role could see.

        Only the endpoint and region still fall back. Neither names a principal;
        they say where the store is, not who is asking. The region prefers the
        credential's own, since an AWS key pair is issued against one.

        Raises:
            BadRequestError: the source names no credential, its secret has been
                deleted, or the secret is not an AWS key pair.
        """
        if credential is None:
            raise BadRequestError(
                message=(
                    "This S3 source has no credential. Pick an AWS key pair in the "
                    "Vault and point the source at it."
                )
            )
        if not isinstance(credential, AwsCredentialsSecret):
            raise BadRequestError(
                message=("An S3 source needs an AWS key pair, and the one it names is not one.")
            )
        client_kwargs: dict[str, Any] = {
            "aws_access_key_id": credential.aws_access_key_id,
            "aws_secret_access_key": credential.aws_secret_access_key.get_secret_value(),
            "region_name": config.get("region") or credential.region_name or settings.S3_RAG_REGION,
        }
        if credential.aws_session_token is not None:
            client_kwargs["aws_session_token"] = credential.aws_session_token.get_secret_value()
        endpoint = config.get("endpoint_url") or settings.S3_RAG_ENDPOINT
        if endpoint:
            client_kwargs["endpoint_url"] = endpoint
        return boto3.client("s3", **client_kwargs, config=Config(signature_version="s3v4"))

    def _objects(
        self,
        container: str,
        prefix: str,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> Iterator[StoredObject]:
        """One page at a time, as `list_objects_v2` hands them over.

        A generator, so a bucket of a million keys is one page in memory rather
        than a list of all of them beside the one the caller is building.

        `Prefix` is omitted rather than sent empty, which is what the connector
        did before this became a subclass: boto3 accepts `Prefix=""` and means
        the same thing by it, and the two are kept the same call so a stored
        source lists exactly what it listed yesterday.

        boto3 hands `LastModified` over as a `datetime`; the string branch came
        with this loop and stays with it, in the client's own method, because
        which of the two arrives is the client's own vocabulary.
        """
        client = self._get_s3_client(config, credential)
        params: dict[str, Any] = {"Bucket": container}
        if prefix:
            params["Prefix"] = prefix

        for page in client.get_paginator("list_objects_v2").paginate(**params):
            for obj in page.get("Contents", []):
                modified_at = obj.get("LastModified")
                if isinstance(modified_at, str):
                    modified_at = datetime.fromisoformat(modified_at)
                yield StoredObject(key=obj["Key"], size=obj.get("Size"), modified_at=modified_at)

    def _download(
        self,
        container: str,
        key: str,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        self._get_s3_client(config, credential).download_file(container, key, str(dest_path))
