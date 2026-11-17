# Built-in integrations

Personal accounts are connected in **Chat controls → Preferences → Your accounts** under `/chat`, or **Settings → Profile → Your connected accounts**. Organization accounts are connected in **Vault → Connect account**. You can connect several accounts for the same provider. Each Google, Microsoft or Slack product is a separate capability in an agent’s **Toolbox**. These integrations use provider APIs directly; vendor MCP servers, Google Workspace MCP preview and a Microsoft Copilot licence are not required.


## Continue with AgenticOS

The shared **Continue with AgenticOS** option is hidden by default. To request access, email **dev@vstorm.co** with your organization, exact public AgenticOS URL, intended providers and incident contact. Vstorm reviews requests individually; access is not automatic. After approval, configure backend `OAUTH_BRIDGE_URL=https://bridge-agenticos.testapp.ovh` and the issued `OAUTH_BRIDGE_ACCESS_KEY`. Keep the key in server-side secret configuration, never in frontend variables, an agent spec or source control. The option appears only when the key, destination and provider are accepted. **Use your own credentials** remains available without Vstorm approval or a bridge key.

Only OAuth code exchange and refresh pass through the bridge. Tokens are sealed in this deployment's owner-bound Vault; business data goes directly to Google, Microsoft or Slack. The bridge keeps its app credentials and an encryption key in server configuration, with no user-token database. Its encrypted, expiring handoff tickets require PKCE; refresh requires a receipt bound to the token and OAuth app. The bridge operator remains trusted because tokens exist transiently in its memory. Provider verification, distribution and tenant consent policies still apply.

The bridge supports native product capabilities and personal/organization accounts, including several accounts at once. Mirage mounts that require the OAuth application's client secret continue to use your own credentials. Reconnect preserves the original credential source. Changing the configured broker origin requires reconnecting managed accounts; tokens are never forwarded to a different broker.

Bridge access is managed exclusively through the operator's CLI. Keys are bound to one exact deployment origin, approved providers and an expiry; their hashes and enrollment/contact metadata are stored separately from user tokens.

Revocation blocks subsequent starts, callbacks, token exchanges and refreshes, but cannot retract provider access tokens already issued or stop an in-flight provider operation. Revoke the provider grant as well after a suspected compromise. A replacement key requires reconnecting managed accounts. Self-hosted bridge operators issue their own deployment keys. Review the bridge privacy policy, terms and your deployment's policies before connecting; the bridge remains trusted because it handles tokens in memory.


## Set up an account

When using your own credentials, an administrator first opens **Vault → Integrations**, configures the provider app and saves one organization-visible OAuth client. This setup shows the exact callback URL, provider console and permissions. “OAuth client saved” only confirms a stored client; the provider may still require consent or app approval. Missing or multiple clients block account consent with guidance to the administrator. Members then choose apps and sign in from chat or their profile, without configuring the provider console. Read access is the default; write permissions are opt-in.

In **Connect an account**, choose a specific service such as Gmail, Google Calendar, Outlook mail or Excel. Google and Microsoft services each have their own entry and logo. The consent form preselects only that service; you can add other services before signing in. Choosing a service does not grant access until you approve the provider’s consent screen.

Google: create a Cloud project, enable the listed APIs (the wizard supplies a `gcloud services enable` command), configure the consent screen and create a **Web application** OAuth client. Copy the callback exactly and store `google_oauth_app`. Choose Internal only for a Workspace organization that owns the project. External apps in Testing can issue refresh tokens that expire after seven days. A normal API integration does not need an AI-powered-agent client or the hosted MCP APIs.

Microsoft: register an Entra app, choose the supported account types and tenant, add a Web redirect and the displayed delegated Graph permissions, and save `microsoft_oauth_app`. Work/school and personal Microsoft accounts work only where the chosen Graph product supports them; Teams requires work/school accounts. Administrator consent can still be required by the tenant's policy.

Slack: the provider-console button opens a manifest with this deployment's redirect and the supported user scopes. Review the scopes before registering the app; each account's consent still requests only its selected read/write access. Save `slack_oauth_app`. An existing channel-bot app can be reused by adding the redirect and user scopes. Workspace app limits and administrator approval still apply. The **Agents → MCP Server** toggle is needed only for Slack's hosted MCP server.

