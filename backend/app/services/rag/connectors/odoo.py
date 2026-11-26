"""Explicit Odoo business fields as knowledge, using an organization account."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from app.core.exceptions import BadRequestError, ExternalServiceError
from app.core.secret_kinds import StorableSecret
from app.services.integrations import ODOO_MODELS, PRODUCTS, OdooAccountToken
from app.services.integrations import execute_odoo_operation as execute
from app.services.rag.connectors import (
    BaseSyncConnector,
    ConfigRefusal,
    ConnectorConfig,
    RemoteFile,
    RemoteListing,
)


class OdooKnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: UUID = Field(
        title="Connected Odoo account",
        description="An organization Odoo account connected in Vault.",
    )
    product_id: Literal[
        "odoo_contacts",
        "odoo_crm",
        "odoo_sales",
        "odoo_accounting",
        "odoo_inventory",
        "odoo_projects",
    ] = Field(title="Business area")
    fields: list[str] = Field(
        default_factory=lambda: ["display_name"],
        min_length=1,
        max_length=50,
        title="Fields to index",
        description="Only these Odoo fields are downloaded. Inspect the product's field metadata first.",
    )


def _account(credential: StorableSecret | None, selected: OdooKnowledgeConfig) -> OdooAccountToken:
    if (
        not isinstance(credential, OdooAccountToken)
        or credential.connection_id != selected.connection_id
    ):
        raise BadRequestError(message="Choose the source's organization Odoo account")
    return credential


class OdooConnector(BaseSyncConnector):
    CONNECTOR_TYPE: ClassVar[str] = "odoo"
    DISPLAY_NAME: ClassVar[str] = "Odoo business records"
    CONFIG_MODEL: ClassVar[type[BaseModel]] = OdooKnowledgeConfig

    async def validate_config(self, config: ConnectorConfig) -> ConfigRefusal | None:
        try:
            selected = OdooKnowledgeConfig.model_validate(config)
        except ValidationError:
            return ConfigRefusal(
                message="Choose an Odoo account, business area and fields", field="product_id"
            )
        if any(re.fullmatch(r"[a-z][a-z0-9_]*", field) is None for field in selected.fields):
            return ConfigRefusal(message="Use Odoo field names without paths", field="fields")
        return None

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> RemoteListing:
        selected = OdooKnowledgeConfig.model_validate(config)
        account = _account(credential, selected)
        files: list[RemoteFile] = []
        complete = True
        for noun, model in ODOO_MODELS[selected.product_id]:
            operation = next(
                op for op in PRODUCTS[selected.product_id].operations if op.id == f"search_{noun}"
            )
            last_id = 0
            for _ in range(50):
                result = await execute(
                    account.credential,
                    operation,
                    parameters={},
                    query={},
                    body={
                        "domain": [["id", ">", last_id]],
                        "fields": ["id", "display_name", "write_date"],
                        "limit": 100,
                        "order": "id asc",
                    },
                )
                rows = result.get("result")
                if not isinstance(rows, list):
                    raise ExternalServiceError(message="Odoo returned an invalid record listing")
                for row in rows:
                    if not isinstance(row, dict) or type(row.get("id")) is not int:
                        raise ExternalServiceError(
                            message="Odoo returned an invalid record identifier"
                        )
                    record_id = row["id"]
                    if not isinstance(record_id, int) or record_id <= last_id:
                        raise ExternalServiceError(
                            message="Odoo returned an unordered record listing"
                        )
                    stamp = row.get("write_date")
                    if not isinstance(stamp, str):
                        raise ExternalServiceError(
                            message="Odoo returned an invalid record timestamp"
                        )
                    try:
                        modified = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                    except ValueError:
                        raise ExternalServiceError(
                            message="Odoo returned an invalid record timestamp"
                        ) from None
                    last_id = record_id
                    files.append(
                        RemoteFile(
                            id=f"{model}:{record_id}",
                            name=f"{model}-{record_id}.md",
                            mime_type="text/markdown",
                            modified_at=modified,
                            source_path=f"odoo://{account.connection_id}/{model}/{record_id}",
                        )
                    )
                if len(rows) < 100:
                    break
            else:
                complete = False
        return RemoteListing(
            files=files,
            complete=complete,
            problems=[] if complete else ["Odoo reached the listing limit; removals were skipped"],
        )

    async def _fetch(
        self,
        file: RemoteFile,
        dest_path: Path,
        config: ConnectorConfig,
        credential: StorableSecret | None,
    ) -> None:
        selected = OdooKnowledgeConfig.model_validate(config)
        account = _account(credential, selected)
        model, _, raw_id = file.id.partition(":")
        noun = next(
            (noun for noun, allowed in ODOO_MODELS[selected.product_id] if allowed == model), None
        )
        if noun is None or not raw_id.isdecimal() or len(raw_id) > 15 or int(raw_id) <= 0:
            raise BadRequestError(message="This Odoo record is outside the selected business area")
        operation = next(
            op for op in PRODUCTS[selected.product_id].operations if op.id == f"read_{noun}"
        )
        fields: list[JsonValue] = list(selected.fields)
        result = await execute(
            account.credential,
            operation,
            parameters={},
            query={},
            body={"ids": [int(raw_id)], "fields": fields},
        )
        rows = result.get("result")
        if (
            not isinstance(rows, list)
            or len(rows) != 1
            or not isinstance(rows[0], dict)
            or rows[0].get("id") != int(raw_id)
        ):
            raise ExternalServiceError(
                message="The selected Odoo record was removed or is no longer accessible"
            )
        dest_path.write_text(
            f"# {model} {raw_id}\n\n" + json.dumps(rows[0], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
