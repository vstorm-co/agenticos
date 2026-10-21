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

**New workflow** opens a dialog that starts you from a trigger or a template.
**How does it start?** offers each trigger - **Manual**, **API request**, **Chat message**, **Webhook**, **GitHub**, **Gmail**, **Schedule**, **Table record**, **Form**, **Channel message**, **Called by a workflow** and **On failure of a workflow** - each an otherwise
empty canvas that begins with it. The templates are ready-made starting points — **Starter**, a single step to rename
and wire up, and **Two-step sequence**, two steps already connected for a linear
flow. Pick one with **Use** and you land in the editor.

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

Under **Automations** the dialog also offers common workflows built on real
steps: **Lead intake** saves a webhook's leads to a table and answers the caller,
**Slack alert on failure** posts when another workflow fails, and **Daily
summary** has an agent write a weekday summary for the team. Each opens with its
table, bot, agent or people still to choose; the editor marks them, and it
publishes once they are chosen.

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
the same list. In the editor, click the name to rename the workflow - its handle, the
part API callers use, stays - click the description under it, or **Add a
description**, to change it, and **+ Tag** files it under a tag.

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

The **canvas** is where a workflow's steps and connections appear, and it has the
editor's whole width below the header. A **node** is one step; an **edge** is a
connection that sets the order: the step it points to runs after the one it leaves.

Each node is a card with the step's icon, its name and one line under it: what it
is set up to do - a condition, a URL, the number of mapped fields - or else the
group it belongs to, such as **Slack** or **Tables**. A step with more than one way
out lists its ports by name: **true** and **false**, **Each item** and **Done**,
and a red **Error** port on a step that handles its errors. A step that stops a
publish carries a red mark: hovering it lists the first problems, and clicking it
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

A new step never lands on top of another, is selected, opens its settings when it
has any, and the canvas scrolls to it when it falls outside the view. Inside a
loop's body every new step is wired into the body, so it stays there. The picker
shows what is valid where you are: **Loop item** and **Loop result** only inside a
loop's body, and a loop until loops are nested as deep as publishing allows.

Right-clicking a step offers **Open settings**, **Duplicate**, **Switch off** and
**Delete step**. With several steps selected, a bar at the bottom deletes them together.

**View only** in the header shows someone who may edit the workflow what a reader
sees: nothing on the canvas moves, connects or is deleted, a step opens read-only
on one click, and **Run** and **Publish** are gone. **Edit** turns it back, and the
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
the map button shows a minimap, and the keyboard button - or **?** - lists every
shortcut; **Tab** opens the step picker. None of them fires while you type in a field.

## Configuring a node { #configuring-a-node }

What each node does, what it is configured with and what its failures mean is in
the [node reference](reference/workflow-nodes.md).

A click selects a step; a double click opens it in a dialog over the canvas (where
nothing can be selected - a published version, **View only** - one click does): its
name and what it does at the top, and under them, in plain words, every problem that
stops a publish - **Not connected yet**, for a step nothing leads to, and a field's
problem after the field's name, which takes you to the field.

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
| **MCP server** and **Tool** | One of the organization's [MCP servers](mcp.md), with its service's mark, then one of the tools it listed when last tested. Choosing it needs `mcp:manage` |

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

### An agent configured in the step { #an-agent-configured-in-the-step }

An **Agent** step either pins an agent from the catalog or, with **Configure
here**, defines its own: a name, a model, instructions, capabilities with the
knowledge, skills and context files they read, and MCP servers - the same editors
the Builder uses. Delegation is the one capability it is not offered, because the
workflow is already where work is handed from step to step.

That agent belongs to the workflow. It is versioned with the graph and never
appears in the catalog. Its first run creates it, and a run after its
configuration changed publishes a new version of it first, checked as publishing
any agent is. Its runs show in Activity with its budget, approvals and history
like any other agent's, and its page there sends you back to the workflow.

**Copy its configuration into this step** starts from a catalog agent to adjust
it, and **Save as an agent** puts the step's agent in the catalog as a draft for
other workflows and people. **Max cost (USD)** caps what one execution of the step may
spend, beside the agent's, the workflow's and the organization's limits.

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

## Validation feedback { #validation-feedback }

