# trigger.gmail

A workflow a message arriving in the organization's Gmail mailbox starts. The
mailbox is the one connected through the **Gmail** portal - the step's panel
says whether one is and connects it - and publishing is refused until it is.

## Which messages

The mailbox is read once a minute by the poll that also fires agents' Gmail
triggers, and a message is new to it once: the first read of a mailbox
establishes where it stands and starts nothing. Of the new ones, a message
starts a run when it fits every filter set - **Subject contains** and **Sender
contains**, ignoring case, and **Label**, exactly - or always when none is. A
message read twice, by a poll that overlapped another, starts its run once.

Each run acts as the member who published the workflow. When the organization
already has too much work in flight to admit one, the poll keeps its place and
reads the same messages again a minute later, so nothing is dropped. A body is
handed on as far as the mailbox read it.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `EmailTriggerOutput` | `sender`, `to`, `subject`, `text`, `snippet`, `labels`, `message_id` |
