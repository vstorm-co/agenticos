
# How to: Add a New Sync Connector

## Architecture

Sync connectors are pluggable adapters that fetch files from external systems
(cloud storage, SaaS APIs, etc.) for ingestion into the RAG pipeline.

### Key classes

| Class | Location | Purpose |
|-------|----------|---------|
| `BaseSyncConnector` | `app/services/rag/connectors/__init__.py` | Abstract base class for all connectors |
| `remote_names` | `app/services/rag/remote_names.py` | Where a remote name may be written, and what may reach a query |
| `RemoteFile` | `app/services/rag/connectors/__init__.py` | Pydantic model describing a remote file |
| `ConfigRefusal` | `app/services/rag/connectors/__init__.py` | Why a config is not acceptable, and which field of it |
| `ConnectorConfigField` | `app/schemas/sync_source.py` | One declared field: its type, whether it is required, its label |
| `ConnectorConfig` | `app/services/rag/connectors/__init__.py` | The source's own config document, as the wizard posted it |
| `CONNECTOR_REGISTRY` | `app/services/rag/connectors/__init__.py` | Dict mapping connector type strings to classes |
| `SyncSource` | `app/db/models/sync_source.py` | Database model storing source configurations |
| `SyncLog` | `app/db/models/sync_log.py` | Database model tracking sync operations |

### Flow

1. User creates a **SyncSource** (connector type + config + collection name +
   the id of the vault secret that authenticates it)
2. User triggers a **sync** (via API, CLI, or scheduled task)
3. Whoever runs the sync unseals that secret and hands it in; the connector's
   `list_files()` returns `list[RemoteFile]`
4. For each file, `BaseSyncConnector.download_file()` decides where it may land
   and calls the connector's `_fetch()` to write it there
5. The ingestion pipeline parses, chunks, embeds, and stores each file
6. A **SyncLog** entry records the result

### A connector does not choose the destination

`download_file()` is concrete and is not overridden. It resolves
`RemoteFile.name` against the sync directory and confirms containment before a
byte is written, then hands `_fetch()` a `dest_path` to write to. A remote name
is attacker-controlled from this system's point of view — anyone who can share a
file into a synced folder chooses it, and `../../../etc/…` is a legal name on
Google Drive — so a connector that picked its own path would be one refusal per
connector to remember. Write to the path you are given, and nothing else.

The same applies to any caller-supplied value a connector puts into a **query**:
check it where the query is built, against what the remote system can actually
issue. `app/services/rag/remote_names.py` holds both answers.

### A connector does not hold its own credential either

`CONFIG_SCHEMA` says how to **find** the documents and nothing more. The
credential is a vault secret the source references by id, unsealed by whoever
runs the sync and handed in as `credential` — so a connector declares what kind
of secret it needs (`SECRET_KIND`) and reads nothing from `config` to
authenticate with.

A field for a token in `CONFIG_SCHEMA` is a credential in a JSONB column, which
is what migration `0042` and #937 removed. There is no deployment-wide fallback
to reach for either: a source runs on the credential it names or it does not run,
because a fallback means one tenant's `folder_id` chooses what is read under the
*operator's* identity.

## Step-by-Step: Notion Connector

This example implements a Notion connector that fetches pages from a Notion
workspace.

### 1. Create the connector file

