# Failure learning

An agent that keeps failing the same way is not learning — it is repeating.
The failure-learning loop mines the runs your agents already made, curates
the repeating failures into a ledger, and proves a fix against the old
behaviour before anything is applied.

Phase 1 covered mining, the ledger, eval cases and tries. Phase 2 adds
proposals and applying a fix: a proposal holds one rule-text change with
its eval evidence, and a publisher applies it in one audited action.
Phase 3 adds the console pages, the daily digest, and the per-agent
rule counts.

## What it mines

Mining is live SQL over `agent_runs` and `message_ratings` — no ETL, no
background job. It looks back seven days by default and surfaces four
signals:

| Signal | What counts | Threshold |
|---|---|---|
| Failed runs | Top-level, non-test runs grouped by agent, model, status and error class | 3 per agent |
| A failure that follows a model | The same error class for one model across agents | 5 across agents |
| Stalled runs | A run still `running` whose heartbeat is older than 10 minutes | 1 |
| Down-rated answers | Assistant messages rated −1 | 3 |

A failed run's error class is parsed from the sentence the run recorded:
`ModelHTTPError` keeps its status code, an expired approval or question is
its own class, a usage limit is its own class, and loop-guard and budget
stops are classes too. Anything else is `other`.

Two limits are worth knowing. A run stuck in a model call keeps beating its
heartbeat, so a hang with a fresh heartbeat is **not detectable** — stalled
means heartbeat-stale, nothing more. And a down-rated answer is attributed
to the nearest run started before it in the same conversation; a message
with no earlier run has no attribution and is dropped.

## The ledger

A pattern worth acting on becomes a ledger entry: a title, a summary, the
evidence, and a status — `draft`, `open`, `dismissed`, or `resolved`. An
entry is open while it is `draft` or `open`, and only one open entry may
exist per pattern per scope. That is enforced by a partial unique index,
not by convention.

Entries are scoped to an agent or to a model. A model entry is a record for
the whole organization and lists beside every agent's entries. A pattern
with an open entry is marked `already_tracked` when mining runs, so the
same failure is not curated twice.

Resolving an entry is the apply's job: a bare status change to `resolved`
is refused, and only applying a proposal against the entry resolves it.

## Eval cases

An eval case is the proof a fix has to pass: an input and what its answer
should say. An agent holds at most 50 cases. A case names an expectation —
`equals`, `contains` or `not_contains` on the answer text or the run
status — and may name the ledger entry it came from, a source run that
showed the failure, and a model profile to try under.

## Trying a fix

A try runs each case twice per sample: once on the current published spec
(the old side) and once on the same spec with the instructions replaced
(the new side). Each run opens a fresh test conversation, runs as a test
run, and is excluded from mining by the `is_test` filter. Samples default
to 1 and cap at 5.

The gate is strict. A side passes only when its run completed **and** the
expectation passes — a run that crashed cannot pass by crashing. A case
passes only when the old side fails and the new side passes, by a majority
of samples when there is more than one. A try passes only when every case
passes. When the old side already passes, the case is reported as not
reproducing: "case does not reproduce - the old text already passes".

Verdicts are judged when the try is read, never stored. A run still going
leaves its case pending.

A try may name a draft proposal instead of an instructions override: it runs
the proposal's new instructions or skill content, so the try is evidence for
that exact proposal. Tries record the proposal id and tested content's
SHA-256; apply refuses unless the linked passing try belongs to that proposal
and hash.

A try runs synchronously in the request and is capped at ten agent runs
(two sides per case sample). Each agent run may make multiple provider
requests, so this is not a provider-request cap. Larger requests are rejected
before agent runs start. Background execution remains a separate follow-up.

## Proposals

A proposal is one rule-text change: the text it replaces, the text that
replaces it, why, and the eval try that evidences it. It names its target —
the agent's instructions, or one skill — and the ledger entry it came from,
if any. A proposal is `draft` until it is applied or rejected; applying is
the approval, and there is no separate approve step.

An instruction proposal is written against the agent's current published
version, unless the body names one. A skill proposal is written against
the skill's content as it stands, and records its SHA-256 hash as the
base. The applied-changes list is the proposals list filtered to
`status=applied`: each entry carries the version it published and the try
that evidenced it.

Skill proposals are eval-gated too. A try runs the proposed skill content
as an in-memory override on the test side and does not write to the skill.

