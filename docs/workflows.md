# Workflows

A **workflow** chains steps into an automation your agents carry out: read a
[table](virtual-tables.md), call an agent, branch on the result, loop over a
list. You build it on a canvas, wire the steps together, and publish it as an
immutable version — the same shape an [agent](concepts.md) has, a draft you edit
and a published version that runs.

This page is the visual editor: the list, the canvas and the step picker, how a node is configured, autosave and publishing, and the keyboard paths through all of it.
The editor lives under **Workflows** in the console. The Workflows **list** page
carries a **"?"** that replays a walkthrough of that list; the editor itself has
no walkthrough.

## Creating and duplicating a workflow { #creating-and-duplicating-a-workflow }

**New workflow** opens two tabs: **How does it start?** and **Templates**. The first shows **Manual**, **API request**, **Chat message**, **Webhook**, **Schedule** and **Table record**; **More ways to start** reveals the other triggers. Templates include **Starter**, **Two-step sequence** and the automations described below. Choose **Use** to open a draft in the editor.

The catalog keeps its cards and search inside one panel. **Filters** reveals status, tags and sorting, with a count of active filters. Failed loading offers **Retry** instead of an empty catalog. Importing starts with a file picker; **Or paste the file's JSON here** reveals a labelled text field.

The list shows every workflow you can see as a card: its status, who can reach
it, whether a version is live, and when it was last edited. **Filter by status**
narrows it to **Drafts** you are still building, the **Published** ones that run,
or the **Archived** ones. From a card you open the editor, the workflow's runs, or
a copy.

**Duplicate** copies a workflow's current draft into a fresh one named
*{name} (copy)*. A duplicate is a new workflow with its own draft, never a copy
of a published version.

!!! info "An empty list may be a filter, not an empty organization"

    **No workflows yet** and **Nothing matches** are different states: the first
    is an organization with none, the second a status filter with no rows under
    it. **Clear filter** returns the full list. A workflow shared with you shows
    under the same list once you have `workflows:view`.

### Templates, exporting and importing { #templates-exporting-and-importing }

The ready-to-run automations are **Public API → table** and **Markdown notebook**. The server prepares a private table and a fully configured draft in one transaction. No account, API key or table selection is needed. The first fetches a sample post from [JSONPlaceholder](https://jsonplaceholder.typicode.com/) and saves its title and body; the second writes a Markdown note. Later runs reuse the table and upsert the same example record. Creating them requires permission to create and edit tables. **Starter** and **Two-step sequence** remain small local examples.

Run history fills the available page area by default, without an expansion control. The catalog fills the available page area and offers its own Full screen control. Pagination appears only when there is another page. File import has a labelled upload area that accepts a file picker or a dropped JSON file.

Run history keeps pagination at the bottom of its panel. A run detail uses a compact summary, a canvas that fills the workspace and one side panel with Steps, Output and available files. Click a step to inspect its recorded data. File and pasted-JSON imports have separate tabs; pasted JSON has a code field and a format action that reports invalid JSON without discarding it.

**Export workflow**, under **More** in the editor's header, exports the draft as a
`.workflow.json` file. The file carries no ids of this deployment: every agent,
table, secret, member, bot or workflow a step picked is left out and listed,
pinned test data is left out, and so is the error workflow. It never holds a
secret's value. **Import** on the list makes a new draft from such a file, takes
out any id a hand-made one still names, and lists every step and field to choose
again before you publish. A file with a step this deployment does not have is
refused, and nothing is made.

### Finding, naming and retiring a workflow { #finding-naming-and-retiring-a-workflow }

Each card says what starts the workflow and how many steps it has, whether it is live
or a draft, and how its last run went and when - its edit date until it has run.

Above the cards, a search finds a workflow by its name, description or tags, a tag
filter narrows the list to one tag, and the order is the last edit, the name or the
newest first. All of it is kept in the address, so a reload or a shared link shows
the same list.

**More → Settings** contains the workflow's name, description, tags and runtime settings, saved automatically. The step editor fills the available window: Input on the left, Parameters and Settings in the middle, Output on the right. Triggers use two panes because they have no incoming data. Each pane scrolls independently on larger screens; phones use one scrolling column. Recorded executions show the parameters read-only beside their data. Record values are fields named after table columns. Notes offer Open note, size presets and resize handles.

The app picker includes catalog MCP servers before they are connected; its generic Call an MCP tool entry is hidden. Connect a service in place, then choose one of its discovered tools. The connection's allowlist remains enforced. The canvas starts with colored steps and a minimap. AI model steps expose instructions, temperature and reasoning effort; unset controls retain provider defaults. Jev decisions expose their model, question and confidence threshold. Send an email uses the platform sender, or connects Gmail or Outlook and switches to that mailbox's actual MCP tool after confirmation. Switching clears incompatible input mappings and is undoable.

The **Send an email** step also offers **SMTP account → New SMTP account**. Enter the server, port, username, password and sender in the vault dialog. STARTTLS usually uses 587; implicit TLS usually uses 465, with certificate verification in both modes. Only `smtp_secret_id` is stored in the workflow. Select **Platform sender** to clear it. Publication and execution enforce secret access; an unavailable account fails instead of silently changing senders.

HTTP request, upload and download share an **Authentication** panel: no authentication, Bearer, API key in a header, API key in a URL parameter, or Basic Auth. Choose an existing vault **HTTP credential** or create one in place; its allowed origin is suggested from the step URL. The workflow stores only `auth.secret_id`. Custom header names and optional prefixes support APIs such as `Authorization: Token …`. Basic Auth uses the vault credential’s username and token as its username and password. Switching methods clears irrelevant settings while preserving the chosen reference; disabling authentication clears the reference.

Searching apps also searches the mirrored MCP registry, including services not yet connected. A connected server without a tool inventory offers **Refresh tools** to connection managers. Channel steps can create and select a bot account inline; only members allowed to manage channels see that action.

The Architect can discover the node catalog, create and revise private workflow drafts, test them and inspect run results. It also creates typed Virtual Tables and queries or updates records. Its workflow-builder and virtual-tables skills explain when to use these features. If a service is absent from the MCP gallery, the Architect can wrap its documented API using an HTTP request step and expose a published callable workflow through the AgenticOS MCP server. Credentials stay in the vault. Tests can perform real actions; publishing unattended authority still requires a human session.

Under its name the editor says where the workflow stands: **Draft, not published**,
or **Live · version 3**, with **Unpublished changes** beside it once the draft
differs from that version in a way publishing would carry. Moving a step or pinning
test data does not count.

A published workflow whose trigger runs on its own - a webhook, a schedule or a new
table record - has an **Active** switch in the editor's header, and its card says
**Active** or **Paused**. Switching it off pauses the trigger at once; switching it
on resumes it as its publisher, so it needs permission to run the workflow. A card's
**...** menu archives a workflow, which pauses its trigger too. An archived one can
be restored, still paused, or deleted with its versions, runs and shares; one whose
runs have not ended is refused with `WORKFLOW_IN_USE`.

## The canvas and adding steps { #the-canvas-and-the-palette }

The editor keeps **Runs**, **Test draft** and **Publish** visible. **More** contains **Versions** and the edit/view switch. **Canvas options** holds the minimap, connection style and shortcuts. A step with no incoming connection leaves more room for parameters by omitting the empty Input pane; **Expected output fields** expands the output schema. **Review setup before testing** opens the unfinished setup.

The **canvas** is where a workflow's steps and connections appear, and it has the
editor's whole width below the header. A **node** is one step; an **edge** is a
connection that sets the order: the step it points to runs after the one it leaves.

Each node is a card with the step's icon, its name and one line under it: what it
is set up to do - a condition, a URL, the number of mapped fields - after the
agent, model or table it works with. A step with more than one way
out lists its ports by name: **true** and **false**, **Each item** and **Done**,
and a red **Error** port on a step that handles its errors. A step that stops a
publish carries a setup mark (red after testing or publishing): hovering lists the first items, and clicking it
opens the step.

A trackpad or a mouse wheel moves the canvas, and a
pinch - or Ctrl or Cmd with the wheel - zooms it; its controls sit in the corner.

Steps are chosen in the **step picker**. It lists sections - **Start**, **AI**,
**Flow**, **Data**, **Apps and the web** - with the groups under each. A group such
as **Slack**, **Tables** or **Jev decisions** opens to its steps, and a group of one
step is that step. **Search steps** finds any step by its name, what it does or its
group. You add a step four ways:

- **+** at the canvas's top left - or **Add step** in the middle of an empty canvas
  - opens the picker. The step goes after the selected step, or at the end of the
  flow in view, wired to it when their ports fit. A starting step goes before the
  current start instead and becomes it.
- **+** beside a step's output opens the picker for the step that comes after that
  output.
- **Right-click** the canvas: the same picker opens where you clicked, and the step
  lands there. Beneath it, **Add a note** and, once something is copied, **Paste**.
- **Drag** a step from the picker to put it where you drop it, wired to nothing.

The apps of Google Workspace (**Gmail**, **Google Calendar**, **Google Drive**,
**Google Docs**, **Google Sheets**) and of Microsoft 365 (**Outlook**, **Outlook
Calendar**, **OneDrive**, **Excel**) are groups of their own in **Apps and the web**.
Each holds the app's native trigger, where the canvas may take one, and one entry per
tool of every organization MCP connection to the matching server - such as **Create
draft** or **Send message**. A connection's tools are sorted into these groups by
name; a tool none of them claims sits in the server's own group (**Google
Workspace**, **Microsoft 365**), which is also where **Connect** and an untested
connection are shown. The sign-in tools (`start_google_auth`, `login`,
`verify-login`) are not offered.

