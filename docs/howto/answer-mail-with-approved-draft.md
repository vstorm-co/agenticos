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

The Gmail workflow below was run end to end against a test mailbox on a development
deployment, with `workspace-mcp` 2.2.1. The Microsoft 365 recipe was not: its tool and
argument names were read from the server's source code, not from a running server.

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
- With `MCP_ENABLE_OAUTH21=true` the Google Workspace server refuses to start on plain
  `http` anywhere but `localhost`, and the deployment refuses a loopback address for an
  MCP server. So serve it over HTTPS on a host name the deployment can reach. To try the
  workflow on a laptop, run the server with `--single-user` and without
  `MCP_ENABLE_OAUTH21` instead: it signs in to Google once, keeps that account's token,
  and answers the deployment without a sign-in. Anyone who can reach the server can
  then use that mailbox, so keep it to a test account on a machine nobody else reaches.
- An **organization** MCP connection to the server, made from that catalog entry by
  someone holding `mcp:manage`. Each connection signs in as one account, so it
  answers from one mailbox. A workflow cannot use a person's own connection yet, so
  a mailbox reached this way is a service account or a shared mailbox.
- The Gmail or Outlook portal connected, for the trigger. The trigger reads mail with
  read access only. The right to write is on the MCP connection, which is a separate
  grant: connect it as the account that should own the replies.

## Gmail

The workflow follows a common Gmail auto-responder pattern: decide whether a mail needs
an answer, draft one, and put it in the thread. It adds two things. A person reviews
every reply before it reaches the mailbox, and chooses there whether to send it or keep
it as a draft. Build it in this order.

1. **Gmail** trigger ([`trigger.gmail`](../reference/workflow-nodes.md#trigger-gmail))
   with **Label** `INBOX`. Its output carries `sender`, `subject`, `text`,
   `message_id`, `thread_id` and `rfc_message_id`. The mailbox is checked every minute
   unless you choose a longer interval on the step.
2. **Does it need a reply?** [`ai.classify`](../reference/workflow-nodes.md#model-steps)
   with three categories, `needs_reply`, `fyi` (newsletters, receipts, notifications,
   thanks) and `spam`, and `text` bound to the sender, subject and body. Set **Minimum
   confidence**, for example `0.7`: a mail the model is less sure about leaves by
   `unsure`, so a person decides it rather than the model. The model's confidence is its
   own report and not calibrated, so try the threshold on your own mail with the step's
   [evals](../workflows.md#evals-for-a-model-step).
3. **Join the two ways to a reply.** Connect `needs_reply` and `unsure` to one
   [`logic.merge`](../reference/workflow-nodes.md#logic-if-and-logic-merge). `fyi`,
   `spam` and `other` end there, or lead to whatever records them.
4. **Draft the reply.** [`knowledge.search`](../reference/workflow-nodes.md#knowledge-search)
   on the collection that holds your answers, with `query` bound to the subject and
   body, then [`ai.prompt`](../reference/workflow-nodes.md#model-steps) with the mail
   and the search's `sources` in its prompt. Instructions that work well: reply in the
   sender's language, in plain text, start with a greeting and end with a sign-off, use
   the passages and never invent an answer, and write a placeholder such as
   `[YOUR_ANSWER_HERE]` where the answer is not known. The approver fills it in. An
   [`agent.run`](../reference/workflow-nodes.md#agent-run) with the knowledge capability
   does the same in one step.
5. **Review it.** [`human.approval`](../reference/workflow-nodes.md#human-approval) with
   `editable` on, `proposal` bound to the drafted reply, the mail itself in `details`,
   and two **choices**: `send` (**Send now**) and `draft` (**Save as draft**). The
   approver edits the text and presses the button for what should happen to it, or
   **Reject**.
6. **Write it to the mailbox.** One
   [`mcp.call`](../reference/workflow-nodes.md#mcp-call) on the Google Workspace
   connection per choice:

   | Choice | Tool | Arguments |
   |---|---|---|
   | `send` | `send_gmail_message` | `thread_id`, `in_reply_to`, `body`, and `to` from the trigger's `sender` |
   | `draft` | `draft_gmail_message` | `thread_id`, `in_reply_to`, `body` |

   Bind `thread_id` from the trigger's `thread_id`, `in_reply_to` from its
   `rfc_message_id`, and `body` from the `final` of the approval's output on that
   choice's port. Leave `references` out: the server derives the chain through the
   message being answered. Leave `subject` out and the reply keeps the thread's subject.
   The send tool refuses a call with neither `to` nor `reply_all` set to `true`; the
   draft tool fills in `to` itself. `user_google_email` is filled in by a server
   running with `MCP_ENABLE_OAUTH21=true`; in single-user mode, bind it to the
   mailbox's address.

   Set both steps' **Ask for approval** to **Never**. A person approved the exact text a
   step ago and would otherwise be asked a second time.

To keep a record, add a record step after any of these to write a row to a
[table](../virtual-tables.md), with the category, the decision and the text sent.

!!! warning "A direct send has no guard"

    `send_gmail_message` takes no idempotency key, and the server marks it as a
    write. If the call is made and no answer comes back, the step ends **Uncertain**
    and the run waits for a person: the mail may or may not have gone out. Open the
    thread in Gmail and look before you run the step again. **Save as draft** cannot
    do this: a repeat can only leave a second draft. The server has no tool that sends
    a saved draft, so a draft is sent from Gmail.

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
- **Gmail: Save as draft.** A repeat leaves at most a second draft.
- **Gmail: Send now** has no such protection; see the warning above.

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
- Press **Save as draft** once and **Send now** once, and check that each did only
  what its button says.
- Send a newsletter and check that it starts no approval.
- Reject the approval and check that nothing is written.

Mail sent to the mailbox from its own address is labelled SENT, and the trigger skips
SENT mail, so test with mail from another account.

## Next steps from the same connection

- **Google Calendar:** `query_freebusy`, `get_events`, `manage_event`.
- **Google Drive:** `search_drive_files`, `get_drive_file_content`.
- **Google Sheets:** `append_table_rows`, `read_sheet_values`.
- **Microsoft 365 calendar:** `list-calendar-events`, `create-calendar-event`.

Another Microsoft route exists: the hosted **Microsoft Work IQ** server answers
questions across mail, meetings, chats and files but blocks changes until a tenant
administrator allows them. See [Microsoft 365 and Outlook](../mcp.md#outlook-setup).