## Applying a proposal

Applying is a human act by a publisher, in the request's transaction, and
it is audited. For an instruction target the apply refuses unless the
linked try exists and gate-passed, judged as its runs stand at that
moment — a try that is missing, pending, or failed cannot land. That is
the gate, checked at apply time rather than stored.

Two guards protect the publish. Optimistic concurrency refuses with 409
unless the agent's current version is still the version the proposal was
written against — someone republished since, so the proposer re-bases the
proposal instead of overwriting a newer publish. The draft guard refuses
with 409 if the agent has unpublished draft edits — a builder's
in-progress work must be published or discarded first, because the apply
saves over the draft.

With the guards passed, the apply loads the draft spec, sets its
instructions to the proposal's new text, saves the draft, and publishes
it, noting the proposal's id. The published version is the frozen new
text, and the proposal records it as the rollback handle. The linked
ledger entry, if any, is marked resolved, and the audit entry records the
proposal, the version, the try, and the base version.

A skill apply requires the linked try to have passed and records its exact
new-content hash. It refuses with 409 unless the live skill still hashes
to the proposal's base hash, then snapshots the prior content on the
proposal before editing. The one-shot revert endpoint restores that
snapshot only while the live skill matches the applied hash; it records
who reverted and an audit entry, and never overwrites later edits.

Undoing an instruction apply is the existing rollback: publish a new
version copied from the base version the proposal recorded. There is no
special loop endpoint for it. A rejection is recorded in the audit trail
with its reason — the proposal row itself carries no decision note.

## The console

The loop lives in the console, on the agent page and on one org-wide
page. The agent page carries a Failure learning tab; the org-wide page
lists every agent's patterns in one place, under Monitoring in the
navigation. Reading needs `agents:view`; curating needs `agents:edit`,
applying an instruction proposal needs `agents:publish`, and applying a
skill proposal needs `skills:edit` on the skill.

### Patterns

The patterns panel lists what the last seven days mined, with the count
and whether the pattern is already tracked. The caveats mining carries
are shown beside the numbers, not hidden: per-model patterns are
approximate, a hang with a fresh heartbeat is not detectable, and a
down-rated answer is only approximately attributed. Tracking a pattern
from the panel opens the ledger form with the pattern filled in.

### Ledger entries

The ledger lists entries with a status filter, and selecting one shows
its eval cases and proposals. Accepting a draft opens it; dismissing one
asks for a reason, and the reason is kept on the entry so the record
survives. Deleting an entry removes it — its eval cases keep what they
said, and record the entry as gone.

### Eval cases and tries

The cases panel lists each case with its latest try's verdict. A case is
created from the run that showed the failure: give the source run id and
load its last user message, with the turns before it as history, then cut
the message down to the failing part and write what the answer should
say. A try runs over the cases checked, with a number of samples and
either a draft proposal's new text or a typed override — never both.
Requests above ten agent runs are rejected before they run. A try that passes the gate offers its text as a proposal,
pre-filled with the try as its evidence.

### Proposal review

Selecting a proposal shows the change as a diff, the eval evidence with
its per-case gate verdicts, and the apply and reject actions. An
instruction proposal applies only once its try has passed the gate, and
only a holder of `agents:publish` sees the apply control. A skill proposal needs a passing try for its exact content; its rollback
control restores the saved content if the skill has not changed since. An
applied proposal records the version it published, with the rollback
hint — undo it by rolling back to the base version it recorded.

### How many rules are live

The top of the tab counts the rules the loop has put into this agent:
applied proposals, open entries, and resolved entries, as three separate
figures. Applied proposals are the rules live in the instructions now.
Open entries are the rules still being worked — an entry is open while
it is draft or open. A resolved entry is its applied proposal, so the
two are counted separately, never added: adding them would count one
rule twice.

That count is a prompt, not a verdict. Rules accumulate — every applied
proposal is a sentence the agent must honour alongside all the others —
so re-audit the live rules once a quarter: read the applied-changes
list, and retire the ones the agent no longer needs by editing the
instructions, rather than leaving them to be re-learned.

## The daily digest

Once a day, a scheduled job — `failure-ledger-digest` — mines the last
seven days for every organization and snapshots each new pattern into a
draft ledger entry, then mails one digest per organization that has
anything new to the deployment's configured recipient. An organization
with nothing new gets no mail. The entries are drafts, never open: a
draft is a pattern the mining found, not one a curator accepted.

