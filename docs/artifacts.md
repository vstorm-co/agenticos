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

Turn on the **Artifacts** capability for the agent. It adds five tools:
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
`publish_artifact`: each binding is a name and a **page query** - a table, the
fields the page reads from it, and optionally filters, a sort and a limit. The
page calls `agenticos.onData(render)`, and `render(data)` runs with the first
data and again on every refresh. `agenticos.data` is a Promise of the first data.

```js
agenticos.onData((data) => {
  // data.tickets = { status, records, fields, count, truncated, limit }
});
```

Each binding arrives as `status` (`ok` or `unavailable`), `records`
(`{id, <field>: value}`), `fields` (label, type, options and state for each),
`count`, `truncated` and `limit`. A page that gets no reply within 10 seconds
sees every binding `unavailable`; a listener added after that asks once more.

**Everyone who opens a live page reads the same records**, whatever their own
access to the tables. The query is read with the access of the page's
[owner](#who-owns-a-page), and only once the owner has agreed to share it
([consent](#consent-the-owner-decides-who-reads-the-data)). So a page is for
data everyone who can open it may see. The records are read when somebody views
the page, and are never stored in it.

### What a binding freezes

A page query is not a link to a saved view. The agent names a `table`, or a
[saved view](virtual-tables.md#saved-views) by id or exact name, and the platform
**copies** the view's filters and sort into the page when it publishes. Editing
or deleting the view later changes nothing on the page.

| In the binding | Meaning |
|---|---|
| `table` or `view` | The table to read, or a view whose filters and sort are copied. Not both |
| `fields` | Each name the page reads, mapped to a column by id or label |
| `filters` | `{column, op, value}`, all of which must hold; added to the view's filters |
| `sort` | `{by, direction}`; replaces the view's sort |
| `limit` | At most 1,000, which is also the default; replaces the view's |

A view's `visible_columns` and `group_by` are ignored: the binding's `fields`
decide the columns. A filter may name a column the page does not read, and the
owner is told which. There is no free-text search on a page query, so a view that
has a search **cannot be bound**; the publish is refused and names it. A view
whose filter names a column that is gone is refused the same way.

Formulas, lookups, rollups and link labels are allowed. They read more than the
column the page names, so the query records everything it reaches: a formula's
input columns, a lookup's or rollup's link and target, each linked table, and
the column each linked table labels its records by. The agent's spec must grant
read on the table, and the person behind the run must read every table the query
reaches, because nobody can bind what they cannot read.

The publish result describes each query in words - its table, filters, order,
limit, and each field with what it reads (`Status (single_select)`, `Pay band:
formula over Salary, Level`). It is the text the owner agrees to, so the agent
checks it is what it meant. A binding carried forward unchanged says `kept`.

A binding name is lower-case letters, digits and `_`. A field name may be written
as its column is labelled: words of letters in any case, digits and `_`, with single
spaces between them, such as `Status` or `Created At`. Both are at most 64
characters, and `__proto__`, `constructor` and `prototype` are reserved for both
(`id` too, for a field). A page has at most 5 bindings, and a binding at most 50
fields.

Version 3 of the [page kit](#the-library-set) draws a binding for the agent:
`AO.records("#tickets", data.tickets)` inside `agenticos.onData` renders the
records as a table with a head from the fields' labels, numbers and dates
right-aligned, choices as badges and every value written as text. Before the
data it shows a loading line, and an `unavailable` or empty binding and a cut list
each get their own message. `AO.onData` in version 3 is
the same call as `agenticos.onData`. A bound page whose script never asks for
its data still publishes, with a [warning](#the-page-contract-and-the-publish-warnings).

### Who sees what

Which version a viewer is served, and whether its data is read for them, depends
on who they are.

| Viewer | Served | Its data |
|---|---|---|
| The page's owner | The latest version | Always |
| Owner, Admin, Builder and Operator, even view-only | The latest version | Always, for the roles that read every table (`tables:view` at ALL) |
| Anyone else who can edit the page | The latest version, so an editor's agent keeps editing what is current | While the owner's consent to that version holds |
| Everyone else who can open it (the **audience**) | The newest version that was ever consented to, or that reads no data | While the owner's consent to it holds |

The audience is never served a version nobody agreed to share. When the data's
consent no longer holds - an editor withdrew it, or the owner changed - the
audience still gets that **whole page**, and every binding arrives `unavailable`
with the reason `awaiting_consent`; the page says "This page's data appears once
its owner confirms sharing it." When no version at all is consented or free of
data, the audience sees "This page isn't available yet" and nothing else.

A binding is also `unavailable` when what it reads changed since the page was
published. The reason is told only to someone who can edit the page; a reader
sees how many sources are unavailable.

| Reason | What happened |
|---|---|
| `creator_gone` | The page's owner is no longer an active member |
| `creator_lost_access` | The owner can no longer read a table the query reaches |
| `source_changed` | A column's meaning changed (its type, a formula, a link or lookup target, an aggregate, an archived or restored option), or a column or table was archived, or a linked table now labels its records by another column. The column's current label is named |
| `awaiting_consent` | The owner has not confirmed sharing this version's data, or it was withdrawn |

One binding going `unavailable` leaves the others working. The page is never
blocked from a table change: nothing stops a column from being changed, and the
binding stops serving until the agent publishes the page again, which resolves the
query against the table as it is now. Renaming a column does not change a binding;
the page keeps reading it by the name the agent gave. Adding an option to a select,
or relabelling one, does not either.

### Consent: the owner decides who reads the data

A page's data is read with its owner's access, so the owner decides who else
reads it, per version. That decision is **consent**: the owner reviews the page
queries in words - each query's table, filters, order, limit and fields, every
linked table it reaches, and who will read it - and confirms.

The review names who reads the page, now and later: the roles that open every
page (Owner, Admin, Builder and Operator), the page's visibility, the people it is
shared with and the groups, including whoever joins them. The owner can only
confirm what they read themselves.

A version's data is in one of these states:

| State | Meaning |
|---|---|
| `not_needed` | The version has no bindings |
| `pending` | Nobody has confirmed it. The audience keeps the version it had |
| `consented` | The owner confirmed it, or it was consented to automatically |
| `declined` | A request to confirm it was declined |
| `withdrawn` | A consent that no longer holds: an editor took it back, or its owner is no longer the page's owner |

A new version is consented **automatically** when its page queries - and
everything they reach - are the ones the owner already consented to. Otherwise it
is `pending`: that includes the first bound version, unless the owner has
[auto-consent](#auto-consent) on.

The owner, and the owner alone as themselves, confirms in the viewer. While the
latest version waits, the strip under the page's title says so, with **Confirm data**:
it opens what the version shares and with whom, and the confirmation carries a
fingerprint of exactly what was shown. If the page was republished in between, or its
queries moved, the confirmation is refused and the owner looks again. Confirming
also checks that the owner can still read every table the query reaches.

An Owner or Admin may confirm for the owner. It is audited as consented by them
for the owner, and the owner's access still backs the data. Anyone with an `edit`
grant cannot: a grant to edit the page is no authority over whose data it reads.

**Withdrawing** takes the consent back. Anyone who can edit the page, as
themselves, uses **Stop sharing data** in the viewer's menu. Every consent given
so far is void, not only the latest, and auto-consent turns off. Every
`edit_data` grant on the page drops to `edit` as well, so a data editor's next
republish waits for the owner instead of undoing the withdrawal. The audience
keeps the page and loses its data until the owner confirms again. Withdrawing
only narrows who reads, which is why every editor may do it.

When the owner leaves the organization, their consents lapse with their
membership. An owner who is removed and invited again starts fresh. An owner who
is deactivated and reactivated revives their consents: reactivating is an
account-wide act, in every organization the account belongs to.

#### Republishing

When an editor other than the owner publishes a version that reads different
data, the version is `pending` and the platform files a **version request**
for the owner - see [Share requests](#share-requests). Until the owner decides,
the audience still sees the earlier version. The publish result says "The audience
still sees v2 until Alex confirms this version's data in the console." (with the
owner's name, or "the page's owner").

A run with no person behind it can republish a bound page only unchanged - the same
bytes and the same queries, which needs no person and no consent. It cannot swap
the code that receives the owner's records. A publish by an editor is refused when
the page's owner cannot read a table the query reaches.

#### Auto-consent

The owner can switch on **Don't ask for consent on republish** for a page. It is
off by default and only the owner, as themselves, turns it on, never an agent. It
asks first: "Any change your runs make to this page's data, new columns and tables
included, reaches everyone who can open it without asking you - API runs too."
The audit entry records the confirmed text.

It covers only the owner's own republishes. An editor's republish still waits.
Auto-consents are recorded as automatic, and when one reaches more than the version
served before it, the owner's strip lists it: "v4 was consented automatically and
reads more: +Deals, +Salary". The owner or an Owner or Admin turns it off, and
withdrawing or handing the page to someone else turns it off too.

#### Data editors

The sharing dialog has a grant level above `edit`: **Can edit, data included**
(`edit_data`), for pages only. It is a standing consent to that person's
republishes, a change of query included. Only the owner, or an Owner or Admin, as
themselves, grants it, after a popup: "Alex can change what data this page shows
to everyone who can open it, including new tables and columns, without asking
you; that includes their API runs." For a group the popup says "Everyone in Sales,
now and later". The grant is audited with the confirmed text.

A republish by someone with `edit_data` is consented automatically, recorded as made
through their grant. They still have to read every table the query reaches, and the
owner still has to. The role scope of Owner or Admin never implies it. Anyone who can
edit the page lowers or removes it, and an ownership switch drops every
`edit_data` grant to `edit`.

### Who owns a page

A page's owner is the person the first publishing run acted for. It never changes
by itself and it is the page's single data owner: the person whose access reads
the data and whose consent shares it. If the owner is deleted, the page has none.
Nobody can claim a page.

The owner hands it to another active member of the organization with **Change
owner** in the viewer's menu, and an Owner or Admin may reassign any page, one
whose owner is gone included. Each does it as themselves, not by impersonating
someone. A grant to edit the page does not allow it. There is no agent tool for it.

The switch is immediate, with no acceptance step. The page's data stops reaching
the audience until the new owner confirms it, every consent so far is void for good
(so handing the page back never revives an old one), auto-consent turns off, any
pending request is voided, every `edit_data` grant drops to `edit`, and the old and
the new owner are notified, except whoever made the switch. It is audited as
`artifact.owner_changed`.

Giving an owner-less page visibility `private` counts as taking it over, and is open
only to an Owner or Admin. It goes through the same rules.

### Share requests

Widening who can open a page that reads data - a wider visibility, or a new
grant or a higher level - is the owner's decision, or an Owner's or Admin's for the
owner. Narrowing is open to every editor. A page that reads no data keeps the
ordinary sharing rules.

Anyone else who can edit the page and tries to widen it does not get a refusal.
The platform files a request. There are three kinds:

| Kind | Made by | Asks |
|---|---|---|
| `audience` | An editor, in the Share dialog or through their agent's `share_artifact` | To widen who opens the page |
| `access` | A member of the page's organization who opens its link without access | To open the page, with an optional note |
| `version` | The publish of another editor whose version reads different data | To confirm that version |

A member can have one pending `audience` and one pending `access` request per page,
and a page has one pending `version` request; a newer one replaces the older.
`audience` and `access` requests are limited to ten an hour per person per
organization by default
([`RATE_LIMIT_ARTIFACT_SHARE_REQUESTS_PER_HOUR`](configuration.md)); `version`
requests are not counted. The page's owner decides. When it has no owner left, the
Owners and Admins can decline; to approve, they first hand the page to a member
(**Change owner**), who confirms the data. A request goes void without a decision when the page's queries change, the owner changes or the page is
archived.

The owner is notified in the console and by email, as set in **Settings →
Notifications** ("Page sharing requests"). The notification names the page and the
requester, never its data.

They are answered in a **Requests** section of the Share dialog, and a **Requests** button in
the viewer's strip shows how many wait. Approving an `audience` or `access` request
applies the visibility and grants it asked for, each only where it still widens.
**It never consents to data**: when the version the audience is served has no consent
that holds, approving is refused with "Confirm the page's data before sharing it", and
the owner confirms the data first, then approves. Declining shares nothing.

The requester is not told when it is decided: the page opening, or not, is the
answer. A page that reads no data takes a plain `access` request, which any
editor of it may approve.

#### Requesting access

A member of the organization who opens the link of a page they cannot open sees "You
don't have access to this page", a note field and **Request access**. Nothing else
is revealed: no title, owner or agent. A signed-out visitor or somebody from another
organization gets the ordinary not-found.

#### Reviewing a changed version

A `version` request opens the page for the owner on the pending version, with its real
data. The strip says who changed what the version reads, with **Review data
change**. The panel compares the version's page queries with the one the audience
sees now, binding by binding and in words: fields, filters, order, limit and linked
tables added, removed or changed, each marked **Reads more**, **Reads less** or no
change, new bindings with their full disclosure, and unchanged ones collapsed.

A toggle, **Audience sees now**, shows the page as the audience has it. The panel names
who published the version and when, and links to the conversation when the owner may
open it. **Approve** confirms the version. **Decline** keeps the audience on the earlier
version and marks the version `declined` in its history; a later republish asks again.
In the Requests list a version request offers **Review data change**, not Approve:
it is confirmed from the review.

### Sharing a page from an agent

`share_artifact(name, visibility?, people?)` lets an agent ask for a page to be
shared: `visibility` is `team` or `org`, `people` are members by full name or
email and groups by name, each asked at view level. It **never shares anything**. It
files an `audience` request for the person the run is for - the owner's own run
included - and answers "Waiting for Alex to approve in the page's Share dialog".
The approval is a person in the console, signed in as themselves, never a tool call.

A name that matches nobody, or several people, is reported back, never guessed. It
asks for nothing public: the public link is only set up in the console. A run with
no person behind it, such as a widget visitor, cannot ask.

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

A line under the strip appears only when something needs attention: a version
waiting for confirmation, a request to review, or sources that cannot be read. A
refused page says "This page's live data is not available to you." A reader whose
sources cannot be read sees how many ("2 of 3 sources unavailable to you"). An editor
also sees why for each source, with an **Open the table** link to the bound table.

When an agent publishes a new version while somebody has the current one open,
the next read (a refresh, manual or automatic) moves the viewer to the version
they are now served: the page is loaded again, with its own data. A viewer who
picked a version from the version menu stays on it.

On an older version, live data is not read. The viewer says "Live data only on the
current version." with **Open current**, and, for an editor, **Restore** for that
version. A restore resolves the version's page queries against the tables as they
are now, so it is a new query when a table moved on, and it waits for consent like
any other republish.

### How the data reaches the page

When the console opens a page it asks for a signed address that carries who the viewer
is. The content route reads each binding **once, on load**, and writes the result
into the page's platform script, so the first `onData` call already has its data
and no round trip follows. Nothing is injected for a thumbnail, a card or a version
from the history.

Refresh and auto-refresh keep using the data route and a `postMessage` from the console,
which now answers the same page-query rows for everyone served that version. The route
is never cached, the address is short-lived, and a record's content is kept out of logs.
A binding that cannot be read in time or fails in the database is injected `unavailable`
and the page still renders.

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
| Share requests | 10 an hour per person per organization (audience and access) |

A cut binding says `truncated: true`, with `limit` set to `records` or `bytes`
and `count` as the number of records served. `bytes` also covers a read whose
measured cost ran out before the shaped data filled the page's share.

The deadline is checked before each query, without cancelling any: each query runs
at most the smaller of 2 s and the time left of the 5 s, and no query starts once
the 5 s are spent, so a page answers in about 5 s and the wall clock can reach about
7 s. Injected loads count against the 30 a minute, like refreshes. Past a rate limit
the data route answers 429, the console retries a busy answer twice, and a page served with
its data gets `busy` bindings. When Redis is down, the rate limit's floor and the
in-flight limit count per API worker, and the per-process cap still bounds each worker.

### Who may publish a bound page

A page binds to a table only if the publishing agent's spec grants read on it, and
the person behind the run reads every table the query reaches, checked when the
page is published or a version restored. Revoking either later does not stop
pages already published; the owner's access is checked again on every load.

A bound page can be **changed** only by a run
acting for a member (an unchanged republish, with the same bytes and queries, needs
no person): the signed-in member (web chat, HTTP API), a linked channel
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
to the Owner, Admin, Builder and Operator roles: their `artifacts:view` is at scope
`ALL`, so they open every page in the organization whatever its visibility and
grants (see [scopes](permissions.md#scope)). A Member or Viewer opens only what is
shared with them. Those four roles are always part of a page's audience, and every
disclosure names them.

Its link - the one the chat card and the agent's reply point at - opens the page
itself (from the chat card, in a new tab), filling the window under one strip with its title, its version and
**Share**. Nobody gets in through that link alone: it opens only for a signed-in
member the rules below already let in. It names the organization the artifact is
in (`?org=`), so a member of several lands in the right one.

Under **Share**, anybody who may manage it can share it three ways:

| Reach | How | Who |
|---|---|---|
| Specific people | A grant, at `read`, `edit`, or for a page, `edit_data` ("Can edit, data included") | Those members, in this organization |
| The organization | Visibility set to the whole organization | Every member whose role reaches shared artifacts |
| Anyone with the link | **Create a public link** | Anybody holding the address, without an account |

Sharing and visibility use the same panel and the same rules as agents and
skills; see [Permissions](permissions.md). Managing an artifact - sharing it,
its public link and its settings, restoring a version, deleting it - needs
`artifacts:edit` on that artifact, from the role or from an `edit` grant.
Opening it needs `artifacts:view`.

The agent cannot widen who reads a page. It publishes, and `share_artifact` only
files a request; a person decides who sees it. This is why the capability does not
ask for approval by default: a first publication is private, and what a bound page
shows is gated by its owner's [consent](#consent-the-owner-decides-who-reads-the-data).
An author who wants a person to approve each republish
of an already shared page, or of a bound page, sets `tool_approval` on
`publish_artifact` in the spec. A bound page can be republished only by a run
acting for a member (see [Live data](#live-data)).

### Sharing a live page

Opening a [live page](#live-data) shows its data to anyone served it, read with the
owner's access rather than their own, so widening who can open it is the owner's
decision. The owner, or an Owner or Admin for them, widens it directly in the Share
dialog once the data is confirmed; any other editor's attempt becomes a
[request](#share-requests). Narrowing is open to every editor.

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
- Live data reaches a member's page in two ways, both decided per viewer on the
  server. On load, the content route writes each binding's records into the page's
  platform script for the member the signed address names; a refresh arrives by
  `postMessage` from the console, which fetches it from the data route with the
  viewer's own session. The page's request carries a nonce that lets the console
  match each reply to the right page load; that is **correlation, not access
  control**. A public link or an embed never gets data. See
  [the security page](security.md#a-pages-data-and-its-address).
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
- **Everyone reads the owner's view of the data.** A page query is read with the
  owner's access, so a page is for data everyone who can open it may see. A page
  query has no free-text search, no per-viewer filter such as "me" or "today", and
  no row- or column-level limit beyond the query itself.
- **A public link or an embed gets no data.** A bound page shows "unavailable" there;
  serving data through a public link is a separate piece of work (#1975).
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

- One capability, five tools: `publish_artifact`, from a workspace file, inline
  or as edits; `read_artifact` to read a page back; `list_artifacts` to find
  one; `preview_artifact` to see it drawn, with its errors; and `share_artifact`
  to ask for a page to be shared.
- The agent, the environment and the name are the identity; publishing again
  keeps the link and adds a version, and any kept version can be restored.
- Private by default; shared with grants, the organization or a public link, by
  a person. The public link can expire, pin a version, ask for a password and be
  embedded on listed sites.
- A page can bind to a page query - a table, filters, a sort, a limit and fields -
  and show live data, read at view time with its owner's access, only once the owner
  has confirmed sharing it, and never stored in the page. Anyone with edit can
  withdraw that consent; widening who can open a bound page is the owner's, or a request.
- The owner can hand a page to another member, who must confirm its data again.
- A short page contract in every Artifacts agent's instructions, and warnings in
  the publish result for what looks wrong in the markup.
- Served from a cookieless route in an opaque origin with no network but the
  deployment's own library set, links that ask before they open, and optionally
  a domain of its own.
- Archiving keeps a page and serves nothing of it, the public link off, until
  someone who may edit it restores it.
- A retention class of its own, measured from the last publication.
