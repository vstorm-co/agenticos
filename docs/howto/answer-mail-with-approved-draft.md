---
title: "Answer mail with an approved draft"
description: "A workflow reads new mail, drafts a reply, asks a person to edit and approve it, then leaves a draft in the thread or sends it through a self-hosted Gmail or Microsoft 365 MCP server."
---

# Answer mail with an approved draft

The [inbox triage page](email-triage.md) ends with text in a chat. This page goes
one step further: a [workflow](../workflows.md) reads a new message, drafts a
reply, shows it to a person who may edit it, and then writes it into the
mailbox - as a draft in the same thread, or as a sent reply. The mailbox is
reached through an MCP server you run yourself.

This is a procedure to follow, not a report of a measured deployment. It needs a
mailbox, a Google or Microsoft app registration and a server that the maintainers
did not run for this page, so nothing here was run against a live mailbox. The tool
and argument names were read from the servers' source code, not from a running server.

## What you need

- One of the two servers, running where the deployment can reach it, with its
  address ending in `/mcp`: [`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp)
  for Gmail, with `--transport streamable-http` and `MCP_ENABLE_OAUTH21=true` and your
  own Google OAuth client, or [`softeria/ms-365-mcp-server`](https://github.com/softeria/ms-365-mcp-server)
  for Outlook, with `--http` and an app registered in Microsoft Entra (add
  `--org-mode` to reach shared mailboxes). The catalog lists them as **Google
  Workspace (self-hosted)** and **Microsoft 365 (self-hosted)**.
- A server on your own network is refused until an operator lists its host in
  `OUTBOUND_PRIVATE_ALLOWLIST` or `MCP_ALLOWED_HOSTS`. See
  [MCP servers](../mcp.md) and [Settings](../configuration.md#project-settings).
- An **organization** MCP connection to the server, made from that catalog entry by
  someone holding `mcp:manage`. Each connection signs in as one account, so it
  answers from one mailbox. A workflow cannot use a person's own connection yet, so
  a mailbox reached this way is a service account or a shared mailbox.
- The Gmail or Outlook portal connected, for the trigger. The trigger reads mail with
  read access only. The right to write is on the MCP connection, which is a separate
  grant: connect it as the account that should own the replies.

## Gmail

Build the workflow in this order.

1. **Gmail** trigger ([`trigger.gmail`](../reference/workflow-nodes.md#trigger-gmail)).
   Its output carries `thread_id`, `rfc_message_id`, `subject`, `sender` and `text`.
2. A drafting step: [`agent.run`](../reference/workflow-nodes.md#agent-run) with the
   knowledge capability, or [`knowledge.search`](../reference/workflow-nodes.md#knowledge-search)
   followed by [`ai.prompt`](../reference/workflow-nodes.md#model-steps). Its text is
   the proposed reply.
3. [`human.approval`](../reference/workflow-nodes.md#human-approval) with `editable`
   on and `proposal` bound from the drafting step. The approver reads the mail's
   summary in `details`, edits the text and approves.

4. [`mcp.call`](../reference/workflow-nodes.md#mcp-call) on the Google Workspace
   connection, tool `draft_gmail_message`, with these arguments:

   | Argument | Bound from |
   |---|---|
   | `thread_id` | the trigger's `thread_id` |
   | `in_reply_to` | the trigger's `rfc_message_id` |
   | `body` | the approval step's `final` |

   Leave `references` out: the server derives the chain through the message being
   answered. Leave `to` out too and the server replies to that message's sender; set
   `reply_all` to `true` to answer everyone on the thread. Leave `subject` out and the
   draft keeps the thread's subject. `user_google_email` is filled in by the server
   because it runs with `MCP_ENABLE_OAUTH21=true`.

   Set this step's **Ask for approval** to **Never**. A person approved the exact text a
   step ago and would otherwise be asked a second time.

To **send** instead of leaving a draft, use `send_gmail_message` with the same
arguments and one more: bind `to` from the trigger's `sender`, or set `reply_all` to
`true`. The tool refuses a call that has neither (`reply_all` needs the `thread_id`),
and only the draft tool fills `to` in by itself. The server has no tool that sends a
saved draft, so the two are separate choices, not two steps.

!!! warning "A direct send has no guard"

    `send_gmail_message` takes no idempotency key, and the server marks it as a
    write. If the call is made and no answer comes back, the step ends **Uncertain**
    and the run waits for a person: the mail may or may not have gone out. Open the
    thread in Gmail and look before you run the step again. When you want a second
    chance to catch a mistake, use `draft_gmail_message` and let a person press
    **Send** in Gmail: a repeat can only leave a second draft.

## Microsoft 365

1. **Outlook** trigger ([`trigger.outlook`](../reference/workflow-nodes.md#trigger-outlook)).
   Its output carries `message_id` and, for a shared mailbox, `mailbox`.
2. The same drafting step and the same editable `human.approval` as above.
3. **Make the reply's body.** A **Map fields** step ([`data.map`](../reference/workflow-nodes.md#data-map))
   builds one field, `reply_body`, of type `json` from the approval's `final`:

   ```text
   {Message: {body: {contentType: 'text', content: source.final}}}
   ```

   with `source` bound to the approval step; the result is `values.reply_body`.

   The server's own guidance for
   `create-reply-draft` is to pass the text as `Message.body.contentType` and
   `Message.body.content`; a supplied body replaces the draft's whole body, so
   the quoted history is not in it.

   Check the argument names in the tool's form
   in the editor after you choose the tool and refresh its tools: the server
   builds them from Microsoft Graph, and they were not seen on a running server.

4. [`mcp.call`](../reference/workflow-nodes.md#mcp-call) on the Microsoft 365
   connection, tool `create-reply-draft`, with `messageId` bound from the trigger's
   `message_id` and `body` bound from `values.reply_body` of the step above. Graph
   threads the draft itself. For a shared mailbox read by the trigger, use
   `create-shared-mailbox-reply-draft` instead, adding `userId` bound from the
   trigger's `mailbox`; the server must run with `--org-mode`. The server registers
   its path parameters in camelCase and requires them.

5. *Optional.* To send the draft, first read its id. The server answers with JSON
   inside its `text`, not as `structured` data, so a
   [`code.python.simple`](../reference/workflow-nodes.md#python) step takes it out:
   bind `args.text` to the create step's `text` and run

   ```python
   import json
   json.loads(args['text'])['id']
   ```

   Do not run the server with `--toon`: its output is then not JSON. Then call
   `send-draft-message` with `messageId` bound to that step's `result`
   (`send-shared-mailbox-draft` for a shared mailbox, which also takes `userId`
   bound from the trigger's `mailbox`).

Set each `mcp.call` step's **Ask for approval** to **Never** after an editable
approval. When nothing was approved before the step, keep the default, **Before a
tool that can change something**. That policy asks before any tool the server does
not mark read-only, so it asks before `create-reply-draft` and before Gmail's
`draft_gmail_message` as well.

### What a repeat does

Neither server accepts an idempotency key, so leave **Idempotency key argument**
empty on these steps. The recipes below make a repeat harmless without one.

- **Microsoft 365: create, then send by the draft's id.** A second
  `send-draft-message` for the same draft fails, because a sent draft has left
  Drafts; it does not send a second mail. A repeated `create-reply-draft` can leave a
  spare draft and never a second sent mail. If the send step breaks after it was
  called, it ends **Uncertain**: look in Sent Items, then re-run it. A re-run of a
  send that had gone out fails instead of sending again.
- **Gmail: leave a draft** (recommended). A repeat leaves at most a second draft.
- **Gmail: a direct send** has no such protection; see the warning above.

A failure before the call - the server down, the connection refused - is
retried on its own. After an unkeyed call to a tool the server does not mark
read-only, the step is never repeated by itself. The
[`mcp.call` reference](../reference/workflow-nodes.md#mcp-call) has the rule.

## Safety

Mail is input from outside, and it can carry instructions aimed at the model; the
Google Workspace server's own documentation warns of this. Keep the approval step
between the drafting step and the mailbox, and do not give the drafting agent a tool
that can write.

Attachments reach the workflow as files, but a reply written this way carries none.

## Check it

- A draft or a sent reply shows in the original thread in the mailbox; a sent one also reaches the sender.
- `In-Reply-To` on the sent or drafted message equals the trigger's
  `rfc_message_id`.
- Edit the text in the approval and check that the edited text, not the proposal,
  is what lands in the mailbox.
- Reject the approval and check that nothing is written.

## Next steps from the same connection

- **Google Calendar:** `query_freebusy`, `get_events`, `manage_event`.
- **Google Drive:** `search_drive_files`, `get_drive_file_content`.
- **Google Sheets:** `append_table_rows`, `read_sheet_values`.
- **Microsoft 365 calendar:** `list-calendar-events`, `create-calendar-event`.

Another Microsoft route exists: the hosted **Microsoft Work IQ** server answers
questions across mail, meetings, chats and files but blocks changes until a tenant
administrator allows them. See [Microsoft 365 and Outlook](../mcp.md#outlook-setup).
