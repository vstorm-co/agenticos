# Artifacts

Exposes five tools. `publish_artifact` publishes a finished page - a report, a small
dashboard, a one-page summary - as an **artifact**: a shared resource with an owner,
a visibility and grants, opened in a browser under a link that stays put.
`read_artifact` reads the current version back, so a small change is an edit rather
than the whole page again. `list_artifacts` names the pages a run may open, and
`preview_artifact` draws one and says what went wrong while it ran. `share_artifact`
asks for one to be shared; it never shares anything itself (see below).

Source lives in artifact storage, independently of a conversation's sandbox: a later
conversation reads it by the same name and republishes edits or replacement content
behind the existing link. It needs no access to the original workspace. View and edit
permissions remain separate.

## Layout

| File | Holds |
|---|---|
| `_toolset.py` | `build_artifacts_toolset`: the five tools, their prompts, the preview report, reading the page out of the workspace, `apply_edits`; `PAGE_CONTRACT`; `PublishedArtifactResult`/`parse_published_artifact`, the wire format the chat card reads |
| `_capability.py` | The `Artifacts` dataclass, `get_instructions()` (the page contract) and `get_toolset()` |
| `__init__.py` | The registry entry, `ArtifactsConfig` and exports |

Identity, versions, storage and serving are `app/services/artifact.py`'s. This
package decides only what the model may say and how its mistakes are answered.

## What an artifact is, and is not

An artifact is a page that is **served**. A chart, a generated PDF and a workspace
file are files, and files already have a home - the workspace browser, the chat's
attachments. What an artifact adds is that it is shareable by link and that
republishing it changes what the link shows rather than making a second link.

## The name is the identity

A publication is keyed on `(organization, agent, environment, name)`. The next run
of the same agent - from the chat, a schedule, the API or a workflow - that
publishes `weekly-report` updates the same artifact, which is what makes "every
Monday, publish the week's numbers to this link" work without anything remembering
an id between runs. A new name is a new page.

The environment is read off the run row, never from the model: a run in `staging`
publishes a page of its own beside the default environment's, so trying a new
version of an agent cannot republish the page production readers have bookmarked.
The default environment is one slot whether or not a run named it.

The name is shared by everybody who runs the agent, so it is not a licence to
write. A run republishes an existing artifact only for its owner or for a member
holding `artifacts:edit` on it - the role scope or an `edit` grant, decided by
`resolve_access` exactly as in the console. Anybody else's run is told the name is
taken and publishes under another, and the page behind the first member's link
stays theirs. Reading back takes `artifacts:view` by the same rule, and a page the
run's person may not open is refused in the same words as one that does not exist.

An archived page is not there to a run: reading, previewing and listing pass over
it. Publishing its name is refused with a message naming the archive, said only
to a run that could have changed the page; a person restores it from the console.

Every publication is a new version row; nothing is overwritten, so a conversation
that published last week's report still opens last week's report. Publishing
exactly the bytes of the current version adds no version (`unchanged` in the
result), so a schedule that finds nothing new leaves the history alone - it still
counts as a publication, so retention's clock restarts either way. The newest
`ARTIFACT_MAX_VERSIONS` are kept, and so is a version a public link is pinned to.

## Edits, and why they carry the version they were made against

`edits` is a list of exact replacements, applied in order to the current version.
Each `old` must occur exactly once in the page as the edits before it left it: not
at all means the model is editing from a memory of the page rather than the page,
and more than once means the edit does not say which place it means. Both are
steered back with what to fix.

The tool reads the page, applies the edits, and publishes with the version number
it read. If another run published in between, the publish refuses rather than
write the edited copy of an older page over the newer one; the model is steered to
read again.

`read_artifact` returns at most 100,000 characters. A page with an inlined library
can be megabytes, and all of it would land in the context; an edit can still name
text past the cut.

## What the model is told about how a page looks

A page renders where nobody on the run can see it, and a model left with the
tool text alone wrote pages in quirks mode, with invented classes, tables with
no head and icons that never drew (#1974). Three things answer that, cheapest
first.

- **The page contract**, `PAGE_CONTRACT`, is this capability's standing
  instruction: the skeleton, a closed list of the kit's most-used classes, icons
  rather than emoji, `AO.records` for bound data, and "load `artifact-pages`
  when it is listed". It is static so the cached prompt prefix keeps it, and
  short because every request pays for it. A test holds each class it names to
  `agenticos-3.css`.
- **One steer a run to the guide.** The first whole HTML page of a run that
  offers the `artifact-pages` skill without having loaded it is sent back to
  load it and rebuild. Once per run, because the flag lives in the toolset the
  run builds; a run's history between turns is text only, so the next turn
  that publishes is steered again. On the last attempt the page publishes and
  the advice rides in the warning instead, since a steer there would publish
  nothing. A run with no such skill is never steered.
- **The publish lint**, `app/services/artifact_lint.py`, reads the published
  HTML and returns what looks wrong in the result's `warning`, one problem a
  line. It never refuses: the page is published either way, and the model
  decides whether to fix it. It is a pure function, so a preview tool can say
  the same things.

## Listing, and who the list is read as

History between turns is text only, so a model that published `open-tickets` an
hour ago no longer has the result in front of it, and a new name makes a second
page beside the first. `list_artifacts` answers "which pages already exist" with
this agent's pages in the run's environment, newest first, at most 50.

It is read as the person listening (`audience.user_id`), as `read_artifact` reads,
and filtered by the console's listing rule: their own pages, organization-wide ones
and those shared with them, or every page for a role that reaches every page. A
reader who has left keeps only their own, which is what `_may` still opens. In a
group chat only organization-wide pages are listed - never the speaker's private
or team pages, nor one shared with the speaker alone - because a title is often the
thing a page was kept private for. `read_artifact` and `preview_artifact` open only
those pages in a group chat too. `may_edit` is answered for `deps.user_id`, the identity
a publish is checked as. A surface with nobody signed in lists nothing.

## Actions: a page that starts a workflow

`publish_artifact(actions=[{workflow, label}])` declares up to five workflows a page's
buttons may start. The declaration is the agent's reviewed allowlist, not the model's
word: each one must be bound in the agent's **Workflows** capability (the factory hands
the run those ids as the `workflow_ids` resource), live, started by hand (Manual or API
trigger), in the organization, and viewable and runnable by the person behind the run.
One the person cannot reach is answered like an unbound one, so a refusal never names
it. The label is plain text of at most 60 characters with hidden characters removed;
the workflow's own name is what the console shows. `None` keeps the current version's
actions, `[]` removes them, and the result's `actions` says what was declared, or `kept`.