## Alternatives to OAuth

Choosing an application subject requires edit access to its Vault credential, including for personal accounts. Viewing a shared credential does not authorize impersonation. Personal accounts recheck that edit access before every token exchange.

Google supports a Vault `gcp_service_account`, with a subject for Workspace domain-wide delegation. The Workspace administrator must authorize the displayed scopes. A plain service account accesses only resources shared with it; it does not become a personal Gmail account.

Microsoft supports a Vault `entra_app` client secret and application permissions with administrator consent. Configure the mailbox subject for mail/calendar; Teams requires the subject's directory object ID so mentions can be matched without directory-wide read permission. Excel workbook APIs require delegated OAuth. Graph application permissions do not support normal Teams posting; use delegated OAuth for that operation. Application scopes differ from delegated scopes and the wizard displays the appropriate list.

Microsoft application accounts record only Graph roles returned by the tenant, limited to the selected products. Selecting read-only also blocks writes locally even if Entra granted a broader role. Each renewal checks that the recorded roles remain granted; reconnect after changing consent.

This setup requires a readable Graph role claim in the token returned by the fixed Microsoft token endpoint. Opaque or encrypted application tokens are refused with a delegated OAuth alternative; AgenticOS does not request directory-wide permissions to inspect consent. This claim is configuration metadata, not authentication of a platform user; Microsoft Graph validates the bearer token.

Slack accepts existing `xoxp-` user tokens or `xoxb-` bot tokens. A bot can post as the app, but it cannot use user-only search APIs. Actual granted scopes are checked before each operation. Tokens and service-account keys are sealed in the Vault, never stored in an agent spec.

Before saving a Slack trigger, watch or knowledge source, AgenticOS checks history access for every selected conversation. This verifies the matching public/private channel or direct/group-message scope and membership, without requesting extra directory permissions. Unreadable conversations are refused at setup.

**IMAP** is a separate read-only mail connection using a host, verified TLS port, username, app password and fixed folder. The operator must allow the exact host in `MIRAGE_ALLOWED_HOSTS`. It reuses the installed Mirage mail client. Microsoft 365 basic-auth IMAP is not an alternative to Microsoft OAuth here.

## Choose what an agent can do

Google products: Gmail (search/read, labels, draft/send), Calendar (events and free/busy), Drive (search, metadata, read/upload/copy), Docs, Sheets and Slides (read/create/update). Sheets includes range reads, append and cell updates.

Microsoft products: Outlook mail, Calendar, OneDrive/SharePoint files, Excel and Word documents, and Teams chats/channels. Slack offers search, my mentions, history/threads, channels/users, lookup, posting/replies, DMs and reactions. IMAP offers search and message reads without marking them seen.

Choose **personal** to use the accounts of the person talking to the agent. The capability does not ask its author for user account names. Existing name filters in saved specs remain visible and can be explicitly removed. Personal tools require a private conversation and current organization membership; the agent never borrows another member’s or its publisher’s account.

Choose **organization** and select the accounts the agent may use. Existing specs with one `connection_id` remain valid; `connection_ids` admits several accounts. Publication checks every selected account and its enabled operations. Each operation rechecks the binding author's current access.

The model receives account names and labels before answering. It selects an account with the tool's `account_name` argument and can use several accounts in one request. If the request does not identify an account, it asks before accessing data. Missing access is explained with directions to Chat settings or Vault. Workflow operations also accept `account_name` in their input when several accounts are configured. Adding or reauthorizing an account requires reviewing a routine's sources before that routine may use it.

Each write requires human approval in agent runs, even if a per-tool override requests otherwise. Disable tools individually to remove them. Workflows expose the same operations as `integration.<product>.<operation>` nodes, with the same account and transport checks. Writes are not automatically retried; place an approval node before writes that need human review in a workflow.

File nodes accept base64 content, never a server-local path. Word writes accept a title and paragraphs and create a `.docx`. Uploads/downloads are bounded to 20 MB, JSON to 2 MB and extracted text to 100,000 characters. A failed write may already have reached the provider: inspect the remote result before retrying.