Picking an entry adds an [MCP call](reference/workflow-nodes.md#mcp-call) already
set to that connection and tool, so stored workflows and the node's contract do not
change. The entry never hides what it is: it carries an **MCP** badge and the
connection's name, and the tool's own name stands on its own line under it, with the
server named once in the group's heading; nothing is cut short.

**Search steps** finds it by either name or by the app. On the canvas the step reads
**Gmail · Create draft** with an **MCP** badge, with the connection and the tool's own
name beneath, and its settings say it is an MCP tool call on that connection and link
to it. Every Gmail tool the server offers has a plain name, such as **List labels** or
**Read thread**; a tool the list does not name shows its own name. The native trigger
is not an MCP call and carries no badge.

With no matching connection the server's own group shows a row to **Connect** the
server. Only organization connections are listed, and a connection's tools are the ones its
last test recorded, so test it again to list new ones. A member who may not edit
a workflow sees the triggers alone. A member who edits it but does not manage
MCP servers sees every action and is not offered a **Connect** row: only a manager
connects a server. An app's action rows are picked, not dragged: only
the step's own rows can be dragged onto the canvas.

A new step never lands on top of another, is selected, opens its settings when it
has any, and the canvas scrolls to it when it falls outside the view. Inside a
loop's body every new step is wired into the body, so it stays there. The picker
shows what is valid where you are: **Loop item** and **Loop result** only inside a
loop's body, and a loop until loops are nested as deep as publishing allows.

Right-clicking a step offers **Open settings**, **Duplicate**, **Switch off** and
**Delete step**. With several steps selected, a bar at the bottom deletes them together.

**Switch to view only** in the header shows someone who may edit the workflow what a reader
sees: nothing on the canvas moves, connects or is deleted, a step opens read-only
on one click, and **Test draft** and **Publish** are gone. **Switch to editing** turns it back, and the
editor always opens in edit mode. A save still under way finishes either way.

!!! note "The step catalog grows over time"

    The picker is fed by the deployment's registered nodes, not a fixed list. A
    node kind registered later appears in it the moment it is, with no change to a
    workflow you already built.

### Notes, tidying and shortcuts { #notes-tidying-and-shortcuts }

**Add a note** under the picker a right click opens puts a note beside the steps:
markdown, written on a double-click or with its pencil, moved by dragging and resized
from its corners; selected, its palette button rolls out swatches to tint it - grey,
yellow, green, blue, purple or red - so a warning reads apart from a to-do. A note is kept in the graph, so versions, restores and copies of the
workflow keep it, but nothing runs or checks it. Selecting a connection offers a **+**
that puts the next step picked into its middle, wired on both sides where the ports fit.
The toolbar's **Tidy up** lines the steps in view up left to right as one undoable edit,
the map button shows a minimap, the palette button switches the steps between colour and Simple (see [How a step is drawn](#how-a-step-is-drawn)), and the keyboard button - or **?** - lists every
shortcut; **Tab** opens the step picker. None of them fires while you type in a field.

### How a step is drawn { #how-a-step-is-drawn }

A card says what sort of step it is before it says what it does. Above the name a
small label reads **Family · Kind** - **AI · Classify**, **Data · Save a record** -
and the icon sits on a tile drawn in the step's family, the same sections the step
picker uses:

| Family | Its tile |
|---|---|
| **Start** | In the ink colour - dark in the light theme, light in the dark one - and round, on a card whose left end is rounded to match |
| **AI** | Solid violet |
| **Flow** | Grey |
| **Data** | Teal |
| **Apps** | White with a blue outline, so a brand's mark sits on it unchanged |
| **Error** | Red |

The families differ in lightness and shape as well as colour, so they still tell
apart for someone who is colour blind and on a canvas zoomed out too far to read.
The minimap draws each step in its family's colour too. A card's border and ring are
never a family's: they belong to the run (see below), a change, a selection or a
step that is switched off.

Under the name, the line starts with what the step works with - the agent, the
model, the table - and goes on with what it is set to do, as in **gpt-4.1-mini · 3
categories**.

A step that can park the run carries a band across the top of its card, worded from
its settings and never from a run:

| Step | The band reads |
|---|---|
| Approval | **Waits for a person** |
| Wait | **Waits 2 days** (or hours, minutes, seconds), **Waits until a time** or **Waits a set time** when an earlier step supplies the time or the length, or **Waits for a call** - which wins when both a duration and a call are set |
| Run a workflow | **Waits for the called workflow**; no band when **Wait for it to finish** is off |
| MCP call | **Asks before writes** or **Asks before every call**, by its approval setting; no band when it never asks |

A step that asks a person shows the band in rose; a timer or a call shows it in
grey. The agent step has none: its approvals come from the agent's own spec, which
the card cannot see.

On a run's canvas a step waiting for a person is drawn in rose, with an hourglass in
its pill, whichever way the steps are drawn.

**Simple** draws every tile neutral and the minimap grey, the way the canvas looked
before steps had families. It keeps what does not depend on colour: the label in
grey, the start's rounded end and a neutral band. Switch it with the palette button
on the canvas toolbar or under **Settings → Profile → Appearance → Workflow steps**;
it is remembered per browser, like the theme.

Drag the right edge, the bottom edge or the bottom-right corner of a selected step to
resize it. A card is 200 to 560 px wide and up to 400 px tall, and never shorter than its
own content needs. More width fits more of the name and the summary; more height lets the
name wrap onto up to three lines and then the summary onto two, and the ports stay at the
bottom of the card.

The size is saved with the draft, so undo, copy, paste, duplicate,
published versions and export keep it. **Reset size** in the step's right-click menu puts
it back to the default, and **Tidy up** spaces the steps around the sizes they have. A
published version, a run and a comparison show the saved size without handles.

## Configuring a node { #configuring-a-node }

What each node does, what it is configured with and what its failures mean is in
the [node reference](reference/workflow-nodes.md).

A click selects a step; a double click opens it over the canvas. In a published version or **View only**, one click opens it. The header names the step and folds unfinished setup into one expandable summary. Open it to see what is missing; choosing a field takes you to its input. After a test or publish attempt, the summary opens with validation details.

**Connect account** in a step or the app picker opens the existing account setup above the workflow. Connect an organization account, finish setup and select it in the step. A secret selector offers **Add API key** or **New secret**, selects the stored secret automatically and keeps only its id in the draft. A trigger missing OAuth app credentials offers **Add credentials** in place; the same vault form stores them for the organization.

**Parameters** is what the step works
on and is set to do, in one list, with the list a step works on first: Filter's
**Items** before its **Condition**. **Settings** is how it runs. Every edit is saved
to the draft as you make it, so **Done** only closes the dialog, and **Delete step**
removes the step. A read-only dialog shows every setting, disabled, at its value.

A parameter that takes text is one box for typed text and values from earlier steps
together, such as `New lead: {{Form.payload.name}} from {{Form.payload.company}}`.
**Data** beside it inserts a value at the cursor, and so does a field dragged from
**Input**. Typing `{{` lists the same values, and inside a trigger's payload or a
loop's item, the fields the last test run saw there; what you type next narrows the
list, and `Enter` or `Tab` writes the placeholder.

A placeholder names a step and a
path into its output, coloured in the box - red, once you leave the box, when it names
nothing this step can read - is checked at publish like any value read from a step, and follows the step
when it is renamed.
With a test run's data, the result is previewed beneath. Nothing is evaluated: when
the step runs, each placeholder becomes its value's text, JSON for a list or an
object, and one with nothing behind it fails the step with `INVALID_BINDING`,
naming it.

Any other parameter - a number, a choice, a switch, a list typed as JSON - is its
own control, and **Data** beside it takes the value from an earlier step instead.
**Data** lists only the values reachable here that carry a compatible type, grouped
by step, each with the kind of value it holds, and says **No compatible upstream
outputs** when there are none. The parameter then shows what it reads - *Run an
agent › text* - and **×** goes back to a typed value.

A required parameter with no value yet is a validation problem, flagged on the step
rather than filled with a silent default. Some parameters hold structured values: a
list of rows you **Add row** to, reorder and remove, or a typed choice that swaps the
sub-form beneath it. The dialog recurses into those rather than sending you to a
separate screen.

### Conditions { #conditions }

**Filter a list**, **If** and **Switch** decide with a condition built from rows: a
field of the item or the value, a check - **is equal to**, **is at least**,
**contains**, **is not empty** and the rest - and what it is compared with. A number,
`true` and `false` are compared as such, anything else as text. With several rows,
**Match all of these** or **any** says how they combine, and the fields the last run
or the test data showed are suggested. The condition is stored as the JMESPath
expression the step evaluates. **Write it as an expression** edits it as that, and
one the rows cannot show stays an expression.

Renaming a **Switch** rule, a classifier category, an error branch, a **Split** branch
or an approval choice carries the wires, bindings and quick log that used the old name, unless
entries are reordered, inserted or deleted, or two names change at once.

### Naming a step, noting it and switching it off { #naming-noting-and-switching-off-a-step }

Clicking the step's name at the top of its dialog gives it a name of its own, shown
on its card and wherever a later step picks what to read - two **Send a message**
steps become *Tell sales* and *Tell support*. No two steps may share a name,
ignoring case.

Under **Settings**, **Note** keeps a line for whoever edits the workflow next, marked
on the card, and the tab carries a dot once anything there is changed.

Turning off
**Run this step** there, or **Switch off** in its right-click menu, keeps a step on
the canvas, dimmed, and skips it when a run reaches it: it does nothing and hands on
what came into it. Publishing refuses the trigger or a step that decides the way
switched off, and a step that reads one that is off, unless what comes into it -
along its one incoming connection, from a step that is on - has the field read,
which it then hands on. All three are saved in the graph, so versions keep them.

### A step's data, test data and testing one step { #a-steps-data-pinning-and-testing-one-step }

Editing a workflow, the dialog puts a step's parameters between two panes. **Input**
shows what one earlier step handed on, the nearest first; when there are more, its
heading picks any step this one may read from. **Output** shows what the step itself
handed on, both from the last test run started in
the editor, or the latest one when it opens. **Table** lays the data out as rows, a
list of records as one row each. **JSON** shows it as it is, and **Fields** lists
every field by path with a plain word for what it holds - text, number, list, ID:
the paths a later step reads.

Before any run, both panes list the fields a step hands on the same way, and those
can be dragged too; a step that nothing leads to says **Not connected yet**. A table
shows its first 50 rows until **Show more** lays out the rest, and a cell cut to its
column shows the whole value on hover.

A column or a field of **Input** can be dragged onto a parameter, which then reads
it from that step, as if it were picked from **Data** - into text, as a placeholder.
A field that does not fit is refused with the reason: a type the parameter does not
take, or a step that does not always run before this one.

Inside a free-form value,
such as a mapping's `values` or a trigger's `payload`, the type is the one the run
showed. **Data** offers free-form values to any parameter too, with **Field inside
it** for the path. Holding a dragged field near the top or bottom of the form scrolls
it, so a parameter out of view can be reached.

**Keep as test data** keeps the output on the step, and **Set test data** types some
in as a JSON object of at most 64,000 bytes. A test run hands test data on instead of
running the step, so a slow model call or a write to a live system is made once and
reused. A step that decides the route never keeps test data, and publishing strips
it all: a published version always runs its steps. A pin icon marks the card, and
**Remove test data** takes it away.

**Test step** runs the step alone, and is the pane's main button while there is no
data yet. The run keeps only the step and the steps leading to it, and each of those
with known output, test data or from the last test run, hands that on instead of
running. The rest run, and nothing after the step does. A step that writes asks
first, since the test really writes. A step inside a loop cannot be tested alone,
because it runs once per item, so test the loop. While the test runs, the square
beside **Test step** stops it. When it ends without running the step - stopped, sent
down another branch, or ended before it - a warning sign there says which. Over the
API, `step` on `POST /api/v1/workflow-runs` does the same.

### Resource pickers { #resource-pickers }

A setting that pins a resource opens a picker rather than a free-text field, so a
step names a real thing your organization has:

| Picker | What it pins |
|---|---|
| **Agent** and **Version** | An agent, by its face and description, then one of its published versions, with the live one marked and each one's date and release note. Changing the agent clears the pinned version, because a version belongs to one agent. The step's card then shows the agent's face and "name · v3" |
| **Table** and **Columns** | A [virtual table](virtual-tables.md), then the columns the step reads — scoped to that table's current schema |
| **Secret** | A [vault](secrets.md) secret, by reference. A step stores the secret's id, never its value |
| **MCP server** and **Tool** | One of the organization's [MCP servers](mcp.md), with its service's mark, then one of the tools it listed when last tested. Choosing it needs the right to edit the workflow - by role or by a grant on it, as publishing the step does - not `mcp:manage`; only a member who manages servers can test one or add another |

Each picker disambiguates same-named rows with context and marks a reference
whose target has gone away. The **Agent** and **Secret** pickers also carry a
create-new link — always, not only when the list is empty — while the **Table**
picker has none. A table whose schema changed since it was bound says so and offers
**Rebind to the current schema**, so a stale column set is a visible prompt
rather than a silent break.

### Evals for a model step { #evals-for-a-model-step }

A step a model answers - an agent, **Ask a model**, **Classify**, **Extract data**,
**Summarize or translate**, or a decision - has an **Evals** tab: the cases it should
handle, and what its answer should then say. **Add a case** takes the input the step
was last tested with - the run's input and what the steps before it handed on - so
test the step once first, then name the case and say where in the answer to look
(`text`, `category`, a path such as `structured.amount`, or nothing for the whole
output) and whether it should **contain**, **not contain** or **equal** a value,
ignoring case and the space around it.

**Try** starts a test run of the step for each case, checked and billed like any
other, and each case is marked passed or failed as its run ends, with what the
answer said or why it gave none. A case whose run cannot start - too much work in
flight, the monthly budget spent - is marked failed with the reason. Try the cases
after changing the prompt, the model or the instructions. A step holds up to 50
cases, and trying them needs `workflows:edit`, like testing the draft.

### Catalog agents { #an-agent-configured-in-the-step }

**Run an agent** selects a published agent from the catalog. Choosing it pins its current published version; the version picker can choose an older one. A published workflow keeps that immutable pin. For an existing incomplete step, **Use published version** fills the missing pin before testing. Create or edit agents in the Agent Builder.

Older graphs containing an agent configured inside a step remain executable. The editor preserves that configuration until you deliberately replace it with a catalog agent. New inline agents cannot be built in workflows. **Max cost (USD)** still caps an execution alongside the other applicable budgets.


### When a step is slow or fails { #when-a-step-is-slow-or-fails }

Under a step's **Settings**, **When it is slow or fails** sets its policy. **Handle
errors** gives the step an **Error** port: a failure its retries did not settle
leaves through it, to a **Handle error** step or anything else you connect, instead
of failing the run. **Tries** is how often the step is attempted in all, and **Wait
between tries** and **First wait** set the pause between attempts. A step whose call
is not safe to repeat, such as running an agent, says so and is never retried.
**Time limit** cuts a call off after that many seconds. What each setting does at
run time is in the [node reference](reference/workflow-nodes.md#error-handling).

A binding to a value with no declared shape - a loop's current item, a trigger's
payload - offers a **Field inside it** box under the source, where you type the path
inside that value, such as `record_id` or `fields.Email`. The run checks that path
when the step is dispatched, since only the run knows what the value holds.

### Quick log { #quick-log }

A quick log writes one line to the workflow's log each time a step finishes in a run,
so you can see what a workflow did without opening each run. It is a setting of the
step. Hover a card and choose **+ Log**: a **LOG** strip docks outside the card's right
side, the step's output handles move to the strip's outer edge, and each output that
is logged has a bar. Remove the quick log to stop logging that step.

The **message** is a template of 1 to 500 characters, `{{step}} → {{outcome}}` by
default. It can use `{{step}}`, the step's name, and `{{outcome}}`, the output the
step left by. It can also use the step's output fields by their path, such as
`{{record.id}}`, and `{{error.code}}` and `{{error.message}}` for a failure. A
reference that does not resolve renders empty, and so does a list index: paths go
through objects only.

**Outputs** picks which outcomes write a line. By default every output does; tick
fewer to log only those, and remove the quick log to log nothing. A quick log is not
allowed on a **Loop item** or **Loop yield** step. Put it on the **For each** step
itself: it writes a line, by its `done` output, when its loop closes. A step with no
outputs logs its failures.

Failures are always written. A failure that no `error` port routes is logged whatever
outputs are ticked, because a run that failed silently is what a log is for. A
failure routed by an `error` port follows the **Outputs** filter like any other
outcome.

No line is written for a step that was skipped, switched off or never started, or
that a [retry from the failed step](#running-a-workflow) reused instead of running.
A log never changes a run: a message that cannot be written is dropped and the run
goes on as it would have. A test run writes its lines too, marked as a test, and a
line from a step that handed on pinned test data is marked as pinned.

Lines are kept with their run and removed with it when history retention removes the
run (see [Workflow settings](#workflow-settings)). Read them on the
[Logs page](#the-logs-page) or, per step, in the run view.

## Connections and foreach scope { #connections-and-foreach-scope }

You draw an edge by connecting one node's output port to another node's input
port. The editor refuses a connection between ports that carry different shapes
before it draws it, so an incompatible wire never lands on the canvas, and drawing a
connection that is already there does nothing.

An edge sets the order the steps run in; it does not move any data. The values a
step reads are its **bindings**, described under
[Configuring a node](#configuring-a-node).

So that a wire does not leave you binding every field by hand, connecting two ports that carry exactly the same
shape — an Echo's output to a Relay's input, say — also binds each of the
target's inputs to the field of the same name on the source. A field you had
already bound is left alone.

When the shapes differ, or a port carries no data, one choice is still made for you:
a step that works on one list, connected after a step that hands on exactly one -
**Filter a list** after **List records** - reads that list. Nothing else is bound,
and you pick each source yourself with **Data**. Undo (`Ctrl`/`Cmd` + `Z`) takes
back the connection and its bindings together, and deleting an edge later leaves
its bindings in place, so remove or rebind them in the step's settings.

To delete a connection, select it: click the wire, and it is drawn heavier and a **Delete connection** button appears on it. Press the button, or press `Delete` or `Backspace`, and the connection goes while the two
steps stay. The connections of a published version cannot be selected, so they
cannot be deleted.

A **For each** step runs its body once per item in a list. The body is not a
separate document - it is part of the same flat graph, shown on its own. **Edit
loop body** on the step, which says how many steps the body holds, enters that
view, and the **Workflow scope** breadcrumb in the canvas's corner shows where you
are, from **Workflow** down to the loop you opened. Each crumb navigates back out.

A body starts at **Loop item**, which the loop's **Each item** port connects to,
and ends at **Loop result**; nothing in it connects back to the loop, which
continues through **Done** once every item has been through the body. The step picker and the binding sources follow the scope you are in, and a step in a body may read
anything that ran before the loop. What the loop does is in the
[node reference](reference/workflow-nodes.md#loops).

### Parallel branches { #parallel-branches }

Any step may send one output port to several steps, and those steps run at the same
time. The **Split** step does the same with named branches, and takes all of them; it
has no condition and cannot route errors. Which branch ends first is not defined, so
nothing may rely on the order. Draw the legs, and bring them together where a later
step needs what they did.

A step with several incoming connections is a join, and needs no **Merge**. It runs
once every step leading to it has settled, if at least one of its connections is
live: a leg that an If left untaken does not hold it back. It is skipped when no
connection is live, and when a step leading to it failed with no error route. Its
bindings may read only steps certain to have run before it, so a join may read each
leg of a parallel group, but not an arm of an If, which may not have run.

A **Merge** has a **Wait for** setting. **The branch that ran** passes on the output
of the one branch that reached it, and publishing refuses it when two of its
inputs can run together. **All branches** waits for every input and hands each one on
by name as `branches`, so later steps read `branches.<name>`; each wire has a
**Branch name**. Publishing refuses it when an input may not run, naming it, or
when only one input ever can. Connecting a second leg to a merge picks the setting
the graph needs, and renaming a branch name carries the steps that read it, in one
undo. The details are in the [node reference](reference/workflow-nodes.md#logic-if-and-logic-merge).

Publishing also refuses a graph with two **Output** steps, or two **Respond to
webhook** steps, that can both run in one run, and an **Error handler** that two
steps able to fail in the same run feed. Give each leg its own.

A branch that fails with no error route fails the run. The steps beside it start
nothing further, and what they had under way is closed: pending approvals, timers,
and the agent runs a step is parked on. A step that finishes after that is recorded
as **Finished after the run stopped**, its work kept, and a [retry](#running-a-workflow)
reuses it rather than doing it again. The run's status follows its live steps, so
a branch waiting for an approval shows even while another still runs.

The run's budget is shared. Every step that spends, and every workflow it calls,
draws on what the cap leaves after spend and what other steps in flight hold, and
never more than its own `max_cost_usd`. A step that finds the rest held by its
siblings waits and asks again, a little later each time, rather than being handed
the whole remainder. A hold ends when the step that took it settles.

Sibling AI
steps run side by side under a run budget only when each has its own `max_cost_usd`:
a step without one holds everything that is left, so its siblings wait until it
settles.

How many branches run at once is set by the worker, not by the run. There is no
per-run limit, so the branches of one run may take every workflow slot of a worker,
`WORKER_WORKFLOW_CONCURRENCY` (five by default, see
[Configuration](configuration.md)), and the rest queue. A run someone is waiting on
goes ahead of one that started itself. A fan-out of many branches in one run
therefore slows other runs on that worker; keep it as wide as the work needs.

## Validation feedback { #validation-feedback }

The editor checks the graph as you edit. Before testing, incomplete steps carry a neutral setup indicator and the canvas says **Finish setup**. Open the indicator to see the checklist and jump to a step. Testing or publishing reveals errors, and leaving an empty required field shows its message inline. Publishing remains blocked until every validation problem is resolved.

A step's settings stay short. What the step needs, and whatever you already set, show
at once; optional settings still at their defaults wait behind a button that counts
them - **3 more options** - which brings them out above itself until **Fewer
options**, and how the step runs waits under **Settings**.
A required value you have not given yet is not flagged beside its field until you
leave that field or try to run or publish: the step's mark on the canvas says it
from the start. A description that only repeats its field's
name is a hint on the name instead of a line under the field.

The messages name the specific fault: a required input with no value, an input
set by more than one source, a connection whose ports carry different shapes, a
step that cannot be reached from the start, a loop back to an earlier step, a
value that reads a step that has not run on every path that reaches it, or a
connection that crosses into or out of a loop's body.

!!! info "The editor's check is a preview; publish is the authority"

    The in-editor validation is a fast mirror of the rules the server enforces.
    It exists to catch a problem while you are looking at it, but it is never the
    last word: publishing re-runs the full validation on the server, and a
    problem the editor missed is surfaced the same way, against the node or field
    it belongs to.

## Autosave and the revision-conflict banner { #autosave-and-the-revision-conflict-banner }

Your draft saves itself. A short pause after you stop editing writes the current
graph, and the status under the title, after its tags, reflects it — **Unsaved changes** while a
save is pending, **Saving…** while it runs, **Saved** once it lands, and **Save
failed — will retry** if it did not.

Each save is written against the revision you opened, so a draft edited in two
places at once cannot silently overwrite. When that happens the editor raises a
banner titled **This draft changed elsewhere**: *Someone edited this workflow
since you opened it. Overwrite keeps your changes; reload replaces them with the
latest saved draft.* You choose:

- **Overwrite** — keep your version and write it over the one saved elsewhere.
- **Reload** — discard your unsaved edits and take the latest saved draft.

## Publishing a version and version history { #publishing-a-version-and-version-history }

Configuring unattended authority requires a member session: publishing a webhook, schedule, table, form, GitHub, email or channel trigger, enabling its exposure, rotating its secret or form link, changing its schedule, and choosing an error workflow. Organization API keys can publish manual workflows, start permitted runs and pause automation; they cannot retain their issuer's user authority for future events. For pre-release installations with existing automation, republish from a trusted member session; historical rows do not record the publishing key's provenance.

MCP steps enforce the connection's current visibility, group/resource access and `allowed_tools` at publication and dispatch. An empty allowlist permits no tools. Withdrawing access after publication refuses execution before credentials are read or a server is contacted.

DOCX extraction streams document XML and stops at the configured character budget, with bounded archive expansion and nesting. It does not build the complete document tree before enforcing that budget.


Version history loads 50 metadata entries at a time; **More** requests older
versions. The API accepts `before` and `limit` (1–100), returning `next_before`
until there are no older versions. Graphs are fetched only when opening a version.
A failed page can be retried while preserving entries already loaded.

**Publish** freezes the current draft as an immutable version that runs — a
version is never changed after it is created. The publish dialog names the version it makes and takes an optional
**Release note** describing what changed; when the draft has not changed since the live
version, it says so first. If the graph still has
problems, publishing is blocked with **Fix the problems below before
publishing**, so a version that would not validate is never created.

Publishing does not end your editing. The draft goes on existing independently of
any published version, so you keep editing it straight away. **Versions** under **More** in the
editor's header opens every published version with its release note, the live one
marked **Live**. **View**
opens a past version read-only - a published version is read-only, and to make
changes you go on editing the draft.

To go back to a published version, open it with **View** and choose **Restore to
draft**. After you confirm, the draft takes that version's graph, and whatever was
unpublished in the draft is discarded. The version itself does not change, and
nothing is published until you publish the draft again. Undo starts over from the
restored graph. If someone changed the draft since you opened it, the restore is
refused with the same conflict banner a save raises, rather than discarding their
edit. Restoring needs `workflows:edit` on the workflow, and an archived workflow
cannot be restored. Each restore is recorded in the [audit log](governance.md) as
`workflow.version_restored`.

**Compare with draft** in a version's preview draws the version and the draft on
one canvas: each step the draft added, changed or removed is marked on its card,
and the list beside it names every changed step with what changed in it - a
setting, an input, its name, note or version, whether it is switched off, and
what it does when it is slow or fails. Moving a step and pinned test data are not
changes. **Show this version** goes back to the version alone.

## Workflow settings { #workflow-settings }

**Settings** groups timing and error handling, run history and retention, and limits into expandable sections. Sections with non-default values start open. The runs page starts with history; **Live performance** expands statistics for published runs. Runs and Logs keep secondary controls under **Filters**. A refused run filter in a link opens its field and error automatically.

Retained inline results have shared ceilings: `WORKFLOW_RUN_MAX_INLINE_RESULT_BYTES` (64 MiB per run) and `WORKFLOW_ORG_MAX_INLINE_RESULT_BYTES` (1 GiB across retained runs). Reservations count compact attempt results, including synthetic loop outputs, and possible run/webhook/error copies. They do not measure physical PostgreSQL storage or replace deployment-wide storage policy. Small terminal failure records can exceed a full allowance so the run can close. `WORKFLOW_INLINE_RESULT_LIMIT` cannot be bypassed by error routing; incurred fees survive and effects are not automatically retried. A handler may already have acted when its result is refused. Use file references or configure history retention to release reservations.

A resumed agent keeps the tighter of its parked lifetime ceiling and the amount already spent plus the workflow's current remaining funds. Spending by sibling branches while approval is pending cannot restore the old headroom. Each eval case consumes a workflow-run allowance, including cases within one batch; exhausted cases are recorded as refused. The HTTP request's first reservation is credited to its first case.

Pinned outputs import nested file references after current access checks. Admission and retention share the file lifecycle lock: a committed import protects its producer, and retention rechecks references after waiting for that lock. Recent editor examples keep the newest run's data despite delayed older responses; pasting preserves notes, and mixed note/step changes apply together.

Migration `0231_workflow_result_bytes.py` backfills counters from existing uncompressed JSON text, conservatively relative to new compact reservations. Stop API and worker writers during this backfill. Existing over-limit histories are preserved but block further large results until cleanup or a configured limit increase. This does not reconstruct content already deleted.

Retained payload reservations also include a run's initial input, its test-mode draft snapshot and each stored Wait resume payload. Admission and resume reserve these bytes before writing or waking steps; a refusal returns `WORKFLOW_INLINE_STORAGE_LIMIT` (429). Resume links authenticate before reading a body. Migration `0232_workflow_input_bytes.py` adds these existing payloads to the counters, preserving results and fees. Stop API and worker writers during the backfill; an existing over-limit organization must clean up retained history or raise its limit before admitting more data.

Stored drafts, published versions and retained imports protect the files they reference from retention. Deleting a producer workflow is refused while another workflow still references its files; remove those references or archive it. Registry edits, admission, imports and cleanup use the same organization lifecycle lock. Deletion checks cross-workflow run dependencies before removing triggers and attempts to unregister GitHub hooks through the existing account integration; provider cleanup failures remain visible in logs.

Combine by key accepts scalar join values and refuses lists or objects without retries. Eval-case creation serializes the case ceiling and position allocation. The dashboard totals include every visible workflow, even beyond 500, and a terminal run refreshes its file list independently of when its steps arrived.

Nested imports are deduplicated by file ID and bounded by `WORKFLOW_GRAPH_MAX_BINDINGS` before database validation.

A source run stays while a retry is active or another retained run imports one of its files. Finishing a retry does not invalidate files its later steps still reference.

**Settings**, under **More** in the editor's header, holds what a workflow is run with rather than
what it does. The settings are the workflow's, not a version's: a change applies
to every run started after it, and publishing keeps them.

- **Timezone** - a schedule's cron expression is read in it, across daylight
  saving too, and a **Date & time** step that names no timezone writes in it. A
  run keeps the one set when it started. UTC when unset. The field says what time
  it is there now, and refuses a zone the browser does not know.
- **Default deadline** - the deadline a run gets when whatever starts it names
  none.
- **Error workflow** - a published workflow starting from **On failure of a
  workflow**, started once when a run fails. See
  [When another workflow fails](#when-another-workflow-fails).
- **Keep runs for** and **Keep runs that succeeded** - a daily sweep removes a run
  and the files it stored that many days after it ends, and a succeeded run the day
  after when succeeded runs are not kept. Unset, runs are kept for good.

**Limits** bound what its runs do at once and spend, above each step's own limits -
an agent step's cost ceiling among them:

- **Runs under way at once** - a real run started past it is refused with `429` until
  one ends. A webhook's or GitHub's sender is told to retry, a schedule waits for its
  next tick, and a table event or a form answer past it is refused. A mailbox is read
  again a minute later, whatever its interval, so the message waits for the run to
  end - unless the runs holding the limit are waiting for an approval: the message is
  then skipped for this workflow and the audit log records it
  (`workflow.mail_message_skipped`). Test runs are neither counted nor held back.
- **Most one run may spend** - the run's own budget, the tighter of it and the
  version's: a run that reaches it stops before its next step, out of budget.
- **Most its runs may spend a month** - counted over the calendar month in UTC,
  test runs included. Once reached, no run starts - `402` - until the month turns
  or the budget is raised. The runs page shows the month's spend against it.

Over the API, `PUT /api/v1/workflows/{id}/settings` replaces them.

History retention removes run contents and files, but retains content-free amounts
and admission timestamps for monthly budget accounting. Deleting history cannot
replenish the workflow’s monthly budget. Fees deleted before this accounting was
introduced cannot be reconstructed.

## Running a workflow { #running-a-workflow }

**Test draft** in the editor's header runs the draft at once, never the published
version - `Ctrl`/`Cmd` + `Enter` does too - first asking for the fields a Manual or API trigger declares. The run then
shows on the canvas as it happens. A pill on each step's corner says where it is -
**Pending**, **Starting**, **Running** with a ticking time, **Waiting**, **Failed**,
**Needs attention**, **Skipped** or **Not reached** - and a step that succeeded shows
how long it took. The wire into a running step moves, the path taken turns green,
and a branch the run did not take fades. A failed step shows its error under its
card and shakes once. A connection says how many items went along it when the step
before handed on a list, and a bar at the bottom says how the run stands, with
**Open run** for its page. While the run goes on, the square beside **Test draft** stops
it, with no question asked. The canvas keeps the run once it ends; the next edit
hides it and leaves a bar saying the graph changed since, still with **Open run**. A step that waited and went on counts one try, not two. **Test draft** waits while an edit is still saving, and says why it cannot
run while the draft has problems.

**Runs** in the editor's header, and the runs icon on a workflow's card, open its
runs, newest first, each with its status, whether it ran the draft or the published
version, what started it, when, for how long and at what cost. **Start a run**
starts one by hand: **Test the draft** runs the draft as it stands, and **Published
version** runs the live one. Its **Input (JSON)** is what the workflow's **Input**
step hands on as `payload`.

Above the list, **How it ran** sums up the real runs of the last 7, 30 or 90 days:
how many ran and how many failed, the share of those that ended that succeeded, the
typical time and the time 95 in 100 finished within, and what they cost by day. The
cost card also gives this month's spend, test runs included, against the workflow's
monthly budget, in red once it is spent. **By step** lists where the time, the cost
and the failures came from, costliest first. Over the API it is
`GET /api/v1/workflows/{id}/stats?days=30`.

When the workflow asked a person for approval in that period, **Approvals** sums up how
they decided: **Approved as proposed**, **Edited before approval** with the median share
of the text the edits changed, **Rejected**, how many requests **expired**, and the
**time to decide**, typical and 95 in 100. A table lists the same figures for each
approval step.

The window is the same days, counted by when the person was asked, and test runs are
left out. The share approved and the share approved as proposed (`acceptance_rate` and
`unchanged_rate` over the API; the card shows the second) are out of the requests that
were decided, an approval or a rejection: a request that expired or was cancelled with
its run was never decided, so it is counted but not part of them. A step that cannot be
edited counts as approved as proposed. The figures state what happened and do not judge
it.

Figures are per step and per day, not per kind of message. To compare categories, route
each one to its own approval step.

How much an edit changed is measured once, when the person decides, by the same scorer
as [`text.compare`](reference/workflow-nodes.md#text-compare), by character: `0` when
they approved the proposal unchanged on a step that can be edited, up to `1` when
nothing of it is left. A step that cannot be edited, a rejection and an expiry have no
such figure. An edit decided before approvals were measured has none either and is left
out of the median rather than counted as no change; when no edit in the period was
measured, the card reads **Change not measured**.

The same figures arrive over the API in the stats' `approvals` block. Across every
workflow you can see, over the dates you choose, `GET
/api/v1/workflow-approvals/stats?from=2026-10-01&to=2026-10-31` gives the totals and the
five workflows with the most requests, and the dashboard's [**Approval
outcomes**](console.md#the-dashboard) card shows them.

The dashboard's **Workflows** card adds the same up across every workflow you can
see, over the period the dashboard is set to: runs, failures, cost and the five
busiest. Above them it counts the runs waiting for a person now - an approval or a
step that needs attention - whenever they started. Over the API it is
`GET /api/v1/workflows/summary?from=2026-10-01&to=2026-10-31`.

A run opens on its duration, its cost (a spend under $0.0001 reads `<$0.0001`, not zero) and how many steps it took, then the error it
ended with, if any. Beside them is the graph it executed, drawn as the editor draws
a run: each step's pill, its tries and its error, and the steps it never reached
faded. Only a page open while the run went on moves; one opened later is still. **Open loop body** shows a loop's iterations the same way.

The run's answer - its text, its structured result, the passages it drew on and how
many files it made, with the JSON itself under **Raw output** - and every step it
took, iteration by iteration, sit alongside. A run still going
refreshes itself every couple of seconds, and **Cancel run** stops it, and withdraws the timers its waiting steps had queued. Its **Files** list what its steps stored - a download, a rendered page, a script's output - each one downloadable.

A run waiting on an [**Ask for approval**](reference/workflow-nodes.md#human-approval)
step shows in the **Approvals** tab of Activity. When the step is set to **Let the
approver edit** and has a proposal bound, such as a drafted reply, the approver
changes it in an editor there, with **Restore original** and **Show changes**, and
approves their version. The step then hands on `final`, `original` and `edited`, so
a later step sends what the person approved. A decider the step does not name sees
the proposal read-only, and a request decided with a changed version
shows an **Edited** badge under **Decided**.

When the step lists **Ways to approve**, the queue shows one button for each, with the
label its author wrote, in place of **Approve**; **Reject** stays. Each way is an output
port of the step, so the workflow goes on by the one the approver pressed, and the
decided row names it. An edit goes with whichever button is pressed.

In the list a test run's version reads **Draft (test)** and a real one's
**Published**, and a run started from the console or the HTTP API reads **Console or
API**. **Status**, **Version**, **Started by** and **Started** (the last hour, day, week or
30 days) narrow the runs, and the list answers a
page at a time; each filter is kept in the address, so a filtered list can be
linked. **Runs** on the workflows list shows every workflow's runs together. On a
run's page, clicking a step shows its **Input** and **Output** from that run. The lines a step's
[quick log](#quick-log) wrote show under the step.

**Retry from failed step** starts a new run of the same version and input in which
each step that succeeded hands on what it handed on before, so only the failed
step and what it did not reach run, and a write is never made twice. A loop runs
again and reuses each item's steps that had succeeded. **Debug in editor** pins
what each step outside a loop handed on in that run onto the draft's steps, so a
test run starts from where that run was. Over the API, `POST
/api/v1/workflow-runs/{id}/retry` retries, and `GET /api/v1/workflow-runs` takes
`status`, `mode`, `triggered_by`, `created_after` and `created_before`.

**Resolve** is offered on a step that needs attention while its run is still live.
A step needs attention when it may have acted and nobody saw it finish, or when it
stopped waiting with nothing left to wake it. The dialog names the step and says
which. **Run it again** queues the step for a new try on the same run, and on a step
that may have written something it warns that doing so can do it twice. **Treat it
as failed** is **Take its error route**, where the step routes its errors or sits in
a loop, or **Fail the run**. If the step reported a result after it was given up on,
**Use that result** goes on from it. Nothing else in the run is touched, so its
siblings, approvals and timers go on.

Only the person who started the run, or an editor of the workflow, may resolve a
step, and in a test run only an editor may resolve a step or retry the run. Over the
API it is `POST /api/v1/workflow-runs/{id}/steps/{node_run_id}/rerun` with a `choice`, and the
decision is audited. A run that was cancelled, or that failed, has no step to resolve:
**Retry from failed step** starts a new run. A step that finished after its run
stopped is marked **Finished after the run stopped**, and a retry reuses it.

### The Logs page { #the-logs-page }

**Logs**, under **More** in the editor's header, lists what the workflow's quick logs
wrote across its runs, newest first: when, the step, its outcome and the message. Narrow
the lines by **Step**, **Outcome** and **Written** (the last hour, day, week or 30
days), search the message, and turn on **Include test runs**, which are left out until
you do. To see one run's lines, paste its id into **Run**, or type the first few
characters of it (at least four); **Show only this run** on a line fills it in, and
**See in Logs** on a run's page opens the log filtered to that run. A line opens the run
that wrote it. In the run view, each step's own lines sit under it, in the order they
were written. An organization API key with `workflows:view` reads them too, for
public-origin runs: see [Reading a workflow's log](api.md#reading-a-workflows-log).

### Alerts { #log-alerts }

An alert tells people when the log gets too busy with something. Below the list, the
**Alerts** card holds a workflow's rules; **Add alert** opens one. A rule has a name
and counts the lines that match:

- **Outcomes**: the results that count, from those the chosen step's log writes, plus
  `error`. A line that left by several ports matches each of them.
- **Step**: one step, or every step that logs.
- **Message contains**: optional words, matched in any case.
- **Occurrences** and **Within**: at least that many matching lines (1 to 1000) in 5,
  15, 30 or 60 minutes, 4 hours or a day.

A rule fires at most once per window: after it fires, it stays quiet for the length of
its window, then counts again from that moment, and a line is never counted for two
firings. Only real runs count; a test run's lines never raise an alert. A workflow
holds up to 25 rules, and a switch on each pauses one.

**Who is told** is the workflow's **owner**, which a new rule starts with, the
organization's **admins**, or **specific people** you pick; a person who has left the
organization is skipped. Each of them gets a notification in the bell and an email, as
their own [notification preferences](governance.md#alerts) allow, and one who can no
longer view the workflow no longer sees it. The notification says how many lines
matched, and its link opens the Logs page filtered to the rule's step and outcomes. A
rule with an outcome that the live version's step does not have is flagged in the list.

Anyone who may view the workflow sees its rules; whoever may edit it, by role or by a
grant on it, adds, changes, pauses and deletes them. The rules are not part of the
public API.

## Starting a workflow from outside the console { #starting-a-workflow-from-outside-the-console }

A workflow may have several independent **triggers**, for example Manual, Webhook and Schedule. Adding a trigger keeps existing starts and their connections. Each run chooses one start and follows only its reachable branch; it never waits for another trigger to fire. A shared step may read only data available from every start that reaches it. Normalize inputs separately before sharing steps when their payloads differ.

Publishing activates every configured unattended entry as the publisher. There is at most one of each unattended kind per workflow. Republishing preserves addresses and credentials for retained nodes and removes deleted registrations. **Trigger** under **More** shows every published start and its controls. The header's **Active** switch pauses or resumes all registrations. **Test draft** lets you choose a start; API requests may pass `entry_node_id`, but real requests can select only Manual/API entries, never an unattended trigger.

A version that starts from **Manual** or **API request**, or from no trigger at all, is started by whoever may run it, as themselves: **Start a run** under Runs, the
[HTTP API](api.md#running-a-workflow) or a WebSocket. Each run is checked, billed
and audited like one started here. Those doors start no other trigger, and each
other trigger has a door of its own. A test run of the draft takes any trigger, and
**Start a run** opens it on an input in that trigger's shape.

**Manual** is the trigger a person starts with **Test draft**; **API request** is the one a system calls, and **Trigger** shows its endpoint and a sample request. Give either its **Input fields** and a run asks for what it needs: **Test draft** and **Start a run** show a form with one box per field instead of the JSON, typed as the
field is, and an API call whose input does not fit is refused with the fields that
are wrong. See [core.input](reference/workflow-nodes.md#core-input).

### From the chat { #from-the-chat }

The chat's picker of who answers lists, below the agents, the published workflows
that start from **Chat message**. With one picked, each message starts a run of it,
and the trigger hands the steps after it the message as `prompt`, with the
`conversation_id` and the `user_id` of whoever sent it. The thread shows a card with
the run's status and a link to its steps, and the workflow's answer follows it once
the run ends.

The answer is written into the conversation when the run ends, whether or not the
chat is still open, so reopening the conversation reads it back. A run writes to
the conversation it was started from and nowhere else: reaching anyone else takes
an HTTP or notification step in the graph.

**Open chat** in the editor's header tries a draft that starts from a chat
message without leaving it. Each message sent in the panel starts a test run of
the draft with that message, the run opens on the canvas, and its answer - the
Output step's text - shows under the message. The runs are test runs with no
conversation to answer into, so nothing said in the panel reaches a real chat.
**New chat** starts over with a new conversation id.

### Over a WebSocket { #over-a-websocket }

`/api/v1/ws/workflow-runs` starts a run and streams its events, or follows one
already going. A client that lost its connection reconnects with the cursor of the
last event it saw and picks up exactly where it stopped. Events are written before
they are sent, so nothing is lost and nothing runs twice. The socket re-checks the
session and the member's access before every frame and every read of the stream.
The frames are in [The HTTP API](api.md#following-a-run-over-a-websocket).

### A webhook or a schedule { #a-webhook-or-a-schedule }

A **Webhook** trigger gets its address and **signing secret** the first time a
version with it is published. The publish shows the secret once, and later
publishes of the same node keep both; a webhook node deleted and added again gets a
new address. The sender signs the exact request body with the secret, HMAC-SHA256
in `X-Signature-256`, and names each delivery in `X-Delivery-Id`; GitHub's own
headers work as well. The trigger hands on the delivery's JSON as `body`, with its
`delivery_id`. A retry that repeats an id is answered with the first run and starts
nothing, because the id is recorded with the run it admitted, in one transaction.

A **Schedule** trigger runs every so often, daily at a set time or on a cron
expression, in the workflow's timezone (UTC unless its **Settings** name another)
and at most once a minute. It fires at its tick, not at the next minute's sweep
after it. Its **Input** is what every run
starts with, handed on as `input` beside the `fired_at` of the tick. A tick that
finds the last run still going is skipped rather than stacking a second run behind
it, and a tick the admission quota refuses waits for the next one.

Both run as the member who published the version, and that member's access is
checked afresh on every fire. A webhook whose member can no longer run the workflow
refuses its deliveries, and such a schedule is switched off and recorded in the
audit trail. **Pause** in the **Trigger** sheet stops either without a publish, and
**New secret** replaces a webhook's secret; the old one stops verifying at once.

Webhook bodies are bounded while streaming, even without Content-Length. Test
deliveries stop at the 64 KB pin limit; live webhook and GitHub deliveries use
`WORKFLOW_RUN_MAX_INPUT_BYTES`. A Respond to webhook step using status 204, 205 or
304 sends no body, as HTTP requires, while preserving its permitted headers.
PDF image conversion refuses documents over 2,000 pages before enumerating their
page sizes, even when only one page was requested.

### When a table record is added, changed or deleted { #when-a-table-record-is-added }

A **Table record** trigger names a table, the record `events` it starts on - added,
changed, deleted - and filters on the record as it was added or changed to, or as it
was before its deletion, from the console, the API, an agent or another workflow's
table step. A change starts it only when a chosen column changed, when the table's
columns are chosen.

It hands on the record: its `record_id`, the `event`, its `values` by column id, the
same values as `fields` by label, a choice as its option's label, `before` and the
`changed` columns for a change or a deletion, and the `author_id` of whoever did it.
Publishing it needs read access to the table, and nothing done before the publish
starts it.

A run started this way carries the chain of triggers it came through, so a workflow
that writes back into a table whose trigger started it is blocked rather than
looping.

The table's own **Triggers** lists the workflows that start from it, pauses and
resumes them, and shows what each decided about every record. See
[Virtual Tables](virtual-tables.md#triggers).

### From a form { #from-a-form }

**Test draft** opens an authenticated form preview for a single Form trigger. Its URL includes the entry node so independent forms stay distinct. Submitting uses the saved draft and starts a test run with the entered answers; open that run to inspect its result. Previewing does not publish a public link. A viewer can inspect the page but cannot execute a draft.

The Form step shows test and published links beside its configuration. **Appearance** controls the accent, standard or wide page width, and card or plain layout. **Preview appearance** uses the same renderer as the public page. Descriptions support Markdown; input fields, button text and the success message remain configurable. Test runs can still execute the workflow's actions.

A **Form** trigger gives the workflow a public page: a title, a description and one
box per field it declares, typed as **Manual**'s fields are, with its own words on
the button and after sending. Publishing creates the page, and **Trigger** shows its
link to copy or open. Anyone with the link fills it in, without signing in, and
each answer that fits the fields starts one run as the member who published the
form. The steps after it read the answers as `payload`, and the runs page says a
form started it.

The link is the page's only credential and survives every publish of the same node.
**New link** replaces it, and the old one then answers as if there were no form;
pausing the trigger closes the page. Answers that do not fit are named on the page
and start nothing, a hidden box catches scripts, and each form takes at most
`RATE_LIMIT_FORM_SUBMISSIONS_PER_MINUTE` answers a minute. See
[trigger.form](reference/workflow-nodes.md#trigger-form).

### From GitHub { #from-github }

A **GitHub** trigger starts the workflow when something happens in one repository:
an issue, a comment, a pull request or its review, a push, a release or an Actions
run - whichever **Starts on** names, and only the **actions** listed, such as
`opened`, when any are. Publishing gives it its own address and signing secret. With
**Set up the webhook for me** on and the organization's GitHub account connected
with permission to manage webhooks, the publish registers the hook on the repository
and registers it again on every later publish; otherwise it shows the secret once,
to paste with the address from **Trigger** into the repository's **Settings >
Webhooks**.

Each delivery GitHub signs for that repository, event and action starts a run as
the member who published the workflow, with the `event`, `action`, `repository`,
`sender` and the whole `payload`. A redelivery answers with its first run, and
anything else - GitHub's `ping` included - is skipped. **New secret** replaces the
secret and registers the hook again where the account set it up. See
[trigger.github](reference/workflow-nodes.md#trigger-github).

### From an email { #from-an-email }

A **Gmail** trigger starts the workflow when a message arrives in the organization's
Gmail mailbox - the one connected through the **Gmail** portal. The step's panel says
whether a mailbox is connected and connects one, and publishing is refused until it
is. The mailbox is read by the poll that also fires agents' Gmail triggers, every
minute, and each new message that fits every filter set - **Subject contains** and
**Sender contains**, ignoring case, and **Label**, exactly - starts a run as the
member who published the workflow.

**Check for new mail every**, in the step's mailbox block, changes that pace (1, 5,
15, 30 or 60 minutes). It is a setting of the mailbox and applies to every trigger on
it.

**Sender contains** reads the sender's address, never the display name: `@acme.com`
matches that domain exactly and not its subdomains, a full address matches that
address, and other text matches part of the address. With it set, a message must also
pass the authenticated-sender check - DMARC passed, or the sender's domain signed it
with DKIM - so a `From` anyone can type does not start a run. Messages labelled
`SENT`, `DRAFT`, `SPAM` or `TRASH` are not arrivals and start nothing, unless
**Label** names one of those.

The run gets the `sender`, `to`, `subject`, `text`, `snippet`, `labels` and the
mailbox's `message_id`, and the thread the message belongs to: `thread_id`, the
`rfc_message_id` (the `Message-ID` header), `in_reply_to`, `references`,
`received_at` and the `html` body. The sender writes the three header fields, so a
reply can be threaded with them but they prove nothing about who sent it. A message
read twice starts its run once, and one the organization had no room to run yet is read again a minute later. See
[trigger.gmail](reference/workflow-nodes.md#trigger-gmail). To read the `html` body
as text, links or what a CSS selector picks, bind it to
[`html.parse`](reference/workflow-nodes.md#html-parse).

An **Outlook** trigger does the same for the organization's Microsoft 365 mailbox,
connected through the **Outlook** portal. Microsoft Graph is read one folder at a
time, so the step names the **Folder** it watches - the inbox unless it says
otherwise - and, to read a shared mailbox the connected account can open, a
**Shared mailbox**. The filters are **Subject contains**, **Sender contains**,
**Has attachments**, **Importance** and **Category**. The first time a folder is
read it starts from the moment the workflow was published or last switched on, so
mail already there starts nothing.

Naming a shared mailbox the organization's Microsoft grant can open takes the permission
to manage connections, as it does for Outlook agent triggers; a workflow already
listening to one keeps it through later publishes, and changing it needs the permission again. If Outlook says the folder can no longer be read, the workflow is
switched off and the audit log says why.

The run gets the same fields as a Gmail
run, with `labels` holding the message's categories and `mailbox` the shared
mailbox it came from. See
[trigger.outlook](reference/workflow-nodes.md#trigger-outlook).

Both mail triggers take outside input: anyone can send the mailbox a message, so
bind what the run does with it as you would for a webhook.

A message's `attachments` list each file's name, declared type and size; a mailbox
lists at most 20 per message, and a `text` or `html` body is read up to 20,000
characters. A run the mailbox started stores them as files of the run, and each one
carries its `file` and `stored: true`. Of the attachments listed, only the first 10
are considered, up to 25 MiB together, and each must fit the chat-upload size limit
and file-type allowlist and the organization's storage quota.

One that is left out carries a `reason`: `too_many` (past the first 10),
`too_large`, `type_not_allowed`, `quota` or `unreadable` - the mailbox answered 400,
401, 403 or 404 for it, or its grant is missing, switched off or cannot be renewed.
A test run reads nothing from the mailbox, so its attachments are `not_fetched`.
When the mailbox fails in a way a retry may cure, the step fails with
`MAIL_ATTACHMENT_UNREACHABLE` and is retried.

### From a channel message { #from-a-channel-message }

A **Channel message** trigger hands a Slack, Mattermost or Telegram bot's messages
to the workflow. Each message the bot would have answered with its own agent - it
passed the bot's access policy, its sender was admitted, and in a channel it named
the bot - starts a run as the member who published the workflow, when it fits
**Where** and **Only when the message contains**. A message naming an agent by
`@handle` still reaches that agent, and one that does not fit is answered by the
bot's agent as before, so a workflow can take refunds and leave the rest.

The trigger hands on the `text`, the `sender` - with the member they linked, if
they did - and the `channel_id` and `thread_id` a **Send a message** step of the
same platform takes, so the answer lands in the thread the message came from. Slack
and Mattermost triggers hand on a thread even for a top-level message, because the
message itself roots it, so a bound reply is threaded; a Telegram trigger hands on a
topic only inside a forum topic.

A **Send a message** step added after a **Channel message** trigger starts as the
trigger's bot, with `channel_id` and `thread_id` bound, when the two platforms match. A
bot's messages start one workflow at most, and listening to a bot needs `channels:manage`.
A voice note arrives as its transcript; other attachments are not handed on. See
[trigger.channel_message](reference/workflow-nodes.md#trigger-channel-message).

### When another workflow calls it { #when-another-workflow-calls-it }

A **Called by a workflow** trigger makes a workflow others run as a step: shared
logic - enrich a lead, file a ticket - kept in one place. It declares its fields as
**Manual** does, and another workflow's **Run a workflow** step, which offers only
workflows published this way, starts it with the input it binds, checked against
those fields first.

The step waits for the called run and hands on its `output`, or
goes on at once with **Wait for it to finish** off. The called run is linked to the
calling run both ways - its page says **Called by** that run, and the step's line on
the caller's page opens the run it started - and shows on the runs pages like any
other. A run an error workflow started says which run's failure started it. A call back into a workflow
already running in the chain, or more than five calls deep, is refused.

Called workflows inherit the caller's remaining run budget and the earlier deadline.
Their spend counts toward the caller's total; `own_cost` exposes the caller's direct
fees for consumers aggregating run records without counting descendants twice.
With a finite caller budget, **Wait for it to finish** must stay on. Cancelling a
caller or revoking its access stops a child before its next dispatch; an external
request already in flight may finish. Retrying a failed call reuses successful
steps of its original, frozen child rather than repeating their effects. A still
running original child must finish or be stopped first. File outputs are explicitly
imported into the caller, and callee access is rechecked when a waiting call resumes.

The caller's daily chart and per-step statistics include called-run fees too.

Recovery stops if a successful step has lost its output, or a called run has
been deleted or has cyclic retry history. It does not repeat effects to recreate
that history. Called-run cancellation, budget exhaustion and revoked authority
also remain failures that an error branch cannot hide.

### From an agent { #from-an-agent }

For new agent tools, bind the AgenticOS platform MCP server and select the workflow discovery, `run_workflow` and execution-reading tools needed. The published workflow's declared input is passed as `fields`; the returned run must be read until it finishes. MCP calls use the requesting member's permissions and retain write approval. An agent executing inside a workflow must call another workflow through a `workflow.run` node. Existing Workflows capability bindings remain compatible: they keep their explicit workflow IDs, wait limit and page-action grants.

A run with no member behind it (a widget, embed or hosted-page visitor, an
unlinked channel sender, an agent event trigger's delivery) starts none.

### From an app { #from-an-app }

A [published page](artifacts.md#actions) can start a workflow that its agent has bound
and that starts from **Manual** or **API request**. The page only asks. The member
viewing it is shown a dialog with the workflow's own name and every input value, and
the run starts only when they confirm. It is theirs: their access, their budget and
their runs page, checked, billed and audited like one started from **Start a run**,
and subject to the same admission quota. A run with no member behind it, or from a
session that is impersonated, starts none.

The runs page says such a run was started by **A page**, and **Started by** filters
on it; over the API its `triggered_by` is `app`. The run also records the page and the
version the member was looking at, and a retry keeps them. The page reads back only the
run's status, its answer and the first line of an error.

### When another workflow fails { #when-another-workflow-fails }

An **On failure of a workflow** trigger makes an error workflow. Picked as another
workflow's error workflow in its **Settings**, it is started once for each real run
of that workflow that ends failed, with the run's `run_id`, its `workflow_id` and
`workflow_name`, the `step_id` and `step_name` of the step that failed, and the
`error` it ended with. It runs as the member who picked it, who must still be able
to run it. A test run starts nothing, and neither does the failure of a run an
error workflow is, so a failing error workflow never starts itself again.
## When something goes wrong { #when-something-goes-wrong }

**What a run promises.** A step's result and the dispatch of the steps after it
are saved together, so a worker that stops between steps loses nothing: another
picks the run up where it was. A worker that stops inside a step leaves an attempt
nobody saw end. A step that is safe to repeat is tried again. A table write replays
its first write through its receipt rather than writing twice, and a notification is
sent once. A step that may already have acted elsewhere and promises nothing more -
running an agent is one - is never repeated on its own: the run stops as **Needs
attention**, so a model is not paid twice or a message sent twice without anyone
deciding it.

Nothing else is exactly once. An HTTP call, an upload or a file write may be made
again after such a stop, so a receiving system that must not see a request twice
needs an idempotency key of its own. Each step's retry promise is listed in the
[node reference](reference/workflow-nodes.md).

| What you see | Why | What to do |
|---|---|---|
| **Needs attention** | A step that may have acted was interrupted, or stopped waiting with nothing to wake it | Check whether its effect happened, then **Resolve** the step on the run: run it again, use a result it reported late, take its error route or fail the run. Cancelling the run, then **Retry from failed step**, starts over |
| `PRINCIPAL_REVOKED` | The member the run acts as lost access, or their account was deactivated | Have a member who may run the workflow publish it again, so its trigger runs as them |
| `WORKFLOW_TRIGGER_MISMATCH` | The run was asked for through a door its live trigger is not: by hand or the API for a workflow that starts from a webhook, or in the chat for one that does not start from a chat message | Start it the way its trigger says, or test the draft, which takes any trigger |
| `INVALID_BINDING` | A value did not fit the field it was bound to | The step's error names the field; fix the binding or the value upstream |
| `REVISION_CONFLICT` | Someone changed a record after the step read it | Route the step's error to a fresh read with `error.handle` |
| A table trigger's history says **Blocked** | The run would have started itself again, or its chain went too deep | See [Triggers](virtual-tables.md#triggers) |
| A webhook answers `403` | The signature does not match the body, or the member it runs as can no longer run the workflow | Sign the exact bytes sent with the current secret, or have a member who may run it publish it again |

## Keyboard and accessibility { #keyboard-and-accessibility }

Every part of the editor has a path that needs no pointer. The step picker is a list you move through with the arrow keys and pick from with Enter, every icon-only control carries a spoken label, and
the canvas takes keyboard focus so you can tab across its steps and connections.
A connection can be made from the keyboard: start one from a node, then complete
it at a compatible target.

The canvas shortcuts fire only while the focus is inside the editor, so they
never steal a key from a field elsewhere on the page:

Drag with the left mouse button to select objects. Hold Shift while dragging to pan; middle and right drag also pan. `Ctrl`/`Cmd` + `A` selects every object in the current scope, including notes at the root.

Watched runs show a moving pulse into the active step and a border sweep on its card. A short completion sweep keeps fast runs legible without changing their actual status or timing. Historical runs stay still; system reduced-motion preferences disable movement. Duration, cost and completed steps align in the summary, with the start time beside the status.

| Keys | Does |
|---|---|
| `Tab` | Open the step picker |
| `Ctrl`/`Cmd` + `Enter` | Test run the draft, wherever the focus is on the page |
| `Ctrl`/`Cmd` + `Z` | Undo |
| `Ctrl`/`Cmd` + `Shift` + `Z`, or `Ctrl`/`Cmd` + `Y` | Redo |
| `Ctrl`/`Cmd` + `C` | Copy the selection |
| `Ctrl`/`Cmd` + `X` | Cut the selection |
| `Ctrl`/`Cmd` + `V` | Paste, offset so it does not cover the original |
| `Delete` or `Backspace` | Delete the selection |
| `Escape` | Cancel a connection in progress |
| `?` | Show these shortcuts |

A paste gets fresh ids and remaps the bindings among the copied steps, so pasted
steps read from each other rather than from the originals. Every edit shortcut is
inert while the editor is read-only - a published version, or **View only**;
`Escape` still cancels a stray connection, and `?` still shows the shortcuts.

Copy and paste have three limits:

- **A bound step reads from where it read before.** A copied step keeps its
  bindings. One that reads from a step you did not copy keeps reading from the
  original, but nothing connects the pasted step to it, so it does not validate until
  you connect them. Select both steps to copy the pair, and the copy reads from its
  own upstream step.
- **A connection travels only with its two steps.** Selecting a connection alone and
  copying does nothing.
- **The shortcuts belong to the canvas.** They work while focus is on the canvas, and
  clicking anywhere in it — a step, empty canvas, a connection — keeps it there. Focus in a step's settings or the step picker keeps the keys for those fields, so click
  the canvas before pressing them.

Agent image attachments share a 20 MB byte ceiling, checked before each file
is loaded, including repeated references. MCP results redact resolved authentication
headers and credentials from text and nested data. Workflow filenames are normalized
centrally before storage, preserving extensions within 255 characters. CSV fields
can use the step’s configured file byte limit, up to 50 MB; parser refusals are typed.

A loop measures its latest yielded results and unhandled errors in SQL before
loading them. `WORKFLOW_FOREACH_MAX_OUTPUT_BYTES` defaults to 10 MiB, including
collection overhead; exceeding it fails with `FOREACH_OUTPUT_TOO_LARGE`. Yield
smaller values or file references for large results. A summary whose generated
key collides with a group field fails with `SUMMARY_KEY_COLLISION`.

Run inputs, draft configurations and pinned outputs must fit PostgreSQL JSONB.
A handler result that cannot be stored becomes `INVALID_NODE_OUTPUT`, with no
automatic retry and with incurred fees retained. An external action may already
have completed, so inspect it before manually repeating the node.

Inline node outcomes share `WORKFLOW_NODE_MAX_OUTPUT_BYTES` (10 MiB by default), including the attempt result, run output and webhook response together. Larger outcomes fail with `NODE_OUTPUT_TOO_LARGE`, retain fees and do not retry automatically. Split out checks its expanded count (at most 10,000) before copying items, and conservatively bounds repeated fields by projected bytes; exceeding either bound returns `SPLIT_OUTPUT_TOO_LARGE`. Use file references for larger data.

A shallow model-field preflight also refuses repeated large values before serialization copies the whole result.

Workflow sockets preserve organization API-key identity and scope ceilings on every frame and stream poll. A view-only key cannot start runs, and keys cannot attach to a member’s private runs or write into personal chats. Key-started runs retain the key ceiling for workers; revocation closes the stream at its next poll.

Inline-agent skill and context galleries load every metadata page and offer Retry on failure. New eval inputs share run admission’s JSONB and byte bounds; older oversized cases remain readable for removal. Failed PDF or sandbox file batches remove files saved earlier in the batch, preserving existing files. A script that reports an error still retains its diagnostic log.

## Recap

- A workflow is a **draft you edit and a published, immutable version that
  runs** — start one from a trigger or a template, and **Duplicate** copies a draft
  into a fresh workflow.
- The **step picker** adds steps - from **+**, a step's output or a right click; the **canvas** wires them, and it
  refuses a connection between incompatible ports.
- An edge sets **order** and bindings carry **values**; connecting ports of the same
  shape creates the bindings for you.
- A parameter is **a value or data from a step** — **Data** reads one from a
  reachable, type-compatible upstream output, or puts it into text.
- The draft **saves itself**, and an edit from two places raises a banner with
  **Overwrite** or **Reload**.
- **Publish** is blocked while a problem stands and re-validates on the server;
  past versions stay viewable read-only, and **Restore to draft** makes one the
  draft again.
- Every action has a **keyboard path**, and the edit shortcuts are inert on a
  read-only published version or in **View only**.
- A workflow may have several independent **triggers**, for example Manual, Webhook and Schedule. Adding a trigger keeps existing starts and their connections. Each run chooses one start and follows only its reachable branch; it never waits for another trigger to fire. A shared step may read only data available from every start that reaches it. Normalize inputs separately before sharing steps when their payloads differ.
- A step's **policy** sets its tries, its time limit and whether its failures
  leave by an **Error** port; a **For each** step's body runs from **Loop item** to
  **Loop result** once per item.
- **Runs** lists every run, **Start a run** tests the draft or runs the published
  version, and a run shows its graph step by step as it happened.

New automations can be submitted through `prepare_workflow_draft`: one approval creates a private table and complete graph atomically. A failed validation leaves neither resource behind. `check_workflow_draft` checks the graph and its resource references without executing handlers or requiring a write approval. It explicitly reports that integrations remain unverified. Test runs with actions still require approval; schedule tests accept plain sample input and supply the event timestamp and configured defaults automatically. The run page distinguishes skeleton checks from integration verification.
