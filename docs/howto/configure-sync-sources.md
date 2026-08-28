# Configure sync sources

Sync sources pull documents from external services (Google Drive, S3/MinIO) into
knowledge collections on their own. Each source stores a connector type, a target
collection, connector-specific settings, a sync mode, an optional schedule, and
the id of the [vault secret](../secrets.md) that authenticates it.

When a sync runs, the connector lists remote files, downloads them to a
temporary directory, and feeds them through the standard ingestion pipeline
(parse, chunk, embed, store). A `SyncLog` entry records the outcome of
every sync operation.

### Architecture at a glance

| Component | Location | Role |
|-----------|----------|------|
| `BaseSyncConnector` | `app/services/rag/connectors/__init__.py` | Abstract base for all connectors |
| `RemoteFile` | `app/services/rag/connectors/__init__.py` | Pydantic model describing a remote file |
| `CONNECTOR_REGISTRY` | `app/services/rag/connectors/__init__.py` | Maps connector type strings to classes |
| `SyncSource` (DB model) | `app/db/models/sync_source.py` | Persists source configurations |
| `SyncLog` (DB model) | `app/db/models/sync_log.py` | Tracks individual sync operations |
| `SyncSourceService` | `app/services/sync_source.py` | Business logic for CRUD + trigger |
| RAG CLI commands | `app/commands/rag.py` | CLI interface for managing sources |
| RAG API routes | `app/api/routes/v1/rag.py` | REST API for managing sources |

## Quick start -- CLI

### List available connector types

```bash
# Shows all registered connectors (e.g. gdrive, s3)
uv run agenticos cmd rag-sources
```

### Add a Google Drive source -- sync every 2 hours

```bash
uv run agenticos cmd rag-source-add \
  --name "Legal docs" \
  --type gdrive \
  --org 0c8f2b1e-... \
  --collection legal \
  --config '{"folder_id": "1abc123def", "include_subfolders": true}' \
  --sync-mode new_only \
  --schedule 120
```

### Add an S3 source -- manual sync only

```bash
uv run agenticos cmd rag-source-add \
  --name "Marketing" \
  --type s3 \
  --org 0c8f2b1e-... \
  --collection marketing \
  --config '{"bucket": "my-docs", "prefix": "marketing/"}' \
  --sync-mode full \
  --schedule 0
```

### Trigger sync manually

```bash
# Sync a single source by ID
uv run agenticos cmd rag-source-sync <source-id>

# Sync all active sources
uv run agenticos cmd rag-source-sync --all
```

### Remove a source

```bash
uv run agenticos cmd rag-source-remove <source-id>
```

The `<source-id>` is a UUID printed when you create the source and shown
in the `rag-sources` listing.

## Quick start -- UI

1. Navigate to **Knowledge Base** and open the **Sync** tab.
2. Click **"+ Add Source"**.
3. Select a connector type (Google Drive, S3). The form fields are
   generated dynamically from the connector's `CONFIG_SCHEMA`.
4. Fill in the connector-specific config fields (e.g. folder ID, bucket
   name).
5. Choose a target collection, sync mode, and schedule interval.
6. Click **"Create Source"**.
7. Use the **"Sync Now"** button to trigger an immediate sync, or wait
   for the schedule to fire automatically.

The UI calls the same REST API documented below, so anything you can do
in the UI you can also do with `curl` or any HTTP client.

## Sync modes

| Mode | Behavior |
|------|----------|
| `full` | Re-sync everything. All files are (re-)ingested, existing documents replaced. |
| `new_only` | Add new files + update changed files. Uses SHA-256 hash to detect changes — unchanged files are skipped. |
| `update_only` | Only update files already in the collection. New files are skipped. Uses SHA-256 hash to skip unchanged files. |

!!! tip "`new_only` for most workflows"

    It adds new files and updates modified ones while skipping unchanged files,
    which is the fastest incremental sync. `update_only` refreshes existing
    documents without adding new ones; `full` is a clean re-import every time.

## Schedule

The `schedule_minutes` field controls how often the source syncs
automatically:

| Value | Meaning |
|-------|---------|
| `0` (or `null`) | Manual only -- trigger via CLI or UI |
| `30` | Every 30 minutes |
| `120` | Every 2 hours |
| `1440` | Once per day |

