# Workflows

A **workflow** chains steps into an automation your agents carry out: read a
[table](virtual-tables.md), call an agent, branch on the result, loop over a
list. You build it on a canvas, wire the steps together, and publish it as an
immutable version — the same shape an [agent](concepts.md) has, a draft you edit
and a published version that runs.

This page is the visual editor: the list, the canvas and palette, how a node is
configured, autosave and publishing, and the keyboard paths through all of it.
The editor lives under **Workflows** in the console. The Workflows **list** page
carries a **"?"** that replays a walkthrough of that list; the editor itself has
no walkthrough.

## Creating and duplicating a workflow { #creating-and-duplicating-a-workflow }

**New workflow** opens a dialog that starts you from a blank canvas or a
template. **Blank workflow** is an empty canvas to build from scratch. The
templates are ready-made starting points — **Starter**, a single step to rename
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

## The canvas and the palette { #the-canvas-and-the-palette }

The **canvas** is where a workflow's steps and connections appear, and the editor
gives it the whole window below the header: the palette on its left, the
**Properties** panel on its right. A **node** is one step; an **edge** is a
connection that sets the order: the step it points to runs after the one it
leaves.

Each node is a card with the step's icon, its name and one line of what
it is set up to do - a condition, a URL, the number of mapped fields - and a step
with more than one way out lists its ports by name: **true** and **false**, **Each
item** and **Done**, and a red **Error** port on a step that handles its errors.
The canvas pans and zooms, and its controls sit in the corner - there is no
minimap.

The **Nodes** palette lists the node types your deployment has registered, in
groups that follow how a workflow reads - **Start and finish**, **Agents**,
**Knowledge**, **Data**, **Tables**, **Branching**, **Loops**, **Errors** - each group
folding away, each row with an icon, a name and its description. **Search nodes**
filters the list. You add a step two ways:

- **Drag** a node from the palette onto the canvas — the pointer path.
- **Click** a node to add it near the center of the view — the keyboard and
  touch path, which needs no drag.

The palette shows what is valid where you are. **Loop item** and **Loop result**
appear only inside a loop's body, since they mean nothing outside one, and a loop
is offered until loops are nested as deep as publishing allows.

!!! note "The node catalog grows over time"

    The palette is fed by the deployment's registered nodes, not a fixed list.
    Early on the catalog is small; more node kinds — calling an agent, reading and
    writing a table, branching and looping — arrive as later milestones register
    them, and they appear in the palette the moment they do, with no change to a
    workflow you already built.

## Configuring a node { #configuring-a-node }

What each node does, what it is configured with and what its failures mean is in
the [node reference](reference/workflow-nodes.md).

Select a node and the **Properties** panel opens on the right. Its fields fall
into two sections. **Configuration** holds static settings — the fixed choices
that do not change from one run to the next, including the resources a step is
pinned to. **Inputs** holds the values a step reads when it runs.

An input is filled one of two ways, and the **Bind** toggle beside the field
switches between them:

- **A literal** — you type the value directly into the field, the same control
  the field's type calls for.
- **A binding** — you read the value from another step's output. **Bind** turns
  the field into a **Source** picker whose options are the upstream outputs that
  are actually reachable here and carry a compatible type — a step's whole output,
  or one field inside it — each shown as *{node} · {port} ({type})*, or
  *{node} · {port} → {field} ({type})* for a field. A field with nothing compatible
  upstream says **No compatible upstream outputs** rather than offering an invalid
  pick.

A required input with no value yet is a validation problem, flagged on the node
rather than filled with a silent default. Some fields hold structured values: a
list of rows you **Add row** to, reorder and remove, or a typed choice that
swaps the sub-form beneath it. The panel recurses into those rather than sending
you to a separate screen.

Select more than one node and the panel reports how many are selected; select an
edge and it shows the connection's **From** and **To**.

### Resource pickers { #resource-pickers }

A setting that pins a resource opens a picker rather than a free-text field, so a
step names a real thing your organization has:

| Picker | What it pins |
|---|---|
| **Agent** and **Version** | An agent, then one of its published versions. Changing the agent clears the pinned version, because a version belongs to one agent |
| **Table** and **Columns** | A [virtual table](virtual-tables.md), then the columns the step reads — scoped to that table's current schema |
| **Secret** | A [vault](secrets.md) secret, by reference. A step stores the secret's id, never its value |

Each picker disambiguates same-named rows with context and marks a reference
whose target has gone away. The **Agent** and **Secret** pickers also carry a
create-new link — always, not only when the list is empty — while the **Table**
picker has none. A table whose schema changed since it was bound says so and offers
**Rebind to the current schema**, so a stale column set is a visible prompt
rather than a silent break.

### When a step is slow or fails { #when-a-step-is-slow-or-fails }

Below a step's fields, **When it is slow or fails** sets its policy. **Handle
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
before it draws it, so an incompatible wire never lands on the canvas.