The editor checks the graph as you edit and shows what is wrong where it is
wrong. Every step with a problem carries a red mark on the canvas and says it under its name when opened, and a field with a problem shows its message inline. The status at the canvas's top right reads **No problems**, or counts the problems and lists them, each under the name of its step and field; choosing one opens that step's settings.

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

**Publish** freezes the current draft as an immutable version that runs — a
version is never changed after it is created. The publish dialog names the version it makes and takes an optional
**Release note** describing what changed; when the draft has not changed since the live
version, it says so first. If the graph still has
problems, publishing is blocked with **Fix the problems below before
publishing**, so a version that would not validate is never created.

Publishing does not end your editing. The draft goes on existing independently of
any published version, so you keep editing it straight away. **Versions** in the
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

- **Runs under way at once** - a real run started past it is refused with `429`
  until one ends. A webhook's or GitHub's sender is told to retry, a schedule waits
  for its next tick, a mailbox is read again, and a table event or a form answer
  past it is refused. Test runs are neither counted nor held back.
- **Most one run may spend** - the run's own budget, the tighter of it and the
  version's: a run that reaches it stops before its next step, out of budget.
- **Most its runs may spend a month** - counted over the calendar month in UTC,
  test runs included. Once reached, no run starts - `402` - until the month turns
  or the budget is raised. The runs page shows the month's spend against it.

Over the API, `PUT /api/v1/workflows/{id}/settings` replaces them.

## Running a workflow { #running-a-workflow }

**Run** in the editor's header tests the draft at once - `Ctrl`/`Cmd` + `Enter` does
too - first asking for the fields a Manual or API trigger declares. The run then
shows on the canvas as it happens. A pill on each step's corner says where it is -
**Pending**, **Starting**, **Running** with a ticking time, **Waiting**, **Failed**,
**Needs attention**, **Skipped** or **Not reached** - and a step that succeeded shows
how long it took. The wire into a running step moves, the path taken turns green,
and a branch the run did not take fades. A failed step shows its error under its
card and shakes once. A connection says how many items went along it when the step
before handed on a list, and a bar at the bottom says how the run stands, with
**Open run** for its page. While the run goes on, the square beside **Run** stops
it, with no question asked. The canvas keeps the run once it ends; the next edit
hides it and leaves a bar saying the graph changed since, still with **Open run**. A step that waited and went on counts one try, not two. **Run** waits while an edit is still saving, and says why it cannot
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

The dashboard's **Workflows** card adds the same up across every workflow you can
see, over the period the dashboard is set to: runs, failures, cost and the five
busiest. Above them it counts the runs waiting for a person now - an approval or a
step that needs attention - whenever they started. Over the API it is
`GET /api/v1/workflows/summary?from=2026-10-01&to=2026-10-31`.

A run opens on its duration, its cost and how many steps it took, then the error it
ended with, if any. Beside them is the graph it executed, drawn as the editor draws
a run: each step's pill, its tries and its error, and the steps it never reached
faded. Only a page open while the run went on moves; one opened later is still. **Open loop body** shows a loop's iterations the same way.

The run's answer - its text, its structured result, the passages it drew on and how
many files it made, with the JSON itself under **Raw output** - and every step it
took, iteration by iteration, sit alongside. A run still going
refreshes itself every couple of seconds, and **Cancel run** stops it. Its **Files** list what its steps stored - a download, a rendered page, a script's output - each one downloadable.


In the list a test run's version reads **Draft (test)** and a real one's
**Published**, and a run started from the console or the HTTP API reads **Console or
API**. **Status**, **Version**, **Started by** and **Started** (the last hour, day, week or
30 days) narrow the runs, and the list answers a
page at a time; each filter is kept in the address, so a filtered list can be
linked. **Runs** on the workflows list shows every workflow's runs together. On a
run's page, clicking a step shows its **Input** and **Output** from that run.

**Retry from failed step** starts a new run of the same version and input in which
each step that succeeded hands on what it handed on before, so only the failed
step and what it did not reach run, and a write is never made twice. A loop runs
again and reuses each item's steps that had succeeded. **Debug in editor** pins
what each step outside a loop handed on in that run onto the draft's steps, so a
test run starts from where that run was. Over the API, `POST
/api/v1/workflow-runs/{id}/retry` retries, and `GET /api/v1/workflow-runs` takes
`status`, `mode`, `triggered_by`, `created_after` and `created_before`.

