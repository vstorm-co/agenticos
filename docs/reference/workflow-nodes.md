# Workflow nodes { #workflow-nodes }

Every step a workflow can contain, with what it is configured with, what it
reads, what it produces and what a failure means. The palette in the editor
lists the same nodes from the same registry. The field documentation below is
generated from the source.

A few rules hold for every node:

- **An edge sets order, and a binding carries a value.** A node's input fields
  are bound to earlier outputs, to a literal, or to a file or table reference.
  See [Configuring a node](../workflows.md#configuring-a-node).
- **A path into a free-form value is checked when the node runs.** A trigger's
  payload, a mapped record and an agent's structured answer have no fixed
  shape, so a binding such as `payload.email` is accepted at publish time and
  validated against its target when the node is dispatched. A value that does
  not fit fails the run with `INVALID_BINDING`, and the handler never sees it.
- **Resources are checked twice.** Publishing refuses a collection, agent
  version, credential or recipient that the graph's author cannot reach. Each
  run checks it again against the run's own principal, because access can be
  withdrawn in between.
- **Effect kind and retries** decide what the engine may do after a failure. A
  `pure` or `idempotent` step is retried. A step that may already have acted
  and gives no guarantee stops for a person instead. A node's own
  [policy](#error-handling) sets how often it is retried, how long a call may
  take and where a failure goes.

## Triggers { #triggers }

A workflow starts from one trigger, the node its graph begins at. Publishing a
version switches its trigger on; see
[Starting a workflow from outside the console](../workflows.md#starting-a-workflow-from-outside-the-console).
Each trigger hands the steps after it what its surface started the run with, frozen
when the run is admitted and at most `WORKFLOW_RUN_MAX_INPUT_BYTES`. A test run
started with an input of another shape fails the trigger with
`TRIGGER_INPUT_INVALID`. A second trigger, or a trigger that is not where the graph
starts, is refused at publish.

### core.input { #core-input }

**API request.** Started from an HTTP request or over a WebSocket. It hands the graph the run's input as `payload`, whatever the caller sent, and names the surface in `triggered_by`. Its id stays `core.input`, so a graph written before Manual and API were separate still starts from the API.

::: app.workflows.contracts.io.WorkflowInputPayload

Its **Input fields** make the input a contract. A field has a name, a type - text,
number, whole number, yes or no, date or choice - and whether it is required. With
none, a run takes any JSON object. With some, **Start a run** asks for each by name,
a run whose input misses one, sends one of the wrong type or sends one not declared
is refused before it starts with `WORKFLOW_RUN_INPUT_INVALID`, and a binding to
`payload.<field>` is type-checked at publish.

::: app.workflows.contracts.fields.InputField

### trigger.manual { #trigger-manual }

**Manual.** Started by a person - **Test draft** in the editor, or **Start a run** on its
runs page. It hands the graph what **API request** does and takes the same input
fields, which the editor asks for before the run starts.

### trigger.chat { #trigger-chat }

**Chat message.** Started by a message in the chat, with this workflow picked to
answer. Its `core.output` text is written back into that conversation.

::: app.workflows.nodes._triggers.ChatTriggerOutput

### trigger.webhook { #trigger-webhook }

**Webhook.** Started by a signed delivery to the workflow's own address, which the
first publish of the node creates along with its signing secret.

Before it is published, **Listen for test event** in the trigger's Output pane
opens a test URL for the draft for two minutes. The one call sent to it, a JSON
object, is pinned as the trigger's output, so each step after it can be tested
on a real delivery. The test URL checks no signature and never starts a run.

::: app.workflows.nodes._triggers.WebhookTriggerOutput

### trigger.schedule { #trigger-schedule }

**Schedule.** Started on a clock, in the workflow's timezone and at most once a
minute.

::: app.workflows.nodes._triggers.ScheduleTriggerConfig

::: app.workflows.nodes._triggers.ScheduleTriggerOutput

### trigger.table_record { #trigger-table-record }

**Table record.** Started by a record of its table being added, changed or deleted -
whichever its `events` name - that matches every filter. A change starts it only when a
column chosen for the table changed, when columns are chosen. Publishing it needs read
access to the table.

::: app.workflows.nodes._triggers.TableRecordTriggerConfig

::: app.workflows.nodes._triggers.TableRecordTriggerOutput

### trigger.workflow_call { #trigger-workflow-call }

**Called by a workflow.** Started by another workflow's `workflow.run` step, with
the fields it declares - the same fields as **Manual** - and never by hand or over
the API. The caller's input is checked against them before the run starts.

### trigger.form { #trigger-form }

**Form.** Started by somebody filling in the workflow's public page, at the link the
first publish of the node creates. The page shows its title, description and one box
per field - the same fields as **Manual** - and a submission that fits them starts a
run as the member who published it. `triggered_by` is `form`.

::: app.workflows.nodes.trigger_form._handler.FormTriggerConfig

### trigger.github { #trigger-github }

**GitHub.** Started by a delivery GitHub signs for the repository, one of the events
and - when it names any - one of the actions the node names. Publishing registers the
hook through the organization's connected GitHub account when it can, or shows the
secret once to paste. `triggered_by` is `github`.

::: app.workflows.nodes.trigger_github._handler.GithubTriggerConfig

::: app.workflows.nodes._triggers.GithubTriggerOutput

### trigger.gmail { #trigger-gmail }

**Gmail.** Started by a new message in the organization's connected Gmail mailbox that
fits every filter set, read once a minute. Publishing is refused until a mailbox is
connected. `triggered_by` is `gmail`. **Sender contains** matches the sender's
address, not the display name: `@acme.com` is that domain exactly, not its
subdomains. With it set, the message must also pass the authenticated-sender check
(DMARC, or a DKIM signature from the sender's domain). Mail labelled `SENT`,
`DRAFT`, `SPAM` or `TRASH` is skipped unless **Label** names it.

The output carries the thread - `thread_id`, `rfc_message_id`, `in_reply_to`,
`references`, `received_at` - and the `html` body, read up to 20,000 characters. The
sender writes the header fields, so they thread a reply and prove nothing about who
sent it.

A run the mailbox started stores the message's attachments as files of the run. A
mailbox lists at most 20 per message and only the first 10 listed are considered, up
to 25 MiB together, each within the chat-upload size limit and file type allowlist
and the organization's storage quota. An attachment left out keeps its place in
`attachments` with a `reason`: `too_many`, `too_large`, `type_not_allowed`, `quota`,
`unreadable` or `not_fetched`. A run the mailbox did not start - a test run - reads
nothing, so every attachment is `not_fetched`.

`unreadable` is an answer of 400, 401, 403 or 404 for the attachment, or a mailbox
grant that is missing, switched off or cannot be renewed. Any other provider failure
fails the step with `MAIL_ATTACHMENT_UNREACHABLE`, which is retried. Both mail
triggers take outside input.

::: app.workflows.nodes.trigger_gmail._handler.GmailTriggerConfig

::: app.workflows.nodes._triggers.EmailTriggerOutput

::: app.workflows.nodes._triggers.MailAttachment

### trigger.outlook { #trigger-outlook }

**Outlook.** Started by a new message in a folder of the organization's connected
Microsoft 365 mailbox that fits every filter set, read once a minute. Publishing is
refused until a mailbox is connected. `triggered_by` is `outlook`. Microsoft Graph
is read one folder at a time, so **Folder** and **Shared mailbox** are where the
poll looks as well as a filter, and the first read of a folder starts at the moment
the workflow was published or last switched on. Anyone who can publish a workflow can
name any shared mailbox the organization's Microsoft grant can open, as Outlook agent
triggers already can. **Sender contains** matches the sender's address, as
for Gmail, and needs mail the sender's domain authenticated or that came from inside
the tenant. A folder or shared mailbox Outlook says cannot be read switches the
workflow off, with `mailbox_folder_unreadable` in the audit log. A stored
configuration that no longer validates is skipped by the poll. The attachments are
staged as for [trigger.gmail](#trigger-gmail), and `labels` holds the message's
categories. Its output is the one of [trigger.gmail](#trigger-gmail).

::: app.workflows.nodes.trigger_outlook._handler.OutlookTriggerConfig

### trigger.channel_message { #trigger-channel-message }

**Channel message.** Started by a message to one of the organization's Slack,
Mattermost or Telegram bots that the bot would have answered with its own agent and
that fits the node's filter. Publishing it needs `channels:manage`, and a bot's
messages start one workflow at most. `triggered_by` is `channel_message`.

::: app.workflows.nodes.trigger_channel_message._handler.ChannelMessageTriggerConfig
    options:
      show_bases: false

::: app.workflows.nodes._triggers.ChannelMessageTriggerOutput

### trigger.workflow_failed { #trigger-workflow-failed }

**On failure of a workflow.** Started once for each real run that fails of a
workflow whose settings name this one as its error workflow, as the member who
chose it. A run this trigger started never starts an error workflow itself.

::: app.workflows.nodes._triggers.WorkflowFailedTriggerOutput

## core.output { #core-output }

What the workflow answers. Its bound fields become the run's `output`, which
the API returns and the invoking surface delivers. It has the same fields as
`agent.run`'s output, so an agent's answer binds straight across. An output
with nothing bound is an empty answer.

::: app.workflows.contracts.io.WorkflowOutputPayload

## webhook.respond { #webhook-respond }

**Respond to webhook.** Answers the delivery that started the run with a status
(200 to 599), headers and a JSON `body` bound from an earlier step. A delivery to
a graph holding this step waits for it instead of taking `202`, for at most
`WORKFLOW_WEBHOOK_RESPONSE_TIMEOUT_SECONDS`. The first respond step to complete
is the answer, a retry of the same delivery gets it again, and the run goes on
after it. A run that ends without reaching the step answers `202` if it
succeeded and `500` if it did not. Headers the API's own response owns are
refused at publish: framing, `Content-Type`, `Set-Cookie`, and the CORS and
browser-policy headers.

::: app.workflows.nodes.webhook_respond.WebhookRespondConfig

## data.map { #data-map }

Builds a small typed record from earlier outputs. Each mapping reads one value
with a JMESPath expression and converts it to `string`, `number`, `integer`,
`boolean`, `json`, `file_ref` or `table_ref`. A value that cannot be converted
fails with `MAPPING_COERCION_FAILED` and names the field.

::: app.workflows.nodes.data_map._handler.DataMapConfig

::: app.workflows.nodes.data_map._handler.FieldMapping

## data.filter and data.combine { #data-filter-and-data-combine }

**Filter a list** keeps the items of a bound list for which a JMESPath condition
over `item` and `index` holds, and says how many it dropped. **Combine lists**
makes one list of `first` and `second`: `append` puts one after the other,
`by_position` merges the objects at the same position, and `by_key` merges into
each object of the first the second's object with the same `key`. Where both have
a field, the second's wins; merging item by item needs objects, and fails with
`COMBINE_NEEDS_OBJECTS` otherwise.

::: app.workflows.nodes.data_filter._handler.DataFilterConfig

::: app.workflows.nodes.data_combine._handler.DataCombineConfig

## text.compare { #text-compare }

**Compare texts** scores how alike two texts, `a` and `b`, are: 1 when they are the
same once the ignored differences are set aside, 0 when they have nothing in common.
It calls no model and costs nothing, and the same two texts always give the same
numbers (scores are rounded to six places). The **method** says what is counted:

- `char_ratio` (the default) is the share of characters an editor would not have to
  touch, from the exact edit distance over characters.
- `token_f1` is the share of words the two texts have in common, order ignored.
- `line_diff` is the share of lines that are unchanged.

Composed and decomposed accents are never an edit, and nor are line endings. The
rest is up to the step. **Ignore whitespace** is on by default: it collapses the
spacing within a line, trims each line and drops blank lines. Line breaks still
count, so only `token_f1`, which counts words, ignores where a line ends. **Ignore
case** and **Ignore punctuation** are off by default. The words of `token_f1` are
runs of letters, digits and underscores: it splits on apostrophes and does not
segment text written without spaces.

**Leave out quoted mail and signatures** drops every line whose first
non-whitespace character is `>` (indented quotes too), the attribution line above
a quote, and everything after a `-- ` or bare `--` signature separator or an
`----- Original Message -----` line. It is a heuristic for plain-text mail: it
does not catch HTML quotes, a reply whose quote is not marked with `>`, an
attribution wrapped over two lines (it stays in) or a signature with no separator.

Each text is at most 100,000 characters, counted before any normalising; scoring two
texts of that size takes a few seconds. A longer text ends the run with
`INVALID_BINDING` before the step runs, so `error.handle` cannot route it. A step
with nothing bound to `a` and `b` fails with `TEXT_COMPARE_NOT_CONFIGURED`; one
bound and the other not ends the run with `INVALID_BINDING`. Empty texts are
allowed: two empty texts score 1, one empty text scores 0. The palette draws the
step with a diff icon, under the data steps.

::: app.workflows.nodes.text_compare._handler.TextCompareConfig

::: app.workflows.nodes.text_compare._handler.TextCompareOutput

## Transform { #transform }

The **Transform** steps reshape a list of objects without a code step. Each takes
`items`, a list bound from an earlier step, and most hand on `items`, so they
chain.

| Step | Does |
|---|---|
| `transform.edit_fields` | Sets fields from JMESPath expressions over each `item`, removes fields, or keeps only the ones set |
| `transform.sort` | Sorts by fields in turn, ascending or descending |
| `transform.limit` | Keeps the first or the last items |
| `transform.remove_duplicates` | Keeps the first of each set of items equal on the fields named, or on the whole item |
| `transform.aggregate` | Collects each field's values across the items into one list per field, as `values` |
| `transform.split_out` | Turns a list inside each item into items of their own |
| `transform.summarize` | Counts, sums, averages, finds the least or greatest, or counts the distinct values, by group |
| `transform.date_time` | Now, or a bound `value` moved by an amount, written out in a timezone - the workflow's unless the step names one |
| `transform.crypto` | Hashes or base64-encodes the bound `text`, or makes a UUID or random hex |

A field is a dotted path, `customer.email`, and an item without it is never an
error. Sort puts it last, Remove duplicates treats "missing" as a value of its
own, Aggregate and Summarize leave it out, Split out keeps the item as it is, and
Edit fields sets `null` where its expression finds nothing. Crypto is not for
secrets: nothing in it is keyed.

Chained, they answer common questions with no code step:

- **The best leads, once each** - **Remove duplicates** on `email`, **Sort** by
  `score` descending, **Limit** to 10, then **Edit fields** keeping only `name` and
  `score`, ready for a message.
- **Totals by region** - **Split out** `lines`, so each order line is an item, then
  **Summarize** the `sum` of `amount` grouped by `region`: one item per region with
  `sum_amount`.
- **One list of addresses** - **Aggregate** `email` hands on `values.email`, every
  address in one list, for any setting that takes a list.

Each step reads `items` from the one before. `tests/integration/test_workflow_transform_composed.py`
runs the first two as written.

::: app.workflows.nodes.transform._handler.EditFieldsConfig

::: app.workflows.nodes.transform._handler.SummarizeConfig

::: app.workflows.nodes.transform._handler.DateTimeConfig

## logic.if and logic.merge { #logic-if-and-logic-merge }

`logic.if` evaluates a JMESPath condition over its bound `value` and continues
down the `true` or the `false` port. Every node on the untaken branch is
recorded as `skipped`. `logic.merge` rejoins the two branches. It runs once the
taken branch reaches it and passes that branch's output on as `value`.
Publishing checks that a merge's inputs leave one `logic.if` through different
ports, so exactly one of them ever runs.

Expressions can select, filter and compare, and call a fixed set of pure
functions: `abs`, `avg`, `ceil`, `contains`, `ends_with`, `floor`, `join`,
`keys`, `length`, `max`, `merge`, `min`, `not_null`, `reverse`, `sort`,
`starts_with`, `sum`, `to_array`, `to_number`, `to_string`, `type` and
`values`. Null, `false`, and an empty string, list or object are false, and
everything else is true, including `0`. An expression that does not parse, or
calls anything else, cannot be published.

::: app.workflows.nodes.logic_if._handler.LogicIfConfig

::: app.workflows.nodes.logic_merge._handler.LogicMergeOutput

## logic.switch { #logic-switch }

**Switch.** Sends the run down the first of many branches whose rule holds. Each
rule has a name, which is its branch's port, and a JMESPath condition over the
bound `value`, tried in order; `otherwise` takes the run when none holds. Its
branches rejoin at a `logic.merge`, which accepts them because exactly one is ever
taken. A rule that fails on its data fails the step with `CONDITION_FAILED` and
names the rule.

::: app.workflows.nodes.logic_switch._handler.LogicSwitchConfig

::: app.workflows.nodes.logic_switch._handler.LogicSwitchOutput

## knowledge.search { #knowledge-search }

Searches knowledge collections for a bound `query` and returns the passages as
typed sources, best first. An empty result is a successful search. A
collection that is gone, or no longer readable by the run's principal, fails
the step with `COLLECTION_NOT_ACCESSIBLE`. The step never searches fewer
collections than the graph names.

::: app.workflows.nodes.knowledge_search._handler.KnowledgeSearchConfig

::: app.workflows.contracts.io.SourceRef

## knowledge.add { #knowledge-add }

Adds a bound text with a `title`, or a run file, to one to five knowledge
collections, through the same upload a collection's page uses: its own parsing
and chunking settings, the organization's budget check, and ingestion queued
rather than waited for. A text is stored as `<title>.md`, and a document of the
same name is replaced rather than duplicated, so a retry updates it. A
collection the principal may not add to fails the step with
`KNOWLEDGE_ADD_REFUSED`.

::: app.workflows.nodes.knowledge_add._handler.KnowledgeAddConfig

## Model steps { #model-steps }

Four steps ask one of the organization's models one thing, with no tools. Each
runs as the step's own agent - created on its first run, republished when its
settings change - through the same runner as `agent.run`, so the step's
`max_cost_usd`, the workflow's budget and the organization's limit are checked
before the request, its cost is booked on the run, and it shows in Activity.
Publishing checks that the author may use the model.

| Step | Does | Hands on |
|---|---|---|
| `ai.prompt` | Answers a bound `prompt` under the step's `instructions` | `text`, and `structured` when `structured_output_schema` asks for an object |
| `ai.classify` | Puts a bound `text` in one of the step's `categories`, or `other` | Leaves by the category's port, with the `category`, a one-sentence `reason`, the `text` and `confidence`; below `min_confidence`, by `unsure` |
| `ai.extract` | Pulls the fields `output_schema` names out of a bound `text`, leaving out what it does not say | `data`, an object of that shape |
| `ai.rewrite` | Summarizes (`short`, `medium`, `long`), translates into `language`, or rewrites a bound `text` in a `style` | `text` |

A classifier's categories are its ports, in order, and the model can only
answer with one of their names or `other`. An answer that is not the object a
step asked for fails it with `STRUCTURED_OUTPUT_MISMATCH`; a spent limit fails
it with `AGENT_BUDGET_EXCEEDED`.

With `min_confidence` set, the model also reports its own confidence in the
category, from 0 to 1. That is its say-so, not a probability, and it is not
calibrated: test a threshold on your own cases with the step's
[evals](../workflows.md#evals-for-a-model-step) before trusting it. The minimum
adds an `unsure` port after `other`: below it the step leaves by that port,
carrying the same output, so the `category` is still there for the workflow to use.

Without a minimum the model is not asked for a number, the prompt is unchanged,
`confidence` is null and the category always wins. An answer with no number never
leaves by `unsure`, and while the port exists `unsure` cannot be a category name.

::: app.workflows.nodes.ai_classify._handler.AiClassifyConfig

::: app.workflows.nodes.ai_classify._handler.AiClassifyOutput

## Decisions { #decisions }

Three steps ask TypeSafe's Jev a typed question about a bound `text`, with a
TypeSafe API key from the vault. Jev does not write text: it answers the
question with a confidence from 0 to 1, in one request, and it can only answer
with one of the answers the step allows. Below the step's `min_confidence` the
step leaves by its `unsure` port instead, so a workflow decides there what a
person or an agent does with a doubtful case.

`decide.*` calls TypeSafe's hosted Jev only. To route doubtful cases on a
self-hosted model, use `ai.classify` with `min_confidence`, which leaves by
`unsure` the same way.

| Step | Asks | Leaves by |
|---|---|---|
| `decide.yes_no` | a yes-or-no question | `yes`, `no` or `unsure` |
| `decide.choose` | which of up to 255 options fits | `out` with the `choice`, or `unsure` |
| `decide.score` | where the text sits on a rubric of 2 to 10 levels | `out` with the `score`, or `unsure` |

The key is checked at publish and read again on every run. A key that is gone
or unshared fails the step with `SECRET_NOT_USABLE`, a model that does not
answer with `DECISION_FAILED`, which is retried as the step's policy says, and a
deployment built without the `browser` extra with `DECISION_MODEL_UNAVAILABLE`.
A merge may rejoin a decision's branches, as it rejoins an If / else step's.

::: app.workflows.nodes._decide.DecisionConfig

::: app.workflows.nodes.decide_choose._handler.ChooseConfig
    options:
      show_bases: false

::: app.workflows.nodes.decide_score._handler.ScoreConfig
    options:
      show_bases: false

## Channels { #channels }

Slack, Mattermost and Telegram each have a group of steps of their own that act
as one of the organization's bots on that platform, through the adapter its replies
already go through, so a message a workflow sends arrives as that bot, and a step
can read what the bot may read. A platform has only the steps its bots can take.

| Step | Slack | Mattermost | Telegram | Hands on |
|---|---|---|---|---|
| **Send a message** (`<platform>.message.send`) | yes | yes | yes | where it was sent |
| **Read messages** (`<platform>.messages.read`) | yes | yes | - | `messages`, oldest first |
| **List members** (`<platform>.members.list`) | yes | yes | administrators | `members`, with their platform ids |
| **Find channels** (`<platform>.channels.find`) | yes | yes | - | `channels` |

A step takes a bot of its own platform only, and a bot speaks for the whole
organization, so acting as one needs `channels:manage`: the graph's author to
publish, the run's principal on every run. A bot deleted, switched off or of another
platform stops the step with `CHANNEL_NOT_USABLE`. A platform that refuses a call at
run time fails it with `CHANNEL_UNSUPPORTED`, and one that does not answer with
`CHANNEL_CALL_FAILED`. Sending is never repeated on its own.

::: app.workflows.nodes._channels.ChannelBotConfig

::: app.workflows.nodes.channel_read._handler.ChannelReadConfig
    options:
      show_bases: false

::: app.workflows.nodes.channel_read._handler.ChannelReadOutput

::: app.workflows.nodes.channel_members._handler.ChannelMembersOutput

::: app.workflows.nodes.channel_find._handler.ChannelFindOutput

## agent.run { #agent-run }

Asks a published agent, at the exact version the step pins, through the same
runner as chat and the API, with the agent's budget, approvals, guardrails and
run history. The run is recorded with the surface `workflow`. Bound `sources`
are appended to the prompt as numbered context. An approval-gated tool call
parks the step, and the decision resumes the same agent run.

`inline` configures the agent in the step instead of `agent`, and exactly one of
the two is set. The spec is the step's, versioned with the graph: the first run
creates an agent owned by the workflow, kept out of the catalog and reached
through the workflow's access, and a run whose spec differs from that agent's
newest version publishes one first, checked as publishing an agent is. Publishing
the workflow checks the spec against its author's access. `max_cost_usd` caps one
execution: the agent stops before a model request past it, and the step fails
with `AGENT_BUDGET_EXCEEDED`.

An agent with an answer format of its own hands its object on as `structured`.
`structured_output_schema` asks for another shape in its place: the agent is run
with that schema, and an answer that breaks it is sent back to the model to be
fixed. The object is checked once more before anything downstream runs. An
agent that never produces one that fits fails the step with `AGENT_RUN_FAILED`,
and an answer with no object where one was asked for fails it with
`STRUCTURED_OUTPUT_MISMATCH`.

| Agent run ended | Step result |
|---|---|
| Completed | Completed |
| Awaiting approval | Waits, then resumes the same run |
| Budget exceeded | `AGENT_BUDGET_EXCEEDED` |
| Guardrail blocked | `AGENT_GUARDRAIL_BLOCKED` |
| Otherwise | `AGENT_RUN_FAILED` |

Bound `attachments` are images from the run's files - a download, a rendered PDF
page, a transformed photo - shown to the agent as pictures rather than as a link it
cannot open. Only PNG, JPEG, WebP and GIF are shown. Any other file fails with
`UNSUPPORTED_ATTACHMENT_TYPE`, so read a document's text with `text.extract` first.

It is never retried automatically, because an agent may have called tools with
side effects.

::: app.workflows.nodes.agent_run._handler.AgentRunConfig

::: app.workflows.nodes.agent_run._handler.AgentRunOutput

## http.request { #http-request }

Calls an HTTP API. Every request and every redirect passes the deployment's
SSRF check and is sent to the address that check approved. A private host the operator
lists in [`OUTBOUND_PRIVATE_ALLOWLIST`](../configuration.md#project-settings) is admitted
too, but only for a URL that starts there: a redirect from a public URL never reaches it.

A URL bound from a public trigger (a webhook, a form, an email) or from an agent's tool arguments can name any listed host, so list only hosts that check their own credential.

A credential is an
[HTTP credential](../secrets.md#kinds) from the vault, and it is
sent only to the origins the secret allows. The response is read under
`max_response_bytes` and handed back without `Set-Cookie`, the authentication
headers or the token.

The credential goes as a bearer token, Basic authentication, a header you name
or, with `query`, a URL parameter you name. **Import cURL** in the editor reads a
command pasted from an API's docs into the method, URL, headers and JSON body. A
credential in the command is never kept in the step: the step is set to send it
the same way, and the vault form opens with it filled in.

A `GET` can page through a list with `pagination`: following a next URL the
response names, sending back a cursor, or counting a page parameter up. Each
page's `items_path` items are collected into `items`, in order. Paging stops when
there is no next page, when a page has no items, or at `max_pages`, when
`complete` is false. Every page together reads no more than
`max_response_bytes`, and a next page on another origin gets no credential.

| What happened | Result |
|---|---|
| The URL is loopback, metadata, not http(s), or private and not on the operator's [`OUTBOUND_PRIVATE_ALLOWLIST`](../configuration.md#project-settings) | `URL_REFUSED`, nothing sent |
| The URL is outside the credential's origins | `SECRET_ORIGIN_DENIED`, nothing sent |
| The connection never opened | `HTTP_UNREACHABLE`, retried |
| Sent, no answer, `GET` or an idempotency header | `HTTP_NO_RESPONSE`, retried |
| Sent, no answer, any other write | Uncertain: the run stops for a person |
| Non-2xx | `HTTP_ERROR_STATUS`, or the response as output with `on_error_status: complete` |
| Larger than the limit | `RESPONSE_TOO_LARGE` |
| A page's `items_path` finds something that is not a list | `PAGE_ITEMS_NOT_A_LIST` |

::: app.workflows.nodes.http_request._handler.HttpRequestConfig

::: app.workflows.nodes.http_request._handler.HttpAuth

::: app.workflows.nodes.http_request._handler.HttpPagination

::: app.workflows.nodes.http_request._handler.HttpRequestOutput

## mcp.call { #mcp-call }

**Call an MCP tool** calls one tool on one of the organization's
[MCP servers](../mcp.md), with `arguments` bound from earlier steps. The editor
offers the servers with their service's mark, then the tools the server listed
when it was last tested; **Refresh tools** tests it again. Each argument the
tool takes is then a field of its own, typed in or bound, as `arguments/<name>`. Only an
organization-owned server qualifies, never a member's own, and publishing
refuses a server that is not the organization's, is turned off, or did not list
the tool. The credential comes from the vault, as it does for an agent.

`approval` decides when a person approves the call first: `writes`, the
default, before any tool the server does not mark read-only; `all` before every
call; `none` never. The request goes to the **Approvals** tab, like
[human.approval](#human-approval), to `approvers` or to anyone holding
`approvals:decide`. Approved, the tool is called; rejected, the step fails with
`MCP_CALL_REJECTED`. A read-only mark is the server's own claim, so choose `all`
for a server you do not trust to make it.

The output is the answer's `text`, its `structured` data when the tool returns
some, and `is_error`. An error the tool answers with fails the step with
`MCP_TOOL_ERROR` unless `on_tool_error` is `complete`.

MCP has no idempotency key of its own. A server that takes one as a tool argument
can still be made safe to retry: set **Idempotency key argument**
(`idempotency_key_argument`) to that argument's name, and the step sends its stable
operation key there - the same on every attempt of the step, and different for each
iteration of a loop - whatever value was bound to it. The tool must declare the
argument as text.

Publishing refuses an argument that the tool's recorded
schema lacks, and a tool whose schema was not recorded passes, so test the server
first; at run time the step lists the server's tools before calling and fails with
`MCP_IDEMPOTENCY_ARGUMENT_UNDECLARED`, calling nothing, when the live schema has no
such argument. A keyed step counts as idempotent: the engine may run it again.

When the call breaks off, what happens next depends on whether it can have reached
the server:

- **Before the call** - the server could not be reached, or did not answer the
  connection or the tool listing - nothing was sent, and the step fails with a
  `MCP_CALL_FAILED` that is retried.
- **After the call, a keyed call or a tool the server marks read-only** (in the
  listing the step just read, else in the one recorded when the server was
  tested) - the same retried failure, because repeating it is safe.
- **After the call, any other tool, with no key** - the tool may have acted and no
  answer came back. The step ends **Uncertain** with *The tool was called and no
  answer came back; it may have acted*, and the run waits for a person, who looks
  at the other system before running the step again.

| What happened | Result |
|---|---|
| The server is gone or turned off | `MCP_SERVER_UNAVAILABLE`, nothing sent |
| Its credential needs authorizing again | `MCP_SERVER_UNAUTHORIZED`, nothing sent |
| The server does not offer the tool | `MCP_TOOL_NOT_FOUND` |
| The server could not be reached, or broke off, before or after a safe call | `MCP_CALL_FAILED`, retried |
| It broke off after an unkeyed call to a tool not known read-only | Uncertain: the run stops for a person |
| The tool does not declare the **Idempotency key argument** | `MCP_IDEMPOTENCY_ARGUMENT_UNDECLARED`, nothing sent |
| The tool answered with an error | `MCP_TOOL_ERROR`, or the answer as output |
| The structured answer is over 1 MiB | `MCP_RESULT_TOO_LARGE` |

::: app.workflows.nodes.mcp_call._handler.McpCallConfig

::: app.workflows.nodes.mcp_call._handler.McpCallOutput

## notification.send { #notification-send }

Notifies members of the organization in the app, by email, or both, through
the notification center. Recipients are members named by id. At run time each
one must still be an active member who can see the workflow, and anyone else is
dropped. If nobody is left, the step fails with `NO_PERMITTED_RECIPIENTS`. Each
person's preferences for **Workflow notifications** still apply. The step
completes when the notification is written, and email is delivered afterwards.
A retried step writes no second notification.

::: app.workflows.nodes.notification_send._handler.NotificationSendConfig

## email.send { #email-send }

Delivering providers reserve each unique recipient against shared Redis allowances before sending the whole batch: `WORKFLOW_EMAIL_MAX_PER_PRINCIPAL_PER_HOUR` (100), `WORKFLOW_EMAIL_MAX_PER_ORG_PER_HOUR` (500) and `WORKFLOW_EMAIL_MAX_PER_DEPLOYMENT_PER_HOUR` (1000). The principal limit spans keys and organizations of the same issuer. Fixed one-hour windows span runs and workers; their boundary can admit twice the allowance. Exhaustion gives `EMAIL_DELIVERY_LIMIT`; unavailable counters give `EMAIL_ALLOWANCE_UNAVAILABLE`, with no send. Reservations are conservative and not refunded after partial reservation, provider failure or cancellation. Log-only providers consume no delivery allowance. Set deployment capacity below the relay quota to leave transactional-mail headroom.

**Send an email** mails up to ten addresses from the deployment's own sender
and [email provider](../configuration.md), one copy to each, so no recipient
sees another's address. It is for people outside the organization, such as a
lead or a customer: members are reached through
[notification.send](#notification-send) and their preferences. `to`, `subject`
and the plain-text `body` are typed in or bound from earlier steps, and
`reply_to` sends replies somewhere other than the deployment's reply address.

The output lists the addresses the provider accepted. `delivered` is false when
the provider only logs mail, which is the development default, so a run never
claims it reached anyone it did not. A copy the provider refuses fails the step
with `EMAIL_NOT_SENT`, naming what was already sent. Mail has no idempotency
key, so a retried step sends again.

::: app.workflows.nodes.email_send._handler.EmailSendConfig

::: app.workflows.nodes.email_send._handler.EmailSendInput

::: app.workflows.nodes.email_send._handler.EmailSendOutput

## human.approval { #human-approval }

**Ask for approval** stops the run until a person approves or rejects what it is
about to do, then goes on by `approved` or `rejected`. The approver reads the
step's `title` and the `details` bound to it, in the **Approvals** tab of
Activity or over `GET /api/v1/workflow-approvals`. `approvers` names who may
decide, and they are notified in the app; left empty, anyone holding
`approvals:decide` may. Past `timeout_hours` the request expires and the step
leaves by `rejected` with `decision: "expired"`. Cancelling the run cancels what
it asked. Each run of the step asks once, so a retry or a loop iteration never
asks twice for the same thing.

Named approvers must be active members holding `approvals:decide`. Publishing checks this, and the step checks again before asking; a person who lost that permission fails the step with `APPROVER_UNAVAILABLE` rather than leaving an undecidable request.

A step can carry a **proposal**: text bound to `proposal`, such as a drafted
reply. The approver reads it next to the request. Turn `editable` on and the
queue shows it in an editor, as `text` or `markdown` (`proposal_format`) under
`proposal_label` (`Proposal` when empty), and the approver may approve a changed
version. A step with nothing bound opens an empty editor, for the case where
drafting produced nothing. `details` is unchanged and stays short; the proposal
may be up to 100,000 characters.

The approved output carries three fields besides the decision:

- `final` is the version the approver approved, the proposal itself when they
  changed nothing.
- `original` is the proposal as asked, `""` when an editable step had nothing
  bound.
- `edited` is true when `final` differs from `original`. Line endings,
  trailing spaces and blank space around the text are not a difference.

An edited version is stored with leading and trailing whitespace removed, so an
edit that begins with an indented code block loses that first indentation.

A step that is not `editable` shows its proposal read-only and, once approved,
hands it on unchanged as `final` with `edited` false, so later steps can bind
`final` whichever mode the step is in. A rejection or an expiry carries no
`final`. Sending an edited version to a step that is not `editable`, or with a
rejection, is refused with `422`. A decider the step does not name sees the
proposal read-only.

If the workflow sends the approved `final` through [`mcp.call`](#mcp-call), set
that step's `approval` to `none`, or the person is asked twice.

::: app.workflows.nodes.human_approval._handler.HumanApprovalConfig

::: app.workflows.nodes.human_approval._handler.HumanApprovalInput

::: app.workflows.nodes.human_approval._handler.HumanApprovalOutput

## flow.wait { #flow-wait }

**Wait.** Holds the run at the step for `seconds` after it is reached, or until a
bound `until`, then goes on; at most thirty days. The step is parked on a timer
whose dispatch row comes due then, so the wait survives a worker restart and holds
no worker, and other branches go on meanwhile. A moment already past goes on at
once, and the run's deadline still applies.
A bound `until` more than thirty days after the step is reached fails the step with `WAIT_TOO_LONG`.

With **Wait for a call to the run's resume link**, the step waits instead until the
address a **Resume link** step gave is called, at most `seconds` (thirty days when
unset). `POST` that address with a JSON object, or nothing: the step hands the body on
as `body`, with `called` true, and the run goes on. Nobody calling in time, it goes on
with `called` false. A call while nothing waits - before the step is reached, after
it went on, or once the run ended - is refused with `WORKFLOW_NOT_WAITING` (409), and a
link that is not the run's answers `404`.

::: app.workflows.nodes.flow_wait._handler.FlowWaitConfig

::: app.workflows.nodes.flow_wait._handler.FlowWaitOutput

## flow.resume_link { #flow-resume-link }

**Resume link.** Hands on `url`, the address that resumes this run's Wait steps
waiting for a call - for a message or a request before the Wait, so whoever answers
can go on with the run. Every run has its own, made from its id under the
deployment's secret and shown to nobody else: holding it is what lets a caller
resume the run, so it is sent only where the answer should come from.

::: app.workflows.nodes.flow_resume_link._handler.ResumeLinkOutput

## Error handling { #error-handling }

Every node takes an optional `policy` beside its config.

| Field | Default | Effect |
|---|---|---|
| `timeout_seconds` | none | A call still running after this long is cut off. A step with no external write, or one whose call is idempotent, fails with `NODE_TIMEOUT` and may be retried. A write that may have landed becomes uncertain and stops for a person |
| `retry.max_attempts` | `WORKFLOW_RETRY_CEILING` | Tries in total, the first included. Only a failure the node marks retryable is tried again, and publishing refuses more than one try for a step whose call is not safe to repeat |
| `retry.backoff`, `base_delay_seconds`, `max_delay_seconds` | `exponential`, `2`, `60` | The wait between tries: fixed, or doubling up to the ceiling |
| `on_error` | `fail_run` | `route` sends a failure that retries did not settle out of the node's `error` port instead of failing the run |

A node whose policy routes its errors has an extra `error` output port. It
carries the `WorkflowError`: `code`, `message`, `details` and `retryable`. The
node's normal output exists only on its other ports, so publishing refuses a
binding that reads the output on the error path, or the error on the success
path. The error port has to lead somewhere, and the two paths may rejoin at a
`logic.merge`.

`error.handle` takes that error on its `in` port and leaves by the first branch
whose `code` and `retryable` both match, or by `default`, which must be
connected. `error.raise` fails its branch with a code, a message and details
that the author sets.

Some failures are never routed. Revoked access, a spent budget (the run's or an
agent's), a cancelled run, a passed deadline, the per-run node ceiling and an
effect of unknown outcome end the run however the graph is wired. A revision
conflict or a validation error can be routed but is never retried blindly,
because the same input fails the same way again.

::: app.workflows.contracts.policy.NodePolicy

::: app.workflows.contracts.policy.RetryPolicy

::: app.workflows.nodes.error_handle._handler.ErrorHandleConfig

::: app.workflows.nodes.error_handle._handler.HandledError

::: app.workflows.nodes.error_raise._handler.ErrorRaiseConfig

## Loops { #loops }

`control.foreach` runs its body once for every element of a bound `items` list,
one element at a time and in order. It then continues through its `done` port
with `results` in input order, `errors` and `count`. The body starts at
`loop.item`, wired from the loop's `body` port, which provides `item`, `index`
and `count`. It ends at `loop.yield`, whose bound `value` is the iteration's
result. No edge leads back to the loop. A step in the body may bind to anything
that ran before the loop, and nothing outside the body may bind into it.

The list is frozen when the loop starts, so an iteration never sees a source
that changed during the run. A list longer than `WORKFLOW_FOREACH_MAX_ITEMS`, or
larger than `WORKFLOW_FOREACH_MAX_MANIFEST_BYTES`, is refused rather than
truncated. An empty list gives `results: []` without running the body. Each
iteration's steps run in their own scope, with their own attempts, idempotency
keys and costs. The next iteration is scheduled in the transaction that ends the
previous one, so a restart resumes at the right index and never repeats a
confirmed write. An approval inside an iteration resumes that iteration.

With `item_error_policy: stop`, the default, the loop fails at the first failed
iteration and the error's details carry that iteration's `scope_path`. With
`collect`, the item's result is `null`, the error is added to `errors` and the
loop carries on. Loops nest at most `WORKFLOW_FOREACH_MAX_DEPTH` deep, and
every node run a run creates counts against `WORKFLOW_RUN_MAX_NODE_RUNS`. There
is no `while` loop and no parallel map.

::: app.workflows.nodes.control_foreach._handler.ForeachConfig

::: app.workflows.nodes.control_foreach._handler.ForeachOutput

::: app.workflows.nodes.loop_item._handler.LoopItemOutput

## Virtual Tables { #virtual-tables }

Seven nodes read and write [Virtual Tables](../virtual-tables.md) through the same
service the console, the API and an agent's table tools use. Validation, revision
conflicts, quotas, history, receipts and audit are the same on every surface.

| Node | Does | Effect |
|---|---|---|
| `table.record.create` | Adds a record | write |
| `table.record.upsert` | Creates or updates the record with an external id | write |
| `table.record.update` | Changes some of a record's cells | write |
| `table.record.delete` | Deletes a record, keeping its history | write |
| `table.record.get` | Finds one record by id or external id | read |
| `table.record.query` | Reads one page of records, filtered and sorted | read |
| `table.create` | Creates a new table with a typed schema | write |

Each record node pins its table in its config, checked at publish against the
graph's author, and checked again as the run's principal on every run. Values are
bound and keyed by column id or by column label. A record comes back with its values
twice: `values` by column id, for bindings, and `fields` by label, to read. A key
that names no live column fails with `UNKNOWN_COLUMN`.

A write carries the step's operation key, so a retried step replays its first write.
An update, upsert or delete with no revision bound writes at the record's current
revision, read under the record's lock, and the replay holds even when the first
write already moved that revision on. A revision that moved is `REVISION_CONFLICT`, which is not retried: the same revision would
conflict again, so route it to a fresh read with `error.handle`. A missing
record is `found: false` from `table.record.get`, not a failure. `table.record.query`
reads at most 100 records a page and says `has_more`. It never reads a whole large
table on its own.

`table.create` is its own node and needs `tables:create`. Its output carries the
new table as a reference a later node's `table` can be bound to, and each column's
id by label. A table that a live workflow reads or writes, or a column it pins,
cannot be archived while that workflow's current version uses it.

Four more steps read what the organization's tables are, and change nothing.

| Step | Does | Leaves by |
|---|---|---|
| `table.list` | lists the tables the principal sees, searched by name | `out`, with `tables` and `total` |
| `table.describe` | reads one table's name and columns | `out`, with `columns` |
| `table.exists` | whether a table of this exact name exists | `yes`, with its id, or `no` |
| `table.record.exists` | whether any record matches the filters | `yes`, with the first one's id, or `no` |

`table.exists` matches the whole name without regard to case, so a workflow can
create its table the first time it runs and reuse it after. The two questions
leave by exactly one port, and a `logic.merge` can join the branches again.

::: app.workflows.nodes.table_list._handler.TableListOutput

::: app.workflows.nodes.table_describe._handler.TableDescribeOutput

::: app.workflows.nodes.table_record_exists._handler.TableRecordExistsConfig

::: app.workflows.nodes._tables.TableRecordOutput

::: app.workflows.nodes.table_record_get._handler.TableRecordLookup

::: app.workflows.nodes.table_record_query._handler.TableRecordQueryConfig

::: app.workflows.nodes.table_create._handler.TableCreateConfig

::: app.workflows.nodes.table_create._handler.TableCreatedOutput

## Files { #files }

A file a step makes is stored as a file of its run and handed on as a `FileRef`: an
id, the type its bytes turned out to be, and a size. A step reads a file only if
its own run made it or the run was started with it - a `FileRef` bound in the
graph, checked at publish against a run the author can see. Any other file,
another organization's or another run's, is `FILE_NOT_FOUND`, so knowing an id
grants nothing. A run's files are listed and downloaded from its page.

| Node | Does | Effect |
|---|---|---|
| `http.download` | Fetches a file over HTTP, streamed, and stores it | write |
| `http.upload` | Sends a file to an HTTP endpoint, streamed from storage | write |
| `file.read` | Reads a file as text, a JSON value or CSV rows | read |
| `file.write` | Stores text, a JSON value or rows as a file | write |
| `text.extract` | The text of a TXT, JSON, CSV, text PDF or DOCX file | read |
| `convert.csv_to_json` | A CSV file as a JSON file of rows | write |
| `convert.json_to_csv` | A JSON list of flat objects as a CSV file | write |
| `convert.text_to_file` | Text as a TXT file | write |
| `convert.pdf_to_png` | Chosen PDF pages as PNG images | write |
| `image.transform` | Crops, resizes, rotates or converts an image | write |

A download follows the same SSRF and credential rules as `http.request`, up to five
redirects. Its body is counted as it arrives and refused past `max_bytes`, and its
type is sniffed from the bytes, so `expected_content_types` cannot be fooled by a
header. `text.extract` does no OCR: a scanned page fails the step with
`TEXT_EXTRACTION_NEEDS_OCR` and names the pages. A corrupt document is
`DOCUMENT_CORRUPT`, a Word document that unpacks past the archive bounds a chat
upload has `DOCUMENT_TOO_LARGE`, and a password-protected PDF `DOCUMENT_ENCRYPTED`.

An image is measured before it is decoded. Its width times height, a crop box and
a requested size are each checked against `CHAT_IMAGE_MAX_PIXELS`, and the result
carries none of the source's metadata. Every step that stores a file stores a new
one on each attempt, so it is `at_least_once`.
A run's files may add up to `WORKFLOW_RUN_MAX_FILE_BYTES`, and an organization's to `WORKFLOW_ORG_MAX_FILE_BYTES`. A step whose file would pass either fails with `FILE_QUOTA_EXCEEDED` and stores nothing. To free space, delete old runs or set a run retention on the workflows that make files.

::: app.workflows.nodes.http_download._handler.HttpDownloadConfig

::: app.workflows.nodes.http_upload._handler.HttpUploadConfig

::: app.workflows.nodes.file_read._handler.FileReadConfig

CSV conversions allow at most 10,000 rows, 1,000 columns and 1,000,000 cells. Both directions bound the encoded output by the step's `max_bytes`, before storing it. PDF text extraction refuses more than 2,000 pages and stops reading pages once `max_chars` is exceeded. Literal files are checked again against the run principal's current source-workflow access at admission.

Sandbox output is also capped while streaming it from the host. A file that grows after measurement cannot bypass the remaining aggregate byte budget; the result JSON counts toward it. Finished called runs remain available until their caller ends, so retention cannot cause the waiting caller to repeat their side effects.

::: app.workflows.nodes.text_extract._handler.TextExtractOutput

::: app.workflows.nodes.convert_pdf_to_png._handler.ConvertPdfToPngConfig

::: app.workflows.nodes.image_transform._handler.ImageTransformConfig

## Python { #python }

Two nodes run Python, for two kinds of work.

`code.python.simple` runs a short script in the Monty sandbox, which has no
filesystem, no network and a small standard library. The script reads the bound
values as `args`, and its last expression is the step's `result`, which must be a
JSON value. It computes and nothing else, so it is `pure` and needs `code:execute`.

In the editor, a code step's script is written in a code editor: Python or
JavaScript highlighted in both themes, Tab and Shift+Tab to indent, Enter keeping
the indentation, brackets and quotes closed as they are typed, the bracket beside
the cursor boxed with its match, and the keys of the
bound `args` offered as `args["` or, in JavaScript, `args.` is typed. Esc, then
Tab, leaves the editor. **Test step** runs the script alone on what the steps
before it handed on.

`code.python.sandbox` runs full Python with packages and the run's files on the
organization's `sandboxd` connection, and needs `sandbox:execute`. The script finds
its input files in `inputs`, writes files to `outputs` and sets `result`. It is a
durable job: the first dispatch starts it in the background, and every later one
checks on it in the same session, so a restarted worker reconnects instead of
starting it again. No platform credential is ever staged into the sandbox, and
what the script can reach beyond its files is the host runtime's own
configuration - choose a runtime without network for untrusted work.

| What happened | Result |
|---|---|
| The result is not JSON | `PYTHON_OUTPUT_NOT_JSON` |
| The script raised or ran past a limit | `PYTHON_ERROR` |
| The job ran past `timeout_seconds` | `PYTHON_SANDBOX_TIMEOUT`, the session purged |
| No usable `sandboxd` connection | `SANDBOX_UNAVAILABLE` |
| It wrote more than 20 files or 100 MB, or printed more than 10 MB | `PYTHON_OUTPUT_TOO_LARGE`, measured in the sandbox before anything is fetched, and the session purged |
| The host could not be reached | `SANDBOX_UNREACHABLE`, retried |

::: app.workflows.nodes.code_python_simple._handler.PythonSimpleConfig

::: app.workflows.nodes.code_python_sandbox._handler.PythonSandboxConfig

::: app.workflows.nodes.code_python_sandbox._handler.PythonSandboxOutput

## JavaScript { #javascript }

`code.javascript.sandbox` runs JavaScript on Node as the same durable job, on the
same `sandboxd` connection, and needs `sandbox:execute`. The script is the body of
an async function: it reads the bound values as `args`, its input files in
`inputs`, writes files to `outputs`, may `await`, and what it `return`s is the
step's `result` - `null` when it returns nothing. `require` loads Node's own
modules and whatever the runtime has installed. Choose a runtime with Node.

Its failures are the Python sandbox's, named for JavaScript: a thrown error is
`JAVASCRIPT_ERROR`, a result that is no JSON value - a function, a `BigInt` -
is `JAVASCRIPT_OUTPUT_NOT_JSON`, and the timeout and the output bounds are
`JAVASCRIPT_SANDBOX_TIMEOUT` and `JAVASCRIPT_OUTPUT_TOO_LARGE`.

::: app.workflows.nodes.code_javascript_sandbox._handler.JavaScriptSandboxConfig

::: app.workflows.nodes.code_javascript_sandbox._handler.JavaScriptSandboxOutput

## workflow.run { #workflow-run }

**Run a workflow.** Runs another workflow's published version, one that starts
from **Called by a workflow**, with the bound `input`, as this run acts. The step
waits for the called run to end and hands on its `output`, or fails with
`CALLED_WORKFLOW_FAILED` and the called run's error; with **Wait for it to finish**
off, it hands on the started run at once. The called run is linked to the step and
to this run's chain. A call into a workflow already running further up the chain
fails with `WORKFLOW_CALL_LOOP`, and one deeper than five calls with
`WORKFLOW_CALL_TOO_DEEP`. A test run of the draft calls the published workflow for
real.

::: app.workflows.nodes.workflow_run._handler.WorkflowRunConfig

::: app.workflows.nodes.workflow_run._handler.WorkflowRunOutput

## Adding a node { #adding-a-node }

A node is a package under `backend/app/workflows/nodes/`: `__init__.py`
registers a `NodeDefinition`, `_handler.py` implements it, and `README.md`
explains why it exists. `load_builtins` imports the package.
`tests/test_workflow_node_layout.py` enforces the layout. A handler returns
`Completed`, `Waiting`, `Failed` or `Uncertain` and never raises. It reads the
run it executes for from `app.services.workflow_execution.context.current()`.

A typed node declares three Pydantic models: its config, set in the editor and
frozen at publish; its input, whose fields are what bindings fill; and its
output, which later steps bind to. `extra="forbid"` on each keeps a typo out of a
published graph. Choose `retry_guarantee` for what a repeat of the call would do:
`idempotent` when the handler makes a repeat harmless itself - a table write passes
`operation_key()` - `at_least_once` when a repeat is acceptable, and `none` when it
is not. A node that reads or writes a resource declares `check_resources`, which
publishing runs against the author and every run against its principal.

The console draws a node from its definition, with its icon and tint in
`frontend/src/components/workflows/node-visuals.ts`. Test the handler directly for
its refusals, and drive it once through `tests/integration/workflow_run_support.py`
so its config, bindings and output are proved in a real run.

::: app.workflows.contracts.definition.NodeDefinition