```python
# app/services/rag/connectors/notion.py
import asyncio
import logging
from pathlib import Path
from typing import ClassVar

from app.core.exceptions import BadRequestError
from app.core.secret_kinds import ApiKeySecret, SecretKind, StorableSecret
from app.schemas.sync_source import ConnectorConfigField
from app.services.rag.connectors import (
    BaseSyncConnector,
    ConfigRefusal,
    ConnectorConfig,
    RemoteFile,
)

logger = logging.getLogger(__name__)


class NotionConnector(BaseSyncConnector):
    """Sync connector for Notion pages."""

    CONNECTOR_TYPE: ClassVar[str] = "notion"
    DISPLAY_NAME: ClassVar[str] = "Notion"
    # Which vault secret authenticates this connector. The wizard offers the
    # organization's matching secrets and nothing else.
    SECRET_KIND: ClassVar[SecretKind] = SecretKind.API_KEY

    # CONFIG_SCHEMA is used for:
    #   - API validation when creating/updating sync sources
    #   - Dynamic form generation in the frontend UI
    # It holds no credential - see "A connector does not hold its own
    # credential either" above.
    CONFIG_SCHEMA: ClassVar[dict[str, ConnectorConfigField]] = {
        "database_id": ConnectorConfigField(
            type="string",
            default="",
            label="Database ID",
            help="Limit sync to a specific Notion database (optional)",
        ),
        "include_subpages": ConnectorConfigField(
            type="boolean", default=True, label="Include sub-pages"
        ),
    }

    def _client(self, credential: StorableSecret | None):
        """The Notion client this source's own credential opens.

        Raises:
            BadRequestError: the source names no credential, its secret has been
                deleted, or the secret is not an API key.
        """
        from notion_client import Client

        if credential is None:
            raise BadRequestError(
                message=(
                    "This Notion source has no credential. Pick an API key in "
                    "the Vault and point the source at it."
                )
            )
        if not isinstance(credential, ApiKeySecret):
            raise BadRequestError(
                message="A Notion source needs an API key, and the one it names is not one."
            )
        return Client(auth=credential.api_key.get_secret_value())

    async def list_files(
        self, config: ConnectorConfig, credential: StorableSecret | None
    ) -> list[RemoteFile]:
        """List Notion pages available for sync."""
        database_id = config.get("database_id", "")

        def _list() -> list[RemoteFile]:
            notion = self._client(credential)
            files: list[RemoteFile] = []

            if database_id:
                # Query a specific database
                response = notion.databases.query(database_id=database_id)
                pages = response.get("results", [])
            else:
                # Search all accessible pages
                response = notion.search(filter={"property": "object", "value": "page"})
                pages = response.get("results", [])

            for page in pages:
                page_id = page["id"]
                title = "Untitled"
                # Extract title from properties
                for prop in page.get("properties", {}).values():
                    if prop.get("type") == "title" and prop.get("title"):
                        title = prop["title"][0].get("plain_text", "Untitled")
                        break

                files.append(
                    RemoteFile(
                        id=page_id,
                        name=f"{title}.md",
                        mime_type="text/markdown",
                        size=None,
                        modified_at=page.get("last_edited_time"),
                        source_path=f"notion://{page_id}",
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
        """Export a Notion page as Markdown to the path the base class chose."""
        def _download() -> None:
            notion = self._client(credential)

            # `dest_path` is already confirmed to be inside the sync directory.
            # Do not build a path from `file.name` — see "A connector does not
            # choose the destination" above.

            # Fetch page blocks and convert to markdown
            # (simplified — use a library like notion2md in practice)
            content = f"# {file.name.replace('.md', '')}\n\nPage content here..."
            dest_path.write_text(content)

            logger.info(f"Exported Notion page {file.id} -> {dest_path}")

        await asyncio.to_thread(_download)

    async def validate_config(self, config: ConnectorConfig) -> ConfigRefusal | None:
        """Refuse a config the wizard can still fix.

        Connectivity is not checked here: `validate_config` sees the config and
        not the credential, so "can this key reach Notion" is a question for the
        first sync. What it can answer is the shape of what was typed.
        """
        refusal = await super().validate_config(config)
        if refusal is not None:
            return refusal

        database_id = config.get("database_id", "")
        if database_id and not database_id.replace("-", "").isalnum():
            # `field=` names one input, and the sync-source wizard marks it.
            # Name it as `CONFIG_SCHEMA` does; where it sits in the request body
            # is not a connector's to know.
            return ConfigRefusal(
                message="A Notion database id is letters, digits and dashes",
                field="database_id",
            )
        return None
```

`validate_config` answers *why not*, or `None` when the config is acceptable.
`ConfigRefusal(message="…", field="database_id")` names one: `SyncSourceService`
roots it against the payload (`config.database_id`), raises it with
`refused_field`, and the wizard marks that input. Name the field as
`CONFIG_SCHEMA` does — where it sits in the request body is not a connector's to
know.

If a connector does check connectivity somewhere, never put the client's own
exception text in the message — an SDK puts the request it was making in there,
and that routinely carries a URL with a key in it. Log it and refuse in your own
words.

### 2. Register in CONNECTOR_REGISTRY

Edit `app/services/rag/connectors/__init__.py` and add:

