---
title: "Triage your inbox and draft replies"
description: "Connect a mailbox as a polled event trigger and have an agent draft replies or extract action items — never send anything."
---

# Triage your inbox and draft replies

Connect a Gmail mailbox as an [event trigger](../triggers.md#gmail-1-minute-and-no-secret-anywhere)
and have an agent read each new message and produce a draft reply or a list of
action items. This is a procedure to run, not a report of a measured deployment —
it needs a real Gmail account and a Google OAuth client the deployment does not
have configured here, so nothing on this page was fired against a live mailbox.

## What the agent can and cannot do with mail

Read this before connecting anything, because it decides whether the page below
is worth the OAuth consent.

**It can read.** The Gmail trigger polls the connected mailbox once a minute and
hands the agent a new message's subject, sender and body. The deployment asks
Google only for the `gmail.readonly` scope — nothing more is requested at the
consent screen, so there is no broader grant to accidentally rely on.

**It cannot send, and it cannot create an actual Gmail draft.** There is no tool,
here or in the MCP catalog, that calls Gmail's send or drafts API. What the
templates below call a "draft" is the agent's answer text, written to the run
that fired — it lands in **Activity**, in that run's conversation, as a message a
person still has to read and paste into an outgoing email themselves. Nothing is
ever sent on your behalf, and nothing is written back into the mailbox.

## What you need

- A [running installation](../install.md) with a model profile.
- A Google OAuth client the deployment operator has registered
  (`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`, Gmail API enabled) — this is a
  *deployment* prerequisite, not something each organization sets up for itself.
  Without it, the Gmail connect card says so instead of a button that could only
  fail.
- The `mcp:manage` permission, to connect the mailbox.

## Build the agent

1. Open **Routines → New event trigger → Gmail → Connect account**. Consent
   authorizes read-only access to the mailbox; connecting fires nothing and
   loses nothing — the mailbox's position is taken at the moment consent
   completes.
2. Pick what fires it: any new message, inbox only, or marked important. Narrow
   further with **Subject contains**, **Sender contains**, or a Gmail label —
   all three are optional substring filters, and an unnamed one means every
   message in scope fires.
3. Start from a template instead of a blank prompt. `GET /trigger-templates`
   lists two for this source:

   | Template | What it does |
   | --- | --- |
   | **Draft a reply to the email** | Summarises what the sender needs in one line, then drafts a reply to review |
   | **Turn the email into action items** | Extracts every action item, its owner and any deadline |

4. Create an agent for this trigger to fire, with a model profile, and publish
   it. No sandbox, no knowledge collection and no other capability is required
   for either template.
5. Bind the trigger to the published agent and set it active.

The reply-draft template's prompt, verbatim:

```text
An email just arrived - its subject, sender and body are in this message.
Summarise in one line what the sender needs, then draft a reply I can review and
send. Match the sender's tone, answer every question they asked, and keep it
brief.
```

## What "Run it" means here

There is no signed delivery to send by hand — Gmail is polled, not pushed, so
there is no URL and no secret at all. Two ways to see the agent work before a
real message arrives:

- **Run now**, on the trigger, fires the agent's **base prompt with no delivery
  context** — no message, no sender, nothing to draft a reply to. It proves the
  agent, its budget and its publish state are all in order, but it does not
  exercise triage: there is no email in that run for the template's instructions
  to act on.
- **A real message landing in the connected mailbox** is the only way to see an
  actual draft. The heartbeat reads what arrived since its last check, once a
  minute, up to 25 messages per tick — so the worst-case latency is a minute, and
  a mailing-list burst does not turn into hundreds of runs.

## Check the result

Once a real message has fired the trigger, the checks that apply generally:

| Check | Reference |
| --- | --- |
| A message matching the filter | Fires once, and the run's conversation holds a drafted reply or an action-item list, never a sent email |
| A message **not** matching subject/sender/label | Does not fire at all |
| An email with no clear question or task | The action-items template says plainly there is no actionable work, rather than inventing one |
| The Gmail connection's own status | Shown on the trigger; a failed poll is reported there, not only in a container log |
| Mail from before the mailbox was connected | Never fires — the cursor starts at the moment consent completed |

## When it goes wrong

- **Nothing fires.** Check the Gmail connection's status first — a broken poll
  is reported on the trigger. Then check the filter: an empty **Subject
  contains** or **Sender contains** matches everything, so a narrow filter that
  looks right on paper can still exclude the message you sent as a test.
- **You expect a sent reply and get a chat message instead.** That is the whole
  design here, not a bug — see *What the agent can and cannot do with mail*
  above. Copy the draft into your mail client by hand.
- **A missed backlog after downtime.** Google keeps about a week of history; a
  cursor older than that resynchronises to now rather than replaying everything
  that piled up, so a mailbox down for longer than a week has a gap nothing
  backfills.
- **`Run now` looks like it worked but nothing useful came back.** It ran the
  agent with no message attached — expected, and not a way to test triage
  itself. Wait for a real delivery, or send yourself a matching test email.

## Record the trial

Once you can run this against a real mailbox: keep the filter you set, the
template or prompt used, a handful of fired runs and their drafts, and who reads
those drafts before anything is sent. A person sends every reply and files every
action item — this agent only prepares the text.

## Next steps

For triage driven by your own app rather than a mailbox, see [triage incoming
support requests from your own app](support-ticket-triage.md), which uses a
signed webhook you control end to end and can be verified without an external
account.