The read-only choice is a local ceiling for OAuth, application and pasted Slack-token accounts. Previously granted provider write scopes do not override it, including Google incremental consent. Reconnect and explicitly enable writes to change that choice.

Publishing an organization binding verifies the scopes of every enabled tool. With a read-only account, disable write tools before publishing or reconnect with write permissions.

## Knowledge, triggers and watches

Drive and SharePoint sources can select the same organization connection instead of a separate credential. OneDrive uses the SharePoint connector with the selected drive/folder. Slack sync indexes only selected channels and their threads. The account is revalidated at every sync; private member accounts are not silently spent by a shared knowledge source.

Connected Drive, SharePoint and Slack readers reacquire the authorized account token before each provider request, so a long sync can renew OAuth credentials without retaining refresh secrets in connector configuration. Revoking the input account grant also stops native trigger polling before opening the token. Microsoft application file triggers identify edits by the configured subject and application ID; their default own-change filter suppresses those edits.

Routine triggers reuse the existing transactional queue, deduplication and approved-source policy. Gmail/Outlook filters, calendar leads and file changes work on native accounts. Slack adds channel messages, mentions and DMs; Teams adds messages and mentions; IMAP adds new mail. Sheets tracks **appended rows** in a selected spreadsheet and sheet, baselining the last occupied row across columns A:ZZ; row insertion/deletion and edits to existing rows are not append events.

A watch selects one personal connection and product, with only a fixed read-only change tool. Enable that product on the agent first. Slack conversations and delegated Teams chats must be selected in the capability. Teams channels use `channel/team-id/channel-id`; an app-only Teams feed with no conversations reads all chats of its configured subject.

Each watch has an independent durable cursor; it advances only after a successful consumed check. New/reset cursors establish a quiet baseline rather than replaying history. Gmail uses history IDs, Outlook and calendars use provider cursors, Slack uses a timestamp per conversation and IMAP uses UIDVALIDITY/UID. Delegated Teams chats use `lastModifiedDateTime`; channel and application feeds use Graph delta. Narrow a source if a bounded read reports too much backlog.

Reconnect from the affected account row to replace credentials in place. The account ID and stable name remain, preserving agent, source and trigger references; its authorization generation changes and existing routines need a source review. Use the same authentication method. Polling errors appear on the account and clear after a successful poll. An inaccessible spreadsheet retains its own cursor while healthy spreadsheets continue. Slack change feeds exclude messages sent by the connected user or bot to prevent reply loops.