```python
from app.services.rag.connectors.notion import NotionConnector

CONNECTOR_REGISTRY["notion"] = NotionConnector
```

### 3. Add dependency (if needed)

If the connector requires a third-party package, add it to `pyproject.toml`:

```bash
uv add notion-client
```

### 4. Test via CLI

```bash
# Store the credential once, then point a source at it
uv run agenticos cmd rag-source-add \
    --org <organization-id> \
    --connector notion \
    --secret-id <vault-secret-id> \
    --config '{"database_id": "abc123"}' \
    --collection knowledge-base
```

`--secret-id` names an entry in that organization's vault; the token never
appears on the command line or in the source's config.

### 5. Test via API

```bash
# Create sync source
curl -X POST http://localhost:8000/api/v1/rag/sync/sources \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Engineering Wiki",
        "connector_type": "notion",
        "collection_name": "knowledge-base",
        "secret_id": "<vault-secret-id>",
        "config": {
            "database_id": "abc123",
            "include_subpages": true
        }
    }'

# Trigger sync
curl -X POST http://localhost:8000/api/v1/rag/sync/sources/{source_id}/sync \
    -H "Authorization: Bearer $TOKEN"

# Check sync status
curl http://localhost:8000/api/v1/rag/sync/logs \
    -H "Authorization: Bearer $TOKEN"
```

## CONFIG_SCHEMA Reference

The `CONFIG_SCHEMA` class variable defines how to **find** a source's documents.
The frontend reads it from the `GET /api/v1/rag/sync/connectors` endpoint to
render the form fields, and `validate_config` reads it to refuse a config that
is missing one.

Each entry is a `ConnectorConfigField`, not a bare mapping. That is what makes a
misspelled key a type error where it is written: `CONFIG_SCHEMA` used to be
`dict[str, dict[str, Any]]`, so a declaration that said `"require": True`
disabled that field's check silently and the wizard drew a required field as
optional (#562).

### Supported field types

`type` is one of four, because those are the four the wizard draws — a fifth
would fall through to a text input and collect the value wrongly, so
`ConnectorFieldType` refuses it.

| Type | UI Widget | Python type |
|------|-----------|-------------|
| `"string"` | Text input | `str` |
| `"boolean"` | Switch | `bool` |
| `"integer"` | Number input | `int` |
| `"textarea"` | Multi-line text | `str` |

### Field properties

| Property | Required | Description |
|----------|----------|-------------|
| `type` | Yes | One of the four above |
| `required` | No | Whether the field must be provided. Defaults to `False` |
| `label` | No | What the UI calls it, and what a refusal names. Defaults to the key |
| `help` | No | Tooltip/description text |
| `default` | No | Placeholder the form shows for an optional field |

There is no `secret` property, and there is nowhere to add one: a credential is
a vault secret the source references by id, so `SECRET_KIND` is how a connector
says what it needs.

### Example

```python
CONFIG_SCHEMA: ClassVar[dict[str, ConnectorConfigField]] = {
    "workspace": ConnectorConfigField(
        type="string",
        required=True,
        label="Workspace",
        help="Which workspace to read",
    ),
    "max_files": ConnectorConfigField(
        type="integer", default=100, label="Max files to sync"
    ),
    "recursive": ConnectorConfigField(
        type="boolean", default=True, label="Include nested items"
    ),
}
```

## Tips

- Set `RemoteFile.source_path` to a unique URI (e.g., `notion://page_id`) — this is used for deduplication across syncs
- Use `asyncio.to_thread()` to wrap blocking SDK calls so they don't block the event loop
- Implement `validate_config()` to test connectivity when users create sync sources — it prevents misconfigured sources, and a `ConfigRefusal` naming a `field` is what makes the wizard mark that input rather than show a sentence over four of them
- Declare `SECRET_KIND` and read the credential from the `credential` argument. A credential never goes in `CONFIG_SCHEMA`, and there is no deployment-wide fallback to fall back to
- Settings in `app/core/config.py` and `.env` are for values that name no principal — where a store is, not who is asking (`S3_RAG_ENDPOINT` is the shape)
- `_fetch()` writes to the `dest_path` it is handed and returns nothing — the base class answers where that is, and the ingestion pipeline handles everything from there