## Starting a workflow from outside the console { #starting-a-workflow-from-outside-the-console }

A workflow starts from one **trigger**, the first node on its canvas. The
**Triggers** group at the top of the step picker holds them all: **Manual**, **API request**, **Chat message**, **Webhook**, **GitHub**, **Gmail**, **Schedule**, **Table record**, **Form**, **Channel message**, **Called by a workflow** and **On failure of a workflow**. Adding one to a
workflow that already has a trigger replaces it in place, and the wires and
bindings that leave the old one leave the new one. **New workflow** starts a
workflow from the trigger you pick there.

Publishing a version is what switches its trigger on. A webhook, a schedule, a
table trigger, a form and a bot's messages then run that version as the member who
published it, and the next
publish moves them to the new version. A publish that starts from a different
trigger switches the old one off. **Trigger**, under **More** in the editor's header, shows the live
trigger and its state, and says when the draft starts differently.

A version that starts from **Manual** or **API request**, or from no trigger at all, is started by whoever may run it, as themselves: **Start a run** under Runs, the
[HTTP API](api.md#running-a-workflow) or a WebSocket. Each run is checked, billed
and audited like one started here. Those doors start no other trigger, and each
other trigger has a door of its own. A test run of the draft takes any trigger, and
**Start a run** opens it on an input in that trigger's shape.

**Manual** is the trigger a person starts with **Run**; **API request** is the one a system calls, and **Trigger** shows its endpoint and a sample request. Give either its **Input fields** and a run asks for what it needs: **Run** and **Start a run** show a form with one box per field instead of the JSON, typed as the
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
and at most once a minute. Its **Input** is what every run
starts with, handed on as `input` beside the `fired_at` of the tick. A tick that
finds the last run still going is skipped rather than stacking a second run behind
it, and a tick the admission quota refuses waits for the next one.

Both run as the member who published the version, and that member's access is
checked afresh on every fire. A webhook whose member can no longer run the workflow
refuses its deliveries, and such a schedule is switched off and recorded in the
audit trail. **Pause** in the **Trigger** sheet stops either without a publish, and
**New secret** replaces a webhook's secret; the old one stops verifying at once.

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
is. The mailbox is read once a minute, by the poll that also fires agents' Gmail
triggers, and each new message that fits every filter set - **Subject contains** and
**Sender contains**, ignoring case, and **Label**, exactly - starts a run as the
member who published the workflow.

The run gets the `sender`, `to`, `subject`, `text`, `snippet`, `labels` and the
mailbox's `message_id`. A message read twice starts its run once, and one the
organization had no room to run yet is read again a minute later. See
[trigger.gmail](reference/workflow-nodes.md#trigger-gmail).

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
same platform takes, so the answer lands in the thread the message came from. A
bot's messages start one workflow at most, and listening to a bot needs
`channels:manage`. A voice note arrives as its transcript; other attachments are
not handed on. See
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

### From an agent { #from-an-agent }

An agent with the [Workflows](reference/capabilities.md#workflows) capability
starts the workflows its spec names as tools, when a conversation asks for what one
does. It reads each one's input fields, starts a run with them as the member it
acts for, and waits for the answer, up to the binding's limit. The run is checked,
billed and audited like one started from **Start a run**, and the runs page says it
was started by **An agent**. Only a published workflow starting from **Manual**,
**API request** or **Called by a workflow** can be given to an agent.

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
| **Needs attention** | A step that may have acted was interrupted | Check whether its effect happened, then cancel the run and start a new one if it did not. Resuming it from the console is not built yet |
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
- A workflow starts from one **trigger** node - **Manual**, an **API request**, a chat
  message, a signed **webhook**, a **schedule** or a new table record - and
  **publishing** switches it on, running as the member who published.
- A step's **policy** sets its tries, its time limit and whether its failures
  leave by an **Error** port; a **For each** step's body runs from **Loop item** to
  **Loop result** once per item.
- **Runs** lists every run, **Start a run** tests the draft or runs the published
  version, and a run shows its graph step by step as it happened.