See [capabilities](https://vstorm-co.github.io/agenticos/reference/capabilities/), [triggers](https://vstorm-co.github.io/agenticos/triggers/), [governance and watches](https://vstorm-co.github.io/agenticos/governance/#proactive-work) and [MCP](mcp.md) for their existing controls.

Set a label such as Work when connecting; use the same label for each person’s corresponding account.

Native triggers created through the API require `connection_id`. Filter edits recheck the account, permissions and conversation selection. Each distinct Slack/Teams conversation selection keeps its own cursor and only feeds its associated triggers; one selection can contain up to 20 conversations.

## Connect without a browser

IMAP and Odoo can be connected through the HTTP API. Copy the [IMAP payload](assets/setup/imap-account.example.json) or [Odoo payload](assets/setup/odoo-account.example.json) and [curl authentication template](assets/setup/agenticos-auth.example.conf) outside the repository. Replace every example value with the authorized test account and an [AgenticOS access token](api.md). Restrict both local files to the operator (`chmod 600 account.json auth.conf`); never commit filled credentials. The templates contain no working credentials.

Allow the exact IMAP host in backend `MIRAGE_ALLOWED_HOSTS`, or the Odoo host in `ODOO_ALLOWED_HOSTS`, preserving existing entries. IMAP uses verified TLS; Odoo requires HTTPS and version 19+ JSON-2. Run the request against your AgenticOS deployment:

```bash
curl --fail-with-body --config auth.conf --json @account.json \
  https://agenticos.example.com/api/v1/me/connected-accounts/imap
```

For Odoo, change the final path to `/odoo`; the template keeps write access off. For an organization account, use `/api/v1/connected-accounts/imap` or `/odoo` instead; the caller needs `mcp:manage`. Success returns the connection ID, not its credentials. Reconnect in place by adding `connection_id` to the payload. A refused hostname or invalid credential must be repaired before the account is usable. Templates and local tests do not establish a live connection.

### Configure polled routines from the terminal

For an already connected account, `integration-trigger-setup --list` lists the native polling presets from the platform catalog without network access. `--accounts` reads accessible account IDs, ownership and reconnect/polling status from your own instance; it does not contact Google, Microsoft or another provider. Use your personal AgenticOS access token, entered at the hidden prompt or read with `--access-token-file`. The account listing requires `agents:view`; creation checks access to the selected agent and account through the existing API.

```bash
uv run agenticos cmd integration-trigger-setup --list
uv run agenticos cmd integration-trigger-setup --accounts --portal google \
  --base-url https://agenticos.example.com --org ORGANIZATION_UUID
uv run agenticos cmd integration-trigger-setup \
  --portal google --preset inbox_only --agent AGENT_UUID \
  --connection CONNECTION_UUID --prompt-file prompt.txt
```

The last command only prints a JSON request locally, including the prompt; it does not create or run a routine. Replace the UUID placeholders and provide a UTF-8 instructions file. Optional `--filter-file filters.json` supplies a JSON object of preset overrides. Offline preparation validates the request shape, not account availability or source-specific filter semantics. For example, Sheets requires its spreadsheet filter; Slack and Teams require conversation selection where applicable. The server validates those fields on creation.

Add `--apply --base-url https://agenticos.example.com --org ORGANIZATION_UUID` to create the routine **paused**, with source review required before activation. Creation uses a single authenticated request with no automatic retry or agent run. If the outcome is uncertain, inspect existing routines before repeating it. Polling uses existing workers and durable cursors; this command creates no Pub/Sub topic, provider webhook or expiring push subscription, and does not change polling frequency. A missing OAuth connection still requires consent; the terminal command does not bypass it.

## Odoo

Connect Odoo 19+ through JSON-2 with the HTTPS origin, database name and a business user's API key. The operator must list the exact host in `ODOO_ALLOWED_HOSTS`; paths, redirects and custom ports are refused. Odoo Online requires a Custom plan for external API access. Install the business modules you intend to use and restrict the user's Odoo ACLs and record rules. Keys expire: rotate them and reconnect the account. Write access is opt-in and every agent write still needs approval.

Toolbox capabilities cover Contacts, CRM, Sales, Invoicing, Inventory and Projects. Each exposes field inspection, bounded record search/read and explicit create/update tools where supported. Stock levels are read-only; use transfers and stock moves for inventory operations. Tools and workflow nodes use the same account and JSON-2 adapter. Arbitrary models, methods and user-supplied context are not accepted.

Watches and routine triggers read created/modified records in their selected business area. Each model has an independent `(write_date, id)` cursor; the first check establishes a quiet baseline. Subsequent checks consume at most 100 records per model and retain the remaining backlog. Deletions are not events. Odoo timestamps have second precision, so repeated updates to the same record within one second may coalesce. Knowledge sync indexes only explicitly selected fields through an organization account; capped listings never remove unseen documents.

Odoo sales confirmation, invoice posting and transfer confirmation/reservation/validation have dedicated approval-gated tools. Use these business actions instead of writing a state field. Actions can return a wizard that needs completion in Odoo; read the record afterward before reporting success. Create invoices with an explicit `move_type` (customer, supplier, refund or receipt). Scalar fields and link/set/clear relation IDs are supported. Create or update related records with their own tools; nested ORM mutations and JSON-object field values are refused.

The Odoo cursor also retains a deduplicated snapshot of its timestamp boundary, so a later update to a lower-ID record is read again. Fingerprints cover the returned ID, display name and write date. Snapshots are capped at 2,000 records per model/timestamp; split bulk updates if this limit is exceeded.

## Exchange Online

Outlook mail and Outlook Calendar connect to Microsoft Exchange Online through Microsoft Graph. Use the Microsoft wizard with delegated OAuth, or an Entra application account with admin-consented application permissions and the target mailbox. No separate IMAP password or Work IQ licence is needed. This path targets Exchange Online; it does not add on-premises Exchange or EWS support.
