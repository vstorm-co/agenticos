# Channel runtime acceptance test

Use the isolated local instance and its copied database. Keep the existing
local instance running. Existing bots and automations in the copy stay disabled.
Create a separate Mattermost bot with username `local-agenticos`, bind the test
agent to it, and invite it only to a dedicated test channel. Use a second
Mattermost participant for the identity and ownership cases.

The shared router, transcript, worker queue and steering capability implement
these behaviours for all supported channels. Mattermost is the manual transport
under test; adapter regressions are covered separately by the focused tests.

## Setup

1. Sign in to the second console with your existing local account.
2. Open Channels and register the separate Mattermost bot. Use the actual
   Mattermost server URL and its new bot token. Prefer the event stream so no
   public callback tunnel is needed.
3. Bind an agent with thread-history tools enabled. For the MCP cases, use a
   known test Notion page and the intended personal or organization binding.
   Check the published version, not only the draft.
4. Run the bot's readiness inspection. An unlinked channel identity or a missing
   personal service is a warning with its own label. A saved personal connection
   does not prove the provider still authorizes it.
5. Replace the test page placeholder below with that page's name. Keep personal
   authorization links in a DM.

## 1. A fresh thread excludes the surrounding channel

Post this as a channel message without mentioning the bot:

> QA-OUTSIDE: tajny kod poprzedniej rozmowy to KAKTUS-731.

Start a **new root message**, not a reply:

> @local-agenticos Cześć. Jakie ustalenia widzisz w tym wątku? Odpowiedz na podstawie kontekstu, który już dostałeś, bez szukania historii kanału.

Expected: the agent does not quote `KAKTUS-731` or claim the other conversation
is part of this thread. Check the run input and context, not only its wording.

## 2. Join an existing thread

Start another root message, without a mention:

> QA-THREAD-A: demo odbędzie się 18 listopada o 14:30. Kod ustaleń: RYŚ-482.

Reply **inside that thread**, as separate posts:

> Sala B, nie sala A.

> Osoba kontaktowa: Marta.

> @local-agenticos Podsumuj ustalenia tego wątku: termin, sala, osoba kontaktowa i kod. Nie szukaj innych rozmów w kanale.

Expected: all four facts are available, with their original authors and times.
`QA-OUTSIDE` is absent. A short complete thread carries no missing-history warning.
The current question appears once, and imported posts
are reference data rather than fake assistant answers.

## 3. Discussion between mentions

Continue the same thread with several normal messages. They may come from both
participants; no bot mention is necessary until the final question:

> Zmiana: demo przenosimy na 19 listopada o 10:00.

> Zostaje sala B.

> Marta potwierdziła nowy termin.

> Nowy kod ustaleń: ŻUBR-914. Poprzedni kod jest nieaktualny.

> @local-agenticos Jakie są teraz aktualne ustalenia? Wskaż, co zmieniono od poprzedniego podsumowania.

Expected: the changed date, time and code win. Earlier context is retained once;
the previous bot answer and earlier imported posts are not imported again.
Repeat after a longer discussion, for example 20 separate posts.

## 4. Explicit channel-history lookup

In the current thread:

> @local-agenticos Teraz użyj narzędzia historii kanału: znajdź wiadomość QA-OUTSIDE i podaj jej kod oraz źródło.

Expected: a real channel-history tool call is visible. It is allowed only when
the binding permits channel history; otherwise the agent explains the missing
access. The code must not have appeared automatically in scenario 1.

## 5. Same-sender additions and late messages

Ask for a task that needs several available read-only tool calls:

> @local-agenticos Znajdź stronę TESTOWA STRONA w Notion, przeczytaj ją i sprawdź powiązane materiały. Przygotuj krótkie podsumowanie z odnośnikami.

While the run is working, from the **same participant**, send:

> @local-agenticos Doprecyzowanie: odpowiedź po polsku, maksymalnie trzy punkty. Dodaj na końcu kod QA-STEER-527.

Expected: when a model request is still ahead, the addition joins that run once.
Its native receipt is marked incorporated, and the run transcript records the
addition. If it arrives after the last model request, it receives its own turn;
it is not lost. Repeat with a file: the file waits for its own turn.

From the **other participant**, send another addressed message while the first
run works. Expected: it remains that participant's task and does not steer the
first person's tool calls or borrow their personal connection.

## 6. Status and stop ownership

During your own active run, send in the same thread:

> @local-agenticos status

Then:

> @local-agenticos stop

Expected: status describes your latest root run. Stop ends it before the next
model request; an external action already in progress may finish. From the
other participant, `stop` must not stop your run. In a new thread without your
run, `status` says there is no task there.

