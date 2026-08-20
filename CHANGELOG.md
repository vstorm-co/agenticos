# Changelog

Notable changes to AgenticOS. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Two things are versioned separately from this file and worth knowing about:

- **`SPEC_VERSION`** — the agent spec format, currently **9**. A published agent
  and a client's exported YAML both carry it, so it only ever moves forward with a
  migration that keeps old documents loading. See
  [the spec reference](docs/reference/spec.md).
- **The migration chain** — `backend/alembic/versions/`, squashed to a single
  `0001_baseline` for this first version. Revision ids named below (`0038`,
  `0059`, `0066`) are history: they describe when something changed, not a file
  that still exists. Schema changes are listed here by what they do.

## [Unreleased]

## [0.0.224] - 2026-08-20

Only the thumb whose request is in flight spins.

### Fixed

- **Rating an answer spun both thumbs.** The spinner was keyed on
  `isLoading && currentRating !== <the other value>`, and an unrated message has
  `currentRating === null` - true for both thumbs at once, which is the normal
  case rather than an edge one. It is keyed on *which* button's request is in
  flight now, so the other thumb stays a thumb. (#928)

## [0.0.223] - 2026-08-20

An object store's connector is a client, not a copy of the listing loop.

### Changed

- **`S3Connector` is an `ObjectStoreConnector` subclass**, with no behaviour
  change: a stored source lists and downloads exactly what it did before.
  #938 made Azure Blob and GCS conditional on this shape existing first, and the
  condition is now met - each of those is a client, a `SCHEME` and a
  `CONNECTOR_TYPE` rather than a second copy of the listing. The shared class
  holds the pagination, the `<scheme>://<container>/<key>` address the sync path
  matches a row on, the skip for a key ending in `/` (a console's "folder", which
  would ingest as a document with no bytes and no name), and the destination,
  which is the base class's answer and the property a new store most easily
  loses. (#988)
- A subclass says which `CONFIG_SCHEMA` field names its container - `bucket` for
  S3 and GCS, `container` for Azure - because a form should say what the store's
  own console says. Both of its hooks are blocking, run on a worker thread,
  because all three SDKs are synchronous. (#988)
- `S3Connector.validate_config` is gone: an override that called `super()` and
  added nothing. (#988)

### Performance

- **An object listing is converted as it arrives.** The refactor first built a
  complete list of the shared listing type and then allocated the complete
  `RemoteFile` list beside it, where the connector before it kept only the
  second - on a bucket of a million keys, a previously working sync running out
  of memory. The listing yields, and the conversion happens inside the same
  worker thread, so one entry exists at a time beside the list being built.
  Found by the automated review on the branch. (#988)

## [0.0.222] - 2026-08-20

The sync wizard says who will be able to read what a source ingests.

### Added

- **The step that decides a source's collection now names the audience.** Access
  is decided at the collection and there is no per-document isolation inside one,
  so everything the credential can reach becomes readable by everyone who can read
  that collection - a Confluence token issued for a whole instance, pointed at an
  `org` collection, publishes the instance to every member holding
  `collections:view`. The decision is the operator's, deliberately; what was wrong
  is that it was made silently. One sentence per scope: `personal` is its owner,
  `org` is everyone who can view the collection, `app` is anybody in the
  deployment. (#982)
- **The credential is named alongside the audience**, because the pair is the
  decision: a credential's own permissions are a ceiling nothing here can raise,
  while `config` narrows the reach and cannot be relied on to keep it narrow. A
  connector that authenticates with nothing has none to name and the sentence does
  not invent one, and neither does one whose reader holds no `secrets:view`.
  (#982)
- **Cloning says it too**, which is the reachable half of "repointing re-asks": a
  clone references the same vault secret and names a different collection, so the
  audience changes while nothing about the credential does. Repointing an existing
  source has no screen to ask on - `PATCH` on `collection_name` is reachable
  through the API and the CLI only, where the audit entry added in 0.0.221 is what
  records it. (#982)

### Fixed

- **The knowledge-base page no longer reads the vault on every load.** The
  wizard mounts whether or not it is open, so a credential lookup in its own body
  fired `/secrets` and `/secrets/kinds` on each page load - including for members
  holding no `secrets:view`, who get a refusal and a retry of it. The lookup lives
  in the notice, which renders inside the dialog. (#982)

## [0.0.221] - 2026-08-20

Who bound a credential to a collection is recorded.

### Fixed

- **Creating, cloning, repointing and deleting a sync source left no audit
  entry.** A source binds a credential to a collection, and access to what it
  ingests is decided at the collection - so the row is the platform's
  authorization decision for everything that credential can reach, and nothing
  recorded who made it. `sync_source.created`, `.updated` and `.deleted` name the
  actor, the connector, the collection and the *id* of the secret. (#983)
- **A clone is recorded as a creation naming the row it came from.** It points a
  credential somebody already scoped at a different collection, so the audience
  changes while nothing about the credential does - the decision in this set that
  is easiest to miss. (#983)
- **An update names the fields it changed, never their values**, one of them
  being `config` - a place a credential has been posted before (#937). An update
  that moves the source to another collection also records the one it left,
  because a rename and a change of audience are otherwise the same entry. (#983)

### Changed

- **A null audit actor now means one of two things**, and the `action` says
  which: the approval expiry sweep, and an operator command at the deployment's
  shell (`rag-source-add`, `rag-source-remove`), which have nobody at a keyboard
  to name. Reading `ctx.subject_id` there - as every HTTP path does - would have
  turned two working commands into an `AuthorizationError`. (#983)
- Three sentences said the audit actor column is `NOT NULL`
  (`docs/permissions.md`, `docs/governance.md`, `AuthContext.subject_id`). It is
  nullable, and has been since the expiry sweep needed it; the reason
  `subject_id` raises is that an authenticated path has a person, not that the
  database would refuse. (#983)

## [0.0.220] - 2026-08-20

A status parameter with one value stops pretending to be a choice.

### Changed

- **`_update_status` in the ingestion flow is `_fail_document`, and takes no
  status.** It branched on two values and all four callers passed `"error"`; the
  `elif status == "done"` was a `pass` whose comment explained why nothing takes
  it - reaching `DONE` needs the vector document's id, which only
  `_run_ingestion` holds, so it calls `complete_ingestion` itself. The name now
  says what the function does: record the *first* failure and refuse to overwrite
  it (#423). `vulture` could not see the dead branch, because the parameter was
  read. (#956)
- **The guard compares `DocumentStatus.ERROR`, not the string.** Two spellings of
  one value set is how #148 happened - a fourth status nothing had ever written,
  filtered on by the listing, so every knowledge base reported `indexed_count:
  0`. (#956)

### Added

- A test for the guard's other half: a row that has not failed yet does take the
  failure. It was covered only incidentally, through `_run_ingestion`. (#956)

## [0.0.219] - 2026-08-20

A tracking row says which file it tracks, so a failed attempt stops piling up.

### Fixed

- **A file that failed to parse on one sync and succeeded on the next left both
  rows.** `complete_ingestion`'s retirement matches on `vector_document_id` and a
  failed parse writes none, so the succeeding run had nothing to name and every
  repeated failure added another row that counted toward the collection's
  `document_count` for good. `rag_documents` gained a `source_path` (`0043`) -
  `gdrive://<id>`, `s3://bucket/key`, or an absolute path for a local or CLI sync
  - and a new attempt retires the previous *failed* one by that address. (#996)
- **Not by filename**, which is the trap and the collision #990 removed on the
  vector side reached from the other direction: `a/readme.md` and `b/readme.md`
  in one bucket share a basename, so a name match deletes the other file's row.
  (#996)
- **Not a `PROCESSING` row either.** "Has no vector id" is also true of an
  attempt still running, and nothing serialises two manual triggers on one
  source - the second would delete the first's live row, after which the first
  finishes, replaces the vectors and finds no row to complete. Retirement matches
  `status == ERROR`. (#996)
- **A failed *supersede* is no longer reported as a failed ingest.**
  `ingest_file` inserts the new document before deleting the one it replaces, so
  a delete that raised returned an error while the vectors sat in the store - an
  `ERROR` row with no vector id, which the next attempt then retired and
  orphaned them. The insert succeeding is the answer; the lingering old document
  is logged. (#996)
- **The CLI sync records its address too.** `rag-ingest` called both
  `create_document` and `ingest_file` without the resolved path it had already
  computed, so its rows got `NULL` and a file failing there repeatedly kept
  inflating the count. (#996)

### Changed

- **An upload stores no address and retires nothing.** Its only name is a
  basename, and two people can upload different `report.pdf`s meaning both to
  exist, since `replace` defaults to false. Retiring by that name would delete
  the first one's failed row - its diagnosis, its retry and its stored file - for
  a caller who asked for no such thing. (#996)
- `source_path` is `Text` with a **hash** index rather than `String(1024)`: an S3
  key alone reaches 1024 bytes before the scheme and bucket are added and a
  filesystem path reaches 4096, and a btree index refuses a key over about 2700
  bytes at insert time. Equality is the only way the column is read. (#996)

## [0.0.218] - 2026-08-20

Every ingest path writes its tracking row before the file is indexed.

### Fixed

- **The local-directory sync opens its document row before the ingest**, and
  writes one whether or not the ingest succeeded. It created the row afterwards
  and only on success, so a row whose write failed - a database blip, a name
  longer than the 255-character column - left the vector document stored and
  untracked, and the next `new_only` run then matched its unchanged hash and
  skipped the file before reaching the write: searchable, invisible and
  undeletable for good. This was the last path still doing it; the connector sync
  stopped in #992. (#997)
- **A locally-synced file that failed to parse keeps its own reason.** `failed`
  was incremented in the sync log and nothing anywhere said which file or why, so
  a run reporting four of forty failures named none of the four. (#997)
- **A locally-synced document's row says which parser read it.** The rows carried
  no `ingestion_config` at all, so `parser` read `null` for every one of them
  while the setting that chose it sat resolved a few lines above. (#997)

### Changed

- `updated` is counted off `replaced_document_id` rather than by searching the
  ingest result's own message for the word "replaced" - the string dependency
  #990's review removed from the connector flow. Equivalent today, since
  `ingest_file` writes that word exactly when it replaced something; one of the
  two is a fact and the other is a sentence. (#997)

## [0.0.217] - 2026-08-20

What a connector sync ingests is visible, and deleting it deletes it.

### Fixed

- **A connector sync records a `rag_documents` row.** It created none, so a Drive
  folder synced into a knowledge base reported "ingested: 40" and left the
  Documents tab empty, the collection's own `document_count` at zero, and the
  documents unreachable by delete - one ingested from a folder could be removed
  only by dropping the whole collection. A failure was a number in the sync log
  and a reason nowhere, so "which four of the forty failed, and why" had no
  answer. (#992)
- **A delete removes the vectors, whichever route asked.**
  `RAGDocumentService.delete_document` took `ingestion_service: Any = None` and
  removed vectors only when a caller passed one - `/rag/documents/{doc_id}` did,
  `/kb/{kb_id}/documents/{doc_id}` did not. So deleting from the Documents tab
  removed the row and left the content searchable, and for a synced document that
  was permanent: the next `new_only` run matched its unchanged hash and skipped
  it. The argument is required and typed now, so a third route cannot repeat it.
  Reachable today for an uploaded document. (#992)
- **The row is opened before the file is indexed**, on the upload and the
  connector sync. Written afterwards and failing - a database blip, a remote name
  longer than the column - it left the vector document stored and untracked, and
  the next `new_only` run then skipped the file before reaching the write. The
  local-directory sync still writes its row afterwards ([#997]). (#992)
- **An `app`-scoped collection belongs to no organization**, so
  `kb.organization_id == organization_id` skipped it: a source pointed at one was
  parsed with the deployment defaults rather than that collection's own settings,
  and filed its documents under no knowledge base. The caller's own row still
  wins over a deployment-wide one of the same name, and another tenant's matches
  neither. (#992)
- **The row records which models read the document.** `image_description_model`
  and `embedding_model` were both omitted, so the documents page showed a synced
  file as parsed by nothing and embedded by nothing. (#992)

### Changed

- A synced document keeps **no original**: a synced file's bytes live in the
  system it came from, and mirroring every one onto this deployment's disk to
  make a retry button work is a cost per corpus rather than per failure.
  `has_file` is false for these and re-running the sync is the retry - which
  since #990 skips everything unchanged and re-fetches exactly what has no
  document, so four failures out of forty cost four transfers. (#992)
- The knowledge base behind a collection is resolved once per sync rather than
  per file: `_config_for_collection` was already finding that row to read its
  parser settings, so one lookup now answers both questions. (#992)

## [0.0.216] - 2026-08-20

A scheduled sync stops duplicating everything it has already ingested.

### Fixed

- **`sync_mode` is implemented for a connector sync.** It reached exactly one
  argument - `ingest_file`'s `replace` - and `ingest_file` never skips anything,
  so a scheduled Google Drive or S3 source re-embedded every file every night;
  and on the default `new_only` it passed `replace=False`, which skips the
  lookup, leaves the old document in place and inserts a second copy. A week of
  nightly syncs was seven copies of every chunk, ranked against each other in
  every search and each one paid for on the organization's own embedding key.
  `skipped` sat beside the loop, initialised and never incremented, which is a
  sync log truthfully reporting `skipped=0` every night. The logic is
  `sync_local_flow`'s, which had it right all along: one `sync_mode` column feeds
  both flows and a mode meaning one thing for a server directory and another for
  a Drive folder is the defect whatever either does alone. (#990)
- **A basename no longer claims a document that names its own address.**
  `existing_document` falls back from `source_path` to *filename*, so a bucket
  holding `a/readme.md` beside `b/readme.md` had the second key find the first
  key's document - equal contents skipped the second file, unequal contents
  deleted the first, and either way a first sync could not keep both. The
  fallback is narrowed rather than removed, because it is what stops a file
  uploaded through the browser and later synced from its own folder being
  duplicated: an upload stores its filename *as* its `source_path`, so the two
  agree and it stays reachable by name. Same collision fixed for two local files
  of one name in different directories. (#990)
- **A replacement inserts before it deletes.** `insert_document` is where the
  embeddings are computed, so a provider refusing between the two statements left
  the collection holding *neither* document - permanently, since a failed ingest
  is returned rather than raised and nothing retries it. This order fails the
  recoverable way instead. (#990)
- **A replaced file is counted as an update.** The connector loop reported every
  success as a first ingestion and passed no `updated` to `complete_sync`, so the
  sync history read zero updates forever - unnoticed, because the mode that
  replaces was unreachable. Read off `replaced_document_id` rather than off the
  result's own sentence. (#990)

### Changed

- Where a sync decides differs between the two flows, because remote bytes cost
  something: `update_only` skips a file it has never seen *before* the download,
  while an unchanged file is recognised after one and before the embedding. A
  stored document with no `content_hash` is re-ingested rather than assumed
  current - skipping a file that may have changed is the answer nothing later
  corrects. (#990)

## [0.0.215] - 2026-08-20

Which sync connectors come after Google Drive and S3, and who ends up able to
read what one ingests.

### Documentation

- **A source's reach, and who decides it.** A sync source ingests into exactly
  one collection, access is decided at the collection, and there is no
  per-document isolation inside one - so everything a source reads becomes
  readable by everyone who can read that collection. The two halves of that
  reach are not equally reliable: `config` narrows it but is a row field anyone
  with `collections:edit` can widen, while the credential's own permissions are a
  ceiling nothing in the product can raise. Hence the rule - scope the
  credential, not just the config. (#938)
- **Mirroring each source's ACLs and filtering at retrieval is decided
  against**, with the reasons written down so it is not proposed again as an
  obvious win: there is no identity map between an Entra or Atlassian principal
  and an `organization_members` row, a permission changed in the source is
  invisible until the next sync so a mirrored ACL is stale authorization, and a
  crawler has no ACL at all. (#938)
- **The connector list is cut and ordered**: #990 first, because every connector
  below names a change signal and the sync path consults none; then a web crawler
  (#984), SharePoint and OneDrive (#985), Confluence (#986), a git repository's
  documentation (#987), and Azure Blob and GCS only once `S3Connector` is an
  object store rather than an S3 one (#988). Notion is decided against for now -
  MCP covers Notion-as-a-tool - and Slack and email archives stay off, because a
  conversation retrieves badly and the channel integrations already put an agent
  *in* Slack. (#938)
- **What a new connector owes** is stated alongside: a change signal named in the
  docstring, a credential scoped where the source is created, and a file count
  somebody has thought about while reading a collection's listing is still a full
  scan (#27). (#938)

### Fixed

- **The page no longer states the local sync's behaviour as the rule for both.**
  `sync_mode`'s hash comparison and skip counters exist in `sync_local_flow` and
  nowhere else; a connector sync implements none of it, which is #990 - filed
  severity high, and found reviewing this change. (#938)
- **`create_source`'s docstring stopped claiming its secret fields are
  Fernet-encrypted**, which has been untrue since #937 deleted
  `app/core/crypto.py`. (#938)

## [0.0.214] - 2026-08-20

The sandbox and connector service contracts are typed.

### Changed

- **A sandbox service returns the schema its route declares.** Every route named
  a `response_model` and the service handed back a `dict[str, Any]` for FastAPI
  to validate into it, so the service→route contract was a mapping the type
  checker could not read and a renamed key was a 500 rather than a red `ty` run.
  `runtime_catalog`, `local_service`, `store_local_credential`, `probe_policy`,
  `policy`, `sessions`, `session_events` and `session_usage` all answer models
  now. `_read` keeps `dict[str, Any]` and is the only one left in the module,
  with a docstring saying why: it is `sandboxd`'s answer, not ours. (#562)
- **A connector's `CONFIG_SCHEMA` is `dict[str, ConnectorConfigField]`** - the
  model that described it at the API edge is now its own type, so a misspelled
  key is a type error where it is written. `type` is a `Literal` of the four
  widgets the wizard draws, mirrored in `rag-api.ts`; its fall-through is a text
  input, so a connector inventing a fifth got a field the form collects wrongly
  with nothing reporting it. `label` is required, since it is what the form
  draws. (#562)
- **The four `sandbox_workspace.py` helpers that read a stored workspace say
  `FileData`** - the backend library's own type, which `StateBackend.__init__`
  has always been annotated with. `_get_s3_client` gained the return type it
  never had. (#562)

### Fixed

- **`usage_report.py` reads `sampled.memory_bytes`, not
  `sampled.get("memory_bytes")`.** Those two keys are the whole of what a usage
  footer shows for a container, and they were unchecked in the one place a
  rename reads as a missing number rather than an error. (#562)
- **A session's `tenant` label is dropped where the filter reads it**, rather
  than by every caller remembering to. It is another organization's id when the
  session is theirs; the listing schema has always said it is absent, and now
  one place makes that true. (#562)

### Documentation

- **`docs/howto/add-rag-source.md` is removed.** It was
  `docs/howto/add-sync-connector.md` a second time, adjacent to it in the nav,
  and stale in the same pre-#937 way: a credential inside `CONFIG_SCHEMA`,
  `list_files(self, config)` with no credential parameter, and a closing tip
  that per-source credentials are stored per sync source in the database. It
  also told the reader to edit the generator's `post_gen_project.py`. (#562)
- **The connector walkthrough teaches the credential model it has had since
  #937**: `SECRET_KIND`, a `credential` argument, no fallback, and a
  `validate_config` that checks the shape of what was typed because it does not
  see the credential. Its CLI and API examples name flags and fields that
  exist. `docs/patterns.md` and two `app/rag/connectors/` paths in
  `docs/architecture.md` and `docs/howto/configure-sync-sources.md` went the
  same way. (#562)

## [0.0.213] - 2026-08-20

Both RAG pages get tabs, and the tab is in the URL.

### Changed

- **Integrations is `/rag`'s third tab.** `ReusableIntegrations` sat under the base
  grid - the right relationship, since the collections are fed from it, and the
  wrong placement: on an organization with a dozen bases it was below a grid three
  rows deep, and reachable *only* from the Knowledge bases tab, which makes a
  page-level concern something you find by first choosing one of two tabs. (#939)
- **A knowledge base has three tabs** - Documents, How documents are read, Sync
  sources. Each section carried a comment justifying its place under the one above,
  and each argument was about reading order on a first visit, which is not where
  somebody returns to: adjusting a parser meant scrolling past every document. The
  stats strip and the override banner stay above the tabs, because they describe
  the collection rather than any one section. (#939)
- **Both pages carry `?tab=`**, read through the SSR-aware `useUrlState` rather
  than a `useState` initializer touching `window` - which renders one value on the
  server and another in the browser, so the default tab flashed before the named
  one arrived. A link can name a section and a reload keeps it. (#939)
- **The onboarding walk selects a tab before spotlighting what is inside it.** Four
  steps gained `activate`; without it a stop waits four seconds for an element that
  never mounts. (#939)

### Fixed

- **Each tab shows only its own section.** The base list rendered for every value
  that was not `search`, so choosing Integrations appended the panel *below* the
  grid rather than replacing it - the placement the tab exists to escape. (#939)
- **A tab's panel lives inside its `Tabs` root**, on both RAG pages. A
  `TabsTrigger` points at its panel with `aria-controls`, and a root that closed
  after the trigger list left those references dangling and the visible section
  with no `role="tabpanel"`. Pre-existing on `/rag`; fixed there too. (#939)

## [0.0.212] - 2026-08-20

The RAG dialogs: a real editor for a model prompt, one width scale, and a mark on
each parser.

### Changed

- **The image-description prompt is a `MarkdownEditor`.** It is a model prompt,
  several sentences long, and it was a bare three-row textarea - while the product
  already has the control for that, the one the Builder uses for an agent's
  instructions, an exposure prompt and a capability's generated form. The editor
  gained `maxLength` so the swap did not quietly drop the hard cap: a field whose
  length the API refuses should not let somebody write past it and find out on
  submit. `IngestionSettings` is embedded whole in the create dialog, so both
  dialogs get it. (#940)
- **The four RAG dialogs agree on a width scale.** The same `IngestionSettings` was
  given 768px in two of them and 512px in the one that also carries four fields
  above it - not a judgement call but a disagreement, since nobody had decided and
  each had picked. `src/lib/dialog-widths.ts` holds the three sizes with the rule on
  each, so the create dialog is no longer the narrowest thing holding the widest
  form. (#940)
- **Each PDF parser choice draws a mark.** Three lines of text where every other
  picker in the product draws one. Only LlamaParse is a product, so it takes
  LlamaIndex's own mark - a row in `scripts/gen-brand-icons.ts`, generated, never a
  hand-authored path - and PyMuPDF and liteparse take a lucide icon rather than one
  row getting special treatment and two getting blanks. (#940)

## [0.0.211] - 2026-08-20

The last second mechanism for secrets at rest is gone.

### Upgrading

**A sync source's credential is no longer a `config` field.** Migration `0042`
handles it, and it is not silent:

- A source holding an encrypted credential has it **removed** from `config` and is
  **named in the migration's output**. Nothing readable is lost - the value was a
  Fernet token over `SECRET_KEY`, and the release that could read it is the one
  being replaced - and leaving it would leave a credential at rest under a
  deployment-wide key, which is the whole point of the change. Each named source
  then has no credential and refuses to sync until one is attached.
- **Add the credential to the organization's Vault** - a `gcp_service_account` for
  Drive, an `aws_credentials` pair for S3, both now offered under a new *Document
  source* group - and point each source at it.
- **A source with no organization stops the upgrade.** `sync_sources.organization_id`
  is `NOT NULL` now, and anything `rag-source-add` created before #707 has none.
  Set it or delete the row, then upgrade.
- **API callers** posting `service_account_json`, `access_key_id` or
  `secret_access_key` under `config` get a 400 naming the field. `rag-source-add`
  takes `--secret-id`.

### Changed

- **A sync source references a vault secret by id.** `sync_sources.config` held the
  credential, encrypted by `app/core/crypto.py`: one deployment-wide Fernet key
  over every tenant's secret, which is the weakness the vault exists to remove and
  the one place `CLAUDE.md`'s "there is no second mechanism" was untrue. That module
  is **deleted**. `config` now says only how to *find* the documents, and each
  connector declares the kind of credential it takes. A credential is added once and
  reused - five collections fed from one Drive folder used to mean the same JSON
  pasted five times and rotated in five places - and it appears on the Vault page
  like everything else. (#937)
- **The sync wizard asks for a credential as its own step**, offering the
  organization's matching secrets and linking to the Vault when there are none. It
  distinguishes a vault that holds nothing from one that could not be read. (#937)
- **`app/worker/background/rag.py` is deleted.** Its three in-process handlers had no
  caller in `app/` at all, and the connector interface change made them
  uncompilable. `IngestionService.from_settings` went with them. (#959)

### Fixed

- **Binding a sync credential checks that the binder can see it.** A secret can be
  private to a member, and a sync runs for everyone who can reach the collection -
  so binding one is lending it. A Builder with `connections:manage` but shared-only
  secret visibility could post the id of another member's private credential and
  have the worker unseal it. The row now goes through
  `resolve_access(..., Perm.SECRETS_VIEW, resource_type=SECRET)`, refused in the
  same words as an id that does not exist so the refusal cannot enumerate the
  vault - the same fix #918 made for embedding keys. (#937)
- **A nullable sync-source column can be cleared.** The repository skipped every
  `None`, so `{"secret_id": null}` answered 200 and left the old credential
  attached, and a source that recovered kept its previous `last_error`. (#937)

## [0.0.210] - 2026-08-20

`rag-source-add` accepted any collection name, including another tenant's.

### Fixed

- **`rag-source-add` refuses a collection it cannot legally own.** The command
  wrote a caller-supplied collection name straight into a `sync_sources` row
  without asking whether it was a legal identifier, whether a knowledge base of
  that name existed, or whose it was - while the HTTP route for the same thing
  asks all three, for the reason its docstring gives: "a sync writes into the
  collection, so pointing one at another tenant's is an injection, not a read".
  The name's *shape* is now judged in `create_source`, so the route and the CLI
  share one rule and a name no table can be called is refused where it enters
  rather than failing later in a worker. Ownership is answered in the command,
  which is the only place that knows who is asking. (#707)
- **The rows the command creates have an organization.** `create_source` was
  called without one and the column is nullable, so every source the CLI ever
  made was org-less - while the model's docstring opens "Belongs to an
  organization". The organization now comes from the collection's own knowledge
  base, which is also step 1 of #937: converging `sync_sources.config` onto the
  vault needs an owner to bind a ciphertext to. (#707)
- **A personal collection is refused, not just another organization's.** A
  personal knowledge base carries the organization's id too, so "same tenant" is
  not ownership: `writable_kb` lets only its owner write to one. Accepted, it
  would have pointed an *organization-owned* sync source at a member's private
  collection, which every member holding `connections:manage` can see and
  trigger. An app-scoped base is refused for the mirror reason - it belongs to
  the deployment and takes an app admin. (#707)
- **A refused `rag-source-add` exits non-zero.** `error` is `click.secho` and
  nothing more, so a command that printed a refusal and returned exited **0** and
  a shell script carried on as though the source had been created. (#707, and
  #972 for the other 23 call sites across `app/commands/`)

### Changed

- **`rag-source-add` requires `--org`.** A script calling it without one now gets
  click's usage error instead of creating an org-less row pointed at a collection
  that may not exist or may be another tenant's. Existing rows are untouched;
  moving them is #937's business. `docs/commands.md` and
  `docs/howto/configure-sync-sources.md` carry the flag in all three documented
  invocations. (#707)

## [0.0.209] - 2026-08-20

A chat attachment was refused by a 10 MiB limit no operator could see or raise.

### Added

- **`CHAT_MAX_UPLOAD_SIZE_MB`, default 10** - what may be attached in chat, and a
  *different* setting from the knowledge base's `MAX_UPLOAD_SIZE_MB` rather than the
  same one. A knowledge-base document is chunked, embedded and read back through
  retrieval; an attachment to an agent with no workspace is pasted whole into the
  prompt, so the same size fails differently on each surface and one ceiling cannot
  be right for both. The default is what the hardcoded limit already enforced, so
  nothing changes on upgrade except that it can now be raised. `GET /health`
  publishes both ceilings, because a client that reads one cannot know the other.
  (#498)

### Fixed

- **The chat upload limit is a setting rather than a literal.** Three numbers
  claimed to be it and they disagreed: `MAX_UPLOAD_SIZE` (10 MiB in
  `file_storage.py`) was what refused, `MAX_UPLOAD_SIZE_MB` (50) was what `/health`
  published and what RAG ingestion used, and the frontend defaulted its own check to
  50. So a 20MB attachment passed the client check, was read into memory, crossed
  the wire in full and came back refused by a number that appeared in no
  configuration file - while `frontend/README.md` told the operator to keep the
  client value "at or below the backend's", which was advice they could not follow.
  (#498)
- **The whole-request body ceiling follows the largest upload limit, not the first
  one.** `BodySizeLimitMiddleware` is global and derived its cap from
  `MAX_UPLOAD_SIZE_MB` alone, so a chat limit configured above the knowledge base's
  would have been unreachable - a 413 before the code that enforces it ran. It now
  takes the largest of the three, including the embed ceiling, which is the smallest
  today and would have been the same latent defect for whoever raised it next.
  (#498)
- **A `sonner` mock in `chat-input.test.tsx` was never reset**, so a toast asserted
  in one test was still recorded in the next one asserting none. Found because it
  would have made a new test lie. (#498)

### Changed

- **The composer's own ceiling is `NEXT_PUBLIC_CHAT_MAX_UPLOAD_SIZE_MB`**, defaulting
  to 10 and named for its surface. It was `MAX_UPLOAD_SIZE_MB` defaulting to 50 - and
  it is the only reader of that value in the frontend, so it was already the chat
  limit by usage with the wrong number in it. The three compose files, the frontend
  `Dockerfile`, `.env.example` and the `vercel-deploy` recipe all named the old
  variable; each now passes the configured value through. **An operator setting
  `NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB` must rename it**, or the composer silently takes
  the 10MB default. (#498)
- **Four pages described the old split** - `configuration.md`, `channels.md`,
  `architecture.md` and `file-processing.md` - and each now names the setting for the
  surface it describes. `file-processing.md`'s "Size Limits" sits under a chat
  heading and led with the knowledge base's number; it leads with the chat one now.
  (#498)

## [0.0.208] - 2026-08-20

Ingesting one changed file read the whole collection four times.

### Changed

- **One document lookup, one scan, both answers.** Three lookups walked the same
  document listing with three predicates - `source_path`-then-`filename`, content
  hash, and two public methods each projecting one field from the first - and every
  one of them read the whole collection. So ingesting a changed file in `new_only`
  mode read it four times (the sync asked for an id, then a hash, and `ingest_file`
  asked for both again) and an unchanged one twice; it is now once for the sync's
  decision and once inside the ingest. Both sync callers, the worker flow and
  `rag-sync` in the CLI, did the identical two-call dance and now do one. (#566)
- **The id and the hash come back together, so they cannot disagree.**
  `IngestionService.existing_document` answers with a frozen `StoredDocument`
  carrying both, and `find_existing` / `get_existing_hash` are gone rather than
  kept as wrappers. While the two were computed separately they *could* name
  different documents - the id lookup checked every document for a `source_path`
  match before falling back to `filename` while the hash lookup interleaved the
  two - so a sync compared a live file's hash against a different document's and
  either re-embedded an unchanged file every night or skipped a changed one as
  current. That was fixed in #548; a caller that cannot ask for one answer without
  the other cannot write it again. (#566)
- **`docs/file-processing.md`** states the precedence, the read count, and that a
  store which cannot answer the listing is treated as "no match" - a failed query
  is not evidence a document is absent, and acting as though one were present
  would delete it. (#566)

## [0.0.207] - 2026-08-20

The two addresses an upload can arrive at answered with different shapes.

### Fixed

- **Both upload routes serialize `RAGIngestResponse` identically.**
  `POST /rag/collections/{name}/ingest` carried `response_model_exclude_none=True`
  and `POST /kb/{kb_id}/documents` did not - same schema, same operation, both
  feeding the same upload UI. `document_id` is `str | None` and is `None` on every
  accepted upload, because the vector store's id does not exist until the worker
  has indexed the file, so one address omitted the key and the other sent it as
  `null`: a client normalising the answer got a different shape depending on which
  it had called. The flag is gone rather than added to the other route - `null` is
  the honest answer, the id is pending rather than absent, and it was the only use
  of `response_model_exclude_none` in the tree. No client is affected: nothing in
  the frontend reads `document_id` from an upload response. (#560)

### Changed

- **`docs/file-processing.md`** names both upload addresses and says they answer
  202 with every field of the schema, `"document_id": null` included. (#560)

## [0.0.206] - 2026-08-20

Storing a long document's chunks cost one database round trip per chunk.

### Changed

- **A document's chunks are written a batch of rows to a statement, not one
  statement each.** `insert_document` issued one `INSERT` per chunk in a Python
  loop inside one open transaction, so at the default `chunk_size` of 512 a
  200-page PDF was one to three thousand *sequential* asyncpg round trips: a
  second or two on a local socket, five to fifteen seconds against a managed
  Postgres at 3-5ms - spent holding a connection while it waited. The rows now go
  200 at a time through an `executemany`, which asyncpg pipelines. The statement
  itself is unchanged, `ON CONFLICT (id) DO UPDATE` included, and it still behaves
  per row: a re-ingest of an unchanged document updates its rows rather than
  duplicating them. (#950)
- **Each batch's rows are built where its statement runs.** Batching the
  statements alone would have bounded what asyncpg receives while leaving the
  worker's memory where it was: the embedding is rendered as text in these rows,
  tens of kilobytes each at 3072 dimensions, so materialising a
  three-thousand-chunk document first meant better than 100MB of live strings on
  top of the float vectors already in hand - an OOM kill rather than a slow
  ingest. 200 rather than one statement per document is the same reason. (#950)
- **`docs/file-processing.md`** says how many round trips storing a document costs
  and why the batch is bounded, in the chunking section where `chunk_size` is set.
  (#950)

## [0.0.205] - 2026-08-20

Ingesting a large batch of documents exhausted the worker's database
connections, and the failure that followed could not be recorded.

### Fixed

- **Every vector store the ingestion worker builds is disposed with the work
  that built it.** `PgVectorStore.__init__` creates a pooled SQLAlchemy engine,
  and the three flows in `app/worker/tasks/rag_tasks.py` each built one and
  disposed none. One flow runs per uploaded document, so two hundred uploads
  meant two hundred pooled engines abandoned in one worker process, each holding
  its checked-in connections until the process exited - and somewhere short of a
  hundred documents the worker reached `max_connections`, after which every
  query raised, including the ones that would have marked a document failed. The
  symptom was an upload stuck at `processing` with a connection error in a log
  nobody reads, indistinguishable from four other failure modes. Two further
  paths went with it: `_run_sync` built its store *before* validating the path,
  so the cheapest refusal - "path not found" - leaked a pool, and
  `_ingestion_service_for` built the store *before* the processor, so a
  collection asking for a parser this build cannot provide left a pool no
  `finally` could reach. (#948)
- **A store built for one request is closed when the request ends.**
  `get_vectorstore` reads the store the lifespan built and, when there is none,
  builds one - and there is none whenever that construction failed, because the
  lifespan logs "Vector store will not be available" and carries on serving. A
  degraded deployment therefore answered every knowledge-base request by building
  a pooled engine and abandoning it, at request rate. The lifespan's own store is
  passed through untouched: it belongs to the process. (#948)
- **The knowledge capability's store is released at shutdown**, and the channel
  consumers stop before either store is disposed. The capability holds a
  process-wide store built on the first search an agent runs, reachable from no
  request, so the lifespan's `aclose` never saw it. Disposing it while the
  Telegram, Slack and Mattermost polling loops were still turning raced a search
  in flight and let the next one rebuild a pool nothing was left to close, so the
  three stop loops now run first. (#948)

### Changed

- **`docs/file-processing.md` states the rule for all three stores** - the
  worker's per flow, the request's, and the capability's per process - and says
  what to look for when ingestion starts failing part-way through a large batch.
  Pooling *within* one flow is kept deliberately: a document's chunks are written
  over that connection, and a flow runs in one event loop. (#948)

## [0.0.204] - 2026-08-20

Every knowledge base in the product reported nothing indexed, however many
documents had finished ingesting.

### Fixed

- **A collection's indexed count filters on the status the pipeline writes.**
  `counts_by_collection` counted rows whose `status` was `"completed"`, and
  nothing has ever written that value: an upload creates a row `processing` and
  the pipeline moves it to `done` or `error`, which is what the model default,
  `docs/file-processing.md` and the frontend's status map all say. The `FILTER`
  clause therefore could not match a row, so `indexed_count` was `0` on every
  knowledge base and a collection where everything succeeded read as entirely
  unindexed. The literal is now an enum: `DocumentStatus` sits beside the column
  in `app/db/models/rag_document.py` - the shape `RunStatus`, `AgentStatus` and
  `InvitationStatus` already take - and the writer (`RAGDocumentService`) and the
  reader name the same member rather than two strings free to drift.
  `rag_document_repo.create` and `update_status` take `DocumentStatus` instead of
  `str`, so the next typo is a type error rather than a count that silently
  reports nothing. (#148)

### Changed

- **`docs/file-processing.md`** says the three status values are the
  `DocumentStatus` members and that the indexed count filters on `done`, so a
  reader of that table knows where the vocabulary lives.

## [0.0.203] - 2026-08-19

A Member could pay for a collection's embeddings with another member's private
key by supplying its id.

### Fixed

- **Binding an embedding key checks that the chooser can see it.**
  `KnowledgeBaseService._check_embedding_secret` looked the chosen key up scoped
  only to the organization and never ran the caller's own secret-view check, so a
  Member with `collections:edit` who supplied the UUID of another member's
  **private** vault key bound a key `secrets:view` would have refused them — and
  the collection's embeddings then billed it, for everyone who can write the
  collection. The picker only ever offered keys the chooser can see, which is not
  a check: the API takes an id and an id is guessable. The fetched row now goes
  through `resolve_access(..., Perm.SECRETS_VIEW, resource_type=SECRET)`, exactly
  as the agent secret bindings already did, and a key the caller cannot view is
  refused as one the vault does not hold — so the refusal cannot enumerate
  somebody else's private secrets. Creation is the only path that binds one:
  `KnowledgeBaseUpdate` carries no `embedding_secret_id`. (#918)

### Changed

- **`docs/file-processing.md` says binding needs `secrets:view`**, and why —
  binding a key is lending it. The page listed the two refusals creation already
  made, another organization's key and the wrong purpose, so a reader acting on it
  would have expected `collections:edit` alone to be enough. (#918)

## [0.0.202] - 2026-08-19

One test-only release: a `catch` the frontend suite reported as covered had
never run.

### Fixed

- **The onboarding resume stash is tested against the storage the code reaches.**
  Node 22+ ships its own `sessionStorage` — enabled on v26.3.0 — which shadows
  jsdom's, so `vi.spyOn(Storage.prototype, "getItem")` patched a different object
  than `takeStashedFlow` called: `getItem` never threw, the test passed through
  the `raw === null` early return, and the `catch` at `resume.ts:45` never ran.
  It read as covered in CI and as uncovered under `make test-frontend-cov` on a
  newer Node. `vitest.setup.ts` now normalizes `sessionStorage` the way it already
  did `localStorage` (one `StorageMock`, installed on both `globalThis` and
  `window`), and both throw-path tests spy the instance and assert an outcome only
  the `catch` produces — a stashed flow that comes back `null`, a write that left
  nothing stored — so a spy that misses fails loudly instead of silently
  uncovering the branch. No product code changed. (#919)

## [0.0.201] - 2026-08-19

An agent is configured in one place, a deployment can brand and close itself,
and a run says what it actually handed its model. Twenty findings from the
review round on the same pull request are in here too — the most serious of
them a one-use invitation link that admitted accounts without bound.

### Added

- **The Toolbox is where an agent is configured.** Context files, collections
  and skills are picked inside the capability that reads them, on the panel's own
  first tab, which the panel opens on; the Knowledge and Skills tabs are gone and
  Skills is a capability with a switch like every other. Settings and Tools are
  two tabs, so a six-field form and a tool description that is a paragraph stop
  sharing one scroll, and the workspace's and delegation's own controls moved
  inside the card that names them. The "Charts is on" card is gone: its switch is
  on the panel's title row, where it renders whether or not the capability is
  granted. (#914)
- **Image generation asks for a provider and a model**, both from the server:
  whether a provider can draw is `supported_native_tools()` on the SDK's model
  class, and which models it offers is `app/core/catalog/image_models.json`, with
  a sentence per model. A model released this morning is one catalog entry.
  (#914)
- **A deployment has its own identity, access policy and notices**, edited from
  `/admin/settings` by whoever holds `is_app_admin` — one row guarded by a unique
  constraint on a column constrained to true, so a second identity is an
  `IntegrityError` rather than a deployment that quietly has two. Name, tagline,
  description, logo and favicon reach the sidebar, the sign-in header, the browser
  tab, the OpenGraph card, the PWA manifest, the iOS touch icon and every email
  the deployment sends; `signup_mode` (`open` / `invite_only` / `closed`) and an
  email-domain allow-list decide who may register; an announcement and a
  maintenance window that actually closes the API. `docs/deployment.md` is the
  page. Migration `0037`.
- **Two ceilings a deployment can set**: organizations per account and agents per
  organization, both null by default, and null is no limit rather than "not
  configured". Every transition into the counted state is checked, not only a
  create, and the count is taken under a transaction-scoped advisory lock —
  read and acted on without one, two requests both pass it and both write.
  Migration `0039`.
- **A run records what it handed its model.** None of it is derivable
  afterwards: the prompt is the spec's instructions plus the platform's, plus a
  channel binding's, plus the bound skills, plus whichever reminder fired, and
  the tools are the registry plus the organization's MCP servers minus whatever
  tool search hid. `RecordingModel` wraps the model the agent was built with and
  writes down each request as it passes; `GET /runs/{id}/manifest` reads it back
  under the transcript's authorization, and a second tab on the run drawer
  renders it with the requests as bars. A table rather than a column on
  `agent_runs`, provider passthrough never recorded, and the write guarded *and*
  in a SAVEPOINT. Migration `0038`.
- **A run is read beside the list rather than over it**, in two full-height
  panes, with the thread folded by run and only the run being read open.
  Stepping between runs is a cache hit and leaves the timeline standing, and the
  arrow keys do what the buttons do.
- **A turn's attachments are on the run timeline, openable.** `MessageRead` has
  carried `files` since attachments existed; the timeline rebuilt its argument
  field by field and lost them, along with the per-turn model, token split, cost
  and context size. "The agent answered badly" and "the agent was handed a scan
  with no text layer" are the same transcript until somebody can look at the
  file. They open through the shared `FileViewer`, addressed through the run —
  `GET /runs/{run_id}/files/{file_id}`, authorized as the transcript is — because
  `/files/{id}` is scoped to the uploader and a run review is not. (#914)
- **Publishing mints a version; deploying it is a separate decision.** An
  environment says whether a publish moves it: `pinned` waits to be promoted onto
  and `tracks_latest` follows, which is what a `dev` somebody is iterating in
  wants. Existing environments become pinned, so an author fixing a prompt no
  longer changes what the live Slack bot answers with in the same action.
  Migration `0040`.
- **The version history pages and reads as a timeline**, MCP servers have a tab
  of their own, and a context file is created and edited the way a skill is.
- **A registration can prove itself with an invitation token.** A shareable link
  with neither an address nor a domain is a real, documented shape and an
  address-based query cannot see one, so closing sign-up silently un-invited
  everybody holding one. `UserCreate` takes an `invitation_token`, and holding it
  *is* the proof; registering with one does not accept the invitation, which
  still needs a session. The console carries it across the redirect that lost it,
  and across the provider round trip in the session. A link with a `max_uses`
  reserves capacity for the registering address, because acceptance happens
  later. (#916, #914) Migration `0041`.

### Fixed

- **A new conversation showed no agent until a reload.** The listing was fetched
  at the one moment the server is guaranteed to answer "nobody answered here
  yet", and nothing asked again. (#909)
- **Every wrong-method request answered 500 instead of 405**, on every route, so
  an unauthenticated caller could make the server log a traceback on any path.
  OpenTelemetry's FastAPI instrumentation reads `.path` unguarded in its
  `Match.PARTIAL` branch — which *is* "path matches, method does not" — and the
  latest published version has the same line, so `app/core/otel_compat.py`
  supplies the fallback upstream missed and a test fails when they fix it. With
  it, `HTTPException` stopped answering `{"detail": …}`: one
  `StarletteHTTPException` registration, forwarding the exception's headers,
  because `Allow` is what makes a 405 useful. (#917)
- **A streaming turn drew as four turns** — the grouping written for exactly that
  keyed on the stored `runId`, which a turn still streaming does not have.
- **The double scrollbar was the document's, and it could not scroll.** An
  absolutely positioned descendant with no positioned ancestor was inflating it;
  `position: relative` on `main` contains them.
- **The dark theme was darker than its numbers.** OKLCH lightness is perceptual,
  so a 14% page renders `#07090c` — black on black, with a 1.05:1 step between a
  page and its cards. Every contrast claim in `globals.css` was re-measured.
- **Every avatar drew 12px initials whatever its size**, because the fallback
  carried its own font-size and beat the one it inherited.
- **A settings write was not readable in the request that made it.** Uploading a
  logo answered `logo_version: null` for a logo it was already serving the bytes
  of: the identity map returned the instance `set_image` had already loaded.
- **A one-use invitation link admitted unlimited accounts.** `used_count` counts
  acceptances and acceptance needs a session, so on an `invite_only` deployment
  every registration read a ceiling nothing had yet moved. A use is reserved for
  the registering address before the account exists, atomically; accepting moves
  the address into the count, so somebody who registered through a one-use link
  can still join. (#914)
- **The provider button refused exactly the invitations that need a token.**
  `invite_only` accepted somebody through the password form and refused the same
  person through Google beside it. (#914)
- **Three writes ran ahead of the transaction that authorised them**: the
  maintenance verdict pushed to Redis before the commit, so a failed disable
  reopened the deployment for up to the cache TTL, and a replaced or cleared
  image's bytes deleted before it, so a rollback left the row pointing at a file
  that was gone. (#914)
- **A logo replaced twice in one second kept the first for a year** — the
  cache-busting token was the row's timestamp truncated to a second, and the
  address carries `immutable`. (#914)
- **A maintenance window never reached an already-open tab**, in either
  direction: the branding context is resolved once by the root server layout, so
  a non-admin was left on a dashboard answering 503 to everything with nothing
  saying why, and closing the window left a tab on the maintenance screen. The
  notice endpoint carries the verdict now. (#914)
- **The announcement banner could take the dashboard down.** `localStorage`
  throws where site data is blocked, and it is read inside
  `useSyncExternalStore` — during render, for every signed-in user. (#914)
- **A run reviewer could see a colleague's attachments and open none of them**,
  and **a streamed request that failed left no entry in the run manifest** — on
  the path where a provider refusal usually surfaces. The manifest's advertised
  512 KB ceiling was not one either: the last trimming stage returned without
  measuring. (#914)
- **Every version picker offered the newest fifty** of however many there are, so
  an agent published more than fifty times could not be repinned to an older
  version, and a row clicked on a later page of the history selected an id the
  comparison dropdown did not hold. (#914)
- **Arrow keys on the run detail's tab strip stepped between runs**, because the
  window listener never asked whether the focused control had already answered
  the key. (#914)
- **A stored image spec stopped being constructible.**
  `ImageGenerationConfig.model` used to be one prefixed string, so a version
  published before this release failed at construction rather than at publish.
  (#914)
- **Vertex AI was offered for drawing and could not be configured** — its model
  class draws, but the capability seals an API key where Vertex wants a service
  account. Being able to draw and being configurable are two questions. (#914)
- **An untouched image binding showed two blank pickers** for a configuration
  that would draw with OpenAI's first model, and **a dropped `page.html` became a
  Markdown file called `page`**. (#914)
- **A read-only Builder could work the panel's capability switch** — the one
  control `disabled` had to leave live, because that prop meant both "the
  capability is off" and "you may not edit". (#914)

### Changed

- **`closed` says what it does.** There is deliberately no
  administrator-creates-an-account path — an account needs a password its owner
  chose, so adding somebody means opening registration to them, which is what
  `invite_only` is. The setting text, the refusal and the page say so rather than
  promising a flow that does not exist. (#914)
- **The admin conversation browser is retired**, and the cross-tenant read with
  it.
- **The model fallbacks are data**, and their context windows are the library's.
- **A chat attachment's bytes are served from one place**
  (`_chat_file_bytes.py`), so what a browser may display does not depend on which
  route authorized the read. (#914)

## [0.0.200] - 2026-08-18

### Fixed

- **A connector's refusal names the field it is about.** The protocol was
  `tuple[bool, str | None]` — a flag and a sentence — so a per-field refusal
  raised inside a connector could not survive the return, and the wizard's
  configure step took no error prop at all. Both halves are done: the protocol
  carries the field, the service roots it against the posted document, and the
  step marks the input the server named and returns to it, since submission
  happens two steps later and a mark on an invisible field says nothing. (#897)
- **A refusal is marked or announced, not both.** The wizard's mutations no
  longer toast what the form is already showing beside the input it belongs to.
  (#897)
- **An abandoned submission cannot steer the wizard that replaced it.** Dismiss
  the dialog while a create is pending, reopen it, and the old refusal used to
  send the new session back to a step whose connector had been reset — a blank
  dialog caused by a form the reader had already left. Each opening is its own
  session now; a superseded answer is said and touches nothing else. Blocking
  dismissal while submitting was the alternative and would have trapped a reader
  behind a hung request. (#897)
- **Both write paths refuse the same way.** `create_source` carried its own copy
  of the validate-and-raise; it goes through the same helper as clone and update,
  so the two cannot drift apart again. (#897)
- **A refused model id is no longer posted back.** `details` is serialized into
  the response body *and* written to the log line beside it, so refusing a bare
  OpenRouter id sent the caller's own submission into the deployment's logs. It
  names the `model` field now and the id is gone. (#898)
- **Two provider refusals name the input they are about.** "This provider is
  keyless so it needs an endpoint" and "this provider needs a key" both answered
  with the provider, which is neither `base_url` nor `secret_id` — so the sentence
  arrived with nothing marked. (#898)
- **A stale key refusal is cleared when the key changes.** Both routes to a new
  key only set the value, so the sentence survived under a key the reader had
  already replaced — a refusal that accuses the current value is worse than
  none. (#898)
- **The mark and its reason are associated.** The model combobox announced
  "invalid" to a screen reader and never why; it goes through the same
  `FormField` the endpoint already used, so the bespoke `invalid` prop that would
  have been a second convention is gone. (#898)

## [0.0.199] - 2026-08-18

### Fixed

- **The storage-root check is a barrier the query actually applies.** 0.0.184
  rewrote it into the `realpath` + `startswith` idiom `py/path-injection` models
  and closed one of the three alerts it claimed; #14 and #15, both sinks in
  `LocalFileStorage.load`, survived on `main` for thirteen releases. The idiom
  was right and the *shape* was wrong: the query clears a normalised path only
  where the `startswith` call alone decides the branch, and the check was written
  `if candidate != base and not candidate.startswith(prefix)`. Falling through
  `A and B` proves neither conjunct, so the guard never applied. The root is
  answered in its own branch above, leaving `startswith` as the whole condition
  of its own — same refusals, same message, same tests. Established by running
  CodeQL 2.26.3 with `codeql/python-queries` over this tree rather than by
  predicting it: two results before, none after. (#903)
- **What 0.0.184 claimed about those alerts is corrected in its own entry**, so a
  reader who goes looking there finds what happened rather than the claim. (#903)

### Added

- **A test that fails if the containment check stops being one condition.** It
  reads `_resolve_safe_path`'s AST and asserts the `startswith` call is the whole
  test of its branch — the property 0.0.184 lost, which every behavioural test in
  the file passed straight through. It pins the shape; only CodeQL answers the
  verdict, and the pull request's own scan is where that is read. (#903)

## [0.0.198] - 2026-08-18

### Fixed

- **Eighteen refusals that name a field now mark it.** They answered with a
  singular `details={"field": "<name>"}`, and the frontend reads the plural
  shape and FastAPI's own `detail` and nothing else — so a mistyped model
  endpoint, a blocked MCP server URL and a spec YAML that would not parse each
  delivered a sentence to a toast and left every input unmarked. The same defect
  0.0.195 fixed for `details["errors"]`, in the third shape it deliberately did
  not touch. `refused_field` takes the sentence **once**, so the envelope's copy
  and the field's cannot drift apart. (#891)
- **A sandbox probe's 404 stopped blaming the address.** It is the one failure
  the two callers of `_get_json` do not share — a session that ended, versus a
  service with no such endpoint — so naming `base_url` for both would have put
  "Sandbox session not found" under the operator's Address box: confidently
  wrong where it had been merely vague. (#891)

### Changed

- **The rules that teach how to write a refusal name the helper.**
  `.claude/rules/exceptions-security.md` and `docs/patterns.md` still taught
  `{"field": "base_url"}` as *the* way to name a field a refusal is about, and
  never mentioned `app/core/field_errors.py` — so this change would have removed
  the shape from the code and left the instruction to recreate it, which is
  exactly how `assistant.py` and `UserRole` outlived their own deletion. (#891)

## [0.0.197] - 2026-08-18

The `e2e` job stopped stalling for twenty-five minutes on an apt mirror.

### Fixed

- **Nothing was cancelling those jobs.** GitHub records a job it ends on its own
  `timeout-minutes` as `cancelled` rather than as a failure, and a `cancelled`
  required check is not a pass the way a `skipped` one is — so the merge stayed
  blocked on a diff that was fine. Across 300 runs, 15 jobs ended that way, and
  the jobs API names the same step in fourteen of them: `Install Playwright
  browsers`. `--with-deps` shells out to `apt-get`, the runner's mirror answers
  `Ign` for every index, and apt stops dead on the fallback — 22 minutes of
  silence. The flag bought nothing: on a healthy run every library Chromium
  links against is already the newest version, and the 21 MB it does install is
  fonts no spec renders. It is gone, and the full suite still passes. (#879)
- **A stall now fails the step that stalled, by name.** Step-level bounds sit
  under the job's, so a residual hang says which step rather than ending the job
  at its outer limit with no explanation. `test_ci_workflow.py` refuses any step
  that installs system packages, so the flag cannot come back quietly. (#879)

### Changed

- **`make coverage-all` runs across worker processes**, like `test` and
  `test-fast` already did. It was the one suite still single-process, which is
  what made 25 minutes reachable on a slow runner: 14m46s of a job for a number
  that does not gate anything. Measured on the branch's own run, the step went
  from 4m31s to 2m41s, and `Install Playwright browsers` from 70s to 1s. (#879)

## [0.0.196] - 2026-08-18

### Fixed

- **An MCP server that writes an address nothing can dial is refused, not
  crashed on.** `httpx.InvalidURL` does not subclass `httpx.HTTPError`, so it
  escaped all three catches in the OAuth flow and answered 500 — one layer
  further out than 0.0.190's fix could reach, because `httpx` refuses to build
  the URL before this project's validator is ever called. Discovery treats an
  unusable candidate as ending *that candidate*: a server with a broken
  `WWW-Authenticate` hint and correct well-known documents still connects. The
  two sites below it raise a refusal of their own. (#889)
- **"Nothing can dial this" and "we will not go there" stay two different
  claims.** The refusal for an unbuildable address is deliberately distinct from
  the blocked-address one, so a failure never misattributes whose fault it was.
  The address itself goes to the log: `InvalidURL`'s message quotes the text it
  could not cast, and on this flow that text is written by the server being
  refused. (#889)
- **`create_client_registration_request` is guarded at all** — it sat outside the
  try it appeared to be inside. (#889)

## [0.0.195] - 2026-08-18

A refusal that names a field marks that field.

### Fixed

- **A per-field refusal highlights the input it names.** The forms mark an
  offending field from `details.fields`, and four refusals answered with
  `details.errors` instead — so an ingestion override, a spec import and a
  capability setting each showed a sentence and left every box unmarked. That is
  the half that says *which one to fix*, and it was missing from three fixes
  released earlier today. One module builds the shape now, reading `loc` and
  `msg` only, so what is left out is decided once rather than remembered at four
  call sites. (#882)
- **A capability setting refused at publish reaches the Builder.** Saving a draft
  does not validate a config schema, so publish is the only place a mistyped
  setting is refused — and the accumulator kept the message and dropped the
  path. Paths are qualified by capability, and by specialist where one applies,
  because two capabilities can hold a setting of the same name and the Builder
  draws a form per specialist over the same set. `SchemaForm` has accepted an
  `errors` prop since it was written; nothing had ever passed it. (#882)
- **A field genuinely called `body` is no longer mistaken for FastAPI's
  transport marker.** The two are told apart by which entry point is asking, not
  by the string: a spec whose top-level key is `body` now says so. (#882)
- **The same field refused two ways answers with the same path.** An upload's
  ingestion override and a collection's own settings both name
  `ingestion_config.chunk_size`, where only the cross-field rule used to line
  up. (#882)

## [0.0.194] - 2026-08-18

MCP OAuth connects to the address it checked, at every hop.

### Fixed

- **The addresses an MCP OAuth flow reaches are pinned to what passed the
  check.** The authorization server, token endpoint, registration endpoint and
  every redirect after them come from the *remote server's* discovery documents,
  not from an operator — and the validator returned a string, so the name was
  resolved a second time to connect and whoever controlled it decided what the
  second answer was. One hostile server was enough, with no operator
  complicity. Every request now goes to an address that passed, with the
  original host in the `Host` header and in TLS SNI, so certificate
  verification is unchanged. (#860)
- **A redirect to a new host is re-checked rather than followed on trust**, and
  the flow walks the hops itself so it can count them. Substitution happens
  inside the transport on a copy of the request, which is also what keeps a
  relative `Location` resolving against the name rather than against the pinned
  address. (#860)
- **Every validated address is tried, not only the first.** A name with several
  public records used to lose the rest, so an unreachable first answer — an
  IPv6 record in an IPv4-only network — failed the flow where an ordinary
  client would have moved on. Only a refused connection moves on, because that
  proves nothing was sent; a failure after the connection is raised, since a
  token grant may already have been processed. A mixed answer is still refused
  whole. (#860)
- **An outbound proxy still works, and the notes say where the pin ends.**
  `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` behave as they did — refusing to
  run when proxied would have cost a proxy-only deployment MCP OAuth entirely,
  in exchange for an egress control it already has. What is pinned is the
  address the proxy is *asked* to reach; TLS stays end to end either way. (#860)
- **A refused hop says so without quoting the URL.** The OAuth error is a fixed
  sentence; the address goes to the log. The catches were narrowed from
  `ValueError` to the refusal type this repository raises, so an unrelated
  library failure is no longer reported as "this server pointed us at a blocked
  address" — a confident claim about whose fault a failure was. (#860)

## [0.0.193] - 2026-08-18

### Fixed

- **The model picker stops telling an organization it has no models when the
  request failed.** It made that claim from an array a refused or failed read
  degrades to `[]` — the ambiguity 0.0.186 fixed one element above it, on the
  page — and it made it in both of the picker's shapes, so an `allowAdd` panel
  also dropped its saved-model disclosure silently. A failed read now says so and
  offers a retry. (#863)
- **And it says nothing at all while the answer is still coming.** The flag
  behind the distinction is the query's success, which is equally false before
  the first answer as after a failure, so the first version of this fix showed a
  destructive failure panel on **every cold render of the Builder** — a false
  alarm on the ordinary path, which is worse than the wrong sentence it replaced.
  The hook answers with three states now, not two, and 0.0.186's page-level
  consumer reads the same one, so there is no second vocabulary to drift. (#863)

## [0.0.192] - 2026-08-18

### Fixed

- **A network blip no longer fails the dependency audit.** `pip-audit` asks
  pypi.org once per locked distribution with no retry, so one slow answer ended
  the run and turned `Security Scan` — a required check — red on a pull request
  whose dependencies were fine. Every run that reaches no verdict is retried now,
  unconditionally: re-running a deterministic failure costs seconds and the same
  answer, while not re-running a transient one is the false red this fixes. (#855)
- **The audit says which of four things happened, in a line a job can read.**
  `make audit` ends on `AUDIT: CLEAN|VULNERABLE|NETWORK|FAILED — detail`, mirrored
  into the job summary. The exit code cannot carry that: GNU Make turns any failed
  recipe status into its own 2, and GitHub Actions never surfaces a step's exit
  code anyway — so a code was the wrong place for a verdict, whether or not `make`
  was in the way. The script keeps 0/1/75 for a human at a terminal, and
  `docs/commands.md` now says which interface delivers which. (#855)
- **An audit that did not happen is never green.** The verdict comes from the JSON
  report, which `pip-audit` writes on both the clean and the vulnerable path and
  only after every distribution has been queried — so its presence means the audit
  finished, whatever the process exited with. (#855)

## [0.0.191] - 2026-08-18

### Fixed

- **A hand-edited agent spec says which field is wrong.** `AgentSpec.from_yaml`
  was called inline in the route expression, and a pydantic `ValidationError` is
  a `ValueError` but not a `RequestValidationError` — so every mistake in an
  imported spec answered 500 with no field path and left a traceback in the log,
  on an endpoint whose ordinary case *is* somebody iterating on YAML by hand. The
  parse moved into the service that owns the refusal: a rule broken answers 400
  with the field path, YAML that will not parse answers 400 with the line and
  column, and
  a document that is not a mapping says so. (#873)
- **A syntax error reports its position, never the line it read.** `str()` on a
  marked YAML error includes the offending source, and the document being refused
  is somebody's spec — instructions, a `secret_id`. Neither the failing text nor
  the submitted values come back; a reader error with only a byte offset gets no
  invented position. (#873)
- **Nothing is read or written before the document is judged.** The parse runs
  first, so a refusal depends only on the caller's own text: it opens no
  transaction and says nothing about which agents exist. (#873)

## [0.0.190] - 2026-08-18

### Fixed

- **An ingestion override the pipeline cannot use is refused, not crashed on.**
  An upload whose `chunk_overlap` is not smaller than its `chunk_size` was
  rejected by a validator whose own docstring said "the form is what says so" —
  and the form got a 500 with `details: null`, while the log took a traceback for
  a number somebody typed. Both upload routes answer 400 naming both settings,
  before the file is stored, and the submitted values are not echoed back. A
  collection's own settings were already correct: they arrive as a schema field,
  so FastAPI refuses the same pair with a 422 before the route is entered, which
  is now pinned by a test rather than asserted in prose. (#874)

## [0.0.189] - 2026-08-18

### Fixed

- **A blocked MCP server URL names the refusal instead of answering 500.**
  `SSRFBlockedError` is a `ValueError` and nothing mapped it, so an operator
  pasting an address that resolves to a private host got "an unexpected error
  occurred" and left a traceback in the log as though the platform had broken.
  All five call sites — personal and organization, create, update and the OAuth
  start — answer 400 naming the `url` field. (#861)
- **A URL with an unusable port is refused rather than validated.**
  `http://8.8.8.8:not-a-port/x` used to come back as checked, to a client that
  could not dial it — the IP-literal branch swallowed the parse error. (#861)
- **The validator stopped calling an MCP address a webhook.** Its messages said
  "Webhook URL blocked" to somebody who had just typed a server URL, and the same
  text reached the browser-automation publish problem. `validate_webhook_url` has
  had no webhook caller for some time. (#861)

  Caught in review of the same change, and never released: an intermediate
  version of the refusal caught `ValueError` broadly, which would have put the
  caller's own text — `urlsplit` parses the port at attribute access, so
  `http://example.com:client_secret=abc123/mcp` produces a message carrying that
  secret — into the 400 body. `UrlRefusedError` is the base for refusals written
  here, the catch is narrowed to it, and a parametrised test asserts that
  invariant so the next bare `ValueError` fails a test rather than reaching a
  response. Before any of this the malformed port answered a generic 500, so no
  released version put that text in a body.

- **The frontend suite has deadlines it can actually meet.** `test-frontend`
  went red on specs that pass in about a second alone, and the diagnosis in the
  issue was half right: measured over four whole-suite runs, coverage
  instrumentation is a 1.6x multiplier on an idle machine but 3.6x on a busy
  one, and **the bare run failed under load too** — so this was never a coverage
  defect, and a deadline that differed between the fast loop and the gate could
  not have reproduced the gate. `testTimeout` moves to 15s, which is 2.5x the
  worst duration measured under load and the figure `playwright.config.ts`
  already justifies for the same class of problem. (#862)
- **The second deadline nobody had noticed.** Two of the three failures in each
  loaded run were Testing Library's own 1s `asyncUtilTimeout`, not
  `testTimeout` — including one of the two specs the issue named, so raising
  `testTimeout` alone would have left the reported symptom reproducible. It goes
  to 5s, deliberately well under `testTimeout`, so an element that is never
  coming loses the race and the failure names it rather than blaming the test.
  (#862)

## [0.0.188] - 2026-08-18

An approval nobody was ever asked for is refused rather than assumed.

**Upgrading:** an agent published with `approval: required` on a search or fetch
its model provider executes **stops running** on this version, with the same
sentence publish would have shown. It is deliberate. Such an agent has been
running without the approval its author asked for — `ApprovalGate` wraps tool
execution, and a provider-executed tool never reaches it — so keeping it running
means keeping the bypass. Set the capability's method to a locally-run one, or
drop the approval requirement, and republish.

### Fixed

- **A provider-executed search cannot be sold as approval-gated.** `web_fetch`
  got this refusal in 0.0.182; `web_research` had the same shape and the same
  silence, with the queue staying empty while the agent searched unapproved.
  (#857)
- **The refusal now also covers agents published before it existed.** Execution
  loads a frozen `AgentVersion` and hands its spec straight to `build_agent`
  without going near `validate_spec`, so a publish-time check alone left every
  already-published agent — including every `web_fetch` one from 0.0.182 —
  bypassing indefinitely. `build_agent` refuses before it assembles anything,
  the way it already refuses an ungranted scope or a deleted secret. (#857)

### Changed

- **A capability declares which of its tools the provider may execute**, through
  `provider_executed` on its registration, and the publish and assembly checks
  read that. The knowledge was a table of capability internals in the service
  layer, which had already gone stale once — and that staleness is exactly what
  #857 was. Tests now assert the declarations name tools and config fields that
  exist, because both halves are silent when wrong: they refuse nothing. (#857)

## [0.0.187] - 2026-08-18

The product teaches itself: a first-run tour, and guided flows that build the
first of each thing.

### Added

- **A passive walkthrough on every dashboard page, replayed by its "?".**
  `TOUR_STEPS` is a registry keyed on the page, each step gated on the
  permission its control carries, so a walk never waits on an element a refusal
  never mounted. Where the completion is stored is the point: `PATCH /users/me`
  rather than a `localStorage` flag, so somebody who signs in on a second
  machine is not walked through it again. (#53)
- **Guided creation flows.** At the end of a walk the product offers to build
  the thing the page is for — an agent, a collection, a skill, an MCP
  connection — with a coach that spotlights one control at a time and waits for
  the signal that the step actually happened rather than for a click. The
  organization's state is frozen when a flow starts, so the steps cannot morph
  under the reader mid-walk. (#53)
- **Three e2e specs for the tour itself**, which the feature had shipped
  without. (#53)

### Fixed

- **The seeded e2e owner is marked as having finished onboarding.** Without it
  the tour auto-opened over every spec that landed on the dashboard and, with
  `allowClose: false`, swallowed the clicks — six specs red for a reason that
  had nothing to do with what they were testing. (#53)
- **A "?" pressed where nothing is walkable closes itself.** A page that renders
  the header but has no steps — or whose steps a permission filters to nothing —
  froze the anchor with an empty list and no popover, so there was no close
  button and nothing ever called `close()`: every later "?" on any page
  recomputed from the stale anchor and stayed empty, leaving the button dead
  app-wide until a reload. (#53)
- **Skip cannot loop on an answered question.** With `agents:edit` and
  `collections:edit` but no `agents:publish`, the agent flow ends on the
  knowledge fork; stepping past the end bounced back onto the answered question
  and re-answered it forever. The step index is resolved against the list the
  flow actually produces rather than guessed at. (#53)
- **Enter and Space no longer walk through the coach's guard.** The freeze
  blocked pointer events only, so Enter in a dialog's name field submitted the
  form three steps early — the collection was created, the later step baselined
  its count after the fact, and the signal it waited for could never fire. Both
  keys are blocked on the guarded control, with Enter keeping its input-wide
  block. (#53)
- **A keyboard user can finish a step.** The coach card is a real dialog now —
  `aria-modal`, focus moved to it on each step, Escape to leave — and the trap
  cycles the card *and* the spotlit control, because a step that waits for a
  signal renders no Next button and confining Tab to the card alone would make
  it uncompletable. (#53)
- **The coach does not offer to build what the organization already has.** While
  the live state was still null it fell back to "this organization has
  nothing", so the "no published agent — build one first?" fork could appear for
  an organization with one and then swap away underneath the reader. (#53)

## [0.0.186] - 2026-08-18

### Fixed

- **The Builder says up front when a draft can never get a model.** A member with
  `agents:edit` but not `connections:manage`, in an organization that has stored
  no model profile, could build an agent they cannot publish: the picker's "add"
  control is gated on a permission they do not hold, and publish is refused
  without a model. Nothing said so until publish failed, and then it pointed at
  the permission rather than at what to do. The panel now says it where the
  missing control would be. (#591)
- **A failed profile query is no longer read as an empty organization.** The hook
  degrades a refused `/providers/model-profiles` to `[]`, and its loading flag
  goes false when retries are exhausted as well as when an answer arrives — so a
  502 told somebody with a dozen models to go and ask an admin for one. The
  notice waits on the query's own success now, not on the absence of loading.
  (#591)
- **The notice waits for the permission set before claiming the caller cannot add
  a model.** `can()` answering false while the set is still loading is right for
  *hiding* a control and wrong for a sentence that tells somebody what they may
  not do: false there means "not known yet". (#591)

## [0.0.185] - 2026-08-18

Three places where the code said something about itself that was not true.

### Fixed

- **`EMAIL_PROVIDER=resend` silently sent nothing.** `get_email_provider` had no
  `case "resend"` and the match ended `case "log" | _`, so a deployment setting
  the value its own module docstring advertised got the *development* provider:
  every invitation, password reset and approval notice was written to a log line
  and returned `accepted=True`. Nobody found out, because every call site catches
  and logs. An unknown value is refused now, with the supported set in `details`,
  and `ResendProvider` — never reachable — is deleted rather than wired up.
  `LOG_PROVIDER_WRITE_TO_DISK` is passed through, which it never had been. (#829)
- **The OAuth refusals no longer say where the server keeps its files.** Two of
  them quoted the whole URL back, query string included, on a path whose
  endpoints are reached with credentials. They name the host now, or nothing
  where there is no host. (#840)
- **A claim about who chooses an MCP OAuth URL is corrected in all four places
  that made it.** "Bearable because an operator types the address" holds for a
  connection URL and a `cdp_url`, but not for the OAuth flow, where the
  authorization server, token endpoint, registration endpoint and every redirect
  hop come from the remote server's discovery documents — one hostile server is
  enough, with no operator complicity. Pinning the validated address is a
  transport change and is tracked in #860; what shipped here is the code and the
  documentation saying what is actually true. (#840)
- **The written-to-disk log filename is safe by construction and unique**:
  `{timestamp}_{msg_id}.html`, with the subject moved to the log line beside the
  path. Two messages in the same second no longer overwrite each other either.
  Not a traversal, despite appearances — the timestamp prefix means the first
  path component is never `..` — and the docstring now says so rather than
  leaving the next reader to re-derive it. (#840)
- **The `ty` relaxations name libraries this project actually has.** They were
  justified by langgraph and deepagents, which never were dependencies, and by
  langchain, which stopped being one. (#833)

## [0.0.184] - 2026-08-18

### Fixed

- **The storage-root check is written so a static analyser can follow it** — a
  `Path.parents` membership test is correct and invisible to the query, and an
  alert nobody can close is an alert everybody learns to ignore. (#841)
  **Correction:** this said it closed three CodeQL `py/path-injection` alerts. It
  closed one. #14 and #15 stayed open on `main` because the check was written as
  a conjunction, which is not a shape the query accepts as a barrier; fixed in
  0.0.199 (#903).
- **A filesystem root can be the storage root again.** The rewritten check built
  its prefix as `base + os.sep` unconditionally, so with `MEDIA_DIR=/` the prefix
  was `//` — which nothing under `/` starts with. `load`, `delete` and
  `get_full_path` all refused with "Path escapes storage root" while `save`
  carried on writing, leaving the store handing back paths it could no longer
  read. The separator is appended only when the root lacks one, and the
  comparison stays a `startswith` on a `realpath` result rather than moving to
  `commonpath` or `is_relative_to`: both are correct, and neither is a barrier
  the query models. (#841)

## [0.0.183] - 2026-08-18

Chunking is ours, and `langsmith` is out of the image.

### Changed

- **The RAG pipeline splits text with its own splitters.** Two classes and one
  method replace the LangChain tree — ten megabytes and eight transitive
  packages, of which the notable one was not the size: `langsmith`, LangChain's
  hosted-observability client, sat in every image built for a platform that
  standardised on Logfire. It was never configured and never imported by us; it
  arrived behind a text splitter. `RecursiveCharacterSplitter` is a port of the
  library's at 1.1.2, narrowed to the one configuration the pipeline built, and
  `MarkdownHeaderSplitter` finds the same sections and then runs the recursive
  splitter over each. Golden tests pin the chunk boundaries so the port cannot
  drift. (#158)
- **The `markdown` strategy honours `chunk_size` again** — it had been silently
  ignoring it. (#158)

### Fixed

- **A document's chunk count is recorded**, where the only stored count was a
  constant 0 — which is also what made a chunking change unmeasurable, and why
  it had to land with the splitters rather than after them. (#147)
- **Re-ingesting a document no longer counts it twice.** A replacement deletes
  one vector document and inserts one, but every dispatch created a fresh
  tracking row, so the superseded row outlived its vectors and kept its
  `chunk_count` in the collection's total. The replaced row and its stored file
  are retired now. (#158)
- **The over-size warning no longer fires at exactly the limit.** A chunk of
  exactly `chunk_size` is within it. The comparison that decides the split is
  untouched — widening that would move every boundary in every collection
  already ingested, which is what the golden tests exist to prevent. (#158)

## [0.0.182] - 2026-08-18

An agent can read the page its search found, and cannot be gated by a gate that
would not hold.

### Added

- **`web_fetch` — a capability that reads one URL and returns the page as
  Markdown.** `web_research` returns titles, URLs and snippets and nothing
  fetched a page, so an agent answered from the snippet and cited a page it had
  never opened. Its own capability rather than a second tool on `web_research`,
  because it composes with every search method — including `native`, where the
  builder returns Pydantic AI's own `WebSearch` and contributes no toolset of
  ours, so a tool added there would be missing for exactly the agents most
  likely to want it. "May this agent dereference whatever URL it likes" is also
  a different grant from "may it search": `web:fetch` is its own scope. (#51)
- **The Builder can edit a list of strings.** The generated form fell back to a
  text input for an array-valued property, so typing a hostname into an
  allowlist stored a scalar string that Pydantic then refused — leaving the
  field blank was the only publishable path. Arrays of strings now render as one
  comma-separated input; arrays of anything else still fall through. (#51)

### Fixed

- **A fetch the model provider runs cannot be sold as approval-gated.**
  `ApprovalGate` wraps tool execution, which is the only place a call can be
  held, so a provider-native fetch never reaches it: under `method: native`
  there is no local tool at all, and under `auto` there is one only on a model
  with no native fetch. A binding that asked for approval and chose either got a
  gate that never fired — the queue stayed empty and the agent read pages nobody
  approved, silently. It is refused at publish now, rather than repaired by
  forcing the local tool: which of the two an author wants is their decision,
  and `auto` is refused alongside `native` because which one runs is a property
  of the model profile and changes without republishing. (#51)
- **A domain filter matched one spelling of a name that has several.** A
  denylist holding `xn--exmple-cua.com` did not stop `https://exämple.com/`, and
  `getaddrinfo` resolves the two identically — so the miss was a fetch rather
  than a failure, and the validator's ASCII-only pattern left no way to write
  the alias by hand. Entries are stored as the single name DNS would be asked
  for (lower case, no root label, IDNA-encoded with the same codec
  `getaddrinfo` uses), and every equivalent spelling reaches both the native and
  the local filter. (#51)
- **An empty `blocked_domains` is no longer refused with the allowlist's
  error.** The two fields do not mean the same thing by `[]`: an empty allowlist
  allows nothing, an empty denylist denies nothing — which is exactly what
  `null` says. A spec imported from YAML or posted by an API client spelling "no
  denied hosts" that way was refused for saying something true. (#51)

## [0.0.181] - 2026-08-18

### Changed

- **jsdom moves to 30.0.1** in the frontend test environment. The bump arrived
  without a regenerated `bun.lock`, so `test-frontend` and `e2e` both failed at
  the install step — `lockfile had changes, but lockfile is frozen` — before
  either had run a single test, which is why the red read like the major version
  breaking the suite. With the lock regenerated the suite is green on jsdom 30:
  308 files, 4704 tests. (#850)

## [0.0.180] - 2026-08-18

### Fixed

- **Every `backendFetch` route says `no-store`.** The 44 route files under
  `orgs/**`, `me/**`, `admin/**`, `sessions/**` and `auth/**` answered with no
  `Cache-Control` at all, so the members, invitations and integrations lists
  refetched right after a create, invite or revoke could be served from cache —
  the same staleness class as #230, on the one surface the shared proxy does not
  cover. `platformProxy` already stamps the header on anything the backend left
  unmarked; a hand-rolled route owes the same, and now cannot forget it: every
  `NextResponse.json` goes through `bffJson`, which stamps `no-store` and leaves
  an explicit policy alone. The binary routes that set their own `max-age` keep
  it. (#553)

## [0.0.179] - 2026-08-18

### Changed

- **Disconnecting an MCP server asks in the product, not in the browser.**
  `window.confirm` was the lone holdout after rag, agents, skills and embeds
  moved to `ConfirmDialog`; the confirmation is now keyed on the pending
  connection, and a second click while the DELETE is in flight is a no-op rather
  than a second request. (#554)
- **The two MCP dialogs left the list component.** The connect/edit dialog and
  the tool picker move into their own modules, taking `mcp-server-list.tsx` from
  about 985 lines to 765. A pure move — the JSX is unchanged and the parent
  keeps its state and both handlers — with the shapes all three share extracted
  to a leaf module so a dialog never imports the component that renders it.
  (#569)

## [0.0.178] - 2026-08-18

The collection page is server state again, not seven `useState` slots.

### Changed

- **`useKBDetail` moved onto React Query.** Seven pieces of local state became
  `qk.kb.detail(id)`, `qk.kb.documents(id)` (paged with `useInfiniteQuery`) and
  three keyed section queries, so an external mutation can invalidate the page
  and the two keys that were dead are live. The bespoke tenant-clearing block is
  gone — `useTenantCacheReset`'s `removeQueries()` already covered it. A cold
  first-load failure stays distinct from a failed refresh: one is the page's
  error, the other is the last good answer under a stale banner. (#557)
- **The admin query-key factories are typed to their real parameters**, the dead
  `admin.users` factory is gone, and the `{ summary: true }` discriminator went
  with the ratings page it distinguished against. (#558)
- **The sandbox `usage` discriminator lives in the key**, not at the call site:
  a listing the service sampled for per-sandbox usage is a more expensive
  request than one without, and the two must not share a cache entry. (#569)

### Fixed

- **The members table waits for the permission answer before drawing its action
  column**, rather than drawing it and then discovering the caller may not use
  it. (#569)
- **`api/files/[id]` encodes its path segment**, and `patchKB` rethrows the way
  its siblings do. (#569)
- **A sync source written into an unread cache now shows up.** The three
  sections sit behind `connections:manage`, so a refused read leaves nothing
  cached while the write is still allowed — the write's second arm covers that,
  and now has the test to say so, along with the tenant guard on the two writes
  that add a row. (#569)

## [0.0.177] - 2026-08-18

### Changed

- **Thirteen backend dependencies move up** — the backend-everything-else group,
  at the versions the lockfile now holds: `uvicorn` 0.52.3, `pydantic-settings`
  2.15.0, `sqlalchemy` 2.0.52, `alembic` 1.19.1, `greenlet` 3.5.5, `prefect`
  3.8.3, `llama-cloud` 2.14.0, `liteparse` 2.13.0, `boto3` 1.43.73,
  `pydantic-monty` 0.0.21, and `ruff` 0.16.3, `ty` 0.0.72 and `pre-commit` 4.6.2
  among the dev tools. Three of those resolve above the floor the group asked
  for, which is why they are quoted from the lock. The lockfile was resolved
  against the merged manifest rather than the group's own base, so Pydantic AI
  stays where 0.0.176 put it instead of being rolled back a release for the
  second time. (#838)

## [0.0.176] - 2026-08-17

### Changed

- **Pydantic AI's floor moves to 2.30.0**, with `genai-prices` at 0.1.2 — the
  agent-frameworks dependency group.
- **A group bump no longer rolls the lock backwards.** The bump resolved
  `pydantic-ai-slim` and `pydantic-graph` to 2.30.0 while `main` already held
  2.31.0, and `backend/Dockerfile` installs the lockfile verbatim
  (`uv sync --frozen`), so the "upgrade" would have shipped an image with an
  older Pydantic AI than the one before it. Re-resolved to 2.31.0, with
  `genai-prices` at 0.1.3, and the note above the floor now names that failure
  rather than a version it had already outlived. (#837)

## [0.0.175] - 2026-08-17

One mechanism draws every third-party mark, and 471 MB leaves the install.

### Changed

- **Every brand and provider mark comes from one generated glyph set.**
  `frontend/scripts/gen-brand-icons.ts` fetches each mark from the set that owns
  it and writes 89 of them as raw path data; `components/icons/glyph.tsx` is the
  one thing that turns that data into an `<svg>`, so `BrandIcon` and
  `ProviderIcon` draw identically rather than agreeing by accident. Adding a mark
  is a row in the generator's table and a re-run — never an import, never a
  hand-authored `d`. Three mechanisms answered this question before, and
  `@lobehub/icons` dragged in a second copy of `lucide-react` besides. Each of
  the 89 marks was rendered from the removed packages and diffed against its
  glyph: 89 identical, 0 differ. (#156, #836)
- **`bun run analyze` produces a report again.** `@next/bundle-analyzer` is a
  webpack plugin and Next 16 builds with Turbopack, so every run printed "no
  report will be generated" and exited 0. It is `next experimental-analyze` now.
  (#156)

### Added

- **`make lint` fails on a frontend dependency nothing imports.** knip, narrowed
  to the one question it is never wrong about, moves from `bunx knip@5` to a
  pinned devDependency with its ignores in `knip.jsonc`, each carrying its reason
  on the line above. `date-fns` sat unused for months *and* was listed in knip's
  own ignores, so the report that would have found it had been told not to look.
  (#156)
- **The frontend's OpenTelemetry spans can leave the process.** The SDK
  registered on every boot, but no compose file, Dockerfile or CI job passed
  `OTEL_EXPORTER_OTLP_ENDPOINT` through, so the spans were built and dropped
  in-process. The variable is passed through now, and the code says plainly what
  leaving it unset means. (#156)

### Removed

- **Four frontend dependencies — 471 MB and 290 packages off every install.**
  `react-icons` and `@lobehub/icons` (replaced by the generated set),
  `@next/bundle-analyzer` (see above), and `date-fns`, which nothing imported.
  `nanoid`'s four call sites all wanted a client-side id, which `chat-store.ts`
  already had; both now call `clientId()` in `src/lib/ids.ts`, keeping the
  non-secure-context fallback that an embedded widget on a plain-HTTP internal
  host depends on. `node_modules` goes from 1.2 GB / 1012 packages to 729 MB /
  722. (#156, #836)

## [0.0.174] - 2026-08-17

A delegate's provider text no longer reaches the parent's transcript through a
status answer.

### Fixed

- **`check_task` and `wait_tasks` name the exception's class, not the provider's
  message.** Both composed their `Error:`, `Retry N:` and `Outcome:` lines from
  `handle.error`, which embeds the exception's own text — and a model client's
  message carries the failing request URL with the key still in its query string
  on a custom `base_url`. What those tools return becomes a `ToolReturnPart`, and
  a return is stored *whole* on purpose, so `tool_retry_notice` (#695) could
  never reach it: the key landed on a stored tool-call row, rendered in the
  conversation and in run history to every member who can read the run, and
  streamed live as `tool_result`. Fixed upstream in
  `subagents-pydantic-ai` 0.2.20, which composes all four lines from
  `TaskHandle.exception`; the floor here moves with it. (#819)
- **The retry line leaked for delegations that eventually succeed.**
  `TaskHandle.finish` clears `error` on completion, so the handle ends clean —
  but a model that polled `check_task` mid-retry already has the answer on a
  transcript row, and nothing goes back to remove it. (#819)

## [0.0.173] - 2026-08-17

A dependency nothing imports is now a failing build, not a thing somebody
notices by reading all 46 lines.

### Added

- **`deptry` runs in `make lint`, over `app`, `cli` and `alembic`.** vulture
  reads the code and finds what is written but unused; deptry reads the manifest
  and finds what is declared but unimported. The scope is the point rather than a
  detail: scanning `app` alone called `tabulate` dead when `cli/commands.py`
  imports it, and removing it took the e2e seed down before a single product spec
  ran. A tree that ships and is not scanned is a tree whose imports do not count.
  (#155)

### Removed

- **Three distributions nothing imports.** `fastapi-cache2` and the eleven-line
  `app/core/cache.py` that called `FastAPICache.init()` on every boot — there is
  no `@cache` decorator on any route; `jinja2`, whose email templates are
  compiled ahead of time and read off disk; and the duplicate, weaker-floored
  `python-multipart` and `httpx` declarations. (#155)
- **The `try/except ImportError` around `rank-bm25`.** It guarded a case that
  cannot happen — hybrid retrieval fuses BM25 with the vector search and a
  deployment cannot choose otherwise — so the import moved to module scope. The
  24 MB of `numpy` behind it is the price of that, taken deliberately and now
  recorded in the manifest. (#155)

### Fixed

- **`anyio` was imported and undeclared.** `app/services/rag_document.py` imports
  it at module scope while the manifest declared it only in the `dev` group, so
  the image — built with `uv sync --no-dev` — was relying on Starlette to pull it
  in. Found by the new gate on its first run. (#155)
- **The manifest says why the ones that read as dead are alive.** `psycopg2-binary`
  (alembic builds a *sync* engine from a bare `postgresql://` URL, so removing it
  breaks every migration), `itsdangerous` (Starlette signs our `SessionMiddleware`
  cookies with it), `tabulate` and `pillow` — the last two listed as zero-import
  in the audit and both wrong, with call sites in `cli/commands.py` and
  `app/services/channels/chart_png.py`. (#155)

## [0.0.172] - 2026-08-17

All files answers "what is that file", not only "who is holding a copy of it".

### Added

- **Search and sort on the All files grid.** The same `useListControls` +
  `SearchInput` pair the five galleries use, filtering on path, agent name and
  extension — `.csv` matches the suffix rather than the string — and ordering by
  name, size, modified or agent. Size and modified descend, because "what is
  biggest" and "what changed" are the questions those orders answer. The bound
  stays on screen while a filter is applied, with a line saying the filter
  searched only what was read: a client-side filter over a truncated listing
  searched a sample, and "3 results" with no caveat would claim the search was
  exhaustive. (#138)
- **A tile is the file card every other surface draws.** The three-line row is
  gone; the grid now uses `components/files`' `FileCard`, so a CSV looks like the
  same thing in the composer, the transcript and here — including the suffix and
  size band (`CSV · 2.0 KB`) that was the extension-legibility half of the issue.
  The line under each card carries what only this view knows: the agent holding
  the file, who else can see it, and the download. (#138)
- **A stored text file previews its first lines, and a stored image draws
  itself.** Both come out of the JSONB document the listing already reads, so a
  grid of thirty tiles is still one request: eight lines capped at 200 characters
  for text, and a 160×128 `data:` URI for a raster image. A container-backed
  workspace answers `null` for both — its bytes are on a host, and one round trip
  per file is exactly what this listing refuses. (#827)

### Fixed

- **A thumbnail's decode is bounded by pixels, not by bytes.** A PNG under a
  kilobyte can declare 8000×8000, and scaling it allocates all 64 megapixels on a
  request somebody made by opening a page. Pillow's own ceiling does not catch
  it — it refuses at 89 megapixels — so the declared size is checked against a
  16 Mpx limit in the header, before any pixel is read. (#827)
- **A thumbnail is drawn as the image is.** Transparency survives (converting to
  `RGB` does not remove what the alpha channel hid, it paints it — usually
  black), and a camera's EXIF orientation is applied before the scale, so a
  portrait photograph is no longer sideways on its tile. (#827)
- **A file's React key joins its workspace and path with a separator.** Without
  one, `{workspace: "ab", path: "c"}` and `{workspace: "a", path: "bc"}`
  collided into a single key. (#138)

## [0.0.171] - 2026-08-16

Tool search's scale guarantee is pinned by a fixture, not a claim.

### Added

- **A fixture pins `tool_search`'s schema surface at scale.** An
  AgenticOS-native `FunctionModel` test at the `build_agent` seam compares an
  unbound agent against a `tool_search` one over deterministic 12-, 100- and
  1,000-tool catalogs, capturing the canonical bytes of the model-visible
  function schemas: 3,480 B / 28,736 B / 287,036 B unbound versus a flat 786 B
  with the binding — the deferred catalog never grows what the model sees. It
  then drives the whole closure — `search_tools`, reveal, execution of the
  revealed target — and proves the other deferred tools stay absent after the
  call returns. (#794)

The agent map draws the whole delegation tree, and says what it cannot.

### Added

- **The agent map renders the delegation tree recursively, from one endpoint.**
  `GET /agents/{agent_id}/delegation-tree` walks the draft's pins with the same
  resolution publish uses — one response instead of a page-walk per hop, with
  per-walk caches so a diamond is one read. Depth is the runtime's own bound
  (`min(inherited, own max_depth)`), so the tree shows exactly what a run can
  reach and marks the rest `truncated` rather than drawing it reachable. What
  the walk cannot resolve says so on the node: a delegate the caller may not
  see answers `restricted` (indistinguishable from a pin at nothing, so a
  shared map cannot probe private agents), a cycle is named and never
  followed, a gone version answers `unpinned`, a stale pin carries its number,
  and an **archived** delegate is named rather than drawn as a working hop —
  the same refusal the runtime raises when a run reaches it. On the map, first-
  level delegates keep their measured edges; each subtree hangs off its parent
  with a drawn connector, focusable and keyed by path; a tree still loading or
  failed says so in the notice instead of posing as a complete one-hop map.
  (#276)

The sandboxes page stops stacking two clocks down one scroll.

### Changed

- **`/sandboxes` is two tabs: connections, and what is running.** The
  configuration table and the live **Running on {host}** panel were one scroll
  on two clocks; now the active tab lives in the URL (`?tab=running`
  deep-links, the default keeps the parameter off) and the live query only
  exists while its tab is on screen — the ten-second poll stops on a page
  nobody is looking at, pinned by a test that the sessions hook is never even
  constructed. The running tab names its host and lets an operator switch
  (closing the activity log on the switch, so one host is never asked for
  another's session); a failed connections request renders the error, never a
  false "no container connection registered"; the sessions table sorts,
  filters and explains an empty match; and the activity log is a labelled
  `DataTable` instead of a bare table in a grey box. (#140)

"dev should serve v3" is answered on the environment's own row.

### Added

- **An environment row pins its own version.** Each environment in the History
  tab carries a select of the agent's published versions, calling the same
  `promote` mutation the Versions list's **Promote to…** menu already used —
  two directions through one edit. The row also renames (the default
  environment is refused one, its name being part of the publish contract; the
  mutation sends the name and nothing else, so a relabel can never silently
  repoint a pin — and an unchanged name sends nothing at all, so the audit log
  records no rename nobody made). A pin at a version genuinely gone renders as
  `v9 (removed)` — legible, since that stale pin is exactly why the agent is
  not answering — while a version merely unlisted (the history still loading,
  or a pin older than the fifty-publish page) renders plain, never with the
  false verdict. (#134)

A workspace file's header finally says when it changed, not only how big it is.

### Added

- **Workspace listings carry a file's modified time to the viewer.** The shared
  file viewer's header could always render `modified …`, but only a knowledge
  base document ever supplied a time — a workspace file stopped at the size.
  Rides on pydantic-ai-backend 0.2.26's `FileInfo.modified_at` (ISO 8601,
  optional): a stored workspace records one on every write inside its JSONB
  document, a workspace archive reports `st_mtime`, and a live container's
  shell listing honestly answers `null` — never a guess. `WorkspaceFileRead`
  (and `FlatFileRead`) gain `modified_at`, the three listing routes pass it
  through, and the chat panel, the workspace explorer, the flat browser and
  the chat tool-result card all hand it to the viewer. (#500)

A run's spills no longer pile up on a container workspace that outlives it.

### Fixed

- **A run's spills are pruned off a container workspace at close.** #804
  stopped `tool_output/` spills outliving the run on a `state` backend, but a
  longer-scoped container workspace (`conversation`/`user`/`agent`) still kept
  every past run's blobs on its filesystem forever. The overflow store now
  records each handle it writes to a per-run spill log — shared with delegates
  that share the parent's sandbox — and `close` deletes exactly those paths
  through the backend's own `execute`. Exact handles, not a prefix sweep, so
  two concurrent runs on a shared workspace cannot take each other's spills
  mid-flight; the `rmdir` of a still-shared spill directory fails silently,
  which is the correct answer, while a refused `rm` keeps its status and is
  logged (`workspace_spill_prune_failed`) rather than raised. Every path is
  checked against the reserved-prefix invariant — `..` refused outright —
  before it reaches the shell. (#803)

A delegated run's failure is written in the platform's words, never the
provider's.

### Fixed

- **A delegated run's stored error is composed, not copied.** A failed
  delegation wrote `agent_runs.error` and its closing `SubagentFinished` frame
  from the subagents library's own exception text — routinely a provider
  client's message carrying the failing request URL, key still in its query
  string on a custom `base_url`. The settlement now composes the same
  controlled sentence the parent's row gets (`run_failure_summary`, moved to
  `app/agents/failures.py` so the capability layer can reach it), and the
  library's text goes to the server log with the original exception beside it.
  Rides on subagents-pydantic-ai 0.2.19, whose `TaskHandle.exception` hands the
  platform the exception instead of a string to parse. The two deliberate
  exceptions keep their own words whole: pydantic-ai's `UsageLimitExceeded`
  (the delegation's own ceiling doing its job) and `BudgetExceeded` raised
  inside a delegate by the parent's shared ledger — a ceiling sentence with its
  numbers is the one failure text the reader acts on. (#699)

## [0.0.164] - 2026-08-16

An agent stops forgetting its instructions mid-run, and remembers across turns.

### Added

- **The `system_reminders` capability.** Re-states steering guidance mid-run to
  counter instruction fade — a model progressively ignoring the guidance it
  started with after many tool-use turns. Three declarative reminder kinds, each
  on its own cadence (`interval` / `first_after` / `max_fires`): fixed
  `reminders[]` lines, `goal_reanchor` (the run's first user request, re-stated),
  and `llm_reminder` (a model-written nudge from the recent transcript, metered
  to the run's ledger, running on the run's own model under its limits minus one
  reserved request, falling back to the goal-reanchor line on any error). The
  cadence is durable per conversation — counters live in a new
  `conversations.reminder_state` JSONB column, so leaving and reloading a
  conversation resumes it; only the counters are stored, never the reminder
  text. A fired reminder is injected as an ephemeral prompt part behind a
  `CachePoint`, so it never enters `message_history` and the cached prefix stays
  byte-identical turn over turn. (#787)

## [0.0.163] - 2026-08-16

An oversized tool return stops eating the run, and nothing spills onto shared disk.

### Added

- **The `tool_output_limits` capability.** A tool return too large for the
  model's window is reduced once, when it is produced, instead of being re-sent
  in full on every later request of the run. Three actions per binding: `spill`
  (default, lossless — the full return goes to the agent's own sandbox backend
  under a `tool_output/` prefix and is replaced with a handle + preview the model
  pages through with `read_tool_result`), `truncate` (a cheap clamp with a marker
  saying what was cut), and `summarize` (an LLM summary on the run's own model,
  its spend booked to the run's ledger). Spills land on the tenant's own backend,
  never shared disk — an agent with no backend gets an in-memory one discarded
  with the run — and a spill the backend refuses degrades to a truncation, never
  a silent drop. (#57)

### Fixed

- **Spills no longer outlive the run on a `state` backend.** A longer-scoped
  `state` workspace was persisting `tool_output/` spills into its stored document
  every run, counting them against `SANDBOX_STATE_MAX_BYTES` until the agent's
  own writes were refused. The flush now strips the reserved prefix, so every run
  self-heals what a prior one left. The container-backend half stays open as
  #803. (#803)

### Changed

- **The ambient-usage delta is one helper, not two copies.** `compaction` and
  `tool_output_limits` each carried an identical snapshot-and-diff for booking a
  self-run `Agent`'s tokens; both now import `usage_counts`/`usage_delta` from
  `budget`, so a pricing fix lands in one place.

## [0.0.162] - 2026-08-16

An agent can drive a real browser, with the same guards as everything else.

### Added

- **The `browser_use` capability.** One tool, `browse_web`, that hands a
  self-contained natural-language goal to an autonomous
  [browser-use](https://github.com/browser-use/browser-use) agent driving a real
  Chromium — `mode='playwright'` launches a local headless browser,
  `mode='remote'` attaches over CDP to an operator-supplied `cdp_url`. A remote
  endpoint is SSRF-checked at publish time, off the event loop, for every binding
  — the first production caller of `validate_webhook_url` (part of #33). The
  browser sub-agent runs on the host run's model wrapped in a `MeteredModel`, so
  its spend is booked against the run's ledger (#802), and the tool is
  `side_effecting`, so every call can sit behind the approval gate. The engine is
  an optional dependency the capability builds without: until browser-use loosens
  its `pydantic` pin (#801), enabling and running it raises a `RuntimeError`
  naming the fix rather than failing quietly. (#59)

## [0.0.161] - 2026-08-16

An agent can draw an image, with the spend on the ledger like everything else.

### Added

- **The `image_generation` capability.** One tool, `generate_image`, that renders
  an image from a prompt with a dedicated image model (OpenAI Responses or
  Google), whatever model the agent itself runs on. The provider key is a
  `SecretRequirement`, so publishing without one is refused at the form; the tool
  is `side_effecting`, so every call can sit behind the approval gate; and the
  subagent's usage is booked to the run's ledger — an unpriced image model
  records zero and flags the run's cost partial rather than hiding it. Images
  land in organization-scoped storage (`generated/{org}`), served only under the
  caller's own organization at `GET /api/v1/generated/{filename}`, rendered
  inline in chat, and — when the run has a workspace open — also written under
  `/output` so a later `execute` step can build with them. (#58)

## [0.0.160] - 2026-08-16

Every person, organization and agent gets a designed default avatar, and a colour
to go with it.

### Added

- **Default avatars, and a colour you can pick.** A row with no uploaded picture
  now falls back to its initials on a colour rather than a blank circle — one
  shared `EntityAvatar` across every surface, keyed to the row's id so an entity
  keeps its colour everywhere it appears. The colour is also choosable: a nullable
  `avatar_color` slot (1..10, null = auto) on users, organizations and agents,
  with a swatch picker on the profile, organization and agent-builder screens. The
  image is drawn only when the row actually has one, which also closes a per-row
  404 several member and user lists were firing. Ten pastel hues live in a tuned
  `--avatar-*` token ramp, theme-independent so they read in light and dark alike.
  (#60)

### Fixed

- **The secrets "Added by" avatar now matches a person's colour everywhere else.**
  It seeded the fallback hue on the author's email rather than their id, so the
  same person could wear one colour there and another beside their name in member
  lists. `SecretRead` now carries `created_by_user_id` and the column seeds on it.
  (#799)

## [0.0.159] - 2026-08-16

A new organization starts with a spend ceiling already in place.

### Added

- **A new organization defaults to a $100 monthly budget.** An org with no cap is
  one runaway agent away from a surprise bill, and a budget only refuses if it
  exists — so a fresh org now starts at the deployment's
  `DEFAULT_ORG_MONTHLY_BUDGET_USD` (`$100` out of the box), editable on the org's
  row like any other cap and enforced by the same guard. The default is applied at
  creation across every path — team create, the personal org on signup, and
  `bootstrap` — and `None` restores the older opt-in posture for a deployment that
  would rather start uncapped. Existing organizations are untouched; no migration,
  because the column already existed. (#785)

## [0.0.158] - 2026-08-16

A long run compacts its own history before it hits the model's limit, metered,
and every agent shows how full its context window is.

### Added

- **Compaction capability.** Ports the `pydantic-ai-harness` compaction strategies
  into the registry: `summarize` (the default, at 0.9 of the window — the only
  strategy that keeps what older turns *said*), `tiered`, `clear_tool_results` and
  `sliding_window`. The trigger is a fraction of the window resolved **per request**
  against the model the request is going to, so the same history passes untouched on
  a 1M window and is cut on a 128K one before the request leaves. (#49)
- **A context-fill gauge on every agent**, not only one that compacts — the warning
  matters most to the agent that will not, because that is the one the provider
  refuses. Read from the provider's own `input_tokens`, stored per turn, and divided
  by the window of the model selected *now*. (#772, #774)
- **`model_profiles.context_length`** — the window a model accepts, recorded from the
  provider's listing at creation rather than guessed from the price snapshot. (#773)
- **`messages.cost_is_partial`** and a server-side conversation cost total; a partial
  figure is drawn `≥ $x`. (#772)

### Fixed

- **A summary is metered.** The strategy writes it through an agent it builds itself,
  which no budget guard wraps, so the capability books the run's usage across the
  hook against the ledger. Recorded, not prevented — the guard refuses on the next
  request. (#16)
- **A conversation's history is read from the transcript, not the socket.** A reload,
  a second tab or a dropped connection left the model answering a follow-up as though
  the thread had started with it. (#771)
- **A summary is kept across turns.** The thread between turns was rebuilt from the
  transcript, so a summary died at the turn boundary and the next turn bought another
  over a longer history; `conversations.summary_messages` now holds it. (#781)
- **A window too small for the agent's own overhead says so** rather than buying a
  summary that cannot get under the instructions and tool schemas on every request
  for ever. (#776)
- **The builder draws a capability's defaults as values** and can label what each
  enum choice does, so a generated form is not a row of empty boxes.

## [0.0.157] - 2026-08-16

An organization's standing knowledge is put into a run instead of made to be asked
for.

### Added

- **Context capability.** A first-class, org-scoped library of text objects — a
  glossary, a brand voice, an escalation matrix — each carrying a `mode`: `inject`
  splices the body into the agent's instructions verbatim, `link` leaves it out of
  the prompt and reads it on demand through `list_context`/`read_context`, so a
  large or rarely-needed file costs nothing until the model reaches for it. Mirrors
  the skills subsystem end to end — model, schemas, repo, the shared access/grant
  machinery, service, routes, spec binding, publish check, runner resolution, and
  the frontend library + builder picker. (#48)
- **`AgentSpec.context_ids`**, bumping `SPEC_VERSION` to **9**. Defaulted, so every
  stored spec and exported YAML loads unchanged.

### Notes

- **Injected content is untrusted input.** A file's body is user-written and reaches
  the model verbatim, so it is delimited (`<context-file>`) and framed as reference
  material rather than instructions. The fence resists accidental breakout — a body
  or name that forges a closing tag or an attribute quote can no longer escape it —
  though an operator with `context:edit` injecting deliberately is out of scope by
  design.
- **Tenant-scoped, checked at publish.** Binding a file hands its body to every run,
  so it is checked against the publisher's own access; a private file another member
  owns is refused indistinguishably from a missing id.

## [0.0.156] - 2026-08-16

An agent can bind many MCP servers without paying for every tool's schema on
every request.

### Added

- **Tool search capability.** Ports Pydantic AI's `ToolSearch` into the registry
  as `tool_search` and pairs it with deferring the connected MCP toolsets, so the
  model discovers the tool it needs instead of carrying every server's schema on
  each turn. Config is `strategy` (`auto` | `keywords` | `bm25` | `regex`) and
  `max_results` (1–50). The capability and the deferral are two halves of one
  decision — `ToolSearch` is inert with nothing deferred, and a deferred tool with
  no search to find it is unreachable — so binding it is what marks the servers'
  toolsets for deferred loading; the registry's own tools stay visible. An agent
  that does not bind it pays nothing. (#50)

### Notes

- **Deferral changes what the model sees, never a tool's identity.** A discovered
  MCP tool arrives under its real prefixed name, so the approval gate still pairs
  on it and a binding's rename still reaches it — `ToolSearch` sits outermost,
  reading the names a rename already applied.
- **No un-metered spend.** Local strategies run in Python; native search runs
  inside the provider's own metered request; the discovery round-trips are
  ordinary model requests the budget guard already wraps.

## [0.0.155] - 2026-08-16

An agent can keep a checklist for itself over a multi-step run.

### Added

- **Planning capability.** Ports the `pydantic-ai-harness` planning checklist into
  the registry: `write_plan`/`read_plan` plus granular step tools, and under
  `enable_subtasks` a dependency-aware mode (`add_subtask`, `set_dependency`,
  `get_available_tasks`, a `blocked` status). The current plan is surfaced back
  each turn as a cache-safe tail reminder behind a `CachePoint`, so the prompt
  prefix stays cacheable and the plan never lands in the system prompt. The tools
  are local checklist edits with no model request behind them, so there is no
  ambient usage to meter. Registry-only — no `SPEC_VERSION` bump — and orthogonal
  to delegation, so an agent may bind both. (#47)

### Fixed

- **A parked run's plan survives the approval park.** The runner owns the store:
  it seeds one from `PausedRunState.plan` on resume, injects it through
  `PLANNING_STORE_RESOURCE`, and reads it back when the run parks. `paused_state`
  is already JSONB, so no migration — a run parked before this stays resumable.
- **The system-prompt guidance is this repository's own string.** The library's
  `get_instructions()` guidance is pinned via `guidance=` alongside the tool
  descriptions, so a harness release that rewrites its default can no longer
  change the agent's system prompt silently. (#778)

## [0.0.154] - 2026-08-16

A tripped guardrail is a visible run outcome, not a crash — on every surface.

### Added

- **Guardrails capability.** A single `guardrails` capability ports the
  `pydantic-ai-harness` guards into the registry, inspecting the text at three
  edges — the user's prompt, the agent's answer, and a tool's result before the
  model reads it — and either redacting a match or blocking the run. Tool-result
  screening is the headline: it is the only guard on untrusted content entering
  the loop, where a prompt-injection payload would otherwise reach the model
  unread. Redactors cover API keys, tokens, JWTs and PEM blocks, plus email,
  IBAN (mod-97), card (Luhn) and US-SSN. Config is data, not callables — flat
  toggles and a keyword string per edge — so it crosses the wire as an agent
  spec. (#46)
- **`RunStatus.GUARDRAIL_BLOCKED`.** A block is a governance outcome, so it gets
  its own status beside `budget_exceeded` — the platform working, not a
  malfunction — visible and filterable in run history, folded into `other` in the
  outcomes donut, and kept out of the "Recent failures" widget and the "Problems"
  preset. `agent_runs.status` is an unconstrained string, so no migration.

### Fixed

- **A guardrail block on the streaming web chat is recorded as
  `guardrail_blocked`, not `failed`.** `GuardrailBlocked` was caught only in the
  non-streaming runner, so on the primary surface a block landed in the generic
  `except Exception` — recorded as `failed`, logged like a crash, and shown to
  the visitor as a generic "turn failed" instead of the guard's safe reason. The
  streaming path now mirrors the budget handling in `agent_chat.py` and
  `agent_session.py`. (#779)

## [0.0.153] - 2026-08-15

The i18n guard stops reading a leading acronym as permission to skip the
sentence behind it.

### Fixed

- **Prose whose first word is an acronym is reported again.**
  `NOT_A_SENTENCE`'s second alternative was `[A-Z]{2,}\s` — written to exempt a
  machine token, it exempted the whole string that token opened, so `API keys
  are stored in the vault` left the sweep while `Provider keys are stored in
  the vault` did not. A hole the width of a vocabulary, in a product whose copy
  opens on `MCP`, `API`, `RAG`, `KB` and `JWT`. Anchoring the alternative on a
  single lower-case word keeps the label it was written for — `MCP server`,
  `AI agents` — and lets the prose through. This is the same mistake as #656,
  one alternative to the left; both are anchored now, and `.claude/rules/frontend.md`
  names both rather than only the first. (#678)
- **A separator label may lead with an acronym.** Anchoring took away cover the
  acronym branch had been giving by accident: the separator alternative accepts
  only a title-case token on the left, so `URL / Endpoint` was exempt through
  the acronym branch and would have started reporting as copy while
  `Model / Provider` did not. Its left token now reads
  `(?:[A-Z][a-z]+|[A-Z]{2,})`. Nothing in `src/` is written that way, so the
  sweep was clean either way and this was found by review rather than by the
  guard.

## [0.0.152] - 2026-08-15

The dashboard is arrangeable, and it finally has a visual system to be
arranged into.

### Added

- **A person arranges their own dashboard.** Cards reorder, resize, hide,
  take a colour and group under named section dividers; more come from a
  gated catalog; the result persists per user per organization, either as a
  single active arrangement or as any number of named presets to switch
  between. The arrangement is a third layer over the two the page already
  had (`effective = preference ?? audience default`) and the permission gate
  still runs **last**, so a preference can reorder or hide a widget but never
  reveal one the caller may not see. Two tables with their repositories —
  `dashboard_layouts` and `dashboard_presets`, placements as JSONB — and
  `/api/v1/me/dashboard-layout` with a `/presets` shelf beneath it; applying
  a preset is a `PUT` of its entries, so there is one write path. (#213)
- **The write contract is deliberately asymmetric.** A write validates every
  placement against the widget registry and the closed span/row sets, so a
  typo is a 422 at the boundary; a read hands back what was stored, so a
  retired widget id drops at render time rather than 500ing the page.
- **A spacing system, in `lib/dashboard/system.ts`.** Band-to-band was 24px
  against card-to-card's 16px — three levels of structure inside eight
  pixels of each other, which is why five bands read as one mass. Bands sit
  at 40px, four times the card gap. Its test asserts the *relationships*,
  since a constant equal to its own literal tests nothing.
- **Four cards the page could not answer before.** Channels — what is
  registered and whether each bot webhooks or polls, which is the difference
  between "silent because nobody asked" and "silent because nothing is
  listening". Knowledge — whether documents that arrived ever finished
  indexing, since a collection can be perfectly fresh and hold two hundred
  documents nothing can retrieve. A week by the hour on a new
  `group_by=hour`. And sparklines on three KPI tiles, free from `runs_by_day`
  answering runs, completed and cost from the one scan it already made.
- **The page opens on numbers.** A steward's dashboard led with "Needs
  attention" — five "nothing here" boxes before the first figure in an
  organization where nothing is wrong. A full-width `summary` strip leads the
  steward, operator and builder layouts and costs no request: every figure
  slices the composed `/stats/usage` response the cards below already share,
  and the completed share reads `run-outcomes`, so it and the Outcomes donut
  cannot disagree.

### Changed

- **One figure component.** There were three — `StatCard` on Admin, `Metric`
  on the dashboard, a private `Figure` inside `ActivityFigures` — so the same
  number changed typeface between a card and the page its "see all" points
  at. `components/ui/figure.tsx` is the one, and the value is sans, semibold,
  with the font's own figures: `tabular-nums` and a mono face on a large
  standalone number are both named anti-patterns, so equal-width digits stay
  in table rows and axis ticks where columns align.
- **Chart ink measured, not argued.** `--color-chart` is `brand-500` in both
  themes at 3.74:1 light and 5.07:1 dark, clear of the 3:1 floor a mark owes
  its surface; a new `--color-track` draws a bar's unfilled part in the
  fill's own hue. `brand-900` was tried in dark and is why the pair is
  measured rather than picked: at 1.41:1 it read as a filled bar, so a
  provider that spent nothing showed a full-width mark beside $0.00. Dashed
  gridlines are gone, the area wash is flat at 10% instead of a gradient
  inventing a second encoding down the y-axis, and a truncated model id has a
  real hover instead of a native `title`.
- **A widget is the object every other page draws.** `WidgetFrame` is built
  on `Card` — same corner, same elevation, the divider under the heading that
  `ListCard` carries — and each card explains itself once, through an info
  icon holding the same sentence the add-widget catalog lists it under.
  Thirteen widgets had rolled their own figure; five carried their
  explanation as grey prose under the data.
- **A row holds cards of comparable natural height.** That rule is what the
  layouts are rebuilt on, and what had left a four-line list beside a chart
  two-thirds empty. The heatmap takes a row to itself: anything beside
  seven-by-twenty-four is either dwarfed or stretched.
- **A period change dims rather than blanks.** It was a new query key, so ten
  cards dropped to skeletons at once and the page emptied and reflowed.
  `keepPreviousData` holds the last answer while `UsageBody` dims it and sets
  `aria-busy`.

### Fixed

- **The Spend card put two definitions of cost side by side.** The headline
  read `cost.period_usd` — model spend alone — while the line under it read
  `/spend → month_to_date_usd`, runs *plus* ingestion, which is the
  arithmetic a monthly cap is measured with. Nothing said they were different
  questions, and on any deployment that indexes documents they disagreed,
  with `ingestion_spend` real money against the cap and nowhere on the page.
  `CostBlock.period_usd` is the whole bill now, with `model_usd` and
  `ingestion_usd` beside it and `previous_period_usd` following so the change
  compares like with like. At `scope=own` the ingestion half is zero rather
  than a share — a worker indexes a document and the ledger records no user.
- **The sections filter vanished the moment somebody saved an arrangement**,
  including one that kept every heading it started with: the filter offered a
  section only if it carried a `titleKey`, and flattening the default turns
  each heading into a divider named by `title`. `isFilterable` reads either
  name, and `sectionLabel` is the single copy of "the caption a person typed,
  else the curated key".
- **Bar-list labels no longer end in an ellipsis** — every row in two cards
  did — and each info icon is named for its card rather than being one of
  twenty-seven identical stops.

## [0.0.151] - 2026-08-15

Every list in the product is now one table and one card, and Activity is a
page you can actually narrow, page and export.

### Added

- **One table primitive, one list shell.** `DataTable` gained sorting and
  filtering in two modes — client-side over rows a caller holds whole, and
  server-side as a request — so a sort header means the same thing everywhere.
  Which mode a table uses follows where its rows live: a client-side sort of
  page one, on a list with three pages, is worse than no header at all.
  `ListCard`/`ListCardEmpty` replaced five per-page card copies and four inline
  empty states, and `components/ui/table.tsx` went with its last caller. Sort
  state survives a reload through `?sort_by=`/`?sort_dir=`, validated against
  the same whitelist the backend route declares. (#139, #282)
- **Activity became an observability page.** One period window feeding the
  figures, the table, the version strip, the Spend tab and all three exports;
  every filter the backend answers (status, surface, a three-state rating,
  agent, person and — narrowed to an agent — version); pagination with
  "51–100 of 1,204"; surface brand marks; a run's chat one click away; and the
  run detail in a drawer whose prev/next walk the run's own conversation.
  (#760, #761, #762, #764, #765, #766)
- **Every organization starts with the shipped skill library.** Creation copies
  each bundled skill in as an ordinary org-visible row, and the listing
  materializes any the catalog grew since — so the install step, its endpoints
  and its gallery are gone. (#281)

### Changed

- **Admin standardised onto both primitives**, one pagination control instead
  of three dialects, organizations on their own tab, and `/admin/ratings`
  deleted whole — ratings are read where the runs are. (#283, #284)
- **The agent map reads in four directions** — surfaces left, model and budget
  above, tools right, delegation below, each subagent a first-class node beside
  a policy box naming `allow_dynamic`. (#518)

### Fixed

- **A CSV exported beside a narrowed table contained everything.** The export
  passed only `agent_id`, while both docstrings promised the file was what was
  on screen. (#763)
- **Deciding the last outstanding approval now resumes the run.** The queue
  posted the decision alone, which left runs approved, undisputed and parked
  forever.
- **Runs still going no longer sort as the cheapest or the lightest.** Cost and
  tokens are written at finish and default to zero, so an ascending sort ranked
  a running row above every finished one; all four orders now put an unfinished
  run last, as duration always did.
- **The run detail's arrows no longer step into delegations** the list itself
  hides — a fan-out's children sat between a run and the thread's next turn.
- **Six lists stopped reporting a failed request as an empty collection** —
  vault, MCP, skills, channels, members and the admin users table each drew
  "nothing here yet" over a refusal, and MCP drew it over a catalog compiled
  into the backend. (#32's shape)
- **Seeding a bundled skill twice costs that row, not the reader's page**, and
  audit entries written by a seeding path now say so rather than asserting the
  organization's owner made a write they never made.

## [0.0.150] - 2026-08-13

The streaming socket was the last surface still writing blank user turns.

### Fixed

- **A blank streaming turn's user message names its files.** 0.0.148 fixed the
  blank-turn class for every surface that reaches the transcript's `record` —
  channels, the embed widget, the HTTP API — but the dashboard's streaming
  socket writes its own user turn and stored the message verbatim, blank
  included; only the composer's client-side substitution hid it, so any raw
  WebSocket client sending `{"message": "", "file_ids": [...]}` stored an
  empty bubble. Both write sites now compose the same one-line-per-file body,
  loaded through the owner-scoped file read from 0.0.149. A typed message is
  never replaced. (#750)

## [0.0.149] - 2026-08-13

A chat turn could attach another user's file by naming its id.

### Security

- **Linking a file the caller does not own is refused.** The link was a blind
  bulk UPDATE with no owner predicate and no unlinked check, and the ids came
  straight off the socket payload — so a turn naming another user's file id
  rendered their filename, MIME and size in the attacker's conversation and
  silently pulled the file off the victim's own message. Both the read and
  the UPDATE now carry the owner in their WHERE; a foreign or unknown id
  answers the same `NotFoundError` (so an id cannot be probed for existence),
  an already-linked one is refused rather than moved — for everybody, its
  owner included — and a malformed id is refused at the boundary instead of
  resurfacing as a failed turn after the message persisted. (#706)

## [0.0.148] - 2026-08-13

A photo sent with no caption read as somebody sending nothing.

### Fixed

- **A caption-less turn's user message names its files.** A channel turn whose
  attachment produced no prompt text wrote a blank user message, so the thread
  in `/chat` jumped straight to the answer with the file card as the only
  trace of the question. The transcript now composes the empty turn's body
  from its attachments — `Attached image: photo.jpg`, one line per file —
  reusing the vocabulary the model's briefing already uses. A caption is never
  replaced, and a resume still writes no user turn at all. (#704)

## [0.0.147] - 2026-08-13

A failed tool's raw error was stored where every reader of the run can see it.

### Security

- **A tool's retry text stays out of the transcript row.** #681 sanitized the
  chat `tool_result` frame; the stored row was the same leak on the run paths
  that never open a socket — the HTTP API and the channel bots. A retry's
  content is written by whichever tool raised (`web_search` builds one from
  the vendor exception, endpoint and query string included; an MCP tool's is
  a third party's entirely), and it landed on a tool-call row rendered in run
  history weeks later. The row now stores the same sentence the frame sends —
  which tool failed and that the model was asked to retry — and the vendor's
  own text goes to the server log beside the write, nowhere else. (#695)

## [0.0.146] - 2026-08-13

A thread nobody owned was everybody's to delete.

### Security

- **An unowned room thread is writable only by its participants.** A channel
  thread's owner is its first *linked* speaker, so a room where nobody linked
  an account had no owner — and the write check answered yes to any member of
  the organization: renaming it, archiving it, deleting the transcript, or
  appending a `role: "assistant"` turn the model reads back as its own words,
  including for threads their own list never showed them. The write now stops
  at the same membership-confirmed participation the read admits; an owned
  thread still refuses its participants the write. (#701)

## [0.0.145] - 2026-08-13

A webhook bot's files had no server to be fetched from.

### Fixed

- **A Mattermost webhook bot's server is recorded per delivery.** Only the
  polling path ever told the adapter a bot's address, so an attachment on an
  outgoing-webhook post parsed with an empty handle and the reply said the
  file could not be downloaded. The receiver now hands the bot row's
  `api_base_url` to the adapter after the token check and before the parse —
  per delivery, so an operator's edit takes effect at once. Not a regression:
  before #547 the file was dropped silently; #547 made the failure visible,
  this makes the file reachable. (#692)

## [0.0.144] - 2026-08-13

A removed channel member kept the thread.

### Security

- **`/chat` now asks the platform whether a reader is still in the channel.**
  A channel thread was shown to anybody whose linked account had ever spoken
  in it, and never asked again — so somebody removed from a Slack, Telegram or
  Mattermost channel kept the thread, including everything said after they
  left. Each adapter now answers a per-account membership question, cached for
  60 seconds and failing closed: an unsupported platform, a missing adapter,
  an unsealable token or an errored call hides the thread rather than showing
  it. The owner and an explicit share keep access on every path. (#641)

## [0.0.143] - 2026-08-13

Three sweeps walked the source tree three different ways.

### Changed

- **One source-tree walker, shared.** `fonts.test.ts`, `loading-state.test.tsx`
  and `platform-proxy.test.ts` each carried their own recursive read of
  `frontend/src`, with their own idea of what to skip — so a directory one of them
  learned to ignore stayed invisible only to that one. They now share
  `src/test-utils/source-files.ts`. (#618)

## [0.0.142] - 2026-08-13

Every page declared itself English, Polish ones included.

### Fixed

- **`<html lang="en">` was hard-coded** from `defaultLocale` in the one layout that
  renders `<html>`, so a screen reader on `/pl/agents` announced Polish copy with
  English pronunciation rules and a crawler read the page as English. It now comes
  from the active locale. More visible since #604, because before that the UI
  mostly reverted to English anyway. (#619)

## [0.0.141] - 2026-08-13

The baked MCP logos were keyed on a domain nothing ever asked for.

### Fixed

- **Every logo in `mcp-logos.generated.ts` was keyed on a brand domain** —
  `linear.app`, `notion.so` — while `logoDataUri` is always asked with the
  connection URL's host, `mcp.linear.app`. The intersection was empty, so the MCP
  badge fell through to Google's live favicon service on every view and the
  self-contained export phoned home per server instead of rendering offline.
  (#614)

## [0.0.140] - 2026-08-13

Polish diacritics swapped typeface mid-word.

### Fixed

- **The vendored woff2 files were the latin subsets**, and eight of the nine
  Polish pairs — `ą ć ę ł ń ś ź ż` — live in latin-ext, so per-glyph fallback
  rendered them in the system font. Worst on Bricolage Grotesque headings at
  700–800, where a word could change typeface halfway through. The latin-ext
  subset of all three families is vendored beside the latin one, at the same
  Google Fonts versions, about 119 KB together. (#606)

## [0.0.139] - 2026-08-13

`timeAgo` fell back to an English date once a timestamp was old enough.

### Fixed

- **The date `timeAgo` answers with past its relative window** was built with a
  hardcoded locale, so a Polish reader watching a list of runs saw Polish for
  anything recent and English the moment a row aged out of "2 days ago". It takes
  the active locale now, like the absolute formatters beside it. (#621)

## [0.0.138] - 2026-08-13

An absolute date was formatted in English on every locale.

### Fixed

- **`formatDate` and `formatDateTime` passed a hardcoded `"en-US"`** to
  `toLocaleDateString` / `toLocaleString`, so the month name and the day-month
  order came from English everywhere — a Polish reader saw `Jul 31, 2026` where
  the runtime would have given `31 lip 2026`. None of it is copy a translator can
  reach, because the strings come from `Intl` rather than the catalog, so no
  amount of `pl.json` would have fixed it. (#621)

## [0.0.137] - 2026-08-13

An MCP consent that was refused landed on the servers page looking exactly like
one that was accepted.

### Fixed

- **Nothing read the outcome the OAuth callback redirected with.** The provider
  sends the browser to a route that has no way to answer the person — a JSON body
  on a page nobody navigated to is a dead end — so every outcome ends as a redirect
  carrying its result in the query. That contract was written in the route handler
  and consumed by no page. The MCP servers page now announces it, and the redirect
  lands there rather than on `/settings/integrations`, which is itself a redirect.
  (#657)
- **A refusal of ours and a refusal from somewhere else travel separately.** The
  callback takes no session by design — the `state` token authenticates the
  exchange — so anybody can put a browser on that address with a refusal of their
  choosing, and that query is now rendered. Ours goes under `mcp_oauth_failure` and
  is looked up in a fixed table, so a stranger cannot spell one and have the
  product say it in its own voice; anything else is stripped of control
  characters, capped at 200 characters and shown quoted after a sentence this
  repository wrote. (#657)

## [0.0.136] - 2026-08-13

DOM key constants were sitting in the message catalog and read back through the
translator.

### Fixed

- **`e.key === t("enter2")` compared a keyboard event against a translation.**
  `Enter`, `Escape`, `Tab`, `ArrowUp` and `ArrowDown` were parked in `en.json` and
  read back in the chat composer, the command palette, conversation rename, the
  share dialog, the sources panel and the question prompt. `src/i18n.ts` merges
  `en.json` under every locale, so this worked only while `pl.json` omitted those
  keys — the first translator to render one would have broken every shortcut on
  that screen. They are literals in the source again, and
  `messages/catalog.test.ts` refuses a catalog value that is a DOM key constant.
  Six of them had in the meantime been translated into `pl.json`, which is the
  failure arriving; they are deleted. (#549)

## [0.0.135] - 2026-08-13

The copy guard read a hyphen in the first word as a label separator, so half a
sentence passed the sweep.

### Fixed

- **`"Sign-in failed"` passed the i18n guard while `"Not authenticated"` was
  refused.** `NOT_A_SENTENCE` exempts a label built from title case around a
  separator — `Model / Provider` — and the whitespace on both sides of that
  separator was optional, so a hyphen *inside* the first word made the whole
  sentence a label. The separator now needs the whitespace that makes it one.
  (#656)

## [0.0.134] - 2026-08-13

A refusal from the BFF reached the toast in English, whatever locale the reader
was in.

### Fixed

- **The route handlers under `src/app/api/**` write a wire payload, not copy**, and
  the toast that renders it was showing that payload verbatim. A refusal now
  travels as a code the client resolves in the active locale, and
  `getErrorMessage` takes the caller's translator — it moved from `@/lib/utils` to
  `@/lib/api-error` in the process, because a function that needs a translator is
  not a utility. Step details take the same route. (#603)
- **The copy guard reads a `.ts` file by the same rules as a `.tsx` one**, so a
  hook's toast and a module table of labels are copy too. `src/app/api/**` is
  skipped by the offence sweep — a route handler sits outside the `[locale]`
  segment and has no translator to reach — and read by the catalog rules, which is
  what reports a `detail` that duplicates a message. (#603)

## [0.0.133] - 2026-08-13

The banner guard walked every worktree on the machine before deciding to ignore
them.

### Fixed

- **`scripts/check_comments.py` filtered after walking rather than pruning.**
  `Path.rglob("*")` descended into `.git`, `.venv`, `node_modules` and every
  checkout under `.claude/worktrees/`, and `SKIP_DIRS` only decided what was
  *reported*. On a machine with 68 worktrees that was about 3.9M paths and roughly
  seven minutes per commit, because pre-commit runs the hook with
  `pass_filenames: false`. It is now `os.walk` with in-place pruning. (#635)

## [0.0.132] - 2026-08-13

The spend page said nothing could not be priced, above three breakdowns that had
priced nothing.

### Fixed

- **`GET /runs/spend` counted its "could not be priced" caveat over *top-level*
  rows only.** By provider and By key price every row in the window through a
  subquery that is deliberately not windowed, so a parent that started before the
  window and delegated inside it put its delegate's spend into the breakdowns while
  the caveat above them read `0` — a page saying the numbers are complete when they
  are not. The caveat now counts what the breakdowns count. (#620)

## [0.0.131] - 2026-08-13

Two RAG document lookups disagreed about which document they were looking at, and
heap order decided.

### Fixed

- **`IngestionService.find_existing` and `get_existing_hash` used different
  precedence.** The first checked every document for a `source_path` match before
  falling back to `filename`; the second interleaved the two in one pass, where a
  filename hit blocked any later source-path match — so a re-sync could answer with
  a different document depending on which helper asked. (#548)
- **`PgVectorStore.get_documents` selected with no `ORDER BY`**, so heap order
  decided which document a lookup answered with, and re-running the same query
  could give a different one. (#548)

## [0.0.130] - 2026-08-13

A scanned PDF ingested with OCR enabled indexed near-empty, silently.

### Fixed

- **The OCR fallback drove the image describer through
  `asyncio.new_event_loop().run_until_complete(...)`** from inside a running loop,
  which produced nothing — and the result was indistinguishable from a PDF that
  genuinely had no text. `PyMuPDFParser._ocr_page` and `_parse_pdf_file` are now
  `async` and await the describer on the caller's loop. (#550)

## [0.0.129] - 2026-08-13

An MCP OAuth failure put the token endpoint, and whatever its query string held,
into a toast in the browser.

### Fixed

- **Three refusals in the MCP OAuth flow interpolated whatever raised.** `httpx`
  puts the failing request in its message, and the two requests this flow makes
  are a client registration and a token grant — so a broken provider reached the
  member's screen as the endpoint it failed on, rendered as a toast since #657 via
  `McpOAuthCallbackResult(ok=False, error=str(exc))`. Each refusal now names the
  stage it failed at and what the reader can do about it; the client's own text
  stays in the `logger.exception` beside the raise. (#686)

## [0.0.128] - 2026-08-13

A test that proved `spawn_after_commit` was needed proved it on a 250ms
stopwatch.

### Fixed

- **`test_spawning_inside_the_request_starts_before_the_row_exists` waited a fixed
  `_GRACE = 0.25s`** for the spawned flow to take its reading, and asserted the
  reading happened inside that window. Under `make test` — four xdist workers plus
  coverage instrumentation on one machine — 250ms guarantees nothing, so the test
  failed once and passed on a clean re-run and in CI. It now waits on a signal from
  the task itself, which is what it was trying to time. (#680)

### Changed

- **A release that only bumps the version no longer runs `test`, `test-frontend`
  and `e2e`.** `scripts/ci_changed_scope.py` reads the diff of
  `backend/pyproject.toml`, `backend/uv.lock` and `frontend/package.json` rather
  than their paths, because those files also hold the dependency lists, the
  coverage `include` lists and the ruff and ty configuration. An absent patch, a
  diff of context lines, or one line that is not a version assignment still runs
  everything. #317 claimed this; it is now true. (#317)

## [0.0.127] - 2026-08-13

An invitation nobody clicked stayed pending for ever, and one clicked too late
was recorded as withdrawn.

### Added

- **An hourly `invitation-expiry-sweep`**, the same shape as the approval sweep.
  `InvitationStatus.EXPIRED` was unreachable — `invitation_repo.expire_stale` had
  no caller — so the pending list kept offering invitations that had timed out.
  Registered hourly rather than more often, because the TTL is measured in days.
  (#456)

### Fixed

- **Accepting a stale invitation marked it `revoked`**, which records a withdrawal
  somebody made when what actually happened is that it ran out. (#456)

## [0.0.126] - 2026-08-13

A shareable invite link could grant ownership, or a role that does not exist.

### Fixed

- **`InviteLinkCreate.role` carried no validator** while its sibling
  `InvitationCreate` refused `owner` and unknown roles. An Owner could mint a link
  that grants owner — co-ownership through a pasted URL, the exact thing the email
  invitation path forbids — or an invented role string that `role_has` cannot
  reason about, which then flowed unvalidated onto the accepter's membership row.
  Both schemas now share one `InvitableRole`: every role in the catalog except
  `owner`, refused at validation. (#551)

## [0.0.125] - 2026-08-13

A plain role change could mint a second owner and walk around ownership transfer.

### Fixed

- **`PATCH /orgs/{org_id}/members/{user_id}` accepted `{"role": "owner"}`** against
  any non-owner member. It succeeded, left the organization with two owners, and
  wrote an audit entry reading `member.role_changed` rather than saying ownership
  had moved — so `transfer_ownership`, the one path that demotes the outgoing owner
  in the same breath, could be walked around with a PATCH. Both halves are closed,
  because either alone leaves the hole open somewhere: `OrganizationMemberUpdate`
  subtracts `owner` from the roles it admits, the way `InvitationCreate` already
  did, and the service now caps the role being *assigned* rather than only
  inspecting the target. (#672)

## [0.0.124] - 2026-08-13

A Mattermost bot reached through an outgoing webhook answered every post in a
channel it was merely invited to.

### Fixed

- **The outgoing-webhook path left `addressed` unset**, and the router reads unset
  as "the platform did not say" and answers. So the transport put the bot back in
  the position the event stream's rule took it out of: replying to colleagues
  talking to each other. The body carries no mention list — Mattermost sends the
  post, not who it notified — so what is read instead is `trigger_word`, the
  platform's own record that the post was for this integration. Empty means the
  webhook fired on its channel filter alone, which delivers every post exactly as
  the socket does, so it is `False` for the same reason a `posted` event with no
  mentions is. Worth knowing before choosing this transport: `@the-bot` is not
  readable here, because nothing in the body says which account the bot is — set
  the trigger word to the bot's handle if that is how people should reach it. An
  `@agent-slug` needs nothing, since the router reads a slug out of the text.
  (#662)

## [0.0.123] - 2026-08-13

The embed session — one visitor's turn on a public URL — was the last surface
outside the coverage and type gates.

### Changed

- **`app/services/embed_session.py` is held to 100% coverage and to `ty`.** It
  decides who a visitor's turn runs as, how often they may ask, and what the page
  is allowed to put in front of the model — every one of which is a refusal a
  stranger can reach — and an unreachable `except BudgetExceeded` sat in it for as
  long as it was ungated, which is the kind of thing the gate exists to name. The
  module was at 93%: the missing 13 lines and 8 partial branches were the frame
  guards in `handle` (a frame that is not a message, an empty one, one past the
  character cap, a visitor past their rate limit), the two endings that produce no
  words, and `_files`. All are covered. (#663)

## [0.0.122] - 2026-08-13

A platform's second way in built its own idea of what a message is, and the two
disagreed about files.

### Fixed

- **Each adapter now has exactly one parser.** Every platform has two ways in — a
  webhook and a stream, or long-polling — and the second one built its own
  normalised message: Telegram's polling loop read text and nothing else, and the
  Mattermost outgoing webhook read no `file_ids` at all. So somebody dropping a
  spreadsheet on a bot had it silently discarded, depending only on which
  transport that deployment happened to run — and long-polling is what a
  self-hosted install uses. Both now put the update back into the shape the
  platform sends and hand it to the same `parse_incoming`, so what counts as a
  message is decided once. What each transport is *handed* still differs, and that
  is the platform's doing: Telegram's polling loop subscribes to new messages
  only, so an edit reaches the webhook receiver and never the poller. (#672)

## [0.0.121] - 2026-08-13

A message's attachments were downloaded and stored twice, and the run was handed
the second copy.

### Fixed

- **Each path fetched the files for itself.** A mention that names nobody of ours
  falls through to the default assistant, and both halves called `_receive_files`
  — so an ordinary message with a spreadsheet on it was downloaded from the
  platform twice, stored twice, and run with the second set. The first row stayed
  against the sender with nothing pointing at it, which on `chat_files` means
  scoped by `user_id` alone and collected by nothing. The fetch now happens once,
  above both paths, and is passed down. (#683)

## [0.0.120] - 2026-08-13

Reloading a conversation whose run is parked on an approval showed nothing to
say so, at either end.

### Added

- **`GET /runs/{run_id}/parked`** answers a run's pending calls — the approval row
  to decide, the tool call id, the tool and its arguments — the same payload the
  live `tool_approval_required` frame carries. Gated on `approvals:decide`. (#601)

### Fixed

- **The step a run parked on rendered as though it had run.** The transcript now
  stores those calls with `status="awaiting_approval"` rather than `running`, taken
  off the runner's paused state for every non-streaming surface and off
  `turn.parked` in web chat. The row does not read "waiting" for ever: a resume
  settles it with what the call returned, an expiry with the timeout notice, and
  both paths already existed. (#601)
- **The approval panel never came back after a reload**, so the only way to finish
  a parked run was the approvals queue on another page. This had always been true
  of every non-streaming surface; #509 removed the stored notice that had been
  covering for both halves, which is what made it visible. (#601)

## [0.0.119] - 2026-08-13

A channel turn refused before it ran left the files it had already stored behind,
owned by nothing.

### Fixed

- **The bytes are stored before the agent is resolved, so whatever refuses in its
  place has to give them back.** A turn that never produced a run left `chat_files`
  rows nothing points at — and that table carries no organization, so an unlinked
  row is scoped by `user_id` alone and no sweep collects it. Both refusal paths now
  discard what the turn stored: the one that stores first and refuses second, and
  the one where a handle names no agent of ours. A file that cannot be deleted
  costs neither the other files nor the reply, because a cleanup that raised would
  replace a refusal somebody can act on with a bot that answered nothing at all.
  (#661, #690)

## [0.0.118] - 2026-08-13

A crashed turn told the chat panel whatever the provider's SDK had put in its
exception.

### Fixed

- **The `error` frame carried `str(exc)` of whatever came out of the run.** A
  provider SDK puts the failing request in its message, so that routinely meant an
  endpoint, an internal host, or a URL with a key still in its query string —
  reaching a member's chat panel and their browser console rather than an HTTP
  body, which is where #342 fixed the same leak. The exception's text now stays in
  the `logger.exception` beside the send, and the frame names only what the reader
  can act on. The class still goes out, because it separates an upstream that
  timed out from one that refused a credential and a class name has never carried
  a URL. Our own refusals do not come through here at all — an `AppException` and
  a `BudgetExceeded` are caught above and passed through whole, since their
  messages are written in this repository. (#659)

## [0.0.117] - 2026-08-13

A failed run stored the provider's own error text in a column that run history
renders for weeks.

### Fixed

- **`agent_runs.error` held `str(exc)` of whatever came out of the run.** It is a
  stored column on `AgentRunRead`, rendered in run history to every member who can
  read it, and what raises there is a model client with `httpx` underneath — so
  that routinely meant an endpoint, an internal host, or a URL with a key still in
  its query string, sitting in a row somebody opens weeks later. The same rule as
  #342 in an HTTP body, #423 in the ingestion columns and #659 in the chat frame,
  with the longest life of the four. Our own refusals are kept whole, because an
  `AppException` raised inside the run is written in this repository and its
  message is the most useful thing an operator can be shown. Anything else stores
  its type, plus the status code when a provider answered one — 401 a credential,
  404 a model the profile names and the provider does not have, 429 a rate limit —
  where a bare class name would make all four `ModelHTTPError`. A group is
  unwrapped to its first leaf first, so an MCP toolset or a delegated run does not
  spend that status code on an `ExceptionGroup` that diagnoses nothing. (#676)

## [0.0.116] - 2026-08-13

A failing tool named a search provider's endpoint, with the key still in the
query string, to everyone watching the run.

### Fixed

- **A `tool_result` frame carried whatever the tool that raised had put in its
  `ModelRetry`.** `web_search` builds one out of the `httpx` or SDK exception it
  caught, so a broken key put `401 Unauthorized for url
  'https://api.tavily.com/search?…'` — an endpoint, a host and whatever the query
  string held — into the chat panel and the browser console of everyone watching.
  An MCP tool's retry is a third party's string entirely, which is why the frame
  is trimmed where it is sent rather than at each raise. The frame still names the
  tool, because a card that resolves saying which step failed is the difference
  from one that spins for ever, and the tool's own text goes to the log beside the
  send. The model reads the retry whole either way — Pydantic AI puts the part
  into the next request itself. Applied in `run_stream.py`, so the widget, a
  hosted page and a channel are covered by the same sentence web chat is. (#681)

## [0.0.115] - 2026-08-13

A file link that fails no longer takes the transcript of a paid run with it.

### Fixed

- **The write linking a channel turn's files to its message shared the
  transcript's SAVEPOINT**, so an exception from it rolled back the user turn,
  the settled tool calls and the assistant message — for a run that had already
  spent money, over a file. It now has a savepoint of its own inside that one:
  it is the only write there touching rows the conversation does not own, and a
  failure costs the link alone. Web chat has always made this trade for the same
  write, in `persist_user_turn`. The savepoint is skipped outright when nothing
  was attached, because opening and releasing one on every turn in the deployment
  is a real cost for a list that is almost always empty. (#690)

## [0.0.114] - 2026-08-13

The security page described an authorization model that was deleted three
months ago.

### Fixed

- **`SECURITY.md` documented `RoleChecker` and `UserRole.USER` / `UserRole.ADMIN`
  as the authorization model.** The `users.role` column went in migration `0066`;
  authority inside an organization is a membership row plus the permission
  catalog, and has been since. A security page is read by somebody deciding
  whether to trust a deployment, so being three months stale there costs more
  than elsewhere. It now describes the three layers and points at
  `docs/permissions.md`.
- **The hardening checklist named no rate limits at all**, which left an operator
  no way to know the public surfaces have them. It now lists the per-surface
  limits — the embed widget's per-visitor cap and each channel bot's
  `rate_limit_rpm` — and says plainly that the console's own routes are not
  metered.
- **The audit-log entry named a table that does not exist.**
  `app_admin_audit_log` is `app_admin_audit_logs`, and organization-level actions
  carry a trail of their own gated by `audit:read`, which the page did not
  mention. (`docs/governance.md`)

## [0.0.113] - 2026-08-13

Every surface — web chat, the embed widget, a channel bot, and the hosted page
this adds — now runs the same turn loop, remembers its conversation and is rate
limited. The three W2 surface issues were one thread of work, and doing them
apart is how the surfaces drifted in the first place.

### Added

- **A hosted chat page.** `/e/{publicKey}` serves an agent as a page rather than
  a snippet somebody has to embed: `hosted_config` holds the copy, the accent and
  the logo, a visitor keeps their thread across reloads, and a published page can
  be edited afterwards. Migrations `0022`, `0023` and `0025`. (#517)
- **The embed WebSocket is offered as an integration, not only documented.**
  `socket_url_for` sits beside `snippet_for` and rides the same read schema, so
  the panel publishes both with the `Origin` rule beside them. It carries no
  `?token=` — in `jwt` mode a token is minted per visitor, and one printed in a
  panel is a working credential on a shared screen. (#516)
- **A run records which channel identity asked for it.**
  `agent_runs.channel_identity_id`, migration `0024`. (#639)

### Fixed

- **A thread past 200 messages sent the model its *first* 200.** The window read
  from the start of the conversation rather than the end, so the longer a thread
  ran the staler the context it was answered from. `count_messages` plus `skip`
  makes the window the last 200. (#636, #638)
- **A group channel refused every sender who had never linked an account.** A room
  now admits an unlinked speaker and the turn runs as the binding's creator; a DM
  is unchanged, and `require_link: true` is the opt-out. (#639)
- **An update sending `null` answered 500 on a `NOT NULL` column.**
  `app/db/updates.py` lets the column decide instead of a hand-kept list, applied
  to every `*Update` and guarded over `app/services/**` and `app/api/**`. (#637)
- **The cookie banner covered Send on a hosted page.** Not rendered on `/e/**` or
  `/shared/**` — neither has an optional cookie to consent to. (#644)
- **The widget was the only surface passing no `message_history`**, so it forgot
  the conversation between turns. It now streams the frames the web chat does,
  and `EmbedSession` takes a session factory and opens one per turn, so an idle
  socket holds no pooled connection. (#39)

### Changed

- **One copy of "an anonymous surface runs as its publisher".**
  `access.publisher_context` is read by the embed session and by channels; there
  were two implementations that had already begun to disagree. (#640)
- **A channel thread has participants.** `/chat` shows a room's thread to
  everybody whose linked account has spoken in it, as a `DISTINCT` over
  `messages.channel_identity_id`. Reading and writing became two questions in the
  process: speaking in a room is a claim on being shown the thread, never on
  deleting or renaming it. Migrations `0026` and `0027`. That record says who
  spoke and is never re-checked against the platform, so somebody removed from a
  channel keeps reading the thread here — deliberately not closed, and #641 says
  why.

## [0.0.112] - 2026-08-12

The copy guard reads the frontend with a TypeScript parser instead of five
regexes, and the 137 English strings it can now see are in the catalog.

### Changed

- **The i18n guard parses instead of grepping, and the copy it found is in the
  catalog.** `scripts/check_i18n.py` had been patched for a new shape four times
  (#199, #246, #249, #314) and each fix was correct: the pattern was the problem.
  Reading a `.tsx` file as text means deciding per candidate whether you are looking
  at TypeScript or JSX, so every rule carried a threshold standing in for a parse
  and the next shape fell between two of them. The last one was one word wide —
  `` aria-label={`Remove ${source.name}`} `` sat below a two-word threshold that
  existed to keep `` `audience${key}Hint` `` out. It is now
  `frontend/scripts/check-i18n.ts`, walking `JsxText`, `JsxExpression`,
  `StringLiteral` and `TemplateExpression` through `ts.createSourceFile`: a node the
  formatter broke over three lines is one node, a type argument list is not JsxText
  at all, and a comment is invisible rather than blanked. `MIXED`, `COUNT`, `LEAD`,
  `JSX_TEXT`, `mask_generics`, `readable`, `NOT_PROSE` and both word-count
  thresholds are deleted rather than ported; every policy rule carries over.
  Runs from `make lint-frontend` (`bun run check:i18n`) and a new pre-commit hook,
  with `frontend/scripts/check-i18n.test.ts` in place of the five
  `backend/tests/test_check_i18n_*.py` files. Closes #395 and #141. (#610)
- **131 hardcoded strings answered, and 34 dead keys deleted.** What the parser
  reports on the tree before the sweep, in 66 files: 64 template literals, 62 text
  nodes, 4 strings and a toast. That is the one-word template literals #395
  measured (`aria-label`s and toasts — `Open ${org.name}`, `${name} updated.`), the
  multi-line text nodes #141 measured (the 404 page, `global-error.tsx`, the
  magic-link step, four legal paragraphs), and eight confirm-dialog titles a bare
  `?` on the machine-read list had been exempting. 128 became messages; three took a
  reasoned `i18n-exempt` — two on the error boundary that renders above
  `NextIntlClientProvider`, one on a capability's wire format. A sentence split across an
  element is now one `t.rich` message rather than a head, a `<span>` and a tail,
  which is what made the 34 fragment keys dead — the guard's own `unreadKeys` named
  every one. Three decisions worth recording. A number and its unit is a formatter
  rather than a message — `` `${bytes} KiB` `` is the shape, and `ctx` joined the
  unit list for the model picker's badge — so the fourteen of those take a rule
  rather than fourteen exemptions. `PROVIDER_DEFAULT` holds a key now instead of the
  words, per the module-table rule. And `result: ` in `run-python.tsx` keeps an
  exemption, because `parseResult` beside it matches the string literally. (#610)

### Fixed

- **An `i18n-exempt` now covers the element it opens.** It applied to its own line
  and the next, so the three exemptions in `app/not-found.tsx` — written above an
  `<h1>` whose words are on the third line, because the opening tag carries four
  Tailwind classes — covered the tag and missed the copy. Nothing noticed while a
  text node alone on its line matched no rule at all. A reason worth two lines
  covers the code under the whole comment block, too. (#610)
- **The parser reads a `.ts` file, which is what kept #446 closed.** The port
  landed with the offence sweep narrowed back to `*.tsx`, because the branch was
  cut before #446 was fixed. Merging it that way would have taken the `.ts` sweep
  out again — every `toast.success("…")` in `src/hooks/**` invisible, and nothing
  stopping the 381 strings #446 migrated from coming back. The sweep reads both
  suffixes now, by the same rules: a parser has no bracket to anchor on, so
  nothing needs gating on the suffix. `src/app/api/**` keeps its skip, still at
  the sweep rather than in a rule, because a route payload is a string a rule
  reads perfectly well and what excuses it is where it lives (#603). Six strings
  the widened sweep found are in the catalog: `timeAgo`'s three relative-time
  labels as ICU plurals, the stream-error prefix, `chunk {number}`, and
  `summarizeEmbedding` — deleted rather than translated, having had no caller but
  its own test. (#610)
- **A key was checked against the wrong namespace when a file held two
  translators.** `missingKeys` unioned every namespace in a file, so a key read
  through one translator counted as present if any *other* namespace held it. That
  hid eight keys on the admin conversations page: `archived`, `active`, `all`,
  `allOwners` and `allAgents` were read through a `useTranslations("admin")` while
  only `pages.admin` held them, so all eight rendered as their own key strings on
  screen in every locale. A call now resolves to the nearest enclosing binding of
  that name — by scope, because one page binds `getTranslations("pages.meta")` in
  `generateMetadata` and `getTranslations("pages.auth")` below it, both called
  `t`, and keying on the name alone reports 157 live keys as missing. Where the
  walk finds no binding it falls back to every namespace that name takes. (#610)
- **`` `Bearer ${token}` `` was reported as copy.** An auth header value is the one
  header shape `MACHINE_READ`'s character class cannot see, holding no punctuation
  at all, so the whitespace rule read it as a word beside an interpolation. Only
  latent while the sweep skipped `.ts`; both call sites are in `src/lib`. (#610)
- **A ternary between two one-word labels in a readable prop was read by nothing.**
  `aria-label={busy ? "Saving" : "Save"}` passed the attribute rule, which read a
  bare literal, and `readString`, which wants a capital and a space before it calls
  something a sentence — #395's own defect wearing a ternary. A label is
  capitalised or holds a space, which keeps `dir === "asc" ? "desc" : "asc"` out.
  (#610)
- **A toast holding a sentence was reported twice**, once by each rule that owns
  it, inflating the count a person works through. The toast rule keeps its
  argument. (#610)

## [0.0.111] - 2026-08-12

The pricing caveat on the cost screen says which breakdown it measures and which
it only marks.

### Fixed

- **One caveat, three breakdowns, and three places claiming it measured all
  three.** "Some runs could not be priced" counts top-level runs — one per run
  tree, the same rows *By agent* groups — so it measures that breakdown and only
  *marks* By provider and By key, which sum every row's own spend, delegated rows
  included. One parent with three unpriced delegates therefore reads `1` while
  three figures below it are a floor. The two schema descriptions, the route
  comment, the rendering side and `docs/governance.md` now say that instead of
  claiming the figure and "its breakdown" cannot disagree. Descriptions, comments
  and tests only — no behaviour change. (#597)
- **The invariant behind it was untested end to end**: no breakdown is a floor
  without a figure on the same page saying so. Two integration tests now pin it —
  a priced parent with an unpriced delegate reads `1` above a provider split that
  is the delegate's own spend, and one parent with two unpriced delegates still
  reads `1`, with the delegate's own row counted nowhere. (#597)

Checked and not changed: the marker itself is sound. The reported sequence — an
unpriced delegate leaving the count at `0` — is not reachable, because a run tree
shares one spend ledger and the top-level row is written from it.

## [0.0.110] - 2026-08-12

A turn that stopped for an approval no longer says so in the agent's own voice,
in a transcript that keeps it forever.

### Fixed

- **The approval notice was stored as the agent's words.** A chat turn that
  parked on an approval wrote *"This run needs approval before it can go further
  — it is waiting in the approvals queue."* into the assistant message's
  `content`. The moment somebody approved, that sentence was false, and it stayed
  in the transcript attributed to the agent, in the middle of a turn that plainly
  did go further — visible between two steps that both ran, since a run's segments
  are drawn as one turn. It was never the model's text; it was UI state written
  into the one field that keeps things forever. A parked run now records no answer
  of its own, which is what every surface that does not stream already did — web
  chat was the one place inventing a sentence. That a run is parked is still said
  by the two things that stop saying it once the decision is made: the step it
  stopped on, and the approval panel. (#509)
- **A model that explained itself before asking for a gated call had that
  explanation overwritten.** A parked turn now persists what was streamed before
  it stopped, the same route a turn that failed, was stopped or lost its socket
  already takes. Usually empty; not always. (#509)

Known, and no longer covered for: a still-parked run says nothing about waiting
once the page is reloaded — the stored tool-call row keeps `status="running"` and
renders as a finished step, and the approval panel is only ever raised by a live
socket frame. Every non-streaming surface has always looked like this; the notice
was accidentally hiding it here. (#601)

## [0.0.109] - 2026-08-12

The suite reaches no Prefect server on a laptop either, so what a developer runs
is what CI runs.

### Fixed

- **A test that called a flow needed a Prefect server listening on
  `localhost:4200`.** Prefect resolves its own settings from `backend/.env` — its
  settings model carries `env_file=".env"` — so the `PREFECT_API_URL` line
  `make dev` needs was also the address a test's flow call tried to reach, and it
  failed as `Failed to reach API at …` out of a test that patches every
  collaborator it has. CI never saw it: with no `.env` there is no URL, so what a
  laptop ran was never what CI ran. The URL is now assigned *empty* before Prefect
  is imported — deleting it would leave the dotenv source to answer, and an empty
  assignment outranks that source because Prefect's model carries
  `env_ignore_empty=False` — and Prefect reads an empty URL as no URL, running the
  flow against a temporary server of its own, which is what CI has always done.
  Unconditionally, so a developer with `make dev` up gets the same run rather than
  a different code path. (#536)
- **That temporary server wrote into a developer's own Prefect database.**
  Its state is a SQLite file under `PREFECT_HOME`, which is `~/.prefect` unless
  something says otherwise — the same file a locally run `prefect server` has
  open. It now points at a directory of the tests' own, for the same reason the
  test database name does. (#536)
- **And starting it inside Prefect's own 20-second allowance failed on a first
  run.** The server migrates its database before it answers: about 75 seconds cold
  against a `PREFECT_HOME` nothing has written, about seven warm. Trading a
  deterministic failure for a first-run one is not a fix, so the allowance is 90
  seconds, and ephemeral mode is named rather than inherited — with it off a flow
  call does not fail fast, it retries for 75 seconds and then fails. (#536)

## [0.0.108] - 2026-08-12

The backend suite runs in a random order, and the first shuffle found a
connection-pool defect that had been hiding behind collection order.

### Added

- **`pytest-randomly`, and the documentation that described it is now true.**
  Two pages said the shuffle was on by default while the plugin was in neither
  `pyproject.toml` nor the lockfile: the suite ran in collection order, the
  documented `-p no:randomly` was a silent no-op, and the order-independence
  those pages called verified had never been exercised by that mechanism. The
  seed is printed in the header and reaches every xdist worker through
  `workerinput`, so `-n auto` collects one order rather than four. A guard test
  asserts the *declaration*, so removing the dependency fails a test rather than
  silently un-shuffling the suite. (#571)

### Fixed

- **A closed event loop's connection was left in the app engine's pool.**
  `app.db.session.engine` is a module-level object, so its pool outlives the test
  that filled it, while anyio gives every test its own event loop — and a
  connection created on a loop that has since closed answers
  `cannot perform operation: another operation is in progress` for the next
  statement issued through it, in whichever test checked it out. The two files
  driving the real `get_db_session` each disposed the engine on the way *out*,
  which covers only the pair of them; anything else sharing the xdist worker
  could leave a connection there. The `engine` fixture now disposes on the way
  *in*, and the two per-file disposes are gone. Pre-existing — which tests share
  a worker was already decided at run time by `--dist load`; the shuffle only
  changed the adjacencies and made it surface, red on run 6 of 8. (#571)

## [0.0.107] - 2026-08-12

Picking Polish now survives the next click.

### Fixed

- **The language switcher redrew the current page and nothing more.** The
  locale's entire persistence was the `/pl` URL prefix, and under
  `localePrefix: "as-needed"` a path without a prefix *is* the default locale —
  so every ordinary `<Link href="/agents">` and `router.push("/orgs")` in the app
  dropped the prefix and the language with it, and a reload never brought Polish
  back either. next-intl reads a `NEXT_LOCALE` cookie itself, but only under
  `localeDetection`, which also turns on `accept-language` sniffing — and this
  deployment serves English at the root whatever the browser asks for. So nothing
  wrote the cookie and nothing read it. One routing config now backs both the
  middleware and the navigation APIs: the switcher writes the cookie with a
  year's `maxAge`, making the choice a preference rather than a session, and the
  middleware redirects an unprefixed path to the picked locale while still
  ignoring `accept-language`. A path that names a locale always wins, so a shared
  `/pl/...` URL still means what it says. (#285)

## [0.0.106] - 2026-08-11

The seam that puts a chart in a Slack reply is covered, so the line holding it
there can no longer be deleted with a green suite.

### Fixed

- **A chart could stop reaching a channel reply without a single test
  noticing.** `drawn_chart` was covered on its own and the runner's hand-back of
  the tool calls a turn made was covered on its own; nothing joined them. Every
  test of `ChannelAgentRouter.answer` mocks the runner, so the list of calls
  stays empty and `image_png` is always `None` — which means `tool_calls=called`
  could be deleted from either call site in `channels/mentions.py` with a green
  suite and a 100% coverage gate, and a Slack user would be back to reading
  "here is the chart" under no chart. Both reply paths now run against a stub
  runner that fills the list the way the real one does, and assert on the PNG
  rather than on a mock call; the stub takes the tool calls as a *required*
  keyword, so a router that stops passing them fails loudly. (#515)

Two things the issue behind this asserted did not survive checking, recorded
here rather than left open: the line it named was already covered by the pull
request that exposed it, and CI was never green while the local gate was red —
the same 99.98% failure was red there for seven runs, so this was not a
`make check` / CI divergence.

## [0.0.105] - 2026-08-11

`next build` no longer touches the network, so a CDN nobody in this repository
controls can no longer fail a frontend build.

### Fixed

- **Every green frontend build so far was luck of the CDN.**
  `next/font/google` resolves a family against `fonts.gstatic.com` at build
  time, and when gstatic 404s the `.woff2` Turbopack surfaces it as
  `Module not found: Can't resolve
  '@vercel/turbopack-next/internal/font/google/font'` and exits non-zero — which
  is `test-frontend`'s `Build` step and `e2e`'s `Build the frontend` step. On
  2026-08-10 it took out two pull requests inside one push window (#570,
  Bricolage, six errors; #544, Inter, twenty-eight) while a third built fine.
  Bricolage Grotesque, Inter and Geist Mono are now vendored under
  `frontend/src/app/fonts/` and read by `next/font/local` — the latin subset of
  each, range-limited to the weights in use, 113 KB across the three, with SIL
  OFL 1.1 and all three copyright notices beside them. A regression test asserts
  no module imports the Google helper and that the set of `.woff2` on disk is
  exactly the set `layout.tsx` declares, compared in both directions. (#572)

- **The coverage gate failed at random, on branches with no Python in them.**
  Exactly 99.98%, twice tonight: on a frontend-only change and on a commit that
  bumped three version strings. The missed line was the `continue` in
  `catalog.custom_icon`, reachable only when `glob` yields a non-matching mark
  first — `scandir` order, which on the runners' ext4 volumes is hash order, not
  alphabetical. A test that asks for a name matching no mark in a directory
  holding two now reaches it whatever the order. A red `test` job at 99.98% on a
  diff that touched no Python is this, and reading it as the branch's fault cost
  an hour. (#625)

Known, unchanged: the vendored subsets are `latin` only — exactly what
`subsets: ["latin"]` asked for before — so Polish diacritics on the `pl` locale
still fall through to the system font.

## [0.0.104] - 2026-08-11

A channel message the platform delivers twice is answered once, and the decision
is the Redis claim rather than a retry header that cannot know.

### Fixed

- **A redelivered channel message became a second full agent run.** Another model
  call, another spend record, another answer in the thread. The fast 200 the
  webhook routes return only prevents the slow-handler retry; a 200 lost on the
  wire — a proxy drop, a pod rotation — was never received, and the redelivery
  that follows is valid, signed and brand-new. The first delivery now claims the
  message with one atomic `SET NX` against the shared Redis, so the claim holds
  across API workers, and it lives fifteen minutes — longer than every platform's
  retry window. Taken in `ChannelMessageRouter.route` rather than the worker shim,
  because the three polling paths call the router directly and a claim in the shim
  would have covered three inbound paths of six; keyed with the chat id, because
  Telegram numbers messages per chat and Slack's `ts` is per channel. (#167)
- **A run that did not finish swallowed every redelivery for fifteen minutes.**
  The claim is taken on receipt, not on completion, so it is given back when the
  run under it dies — under `BaseException`, so a task cancelled while the pod
  drains counts as one. Harmless on the webhook paths, where the 200 has already
  gone out, but the pollers re-read what the process died on: aiogram re-fetches
  an unconfirmed `getUpdates` batch and Socket Mode redelivers an unacknowledged
  envelope. (#167)
- **Nothing is refused on a retry header alone.** A Slack request carrying
  `x-slack-retry-num` is logged and then processed like any other. The header says
  Slack is redelivering; it does not say the first attempt did any work, and
  `reason=http_error` means it explicitly did not — the route raised before
  `spawn`, so nothing was scheduled and no claim was taken. A transient database
  error in `find_active` was enough to lose a message that way: 500, redelivery,
  200, and a log line reading like a success. (#167)

The guarantee degrades open, never shut, and always with a log line: a message
with no id, an unconfigured module and an unreachable Redis are all processed
rather than dropped. A duplicated answer is the rarer, cheaper failure than a
dropped question.

## [0.0.103] - 2026-08-11

The Builder says when the agent people are talking to is not the one on screen,
and Publish says what it will move before it moves it.

### Added

- **Publish says what it will move before it moves it.** The confirmation dialog
  names the version it creates, the default environment that follows the publish
  the moment it lands (or, on a first publish, that `production` is created and
  the agent goes live), and each pinned environment that stays on the version it
  is pinned to. (#519)

### Fixed

- **The Builder tracked "unsaved" and never "unpublished".** Once the autosave
  settled the page read as finished, while every channel, widget and API call was
  still answering with the published version — toggle a tool off in the Toolbox
  and nothing on screen said a publish was needed. A header badge now compares the
  *stored* draft against the frozen version spec: "Draft differs from v7", with a
  title spelling out that published surfaces keep answering with v7 until a
  publish, or "Up to date with v7". Compared as sorted-keys YAML, the same
  serialization the version diff reads, so key order cannot read as a change
  nobody made. (#519)
- **A publish left the environments panel naming the pin it had just moved.**
  Publish and rollback invalidated `qk.agents` and not `qk.environments`, so the
  History tab contradicted the dialog's own sentence seconds after it was read.
  Pre-existing; included because the new dialog makes it visible. (#519)

## [0.0.102] - 2026-08-11

The copy guard reads a `.ts` file, and the 381 English strings it had never been
pointed at are in the catalog.

### Fixed

- **`check_i18n.py` never read a `.ts` file, so every hook toast was invisible to
  it.** The offence sweep walked `frontend/src/**/*.tsx` and nothing else, which
  left 381 offences across 90 files unread since the guard was written: nineteen
  `toast.success("…")` in `src/hooks/**` alone, plus the module tables of labels in
  `lib/tool-catalog.ts`, `lib/ingestion-config.ts` and `lib/mcp-servers.ts`.
  Widening the glob was not the fix — in a `.ts` file `; return` is a text node and
  `a > b` is a count — so `JSX_TEXT`, `MIXED`, `COUNT` and `LEAD` are gated on the
  suffix and the rest now read a string literal wherever it sits. All 381 are
  migrated: 233 messages added to `messages/en.json`, and the module tables hold
  keys with the copy resolved where it renders, pure helpers taking the caller's
  translator (`toolStep`, `toolCaption`, `ingestionProblems`,
  `mergeWithUserCommands`). (#446)
- **The `import`/`export` line-skip keyed on the keyword rather than the module
  specifier**, which in a `.ts` file hid every `export const LABEL = "…"` and every
  default parameter on an `export function` — `getErrorMessage`'s
  `"An unexpected error occurred"`, the sentence behind most failed requests here,
  and `PROVIDER_DEFAULT` beside a `useTranslations` import somebody had already
  added and never used. (#446)
- **The MCP add-server dialog rendered a catalog key as its hint.** `AUTH_CHOICES`
  held `hint: "authTokenHint"` and the paragraph below the radio group printed it
  verbatim, in every locale — neither a hardcoded string nor a missing key, so no
  guard could see it. Found by the duplication rule once the catalog held the
  sentence. (#446)
- **The test translator was rebuilt on every call**, where the real
  `useTranslations` is a `useMemo` over stable inputs. A hook putting `t` in a
  `useCallback`'s dependencies then handed a new function to every render, and an
  effect keyed on that callback re-fired forever: the admin conversations screen
  loaded in a loop and never left its spinner. `vitest.setup.ts` caches one
  translator per namespace. (#446)

### Removed

- **A superseded MCP catalog and two dead helpers.** `lib/mcp-catalog.ts` held a
  curated table of fourteen servers with their own descriptions, examples and
  category headings; nothing rendered it — the catalog the product shows is served
  by the backend from `app/core/catalog/mcp_servers.json`, is fifty-nine entries
  deep, and has its own categories. Its copy was dead English, so it was deleted
  rather than translated, along with `MCP_CATEGORIES`' four unrendered headings and
  `summarizeIngestion`, which only its own test called. `gen-mcp-logos.ts` now
  takes its domains from the backend catalog. (#446)

## [0.0.101] - 2026-08-11

Three static guards against the code getting worse, and the slop they target
swept out of the tree.

### Added

- **Guards that enforce standards `CLAUDE.md` only stated.** `scripts/check_routes.py`
  keeps an endpoint module to routers — a helper moves to a service or a
  `_`-prefixed module, or carries a reasoned `# routes-helper` marker;
  `scripts/check_comments.py` rejects ASCII banner comments; and `vulture` gates
  unused variables and parameters in `make lint`. The noisier function-level scan
  and the frontend `knip` live in `make dead-code` as an advisory report, because
  a blocking function gate on a registry-driven codebase is false positives all
  the way down. (#595)

### Changed

- **Route helpers moved out of the endpoint modules.** The runs status parser
  became `RunStatus.parse_csv`, on the enum that owns the values and shared by the
  list and export routes; the sharing loaders moved to `_sharing_loaders.py`.
- **Comment slop removed, ~140 lines across the backend and frontend** — section
  labels, restatements, and mechanism-narration. The load-bearing
  `#issue`/footgun/invariant comments and the docstrings stay, and `CLAUDE.md` and
  `code-style.md` now state the bar: the default is no comment.
- **Two dead items the previous sweep missed**, caught by the new `vulture` gate:
  `sanitize_filename`, orphaned when its only caller was removed in #579, and a
  dead `project_id` argument on `channel_session.create`. Closes #521. (#595)

## [0.0.100] - 2026-08-10

Dead weight removed across the backend and frontend, and one dead method turned
into a real contract.

### Changed

- **Stripped unreferenced code across the tree.** Repository helpers, service
  methods, sanitizers and frontend exports with no surviving caller are deleted
  (each traced first), and four frontend `export`s narrowed to module-internal.
  Net −892/+53. Not only deletion: the vector store's dead `aclose()` becomes an
  abstract contract the application lifespan shuts down through, so teardown no
  longer reaches past the interface into `.engine` behind a `# type: ignore`.
  (#579)

## [0.0.99] - 2026-08-10

Run history can be filtered by rating, and a down-rated run says so — with the
comment readable on the run itself.

### Added

- **Filter run history by rating, and flag a down-rated run.** A `rated=down`
  filter on run history, and a `down_rated_run_ids` marker on list rows —
  tenant-bound, `distinct`, and the same `rating < 0` definition the filter uses,
  so a marked row is exactly a row the filter returns. In the run detail, the
  most recent down rating's comment is read off the transcript
  (`RunTranscriptMessage.rating_comment`, from
  `get_down_rating_comments_for_messages`, batched newest-first), so "what people
  said was wrong" is readable where the run is read rather than only in the
  app-admin export. Permission-gated on `runs:view`. Completes the run side of
  #209. (#538)

## [0.0.98] - 2026-08-10

Runs, approvals and spend export as CSV — exactly the rows the list would show.

### Added

- **CSV export for runs, approvals and spend.** `GET /runs/export`,
  `/approvals/export` and `/spend/export` each serialise exactly the rows their
  list route would return, gated as their list sibling is (runs and spend on
  `runs:view`, approvals on `approvals:decide`) with the `Scope.OWN` floor
  enforced in-query. An unbounded export gets the two rules it needs by design: a
  mandatory date range and a row cap that refuses rather than truncates above it.
  Columns survive a spreadsheet sum — `cost_is_partial` on runs,
  `partial_run_count` on spend, so a wholly unpriced run exports a real `0` beside
  `cost_is_partial=true`, never a bare `0` — and CSV formula injection is
  neutralised. Each export writes an `audit_log` entry (window, applied filter
  names, row count — never the request body or a resolved row). An export menu on
  the Activity page carries the applied filters, gated on `runs:view`. Closes
  #211. (#531)

## [0.0.97] - 2026-08-10

Regression coverage that every entry point records a run's transcript.

### Changed

- **Transcript recording is covered for embed, channel and default-agent runs.**
  `backend/tests/test_surface_transcripts.py` asserts at the repository boundary
  that a widget run, a channel mention and the default agent each record their
  turns — role, content, run id, the model and version that actually ran, and
  tool-call args and results — and that a broken widget run still records what
  the visitor asked. Closes #205's requirement that the fix ship with a
  regression test. (#530)

## [0.0.96] - 2026-08-10

The sync-source wizard is decomposed into one component per step — a structural
refactor, no behaviour change.

### Changed

- **Sync-source wizard split into per-step components.** The 761-line
  `sync-source-wizard.tsx` becomes a ~320-line shell (cross-step flow, the shared
  form, the header and step indicator, and the `connectorsFailed` /
  `orgIntegrationsFailed` flags it hands down) plus one component per step —
  `sync-source-{connector,configure,schedule,clone}-step.tsx` — following the
  pattern #221 set in `components/rag/`. A folded-in fix routes the empty-config
  note through `next-intl`. Closes #461, #540. (#529)

## [0.0.95] - 2026-08-10

The Activity tab's spend view breaks down who spent what.

### Added

- **Per-person spend on the Activity tab.** A `SpendByPerson` card beneath "By
  agent" on the Spend tab reads `/stats/usage?group_by=user` over the tab's date
  window, gated on `runs:view` (renders nothing and issues no query without it),
  with delegated runs excluded. A "+N others" line appears when `active_users`
  exceeds the rows shown, so a top-N list never reads as the whole organization.
  Closes #214. (#578, superseding the stacked #527)

## [0.0.94] - 2026-08-10

The Activity tab gains a per-version summary that cannot disagree with the
dashboard's completed-share figure.

### Added

- **A version strip on the Activity tab.** When narrowed to one agent, a card per
  version sits above the run table — runs, completed share, cost per run, p95 and
  the current-version marker. Its "completed share" and the dashboard's Outcomes
  donut both compute through one shared helper (`src/lib/run-outcomes.ts`), with
  `cancelled` and `budget_exceeded` in the denominator on both sides, so the two
  figures cannot drift. Closes #489. (#526)

## [0.0.93] - 2026-08-10

A run's transcript is readable by authorization, not only by whoever owns the
run.

### Added

- **`GET /api/v1/runs/{run_id}/transcript`** — returns a run's messages
  (paginated) to any colleague in the same organization holding `runs:view`; a
  run is read by authorization, not by ownership. A caller from another tenant is
  refused exactly as a run that does not exist is, so existence never leaks. The
  response's `conversation_id` is `null` when the run has no transcript, distinct
  from an empty `items`. `AgentRunnerService.get_run_transcript` resolves the run
  org-scoped (404 before the permission is read), then checks `runs:view` (403).
  Closes #490. (#525)

## [0.0.92] - 2026-08-10

The whole-suite test targets run across worker processes, roughly halving them.

### Changed

- **`make test` and the other whole-suite targets run across workers.** `pytest
  -n auto --maxprocesses 4` on `test`, `test-fast`, `test-integration` and
  `test-cov`; `pytest-cov` combines the per-worker data so the 100% platform gate
  is unchanged, and scoped `pytest <file>` runs stay serial (spawning workers for
  one file costs more than the file). The cap is four because the unit slice is
  import-bound — every worker imports the app once — and an uncapped `-n auto` on
  a many-core machine runs *slower* than serial, all of it worker startup. Adds
  `pytest-xdist` to the dev group. Refs #520. (#570)

## [0.0.91] - 2026-08-10

The integration test suite builds its schema once per process instead of before
every test, halving it.

### Changed

- **Integration tests build the schema once, not before every test.** The
  per-test `drop_all` + `create_all` (~0.4s of DDL each, very nearly the whole
  runtime of a suite whose assertions are microseconds of Postgres work) is
  replaced by a session-scoped build plus a `TRUNCATE ... RESTART IDENTITY
  CASCADE` reset between tests. The integration slice drops from ~125s to ~53s,
  and the per-process `_p<pid>` database isolation is untouched, so two runs on
  one machine stay safe. `TRUNCATE`, not a rollback: the API-flow tests commit
  through the real session, so their rows would outlive a rollback. Closes #215.
  Refs #520. (#535)

## [0.0.90] - 2026-08-10

Importing the application stops dragging in two SDKs it never uses on the
request path, so every process start and scoped test run is a couple of seconds
shorter.

### Changed

- **`import app.main` no longer pulls in `aiogram` and `prefect`.** The Telegram,
  Slack and Mattermost adapters are imported inside `lifespan` (which the test
  client never runs) and the sync flows inside their dispatcher, so a cold app
  import drops from ~5.5s to ~2.3s — a cost every scoped `pytest` run and every
  process start paid for libraries neither the API nor the tests touch. A
  subprocess guard test keeps them out of `sys.modules`, and a dead
  `_slack_register` alias went with it. Runtime behaviour is unchanged; startup
  imports them as before. Refs #520. (#544)

## [0.0.89] - 2026-08-10

Run history gains the duration controls the dashboard's p95 needs rows behind,
and the contributor guidance has its test-loop numbers corrected.

### Added

- **Sort and filter run history by duration** — a sortable `Took` column, a
  "slow runs" canned view, and a dashboard p95 deep-link that seeds the sort and
  the time window. The sort is server-side over the whole narrowed set, not one
  page; the backend query landed with #202 and is reused unchanged. Closes #210.
  (#528)

### Changed

- **Contributor guidance** — `CLAUDE.md` now states the scoped-vs-full test rule
  outright and its runtime figures are corrected against measurement: CI answers
  in about twelve minutes rather than seven, and a scoped backend file takes a
  few seconds rather than "under one" (the wait is importing the app, not the
  run). The same stale CI figure in `docs/testing.md` and three moved
  `app/core/catalog/` paths in the docs trigger map went with it. Closes #522.
  (#534)

## [0.0.88] - 2026-08-10

Two grouped dependency updates, nothing else. The lockfile resolves cleanly with
both applied (`uv lock --check`), and CI is green on the combination.

### Changed

- **Agent-framework dependencies** — `pydantic-ai-slim` to 2.26.0 (including its
  `mcp` extra), `logfire` to 4.40.0, and `genai-prices` to 0.1.1. (#523)
- **The rest of the backend** — `uvicorn[standard]` to 0.52.1, `alembic` to
  1.19.0, `pymupdf` to 1.28.2, `liteparse` to 2.11.1, `google-auth` to 2.56.3,
  `boto3` to 1.43.66, and the `ty` type checker to 0.0.69. (#524)

## [0.0.87] - 2026-08-10

Mattermost is a channel you can register and talk to, and the gaps that stopped
any channel from being a complete surface are closed with it. One agent can now
answer on Mattermost, Slack and Telegram, be watched writing its reply, read the
channel it is answering in, and be told how to write for that surface — without
editing the spec every surface shares. Closes eleven issues (#41, #24, #22, #10,
#205, #157, #152, #208, #26, #153, #514). The delivery-dedup guard a retried
webhook needs is deliberately not here and stays tracked as #167.

Nine migrations, `0013`–`0021`, add the link-request, exposure-prompt and
per-binding tool columns and settle the "one agent per bot" rule. `SPEC_VERSION`
stays at **8**: the channel-tools capability is assembled per run from the
binding that admitted the message, never stored in a published spec.

### Added

- **A working Mattermost integration.** A bot is registered with its own server
  URL and an operator-supplied webhook secret, and answers over either an
  outgoing webhook or an authenticated event stream — the latter the right
  choice behind a VPN, exposing nothing. Registerable from the exposure panel
  and from the CLI (`agenticos cmd channel-add-bot`), for a deployment with no
  browser pointed at it. `api_base_url` is validated on scheme and shape so an internal
  address passes. (#41, #24)
- **A reply a chat can watch being written.** A placeholder post appears the
  moment the question arrives, grows in place — throttled to about one edit a
  second — and shows what the agent is doing while a tool runs, on Mattermost,
  Slack and Telegram through one seam. An adapter that cannot edit a message
  still posts one finished answer. (#514)
- **A per-channel prompt on the binding.** House style for a surface — how to
  lay a message out, how long to answer, which language — appended to the spec's
  instructions at run time and never substituted for them, seeded per platform
  and editable beside the environment and session-scope controls. It lives on
  the exposure row, so it never enters a client's exported YAML. (#153)
- **An agent can read the channel it is answering in** — its info and members —
  through tools granted by the binding, so "may it read what was said here" has
  a different answer on an internal server and a customer one.
- **Account linking and complete channel runs.** `/link` mints a code and
  `@slug` runs as the person who typed it; a channel run records its messages
  and the surface it arrived on, renders a chart as an image, and answers a tool
  approval in the thread that asked for it. (#10, #205, #208, #157, #152)

### Changed

- **`webhook_secret` is sealed at rest** through the vault, beside the three
  secrets that already were; the Mattermost webhook accepts the token Mattermost
  generates rather than one minted locally, while Telegram keeps minting the one
  we hand out. (#22)
- **A channel webhook hands its work over with `spawn_after_commit`**, so the
  background run sees the row the request just wrote. (#26)
- One bot serves one agent; a second binding to the same bot is refused.

### Fixed

- A failed final live-reply edit re-posts the answer whole instead of blanking
  it; "needs approval" is said only when a run actually parked; a resumed channel
  run keeps its exposure prompt and channel tools; and the chart renderer sizes a
  stacked bar to the stack rather than the tallest bar, treats a non-finite value
  as a gap, and draws in any colour Pillow accepts.

## [0.0.86] - 2026-08-09

A file dragged into the chat lands wherever it is dropped.

### Changed

- **The whole page is the drop target.** Attaching a file by dragging it meant
  hitting the composer - a strip a few centimetres tall at the bottom of the
  window - and missing it was not a no-op: the browser's default for a dropped
  file is to *open* it, so a drop anywhere else navigated the tab away from the
  conversation and whatever was half-typed in it. The same `preventDefault` that
  lets the page take the file is what stops the browser taking it, so listening
  on the window fixes both halves at once. While a file is over the page an
  overlay covers it: the ground blurred, a dashed card in the middle, and the
  per-file size limit written on it, because a 60MB video refused *after* the
  drag is a round trip nobody needed to make.

  A drag carrying anything other than files - selected text, a link, one of the
  app's own draggable rows - is left entirely alone, not even prevented. Nothing
  is accepted while the composer is disabled (an archived conversation, a run
  waiting on an approval), and the overlay not appearing is what says so.

### Fixed

- **The DataTransfer type name was in the message catalog.** The check for "this
  drag carries files" compared against a translated key, so the DOM's own
  constant `Files` sat in `en.json` as copy - and translating it would have
  stopped drag-and-drop working with nothing on screen to say why.

## [0.0.85] - 2026-08-09

Approving a tool call, and everything that was missing on the other side of it.
A run that stopped for a person, was let through, and carried on had almost none
of that written down — so the second half of a turn was a blank, and the record
of it was worse than the screen.

### Fixed

- **A continuation now says what it did.** `POST /runs/{id}/resume` executes the
  agent inside the request rather than on the socket a conversation streams, so
  its tool calls reached nobody: the response carried the answer, the status and
  the cost, and never the work. Approving a command showed nothing running, then
  asked for a second approval for a step that had never been drawn, and finished
  with a reply that accounted for neither. The response now carries the calls, in
  order, each with what came back ([#505](https://github.com/vstorm-co/agenticos/issues/505)).
- **A continuation with no answer recorded nothing at all.** The transcript wrote
  the assistant turn only when there was an answer, and a segment that runs a
  command and then parks on a second one has none — so the command it ran, its
  arguments and its result were never written. Three commands ran in a sandbox
  and history accounted for one.
- **What an approved call returned is recorded.** Its row is written open when
  the run parks; the resume that finally runs it produces the return *without*
  the call it belongs to, so nothing ever closed the row. The one call somebody
  deliberately reviewed was the one call that opened onto nothing
  ([#506](https://github.com/vstorm-co/agenticos/issues/506)).
- **One run is drawn as one turn.** A run that parks leaves several assistant
  messages — each segment written as it happens, rather than folded back into a
  turn somebody has already read — and each drew its own avatar and agent name.
  One question read as three agents answering it. Consecutive messages of the
  same run are now one turn: the avatar and the name once, at the top, and the
  time and the cost once, under the end.
- **The approval panel belongs to its conversation.** It followed the reader into
  another thread and its buttons still worked, so a call could be decided from
  under a different agent's transcript — settling a step in messages that were no
  longer loaded, with nothing on screen changing to say it had happened
  ([#507](https://github.com/vstorm-co/agenticos/issues/507)).
- **A replayed step no longer animates.** A tool call is stored as running until
  something records its outcome, and an expiry runs nothing — so the step it
  parked on stayed open and pulsed in the present tense under a conversation that
  had ended days earlier. The expiry sweep closes those steps now, and a replayed
  call still marked in flight renders as unfinished: not an error, not a success,
  the outcome nobody wrote down.

## [0.0.84] - 2026-08-09

The chat surface, seven issues deep — plus the two things a conversation could
not previously say about itself: what order a turn happened in, and what it is
waiting for.

### Added

- **A turn's order is recorded rather than reconstructed.** `messages.parts`
  (migration `0012`) stores the sequence as it was streamed — reasoning, the text
  the model wrote, and the tools it called, interleaved as they occurred. A row
  used to say *what* a turn contained and never *when*, so a client replaying one
  had to invent an order, and the only one it could invent was reasoning, then
  every tool, then the answer. A turn that introduced three charts, drew them and
  summarised them lost its introduction on save and showed the summary above the
  work it described. Null on a turn of one part and on anything written before
  this, which is a client's signal to fall back rather than render nothing.
- **Search, sort and an agent filter on the conversation sidebar**, served by the
  route rather than applied to the thirty threads already fetched. The tab counts
  are gone rather than moved: they counted what had been fetched, so a deployment
  holding hundreds read "Active 8 · Archived 2". The collapsed rail carries the
  recent threads, a search that opens with the cursor in the box, and Archived.
- **Spreadsheets can be attached and read.** `.xlsx` and `.xlsm` join the allowed
  types, parsed with `openpyxl` — every sheet named, rows tab-separated — and the
  extraction is written beside the original in a workspace exactly as a PDF's is.
  An agent cannot open a workbook: `run_python` has no filesystem and the sandbox
  has no spreadsheet library, so accepting one without parsing it would have been
  worse than the refusal it replaces.

### Fixed

- **`create_chart` drew an empty frame.** `data: list[dict[str, Any]]` reaches a
  model as an array of objects with no declared properties, so the only row the
  schema promised was valid was `{}` — which is what arrived, beside a full set of
  series, colours and axis titles. The numbers are columns now: `x_values` and one
  `values` list per series, with nothing in the signature left unsaid.
- **Tool calls rendered as raw JSON.** `web_search` and `create_chart` were renamed
  in the backend and three of four frontend files went on matching the old names.
  One table now, `lib/tool-catalog.ts`, checked against the capability registry in
  both directions by a backend test.
- **One file viewer and one file card**, everywhere. Opening a file meant four
  different things depending on where it was clicked, and showing one meant three.
- **The file viewer was served the model's read of a file, not the file.**
  `StateBackend.read` numbers every line for an agent citing one; the viewer showed
  those numbers, so Source could not be copied and an HTML preview rendered them as
  page content.
- **A parked run can be decided from the conversation it stopped in.** A resume
  that reaches a second gated call parks again, and nothing said so — the panel
  closed on a run still waiting, leaving the approvals queue as the only way to
  finish it. The resume response carries what is still parked, the panel reopens on
  the same turn, and an approved step stops saying it is waiting for approval.
- **Every message after the first was dropped on a resumed thread.**
  `persist_user_turn` called two functions without a required keyword, and the
  `TypeError` was logged as "failed to persist conversation".
- Charts open wherever they sit in a turn rather than only as the last step; a
  chart's x-axis title no longer lands on its legend; a long paste attaches as a
  file instead of filling the composer; `run_python` folds its code once output
  arrives; the reasoning block renders Markdown; and the Builder's inline
  specialists can be discarded without scrolling past six sections to find the
  control.


## [0.0.83] - 2026-08-08

### Fixed

- **The Activity page's run list and the RUNS figure only moved on a full page
  reload.** `useRuns` — read by both the RUNS figure and the Run history tab —
  carried the app-wide query defaults (`staleTime` five minutes,
  `refetchOnWindowFocus` off), so after an agent ran, the Runs tab sat at "No
  runs yet" and the RUNS count at zero beside a Spend tab that already counted
  the run, until the page was reloaded. It now spreads `DASHBOARD_FRESHNESS`
  like `useSpend`, `useUsageStats` and `useApprovals`, so returning to the tab
  refetches. The runs were written and `GET /runs` returned them throughout —
  this was only a stale client cache. (#499)

## [0.0.82] - 2026-08-07

### Added

- **Activity is rebuilt on our own rows.** `/runs` reads `agent_runs`,
  `messages` and `tool_calls`, so no panel goes blank on a deployment that never
  set `LOGFIRE_TOKEN`. Three tabs — Runs, Approvals, Spend — each owning its own
  request, loading state, empty state and retry, which is the only arrangement in
  which "nothing is waiting" and "we could not ask" stay different sentences. The
  Approvals tab is withheld whole from a caller without `approvals:decide` rather
  than shown with its buttons removed: reading the queue takes the same permission
  as deciding one, so a refused caller was reading a 403 drawn as "Nothing waiting
  — agents are running without needing you".
- **`messages.run_id`** — which run produced a turn, and what a run detail view
  is built on. Nullable, `ON DELETE SET NULL`, no backfill: deleting a run must
  not delete the transcript, and a turn written outside a run has no run to name.
  Chosen over windowing `messages` between a run's `started_at` and `ended_at`,
  which is quietly wrong — two runs in one thread interleave, so the first run's
  window contains the second's turns, and a run that never ended yields an empty
  window that reads as "nothing was recorded".
- **Nine filters on run history**, each narrowing the page and the count
  together: a *set* of statuses (`failed,budget_exceeded` is the query somebody
  actually types), surface, who it ran as, a time window, environment, exposure,
  version, "slower than", and whether anybody rated it down. Sorting by duration
  is computed in SQL over the whole narrowed set, because sorting a page of
  twenty-five sorts the wrong set — that is the gap between "p95 is 14.8s" on the
  dashboard and *those runs*.
- **Spend by provider and by key**, which a per-agent breakdown cannot answer: an
  invoice arrives from a vendor, and a leaked key is found by what was spent
  through it.
- **The role-aware dashboard** (#149): one route, one widget registry,
  twenty-seven cards. Which cards a caller gets is decided by the permissions they
  hold, never by their role name.
- **Where agents run code** (#455): sandbox capacity, sessions and runtime cards
  in that registry — how much room is left, what is running, and what the host
  allows, which are the three questions an operator has when an agent dies inside
  a container.
- **One knowledge surface** (#221): `/rag` lists the bases, `/rag/[id]` is the
  base itself, and `/kb` only redirects. Search now defaults to every base the
  caller can read instead of one collection at a time, and each result carries its
  document, page, score and which base it came from.
- **`connections:view`, so an operator can watch where sandboxes run without
  being handed the keys to them.** `connections:manage` did two jobs: reading a
  host's session list, its activity log and the memory and CPU ceilings its
  service enforces, and pointing a connection at an address and attaching the
  vault secret that starts containers there. Only owner, admin and builder held
  it, so the operator dashboard had no sandbox section at all — despite those
  reads being exactly the operator's questions ("why did that agent just get a
  429"). The reads (`GET /sandbox-connections`, `/runtimes`, `/{id}/policy`,
  `/{id}/sessions`, and the session events) now carry `connections:view`, which
  operator holds; create, edit, delete, probe, the local-service peek and the
  credential store stay on `connections:manage`. Nothing in the catalog implies
  one permission from another, so the roles that manage connections were given
  the read alongside it and lose no access.
- **Two host-wide session numerators** (#495), so all three ceilings on
  `GET /sandbox-connections/{id}/sessions` divide against something honest.
  `len(sessions)` is scoped to the caller's organization and was being divided by
  `SANDBOXD_MAX_SESSIONS` and `SANDBOXD_MAX_OPEN_SESSIONS`, both host-wide — so an
  operator under their own ceiling and still refused a session had no way to see
  the host was full of another tenant's work.

### Fixed

- **Four surfaces were recording nothing at all.** Writing the transcript was
  each surface's job and they were not equal: web chat recorded everything, a
  channel bot recorded two lines of text, and the embedded widget, a channel
  mention, the HTTP API and every resumed run recorded nothing — so an
  organization was billed for an answer given to a visitor on a client's site with
  no row saying what was asked or what was said back. It is written from
  `AgentRunnerService._run` now, the one place a non-streaming run executes,
  because a thing every surface has to remember is a thing the next surface will
  not. The write runs inside a SAVEPOINT: a failed transcript rolls back only
  itself, and the run row's status, cost and tokens still commit.
- **A streaming chat turn that did not finish threw its answer away.** A run that
  failed, hit its budget, was stopped or lost its socket never returns a
  `ChatTurn`, so the write on the success path was skipped and everything the
  model had already streamed was discarded — leaving the run in history pointing
  at a transcript holding the question and nothing else. That is the run somebody
  opens.
- **A delegate's spend was billed to its parent's vendor.** Every run in a tree
  shares one ledger, so a parent's `cost_usd` already contains its children's:
  counting every row billed the money twice, and counting only top-level rows
  totalled correctly while attributing the delegate's spend to the wrong provider
  and the wrong key. Each row now carries what it spent *itself*, which nests and
  still sums to the bill.
- **`logfire_trace_id` was null on every row ever written.** `finish()` accepted
  one from the day the column existed and no caller ever passed it, so the write
  was guarded by a condition that was always false and the field the public API
  documents as a deep link into the trace was empty. It is read at the point of
  writing now, on every path out of a run — including the failed ones, which are
  the runs somebody wants a trace for.
- **An embedded run was recorded as `web`, and a Mattermost mention as `api`.**
  Nothing errored; the numbers simply landed in the wrong bucket, and every reader
  of the column inherited it. A widget on somebody else's public site and an
  employee in the dashboard are not the same thing to anyone asking how this
  product is used.
- **The approvals queue had no stable order to page through.** `created_at` comes
  from `server_default=func.now()`, which Postgres answers with the *transaction*
  timestamp, and a run parks on all of its outstanding calls at once — so every
  call a fan-out parked shared an instant exactly, and a page boundary drawn
  through them let a row come back on two pages or on neither.
- **The count of what is waiting stopped at fifty.** `GET /approvals` answers
  fifty rows at a time and the figure drew `items.length`, so a queue of a hundred
  and twenty read 50 and went on reading 50 however long it grew. A count that
  saturates is worse than a missing one: nothing on screen looks unusual.
- **`kind` never reached a client** (#494). `SandboxConnectionService.sessions()`
  sets it on both return paths, but `SandboxSessionList` never declared the field,
  so `response_model` stripped it — and a Daytona host holding no sessions by
  design was byte-for-byte identical to an idle docker host.
- **The ratings table drew nothing at all on a failed request.** Its error state
  was folded into `empty`, and a failure leaves no rows array for the empty branch
  to fire on — so neither rendered, and an app admin reading a broken endpoint saw
  a header row over blank space with no reason to think anything was wrong.
- **The test suite resolved its Postgres password twice** (#491), with two
  different defaults, so any checkout without a `backend/.env` failed two tests
  for a reason that had nothing to do with the code.

### Changed

- **`SPEC_VERSION` is 8.** `observability.organization` and
  `observability.project` say where an agent's traces can be *read*, which a write
  token does not carry. Both optional with a default, so every stored document and
  every client's exported YAML keeps loading unchanged and there is no migration
  to write. Both are validated as slugs rather than only length-bounded: they are
  interpolated into a URL path, and a value with a slash or a query character
  would escape it.

## [0.0.81] - 2026-08-07

### Fixed

- **145 more keys came out of `messages/en.json`, and 82 of them had a
  hand-written Polish translation** — done for nobody, because nothing read the
  English either. Another 43 messages had their words written out in the source
  beside the key that held them, so the catalogue looked migrated while the
  literal stayed on screen. That is worse than an unmigrated string: the guard
  counted it as handled (#425).
- A sentence split across two keys, its tail beginning at a full stop, so neither
  half reads as copy to anything looking at one key at a time.

### Added

- Three rules, all anchored on the **catalogue** rather than the source, so none
  has to decide what a text node is — which is how two of them reach `.ts` files
  the offence sweep has never opened: a key nothing reads, a message whose words
  also sit in the source, and a value opening on `.` `,` `:` `;`.

## [0.0.80] - 2026-08-07

### Fixed

- **166 values came out of `messages/en.json`**: 18 Tailwind class lists, still
  being read back through `cn(t("…"))` so a translator opening `pl.json` was
  asked to translate CSS, and 148 fragments of JavaScript source that nothing
  read at all. The catalogue goes 2849 → 2696 (#348).
- `check_i18n.py` could not see copy passed through a prop it did not know:
  `READABLE_ATTRS` had no `noun`, so `<Pager>` took one from six call sites as a
  plain English word and rendered `3 of 40 skills` under `pl`, where no plural
  can agree with the count. The word is inside the message now (#362).
- The knowledge-base document table told a Viewer to drag in files they may not
  upload (#349).
- `SharingPanel` interpolated an English noun into five sentences and pluralised
  it with an `s` (#420).

## [0.0.79] - 2026-08-07

### Fixed

- A failed sync source was drawn exactly like a successful one. `SyncStatusBadge`
  tested `status === "failed"`, which the worker never writes — it writes `done`
  and `error` — so every finished and every failed sync fell through to the same
  grey token (#356).
- The document badge twenty lines above it was wrong the same way, and worse:
  three of its four keys (`completed`, `pending`, `failed`) are names nothing
  writes, against the service's `processing`/`done`/`error`. It had been "fixed"
  onto that wrong vocabulary once already.
- `/rag`'s status icon drew anything it did not recognise as a spinner, so a
  cancelled sync spun for the life of the page.
- The sync wizard's target-collection picker could not be reached from any of its
  three call sites, so "Add source" on `/rag` — where the tab lists the whole
  organization's sources — filed against whichever collection the sidebar
  happened to have selected, invisibly (#434).
- Creating a collection on `/rag` reported every refusal as "Failed to create
  collection", discarding the server's own message — which is what made 0.0.66's
  better 400 invisible on the only screen that creates one by name (#436).

### Added

- `frontend/src/lib/rag-status.ts` — one source for the vocabulary, naming the
  three columns that share it and what writes each.

## [0.0.78] - 2026-08-07

### Fixed

- Seven select triggers repeated a badge that only means something in the list —
  "deployment default", "not on this host" — where a comparison against the other
  options has nothing to compare against. They move into `SelectItem`'s `trailing`
  slot, which renders outside `ItemText` and so is not inherited by the closed
  trigger (#341).
- Create knowledge base could not say the embedding-model list had *failed*:
  loading and refused were the same pixels. Refused now has its own branch and
  names the default the collection will get anyway (#365).
- The runtime field lost its only warning when the badge moved, and
  `connection-dialog` saves `default_runtime` without validating it — so you could
  probe a host, pick an alias it had just refused, and save with nothing
  dissenting. An explicit line under the field restores it, and restores it for
  screen readers too, since Radix names an option by `ItemText` alone.

## [0.0.77] - 2026-08-07

### Security

- The chat's model picker created an organization-wide model profile without
  checking `connections:manage`, so anybody who could open a conversation was
  offered the form and refused by the API (#419).
- The chat's approval panel offered editable arguments and Submit to anybody a
  parked run streamed to, though deciding an approval needs `approvals:decide`,
  which neither `member` nor `builder` holds. The banner and the arguments stay,
  read-only; the controls become a sentence (#438).

## [0.0.76] - 2026-08-07

### Security

- `InlineSecret` offered a vault write at seven call sites and only one checked
  `secrets:edit`, so six of them showed the form and let the API answer 403. The
  permission is now checked inside the component, because every call site posts
  the same endpoint — a per-caller gate is one condition written seven times and
  forgotten six of them (#361).

### Fixed

- Two test fixtures answered `/me/permissions` with a list, which is a `TypeError`
  inside `usePermissions` rather than "no permissions" — so those specs had been
  passing for the wrong reason.

## [0.0.75] - 2026-08-07

### Fixed

- The admin conversations screen's Owner filter was permanently empty. Its BFF
  proxy forwarded to a route that has never existed — the path matched
  `/admin/conversations/{conversation_id}` instead, which 422'd trying to parse a
  UUID — and both admin proxies dropped `sort_by` and `sort_dir` on the way
  through (#413).
- The admin users table drew a `Role` column for a field the API stopped
  returning in migration `0066`, so it had been blank since. It now renders
  `conversation_count`, which the backend had been joining for on every page load
  and nothing read (#414).
- The skills library marked a skill uninstalled that cannot be installed, so
  Install answered 409 (#415).

### Added

- `test_bff_forwarded_paths.py` reads every `/api/v1/…` literal out of the route
  handlers and checks it against the application's own route table, in
  declaration order, validating each hard-coded segment through the field FastAPI
  would use. Over 46 forwarded paths it finds exactly one defect — the one above.

## [0.0.74] - 2026-08-07

### Fixed

- A tool call nobody decided parked its run for ever. Approvals still pending
  after their window are now swept to `expired` — recorded as a decision nobody
  made (`decided_by_user_id IS NULL`) rather than as a denial somebody issued,
  so the audit trail says what actually happened (#178).

## [0.0.73] - 2026-08-07

### Fixed

- The web chat billed nothing for the embedding calls behind a knowledge search.
  Metering lived at the call site, so a surface that forgot it under-reported
  silently: `record_ambient_usage` found no active ledger and dropped the cost,
  the run's own total was short, the organization's month never saw it, and
  nothing raised. The meter moved inside `execute` and `iterate`, so every
  surface that runs an agent is metered by construction rather than by
  remembering (#16).

## [0.0.72] - 2026-08-07

### Fixed

- The dev and production stacks notice a worker whose event loop has stopped
  turning (#358). Both were where #336 found them: `docker-compose-dev.yml` runs
  a single unsupervised uvicorn, and `docker-compose-prod.yml` runs uvicorn's
  `Multiprocess`, which pings each worker over a pipe answered by a thread — and
  a thread keeps answering while the loop is blocked, so the one stack with
  cover had cover against the least likely failure. The worker now judges its
  own loop from a thread (`app/core/watchdog.py`) and kills its own process,
  which turns a wedge into the one failure all three stacks already handle.
  Neither supervisor was replaced and PID 1 is untouched in all three.
- Ctrl+C returns from a worker that wedged *before* its first beat (#366). The
  reload supervisor escalated to `SIGKILL` on a verdict it could not reach for a
  worker that had never beaten — one hung on a Postgres that is down, say — so
  the shutdown waited out Docker's ten-second grace period instead. It now
  terminates and joins with a bound, and says which of the two it killed.

### Changed

- **`RELOAD_WEDGED_AFTER` is now `EVENT_LOOP_WEDGED_AFTER`.** It is no longer
  only the reload supervisor's: the worker's own watchdog reads the same
  variable, so one number turns the check off for a debugging session rather
  than leaving one of the two judges running to kill it.

## [0.0.71] - 2026-08-07

### Fixed

- Ingestion and sync flows were spawned before the transaction that wrote the row
  they read had committed, so a flow could start, look for its own document row
  and not find it — an upload answered `processing` that stayed that way.
  `spawn_after_commit` queues the work on the session and `_managed_session`
  starts it two statements after `commit()` (#417).
- `rag-source-sync` cancelled the sync it had just reported starting: `asyncio.run`
  kills pending tasks on the way out (#439).
- `POST /rag/documents/{id}/retry` queued nothing and cleared the error message,
  so a retry was a one-way trip into permanent `processing`. A bare `ValueError`
  on a decided refusal is now a 400 rather than a 500 (#441).


## [0.0.70] - 2026-08-07

### Fixed

- A write was answered before its transaction committed, so the next read could
  miss it. `get_db_session` commits in the exit code of a `Depends`-with-`yield`,
  and FastAPI unwinds that stack **after** the response has been written — so a
  2xx said the request had been handled, not that the write was readable. One
  keyword argument, `scope="function"`, moves the commit in front of the response
  (#353).
- A failed request now rolls back before the error response is built rather than
  after it, because the exception unwinds the same stack. A caller could be told
  404 while the partial write causing it was still open.
- A failed health probe left the session's transaction aborted, which on the new
  ordering turned an intended 503 into a 500 — on the endpoint an operator reads
  when something is already wrong (#416).


## [0.0.69] - 2026-08-07

### Fixed

- Admin user and conversation search did not escape `LIKE` wildcards, so a caller
  typing `%` or `_` changed what the query meant rather than searching for it: `_`
  matched any single character and `%` matched everything, which is a wrong-rows
  bug and a cheap way to make an admin listing scan far more than it should. All
  three sites now go through one helper on SQLAlchemy's `icontains(autoescape=True)`
  (#372).
- Admin listings sorted on nullable columns without ordering nulls, so the emptiest
  rows led page one (#411).

### Removed

- `escape_sql_like` in `core/sanitize.py` — dead, and half-right in a way that
  would have been worse than nothing had anything called it.


## [0.0.68] - 2026-08-07

### Security

- An app admin's password reset was written to the audit trail in plaintext. The
  request body was dumped into `app_admin_audit_logs.details`, so resetting a
  password recorded it (#412).
- A refusal's `details` described the server rather than the refusal: an upstream
  client's exception text on a 503, container filesystem paths on a 500, and a
  provider base URL echoed back on four validation errors — one of which exists
  *because* the URL carries a password. The diagnosis moves to the log; the
  response names the field that explains the refusal (#342).
- A sandbox address could carry userinfo, which `probe_policy` echoed into both
  the response and the log. `ServiceAddress` was the only one of the three URL
  validators not refusing credentials.

### Fixed

- The capability registry echoed a rejected configuration back to the caller in a
  400, unlike the identical call one module over.


## [0.0.67] - 2026-08-07

### Security

- A failed ingest stored a vendor SDK's exception text in `rag_documents.error_message`
  and the dashboard rendered it. An embedding or vector-store client's message can
  carry an endpoint, a key fragment, a bucket name or an internal host — and stored,
  that is a durable leak read later by whoever looks at a failed upload, rather than
  the transient one 0.0.38 closed on the HTTP path. Nine sites now record the stage,
  the exception **type** as a symbol, and what to do about it; the text goes to the
  worker log (#423).

### Fixed

- The outermost ingestion handler overwrote the innermost one's message, so a parse
  failure — the commonest path — reported "could not be ingested" rather than "could
  not be read". Harmless while all three wrote the same `str(exc)`; not harmless once
  the innermost knew which stage had failed.


## [0.0.66] - 2026-08-07

### Security

- `POST /kb` accepted any `collection_name` and never claimed it, so a member with
  `collections:edit` could point a knowledge base at another organization's vector
  table and read and write it through every gate that followed. `claim` had
  exactly one call site, the `/rag` route (#367).
- A collection name over 45 characters truncated onto another collection's table.
  The bound is derived from the longest identifier built from a name —
  `rag_<name>_embedding_idx`, not `rag_<name>` — so a name of 46 to 59 characters
  truncated only the *index* name, `CREATE INDEX IF NOT EXISTS` then found the
  first collection's index and built nothing, and the second collection searched
  unindexed at the first one's width (#368).
- Upper case is refused. Postgres folds an unquoted identifier, so `Handbook` and
  `handbook` were two rows, two collections the platform believed distinct, and
  **one physical table** holding both tenants' vectors — #368's defect reached by
  another route. Refused rather than normalised: this branch's argument is that an
  unusable name is turned away, not silently rewritten into something the caller
  never typed.

### Fixed

- A malformed or reserved collection name answers 400 rather than 500 (#371).
- Dropping a collection whose name the new rules refuse no longer swallows the
  refusal and orphan the vector table.


## [0.0.65] - 2026-08-07

### Security

- A Drive file whose name is a path escaped the sync directory. A remote filename
  is attacker-controlled from this system's point of view — anyone who can share
  a file into a synced folder chooses it — so the write target is now **resolved
  and confirmed** to be inside the directory rather than sanitised by
  substitution, which makes `..`, its encodings, homoglyphs and a pre-existing
  symlink one question instead of a blacklist that is always one entry short
  (#370).
- A sync source's `folder_id` was interpolated into the Drive query unescaped.
  It is now allowlisted where the query is built — the single funnel both the
  configured folder and every recursed sub-folder pass through, so rows written
  before the check are covered too — and asked again by every route that stores a
  config, not only by create (#369).
- Two deployment-wide credential fallbacks removed. A tenant's `folder_id` or
  `bucket` could widen a query running under the **operator's** identity, which
  turns one field of a source's own configuration into a reach across
  organizations. The S3 case was the worse of the two: both settings default to
  empty, so the fallback resolved to `None` and boto3 fell through to the
  container's own credential chain.

### Changed

- The write target is now `BaseSyncConnector.download_file`'s decision, with
  connectors implementing `_fetch`. A connector added later cannot choose a path,
  and a test asserts none overrides it.


## [0.0.64] - 2026-08-07

### Fixed

- Every JSON response the platform proxy returns now declares a cache policy. It
  carried none — no `Cache-Control`, no `ETag`, no `Last-Modified` — on every
  mutable collection on the surface, and silence is not "do not cache": a 200
  with no policy is one the browser may reuse on its own judgement. Every answer
  here depends on a cookie, a permission set and an organization header, so there
  is nothing on this surface a shared or heuristic cache may keep. A backend that
  does name a policy still wins, which is how the catalog icons and the embed
  bundle keep theirs.


## [0.0.63] - 2026-08-07

### Fixed

- A stacked pull request ran no CI at all, and its checks list was empty rather
  than red. `ci.yml` triggered on `pull_request: branches: [main, master]`, which
  matches on the **base**, so a branch opened against another branch matched no
  trigger — and an empty check list reads as "still running" rather than "nobody
  looked". Four pull requests merged that way in one day, each verified only
  locally. The trigger no longer filters on the base (#359).
- `docs/file-processing.md` described a platform-admin RAG model this project
  replaced: "any authenticated user can search any collection", "only admins can
  manage them". All three claims were false, and the same paragraph sat under its
  own heading in `docs/architecture.md`, which a search for "only admins" misses
  because that copy reads `Only **admins**` (#354).

### Changed

- Every CI job now carries a `timeout-minutes`, each several times its measured
  runtime. Only `changes` had one, so a hung job ran to the platform default
  rather than to a number somebody chose (#364).


## [0.0.62] - 2026-08-07

### Fixed

- None of the ten cases around `mask_generics` in the i18n guard's test file
  tested it: stub the function to `return text` and all ten still passed, while
  the guard then reported three false positives over the real tree. It was
  load-bearing and untested, so a refactor could have broken it with only a
  tree-wide `make lint` to notice. One case now fails without it.


## [0.0.61] - 2026-08-07

### Security

- `h2` bumped past CVE-2026-71554.


## [0.0.60] - 2026-08-07

### Fixed

- `main` did not pass `make lint-backend`. Two ruff findings — `RET501` and a
  `RUF100` for a `noqa` naming a rule this project does not select — arrived with
  PRs merged during the GitHub Actions outage, when every check sat `pending` and
  nobody could see them. Because the pre-commit hook runs `ruff check . --fix`
  over the whole tree regardless of what is staged, it kept rewriting those two
  files into unrelated commits and rolling them back, so every branch cut from
  `main` started red on a gate it had not broken (#407).


## [0.0.59] - 2026-08-06

### Fixed

- `tests/test_migrations.py` ran for the first time. It needed a database called
  `agenticos_migrations_test`, a missing one became a module-level skip, and
  nothing in the repository ever created it — so the only assertions that
  `downgrade()` works at all reported "4 skipped" into a green build on every CI
  run this project has ever had (#234). The module creates that database before
  its first test and drops it after its last, with the process id in the name so
  two runs on one machine cannot drop each other's mid-upgrade (#346).
- A remaining skip now means one thing only: no Postgres answered. Under `CI` it
  is not a skip at all but a failure, because a declared service container that
  did not come up is not a laptop without Docker.
- The probe says *why* the server did not answer. A Postgres that is up and
  refusing — a wrong password, a database in recovery — used to be reported as a
  container that never started.


## [0.0.58] - 2026-08-06

### Fixed

- `make install` did not create `backend/.env`, the third thing a fresh checkout
  is missing. Everything running on the host reads it — `db-check`, `db-upgrade`,
  `run`, and pytest through `app.core.config` — so without one
  `POSTGRES_PASSWORD` is empty and `alembic check` is refused with
  `fe_sendauth: no password supplied`, four minutes into `make check`. It is
  copied from the example, once, and an existing file is never overwritten (#299).
- `REDIS_PASSWORD` carried a live placeholder in the example. Copied into a dev
  `.env` it made every request fail against a local redis that has no
  `requirepass`, and in a deployed stack it let `change-me-in-production` be
  inherited from an example file. It is commented out in both directions now,
  and the deployed compose files already refuse to start without a real one.
- The empty `SANDBOXD_TOKEN=` in the example did not match the `^SANDBOXD_TOKEN=.`
  that `make dev` greps for, so a fresh checkout ended up with the key twice and
  worked only by last-wins. The assignment is gone; the comment stays.


## [0.0.57] - 2026-08-06

### Fixed

- `make install` did not install the frontend toolchain, so a fresh checkout
  could not run `make check` at all: eslint, prettier, tsc, vitest and next live
  only in `frontend/node_modules`, and the first four minutes of `check` are the
  backend half, so it said `eslint: command not found` well after you had walked
  away (#227).

### Changed

- `test_ci_parity.py` now holds the setup commands to the mirror-image rule: a
  gating job may prepare its runner however it likes, as long as `make install`
  prepares a laptop the same way. The next toolchain CI adds has to land in
  `install` or be exempted with a written reason.
- `make quickstart` no longer claims to install dependencies in `docs/commands.md`.
  It is `quickstart: dev`, and nothing in that chain reaches `install` — which
  sent people down exactly the road this release closes.


## [0.0.56] - 2026-08-06

### Changed

- The last four route handlers that read a repository directly now go through a
  service, which is what `.claude/rules/architecture.md` has always asked for:
  the audit listing, a knowledge base's sync logs, an org integration's sync
  logs, and the vault key a provider catalog is fetched with (#232).
- `AuditService` is new. The `/audit` route held "an entry belongs to exactly one
  organization" as a keyword argument it filled in itself, which is a scope no
  service test can see and one the next reader of that entity would have had to
  know to repeat.
- Both surfaces showing a sync source's history read it through
  `SyncSourceService.list_logs` rather than each carrying its own query and its
  own copy of the same twelve-field mapping.
- The provider-listing key moves out of a private helper in the route and into
  `OrganizationSecretService`, so nothing in the HTTP layer unseals a secret.


## [0.0.55] - 2026-08-06

### Fixed

- The reserved-names integration test set the vector store's resolver to `None`,
  which stopped being valid in 0.0.43 when the resolver became required and its
  `None` short-circuit was deleted. `_for_collection` calls it unconditionally,
  so the test raised `TypeError: 'NoneType' object is not callable` on every run
  with a real database. Shipped in 0.0.45 and fixed here.


## [0.0.54] - 2026-08-06

### Fixed

- A knowledge base's sync history came back short. The route read every log
  carrying that source id, applied `limit` in SQL, and only then dropped the rows
  belonging to another collection — so the page was cut before the thinning. A
  source repointed at another base (`SyncSourceUpdate` carries
  `collection_name`, and earlier runs keep the name they ran against) made a
  request for twenty runs answer with fewer, `total` described the survivors
  rather than the source, and there was no way to page past the gap. The source
  is resolved against the base first now (#233).
- A source that is not this base's answers `404` rather than `200 []`. Both
  rendered "no syncs yet", and one of them was a request that should have failed.


## [0.0.53] - 2026-08-06

### Fixed

- The double-backtick guard skipped every directory called `worktrees`, which was
  the wrong rule twice over: it silently stopped reading a `docs/worktrees/` that
  is only a directory with a name, and it still walked a git worktree placed
  anywhere else. It now detects a nested checkout — a `.git` file or directory —
  and declines to descend into it, which is what the rule always meant (#225).
- The self-exemption matched one absolute path, so every copy of the script under
  a worktree was reported as three findings on a line nobody had edited. It
  matches the file's name now, and `--fix` is safe on a copy for the same reason.


## [0.0.52] - 2026-08-06

### Fixed

- `scripts/check_i18n.py` skipped any line containing `=>`, because a type like
  `(() => Promise<void>) | null` reads as a text node to a regex — and an inline
  handler is the most common thing on a JSX line, so the exemption was far wider
  than the problem. It also matched nothing when a text node spanned two lines,
  which the formatter does freely. The guard now masks generics rather than
  skipping the line, and reads interpolation rules over the whole file (#314).
- 55 strings across 30 files that those two blind spots had been hiding,
  including two menu items sitting between translated siblings, and English
  compiled into the two model-picker components (#332).


## [0.0.51] - 2026-08-06

### Fixed

- `scripts/check_i18n.py` walked past two shapes of hardcoded copy: a sentence
  that begins with a word before its interpolation, and a count built with a
  lambda rather than an ICU plural. Both render in English under any locale, and
  `make lint` reported clean over them (#249).


## [0.0.50] - 2026-08-06

### Fixed

- The embedding Model select in Create knowledge base never showed its value —
  it said "Loading models…" for as long as the dialog was open, while the list
  below it was populated. Radix writes the new value onto a hidden native select
  and dispatches `change` before the items have registered their options, so the
  value read back was empty and clobbered the state. This is the one choice in
  the dialog that cannot be revisited, since a collection's embedding width is
  frozen at creation (#328).
- The agent builder offered the add-model form to anyone who could open it,
  though submitting needs `connections:manage`, and the store-a-key form inside
  it never checked `secrets:edit`. A control the caller may not use is not
  rendered (#329).
- Two buttons in the same dialog were both called "Add a key" while writing
  different secrets. By accessible name they were indistinguishable, so a screen
  reader heard the same button twice (#331).


## [0.0.49] - 2026-08-06

### Changed

- Every place a provider or a provider key is chosen now draws the same row —
  brand mark, name, an optional masked hint. Choosing an embedding key in Create
  knowledge base offered bare strings while the agent builder three clicks away
  drew the mark, and the two did not look like the same product. Ten pickers
  converge on one primitive, including two that had hand-copied the row and one
  where two different keys rendered as the same line (#304).

### Fixed

- A provider mark's `<title>` was being used as its option's type-to-search key,
  so every model in Create knowledge base answered to `openrouter…` rather than
  to its own name.
- The tick marking a stored key was inherited by the closed select's trigger,
  where it reads as "selected" rather than "has a key".


## [0.0.48] - 2026-08-06

### Fixed

- The **Describe images** model control in Create knowledge base was the agent
  builder's picker rendered in its lesser branch: a bare radio list, with no
  provider/model/key form, no way to say whether the chosen profile can
  authenticate at all, and — on a deployment with no saved profiles — a dead end
  offering no way out of itself (#305).

### Changed

- `ModelProfilePicker`'s `allowAdd` meant two things at once: show the form, and
  offer the bin on every saved row. They are now `allowAdd` and `allowRemove`.
  The knowledge-base dialog gets the first only, so it can create a model and a
  key but cannot destroy an organization-wide profile that agents point at. The
  current-model line, which is what says a profile has no key, renders in both
  shapes.
- The add-model form in that dialog is gated on `connections:manage`; it posts a
  model profile, and a control the caller may not use is not rendered.


## [0.0.47] - 2026-08-06

### Fixed

- The knowledge-base detail page stated the size of the page the table had
  loaded, not the size of the collection. A collection holding fifty-seven
  documents said "20 documents" under its own title, and pressing Load more made
  the number climb, which reads as ingestion happening rather than the page
  correcting itself. The document count now reads the collection's total; the
  vector count says plainly that it counts what is loaded, until everything is
  (#324).
- Nine strings in the knowledge-base pages rendered in English under any locale —
  single words below the guard's threshold, text nodes alone on a line, copy
  behind an `&&`, and a schedule read as "every 30m". Two of them are counts and
  are now ICU plurals (#325).
- Drag-and-drop upload compared a translated string against the browser's
  `DataTransfer` type. Under Polish that comparison could never match, so
  dropping a file would have done nothing.

### Changed

- A Tailwind class list was being stored in `messages/en.json` and read through
  the translator, so a translator opening `pl.json` was asked to translate CSS.


## [0.0.46] - 2026-08-06

### Changed

- A knowledge base is deleted from its own page, not from the card in the list.
  The only control used to be a hover-revealed trash icon sitting on top of a
  whole-card link — the most destructive action on the resource, one mis-aimed
  click away from opening it, on the surface that shows least about what is
  about to be destroyed. It is now in the detail page's actions menu, behind
  `collections:edit`, behind a confirmation naming the collection and its real
  document count, and it is not offered for the default collection, which the
  server refuses (#303).
- The three `window.confirm` calls in the knowledge-base pages are proper
  confirmation dialogs with translated copy. A raw `confirm()` argument is
  hardcoded English the i18n guard cannot see.

### Fixed

- Both delete dialogs now disable while the request is in flight. A double-click
  sent a second DELETE and toasted a 404 over a removal that had worked.


## [0.0.45] - 2026-08-06

### Fixed

- A collection could be named after a model table. `_table("documents")` derives
  `rag_documents`, which is the table tracking every organization's ingested
  documents, so `GET /rag/collections/documents/info` returned every
  organization's document count and the delete path issued a `DROP TABLE`
  against it. Nothing refused the name, and `documents` was the *default*
  collection name, so the collision sat on the documented first-run path. Both
  the store and `KnowledgeBaseService.create` now refuse a name that collides
  with a declared model table (#345).

### Changed

- The default collection name is now `default`, one constant shared by the four
  `rag-*` commands and two schemas, pinned by a test that fails if it is ever
  set to a model table's name. `RAGSettings.collection_name` was read nowhere
  and is deleted.


## [0.0.44] - 2026-08-06

### Fixed

- `PgVectorStore.list_collections()` reported a collection called `documents`
  that does not exist. It matched every table by name prefix, and `rag_documents`
  — the model table tracking ingested documents — matched. The listing has held
  that phantom on every deployment since the table existed, and `rag-stats`
  reported the row count of that tracking table as a vector count. Collection
  membership is now decided by `is_runtime_vector_table`, the same predicate
  alembic uses, so the two answer from one source (#339).
- The prefix match also treated `_` as a SQL wildcard, so a table named
  `ragXfoo` listed as a collection called `Xfoo`.


## [0.0.43] - 2026-08-06

### Fixed

- Document ingestion ignored the collection's own embedding key and model. The
  worker built its vector store with no resolver, so the collection's
  `embedding_secret_id` — validated and stored when the collection was created —
  was never read. On a deployment with no `OPENROUTER_API_KEY` this crashed with
  advice to set one; where both were set it was worse than a crash, billing the
  deployment's account while the UI said the organization's key paid. The
  collection's recorded model was ignored the same way, so a collection could be
  indexed by one model and searched by another (#306).
- The three ways key resolution can silently fall back to the deployment key —
  a missing secret row, an unseal failure, the wrong kind — now reach the flow
  log the operator reads, and the error names the collection and which key it
  tried.

### Changed

- `resolver` is now required on `PgVectorStore` rather than defaulting to `None`.
  Five call sites passed it and one forgot; the default is what made forgetting
  silent.


## [0.0.42] - 2026-08-06

### Fixed

- `make db-check` failed on any database that had ingested a document. Alembic
  compared the models against the live schema and saw the per-collection vector
  tables the RAG store creates at runtime, which no migration declares, so it
  reported drift that no migration could ever resolve (#288).

### Added

- `app/db/vector_tables.py` — `is_runtime_vector_table`, one predicate for
  "is this table a runtime vector table rather than a declared model", read from
  `Base.metadata` rather than from a name pattern.


## [0.0.41] - 2026-08-06

### Fixed

- The local supervisor replaced a worker that had died but ignored one that was
  alive and not answering — deadlocked on a lock, spinning, or blocked on a
  socket that never replies. Such a worker has no exit code, so the supervisor
  saw a healthy child and did nothing while the container served no requests.
  The worker now stamps a monotonic beat from uvicorn's `callback_notify`, and a
  worker silent across two consecutive polls is replaced (#336).

### Added

- `RELOAD_WEDGED_AFTER` — how long a worker may go without running its event
  loop before it is treated as wedged. Set it to `0` under a debugger.


## [0.0.40] - 2026-08-06

### Fixed

- When the kernel killed the reloader's worker in the local stack — an OOM kill
  being the realistic way — nothing reaped it and nothing replaced it. PID 1
  stayed alive, so the container reported `Up`, Docker's restart policy never
  fired, and every request timed out with no log line because the process that
  would have written it was gone. A supervisor now replaces a worker that dies,
  the way uvicorn already does on the `--workers` path (#308).

### Added

- `backend/cli/reload_supervisor.py`, a dedicated entrypoint. It deliberately
  does not import the application: routing PID 1 through `cli.commands` cost
  464 MB against 28 MB, which is the whole application inside the one process
  whose job is to survive an OOM kill.


## [0.0.39] - 2026-08-06

### Fixed

- `prefect-runner` had never once passed a health check and never could. It runs
  the backend image, which carried a `HEALTHCHECK` written for the API, and the
  runner serves no HTTP. A status that is red unconditionally is not a status: a
  dead runner looked exactly like a live one, and nothing could depend on it
  becoming healthy. The runner now serves Prefect's own `/health` on 8080 and is
  probed against it (#310).
- The API's own probe passed on a 500 — it fetched the health endpoint and
  ignored the status. It now raises for status, with a 30s start period.

### Changed

- The `HEALTHCHECK` moved out of `backend/Dockerfile` and into the `app` and
  `prefect-runner` service definitions in all three compose files. An image with
  two consumers should not assert what only one of them can satisfy.


## [0.0.38] - 2026-08-06

### Fixed

- A domain exception carrying a `UUID` in its `details` was delivered as a bodiless
  500 instead of the refusal it described. `JSONResponse` serializes with plain
  `json.dumps`, which cannot encode a `UUID`, so the exception handler raised on
  the way out — after it had already logged the refusal, which is why the log and
  the response disagreed. A browser session kept across a database reset hit this
  on every `GET /api/v1/auth/me`. All three response-building handlers now encode
  `details` through `jsonable_encoder` (#307).
- The capability registry echoed a rejected configuration back to the caller in a
  400, unlike the identical call one module over.

### Changed

- `.claude/rules/exceptions-security.md` showed `details={"user_id": str(user_id)}`,
  which contradicted both the code and `architecture.md`. Domain exceptions pass
  the value; the encoder handles it. The one exception, money, says why.


## [0.0.37] - 2026-08-06

### Fixed

- The `ai-review` workflow concluded `success` when it had produced no review at
  all, and posted "the reviewer did not produce a result" — a sentence that reads
  like a verdict on the diff. Eleven pull requests merged unreviewed before anyone
  noticed. A run is now classified `reviewed`, `declined` or `broken`; `broken`
  fails the job and the comment says the reviewer failed, carrying what Codex
  printed. A cancelled run no longer reports the reviewer as dead, and a broken
  re-run no longer deletes the previous run's inline findings (#311).

The cause of the Codex failure itself is an enforced spend limit on the OpenAI
project, recorded on #311. The `pull_request` trigger stays off until that is
lifted.


## [0.0.36] - 2026-08-06

### Fixed

- The end-to-end suite's `[seed]` project asserted the colleague's membership
  with a single read. When it lost, Playwright skipped everything that depends
  on the fixture and reported the whole suite red having exercised no product
  code at all — three times in one day, on unrelated branches. The step now
  polls the API and, when it does give up, prints what it actually saw
  (#335).

The underlying cause is filed rather than fixed: this backend answers a write
before the transaction commits, so a 2xx says the request was handled and not
that the write is readable (#353).


## [0.0.35] - 2026-08-06

Nothing in this release changes what the product does. It changes what CI costs,
which had reached about 8,900 billed Actions minutes in the first six days of
August across 369 runs at 24.1 minutes each
([#317](https://github.com/vstorm-co/agenticos/issues/317)).

### Changed

- **A push to a branch now cancels that branch's run in flight.** `ci.yml` carried no
  `concurrency` block at all, while `ai-review.yml` and `docs.yml` both did — so every
  push started a fresh matrix and left the previous one running to completion. 75 of
  369 runs were superseded while still in flight, about 1,800 billed minutes, and only
  2 runs in that window were ever `cancelled`. A push to `main` is exempt, and via
  `github.run_id` rather than `cancel-in-progress: false`: `false` means *queue*, and
  GitHub cancels any previously **pending** run in a group when a newer one is queued,
  so a third merge arriving would have cancelled the second and left that commit with
  no CI at all.
- **`test`, `test-frontend` and `e2e` are skipped when the changed paths cannot affect
  them.** A `changes` job decides, and the decision lives in
  `scripts/ci_changed_scope.py` rather than in a glob, so it is testable. It skips a
  suite only when *every* changed path is provably irrelevant to it — an unrecognised
  path runs everything — because the permissive spelling of the same idea would let a
  new directory silently stop a suite, which is a green build with a gate missing from
  it rather than a red one. A required status check is satisfied by `success`,
  `skipped` **or** `neutral`, which is why this is a job-level condition and not a
  `paths:` filter: a filtered-out workflow never posts its checks, and the ruleset
  would wait forever. See [branches](docs/branching.md#a-required-check-may-legitimately-report-skipped).
- **Dependencies are cached, at all seven install sites.** `setup-uv` was called five
  times with no cache, re-resolving and re-downloading all 278 locked packages each
  time; `setup-bun` caches the binary and not the packages; and `e2e` downloaded about
  170 MB of Chromium on every run. All three are keyed on the lockfile that pins them.

### Fixed

- **Four ways the new path gate could have passed on nothing**, all found in review of
  the change that introduced it and all the failure it was built to prevent. A
  `changes` job that *failed* skipped every gated suite without its condition being
  read, and since a skipped required check is a pass and `changes` is not itself a
  required context, one API error would have turned the merge button green over a
  branch where nothing ran — each gated job now carries `!cancelled()`. A rename was
  half-invisible, because `pulls/{n}/files` reports only the path a file arrived at, so
  a module moved out of `backend/` skipped the backend suite; `previous_filename` is
  fed through as well. And the `changes` job declared `pull-requests: read` without
  `contents: read`, which a job-level block *replaces* rather than adds to — working
  only for as long as this repository stays public.

## [0.0.34] - 2026-08-06

### Changed

- **The automated reviewer no longer runs on a pull request**
  ([#311](https://github.com/vstorm-co/agenticos/issues/311)). Every `ai-review` run since
  2026-08-05 evening died about twelve seconds into its Codex step with `codex exited with code 1` —
  the shape of an authentication, quota or entitlement refusal at the first API call rather than a
  model working and failing — and then concluded `success` and posted "No review: the reviewer did
  not produce a result", a sentence that reads like a verdict on the diff. Eleven pull requests
  merged with no automated review before anybody noticed, three of them releases. A reviewer that
  runs and says nothing is worse than one that plainly is not running, so the `pull_request` trigger
  is removed until the Codex failure is understood; `workflow_dispatch` stays, because the fix has
  to be testable against a real pull request. Adding the `ai-review` label now does nothing at all.
  `CLAUDE.md` and [code review](docs/code-review.md) say so, and the latter records that its own
  "a failed run says so" claim is what #311 disproved — making a failed run *report* as a failure is
  the second half of that issue and is not done.

## [0.0.33] - 2026-08-06

### Fixed

- **The Prefect runner no longer starts every queued flow run at once.** `aserve` declares
  `limit: Optional[int] = None` and hands that straight to `Runner(limit=...)`, where `None` means
  *no cap* — while constructing a `Runner` without the argument falls back to Prefect's own default
  of five. Calling `aserve(*deployments)` and saying nothing was therefore the one spelling that
  removed the ceiling entirely. Starting the stack after three days of downtime, the runner found
  the backlog of once-a-minute `rag-sync-check` runs and started 71 `prefect.engine` processes at
  once — each a fresh interpreter importing the whole application, about 120 MB apiece. 6.02 GiB of
  a 7.75 GiB host, and the kernel resolved it by OOM-killing the API container's worker.

### Added

- **`PREFECT_RUNNER_LIMIT`** (default `5`) — how many flow runs execute at once; the rest queue. A
  memory ceiling rather than a throughput dial, and the moment it matters is the restart after
  downtime rather than the steady state. Documented in
  [configuration](docs/configuration.md#background-work-prefect).

## [0.0.32] - 2026-08-06

### Fixed

- **A dynamic specialist's definition is now owned per delegation, not keyed by name**
  ([#292](https://github.com/vstorm-co/agenticos/issues/292)). What each specialist a model
  invented was built from rode a single per-run store keyed by the specialist's name, and the build
  factory overwrote it on a repeat. Two `delegate` calls in one turn with the same name but
  different instructions — which Pydantic AI may run concurrently — both wrote that one entry, so
  whichever delegation opened its panel later stamped the *other* specialist's definition onto its
  `SubagentStarted` frame, and the chat's "Promote to a draft agent" control ([#177](https://github.com/vstorm-co/agenticos/issues/177))
  then carried someone else's instructions and model. Each `delegate` now owns its own copy; the
  name-keyed store is kept only for the `create_agent` specialists a `task` reaches by name, which
  are one-per-name and cannot collide. Narrow and self-inflicted — no cross-tenant or permission
  impact.

## [0.0.31] - 2026-08-06

### Changed

- **The chat "Promote to a draft agent" control now pre-validates the model-chosen name**
  ([#293](https://github.com/vstorm-co/agenticos/issues/293)). A dynamic specialist's name is
  whatever the model chose, and the delegation library allows names the backend `SpecialistSpec`
  rejects — its pattern (`^[a-zA-Z0-9_-]+$`) and its 64-character limit. The chat control passed
  that name straight to the promote request, so an over-long or oddly-punctuated one failed with a
  raw 422 surfaced as an error toast — for a name nobody can edit in chat. The control now disables
  and shows the reason when the name would be refused, the same guard the Builder's specialist
  editor already puts on its own promote button.

## [0.0.30] - 2026-08-06

### Added

- **Promote a specialist to a draft agent — the honest way to keep one**
  ([#177](https://github.com/vstorm-co/agenticos/issues/177)). A dynamic specialist is
  never persisted (keeping one means publishing an agent, a person's action), and an inline
  specialist lives only in its parent's spec — so the only way to keep either was to copy
  its instructions out of a chat log, producing an agent whose provenance nobody can see.
  A **Promote to a draft agent** action now sits on an inline specialist in the Builder's
  delegation section and on a dynamic specialist in the chat delegation panel while the run
  that created it is still on screen. It creates an ordinary **draft** from the specialist's
  instructions, model profile, capabilities, collections and skills, through the same
  `SpecialistSpec.to_agent_spec()` conversion — and stops there: it does not publish, does
  not pin the new agent as a delegate of its parent, and does not remove the inline
  specialist, each of which stays a decision the author makes next with the usual validation
  in front of it. The draft is owned by **the person who promoted it** and subject to the
  usual `AGENTS_EDIT` check — a specialist created inside someone else's run does not become
  their agent. A promoted dynamic specialist publishes without further editing and answers,
  when run, what it answered inside the run it came from.

## [0.0.29] - 2026-08-06

### Fixed

- **An inline specialist's spend under a published delegate now reaches an agent's month**
  ([#228](https://github.com/vstorm-co/agenticos/issues/228)). Spend attribution (0.0.7,
  #192) stamps every `SpendEntry` with the delegation that booked it and reads a
  delegation's cost as its share of the ledger — but an inline specialist gets no
  `agent_runs` row, only published delegates do. So an inline `fact-checker` under a
  published `researcher` booked its spend to its own key, which is in no run row, and the
  innermost stamp meant it was not in the researcher's share either: on a $0.75 run the
  researcher's row read $0.50, and $0.25 reached no agent's month. The organisation total
  was always right (the top-level row is the whole ledger), which is why nothing failed.
  An entry now carries a second attribution — *who spent it* (for the delegation panel's
  own-share `cost_usd`) and *which agent row it bills to* (for the month): an inline
  specialist bills to its nearest published ancestor, so that row is whole again while the
  panel still shows the specialist's own share, with nothing double-counted. Holds through
  an inline specialist nested under another inline specialist, too.

## [0.0.28] - 2026-08-06

### Fixed

- **A `create_agent` specialist created by a nested delegate survives an approval park**
  ([#254](https://github.com/vstorm-co/agenticos/issues/254)). 0.0.20 (#175) carried a
  top-level dynamic specialist across a park — its definition serialised into `paused_state`
  and re-seeded on resume through the same factory — but only at the root. A specialist a
  delegate *one level down* created was still lost when a nested delegation parked and
  resumed: the nested level's registry was rebuilt empty, so `task` answered "unknown
  subagent" for it. The specialist carry now descends the parked tree, so a kept specialist
  at any depth is re-seeded on resume and reachable by name, metered on the run's shared
  ledger exactly as it was the first time. `max_agents` still bounds each level, so a resume
  cannot exceed it by rebuilding.

## [0.0.27] - 2026-08-05

### Fixed

- **A delegation panel closes when an approved resume's continuation raises**
  ([#262](https://github.com/vstorm-co/agenticos/issues/262)). The panel reconciliation
  from 0.0.16 (#173/#250) closed an awaiting panel from the resumed run's status — but only
  when the resume *returned* one. If the continuation raised, `AgentRunnerService._run`
  recorded the run `failed`/`cancelled` and re-raised, so `POST /runs/{id}/resume` returned
  no result, the frontend skipped reconciliation, restored the already-decided approval, and
  left the panel on `awaiting_approval` forever — with a retry then refused because the run
  was already terminal. The resume route now conveys the recorded terminal status even on
  the raising path, without swallowing the failure the caller still sees, so the panel
  reaches `failed`/`cancelled` and the spent approval is not restored.

## [0.0.26] - 2026-08-05

### Added

- **The agent map is interactive, and shows delegates as their own nodes**
  ([#126](https://github.com/vstorm-co/agenticos/issues/126)). The map — the read-only
  picture of "what is this agent, in total?" — now draws delegation. A published delegate
  (pinned, navigable), an inline specialist (no page of its own), and a pin the
  organization no longer has or the caller cannot see (named as unreachable rather than
  dropped) each render as a distinct kind of node — an agent, not a tool — grouped under a
  Delegation heading and edged to the hub by the same measured layout the capabilities use.

  And it is a control now, not a picture: every node is a focusable button, click or
  Enter/Space lights its edge and dims the rest and opens a detail panel, Escape or a click
  away clears it, and a published delegate's panel links through to *that* agent's page — so
  the delegation tree is walkable one hop at a time. It stays read-only (the forms own the
  fields) and keeps pan/zoom. Rendering the tree recursively inline is a deliberate
  follow-up, [#276](https://github.com/vstorm-co/agenticos/issues/276).

## [0.0.25] - 2026-08-05

### Changed

- **`ruff` now lints `alembic/` and the guard scripts, and the dead ignore is live again**
  ([#229](https://github.com/vstorm-co/agenticos/issues/229)). `ruff` was only ever invoked
  on `backend/app` and `backend/tests`, so `backend/alembic/` and the repository-root
  `scripts/` (the three guards — `check_backticks.py`, `check_i18n.py`, `docs_drift.py` —
  that gate every PR) were never linted, and the `per-file-ignores` entry for `alembic/**`
  silenced rules on files ruff never read. `make lint-backend` and both pre-commit ruff
  hooks now run `ruff check . ../scripts` from `backend/`, so all three trees are linted and
  the config stays one definition across make, pre-commit and CI (`test_ci_parity.py` still
  holds). No genuine code defects surfaced: `alembic/` was already clean, and the 21
  findings in `scripts/` are legitimate patterns relaxed with a documented reason (`T201`,
  since printing is the guards' purpose; `S603`/`S607`, the same literal-argv `git`
  invocation already accepted for the migration test). The `alembic/**` ignore is kept and
  now genuinely live, covering autogenerated migrations' downgrade stubs and raw
  `op.execute` SQL. A model edited without a migration — `x == 2` under `alembic/versions/`
  — is now refused where the old command passed it silently.

## [0.0.24] - 2026-08-05

### Fixed

- **A parked run whose spec no longer builds stays resumable**
  ([#176](https://github.com/vstorm-co/agenticos/issues/176)). `resume` flipped the run to
  `RUNNING` before fetching and building its spec, and `claim_parked_run` only claims a run
  in `AWAITING_APPROVAL` — so if the build then failed (a secret a binding named was
  deleted, a model profile removed, a capability dropped in a deploy, an MCP connection
  unshared), the row was stranded in `RUNNING` and could never be resumed again, with a
  person's approval recorded against work that would not continue and nothing reporting it.
  The spec is built first now, and the run is marked `RUNNING` only once the build has
  succeeded; a build that raises leaves the run `AWAITING_APPROVAL`, so the same approval
  can be resumed once whatever the spec named is restored.

## [0.0.23] - 2026-08-05

### Fixed

- **The E2E suite runs beside another checkout's dev server**
  ([#223](https://github.com/vstorm-co/agenticos/issues/223)). `playwright.config.ts`
  hardcoded ports 3000 and 4010, so the suite could not start when a `make dev` or a second
  checkout already held them. The frontend port now derives from `E2E_PORT` (default 3000)
  and the stub model server's from `E2E_STUB_MODEL_PORT` (default 4010), driving `baseURL`,
  both `webServer` URLs, each server's `PORT`, and — the part that has to agree — the stub
  URL the specs write into the model profile the backend dials, so server, specs and backend
  all read one value. Same shape as #189: the value is *derived* from the environment, not
  `setdefault`, so CI is exercised on the new path rather than silently left on the old one.
  The loopback binding is kept, so the host-uvicorn path works and the containerised-backend
  constraint is not falsely implied.

## [0.0.22] - 2026-08-05

### Added

- **A sync delegate can ask the person already waiting on its parent**
  ([#184](https://github.com/vstorm-co/agenticos/issues/184)). An author can turn on
  questions for a delegation, so a **sync** specialist can ask "which currency?" of the
  person waiting on the parent run instead of burying an assumption in its answer —
  answered through the run's own `ask_user` channel, the same one the parent uses. It is
  off by default and gated tightly, because the reasons this was once declined are real:
  a **background** delegation has handed back a task id with nobody waiting, so it is never
  granted the ability (nor is an `auto` delegation, which may become one); a specialist a
  model invented at run time is never granted it either; and a surface with no `ask_user`
  (the API, a channel, a schedule) refuses rather than hangs. The library injects
  `ask_parent` for a caller-supplied delegate only since `subagents-pydantic-ai` 0.2.17,
  which is why this rides on the 0.2.18 floor adopted in 0.0.21.

  Concurrency came with it: two delegate questions in one turn would race the single
  `ask_user` channel, so the channel is serialised — the same class of fix as the approval
  writes in 0.0.17, and for the same reason.

## [0.0.21] - 2026-08-05

### Changed

- **Adopt `subagents-pydantic-ai` 0.2.18, which fixes the general-purpose delegate at the
  source** ([#174](https://github.com/vstorm-co/agenticos/issues/174)). The delegation
  library used to default its `default_model` to a hardcoded string, so a consumer with no
  usable default — which AgenticOS is, on purpose: there is no deployment-wide model — got a
  general-purpose delegate that either failed or, worse, ran one tenant's work on whatever
  provider key happened to sit in the process environment. AgenticOS had already removed the
  switch from its own surface (0.0.7) and refuses a modelless dynamic specialist in
  `DelegatingToolset._refuse_dynamic`; 0.2.18 removes the fallback upstream too, so the
  library now refuses a modelless dynamic call of its own accord rather than compiling an
  unmetered one. The pin moves to `>=0.2.18` and the local comments and the capability
  reference are corrected to describe the removed fallback in the past tense. `#174` closes
  now that AgenticOS is on the fixed version.

## [0.0.20] - 2026-08-05

### Fixed

- **A `create_agent` specialist survives the approval park that interrupts it**
  ([#175](https://github.com/vstorm-co/agenticos/issues/175)). A specialist the model
  writes at run time is documented as lasting for the reply, but it did not survive a
  *second* approval park: the library's dynamic-agent registry belongs to the built agent,
  and a resume rebuilds the agent fresh, so `task` answered "unknown subagent" for a
  specialist the model was told it could keep. The specialist's definition — a name,
  instructions, a model — is now carried in the run's `paused_state` alongside the spend,
  timings and approval rows already kept there, and a resumed turn re-seeds the registry
  through the same factory, so the specialist arrives with the run's shared budget guard
  and approval channel exactly as it did the first time. `max_agents` still bounds how many
  one run may keep, so a resume cannot exceed it by rebuilding. This survives within one
  run; a dynamic specialist is still never persisted across runs — keeping one past its run
  means promoting it to a published agent, which is a person's action.

## [0.0.19] - 2026-08-05

### Added

- **An offline audit of the skill bindings a published version can no longer reach**
  ([#186](https://github.com/vstorm-co/agenticos/issues/186)). Publish-time validation
  (0.0.8, #179) stops a *new* version binding a skill its publisher cannot see, but a
  version published before that check keeps loading whatever its spec named — so a
  published agent may be reading another member's private skill right now, and nothing
  reported it. `agenticos cmd audit-skill-bindings` sweeps every **runnable** published
  version — not just each agent's current pointer, but versions a non-terminal run will
  resume on, reached through the delegation pin-closure — and names the agent, the version,
  the skill and the publisher for each binding that publisher could not reach today.

  Two edges it gets right, because an audit that cries wolf is one an operator learns to
  ignore: the pin-closure honours `max_depth`, so a binding only an unreachable grandchild
  holds is not flagged; and a disabled skill, or a delegate whose agent has been archived,
  is dropped rather than reported, since neither can actually load. A version whose
  publisher has since been **deleted** is a third answer, not "reachable" or not — the
  report says so, because `published_by_user_id` is `SET NULL` and an operator needs to
  know the difference. It **reports**, never unbinds: taking a skill off a published
  version would change what a published agent does without anyone deciding, which is the
  opposite of what publishing means here.

## [0.0.18] - 2026-08-05

### Fixed

- **A run count is an ICU plural, and the guard that missed it now catches the shape**
  ([#199](https://github.com/vstorm-co/agenticos/issues/199)). A run count was built as
  `"{n} runs"` — a plural only English forms that way — and `scripts/check_i18n.py`, the
  gate whose whole job is to refuse exactly that, passed over it. Both halves are fixed:
  the count is now `{count, plural, =1 {1 run} other {# runs}}` with the component passing
  `count`, and the guard is closed so the next English-only plural is refused rather than
  merged. A guard verified only by a green suite is a guard nobody has tested, so the
  change writes the offending shape into a fixture and confirms the script rejects it.

## [0.0.17] - 2026-08-05

### Fixed

- **Two gated tool calls in one model step no longer race the request's session**
  ([#169](https://github.com/vstorm-co/agenticos/issues/169)). A gated tool call writes an
  approval row, and pydantic-ai runs the tool calls from one model response
  *concurrently* — so an agent with two gated tools, answering one step with both, hit
  `db.add` + `flush` on the request's shared `AsyncSession` from two coroutines at once,
  and `AsyncSession` is not concurrency-safe: the damage reaches the parent run row and the
  conversation, not just the approval. Delegation widened the window, since a sync delegate
  keeps the parent's channel. The approval rows are now queued during the run and written
  once when it parks — the shape delegation already took for its child run rows — so nothing
  writes to the session mid-run. A run whose model emits two gated calls in one step parks
  once naming both, with two rows of distinct ids and a session still usable for the
  terminal write.

  Two follow-ups the write path surfaced, both fixed here. A delegate **deleted** between
  the park and the deferred write no longer breaks the park: the write first locks the
  delegates still present, and a parked call whose delegate is gone is written with a null
  `subagent_agent_id` (the `SET NULL` foreign key) rather than a reference that would fail
  the insert and roll the parked run back — the approval survives and a person can still
  decide it; only the delegate attribution, which no longer exists, is dropped. And the
  lock that holds the surviving delegates takes `FOR KEY SHARE` rather than
  `FOR NO KEY UPDATE` (`with_for_update(read=True, key_share=True)`), so it blocks a
  concurrent delete without also blocking an ordinary agent update.

## [0.0.16] - 2026-08-05

### Fixed

- **A delegation panel reaches a terminal state when its delegate parked on an approval**
  ([#173](https://github.com/vstorm-co/agenticos/issues/173)). When a sync delegation
  parked for a human approval in web chat, its panel showed the delegate as still working
  and stayed there — because `POST /runs/{id}/resume` runs over HTTP with no
  `subagent_events` sink, so no `subagent_complete` frame ever reached the WebSocket
  reducer, and the panel sat on `awaiting_approval` forever after the approval was granted.
  Web-chat resume doesn't stream, so the panel is now reconciled from the HTTP answer: the
  resumed run's own status is applied to every panel still awaiting — `completed`,
  `failed`/`budget_exceeded`→failed, `cancelled` — while a resume that parks *again* is
  left waiting, preserving the continuation case. Streamed text is kept; cost and tokens
  stay null rather than invented, since the frame that carries them never arrived. This
  covers a resume that **returns** a status; a resume whose continuation itself raises
  returns no result and still leaves the panel waiting, tracked as
  [#262](https://github.com/vstorm-co/agenticos/issues/262).

## [0.0.15] - 2026-08-05

### Fixed

- **A sync-only delegating agent is no longer offered the background-task tools**
  ([#185](https://github.com/vstorm-co/agenticos/issues/185)). An agent configured
  `mode: "sync"` can never have a background delegation, yet its model was still offered
  the six tools that only make sense for one — `check_task`, `wait_tasks`,
  `list_active_tasks`, `send_message_to_subagent`, and both cancels. Six tool descriptions
  in every turn's context for actions that cannot happen, and tool descriptions are the
  strongest prompt surface in this product. This is the same defect class as
  [#182](https://github.com/vstorm-co/agenticos/issues/182) (0.0.8) and extends its
  mechanism: the offered set is now computed per run. The six tools are withheld only from
  an agent that can never reach a background delegation — mode `sync`, no delegate whose
  `preferred_mode` is `async` or `auto`, and dynamic specialists off; anything that could
  still produce a background delegation (an `auto` agent, or an `auto`-override on a
  delegate, or an enabled dynamic-specialist path) keeps all of them, since the model
  decides per delegation there. A dedicated test pins the exact tool set each of those
  configurations is offered; the capability drift table is unchanged and does not itself
  catch this, since its widest fixture is background-capable by construction.

## [0.0.14] - 2026-08-05

### Changed

- **`alembic check` is a usable gate again**
  ([#183](https://github.com/vstorm-co/agenticos/issues/183)). It had failed on `main`
  for reasons unrelated to any change under test — index-naming drift from early
  migrations that the models and the migrations disagreed about — so the one command that
  would catch "somebody edited a model and forgot the migration" could not be run, and it
  hid real drift behind noise a reader had to filter by hand. The drift is resolved (the
  models and migrations now agree on the index names), and `alembic check` is wired into
  both `make check` and CI, on both sides of `tests/test_ci_parity.py`, so it stays green
  rather than rotting again. This is the fourth check to have existed and not run — after
  `make check` equalling CI (#143), spelling over the tree (#188) and the CodeQL config
  (#220) — and, like those, the value is in the check running at all.

## [0.0.13] - 2026-08-05

### Fixed

- **`bootstrap` ensures the model profile it names, rather than adopting any it finds**
  ([#172](https://github.com/vstorm-co/agenticos/issues/172)). On a database that had
  been used before, `make platform-bootstrap` adopted whatever model profile already
  existed instead of ensuring the one it was told to create — so the agent it published
  ran on a profile nobody asked for, and several E2E specs that assume the named profile
  failed on any database not freshly created. It now ensures the profile it names,
  creating it when absent and matching by name when present, so a second bootstrap is
  idempotent rather than dependent on what the database happened to hold.

## [0.0.12] - 2026-08-05

### Fixed

- **A delegated run's recorded time span survives an approval park**
  ([#191](https://github.com/vstorm-co/agenticos/issues/191)). A delegated `agent_runs`
  row reads its span from the library's `TaskHandle`, which is correct for a single-turn
  delegation — but one that parks on an approval and resumes runs in two processes, and
  the resume rebuilds a fresh handle stamped at the *resume*, so the row began when the
  person answered and dropped the entire pre-park segment. The earliest start is now
  carried across the park the way spend is (0.0.8, #180): `ParkedDelegation` holds it,
  `paused_state` serialises it, and the resumed turn folds it back in — the span is the
  first segment's start and the last segment's end, and unlike cost the segments are not
  summed. A pre-task refusal, which finds no handle, still writes no row at all.

### Changed

- **Run-history routes read through the service, not the repository**
  ([#197](https://github.com/vstorm-co/agenticos/issues/197)). A route reaching
  `agent_run_repo` directly is one of this codebase's named hard boundaries, and it was
  crossed here — which is not merely stylistic: a route that reaches the repository
  bypasses wherever the service puts the tenant scope, so the next filter added to the
  service is one a hand-written route keeps its own answer to. `list_runs` now scopes to
  the caller's organization inside `AgentRunnerService`, the one tenant boundary the rest
  of run history already reads through, and the delegated-run parameters added in 0.0.11
  (`parent_run_id`, `include_delegations`) thread through it rather than sitting in the
  route.

## [0.0.11] - 2026-08-05

### Fixed

- **Run history can tell a delegated run from one a person started**
  ([#181](https://github.com/vstorm-co/agenticos/issues/181)). The columns
  (`parent_run_id`, `subagent_task_id`) had existed since delegation landed and nothing
  read them, so a fan-out turn listed as several independent runs and a page that summed a
  column double-counted every delegation — a parent's cost already contains its children's.
  `AgentRunRead` now carries both, and withholds the delegation handle whenever the parent
  is gone (a foreign key can only null its own column, so `subagent_task_id` outlives the
  delete that nulls `parent_run_id`); `list_runs` filters `parent_run_id IS NULL` for the
  history list, and answers the run-detail query — "what did this run delegate" — by
  `parent_run_id`, which is the lookup the migration's index was speculative weight for
  until it had one.

  A delegated run is **badged** in the table and reachable from its chat panel, so the
  fan-out reads as one tree rather than a list of strangers. The monthly sums keep the
  existing `(organization_id, started_at)` index, with the null test applied to rows it
  already found.

## [0.0.10] - 2026-08-05

### Fixed

- **The E2E seed no longer depends on a product bug to pass**
  ([#132](https://github.com/vstorm-co/agenticos/issues/132)). Five sites created a row
  through a dialog and then asserted it was on screen, with no wait on the write that put
  it there; four flaked, and three branches paid a diagnosis for it in one day. Two causes,
  both now removed from the test's path. An open Radix dialog takes the rest of the page
  out of the accessibility tree, so `getByRole` resolved to nothing while the dialog was up
  and the assertion reported `element(s) not found` for a refusal it never looked at — a
  shared `submitDialog` waits on the write's own network response instead, and through the
  client's transparent 401 retry so it matches the request that settled rather than the one
  that was retried. And a **fixture** step now asserts through the API, never on the row
  appearing, because the refetch after a write is sometimes answered the pre-write list —
  which is a real product bug ([#230](https://github.com/vstorm-co/agenticos/issues/230)),
  left open, not a broken fixture.

  A failing `[setup]` or `[seed]` step is a Playwright *project dependency*, so its failure
  skips every product spec — the log reads "1 failed, 7 passed, 17 did not run" and looks
  like a product regression. `e2e/fixture-reporter.ts` now prints a banner saying exactly
  that, so the next reader does not spend the diagnosis a fourth time.

## [0.0.9] - 2026-08-05

### Fixed

- **Five WebSocket frames the frontend declared but no backend surface sends**
  ([#195](https://github.com/vstorm-co/agenticos/issues/195)). `use-chat.ts` and
  `WSEventType` named `llm_started`, `llm_completed`, `todo_event`, `context_usage` and
  `context_compacted` — two with live `case` arms and a test asserting a dead branch
  behaves. That is [#144](https://github.com/vstorm-co/agenticos/issues/144) in the
  opposite direction: #144 was the frontend matching tool names the backend had stopped
  sending; this is frames it never started. With `app/services/agent_session.py` now fully
  covered and in the gate (0.0.8, #165), the set of frames a surface actually emits is
  knowable exactly — none of the five is among them, on the dashboard socket, the channel
  surface or the embed. The union members, the `case` arms, the payload interfaces and the
  test for the dead branch are gone, along with two per-event interfaces whose field names
  disagreed with the wire (`TextDeltaEvent.data.delta` for the wire's `content`,
  `ToolResultEvent.tool_name`/`result` for `tool_call_id`/`content`).

## [0.0.8] - 2026-08-05

Everything that landed after delegation and before the next feature: the branches that
were stacked behind it, plus two more the same work surfaced. Nearly all of it is a defect
delegation created or uncovered, and several are about a check that reported green while
the thing it checked went unchecked.

No schema change, `SPEC_VERSION` unchanged at **7**.

### Fixed

- **A delegation's recorded cost is its own, not the run around it**
  ([#180](https://github.com/vstorm-co/agenticos/issues/180)). Cost was measured as the
  growth of the run's shared ledger between the delegation starting and being settled — and
  a **background** delegation is settled when it is next *polled*, which is arbitrarily
  later than it finished. So a delegate that spent $0.01 while the parent went on to spend
  $0.50 was recorded at **$0.51**, on its own run row, in its monthly total and in the
  delegation panel.

  Every `SpendEntry` now carries the delegation that booked it, and a delegation's cost is
  its share of the ledger rather than a window over it. That also fixes the second half:
  a mid-tree delegate no longer counts what its own delegates spent.

  `has_unpriced_models` travels with the share and survives an approval park, so a row
  cannot claim a precise cost for a delegation that had an unpriced request before the
  approval.

- **A cancelled run is recorded cancelled, and the row survives**
  ([#171](https://github.com/vstorm-co/agenticos/issues/171)). `_run` caught
  `BudgetExceeded` and `Exception` but not `CancelledError`, which derives from
  `BaseException` — so a cancel passed straight through with the status left at its initial
  `FAILED`, and because a propagating `BaseException` skips the session's auto-commit, even
  that write rolled back and the row stayed `RUNNING` forever. It now records
  `CANCELLED`, commits explicitly, and keeps the tokens already spent — the streaming
  surface had this right and said so in a comment the non-streaming path did not follow.
  Delegation reaches this path too, so a cancelled delegation now keeps its cost rather
  than losing it.

- **`skill_ids` is validated at publish, at both levels**
  ([#179](https://github.com/vstorm-co/agenticos/issues/179)). It was the one reference a
  spec could make that publish never checked — and skills carry grants that nothing
  enforced, so a publisher whose role gives `SKILLS_VIEW: Scope.SHARED` could bind another
  member's **private** skill by UUID and every runner of that agent then read its body.
  Refused now, with the same deliberately indistinguishable "not found" wording the
  collection check uses, so ids stay unprobeable. Versions published *before* the check are
  a separate problem, tracked as [#186](https://github.com/vstorm-co/agenticos/issues/186).

- **A delegation tool nothing could reach is no longer offered**
  ([#182](https://github.com/vstorm-co/agenticos/issues/182)). `answer_subagent` exists so a
  parent can answer a question its delegate asked, and no delegate here can ask one — the
  library injects `ask_parent` for neither a configured delegate nor an autonomous
  specialist. So it was a tool description in every delegating agent's context, on every
  turn, for an action that cannot happen; tool descriptions are the strongest prompt surface
  in this product.

  It stays **declared** — a tool absent from a capability's `tools=` can be neither gated nor
  renamed, and that half of the failure is silent — and the drift test now subtracts an
  explicit table rather than skipping the capability. Seven tools are offered, nine under
  `allow_dynamic`, ten declared.

### Changed

- **The chat wire format is behind the coverage gate at 100%**
  ([#165](https://github.com/vstorm-co/agenticos/issues/165)). `app/services/agent_session.py`
  decides every frame the dashboard WebSocket sends and every frame it accepts, and it was
  in **neither** the coverage nor the `ty` include list — 63% covered, with `process_message`
  and both terminal `complete` frames untested. Every surface reads this format, so a frame
  renamed here is a frontend branch that silently stops matching, which is
  [#144](https://github.com/vstorm-co/agenticos/issues/144) exactly.

  Now 100% of 194 statements and 72 branches, in both lists, with 56 tests that assert the
  frame that reached the socket rather than that a method was called. The author
  mutation-tested it — 19 mutations, every frame name renamed, both terminal flags flipped,
  the disconnect re-raise swallowed — and all 19 were caught, because 100% coverage is a
  claim about lines executed and not about tests that would notice.

  Two dead branches came out with it, one of which would have silently dropped the frame
  carrying a run's answer had it ever been reachable.

- **CodeQL's false positives no longer block a merge by hand**
  ([#220](https://github.com/vstorm-co/agenticos/issues/220)). `github-code-quality` posts
  each alert as a review thread, and the ruleset requires every thread resolved — so one
  idiomatic pattern (`py/ineffectual-statement` on a bare `await <task>`, which suspends and
  re-raises and is the whole point of the statement) cost eight hand-written replies on a
  single pull request, with no `.github/codeql/` config in the repository to tune it. There
  is one now, suppressing only what is demonstrably wrong for this codebase's idioms and
  leaving everything else reporting — the inverse of #188 and #203, which were checks looking
  at too little. `docs/code-review.md` now documents the CodeQL half: how alerts arrive, that
  they gate through the ruleset, and where the config lives.

## [0.0.7] - 2026-08-05

**Delegation.** An agent can hand work to named specialists instead of carrying every
intermediate result in one context — and three checks that existed and did not run were
made to run, which is how two of the defects below were found.

`SPEC_VERSION` is unchanged at **7**: every field delegation adds is optional with a
default, so a spec stored before it reads unchanged. Two migrations,
`0007_delegated_runs` and `0008_approval_delegate`, both additive and both reversible.

### Added

- **Delegation** ([#40](https://github.com/vstorm-co/agenticos/issues/40)). Two kinds, and
  the difference is deliberately visible rather than smoothed over:

  - a **delegate** is a published agent **pinned to a version** — permission-checked at
    publish, with its own capabilities, model and collections. A pin whose version is gone
    fails the run and names the delegate; never a quiet fall back to the current version,
    because the point of pinning is that nothing changes without somebody deciding.
  - an **inline specialist** carries its own bindings but is **not versioned**: nothing can
    reference it, and editing the parent changes it.

  What makes something an agent here is versioning, a permission check at publish, its own
  capabilities, and being metered and capped. A specialist has three of the four, and the
  one it lacks is the version — which is the whole design, and why there is one spec type,
  one validator and one builder used recursively rather than a second agent format.

  A delegation streams into its own collapsible panel per task, so a fan-out is legible
  rather than a quiet gap in the transcript; a gated tool inside a delegate parks the run
  and **resumes in place** rather than re-running the delegation; `sync`, `async` and `auto`
  modes with the task-lifecycle tools; and a model may invent a specialist at run time
  behind `allow_dynamic`, built through the same `build_agent` everything else goes through
  so its requests are priced and counted.

  Cost is the part worth reading twice. One run has **one spend ledger**, and every delegate
  records into it — which is what makes the parent's cap see a delegation's spend before its
  next model request, at precisely the moment delegation multiplies what a turn can cost. So
  the caps that bind inside a delegation are the parent's. A delegation to a published agent
  also gets an `agent_runs` row of its own carrying `parent_run_id`, and the two monthly
  questions want opposite arithmetic: what the organization owes excludes child rows, what
  *one agent* cost includes them.

### Fixed

- **A delegate's own knowledge collections never reached the running delegate**
  ([#166](https://github.com/vstorm-co/agenticos/issues/166)). The delegation library runs a
  child on `clone_for_subagent` of the *parent's* deps, so the deps our factory built for it
  — collections and all — were discarded before its first request. A delegate configured
  with a collection resolved it, never saw it, and answered "No active knowledge bases
  selected" to every search while looking correctly configured.

- **Three spend aggregates double-counted a delegated run**
  ([#170](https://github.com/vstorm-co/agenticos/issues/170)), and one of them was emailed
  as the organization's bill. On a $1.00 run of which $0.40 was a delegate, the bill read
  $1.00 and three breakdowns read $1.40 — with the delegate's $0.40 appearing under two
  vendors at once.

- **The liveness probe reported version `1.0.0` from every deployment**, however many
  releases it was behind. `GET /api/v1/health/live` read
  `getattr(settings, "VERSION", "1.0.0")` against a setting that has never existed, so the
  fallback was the only answer it ever gave — and the `getattr` is what made it silent
  rather than an `AttributeError` on the first request. It now reports `app.__version__`,
  the same source OpenAPI and the CLI already read.

  Found by the automated reviewer on this release's own pull request, which is the right
  place for it: the one claim a release makes is that the version is the same everywhere.
  The test that should have caught it is named `test_liveness_probe_reports_the_build` and
  asserted the status and the environment — everything except the build.

- **Every integration run gets a database of its own**
  ([#189](https://github.com/vstorm-co/agenticos/issues/189)). `tests/integration/conftest.py`
  called `drop_all` against a fixed database name, so two suites at once dropped each
  other's tables — two runs of the same commit produced *different* failure sets, which is
  the signature of a race rather than a bug. Four people lost time to it in one day. The
  name now carries the pytest process id, created and dropped by the fixture; both safety
  rails are kept and one added.

### Changed

- **`make check` now runs every job CI runs**
  ([#143](https://github.com/vstorm-co/agenticos/issues/143)). It was documented as "what CI
  runs" and ran about half: `bun run build`, `pip-audit` and `mkdocs --strict` had no local
  equivalent at all, and eslint, prettier and `tsc` sat outside `make lint`, so it passed on
  a branch with a type error in a `.tsx`. One divergence ran the other way and is the
  sharper one — the i18n check was local-only, so a pull request could merge an
  untranslated string in a product whose frontend rules lean on that script.

  Fixed structurally rather than by copying commands: the workflow calls the Makefile's
  targets, and `backend/tests/test_ci_parity.py` asserts both directions, so a job added to
  one and not the other fails the suite.

- **Spelling is checked over the tree, not over the files a commit happens to touch**
  ([#188](https://github.com/vstorm-co/agenticos/issues/188)). One misspelling was sitting
  on `main`, waiting for whoever next opened that file for an unrelated reason. Exactly one
  existed once the scope was right, verified two ways — the per-file scope had not
  accumulated a backlog, it was hiding one word and would have gone on hiding the next.
  `.codespellrc` now records that omitting the `en-GB_to_en-US` dictionary is deliberate:
  this repository writes "behaviour" on purpose.

## [0.0.6] - 2026-08-04

Dependencies only. No behaviour change, no schema change, `SPEC_VERSION` unchanged
at 7 — this is here so the version literals and the lockfiles move together rather
than drifting until somebody notices.

### Changed

- **TypeScript 5.9.3 → 6.0.3** (dev). A major, so it was checked rather than
  assumed: `tsc --noEmit`, `eslint --max-warnings 0`, the coverage gate and
  `next build` all pass with no source change.

  Dependabot bumped `frontend/package.json` and left `bun.lock` alone, which two CI
  jobs would have refused — they run `bun install --frozen-lockfile`, and that fails
  outright when the manifest and the lock disagree. The lock is updated here, so the
  next such bump should be checked for the same omission.

- **ruff 0.15.0 → 0.16.1** (dev). Ruff is the formatter as well as the linter, so a
  new rule or a changed format would have turned `make lint` red *after* the merge
  rather than before it. `ruff format --check` reports 476 files already formatted
  and `ruff check` passes, so nothing in the tree needed touching.

- **boto3 1.43.59 → 1.43.62.**

## [0.0.5] - 2026-08-04

**Every sign-in lands on the dashboard**, and a deep link interrupted by the login
form is resumed rather than dropped.

### Changed

- **One post-sign-in destination, decided in one place.** Password sign-in forked
  on `is_app_admin`, the OAuth callback always went to `/dashboard`, and the magic
  link always to `/chat` — three call sites that each decided on their own and
  disagreed, so which door somebody came through decided where they landed.
  `postSignInDestination()` in `src/lib/auth-landing.ts` is now the only answer.

  The default is the same for every role on purpose. What a role may not see is
  handled by not rendering the widget, never by a different landing page — a role
  fork there quietly splits one product into two.

- The mobile tab bar's Home tab targets `/dashboard` for every role, and its unused
  `useAuth` dependency is gone.

### Added

- **`?returnTo=` survives the login round trip.** `AuthGuard` appends the path it
  refused when it sends a visitor to `/login`, and the visitor resumes there after
  signing in instead of being dumped on the dashboard having lost where they were
  going.

  Deliberately not for OAuth: that needs the `state` parameter round trip, and the
  flow is being rewritten separately.

### Security

- **The `returnTo` guard refuses anything off-origin**, so the login form cannot be
  turned into an open redirect. Two checks, both load-bearing: a pattern that
  demands a single leading slash, and an origin comparison after parsing. The
  pattern alone misses control characters, because the URL parser strips tab, LF
  and CR before parsing — so `/<tab>/evil.example` resolves off-origin. The origin
  check alone would accept a bare relative path like `agents`, which resolves
  against wherever the visitor happens to stand.

  Refused values are not sanitised into something safe. A fixed-up open redirect is
  still an open redirect, so anything suspect falls back to the dashboard.

## [0.0.4] - 2026-08-04

**An agent can have a workspace: files, and on a container-backed host a shell.**
`SPEC_VERSION` is unchanged at 7 — `capabilities` is an open list, so adding an id
is additive and every published agent keeps loading.

### Added

- **The `sandbox` capability.** Seven tools — `ls`, `read_file`, `glob`, `grep`,
  `write_file`, `edit_file`, `execute` — over one of two backends. `state` stores a
  JSON document in this database and needs no infrastructure, which is what makes
  the feature real on a default install; `service` runs a container or a cloud
  sandbox on a connection an operator registered.

  `code_execution` stays. The two are not a subset of each other: it computes with
  no infrastructure anywhere, and `state` has no shell at all, so an agent granted
  both computes with one and remembers with the other.

- **`backend` is infrastructure; `session_scope` is a data-sharing policy.**
  Getting the first wrong costs a feature. Getting the second wrong shows one
  person another person's files — so `agent` scope warns at the field, the file
  panel names whose workspace it is, and setting it is recorded in the audit log.

  The spec never names an image, a mount, a network mode or a ceiling. A spec is
  authored in a browser by anyone holding `edit` on an agent, and one that could
  name a container image could name one whose entrypoint mounts the host.

- **Attachments stop being context and become data.** A file used to be parsed and
  pasted into the message, at its full token weight on every turn forever, and a
  50 MB CSV could not be attached at all. With a workspace it is written to
  `/uploads/` and the model gets a reference plus twenty lines. Images go both
  ways under a ceiling: a path is no substitute for looking at a picture, and
  looking at one is no substitute for being able to resize it.

- **Sandbox connections**, with their credentials in the vault — a per-organization
  row rather than a deployment setting, which is what makes two hosts possible and
  what bills a Daytona sandbox to the organization that opened it.

- **Read-only workspace routes and a browser.** Folders, whole-tree search,
  previews and downloads. A container-backed workspace is read off the host volume,
  so a week-old conversation lists its files after its session was reaped.

- **A file panel in chat**, beside the transcript, and a Workspaces page scoped per
  reader — an operator sees the organization's, everybody else sees their own files
  and the shared workspace of an agent they have talked to.

- **`sandboxd` runs beside the app** and is the only service holding the Docker
  socket, which is the whole reason an agent can have a container while this
  application has no Docker access. Never published, its own dashboard off,
  reaching the daemon by supplementary group rather than as root.

### Changed

- **Approval is per tool.** `sandbox` is the first capability that genuinely reads
  *and* writes, and one flag cannot describe it: marking the capability
  side-effecting makes an agent ask permission to list a directory, and not
  marking it lets a write run unattended. `CapabilityToolInfo.side_effecting`
  overrides the capability's answer per tool — additive, `None` defers, every
  existing capability behaves exactly as before.

  Only `execute` is gated. Writing into scratch space deleted with its
  conversation is not the act sending an email is, and an agent that must ask
  before every write cannot do multi-step work at all.

- **The ruleset denies, the platform asks.** The library ships `allow`/`deny`/`ask`,
  and its `ask` is an in-run `await` that dies with the socket, while this
  platform's persists a row, mails somebody and parks the run. So `"ask"` never
  comes from the ruleset, with `ask_fallback="deny"` as the backstop.

- **Requires `pydantic-ai-backend>=0.2.25`**, which fixes three things this
  repository had worked around: a ruleset's per-path rules are enforced by the
  library (and it also filters `grep` and checks a command's path arguments),
  `WorkspaceArchive.read_bytes` serves a file a decode would have ruined, and
  `stop(purge=...)` means the same thing on every backend.

- **Attachment routing moved out of the WebSocket into the chat runner**, because
  where a file goes depends on whether the agent has a workspace and only
  `prepare` knows that. Every surface behaves the same instead of the WebSocket
  owning the only implementation.

### Fixed

- Paths an agent may not touch are refused: credentials (`**/.env`, `**/*.pem`,
  `**/.ssh/**`) and the system tree. A `grep` cannot return a line from one, and a
  command naming one is refused.
- A Daytona sandbox is deleted when its run or its conversation ends. It used to
  be deleted on neither, once per run, on the organization's own cloud account.
- A workspace is keyed on the host it runs on, so moving an agent between
  connections opens a new one instead of reattaching to a row naming the host it
  has left.
- Writes are capped at the call site rather than at the flush. Refusing later
  accepted the write, reported success to the model, and dropped the run's work in
  a `finally` block while the agent kept reasoning about a file that was never
  kept.
- A file too large to store is named and sampled rather than pasted whole — the
  fallback used to run backwards, since a write is only refused for a file too big
  to paste.
- The chat file panel is always reachable, and lists what people attached as well
  as what the agent wrote. It used to appear only once a workspace row had been
  flushed, so it was absent for the whole of a turn parked awaiting approval.
- Approving a parked call shows the resumed answer. `POST /runs/{id}/resume`
  executes the agent and returns its output; the chat discarded it, so an approval
  looked like it had done nothing until the page was reloaded.

### Security

- Every secret at rest goes through the vault, including the sandbox service token
  and a Daytona key. There is no second mechanism.
- A workspace file served inline gets an opaque origin, `nosniff`, a CSP sandbox
  and `filename*` only — `.svg` and `.html` are never inline, because "the agent
  wrote it" is not a trust boundary.
- The address a client asks the platform to probe is validated, so a holder of
  `connections:manage` cannot turn the API container into a fetch proxy for
  anything on its network.
- A user id is hashed rather than sanitised when it keys a workspace. Dropping the
  characters a session id forbids mapped `a.b` and `ab` onto one workspace, which
  is one person reading another's files.

## [0.0.3] — 2026-08-02

A frontend release, and almost all of it is about one thing: what a browser is
still holding when the account or the organization changes underneath it.

### Security

**One tenant's data could reach another tenant's screen, and one account's could
reach another account's.** Nothing here crossed a server-side boundary - every
refusal the backend makes it still made - but the browser kept and re-showed
answers it had already been given, which for a multi-tenant product is the same
outcome by a different route.

- **Uploads went to the wrong organization.** `ingestFile` sent no
  `X-Organization-Id`, and the backend reads a request without it as the
  caller's personal organization - so uploading into a collection whose name
  exists in both wrote the file to the wrong tenant and reported success under
  the right one. The one *write* across the boundary in this list.
- **Switching organization changed a label and nothing else.** Most query keys
  name no organization, so with `staleTime` at five minutes one tenant's agent
  names, knowledge bases, secrets and conversations stayed on screen under
  another's. Everything cached is dropped on a switch now - dropped rather than
  marked stale, and before the paint rather than after it.
- **Signing out left the previous account's data in memory.** The query cache
  and the Zustand stores both survived a sign-out, so the next account signing
  in on the same browser could be served the previous one's conversations,
  agents, and the device names and IP addresses on their profile. Emptied when
  the signed-in account changes, keyed on the account rather than on the act of
  signing in - a password login, an OAuth callback, a magic link and the
  dashboard's own auth check are four different doors, and only one of them was
  covered.
- **A request already in flight could refill what had just been emptied.** A
  conversation's messages, a page of the list, a knowledge base's documents, a
  chat message queued while the socket was down: each now checks the account and
  the organization it started in before writing anything.

### Added

- `apiClient.raw()` — the `Response` without the JSON parse, for downloads and
  previews, so reaching for bytes no longer means giving up the organization
  header, the 401 refresh and `ApiError`.
- `useChanged` — one tested hook for "adjusting state when a prop changes",
  replacing the effects that wrote state after rendering the stale value once.

### Changed

- **`eslint-config-next` 15 → 16**, which turns on the React Compiler's hook
  rules; the frontend broke them in 31 places and no longer does. Server reads
  moved to the query layer where they belonged, and the flat config is imported
  directly - through `FlatCompat` the plugin graph is self-referential and
  ESLint dies serializing it.
- `admin/ratings` fetched its fixed thirty-day summary again for every page of
  results, and rendered a failed half as zeroes beside a full table. Two
  queries, two error states.
- `admin/system` polled health on an interval that kept running in a hidden tab.
- The RAG document list, the ratings page and the admin user drawer rendered a
  502 as "nothing here". They say what happened, and offer a retry.

### Fixed

- `/rag` polled a document's ingestion status exactly once. It armed the next
  poll from the identity of an array React Query deliberately keeps stable, so
  a document stuck at `processing` never updated without a reload.
- The `/rag` sync tab emptied itself on an organization switch and stayed empty
  until the user clicked away and back.
- The sync wizard discarded a half-filled form when a background refetch
  reordered the collection list.
- The admin user drawer vanished instead of closing when its row was deleted.
- "Revoke all others" from the second page of sessions listed the devices it
  had just revoked.
- The agent builder could sit on its skeleton after a rollback to a version
  structurally equal to the current draft.

### Removed

- `MANUAL_STEPS.md`, a generator leftover in which nearly every variable name
  was wrong. `docs/configuration.md` has it correctly, and now has the two
  external click-paths that file was the only place to carry.

### Notes for operators

Nothing to do. No migration, no configuration change, no API change. A signed-in
user is signed out of nothing; the first page load after deploying refetches
more than usual, because a browser holding a cache from before this version
identifies its tenant and starts again.

## [0.0.2] — 2026-08-02

A dependency patch, and the first release cut through the path 0.0.1 built.

### Changed

- `tavily-python` 0.7.26 → 0.7.27, which is what the `web_research` capability
  searches with.

## [0.0.1] — 2026-08-02

First tagged version. The platform is usable end to end — build an agent in the
UI, publish it, run it from chat, an HTTP API, Slack or an embedded widget, with
budgets and approvals applying identically to all of them — and the interfaces
below should be treated as unstable until 0.1.0.

### Added

**The agent model.** An agent is data, not code: instructions, a model profile, a
set of capabilities and a budget, versioned on publish and exportable as YAML into
a client's own git repository. Spec, version, exposure and run are the four nouns
everything else is built from.

**Capabilities** — seven, registered in code and composed by configuration:
knowledge search, skills, web search (DuckDuckGo, native, Tavily, Brave, Exa),
sandboxed Python, charts, reasoning effort, and a clock. Per-tool approval and
per-agent tool renaming key on a stable tool id, so a rename cannot detach an
approval gate.

**MCP** — any Model Context Protocol server by URL, over streamable HTTP or SSE,
with 58 common servers in the picker and full OAuth 2.1 (discovery, dynamic client
registration, PKCE, refresh). Connections are personal or organization-wide; only
the latter can be bound by a published agent.

**Models** — 27 providers, per-organization credentials, fallback on outage, and
self-hosted Ollama or a LiteLLM proxy. Model ids stay free text, with live and
curated pickers, because a provider ships something the morning after any list is
warmed.

**Knowledge and skills** — collections with pgvector retrieval over uploaded
documents, Google Drive and S3; and skills, which are written know-how the agent
loads only when it decides one is relevant.

**Governance** — monthly budgets checked *before* each model request and recorded
even when a run fails, human approval for side-effecting tools, per-agent alerts
with an audience, and an audit trail.

**Permissions** — three layers: the deployment superadmin, an organization role
composed from a permission catalog, and per-row visibility plus grants. Effective
access is `max(role scope, grant)`, so sharing one resource never means promoting
somebody.

**The vault** — envelope encryption for every credential at rest, sealed to the
organization or member that owns it, so a ciphertext moved between tenants cannot
be decrypted. There is deliberately no second mechanism.

**Surfaces** — web chat, HTTP API, Slack, Telegram, Mattermost and embeddable
widgets, all behind one runner.

**Multi-tenancy** — organization isolation enforced by database constraints rather
than by service code alone.

**Dependency freshness as a policy.** FastAPI, Pydantic AI, Logfire and
genai-prices are uncapped and meant to track their newest release — genai-prices
especially, since it *is* the price snapshot budgets are computed from.
`make deps-upgrade` bumps them, a scheduled `framework-freshness` workflow tries
the newest on a Monday and opens an issue when it breaks, and Dependabot opens the
PR. Majors are not held back: delaying one does not avoid the upgrade, it only
makes the eventual jump wider.

**Pre-commit**, covering both halves of the repo: the standard hygiene hooks,
`codespell`, `yamlfmt`, `zizmor` over the workflows, and ruff / ty / prettier /
eslint / tsc. `pre-commit` had been a dependency and `make install` had been
running `pre-commit install` for a while, but there was no config file, so the
installed hook did nothing.

### Fixed

- **Every path that created a user was broken.** The user repository still passed
  `role=` to the model after the column was dropped in `0066`, and SQLAlchemy
  raises on an unmapped keyword — so registration, Google OAuth,
  `agenticos user create` and `agenticos cmd bootstrap` all failed. Bootstrap is
  the command the install instructions open with.
- **`agenticos cmd seed --clear` deleted nothing**, for the same reason: it
  filtered on the dropped `role` column. It now keys on `is_app_admin`.
- **The chat WebSocket 500'd on handshake in local development.**
  `docker-compose.dev.yml` claimed in its header to be identical to
  `docker-compose.yml`, had drifted, and had lost `--ws websockets-sansio` —
  and it was the file `make dev` used.
- **Production ran without a route to the internet.** The only network was marked
  `internal: true`, which blocks egress, so no agent could reach a model provider.
  Split into an internal `data` network for Postgres and Redis and an `edge`
  network for the app.
- **Production ran no background work at all** — no Prefect server or runner, so
  document ingestion and collection syncs never happened and an upload stayed
  unsearchable forever.
- **The test guarding the coverage gate could not run on the interpreter that
  ships.** It used `Path.full_match`, added in Python 3.13, while CI installs
  3.12. `backend/.python-version` now pins 3.12 so local matches.
- **The security CI job never audited anything** — it errored installing
  `pip-audit` outside a virtualenv, with two more argument errors queued behind
  that.
- **Icons and diagrams in the documentation rendered as their own source**, for
  want of `pymdownx.emoji` and a mermaid custom fence.
- **FastAPI 0.141 stopped flattening included routers into `app.routes`**, so
  every route sweep in `tests/api/test_platform_routes.py` silently ran over zero
  routes. Rewritten on the public `iter_route_contexts`. Found by upgrading rather
  than by a Dependabot PR, which is the argument for the freshness workflow.
- **`Agent.updated_at` was typed `string | undefined`** while the API sends
  `null`, which made the honest test for "never edited" a type error.
- **The workflows ran with a broader token than they need** and left the checkout
  credential on disk. Every action is now pinned to a commit SHA,
  `persist-credentials: false` everywhere, `contents: read` by default, and Pages
  write scoped to the one job that deploys.
- **`backend/.pre-commit-config.yaml`** shadowed the repository root and carried a
  `ty` hook that failed on an argument the pinned `ty` does not accept.

### Security

- **A conversation was readable and writable across tenants.** `GET
  /conversations/{id}/messages` returned a full transcript — tool calls and
  their arguments included — for a conversation in another organization, and
  `POST` to the same path appended a turn to it, `role: "assistant"` included,
  which rendered to its owner as the agent's own words. `organization_id` is now
  a required argument on every conversation read and write; a caller that
  genuinely reads across tenants passes an explicit sentinel.
- **The avatar proxy forwarded a path traversal to the backend.** It is the one
  route handler served without a session, so an anonymous caller could drive
  arbitrary `GET`s against the internal API and read the response.
- **A channel bot missing one configuration value stalled the whole API.** The
  Slack and Mattermost supervisors retried a start that returns without
  awaiting, which never yields — so the event loop starved and every request,
  health check included, stopped being answered.
- **Icons are resolved from the directory listing**, not by joining a request
  parameter onto a path, and a symlink out of that directory is refused.

### Added — the toolchain that keeps it honest

- **An automated pull request reviewer** that reads this repository's own rules
  from the base branch rather than a generic checklist. See
  [Code review](docs/code-review.md).
- **`main` is protected by a ruleset** with no bypass actors: pull request
  required, CI green, squash only, no force push. See
  [Branches](docs/branching.md).
- **A weekly freshness job** that upgrades the entire lockfile, transitive
  packages included, runs the suite against it and opens an issue when the
  newest release breaks us.

### Changed

- **One compose file per environment**, with a matching frontend file beside it:
  `docker-compose.yml` (local), `docker-compose-dev.yml` (dev server),
  `docker-compose-prod.yml` (production), each with a `.frontend.yml` sibling.
  `make stage` is kept as an alias for the new `make dev-server`.
- **One long-lived branch.** Work reaches `main` by pull request from a
  short-lived branch, squashed on merge. A `dev` branch existed briefly and was
  removed; see [Branches](docs/branching.md). CI's lint job matches `make lint`,
  and the integration suite refuses to skip when `CI` is set: an unreachable
  database there means the service container failed, and skipping two hundred
  tests to report green is worse than failing.
- **Pydantic AI 2.x** is the agent runtime, and the frontend is on **Next 16**.
- **The documentation is the single copy of how the system works**, with a
  trigger map from code path to page in `CLAUDE.md` and a `Stop` hook
  (`scripts/docs_drift.py`) that names the pages a change owes.

### Removed

- `users.role`, `UserRole`, `User.has_role()`, `RoleChecker`, `CurrentAdmin` and
  `CurrentSuperuser` (`0066`). Authority inside an organization is a membership
  row plus the permission catalog.
- `CHANNEL_ENCRYPTION_KEY` and the deployment-wide Fernet keys (`0038`).
  Everything seals through the vault, bound to an owner.
- `app/agents/assistant.py` and `app/agents/prompts.py`. There is no single agent
  object and no system prompt in code; an agent is assembled per run from the
  capabilities its spec names.
- Conversation-level knowledge-base ids (`0059`). An agent's spec is the only
  thing that decides what it may search.
- `ENV_VARS.md`, superseded by [Configuration](docs/configuration.md).
- `.fastapi-fullstack.json` and the `make upgrade*` template-merge targets. This
  codebase has diverged from the generator past the point where a 3-way merge
  helps.

[Unreleased]: https://github.com/vstorm-co/agenticos/compare/v0.0.32...HEAD
[0.0.32]: https://github.com/vstorm-co/agenticos/compare/v0.0.31...v0.0.32
[0.0.31]: https://github.com/vstorm-co/agenticos/compare/v0.0.30...v0.0.31
[0.0.30]: https://github.com/vstorm-co/agenticos/compare/v0.0.29...v0.0.30
[0.0.29]: https://github.com/vstorm-co/agenticos/compare/v0.0.28...v0.0.29
[0.0.28]: https://github.com/vstorm-co/agenticos/compare/v0.0.27...v0.0.28
[0.0.27]: https://github.com/vstorm-co/agenticos/compare/v0.0.26...v0.0.27
[0.0.26]: https://github.com/vstorm-co/agenticos/compare/v0.0.25...v0.0.26
[0.0.25]: https://github.com/vstorm-co/agenticos/compare/v0.0.24...v0.0.25
[0.0.24]: https://github.com/vstorm-co/agenticos/compare/v0.0.23...v0.0.24
[0.0.23]: https://github.com/vstorm-co/agenticos/compare/v0.0.22...v0.0.23
[0.0.22]: https://github.com/vstorm-co/agenticos/compare/v0.0.21...v0.0.22
[0.0.21]: https://github.com/vstorm-co/agenticos/compare/v0.0.20...v0.0.21
[0.0.20]: https://github.com/vstorm-co/agenticos/compare/v0.0.19...v0.0.20
[0.0.19]: https://github.com/vstorm-co/agenticos/compare/v0.0.18...v0.0.19
[0.0.18]: https://github.com/vstorm-co/agenticos/compare/v0.0.17...v0.0.18
[0.0.17]: https://github.com/vstorm-co/agenticos/compare/v0.0.16...v0.0.17
[0.0.16]: https://github.com/vstorm-co/agenticos/compare/v0.0.15...v0.0.16
[0.0.15]: https://github.com/vstorm-co/agenticos/compare/v0.0.14...v0.0.15
[0.0.14]: https://github.com/vstorm-co/agenticos/compare/v0.0.13...v0.0.14
[0.0.13]: https://github.com/vstorm-co/agenticos/compare/v0.0.12...v0.0.13
[0.0.12]: https://github.com/vstorm-co/agenticos/compare/v0.0.11...v0.0.12
[0.0.11]: https://github.com/vstorm-co/agenticos/compare/v0.0.10...v0.0.11
[0.0.10]: https://github.com/vstorm-co/agenticos/compare/v0.0.9...v0.0.10
[0.0.9]: https://github.com/vstorm-co/agenticos/compare/v0.0.8...v0.0.9
[0.0.8]: https://github.com/vstorm-co/agenticos/compare/v0.0.7...v0.0.8
[0.0.7]: https://github.com/vstorm-co/agenticos/compare/v0.0.6...v0.0.7
[0.0.6]: https://github.com/vstorm-co/agenticos/compare/v0.0.5...v0.0.6
[0.0.5]: https://github.com/vstorm-co/agenticos/compare/v0.0.4...v0.0.5
[0.0.4]: https://github.com/vstorm-co/agenticos/compare/v0.0.3...v0.0.4
[0.0.3]: https://github.com/vstorm-co/agenticos/compare/v0.0.2...v0.0.3
[0.0.2]: https://github.com/vstorm-co/agenticos/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/vstorm-co/agenticos/releases/tag/v0.0.1
