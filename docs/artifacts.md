# Artifacts

An **artifact** is a page an agent published: a report, a small dashboard, a
one-page summary somebody opens in a browser. It has a link that stays the same
when the agent publishes it again, so "every Monday, publish the week's numbers
to this page" is one link people bookmark rather than a new one each week.

An artifact is not a file. A chart, a generated PDF and a workspace file already
have a home in the chat and in the [workspace](sandbox.md). An artifact is the
thing that is *served*: it has an owner, a visibility and grants like an agent
or a skill, and it can be given a public link for somebody with no account.

## Publishing one

Turn on the **Artifacts** capability for the agent. It adds four tools:
`publish_artifact`, which the model calls when the result is something a person
should open rather than read once in the chat; `read_artifact`, which reads a
published page back; `list_artifacts`, which names the pages a run may open; and
`preview_artifact`, which draws a page and says what went wrong in it.

The page comes from one of three places:

- **A file in the agent's workspace**, ending in `.html` or `.md`. This is the
  usual case for an agent with the [Files & shell](reference/capabilities.md#files-shell)
  capability: it writes `report.html`, runs whatever builds it, then publishes
  the file. The bytes are read through the run's own workspace backend, so it
  works on every sandbox backend.
- **The page passed inline**, for an agent without a workspace or a short page.
- **Edits to the page already published** under that name - see below.

The chat shows a card for the published page. The card links to the version
*this* run published, so reading the conversation later still shows what was
published in it, not what the page shows today.

### Changing part of a page

Changing a word should not cost the whole page again. The agent calls
`read_artifact` with the page's name, which returns the current version as it
was written, then `publish_artifact` with the same name and `edits`: exact
replacements, applied in order. Each one must match exactly one place in the
page; a miss or an ambiguous match is sent back to the model to fix. The result
is a new version like any other.

The edits carry the version they were made against. If another run published in
between, nothing is written and the model is told to read the page again, so an
edited copy of an older page never replaces a newer one. Reading follows the
same rule as opening the page in the console: the person the run acts for must
be allowed to open it. A page over 100,000 characters is returned cut, and says
so; an edit can still name text past the cut.

### Finding a page again

Each message is a new run, and a run sees the earlier turns as text only, so the
model does not keep the names it published under. `list_artifacts` lists the
agent's pages in the run's environment, newest first and at most 50: each with
its name, title, current version, format, live bindings, visibility, whether a
public link is on, when it was published, its console link, and `may_edit` -
whether publishing under that name from this run updates the page rather than
being refused. The model checks it before choosing a new name.

The list is read as the person the run is for, by the console's rule: their own
pages, the organization's and those shared with them, or every page for a role
that sees every page. In a group chat the channel sees only organization-wide
pages: never the speaker's private or team pages, nor a page shared with the
speaker alone. A surface with nobody signed in, such as a public widget, lists
nothing.

## Live data

A page can show records from [Virtual Tables](virtual-tables.md) that stay
current, instead of the copy it was published with. The agent passes `bindings` to
`publish_artifact`: each binding is a name, a [saved view](virtual-tables.md#saved-views)
and the columns the page reads from it. `list_views` gives the agent each view's
id and columns. The page calls `agenticos.onData(render)`, and `render(data)` runs
with the first data and again on every refresh. `agenticos.data` is a Promise of
the first data.

```js
agenticos.onData((data) => {
  // data.tickets = { status, records, fields, count, truncated, limit, filters_dropped }
});
```

Each binding arrives as `status` (`ok` or `unavailable`), `records`
(`{id, <field>: value}`), `fields` (label, type, options and state for each),
`count`, `truncated`, `limit` and `filters_dropped`, which is true when a filter of
the view named a column that is gone, so the records match more than the view
meant.

A page that gets no reply within 10 seconds sees every binding
`unavailable`; a listener added after that asks once more.

A binding is `unavailable` when this viewer may not read its view or the view is
gone. A field whose column was removed is served under its field name as a
`text` field with value `null` and state `missing`; an archived column gives
`null` with state `archived`.

The records are read **when somebody views the page, with that viewer's own
access**, and are never stored in it. Two people opening the same page can see
different rows. The publish result lists each field as `Label (type)`, so the
agent can check it bound the column it meant; a binding carried forward unchanged
says `kept`.

A private view serves only its owner. Binding one still publishes the page, and the
result's `warning` gets a line saying that only the person sees its records until
the view is shared, which the agent tells them. Whether a colleague will see them
is answered where the page is shared: see
[Who sees a live page's records](#who-sees-a-live-pages-records).

Version 3 of the [page kit](#the-library-set) draws a binding for the agent:
`AO.records("#tickets", data.tickets)` inside `agenticos.onData` renders the
records as a table with a head from the fields' labels, numbers and dates
right-aligned, choices as badges and every value written as text. Before the
data it shows a loading line, and an `unavailable` or empty binding, a cut list
and a dropped filter each get their own message. `AO.onData` in version 3 is
the same call as `agenticos.onData`. A bound page whose script never asks for
its data still publishes, with a [warning](#the-page-contract-and-the-publish-warnings).

A binding name is lower-case letters, digits and `_`. A field name may be written
as its column is labelled: words of letters in any case, digits and `_`, with single
spaces between them, such as `Status` or `Created At`. Both are at most 64
characters, and `__proto__`, `constructor` and `prototype` are reserved for both
(`id` too, for a field). A page has at most 5 bindings, and a binding at most 50
fields.

### What the viewer sees

A page with bindings shows a **Live** badge on its card, in the dashboard's
artifact widget and in the viewer. In the viewer its dot pulses while the data
arrives and turns amber when some sources are unavailable to this viewer. A
viewer who can read none of them sees no badge, and neither does an older version.

The viewer has **Refresh**, which reads the data again and updates a page that
uses `agenticos.onData` in place, with when it was last read in the button's
tooltip. Beside it is a menu to refresh automatically: Off, every minute, every 5
or 15 minutes, or every hour. Each viewer picks their own, and the choice is
remembered per page in that browser.

Auto-refresh does nothing while the tab is hidden, and reads once when the tab
comes back if a tick was missed. It stops when the data is refused (the page is
gone for this viewer) and when no source on the page can be read, until the
viewer clicks Refresh and a read answers. A failure that says nothing about the
page, such as a server error, keeps it polling. A busy answer (429) is tried
again twice, a second apart, before the viewer is told "Busy, try again in a
moment."

A line under the strip appears only when something needs attention. A refused
page says "This page's live data is not available to you." A reader whose sources
cannot be read sees how many ("2 of 3 sources unavailable to you"). An editor,
meaning anyone who can edit the page, also sees why for each source (for example
its saved view is gone, its table is archived, the agent was not granted the
table, or you cannot read its saved view) with an **Open the table** link to the
bound view.

When an agent publishes a new version while somebody has the current one open,
the next read (a refresh, manual or automatic) moves the viewer to the new
version: the page is loaded again from the new version, with its own data. A
viewer who picked a version from the version menu stays on it.

On an older version, live data is not read. The viewer says "Live data only on the
current version." with **Open current**, and, for an editor, **Restore** for that
version. Restoring a version whose live sources are unavailable says which.

### Limits

Every answer is bounded, so one page cannot take the deployment down:

| Limit | Value |
|---|---|
| Bindings per page | 5 |
| Records per binding | 1,000 |
| Shaped data per page | 4 MiB, split fairly between the bindings |
| One query | at most 2 s |
| One page | 5 s deadline |
| Data loads | 30 a minute per viewer, one in flight per viewer, and a cap per process |

A cut binding says `truncated: true`, with `limit` set to `records` or `bytes`
and `count` as the number of records served. `bytes` also covers a read whose
measured cost ran out before the shaped data filled the page's share.

The deadline is enforced without cancelling any query: each query runs at most the
smaller of 2 s and the time left of the 5 s, and no query starts once the 5 s are
spent, so a page answers in about 5 s. Past a rate limit the route answers 429;
the console retries a busy answer twice. When Redis is down, the rate limit's
floor and the in-flight limit count per API worker, and the per-process cap
still bounds each worker.

### Who may publish a bound page

A page binds to a table only if the publishing agent's spec grants read on it,
checked when the page is published or a version restored. Revoking the grant
later does not stop pages already published, and each viewer still reads only
what their own access allows.

A bound page can be republished only by a run
acting for a member: the signed-in member (web chat, HTTP API), a linked channel
sender or a schedule's creator. A widget, embed or hosted-page visitor, an
unlinked channel sender and an agent event trigger's delivery (GitHub, email,
webhook relay) do not count, and neither does a workflow run admitted by a public
door or anywhere in such a run's chain.

## One name, one link

The identity of an artifact is its **name within the agent** - `weekly-report`,
`churn-dashboard`. Publishing under the same name updates the same artifact,
from any surface: the chat, the API, a [trigger](triggers.md) or a workflow. A
new name makes a new page. The name is lower-case letters, digits and hyphens,
up to 64 characters.

The name is also **within the environment** the run answered from. A run in a
named [environment](environments.md) - `staging`, `dev` - publishes a page of its
own beside the default environment's, so trying a new version of an agent cannot
republish the page production readers have bookmarked. The environment is read
from the run itself, never from the model, and the list and the page name it.

The name is shared by everybody who runs the agent, but the page is not. A run
republishes an existing artifact only when the person it acts for owns it or
holds `artifacts:edit` on it - from the role or from an `edit` grant, the same
rule as managing it in the console. Anybody else's run is told the name is taken
and publishes under another one, so a colleague asking the same shared agent for
a `weekly-report` cannot replace the page behind your link.

Every publication is a new **version**. Nothing is overwritten, so the version
list on the artifact's page is the page's history. Two things keep that history
bounded:

- Publishing exactly the bytes the current version holds adds no version. The
  result says `unchanged`, and a schedule that found nothing new leaves the
  history alone. It still counts as a publication, so retention's clock restarts.
- Only the newest versions are kept, `ARTIFACT_MAX_VERSIONS` of them (20 by
  default). An older version is removed when a new one lands - except one the
  public link is pinned to. A conversation that links to a removed version says
  the version is no longer kept and offers the latest one.

**Restore this version** puts a kept version back. A member who may edit the page
opens the version and restores it; that adds a new version with the old one's
bytes, so the history keeps what happened and the restore can be undone the same
way. Nothing new is stored. It is recorded in the audit trail. The new version
says where it came from: the version list shows it as `v4 · restored from v2`,
and the API gives its `restored_from` number, which a publish leaves empty.

## Supported formats

| Format | What is stored | What is served |
|---|---|---|
| HTML (`.html`, `.htm`, or `format: html`) | The document as the agent wrote it | The same document, behind a short platform script (see [How the page is isolated](#how-the-page-is-isolated)) |
| Markdown (`.md`, `.markdown`, or `format: markdown`) | The Markdown source | The source rendered into a plain page, tables included. Raw HTML in it is escaped |

One version is one self-contained document of at most `ARTIFACT_MAX_BYTES`
(5 MiB by default). There are no multi-file bundles: inline your own script,
styles and images (as `data:` URIs) into the one file.

!!! warning "The page has no network"

    Scripts run, so a chart drawn by a library works. But the page cannot load
    anything from anywhere and cannot send anything anywhere - a CDN script, a
    web font from a URL and an API call all fail. The exceptions are the
    library set below, which the deployment serves itself, and the
    [live data](#live-data) the console hands a page that declared bindings.
    The tool tells the model this. It is deliberate, and
    [How the page is isolated](#how-the-page-is-isolated) says why.

### The library set

The deployment serves a few files beside every page, so the model stops pasting a
whole chart library into each one. A page loads them by a relative address, and
keeps working if the deployment later moves its content to another origin:

| Address in the page | What it is |
|---|---|
| `lib/chart-4.5.1.umd.min.js` | Chart.js 4.5.1, as `window.Chart` |
| `lib/d3-7.9.0.min.js` | d3 7.9.0, as `window.d3` |
| `lib/lucide-1.46.0.min.js` | Lucide 1.46.0 icons, as `window.lucide` - the console's own icon set |
| `lib/agenticos-3.css` | The page kit: the console's look for pages, light and dark, and the `ao-` components a page is built from |
| `lib/agenticos-3.js` | `window.AO`: Chart.js in the console's style, number formatting in the page's language, icons, tabs, `AO.onData` and `AO.records` |
| `lib/agenticos-2.css`, `lib/agenticos-2.js` | The previous version of the kit, kept for the pages published against it |
| `lib/agenticos-1.css` | The first version of the look, kept for the pages published against it |

Every name carries its version and is cached for a year. An upgrade adds a new
file beside the old one, so a page published against a version keeps getting it,
and a shipped file is never edited. Nothing is fetched from outside the
deployment, so an air-gapped one works the same way. The files are listed in
`backend/app/core/catalog/artifact_lib/`.

Version 3 keeps every class and call of version 2. It also forgives markup a
model writes loosely: a title, subtitle and meta line placed straight in the
header stack rather than spreading across it, a table built without `<thead>`
still gets its header row, and a message written into a table's wrap is padded.
It adds loading and note lines, a caption line, a live dot, lists, a toolbar
with inputs, and the header's icon and actions. Icons a script adds after the
page loaded, as a live page's records do, are drawn too.

The bundled **`artifact-pages`** [skill](skills.md) teaches an agent to use them:
the mandatory skeleton, every class of the kit, three templates (a dashboard, a
report and a live table drawn with `AO.records`), the house style, icons instead
of emoji, and how to change a page with `read_artifact`. A new organization gets
it with the other bundled skills, an existing one through `seed-skills`, and the
Artifacts capability's **Page style** tab in the Builder offers it. Edit the
skill to describe your own brand, and the agent follows it.

### The page contract and the publish warnings

The agent cannot see the page it publishes, so the platform tells it what a page
must look like and what looks wrong in the one it sent.

The Artifacts capability gives every agent that has it a short **page contract**
in its instructions, whether or not the skill is bound: the skeleton (doctype,
viewport, `lang`, the kit's stylesheet and script in order, `main.ao-page` and
the header), a closed list of the kit's most-used classes, Lucide icons rather
than emoji, and `AO.records` for bound data.

When the agent's run offers the `artifact-pages` skill and has not loaded it,
its first whole HTML page is sent back once with a request to load the skill
and rebuild. That happens once per run; each new message is a new run, so it
can happen again on a later turn. An edit is never sent back.

A published HTML page is then checked, and the result carries a `warning` with
one line for each problem found. The page is published either way. The checks:

- no `<!doctype html>` as the first line, or no viewport meta;
- an `ao-` class, in the markup or named in a script, that the kit version the
  page loads does not define and its own `<style>` does not either;
- a table without `<thead>`, or without the `ao-table` class;
- `data-lucide` icons without `lib/lucide-1.46.0.min.js`;
- `AO.onData` or `AO.records` on a page that does not load `lib/agenticos-3.js`;
- a bound page whose script never calls `agenticos.onData` or reads
  `agenticos.data`, so it shows no records.

### Seeing the page: preview

`preview_artifact` draws the current version of a page as somebody opening it
would see it, 1280 pixels wide, and hands the model a picture and a written
report. The report gives each binding's data (records, cut, or unavailable and
why), whether the page asked for its data, uncaught errors with their line,
console errors and warnings, what the page's security policy refused, requests
refused, dialogs, and the publish warnings above. The picture is at most 2400
pixels tall; a longer page says how tall it is. A page still running after 15
seconds is reported as such, without a picture.

The data is read as the person the run is for, exactly as the console would
read it for them. In a group chat only an organization-wide page can be
previewed, the same pages the list shows there, and it is drawn without data. A
surface with nobody signed in previews nothing. Nothing the page asks for reaches the
network: the API answers every request with the page, the
[library set](#the-library-set) or a refusal.

The picture needs a browser the operator runs, named by
[`ARTIFACT_RENDER_CDP_URL`](configuration.md#published-artifacts), and the backend's
`browser` extra. That setting is the operator's alone: it is separate from the
hosts a browsing agent may drive, and no agent can point a browser at it. Without either, the tool still returns the report, without the
picture, and says the deployment has no renderer. Turn **Preview screenshot**
off in the capability's settings for a model that cannot read images; the
report still comes back. `agenticos cmd doctor` says whether the renderer
answers.

## Who can open it

A new artifact is **private** to the person the publishing run acted for: the
person in the chat, or the creator of a trigger. A private page is also visible
to the Owner, Admin, Builder and Operator roles.

Its link - the one the chat card and the agent's reply point at - opens the page
itself (from the chat card, in a new tab), filling the window under one strip with its title, its version and
**Share**. Nobody gets in through that link alone: it opens only for a signed-in
member the rules below already let in. It names the organization the artifact is
in (`?org=`), so a member of several lands in the right one.

Under **Share**, anybody who may manage it can share it three ways:

| Reach | How | Who |
|---|---|---|
| Specific people | A grant, at `read` or `edit` | Those members, in this organization |
| The organization | Visibility set to the whole organization | Every member whose role reaches shared artifacts |
| Anyone with the link | **Create a public link** | Anybody holding the address, without an account |

Sharing and visibility use the same panel and the same rules as agents and
skills; see [Permissions](permissions.md). Managing an artifact - sharing it,
its public link and its settings, restoring a version, deleting it - needs
`artifacts:edit` on that artifact, from the role or from an `edit` grant.
Opening it needs `artifacts:view`.

The agent cannot widen who reads a page. It publishes; a person decides who sees
it. This is why the capability does not ask for approval by default: a first
publication is private, and what a bound page shows is decided at view time by
each viewer's own access. An author who wants a person to approve each republish
of an already shared page, or of a bound page, sets `tool_approval` on
`publish_artifact` in the spec. A bound page can be republished only by a run
acting for a member (see [Live data](#live-data)).

### Who sees a live page's records

Sharing a [live page](#live-data) lets a person open it, but each binding's records
are read with their own access. To see them they also need read access to the
binding's table, and a view that is shared or their own. A page bound to a private
view therefore shows its records only to the view's owner; the publish result tells
the agent so, for it to pass on.

### The public link

A public link is `/a/<key>` on the console's own address, with a 192-bit random
key - the same rule the hosted chat page's key follows. It says nothing about who
published it or which organization it belongs to.

**Replace the link** issues a new key, and the old one stops opening anything at
once. **Turn off** removes it. Both are recorded in the audit trail. A page
somebody already has open keeps showing until its signed content address
expires, at most `ARTIFACT_VIEW_TTL_SECONDS` (five minutes by default).

A revoked member is in the same position: they lose the artifact on their next
request, and a page they already had open stays for that same window at most.

Under the link, **Share** holds its settings. They stay when the link is replaced,
and a link turned off and on again keeps them:

| Setting | What it does |
|---|---|
| **Stops opening after** | A date after which the link opens nothing, as if it were off |
| **Shows** | The newest version, or one kept version pinned so a new publication does not change what people with the link already saw. A pinned version is never pruned |
| **Password** | Asked before the page opens. The link says nothing - not the title, not when it was published - until it is right. Stored hashed, never shown again; every attempt counts against the link's rate limit |
| **Sites that may embed it** | See below |

The card also says how many times the link was opened and when last. It counts
openings, not people: nothing about a visitor is stored. Every change to the
settings is audited, naming which settings changed and never a password.

### Embedding it on another site

A public page can be placed on an intranet page, in a wiki or on a client's site
with an `<iframe>`. List the sites under **Sites that may embed it** - scheme and
host only, `https://intranet.example.com`, or `https://*.example.com` for a
site's subdomains - and copy the **Embed code** Share then shows.

The code frames `/api/v1/artifact-embed/<key>` on the content origin: a small
document of this deployment's own, which frames the page in the same sandbox as
everywhere else. Its policy lets only the listed sites frame it, and the page's
own policy lets only that document and the console frame the page. With no site
listed, nobody can. A page behind a password cannot be embedded - the embed says
to open it on its own page instead - and nobody signs in inside a frame on
somebody else's site.

## How the page is isolated

An artifact is HTML with script in it, written by a model that may have read
something hostile. It is served so that nothing it does can reach the console or
the person looking at it:

- The bytes come from a separate route, `/api/v1/artifact-content/<token>`,
  that reads no cookie and no session. The token is signed, names one version,
  and expires in minutes. It is minted only after a grant or a public link
  admitted the caller.
- Every content response carries `Content-Security-Policy: sandbox
  allow-scripts allow-modals`, with no `allow-same-origin`. The page runs in an
  opaque origin, so it cannot read the console's cookies, storage or page, and a
  request it made would carry nothing of the viewer. That holds even when
  somebody opens the content address on its own.
- The same policy sets `default-src 'none'` and `connect-src 'none'`. The only
  remote source it names is the library set's own path on the content origin,
  for scripts, styles and fonts. `frame-ancestors` names only the console - and,
  for a page with a public link and embedding sites, the embed document and
  those sites. The frame in the console carries the same `sandbox` list as a
  second lock.
- There is no `allow-popups`. `connect-src` does not govern navigation, so a link
  that opened a new window would be a way to send what the page shows to an
  address the page chose. Instead, every served page gets a short platform script
  first: a click on a link to another site becomes a message to the frame's
  parent. The console and the public page show the full address and open it in a
  new tab only when the person agrees; the embed document does the same in a bar
  under the page. The page could send that message itself, so it is a request and
  never a permission - the person reading the address is what stands between a
  prompt-injected page and the address it would send its numbers to.
- Live data arrives by `postMessage` from the console, which fetches it as the
  viewer. The content route never carries records. The page's request carries a
  nonce that lets the console match each reply to the right page load; that is
  **correlation, not access control**. Access is the viewer's own session on the
  data route, so a page only ever receives what the viewer may read.
- One signed address loads its page a few times a minute at most, counted per
  address before anything is read. The console and the public page mint a
  fresh address each time they draw the frame, and minting one through a public
  link is itself limited per link.

The **Artifacts** list draws each card's current page as a live thumbnail
through the same kind of frame, with script and nothing else: no dialogs, no
popups, no forms. Script, so a dashboard whose charts a library draws is not an
empty canvas on its card. The thumbnail is inert - no pointer events, out of the
tab order, hidden from assistive technology - and exists only while its card is
near the viewport, so a long list runs the few a reader can see and stops a page
that scrolled away.

On top of that, a deployment can serve content from a **separate registrable
domain** by setting `ARTIFACT_ORIGIN` - for example
`https://agenticos-content.example.net`, routed to the same API. The page is
then on another site entirely. The opaque origin already isolates it, so this is
hardening a security review may ask for, not a requirement. Set the variable for
the backend and for the frontend, which adds that origin's content route to its
`frame-src`. See
[Configuration](configuration.md#published-artifacts).

## Archiving a page

Archiving takes a page away from everyone without losing it. Someone who may
edit the page chooses **Archive** from the **More actions** menu above it, and
a dialog says what that does before anything changes. The page, its versions,
its grants and its name are kept. Nothing serves it until it is restored, from
the same page. Archiving is audited as `artifact.archived`, and restoring as
`artifact.unarchived`.

While a page is archived, every path that would show it answers as though it
were not there:

- **The console.** Its view and its live data are refused, and so is a signed
  address minted before the archive. A reader who opens its link is told it is
  not available. Someone who may edit it sees when it was archived, with
  **Restore** and **Delete**.
- **Lists.** The Artifacts list and the dashboard widget leave it out. Choose
  **Archived included** on the list to see it, marked **Archived**.
- **The public link and the embed.** Both open nothing.
- **The agent.** `publish_artifact` refuses the name with a message naming the
  archive, so a run cannot start a second page under it. `read_artifact`,
  `preview_artifact` and `list_artifacts` treat the page as absent. A run that
  may not edit the page hears only that the name is not its to change.

Archiving turns the public link off, audited as `artifact.public_link_disabled`,
and restoring does not turn it back on. An address sent out before the archive
stays dead until somebody makes a new one from **Share**. The link's expiry,
pinned version, password and embedding sites are kept for that.

Over the API, `POST /api/v1/artifacts/{id}/archive` archives a page, and
archiving it again changes nothing. `POST /api/v1/artifacts/{id}/unarchive`
restores it, and answers `400` for a page that is not archived. Both ask for the
right to edit that page, a grant included. `GET /api/v1/artifacts` lists
archived pages only with `include_archived=true`, and `archived_at` on each page
says when it was archived.

## Retention and deletion

Artifacts are a [retention class](governance.md#the-classes) of their own,
measured from the **last publication** - a report republished every week is
alive however old its first version is. Like every class, it keeps artifacts for
ever until an organization or the deployment sets a period.

Deleting an artifact - by hand or by retention - removes every version, its
stored bytes, its grants and its public link. An archived page ages and is
deleted like any other. Deleting the agent does not delete
its artifacts: they stay readable and simply have no publisher. Deleting a named
environment does the same to the pages published from it, so they never land on
the default environment's page of the same name. Deleting the organization
removes them. A deleted person's artifacts stay and lose their owner, the way
their agents and skills do.

The bytes live in the deployment's [file storage](configuration.md#uploaded-files-at-rest),
under `artifacts/<organization>/<artifact>/`.

## Limitations

- **One self-contained document per version.** No bundles, and no network from
  inside the page beyond the served library set and the [live data](#live-data)
  the console hands it.
- **Live data is bounded.** Five bindings, 1,000 records each and about 5 s a
  load; see the [limits](#limits). Data that is not bound is the page as
  published, and changes when the agent publishes again.
- **Nothing on the page acts.** A form or a button has nowhere to send what it
  collects.
- **An open page outlives a revocation by one signed-address lifetime**, five
  minutes by default.
- **A link inside a page asks first.** It opens in a new tab after a person
  agrees; the page itself cannot open a window or navigate the console.
- **An embed needs the public link and no password.** Members cannot sign in
  inside another site's frame.
- **Removed versions are gone.** A conversation that links to a version older
  than the kept window can only offer the latest one.
- **Without a renderer the agent does not see its page.** The publish warnings
  read the markup and cannot tell how it looks. With one, the picture is a
  headless Chromium's: fonts and sizes can differ slightly from a reader's
  browser.

## Recap

- One capability, four tools: `publish_artifact`, from a workspace file, inline
  or as edits; `read_artifact` to read a page back; `list_artifacts` to find
  one; and `preview_artifact` to see it drawn, with its errors.
- The agent, the environment and the name are the identity; publishing again
  keeps the link and adds a version, and any kept version can be restored.
- Private by default; shared with grants, the organization or a public link, by
  a person. The public link can expire, pin a version, ask for a password and be
  embedded on listed sites.
- A page can bind to saved table views and show live data, read at view time with
  the viewer's own access and never stored in the page.
- A short page contract in every Artifacts agent's instructions, and warnings in
  the publish result for what looks wrong in the markup.
- Served from a cookieless route in an opaque origin with no network but the
  deployment's own library set, links that ask before they open, and optionally
  a domain of its own.
- Archiving keeps a page and serves nothing of it, the public link off, until
  someone who may edit it restores it.
- A retention class of its own, measured from the last publication.
