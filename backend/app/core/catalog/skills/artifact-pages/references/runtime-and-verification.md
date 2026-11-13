# Runtime and verification

The current tool description is authoritative. These recipes explain the decisions around it; they do not add tools, permissions or network access.

## Build and publish

1. Read the existing App when updating one. Keep its stable name and make exact targeted edits where possible; concurrent updates require the current version.
2. Choose HTML for interaction and Markdown for a readable document. A complete HTML page includes doctype, language, viewport and title. Native HTML, CSS, SVG and a small script are often sufficient.
3. Use only the library paths named by the active Apps tool. Apps currently serves `agenticos-3` helpers; the similarly named Visuals helpers are a different contract. Load only what the page uses. JSX and bare package imports are not executable browser HTML: a build must really run and bundle its dependencies before publication.
4. Keep images self-contained using the admitted format. Remote URLs, CDN scripts and web fonts do not load in the isolated page. Provide useful alternative text for informative imagery; decoration should be silent to assistive technology.
5. Publish through the real tool. Open the resulting version as an authorized recipient, then check its intended shared/public surface separately. A local file is not proof that a shared link or data binding works.

## Live records and actions

Use the active tool's binding schema for live tables, including exact field names and supported limits. Treat `status: unavailable` as unavailable data, not as a successful empty query. An empty successful result can invite the reader to adjust a filter. A truncated result must say that it is partial; compute summaries honestly for that subset unless the source supplies a full aggregate.

Render record text with `textContent` or another escaping renderer. User-supplied text must not become `innerHTML`, an executable event handler or a script. Fetching an arbitrary endpoint is not a substitute for a supported binding.

The records of a shared App are read under its admitted data access. Do not assume that each viewer's own permissions will filter a snapshot or an owner-backed query. Include only what that audience may see. Write actions require actual supported workflow/action bindings and their current permissions/approvals. Preserve the user's input when an action is refused; acknowledge success only after a real successful result.

## Check before delivery

- Main question, source/period/units and assumptions are visible.
- The first state is useful; every primary control, reset and navigation target works.
- Empty, unavailable and failed states tell the truth and offer a relevant next step.
- Phone and desktop have readable type, unclipped controls and no unintended horizontal page scroll. A genuinely wide table may scroll in a named, keyboard-focusable region.
- Tab order, focus, labels and keyboard activation work. Color is not the only status cue. Animation has a useful purpose and respects reduced motion.
- There are no unexpected external requests, console exceptions, broken images or missing library globals.
- The actual published page opens for its intended audience. Check any live binding or action separately from layout.

Describe the checks actually performed. If publication, an integration or a device remains untested, say which one. Offer the real link and one or two useful things the reader can try.


## Keep scripts local and initial content resilient

Use `<script type="module">` for page logic or wrap a classic script in an IIFE. Top-level classic-script declarations share the Window scope: names such as `top`, `parent`, `location` and `name` can collide with built-in properties and stop the entire script before any card or chart is filled. Keep rendering functions independent so an optional icon or chart failure does not erase the report's text and table. Render essential headings, figures and source links in HTML first; enhance them with working controls.

A syntax/structure check does not execute JavaScript. `preview_artifact` must report the actual renderer's console exceptions and missing resources. When it says no renderer is available, state that execution remains unverified; do not describe the page as rendered successfully. Load only the documented AO APIs, and do not guess an API from its name. When a failure occurs, inspect the source and actual console error before changing a dependency.

## Public links

A signed-in App URL is not public. When the person explicitly wants anyone with the link to read it, use the platform MCP `create_app_public_link` operation with the real artifact id and public confirmation. It follows the normal write gate and the App's edit permission. Reuse an existing public URL; do not rotate it incidentally. Public live-data consent, expiry and passwords remain separate controls, and a refused or pending action is not a working public link. A private channel request alone does not authorize public publication.
