# Configure sync sources

Sync sources pull documents from external services (Google Drive, S3/MinIO, a
public website, a Git repository) into knowledge collections on their own. Each source stores a
connector type, a target collection, connector-specific settings, a sync mode, an
optional schedule, and the id of the [vault secret](../secrets.md) that
authenticates it - a website needs none.

When a sync runs, the connector lists remote files, downloads them to a
temporary directory, and feeds them through the standard ingestion pipeline
(parse, chunk, embed, store). When the listing is complete, documents the source
brought in earlier and no longer lists are removed. A `SyncLog` entry records the
outcome of every sync operation.

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
# Shows all registered connectors (e.g. gdrive, s3, git)
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

### Add a Git source -- a repository's docs, nightly

```bash
uv run agenticos cmd rag-source-add \
  --name "Handbook" \
  --type git \
  --org 0c8f2b1e-... \
  --collection handbook \
  --config '{"repository_url": "https://github.com/acme/handbook.git", "branch": "main", "path_prefix": "docs"}' \
  --sync-mode new_only \
  --schedule 1440
```

Then choose its access token as the source's credential in the UI, or send
`secret_id` with a `PATCH` — see [Git repository setup](#git-repository-setup).

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
3. Select a connector type (Google Drive, S3, Website, Git
   repository). The form fields are
   generated from the JSON Schema of the connector's `CONFIG_MODEL`. A website
   has no credential step.
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

### What a sync removes

In every mode, a sync removes the documents its source brought in earlier and no
longer lists: a page taken off the site, a file deleted from the Drive folder, an
object removed from the bucket. The sync log counts them under `removed`.

It removes nothing unless the listing was **complete**. A crawl that stopped at its
page limit, or could not read one of the pages, has not seen what it does not list.
That run keeps every document and says so in the sync log's message. The next sync
with a complete listing removes what is gone. A document that could not be removed
counts as a failed file, and the next sync tries again.

One sync of a source runs at a time. A sync started while another sync of the same
source is still running does not start, and its log says so.

Only the source's own documents are removed. An upload, or a document another
source brought into the same collection, is never touched. When two sources on
one collection list the same document, it stays until both stop listing it. A
document ingested before its source recorded this (September 2026) is kept until
a sync of the source lists it again.

### What a second sync does

A sync after the first one does as little as the source lets it:

- **An unchanged file costs a download, not an embedding.** Its SHA-256 matches
  the stored document's, so it is counted as `skipped` and never parsed or
  embedded again.
- **An unchanged source costs one request.** A connector that can say what its
  whole content is at — a Git branch's head commit — records that after every run
  that finished with nothing failed. The next `new_only` or `update_only` run that
  finds the same value, under the same configuration, stops before it lists
  anything: its log shows no files processed, and it removes nothing. Changing the
  configuration, the collection or the mode makes the next run read everything
  again, and `full` never stops early.
- **A file a stopped sync left half-done is put right.** A worker that stopped
  after storing a file's vectors, and before recording them, leaves them untracked.
  The next sync of that source deletes what nothing tracks and ingests the file
  again, and it does not stop early while such a file is waiting.

A run with a failed file records no state, so the next run reads the source in
full and retries it.

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

## Website setup

A `web` source reads a public website, usually a product's documentation site. It
needs no credential and no vault entry. Give it a start URL, and it either
follows links from that page or reads the pages a sitemap lists.

```bash
uv run agenticos cmd rag-source-add \
  --name "Product docs" \
  --type web \
  --org 0c8f2b1e-... \
  --collection product-docs \
  --config '{"root_url": "https://docs.example.com/guide/", "max_depth": 3}' \
  --sync-mode new_only \
  --schedule 1440
```

### Website connector config fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `root_url` | string | Yes | -- | The page the crawl starts from. Its host is the only host the source reads. |
| `max_depth` | integer | No | `2` | How many links away from the start URL to follow, `0` to `10`. `0` reads the start page only. |
| `path_prefix` | string | No | the start URL's folder | Only pages whose path starts with this are read. `https://docs.example.com/guide/intro` reads `/guide/` by default; set `/` for the whole host. |
| `sitemap_url` | string | No | -- | Read the pages this sitemap lists instead of following links. It must be on the start URL's host, and use `https://` when the start URL does. A sitemap index is followed to its sitemaps. |
| `max_pages` | integer | No | `500` | The crawl stops after reading this many pages, `1` to `5000`. |

### What bounds a crawl

- **One host and one path.** Links to other hosts, and to paths outside
  `path_prefix`, are not followed. A redirect that leaves them is not followed
  either. A start URL on `https://` is never left for `http://`: a link or a
  redirect to a cleartext page is not followed.
- **The deployment's network is out of reach.** Every request - robots.txt, the
  sitemap, each page and each redirect - is checked against the same SSRF policy as
  webhooks and MCP servers. It is sent to the address that passed the check. A start
  URL that resolves to a private, loopback, link-local or cloud-metadata address is
  refused when you save the source.
- **robots.txt is obeyed** for sitemaps and pages, including `Crawl-delay` up to
  ten seconds. The crawler identifies itself as `AgenticOS-Crawler`. It waits at
  least half a second between requests, and a page that says `noindex` or
  `nofollow` is honoured. A page that a sitemap still lists after it says
  `noindex`, or after it is gone, is removed from the collection.
- **Size and time.** A page larger than 5 MB is not read. The crawl stops at
  `max_pages`. A sync stops reading the site after six hours, and a sync that
  stopped removes nothing.

Each page is stored as a Markdown document holding its text and the URL it came
from, without its query string. Navigation, headers, footers and scripts are left out. A page is re-embedded
only when its text changes. A new build stamp or tracking script in the markup does
not count as a change.

### Who can read what it imports

A website source has no credential, so its reach is what the site shows to anyone
on the internet. It never gets past a login. Everything it imports is searchable by
everyone who can search the collection it feeds, as with any other source. See
[who ends up able to read what a source ingested](../file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

Only HTML pages are imported. A PDF or other file linked from a page is not
downloaded.

## Git repository setup

A `git` source reads a repository's documentation over HTTPS — GitHub, GitLab or
any other host that serves git over HTTPS. It needs the clone URL and an access
token, not either platform's API.

### 1. Issue a token for the one repository

**A token's reach is the source's reach.** Everything the source ingests becomes
searchable by whoever can read the collection, so a token that can read every
private repository its owner can is a token that can publish all of them to that
audience. See [who ends up able to read what a source
ingested](../file-processing.md#who-ends-up-able-to-read-what-a-source-ingested).

- **GitHub:** a fine-grained personal access token, *Only select repositories*,
  with the one repository, and **Contents: Read-only** as its only permission.
- **GitLab:** a project access token on the one project, role **Reporter**, scope
  **`read_repository`** only.

Give it an expiry date. When it expires, the source's next sync fails with *the
repository refused the source's token*, and the fix is a new token in the same
vault secret.

### 2. Add it to the Vault

Add the token to the Vault as a **Git access token**, with the **host** it
belongs to: `github.com`, `gitlab.com`, or your own server such as
`git.example.com:8443`. A host with non-ASCII letters is entered in its encoded
form, such as `xn--bcher-kva.example` for `bücher.example`. Then choose the token
on the source's credential step. It is sent
as an HTTP `Authorization` header, never in the URL, and never in a command line
another process can read.

**The host is the token's, not the source's.** Whoever edits a source chooses
its repository URL, and a token is sent only to the host it was added with. So
editing a source cannot aim the organization's token at another server, and no
other kind of key, such as a model provider's API key, can be chosen for a Git
source at all.

### 3. Git connector config fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `repository_url` | string | Yes | -- | The HTTPS clone URL, e.g. `https://github.com/acme/handbook.git`. No user name or token in it. |
| `branch` | string | No | `main` | The branch to read. |
| `path_prefix` | string | No | -- | A directory inside the repository, e.g. `docs`. Leave empty for the whole repository. |
| `include` | list of strings | No | `**/*.md`, `**/*.txt` | Which files to ingest, as `.gitignore`-style patterns relative to `path_prefix`. |

The default is documentation, not the whole tree: a repository's source code is
not a corpus, and ingesting it fills a knowledge base with code nobody asked to
search. Add a pattern such as `**/*.pdf` for another format the collection's
parser reads. A pattern cannot start with `!`.

Each file is a document whose address is
`git://<host>/<owner>/<repo>@<branch>/<path>`, with `:<port>` after the host when
the port is not 443. The branch is part of the address, so two sources reading two
branches of one repository into one collection keep separate documents.

### 4. What a sync transfers

The first request of every sync is `git ls-remote` for the branch — about a
kilobyte. When the head commit has not moved since the last clean run, the sync
stops there. When it has moved, the connector makes a shallow, partial, sparse
clone: one commit, and only the files the include patterns match. A monorepo's
documentation therefore costs its documentation, not its source tree.

Before the clone writes anything to the worker's disk, the connector measures
every file it would write. A file over the knowledge base's document cap
(`MAX_UPLOAD_SIZE_MB`, 50 MB by default), or more than 512 MB of files in all, is
refused, and nothing is written.

Symbolic links and submodules are not followed, and a link is not ingested as a
document.

### Network rules

The URL must be `https://`. Its host is resolved once and checked like any other
address a tenant chooses: a host that resolves to a private, loopback or
link-local address is refused when the source is saved and again when it syncs,
and git connects only to the addresses that check approved. Redirects are not
followed. A deployment behind an egress proxy (`HTTPS_PROXY`) keeps using it; the
proxy then resolves the host itself.

The worker image ships `git`. A worker built from another image needs `git`
2.37 or newer on its `PATH`.

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
| `failed` | Failed to ingest, including pages or files the listing could not read, and documents that could not be removed |
| `removed` | Removed because the source no longer lists them (see [what a sync removes](#what-a-sync-removes)) |
| `error_message` | What went wrong, or why nothing was removed. A run can be `done` and still have a message, for example when a crawl stopped at its page limit |
| `started_at` | When the sync started |
| `completed_at` | When the sync finished |

View logs via CLI output or the API:

```bash
curl http://localhost:8000/api/v1/rag/sync/logs?collection_name=legal&limit=5 \
  -H "Authorization: Bearer $TOKEN"
```

## Adding custom connectors

To add a new connector type (e.g. Notion, Confluence, Dropbox), see
[Add a sync connector](./add-sync-connector.md).

The short version:

1. Create a class inheriting `BaseSyncConnector` in
   `app/services/rag/connectors/`.
2. Implement `list_files()`, `_fetch()`, and optionally `validate_config()`.
3. Declare `SECRET_KIND` — what kind of vault secret authenticates it — and a
   `CONFIG_MODEL`, a Pydantic model saying how to find the documents. The
   credential is never one of its fields.
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
Website (`web`) is available.
Git (`git`) is available.

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

### Website: "resolves to private/internal address"

The start URL, or the sitemap, points inside the deployment's network, or its name
resolves there. A website source reads only public addresses. To index an internal
site, publish its pages somewhere public, or upload the files directly.

### Website: "The site's robots.txt could not be read, so it was not crawled"

`/robots.txt` on the start URL's host timed out or answered with a server error
(5xx) three times in a row. The crawler does not guess what an unreachable
robots.txt would allow, so the run stops. A missing robots.txt (404) or a
forbidden one (403) means no rules, and the crawl goes ahead.

### Website: "The start URL … did not lead to an HTML page"

The start URL answered 404, redirected to another host or outside `path_prefix`,
or served something other than HTML. Open it in a browser, then use the address
it ends at as `root_url`.

### Website: "robots.txt does not allow the start URL"

The site asks crawlers to stay out of that path. Choose a start URL the site
allows, or ask the site's owner to allow `AgenticOS-Crawler`.

### Website: "… answered HTTP 403" or "… could not be reached"

The page needs a login, or the site refused the crawler. It failed after three
attempts if the answer was a timeout, 429 or 5xx. Each page like this counts as a
failed file. Nothing is removed on that run, because the pages behind it were not
seen.

### "The source could not be listed completely, so documents it may no longer hold were kept"

The listing stopped short: a crawl reached `max_pages`, or some pages could not
be read. What was found was ingested, and nothing was removed. Raise `max_pages`,
or narrow the crawl with `path_prefix`, until a run finishes without this message.

### Git: "The repository refused the source's token"

The token has expired, was revoked, or cannot read this repository. Issue a new
one as described in [Git repository setup](#git-repository-setup) and replace the
value of the vault secret the source uses; every source using that secret picks
it up on its next sync.

### Git: "The repository was not found, or the source's token cannot see it"

Check the clone URL first. A private repository answers *not found* rather than
*forbidden* to a token that cannot read it, so a fine-grained token issued for a
different repository reads as this.

### Git: "The repository has no branch named …"

The `branch` field names a branch the repository does not have. Its default is
`main`; an older repository's default branch may be `master`.

### Git: "… is … MB, and a synced file may be at most … MB"

A file the include patterns match is larger than the knowledge base's document
cap. Narrow `include` or `path_prefix` so that the file is left out. Nothing was
written for this sync.

### Git: "… over the … MB one sync may check out"

All the files the include patterns match are more than 512 MB together. Narrow
`include` or `path_prefix`, or split the repository into more than one source,
each with its own prefix.

### Git: "This token was added for …, and the repository is on …"

The source's repository is on a different host from the one its token was added
with. Either the URL is wrong, or the source needs a token added for that host.
Nothing was sent to the repository's host.

### Git: "A Git source needs a Git access token"

The source names a secret of another kind, such as an API key. Add the token as a
**Git access token**, with its host, and choose that one.

### "Another sync of this source is still running"

A run was triggered while another run of the same source was in progress, so it
did not start. The run in progress finishes normally; trigger again after it if
the source changed meanwhile.

### Git: "… resolves to a private address"

The repository's host resolves inside the deployment's network, so the source is
refused. A self-hosted Git server on an internal address cannot be reached by a
sync source.

### Git: "git is not installed on this worker"

The worker runs from an image without `git`. The shipped `backend/Dockerfile`
installs it; a custom image needs it added.

### Git: a sync finished with no files processed

The branch's head commit is the one the last clean run read, under the same
configuration, so there was nothing to do. Switch the source to `full` for one run
to read everything again regardless.

### Scheduled syncs are not running

A background task system must be running. Check that your worker process
is active:

Without a worker, only manual triggers via CLI or API will work.
