"""S3/MinIO sync connector for RAG ingestion.

The credential is an `AwsCredentialsSecret` in the organization's vault, named
by the source's `secret_id` and unsealed by whoever runs the sync. It used to be
`access_key_id` and `secret_access_key` fields inside the source's own `config`,
encrypted with one deployment-wide Fernet key (#937).

`endpoint_url` and `region` stay in the config and still fall back to the
`S3_RAG_*` settings: neither names a principal.
"""

import asyncio
import logging
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
from app.services.rag.connectors import (
    BaseSyncConnector,
    ConfigRefusal,
    ConnectorConfig,
    RemoteFile,
)

logger = logging.getLogger(__name__)


class S3Connector(BaseSyncConnector):
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

    async def validate_config(self, config: ConnectorConfig) -> ConfigRefusal | None:
        """Validate required fields only - connectivity is checked at sync time."""
        return await super().validate_config(config)

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> list[RemoteFile]:
        """List files in an S3 bucket/prefix."""
        bucket = config["bucket"]
        prefix = config.get("prefix", "")

        def _list() -> list[RemoteFile]:
            client = self._get_s3_client(config, credential)
            paginator = client.get_paginator("list_objects_v2")
            params: dict[str, Any] = {"Bucket": bucket}
            if prefix:
                params["Prefix"] = prefix

            files: list[RemoteFile] = []
            for page in paginator.paginate(**params):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key.endswith("/"):
                        continue

                    name = Path(key).name
                    modified_at = None
                    if obj.get("LastModified"):
                        modified_at = obj["LastModified"]
                        if isinstance(modified_at, str):
                            modified_at = datetime.fromisoformat(modified_at)

                    files.append(
                        RemoteFile(
                            id=key,
                            name=name,
                            mime_type=None,
                            size=obj.get("Size"),
                            modified_at=modified_at,
                            source_path=f"s3://{bucket}/{key}",
                        )
                    )

            return files

        return await asyncio.to_thread(_list)

    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        """Download a file from S3 to the path the base class chose."""
        parts = file.source_path.replace("s3://", "").split("/", 1)
        bucket = parts[0]

        def _download() -> None:
            client = self._get_s3_client(config, credential)
            client.download_file(bucket, file.id, str(dest_path))
            logger.info(
                "Downloaded s3://%s/%s (%d bytes)", bucket, file.id, dest_path.stat().st_size
            )

        await asyncio.to_thread(_download)
