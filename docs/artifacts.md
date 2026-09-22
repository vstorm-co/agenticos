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

Turn on the **Artifacts** capability for the agent. It adds one tool,
`publish_artifact`, and the model calls it when the result is something a person
should open rather than read once in the chat.

The page comes from one of two places:

- **A file in the agent's workspace**, ending in `.html` or `.md`. This is the
  usual case for an agent with the [Files & shell](reference/capabilities.md#files-shell)
  capability: it writes `report.html`, runs whatever builds it, then publishes
  the file. The bytes are read through the run's own workspace backend, so it
  works on every sandbox backend.
- **The page passed inline**, for an agent without a workspace or a short page.

The chat shows a card for the published page. The card links to the version
*this* run published, so reading the conversation later still shows what was
published in it, not what the page shows today.

## One name, one link

The identity of an artifact is its **name within the agent** - `weekly-report`,
`churn-dashboard`. Publishing under the same name updates the same artifact,
from any surface: the chat, the API, a [trigger](triggers.md) or a workflow. A
new name makes a new page. The name is lower-case letters, digits and hyphens,
up to 64 characters.

Every publication is a new **version**. Nothing is overwritten, so the version
list on the artifact's page is the page's history. Two things keep that history
bounded:

- Publishing exactly the bytes the current version holds adds no version. The
  result says `unchanged`, and a schedule that found nothing new leaves the
  history alone.
- Only the newest versions are kept, `ARTIFACT_MAX_VERSIONS` of them (20 by
  default). An older version is removed when a new one lands. A conversation
  that links to a removed version says the version is no longer kept and offers
  the latest one.

## Supported formats

| Format | What is stored | What is served |
|---|---|---|
| HTML (`.html`, `.htm`, or `format: html`) | The document as the agent wrote it | The same document |
| Markdown (`.md`, `.markdown`, or `format: markdown`) | The Markdown source | The source rendered into a plain page, tables included. Raw HTML in it is escaped |

One version is one self-contained document of at most `ARTIFACT_MAX_BYTES`
(5 MiB by default). There are no multi-file bundles: inline the stylesheet, the
script and the images (as `data:` URIs) into the one file.

!!! warning "The page has no network"

    Scripts run, so a chart drawn by an inlined library works. But the page
    cannot load anything from anywhere and cannot send anything anywhere - a CDN
    script, a web font from a URL and an API call all fail. The tool tells the
    model this. It is deliberate, and the next section says why.

## Who can open it

A new artifact is **private** to the person the publishing run acted for: the
person in the chat, or the creator of a trigger. From its page in **Artifacts**,
anybody who may manage it can share it three ways:

| Reach | How | Who |
|---|---|---|
| Specific people | A grant, at `read` or `edit` | Those members, in this organization |
| The organization | Visibility set to the whole organization | Every member whose role reaches shared artifacts |
| Anyone with the link | **Create a public link** | Anybody holding the address, without an account |

Sharing and visibility use the same panel and the same rules as agents and
skills; see [Permissions](permissions.md). Managing an artifact - sharing it,
its public link, deleting it - needs `artifacts:edit` on that artifact, from the
role or from an `edit` grant. Opening it needs `artifacts:view`.

The agent cannot widen who reads a page. It publishes; a person decides who sees
it. This is why the capability does not ask for approval by default: a first
publication is private. An author who wants a person to approve each republish
of an already shared page sets `tool_approval` on `publish_artifact` in the spec.

### The public link

A public link is `/a/<key>` on the console's own address, with a 192-bit random
key - the same rule the hosted chat page's key follows. It always shows the
latest version and says nothing about who published it or which organization it
belongs to.

**Replace the link** issues a new key, and the old one stops opening anything at
once. **Turn off** removes it. Both are recorded in the audit trail. A page
somebody already has open keeps showing until its signed content address
expires, at most `ARTIFACT_VIEW_TTL_SECONDS` (five minutes by default).

A revoked member is in the same position: they lose the artifact on their next
request, and a page they already had open stays for that same window at most.

## How the page is isolated

An artifact is HTML with script in it, written by a model that may have read
something hostile. It is served so that nothing it does can reach the console or
the person looking at it:

- The bytes come from a separate route, `/api/v1/artifact-content/<token>`,
  that reads no cookie and no session. The token is signed, names one version,
  and expires in minutes. It is minted only after a grant or a public link
  admitted the caller.
- Every content response carries `Content-Security-Policy: sandbox
  allow-scripts allow-popups allow-popups-to-escape-sandbox allow-modals`,
  with no `allow-same-origin`. The page runs in an opaque origin, so it cannot
  read the console's cookies, storage or page, and a request it made would carry
  nothing of the viewer. That holds even when somebody opens the content address
  on its own.
- The same policy sets `default-src 'none'` and `connect-src 'none'` with no
  remote source, and `frame-ancestors` names only the console. The frame in the
  console carries the same `sandbox` list as a second lock.

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
its artifacts: they stay readable and simply have no publisher. Deleting the
organization removes them. A deleted person's artifacts stay and lose their
owner, the way their agents and skills do.

The bytes live in the deployment's [file storage](configuration.md#uploaded-files-at-rest),
under `artifacts/<organization>/<artifact>/`.

## Limitations

- **One self-contained document per version.** No bundles, and no network from
  inside the page.
- **No live data.** A dashboard shows the data it was published with. It
  refreshes when the agent publishes again - a schedule is the usual way.
- **The agent cannot read its artifacts back.** A report is rebuilt from its
  data, not edited from the last version.
- **An open page outlives a revocation by one signed-address lifetime**, five
  minutes by default.
- **Removed versions are gone.** A conversation that links to a version older
  than the kept window can only offer the latest one.

## Recap

- One capability, one tool: `publish_artifact`, from a workspace file or inline.
- The agent and the name are the identity; publishing again keeps the link and
  adds a version.
- Private by default; shared with grants, the organization or a public link, by
  a person.
- Served from a cookieless route in an opaque origin with no network, and
  optionally from a domain of its own.
- A retention class of its own, measured from the last publication.
