# Workflows

A **workflow** chains steps into an automation your agents carry out: read a
[table](virtual-tables.md), call an agent, branch on the result, loop over a
list. You build it on a canvas, wire the steps together, and publish it as an
immutable version — the same shape an [agent](concepts.md) has, a draft you edit
and a published version that runs.

This page is the visual editor: the list, the canvas and palette, how a node is
configured, autosave and publishing, and the keyboard paths through all of it.
The editor lives under **Workflows** in the console, and its **"?"** replays a
walkthrough of the page you are on.

## Creating and duplicating a workflow { #creating-and-duplicating-a-workflow }

**New workflow** opens a dialog that starts you from a blank canvas or a
template. **Blank workflow** is an empty canvas to build from scratch. The
templates are ready-made starting points — **Starter**, a single step to rename
and wire up, and **Two-step sequence**, two steps already connected for a linear
flow. Pick one with **Use** and you land in the editor.

The list groups every workflow you can see by status — **Drafts** you are still
building, the **Published** versions that run, and the **Archived** ones — and
**Filter by status** narrows to one. Each row's badge shows **Draft**,
**Published** or **Archived**.

**Duplicate** copies a workflow's current draft into a fresh one named
*{name} (copy)*. A duplicate is a new workflow with its own draft, never a copy
of a published version.

!!! info "An empty list may be a filter, not an empty organization"

    **No workflows yet** and **Nothing matches** are different states: the first
    is an organization with none, the second a status filter with no rows under
    it. **Clear filter** returns the full list. A workflow shared with you shows
    under the same list once you have `workflows:view`.

## The canvas and the palette { #the-canvas-and-the-palette }

The **canvas** is where a workflow's steps and connections appear. A **node** is
one step; an **edge** is a connection carrying one step's output into the next.
The canvas pans and zooms, and its controls sit in the corner — there is no
minimap.

The **Nodes** palette on the side lists the node types your deployment has
registered, grouped by category, each with an icon, a name and a description.
**Search nodes** filters the list. You add a step two ways:

- **Drag** a node from the palette onto the canvas — the pointer path.
- **Click** a node to add it near the center of the view — the keyboard and
  touch path, which needs no drag.

The palette shows what is valid where you are. Inside a loop's body it hides node
kinds that cannot live there, so the list you see is always addable at the scope
you are editing.

!!! note "The node catalog grows over time"

    The palette is fed by the deployment's registered nodes, not a fixed list.
    Early on the catalog is small; more node kinds — calling an agent, reading and
    writing a table, branching and looping — arrive as later milestones register
    them, and they appear in the palette the moment they do, with no change to a
    workflow you already built.

## Configuring a node { #configuring-a-node }

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
  are actually reachable here and carry a compatible type, each shown as
  *{node} · {port} ({type})*. A field with nothing compatible upstream says **No
  compatible upstream outputs** rather than offering an invalid pick.

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

Each picker disambiguates same-named rows with context, offers a create-new
escape hatch when the list is empty, and marks a reference whose target has gone
away. A table whose schema changed since it was bound says so and offers
**Rebind to the current schema**, so a stale column set is a visible prompt
rather than a silent break.

## Connections and foreach scope { #connections-and-foreach-scope }

You draw an edge by connecting one node's output port to another node's input
port. The editor refuses a connection between ports that carry different shapes
before it draws it, so an incompatible wire never lands on the canvas.

A `foreach` step runs its body once per item in a list. The body is not a
separate document — it is part of the same flat graph, shown on its own. **Open
body** on the step enters that view, and the **Workflow scope** breadcrumb shows
where you are, from **Workflow** at the root down to the loop you opened. Each
crumb navigates back out. The palette and the binding sources follow the scope
you are in, so what you can add and what you can read from are always the ones
valid at that level.

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
any published version, so you keep editing it straight away, and each published
version is listed under **Version history** with its release note. **View** opens
a past version read-only — a published version is read-only, and to make changes
you go on editing the draft.

## Running a workflow { #running-a-workflow }

A workflow's **Runs** tab is where its test and production runs will appear, per
step with their inputs, outputs and costs. Run history lands once the workflow
runner ships; until then the tab shows that it is not available yet, and the
editor is for building and publishing.

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

## Recap

- A workflow is a **draft you edit and a published, immutable version that
  runs** — start one blank or from a template, and **Duplicate** copies a draft
  into a fresh workflow.
- The **palette** adds steps by drag or click; the **canvas** wires them, and it
  refuses a connection between incompatible ports.
- A node's inputs are **a literal or a binding** — **Bind** reads a value from a
  reachable, type-compatible upstream output.
- The draft **saves itself**, and an edit from two places raises a banner with
  **Overwrite** or **Reload**.
- **Publish** is blocked while a problem stands and re-validates on the server;
  past versions stay viewable read-only.
- Every action has a **keyboard path**, and the edit shortcuts are inert on a
  read-only published version.