The recipient is configuration, not a default. Set
`FAILURE_LEARNING_DIGEST_RECIPIENT` to the address the digests go to;
while it is empty the job does nothing at all — it creates no draft
entries and sends no mail. It is one address for the whole deployment,
so it sees every organization's digest: make it an operator address, not
a member's. See [the settings reference](configuration.md#email-smtp).

## Permissions

| Route | Permission |
|---|---|
| `GET /v1/failure-learning/patterns` | `runs:view` |
| Per-agent patterns, ledger and eval reads | `agents:view` |
| Per-agent ledger, case and try writes | `agents:edit` |
| Proposing a change, rejecting a proposal | `agents:edit` (instructions) / `skills:edit` (skill target) |
| Applying an instruction proposal | `agents:publish` |
| Applying a skill proposal | `skills:edit` on the skill |

Only the org-wide patterns list carries a route gate. The per-agent routes
resolve access against the agent inside the service, and a refusal reads as
not-found — so a viewer holding an explicit grant on one agent is not
refused before the grant is consulted.

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/failure-learning/patterns` | Org-wide patterns |
| `GET` | `/v1/agents/{agent_id}/failure-learning/patterns` | One agent's patterns |
| `GET` | `/v1/agents/{agent_id}/failure-learning/ledger` | List ledger entries |
| `POST` | `/v1/agents/{agent_id}/failure-learning/ledger` | Curate a pattern |
| `GET` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | One entry |
| `PATCH` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Accept, dismiss, rewrite |
| `DELETE` | `/v1/agents/{agent_id}/failure-learning/ledger/{entry_id}` | Remove an entry |
| `GET` | `/v1/agents/{agent_id}/failure-learning/eval-cases` | List eval cases |
| `POST` | `/v1/agents/{agent_id}/failure-learning/eval-cases` | Add a case |
| `DELETE` | `/v1/agents/{agent_id}/failure-learning/eval-cases/{case_id}` | Remove a case |
| `POST` | `/v1/agents/{agent_id}/failure-learning/eval-runs` | Start a try |
| `GET` | `/v1/agents/{agent_id}/failure-learning/eval-runs/{try_id}` | Read a try, judged as it stands |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals` | Propose a change |
| `GET` | `/v1/agents/{agent_id}/failure-learning/proposals` | List proposals; `status=applied` is the applied-changes list |
| `GET` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}` | One proposal, with its eval evidence |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}/apply` | Apply a proposal, audited |
| `POST` | `/v1/agents/{agent_id}/failure-learning/proposals/{proposal_id}/reject` | Reject a proposal, with a reason |

Starting a try is rate-limited on the `agent_eval_run` surface, and each
side-run counts against the caller's budget like any run. A try naming a
`proposal_id` runs that proposal's new text; naming both a proposal and an
override is refused.

## Frequently asked questions

### Why does a failure I can see not appear as a pattern?

It is below a threshold, outside the seven-day window, a test run, or a
delegated run. Delegations are counted inside their parent, and test runs
are the loop's own tries — mining either would learn from itself.

### Why did my try take so long?

Tries run synchronously: every case runs twice per sample, one agent run
after another, inside the request. A try can start at most ten agent runs;
each run may make multiple provider requests.

### Can a try change what my agent says?

No. Both sides run as test runs against a frozen copy of the spec. The
published agent is untouched until a proposal is applied.

### What if the agent was republished since I proposed?

The apply refuses with 409. Re-base the proposal on the new version —
write it again against what the agent publishes now — instead of
overwriting the newer publish.

### How do I undo an apply?

Roll back to the base version the proposal recorded: the existing rollback
publishes a new version copied from it, so the timeline shows the rollback
happened. A skill apply can be reverted once from its snapshot if the skill still
has the applied content.

### What happens when I apply a skill change?

Every agent bound to the skill runs the new content on its next run. The
proposal's passing eval covers the exact new content; rollback restores the
previous content unless a later edit changed the skill.

### Where do I see the new patterns each day?

In your inbox, if the deployment configured a digest recipient — one
mail per organization with anything new, a logged no-op when unset or
when there is nothing —
and on the org-wide patterns page, which lists every agent's patterns
in one place.