## 7. Personal Notion without a linked identity

Use a participant whose Mattermost identity is not linked in the copied
instance. With a **personal** Notion binding, ask:

> @local-agenticos Wyszukaj w moim Notion stronę TESTOWA STRONA i podsumuj ją.

Expected: the agent explains the missing identity link and personal service
connection. The diagnostic result reports `execution=not_started`. It does not
use the publisher's or organization's Notion account. It does not ask to connect
unrelated services.

DM the bot:

> link

Open the private link, sign in to the **second** local instance and confirm.
Return to the original thread and ask again. If personal Notion is still absent,
the response asks to connect that service; it does not claim linking the chat
also authorized Notion.

Connect the personal service, then ask again. Expected: the run uses that
participant's connection. An expired/revoked authorization is explained as
requiring authorization again. Never post identity confirmation links in a room.

## 8. Configured approvals

With the intended organization MCP binding set to **Run freely**, ask for a
read-only search of the test page from an unlinked admitted participant.
Expected: the channel does not add an approval of its own. Then configure an
explicit **Ask first** policy, publish it and repeat. Expected: approval is
still required and the existing decision flow works.

For a personal binding, missing identity or credentials remain missing even
under Run freely. Approval is not a replacement for authentication. Test writes
only against a disposable test record whose modification you intend.

## 9. Reset, compaction and missing context

In the populated thread, send `/new` where the platform passes slash commands,
or use a new root thread. `/new` must not immediately reload the discussion it
just reset. A new root thread must not inherit another thread's context.

For a long thread that exceeds a provider page, inspect the persistent notice
about missing context and ask the bot to read the omitted section with the
history tool. The provider page need not be the latest 100 posts on every
platform. Compaction must reuse the shared conversation summary; native posts
already represented by that summary must not be reimported. These cases also
have automated PostgreSQL and transcript tests.

## 10. Worker loss and final-delivery recovery — with the developer

Coordinate these checks while inspecting the second instance's logs and jobs:

1. Receive a message, restart its worker before admission is processed, and
   verify the queued message survives.
2. Lose a worker after execution has started. Confirm the paid run and tool
   effects are not automatically repeated.
3. Interrupt after the terminal response is committed but before submission.
   Confirm a delivery job sends the saved answer without another model run.
4. Make submission's outcome ambiguous. Confirm it is recorded as unconfirmed
   and is not blindly retried.
5. Revoke access or move/reset the session before recovered delivery. Confirm
   the saved answer does not leak into a destination that no longer admits it.

## Evidence to collect

For every scenario, retain the Mattermost thread URL and the run ID. Inspect
native post IDs, imported reference messages, summary position, tool-call
identity, approval state and background-job outcome. Check for duplicate replies
and actions, not just a plausible final answer. The developer will correlate
these with the local API and worker logs.

## Adapter regression checks

The shared-context tests cover Mattermost, Slack and Discord. Native provider
fixtures additionally check that Slack message events, `/agent` and message
shortcuts commit admission before acknowledging in Socket Mode, including a
failed database write. Prompt-button acknowledgements remain immediate.
Telegram's real SDK polling iterator must keep its offset unchanged after a
failed write and retry the update. Discord's Gateway must keep reading while a
message waits on its metadata request. PostgreSQL tests send the same native
receipt twice for each platform and verify one job, with independent bot/thread
queues and no raw credentials in the payload. These checks do not post messages
to live Slack, Telegram or Discord accounts.

## Review regressions

- `/btw` has no thread concurrency key and always sets the tool-free aside context, including across workers. It cannot promise an idle model slot.
- Sender limits and access checks run before admission; transaction-scoped organization locks protect count and byte caps, including a separate control lane. Oversized/excess messages are acknowledged and discarded.
- Signed Discord/Teams attachment handles are organization-bound vault envelopes in jobs; `vault-rotate` includes retained channel jobs. Cross-tenant unwrap fails.
- The terminal transaction stores the rendered usage footer. Live delivery commits native assistant receipts with delivery settlement. Recovery leaves fenced completion to the worker runtime.
- A lease lost at a model boundary skips terminal writes; loss during the final request is checked again under a job-row lock before committing its answer.
- A history page missing the current native post or its timestamp adds a gap notice without importing future messages, fetching their files or advancing the cursor.
- Publication diagnostics inspect the bound agent and environment inside the organization, without requiring the manager to run that agent. Personal-service diagnostics still use the current caller.

The security review's proposal to restore approvals for unlinked participants is intentionally not adopted: this change explicitly honors authored Run freely/Ask first policies on channel exposures. The upgrade note tells operators to select Ask first or require linked accounts. Personal credentials and platform MCP write floors remain enforced.
