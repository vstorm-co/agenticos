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

Turn on the **Artifacts** capability for the agent. It adds two tools:
`publish_artifact`, which the model calls when the result is something a person
should open rather than read once in the chat, and `read_artifact`, which reads a
published page back.

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
way. Nothing new is stored. It is recorded in the audit trail.

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
    web font from a URL and an API call all fail. The one exception is the
    library set below, which the deployment serves itself. The tool tells the
    model this. It is deliberate, and [How the page is isolated](#how-the-page-is-isolated)
    says why.

### The library set

The deployment serves a few files beside every page, so the model stops pasting a
whole chart library into each one. A page loads them by a relative address, and
keeps working if the deployment later moves its content to another origin:

| Address in the page | What it is |
|---|---|
| `lib/chart-4.5.1.umd.min.js` | Chart.js 4.5.1, as `window.Chart` |
| `lib/d3-7.9.0.min.js` | d3 7.9.0, as `window.d3` |
| `lib/lucide-1.46.0.min.js` | Lucide 1.46.0 icons, as `window.lucide` - the console's own icon set |
| `lib/agenticos-2.css` | The console's look for pages, light and dark, and the `ao-` components a page is built from |
| `lib/agenticos-2.js` | `window.AO`: Chart.js in the console's style, number formatting in the page's language, icons, tabs |
| `lib/agenticos-1.css` | The first version of the look, kept for the pages published against it |

Every name carries its version and is cached for a year. An upgrade adds a new
file beside the old one, so a page published against a version keeps getting it.
Nothing is fetched from outside the deployment, so an air-gapped one works the
same way. The files are listed in `backend/app/core/catalog/artifact_lib/`.

The bundled **`artifact-pages`** [skill](skills.md) teaches an agent to use them: two
templates (a dashboard and a report), the house style and its components, icons
instead of emoji, and how to change a page
with `read_artifact`. A new organization gets it with the other bundled skills, an
existing one through `seed-skills`, and the Artifacts capability's **Page style**
tab in the Builder offers it. Edit the skill to describe your own brand, and the
agent follows it.

## Who can open it

A new artifact is **private** to the person the publishing run acted for: the
person in the chat, or the creator of a trigger.

Its link - the one the chat card and the agent's reply point at - opens the page
itself, filling the window under one strip with its title, its version and
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
publication is private. An author who wants a person to approve each republish
of an already shared page sets `tool_approval` on `publish_artifact` in the spec.

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
the backend and for the frontend, which adds that origin to its `frame-src`. See
[Configuration](configuration.md#published-artifacts).

## Retention and deletion

Artifacts are a [retention class](governance.md#the-classes) of their own,
measured from the **last publication** - a report republished every week is
alive however old its first version is. Like every class, it keeps artifacts for
ever until an organization or the deployment sets a period.

Deleting an artifact - by hand or by retention - removes every version, its
stored bytes, its grants and its public link. Deleting the agent does not delete
its artifacts: they stay readable and simply have no publisher. Deleting a named
environment does the same to the pages published from it, so they never land on
the default environment's page of the same name. Deleting the organization
removes them. A deleted person's artifacts stay and lose their owner, the way
their agents and skills do.

The bytes live in the deployment's [file storage](configuration.md#uploaded-files-at-rest),
under `artifacts/<organization>/<artifact>/`.

## Limitations

- **One self-contained document per version.** No bundles, and no network from
  inside the page beyond the served library set.
- **No live data.** A dashboard shows the data it was published with. It
  refreshes when the agent publishes again - a schedule is the usual way.
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

## Recap

- One capability, two tools: `publish_artifact`, from a workspace file, inline
  or as edits, and `read_artifact` to read a page back.
- The agent, the environment and the name are the identity; publishing again
  keeps the link and adds a version, and any kept version can be restored.
- Private by default; shared with grants, the organization or a public link, by
  a person. The public link can expire, pin a version, ask for a password and be
  embedded on listed sites.
- Served from a cookieless route in an opaque origin with no network but the
  deployment's own library set, links that ask before they open, and optionally
  a domain of its own.
- A retention class of its own, measured from the last publication.
