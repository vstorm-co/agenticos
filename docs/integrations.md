# Built-in integrations

Connect an account under **Settings → Vault → Connected accounts**. Each Google, Microsoft or Slack product is a separate capability in an agent's **Toolbox**, with its own account selection and individual tool switches. These integrations use provider APIs directly; vendor MCP servers, Google Workspace MCP preview and a Microsoft Copilot licence are not required.

## Set up an account

The provider wizard shows the deployment's exact callback URL, console link and requested scopes. Select products first. Reads are the default; opt into write permissions explicitly. An administrator stores one organization-visible OAuth app in the Vault; members reuse it when connecting personal accounts. Multiple app credentials require an administrator to resolve which one the deployment uses.

Google: create a Cloud project, enable the listed APIs (the wizard supplies a `gcloud services enable` command), configure the consent screen and create a **Web application** OAuth client. Copy the callback exactly and store `google_oauth_app`. Choose Internal only for a Workspace organization that owns the project. External apps in Testing can issue refresh tokens that expire after seven days. A normal API integration does not need an AI-powered-agent client or the hosted MCP APIs.

Microsoft: register an Entra app, choose the supported account types and tenant, add a Web redirect and the displayed delegated Graph permissions, and save `microsoft_oauth_app`. Work/school and personal Microsoft accounts work only where the chosen Graph product supports them; Teams requires work/school accounts. Administrator consent can still be required by the tenant's policy.

Slack: **Create the Slack app** opens a prefilled manifest with this deployment's redirect and read-only user scopes. Add write scopes when requesting writes, then reinstall/authorize. Save `slack_oauth_app` and complete consent. An existing channel-bot app can be reused by adding the redirect and user scopes to it. Workspace app limits and administrator approval still apply. The **Agents → MCP Server** toggle is needed only when separately using Slack's hosted MCP server.

## Alternatives to OAuth

Google supports a Vault `gcp_service_account`, with a subject for Workspace domain-wide delegation. The Workspace administrator must authorize the displayed scopes. A plain service account accesses only resources shared with it; it does not become a personal Gmail account.

Microsoft supports a Vault `entra_app` client secret and application permissions with administrator consent. Configure the mailbox subject for mail/calendar; Teams requires the subject's directory object ID so mentions can be matched without directory-wide read permission. Excel workbook APIs require delegated OAuth. Graph application permissions do not support normal Teams posting; use delegated OAuth for that operation. Application scopes differ from delegated scopes and the wizard displays the appropriate list.

Slack accepts existing `xoxp-` user tokens or `xoxb-` bot tokens. A bot can post as the app, but it cannot use user-only search APIs. Actual granted scopes are checked before each operation. Tokens and service-account keys are sealed in the Vault, never stored in an agent spec.

**IMAP** is a separate read-only mail connection using a host, verified TLS port, username, app password and fixed folder. The operator must allow the exact host in `MIRAGE_ALLOWED_HOSTS`. It reuses the installed Mirage mail client. Microsoft 365 basic-auth IMAP is not an alternative to Microsoft OAuth here.

## Choose what an agent can do

Google products: Gmail (search/read, labels, draft/send), Calendar (events and free/busy), Drive (search, metadata, read/upload/copy), Docs, Sheets and Slides (read/create/update). Sheets includes range reads, append and cell updates.

Microsoft products: Outlook mail, Calendar, OneDrive/SharePoint files, Excel and Word documents, and Teams chats/channels. Slack offers search, my mentions, history/threads, channels/users, lookup, posting/replies, DMs and reactions. IMAP offers search and message reads without marking them seen.

Choose **personal** to resolve the current person's account by its exact name, label or address. An empty name works only with one matching account. Personal tools require a private conversation and current organization membership. Choose **organization** and a connection ID for shared automations. A capability never borrows another member's account.

Each write requires human approval in agent runs, even if a per-tool override requests otherwise. Disable tools individually to remove them. Workflows expose the same operations as `integration.<product>.<operation>` nodes, with the same account and transport checks. Writes are not automatically retried; place an approval node before writes that need human review in a workflow.

File nodes accept base64 content, never a server-local path. Word writes accept a title and paragraphs and create a `.docx`. Uploads/downloads are bounded to 20 MB, JSON to 2 MB and extracted text to 100,000 characters. A failed write may already have reached the provider: inspect the remote result before retrying.

## Knowledge, triggers and watches

Drive and SharePoint sources can select the same organization connection instead of a separate credential. OneDrive uses the SharePoint connector with the selected drive/folder. Slack sync indexes only selected channels and their threads. The account is revalidated at every sync; private member accounts are not silently spent by a shared knowledge source.

Routine triggers reuse the existing transactional queue, deduplication and approved-source policy. Gmail/Outlook filters, calendar leads and file changes work on native accounts. Slack adds channel messages, mentions and DMs; Teams adds messages and mentions; IMAP adds new mail. Sheets tracks **appended rows** in a selected spreadsheet and sheet, baselining the last occupied row in column A. Keep that column populated; row insertion/deletion and edits to existing rows are not append events.

A watch selects one personal connection and product, with only a fixed read-only change tool. Enable that product on the agent first. Slack conversations and delegated Teams chats must be selected in the capability. Teams channels use `channel/team-id/channel-id`; an app-only Teams feed with no conversations reads all chats of its configured subject.

Each watch has an independent durable cursor; it advances only after a successful consumed check. New/reset cursors establish a quiet baseline rather than replaying history. Gmail uses history IDs, Outlook and calendars use provider cursors, Slack uses a timestamp per conversation and IMAP uses UIDVALIDITY/UID. Delegated Teams chats use `lastModifiedDateTime`; channel and application feeds use Graph delta. Narrow a source if a bounded read reports too much backlog.

See [capabilities](reference/capabilities.md), [triggers](triggers.md), [governance and watches](governance.md#proactive-work) and [MCP](mcp.md) for their existing controls.

Set a label such as Work when connecting; use the same label for each person’s corresponding account.
