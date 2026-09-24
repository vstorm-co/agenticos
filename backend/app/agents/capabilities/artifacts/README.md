# Artifacts

Exposes one tool, `publish_artifact`, which publishes a finished page - a report,
a small dashboard, a one-page summary - as an **artifact**: a shared resource with
an owner, a visibility and grants, opened in a browser under a link that stays put.

## Layout

| File | Holds |
|---|---|
| `_toolset.py` | `build_artifacts_toolset`: the tool, its prompt, reading the page out of the workspace; `PublishedArtifactResult`/`parse_published_artifact`, the wire format the chat card reads |
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

A publication is keyed on `(organization, agent, name)`. The next run of the same
agent - from the chat, a schedule, the API or a workflow - that publishes
`weekly-report` updates the same artifact, which is what makes "every Monday,
publish the week's numbers to this link" work without anything remembering an id
between runs. A new name is a new page.

The name is shared by everybody who runs the agent, so it is not a licence to
write. A run republishes an existing artifact only for its owner or for a member
holding `artifacts:edit` on it - the role scope or an `edit` grant, decided by
`resolve_access` exactly as in the console. Anybody else's run is told the name is
taken and publishes under another, and the page behind the first member's link
stays theirs.

Every publication is a new version row; nothing is overwritten, so a conversation
that published last week's report still opens last week's report. Publishing
exactly the bytes of the current version adds no version (`unchanged` in the
result), so a schedule that finds nothing new leaves the history alone - it still
counts as a publication, so retention's clock restarts either way. The newest
`ARTIFACT_MAX_VERSIONS` are kept.

## Why the page has no network

The page is agent-authored HTML with script in it, and it is served with a
`sandbox` Content-Security-Policy that gives it an opaque origin: it cannot read
the console's cookies, storage or DOM, and a request it made would carry nothing
of the viewer. `connect-src 'none'` and no remote sources go one step further -
the page cannot load code from anywhere or send what it shows anywhere, so a
prompt-injected report cannot beacon the numbers it was built from. The tool text
tells the model to inline everything for that reason; a CDN script simply does
not load. The sandbox grants no `allow-popups` for the same reason: `connect-src`
does not govern navigation, so a link opening a new window would be a way out to
an address the page chose. A link inside the page stays in its frame, where the
console's `frame-src` refuses every origin but the content one.

## Deliberately not side-effecting

`side_effecting` would put every publication behind the approval gate, which would
park the scheduled report this capability exists for. A first publication is
private to the person the run was for, and making it visible to anyone else is a
person's decision in the console, not the model's. An author who wants a person to
approve each republish of an already-shared page sets `tool_approval` on
`publish_artifact` in the agent's spec.

## Deliberately not here

- **Choosing visibility or turning on the public link.** Sharing is a decision a
  member makes with their own grant; an agent that could widen who reads a page
  would be an agent that could leak one.
- **Multi-file bundles.** One self-contained HTML or Markdown document per
  version. A bundle means a manifest, path routing and per-file limits for a
  benefit an inlined page already delivers.
- **Listing or reading artifacts back.** A report refreshes by being rebuilt from
  its data, not by editing the last version.
