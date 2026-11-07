# Built-in integrations

Connect an account under **Settings → Vault → Connected accounts**. Each Google, Microsoft or Slack product is a separate capability in an agent's **Toolbox**, with its own account selection and individual tool switches. These integrations use provider APIs directly; vendor MCP servers, Google Workspace MCP preview and a Microsoft Copilot licence are not required.

## Set up an account

The provider wizard shows the deployment's exact callback URL, console link and requested scopes. Select products first. Reads are the default; opt into write permissions explicitly. An administrator stores one organization-visible OAuth app in the Vault; members reuse it when connecting personal accounts. Multiple app credentials require an administrator to resolve which one the deployment uses.

Google: create a Cloud project, enable the listed APIs (the wizard supplies a `gcloud services enable` command), configure the consent screen and create a **Web application** OAuth client. Copy the callback exactly and store `google_oauth_app`. Choose Internal only for a Workspace organization that owns the project. External apps in Testing can issue refresh tokens that expire after seven days. A normal API integration does not need an AI-powered-agent client or the hosted MCP APIs.

Microsoft: register an Entra app, choose the supported account types and tenant, add a Web redirect and the displayed delegated Graph permissions, and save `microsoft_oauth_app`. Work/school and personal Microsoft accounts work only where the chosen Graph product supports them; Teams requires work/school accounts. Administrator consent can still be required by the tenant's policy.

Slack: **Create the Slack app** opens a prefilled manifest with this deployment's redirect and read-only user scopes. Add write scopes when requesting writes, then reinstall/authorize. Save `slack_oauth_app` and complete consent. An existing channel-bot app can be reused by adding the redirect and user scopes to it. Workspace app limits and administrator approval still apply. The **Agents → MCP Server** toggle is needed only when separately using Slack's hosted MCP server.

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

Choose **personal** to resolve the current person's account by its exact name, label or address. An empty name works only with one matching account. Personal tools require a private conversation and current organization membership. Choose **organization** and a connection ID for shared automations. A capability never borrows another member's account.

Each write requires human approval in agent runs, even if a per-tool override requests otherwise. Disable tools individually to remove them. Workflows expose the same operations as `integration.<product>.<operation>` nodes, with the same account and transport checks. Writes are not automatically retried; place an approval node before writes that need human review in a workflow.

File nodes accept base64 content, never a server-local path. Word writes accept a title and paragraphs and create a `.docx`. Uploads/downloads are bounded to 20 MB, JSON to 2 MB and extracted text to 100,000 characters. A failed write may already have reached the provider: inspect the remote result before retrying.

Publishing an organization binding verifies the scopes of every enabled tool. With a read-only account, disable write tools before publishing or reconnect with write permissions.

## Knowledge, triggers and watches

Drive and SharePoint sources can select the same organization connection instead of a separate credential. OneDrive uses the SharePoint connector with the selected drive/folder. Slack sync indexes only selected channels and their threads. The account is revalidated at every sync; private member accounts are not silently spent by a shared knowledge source.

Routine triggers reuse the existing transactional queue, deduplication and approved-source policy. Gmail/Outlook filters, calendar leads and file changes work on native accounts. Slack adds channel messages, mentions and DMs; Teams adds messages and mentions; IMAP adds new mail. Sheets tracks **appended rows** in a selected spreadsheet and sheet, baselining the last occupied row across columns A:ZZ; row insertion/deletion and edits to existing rows are not append events.

A watch selects one personal connection and product, with only a fixed read-only change tool. Enable that product on the agent first. Slack conversations and delegated Teams chats must be selected in the capability. Teams channels use `channel/team-id/channel-id`; an app-only Teams feed with no conversations reads all chats of its configured subject.

Each watch has an independent durable cursor; it advances only after a successful consumed check. New/reset cursors establish a quiet baseline rather than replaying history. Gmail uses history IDs, Outlook and calendars use provider cursors, Slack uses a timestamp per conversation and IMAP uses UIDVALIDITY/UID. Delegated Teams chats use `lastModifiedDateTime`; channel and application feeds use Graph delta. Narrow a source if a bounded read reports too much backlog.

See [capabilities](reference/capabilities.md), [triggers](triggers.md), [governance and watches](governance.md#proactive-work) and [MCP](mcp.md) for their existing controls.

Set a label such as Work when connecting; use the same label for each person’s corresponding account.

Native triggers created through the API require `connection_id`. Filter edits recheck the account, permissions and conversation selection. Each distinct Slack/Teams conversation selection keeps its own cursor and only feeds its associated triggers; one selection can contain up to 20 conversations.

## Odoo

Connect Odoo 19+ through JSON-2 with the HTTPS origin, database name and a business user's API key. The operator must list the exact host in `ODOO_ALLOWED_HOSTS`; paths, redirects and custom ports are refused. Odoo Online requires a Custom plan for external API access. Install the business modules you intend to use and restrict the user's Odoo ACLs and record rules. Keys expire: rotate them and reconnect the account. Write access is opt-in and every agent write still needs approval.

Toolbox capabilities cover Contacts, CRM, Sales, Invoicing, Inventory and Projects. Each exposes field inspection, bounded record search/read and explicit create/update tools where supported. Stock levels are read-only; use transfers and stock moves for inventory operations. Tools and workflow nodes use the same account and JSON-2 adapter. Arbitrary models, methods and user-supplied context are not accepted.

Watches and routine triggers read created/modified records in their selected business area. Each model has an independent `(write_date, id)` cursor; the first check establishes a quiet baseline. Subsequent checks consume at most 100 records per model and retain the remaining backlog. Deletions are not events. Odoo timestamps have second precision, so repeated updates to the same record within one second may coalesce. Knowledge sync indexes only explicitly selected fields through an organization account; capped listings never remove unseen documents.

Odoo sales confirmation, invoice posting and transfer confirmation/reservation/validation have dedicated approval-gated tools. Use these business actions instead of writing a state field. Actions can return a wizard that needs completion in Odoo; read the record afterward before reporting success. Create invoices with an explicit `move_type` (customer, supplier, refund or receipt). Scalar fields and link/set/clear relation IDs are supported. Create or update related records with their own tools; nested ORM mutations and JSON-object field values are refused.

The Odoo cursor also retains a deduplicated snapshot of its timestamp boundary, so a later update to a lower-ID record is read again. Fingerprints cover the returned ID, display name and write date. Snapshots are capped at 2,000 records per model/timestamp; split bulk updates if this limit is exceeded.

## Exchange Online

Outlook mail and Outlook Calendar connect to Microsoft Exchange Online through Microsoft Graph. Use the Microsoft wizard with delegated OAuth, or an Entra application account with admin-consented application permissions and the target mailbox. No separate IMAP password or Work IQ licence is needed. This path targets Exchange Online; it does not add on-premises Exchange or EWS support.