!!! warning "A schedule needs the Prefect runner"

    `check_scheduled_syncs_flow` is a Prefect deployment that wakes every 60
    seconds and fires whatever is due, so `schedule_minutes` does nothing without
    the `prefect-server` and `prefect-runner` containers `make dev` starts. With
    neither running, only a manual trigger (CLI, API or the UI) syncs anything.

## Google Drive setup

### 1. Create a service account

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (or select an existing one).
3. Enable the **Google Drive API**.
4. Go to **IAM & Admin > Service Accounts** and create a new service
   account.
5. Create a JSON key for the service account and download it.

### 2. Share your Drive folder

1. Open Google Drive and navigate to the folder you want to sync.
2. Click **Share** and add the service account email address (it looks
   like `name@project.iam.gserviceaccount.com`).
3. Grant at least **Viewer** access.

### 3. Give the source the key

Paste the contents of the JSON key file into the source's **Service Account
JSON** field. A `gdrive` source runs on the credential its own configuration
carries and on nothing else — there is no deployment-wide fallback, because one
would let a source's `folder_id` decide what is listed under the operator's
service account.

`GOOGLE_DRIVE_CREDENTIALS_FILE` in `.env` is for the `rag-sync-gdrive` CLI
command only.

### 4. Get the folder ID

The folder ID is the last segment of the Google Drive folder URL:

```
https://drive.google.com/drive/folders/1abc123def456ghi
                                        ^^^^^^^^^^^^^^^
                                        This is the folder ID
```

### 5. Google Drive connector config fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `folder_id` | string | Yes | -- | Google Drive folder ID from the URL |
| `include_subfolders` | boolean | No | `true` | Recursively include files from subfolders |