Like bindings, what a page can start is not changed by a run nobody answers for: a run
with no person may neither add nor change actions, and republishes a page that has some
only unchanged. A restore checks the stored actions again against the agent's current
spec. The checks and the version column are `app/services/artifact_actions.py`; starting
a run, as the person viewing the page and after they confirm it, is the console's and
the start route's, not this package's. See `docs/artifacts.md#actions`.

## Preview, and where the browser is

`preview_artifact` renders the current version through
`app/services/artifact_render.py` in a browser the operator runs
(`ARTIFACT_RENDER_CDP_URL`), the way a viewer's frame shows it: a host document
frames the page with the console's sandbox and answers its data bridge with what
the console would post the run's person. Every request is answered by the API or
refused, so the browser needs no network. The model gets a written report - data
per binding, uncaught errors, console errors, policy refusals, refused requests,
dialogs, then the publish lint - and the picture as an image part beside it
(`ToolReturn`), so the transcript and the chat step keep the text and not a
megabyte of base64.

The data is what `member_context(audience.user_id)` would be served: each page
query read with the page owner's access, for a viewer the page serves data at all.
In a group chat only a page the list would show there - an organization-wide one -
is opened at all (`room_may_see`), and it is drawn without data, since a picture of
the page's records would be read by the whole channel. Without a renderer, or without the `browser` extra, the report
comes back alone and says so: every deployment gets the lint, and those running
the browser get the picture. `preview_screenshot: false` keeps the picture from a
model that cannot read images; the report still comes back, because a page that
throws is worth knowing about whatever reads the answer.

## Why the page has no network

The page is agent-authored HTML with script in it, and it is served with a
`sandbox` Content-Security-Policy that gives it an opaque origin: it cannot read
the console's cookies, storage or DOM, and a request it made would carry nothing
of the viewer. `connect-src 'none'` and no remote sources go one step further -
the page cannot load code from anywhere or send what it shows anywhere, so a
prompt-injected report cannot beacon the numbers it was built from. The tool text
tells the model to inline its own data for that reason.

Two exceptions, both the deployment's own. A pinned **library set** - Chart.js, d3
and a stylesheet of the product's tokens - is served beside the page's address and
named by a relative path (`lib/chart-4.5.1.umd.min.js`), so the model stops
inlining 200 KB of Chart.js into every page. And a **link** to another site asks
the frame's parent to open it: the page has no `allow-popups`, and a person reads
the address before anything opens. See `docs/artifacts.md`.

## Sharing is a request, never an action

`share_artifact(name, visibility?, people?)` files an `audience` share request
(`app/services/artifact_requests.py`) as the run's person and answers "Waiting for
<owner> to approve in the page's Share dialog". It is the same request an editor's
Share dialog files when they are not the one who decides, and it is filed for the
owner's own run too: one mechanism, so an approval is always a person in the console, as
themselves, never a tool call that a prompt-injected page could talk into widening
itself. For that reason it is not a tool approval either - nothing parks unless an operator gates it - and it is
declared `side_effecting=False`: the call applies nothing.

`visibility` is `team` or `org`; there is no `public`, and the public link is never
touched. `people` are members' full names or addresses and groups' names, compared whole
and ignoring case, each asked for at view level; a name that matches nobody or several is
reported back, never guessed. A run with no person behind it (an outsider's input, a
widget visitor) cannot ask. A group chat opens only organization-wide pages, as
`read_artifact` does. An unbound page is no exception: the owner, or an Owner or Admin
when it has none, decides every widening, so the request is filed in all cases.

## Deliberately not side-effecting

`side_effecting` would put every publication behind the approval gate, which would
park the scheduled report this capability exists for. A first publication is
private to the person the run was for, and making it visible to anyone else is a
person's decision in the console, not the model's. An author who wants a person to
approve each republish of an already-shared page sets `tool_approval` on
`publish_artifact` in the agent's spec. `read_artifact`, `list_artifacts` and
`preview_artifact` change nothing, and `share_artifact` only files a request.

## Deliberately not here

- **Applying a share, or touching the public link or its settings.** Sharing is a decision
  a member makes in the console; an agent that could widen who reads a page would be an
  agent that could leak one. `share_artifact` only asks.
- **Multi-file bundles.** One self-contained HTML or Markdown document per
  version, plus the served library set. A bundle means a manifest, path routing and
  per-file limits for a benefit an inlined page already delivers.
- **Listing beyond the reader's reach.** The list is what the person listening may
  open in the console, never what the agent or its publisher could.
- **A tool that starts a workflow from a page.** The page asks, a person confirms; the
  agent declares what may be asked and starts nothing.
- **A browser in the API image.** The renderer is an operator's service on a network
  with no egress, never a process beside the vault.
