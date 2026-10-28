# trigger.outlook

A workflow a message arriving in a folder of the organization's Outlook
mailbox starts. The mailbox is the one connected through the **Outlook** portal
(Microsoft 365) - the step's panel says whether one is and connects it - and
publishing is refused until it is.

## Which messages

Microsoft Graph is read one folder at a time, so the **Folder** this step names (`inbox`
by default, another well-known folder, or the display name of a top-level folder) and
its **Shared mailbox**, when it names one, are where the poll looks as well as a filter.
The poll that also fires agents' Outlook triggers reads the folders of both, every
minute unless the mailbox's **Check for new mail every** setting says otherwise. A
message is new to a folder once: the first read of a folder starts at the moment the
workflow was published and starts nothing for the mail already there. Of the new ones, a
message starts a run when it fits every filter set - **Subject contains** and **Sender
contains**, ignoring case, **Has attachments**, **Importance** and **Category** (one of
the message's categories, ignoring case) - or always when none is. A message read twice,
by a poll that overlapped another, starts its run once.

A sender filter also needs mail the sender's domain authenticated (DMARC, or a
DKIM signature from that domain) or that came from inside the tenant.

Each run acts as the member who published the workflow. When the organization already
has too much work in flight to admit one, the poll keeps its place and reads the same
messages again a minute later, whatever the mailbox's interval, so nothing is dropped. A
workflow at its own limit on concurrent runs is read again the same way, except when
runs waiting for an approval hold the limit: the message is then skipped for that
workflow, with a log line and an audit entry, so one workflow waiting on people does not
hold the mailbox.

If Outlook says the folder or the shared mailbox cannot be read, the workflow is
switched off and the audit log says why (`mailbox_folder_unreadable`). A revoked
grant switches off agents' triggers only, as for Gmail.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `EmailTriggerOutput` | `sender`, `to`, `subject`, `text`, `snippet`, `labels` (the message's categories), `message_id`, `thread_id` (the conversation), `rfc_message_id`, `in_reply_to`, `references`, `received_at`, `html`, `mailbox` (the shared mailbox it was read from, empty for the account's own), `attachments` (each: id, name, declared type and size, and `file` once stored, else `reason`) |

## Attachments

A run the mailbox started stores the message's attachments as files of the run, when
the graph binds the trigger's `attachments` (or its whole output) and otherwise lists
them as `not_fetched`. They are read with the organization's Outlook grant and handed on as `file` with
`stored: true`; the limits and the `reason` an attachment is left out are those of
`trigger.gmail`. A test run reads nothing from the mailbox: every attachment is
`not_fetched`.