An edge sets the order the steps run in; it does not move any data. The values a
step reads are its **bindings**, described under
[Configuring a node](#configuring-a-node).

So that a wire does not leave you binding every field by hand, connecting two ports that carry exactly the same
shape — an Echo's output to a Relay's input, say — also binds each of the
target's inputs to the field of the same name on the source. A field you had
already bound is left alone.

When the shapes differ, or a port carries no data,
nothing is bound and you pick each source yourself with **Bind**. Undo (`Ctrl`/`Cmd` + `Z`) takes
back the connection and its bindings together, and deleting an edge later leaves
its bindings in place, so remove or rebind them in the panel.

To delete a connection, select it: click the wire, and it is drawn heavier, the
panel shows its **From** and **To**, and a **Delete connection** button appears on
it. Press the button, or press `Backspace`, and the connection goes while the two
steps stay. The connections of a published version cannot be selected, so they
cannot be deleted.

A **For each** step runs its body once per item in a list. The body is not a
separate document - it is part of the same flat graph, shown on its own. **Edit
loop body** on the step, which says how many steps the body holds, enters that
view, and the **Workflow scope** breadcrumb in the canvas's corner shows where you
are, from **Workflow** down to the loop you opened. Each crumb navigates back out.

A body starts at **Loop item**, which the loop's **Each item** port connects to,
and ends at **Loop result**; nothing in it connects back to the loop, which
continues through **Done** once every item has been through the body. The palette
and the binding sources follow the scope you are in, and a step in a body may read
anything that ran before the loop. What the loop does is in the
[node reference](reference/workflow-nodes.md#loops).

## Validation feedback { #validation-feedback }

The editor checks the graph as you edit and shows what is wrong where it is
wrong. A selected node with a problem carries a badge counting its problems in
the panel header, a field with a problem shows its message inline, and a
collapsible list at the foot of the panel collects the problems together so each
one links to the node or field it is about.

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
graph, and the status beside the header reflects it — **Unsaved changes** while a
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
version is never changed after it is created. The publish dialog takes an
optional **Release note** describing what changed. If the graph still has
problems, publishing is blocked with **Fix the problems below before
publishing**, so a version that would not validate is never created.

Publishing does not end your editing. The draft goes on existing independently of
any published version, so you keep editing it straight away. **History** in the
editor's header opens every published version with its release note. **View**
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

## Running a workflow { #running-a-workflow }

**Runs** in the editor's header, and the runs icon on a workflow's card, open its
runs, newest first, each with its status, whether it ran the draft or the published
version, what started it, when, for how long and at what cost. **Start a run**
starts one by hand: **Test the draft** runs the draft as it stands, and **Published
version** runs the live one. Its **Input (JSON)** is what the workflow's **Input**
step hands on as `payload`.

A run opens on its duration, its cost and how many steps it took, then the error it
ended with, if any. Beside them is the graph it executed, with each step marked by
what the run did with it, its tries and its error, and the steps it never reached
faded. **Open loop body** shows a loop's iterations the same way.

The run's output
and every step it took, iteration by iteration, sit alongside. A run still going
refreshes itself every couple of seconds, and **Cancel run** stops it.

## Keyboard and accessibility { #keyboard-and-accessibility }

Every part of the editor has a path that needs no pointer. Clicking a palette
node adds it without a drag, every icon-only control carries a spoken label, and
the canvas takes keyboard focus so you can tab across its steps and connections.
A connection can be made from the keyboard: start one from a node, then complete
it at a compatible target.

The canvas shortcuts fire only while the focus is inside the editor, so they
never steal a key from a field elsewhere on the page:

| Keys | Does |
|---|---|
| `Ctrl`/`Cmd` + `Z` | Undo |
| `Ctrl`/`Cmd` + `Shift` + `Z`, or `Ctrl`/`Cmd` + `Y` | Redo |
| `Ctrl`/`Cmd` + `C` | Copy the selection |
| `Ctrl`/`Cmd` + `X` | Cut the selection |
| `Ctrl`/`Cmd` + `V` | Paste, offset so it does not cover the original |
| `Escape` | Cancel a connection in progress |

A paste gets fresh ids and remaps the bindings among the copied steps, so pasted
steps read from each other rather than from the originals. Every edit shortcut is
inert while you are viewing a published version, which is read-only; `Escape`
still cancels a stray connection.

Copy and paste have three limits:

- **A bound step reads from where it read before.** A copied step keeps its
  bindings. One that reads from a step you did not copy keeps reading from the
  original, but nothing connects the pasted step to it, so it does not validate until
  you connect them. Select both steps to copy the pair, and the copy reads from its
  own upstream step.
- **A connection travels only with its two steps.** Selecting a connection alone and
  copying does nothing.
- **The shortcuts belong to the canvas.** They work while focus is on the canvas, and
  clicking anywhere in it — a step, empty canvas, a connection — keeps it there. Focus
  in the **Properties** panel or the palette keeps the keys for those fields, so click
  the canvas before pressing them.

## Recap

- A workflow is a **draft you edit and a published, immutable version that
  runs** — start one blank or from a template, and **Duplicate** copies a draft
  into a fresh workflow.
- The **palette** adds steps by drag or click; the **canvas** wires them, and it
  refuses a connection between incompatible ports.
- An edge sets **order** and bindings carry **values**; connecting ports of the same
  shape creates the bindings for you.
- A node's inputs are **a literal or a binding** — **Bind** reads a value from a
  reachable, type-compatible upstream output.
- The draft **saves itself**, and an edit from two places raises a banner with
  **Overwrite** or **Reload**.
- **Publish** is blocked while a problem stands and re-validates on the server;
  past versions stay viewable read-only, and **Restore to draft** makes one the
  draft again.
- Every action has a **keyboard path**, and the edit shortcuts are inert on a
  read-only published version.
- A step's **policy** sets its tries, its time limit and whether its failures
  leave by an **Error** port; a **For each** step's body runs from **Loop item** to
  **Loop result** once per item.
- **Runs** lists every run, **Start a run** tests the draft or runs the published
  version, and a run shows its graph step by step as it happened.
