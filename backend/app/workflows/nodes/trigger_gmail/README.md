# trigger.gmail

A workflow a message arriving in the organization's Gmail mailbox starts. The
mailbox is the one connected through the **Gmail** portal - the step's panel
says whether one is and connects it - and publishing is refused until it is.

## Which messages

The mailbox is read by the poll that also fires agents' Gmail triggers, every minute
unless its **Check for new mail every** setting says otherwise - one setting for every
trigger on the mailbox - and a message is new to it once: the first read of a mailbox
establishes where it stands and starts nothing. Of the new ones, a message starts a run
when it fits every filter set - **Subject contains** and **Sender contains**, ignoring
case, and **Label**, exactly - or always when none is. A message read twice, by a poll
that overlapped another, starts its run once.

Each run acts as the member who published the workflow. When the organization already
has too much work in flight to admit one, the poll keeps its place and reads the same
messages again a minute later, whatever the mailbox's interval, so nothing is dropped. A
workflow at its own limit on concurrent runs is read again the same way, except when
runs waiting for an approval hold the limit: the message is then skipped for that
workflow, with a log line and an audit entry, so one workflow waiting on people does not
hold the mailbox. A body is handed on as far as the mailbox read it.

## Ports

| Port | Kind | Schema | What it carries |
|---|---|---|---|
| `out` | output | `EmailTriggerOutput` | `sender`, `to`, `subject`, `text`, `snippet`, `labels`, `message_id`, `thread_id`, `rfc_message_id`, `in_reply_to`, `references`, `received_at`, `html`, `mailbox`, `attachments` (each: id, name, declared type and size, and `file` once stored, else `reason`) |

## Attachments

A run the mailbox started stores the message's attachments as files of the run, when
the graph binds the trigger's `attachments` (or its whole output) and otherwise lists
them as `not_fetched`. They are read with the organization's Gmail grant and handed on as `file` with
`stored: true`. At most 10 are stored, each within the chat upload size limit and
type list (an executable or script is listed by name and never fetched) and 25 MiB
in all. One that is left out says why in `reason`: `too_many`, `too_large`,
`type_not_allowed`, `quota`, `unreadable` (the grant is missing or off, or Gmail no
longer has it) or `not_fetched` (a test run reads nothing from the mailbox, nor does a graph that does
not read the attachments). If
Gmail cannot be reached the step fails as `MAIL_ATTACHMENT_UNREACHABLE` and is
retried, and the files that attempt stored are removed. An attempt interrupted
before it finished leaves its copies with the run until run retention removes them.
Stored files count against the organization's file quota, and any sender may mail a
trigger with no **Sender contains**, so bind `attachments` only when a step needs the files.
