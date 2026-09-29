# Artifacts

Exposes two tools. `publish_artifact` publishes a finished page - a report, a small
dashboard, a one-page summary - as an **artifact**: a shared resource with an owner,
a visibility and grants, opened in a browser under a link that stays put.
`read_artifact` reads the current version back, so a small change is an edit rather
than the whole page again.

## Layout

| File | Holds |
|---|---|
| `_toolset.py` | `build_artifacts_toolset`: both tools, their prompts, reading the page out of the workspace, `apply_edits`; `PublishedArtifactResult`/`parse_published_artifact`, the wire format the chat card reads |
| `_capability.py` | The `Artifacts` dataclass and `get_toolset()` |
| `__init__.py` | The registry entry and exports |

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

## Deliberately not side-effecting

`side_effecting` would put every publication behind the approval gate, which would
park the scheduled report this capability exists for. A first publication is
private to the person the run was for, and making it visible to anyone else is a
person's decision in the console, not the model's. An author who wants a person to
approve each republish of an already-shared page sets `tool_approval` on
`publish_artifact` in the agent's spec. `read_artifact` changes nothing.

## Deliberately not here

- **Choosing visibility, the public link or its settings.** Sharing is a decision a
  member makes with their own grant; an agent that could widen who reads a page
  would be an agent that could leak one.
- **Multi-file bundles.** One self-contained HTML or Markdown document per
  version, plus the served library set. A bundle means a manifest, path routing and
  per-file limits for a benefit an inlined page already delivers.
- **Listing artifacts.** The agent knows its pages by the names it gave them; a
  listing would put other members' page titles in front of the model.