The service account itself is **not** a config field. Add it to the Vault as a
`gcp_service_account` credential and point the source at it with `secret_id`: it is
stored once and referenced by every source that needs it, rather than pasted into
each one ([#937](https://github.com/vstorm-co/agenticos/issues/937)). Posting it
under `config` is refused.

A `folder_id` may hold only what Google issues — letters, digits, `-` and `_`.
Anything else is refused when the source is created, because the id is
interpolated into the Drive query and a single quote in it widens what the query
lists.

Google Docs, Sheets, and Slides are automatically exported to portable
formats (PDF, XLSX, PPTX) during download. A file whose Drive name contains path
separators is written as one file inside the sync directory, never at the path
its name spells.

## S3 / MinIO setup

### 1. Configure the environment

Add the following variables to your `.env`:

```bash
S3_RAG_ENDPOINT=https://s3.amazonaws.com   # or your MinIO URL, e.g. http://localhost:9000
S3_RAG_ACCESS_KEY=your-access-key
S3_RAG_SECRET_KEY=your-secret-key
S3_RAG_REGION=us-east-1                    # required for AWS, optional for MinIO
```

For MinIO, the endpoint is typically `http://minio:9000` (Docker) or
`http://localhost:9000` (local).

### 2. S3 connector config fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `bucket` | string | Yes | -- | S3 bucket name |
| `prefix` | string | No | `""` | Key prefix to limit sync scope (e.g. `documents/legal/`). Leave empty for the entire bucket. |

## API reference

All sync source endpoints live under `/api/v1/rag/sync/`. Listing takes
`collections:view` and everything that changes a source takes `collections:edit`,
in both cases reaching the collection the source belongs to — there is no admin
role in it. See
[who may reach a collection](../file-processing.md#who-may-reach-a-collection).

### Sync sources CRUD

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/sync/sources` | List all configured sync sources |
| `POST` | `/api/v1/rag/sync/sources` | Create a new sync source |
| `PATCH` | `/api/v1/rag/sync/sources/{id}` | Update an existing sync source |
| `DELETE` | `/api/v1/rag/sync/sources/{id}` | Delete a sync source |
| `POST` | `/api/v1/rag/sync/sources/{id}/trigger` | Manually trigger a sync |

### Connectors & logs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/rag/sync/connectors` | List available connector types with config schemas |
| `GET` | `/api/v1/rag/sync/logs` | List sync history (filterable by `collection_name`) |

### Example: create a source via API

```bash
curl -X POST http://localhost:8000/api/v1/rag/sync/sources \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Legal Drive",
    "connector_type": "gdrive",
    "collection_name": "legal",
    "config": {
      "folder_id": "1abc123def",
      "include_subfolders": true
    },
    "sync_mode": "new_only",
    "schedule_minutes": 120
  }'
```

### Example: trigger a sync via API

```bash
curl -X POST http://localhost:8000/api/v1/rag/sync/sources/{source_id}/trigger \
  -H "Authorization: Bearer $TOKEN"
```

### Example: check sync history

```bash
curl http://localhost:8000/api/v1/rag/sync/logs?limit=10 \
  -H "Authorization: Bearer $TOKEN"
```

### Example: discover available connectors

```bash
curl http://localhost:8000/api/v1/rag/sync/connectors \
  -H "Authorization: Bearer $TOKEN"
```

The response includes each connector's `config_schema`, which the
frontend uses to render dynamic forms. It is also useful for building
integrations programmatically.

## Updating a source

You can update any subset of fields on an existing source with `PATCH`:

```bash
curl -X PATCH http://localhost:8000/api/v1/rag/sync/sources/{source_id} \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sync_mode": "full",
    "schedule_minutes": 60,
    "is_active": false
  }'
```

Updatable fields: `name`, `config`, `sync_mode`, `schedule_minutes`,
`is_active`, `collection_name`.

Set `is_active` to `false` to pause a source without deleting it.

## Monitoring sync operations

Every sync creates a `SyncLog` entry with the following fields:

| Field | Description |
|-------|-------------|
| `source` | Connector type or `"local"` for CLI ingestion |
| `collection_name` | Target collection |
| `status` | `running`, `done`, or `error` |
| `mode` | `full`, `new_only`, or `update_only` |
| `total_files` | Number of files discovered |
| `ingested` | Successfully ingested (new) |
| `updated` | Successfully re-ingested (replaced) |
| `skipped` | Skipped (already present or unchanged) |
| `failed` | Failed to ingest |
| `error_message` | Error details (if `status` is `error`) |
| `started_at` | When the sync started |
| `completed_at` | When the sync finished |

View logs via CLI output or the API:

```bash
curl http://localhost:8000/api/v1/rag/sync/logs?collection_name=legal&limit=5 \
  -H "Authorization: Bearer $TOKEN"
```

## Adding custom connectors

To add a new connector type (e.g. Notion, Confluence, Dropbox), see
[How to: Add a New Sync Connector](./add-sync-connector.md).

The short version:

1. Create a class inheriting `BaseSyncConnector` in
   `app/services/rag/connectors/`.
2. Implement `list_files()`, `_fetch()`, and optionally `validate_config()`.
3. Declare `SECRET_KIND` — what kind of vault secret authenticates it — and a
   `CONFIG_SCHEMA` of `ConnectorConfigField`s saying how to find the documents.
   The credential is never one of those fields.
4. Register it in `CONNECTOR_REGISTRY` in
   `app/services/rag/connectors/__init__.py`.

Once registered, the connector appears automatically in the CLI, API,
and UI.

## Troubleshooting

### "No sync sources configured"

You have not created any sources yet. Use `rag-source-add` (CLI) or
`POST /api/v1/rag/sync/sources` (API) to create one.

### "Unknown connector type"

The connector type you specified is not in `CONNECTOR_REGISTRY`. Check
available types with `rag-sources` or `GET /api/v1/rag/sync/connectors`.
Google Drive (`gdrive`) is available.
S3 (`s3`) is available.

### Google Drive: "this source has no credential"

The source's `secret_id` is empty, or the vault secret it named has been deleted.
Add the service account JSON to the Vault and choose it on the source's credential
step — `GOOGLE_DRIVE_CREDENTIALS_FILE` does not stand in for it, and only the
`rag-sync-gdrive` CLI command reads that setting.

### "A Google Drive source needs a service account credential"

The `secret_id` names a credential of the wrong kind — an AWS key pair, say. A Drive
source takes a `gcp_service_account` and an S3 source an `aws_credentials` pair; the
wizard offers only the matching ones, so this is reachable through the API.

### Google Drive: "folder ID may contain only letters, digits, '-' and '_'"

The value is not a Drive folder id. Take it from the folder URL: it is the last
segment, and nothing else in that URL belongs in the field.

### Google Drive: "Cannot access folder"

Make sure you shared the folder with the service account email. The
service account needs at least Viewer access.

### S3: "Cannot access bucket"

Verify that `S3_RAG_ACCESS_KEY`, `S3_RAG_SECRET_KEY`, and
`S3_RAG_ENDPOINT` are set correctly in `.env`. For MinIO, ensure the
endpoint includes the port (e.g. `http://localhost:9000`).

### Scheduled syncs are not running

A background task system must be running. Check that your worker process
is active:

Without a worker, only manual triggers via CLI or API will work.
