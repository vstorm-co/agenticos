---
description: Frontend conventions — App Router, data layer, stores, i18n, permissions
globs: ["frontend/**/*.ts", "frontend/**/*.tsx", "frontend/**/*.css"]
---

# Frontend Conventions

Deeper guidance lives in the `frontend-feature` skill.

## Stack

Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind · `next-intl` ·
TanStack Query · Zustand · vitest + Testing Library · Playwright. Package manager and
runner: **bun**.

## Structure

| Path | |
|---|---|
| `src/app/[locale]/(dashboard)/…` | The product. Routes are **locale-prefixed** |
| `src/app/[locale]/(auth)/`, `auth/`, `onboarding/`, `legal/`, `shared/` | Everything else |
| `src/app/api/…` | Route handlers proxying to the backend (same-origin auth cookies) |
| `src/lib/` | Typed API clients on `api-client.ts` / `server-api.ts`, plus `query-keys.ts` |
| `src/hooks/` | One per resource — `use-agents`, `use-permissions`, … |
| `src/stores/` | Zustand, one per concern, re-exported from `index.ts` |
| `src/components/<domain>/` | UI by domain; primitives in `ui/`, empty/error in `states/` |
| `src/types/` | Shared types |

There is no `(marketing)` route group.

## Conventions

- **Server Components by default.** `"use client"` only for state, effects or handlers.
- **All API access goes through `src/lib/` clients**, consumed via a hook. No `fetch`
  in a component.
- **Register query keys** in `query-keys.ts` so invalidation stays consistent.
- **Stores hold UI/ephemeral state only.** Server data lives in the query layer.
- **Every user-facing string through `next-intl`**, and `make lint` enforces it:
  `frontend/scripts/check-i18n.ts` fails on a string a person would read sitting in a
  component - a text node, a readable attribute, a toast, a sentence in a ternary -
  and on the reverse, a key a component reads that `messages/en.json` does not hold.
  A genuine non-string takes `i18n-exempt: <reason>`; the reason is required, and it
  covers the line it is on, the line below, and the element it opens - so a comment
  above a tag with four Tailwind classes on it still reaches the copy inside.
  `bun run check:i18n` from `frontend/` runs it alone; `scripts/check-i18n.test.ts`
  is what holds each rule shut.
- **The guard parses; it does not grep (#395).** It walks `JsxText`, `JsxExpression`,
  `StringLiteral` and `TemplateExpression` through `ts.createSourceFile`, which is why
  there are no thresholds left to fall between: a node the formatter broke over three
  lines is one node, a type argument list is not JsxText at all, and a comment is
  invisible rather than blanked. The four shapes patched into the old regexes - #199,
  #246, #249, #314 - each keep a spec, and so does #141's plain multi-line node. What a
  *string literal* holds is the one rule still deciding by pattern, and #656 and #678 are
  what that costs - the same mistake twice, in the same regex: an alternative written to
  exempt a *token* that exempted the whole string it opened. A hyphen inside the first word
  read as the separator in `Foo / Bar`, so `Sign-in failed` was a label and no sentence
  opening on a hyphenated word was ever reported; and a leading acronym exempted everything
  after it, so `API keys are stored in the vault` left the sweep while `Provider keys are
  stored in the vault` did not - a hole the width of a vocabulary, in a product whose copy
  opens on `MCP`, `API`, `RAG`, `KB` and `JWT`. Both alternatives are anchored now - the
  `[A-Z]` after the separator, the `$` after a single lower-case word - so each exempts a
  complete two-token label and nothing longer. `MCP server` is still a label; `MCP server
  URL` is copy and needs a key. Either side of the separator may itself be an acronym
  (`URL / Endpoint`), which the acronym alternative used to cover by accident and anchoring
  it took away.
- **It reads a `.ts` file as well as a `.tsx` one, and by the same rules.** A parser
  reads one by construction: there is no bracket to anchor on and so nothing to gate on
  the suffix, and a file with no JSX in it simply yields no phrases. That matters because
  a hook's toast and a module table of labels are copy - 381 offences across 90 files,
  unread for as long as the sweep walked `*.tsx` alone (#446). **`src/app/api/**` is read
  like everything else**: a route handler sits outside the `[locale]` segment and has no
  translator to reach, so a refusal it mints is a `BFF_ERROR_KEYS` code from
  `src/lib/bff-errors.ts` (written with `bffRefusal`, resolved by `getErrorMessage`
  against the `errors` namespace at the toast), never an English sentence (#603).
  `dev/`, the playground, is the one skip left.
- **A count is an ICU `plural`, never a ternary.** `{n} file{n === 1 ? "" : "s"}`
  and `count === 1 ? "1 skill" : \`${count} skills\`` are sentences only English
  builds that way, so they are refused too - the message holds
  `{count, plural, =1 {1 skill} other {# skills}}` and the component passes `count`.
  Same for a text node that mixes words with an interpolation: it is one message with
  a named parameter, not English with a hole in it. **A single word counts** — on
  either side: `Owned by {email}`, `{n} runs`, `Rotate {name}`, `· expires {date}`.
  So does a single word beside an interpolation in a *template literal* -
  `` aria-label={`Remove ${source.name}`} `` - where whitespace is the discriminator
  rather than a word count: a space between a word and the `${` makes it prose, and
  `` `audience${key}Hint` `` builds a key. **An element ends a phrase**, so
  `Sign in to <em>{t("x")}</em>` is refused: one message with a tag, read with
  `t.rich`, never a head and a tail. A number and a unit is not a sentence -
  `` `${bytes} KiB` `` and the like - and the unit list in the guard is what says so.
- **A key nothing reads is not a translation, and a sentence is one message.** The
  guard asks the catalog both questions: it refuses a key no component
  reads, and a message whose words are also written out in the source. Both are anchored
  on the catalog rather than on the source, which is how they found the `.ts` copy first:
  the offence sweep walked `*.tsx` alone until #446, so `src/hooks/**` had never been
  read by it at all and nineteen toasts sat there in English beside the keys holding
  them. Both halves read every `.ts` file now. 141 keys were unread, 82 of them
  translated into Polish for nobody (#425).
  `messages/catalog.test.ts` adds the third and cheapest: **a value opening on `.`, `,`,
  `:` or `;` is half a sentence** - the other half is still in the JSX. A sentence with
  emphasis or a link in it is *one* message with a tag, read with `t.rich`
  (`Sign in to <em>your workspace.</em>`), never a head, a `<span>` and a tail.
- **The catalog holds copy, and only copy.** A false positive from the guard takes an
  `i18n-exempt`; it never takes a key. Answering one by moving the offending text into
  `en.json` silences the guard and hands a translator something nobody reads - which is
  how 18 Tailwind class lists and 148 fragments of source ended up in there, the class
  lists read back through `cn(t("flexItemsStartGap"))` where translating one strips the
  component of its styling (#348). `messages/catalog.test.ts` refuses both shapes now.
  A DOM `KeyboardEvent.key` name is not copy either: fifteen were parked and read back
  as `e.key === t("enter2")`, where the first Polish translation would have silently
  killed Enter-to-submit (#549) - key handling compares the literal (`e.key ===
  "Enter"`), and the catalog test refuses a value that is exactly a key constant.
- **A module table holds keys, and the component translates.** A module constant cannot
  call a translator, so a table of labels holds catalog keys and the copy is resolved at
  the point of use - `TOOL_CATALOG`'s `captionKey`, `MCP_AUTH_LABEL`, the `Choice` rows
  in `ingestion-config.ts`. A *pure function* over such a table either answers with a
  key or takes `t`: `toolStep`, `toolCaption`, `ingestionProblems` and
  `mergeWithUserCommands` all take the caller's translator, and `Translate` in
  `agent-step-captions.ts` is the shape they take. A table whose labels nothing renders
  is **deleted** rather than translated - four MCP category headings and a whole
  superseded catalog went that way, and a key nothing reads fails the build anyway.
- **A verb the sentence agrees with is not a parameter either.** `{verb} {subject}` is
  the `{noun}` defect below under another name, so a step naming its own subject holds
  one message per tense and selects on whether it has one:
  `{named, select, no {Writing…} other {Writing {subject}}}`.
- **A noun the sentence agrees with is not a parameter, and not a prop.**
  `{matched} of {total} {noun}` with `noun="skills"` reads as translated and renders
  `3 of 40 skills` under `pl`. The noun goes inside the ICU `plural` or `select`, so
  each locale writes its own forms; a component that needs one takes the *formatted
  phrase* (`counted="40 skills"`, from the caller's namespace) or a key, never a word.
  The guard only reads props named in `READABLE_ATTRS`, so copy arriving through a new
  prop name is invisible until that name is added - `noun` and `term` were (#362).
- **English is the source language, and `pl.json` holds only what is translated.**
  `src/i18n.ts` merges `en.json` underneath every locale, so a missing translation
  renders English instead of the key. A module-level table of labels cannot call a
  translator, so it holds *keys* and the component translates at the point of use;
  a pure helper either answers with a key or takes `t`.
- **The product's own nouns stay English in every locale**, and this is the list:
  **agent, spec, capability, skill, embed, budget, run, prompt, provider, token,
  vault, workspace, sandbox, MCP**. They name things a client also meets in
  `docs/`, in the API and in the YAML a spec exports into their own repository, so
  translating them in the UI and nowhere else makes two vocabularies for one
  product - a Polish reader looking up *zdolność* finds nothing. Inflect them
  rather than replacing them (`agenta`, `w spec`, `runy`), and translate everything
  around them. Decided before the first namespace rather than after the third
  (#643); a word joining the list belongs here, not in one `pl.json` entry.
- **Translate a namespace, not a branch.** Seventy Polish strings among four
  hundred English ones in one dialog is worse than a consistently English one, so
  the unit of work is the namespace a person reads on one screen - which is why
  #634 finished `hosted` (12 keys, what a Polish visitor lands on) and left
  `agents` (509) whole. Polish also makes the count rule bite harder than English
  does: `one`/`few`/`many`/`other` where `en.json` needed `=1`/`other`.
- **The locale lives in a cookie, and a switch goes through `@/lib/locale-navigation`.**
  `localePrefix: "as-needed"` means an unprefixed path *is* English, and 49 files import
  a plain `next/link` - so a switch that only rewrites the URL survives exactly one
  navigation (#285). `useRouter().push(pathname, { locale })` from
  `@/lib/locale-navigation` writes `NEXT_LOCALE` as well as prefixing the path, and
  `src/middleware.ts` restores that prefix from the cookie on the way in - and records
  the cookie for a path that names a locale, which next-intl does only when
  `accept-language` disagrees. Never switch locale through `next/navigation`, and keep
  prefix parsing in `src/lib/locale-routing.ts`: next-intl matches a prefix
  case-insensitively, and a second parser that does not turns `/PL/agents` into a 404.
- Keep components under ~100 lines; extract when they grow.
- **A response with no `Cache-Control` is not a response nobody caches.**
  `platform-proxy.ts` stamps `no-store` on anything the backend left unmarked: every
  answer on this surface depends on a cookie, a permission set and the organization
  header, and a list refetched right after a write must reach the server. A
  hand-rolled route file owes the same header - the proxy is the only place that
  applies it for you.
- **A brand mark is one row in a generator's table, and there is no second
  source.** `src/lib/brand-glyphs.generated.ts` holds every service, connector
  and model-provider mark the console draws, as raw SVG path data, written by
  `bun run gen:brand-icons` from Simple Icons, Font Awesome and
  `@lobehub/icons-static-svg`. Adding a mark means adding a row to `BRANDS` or
  `PROVIDERS` in `scripts/gen-brand-icons.ts` and re-running — never an import
  from an icon package, and never a hand-authored `d`, which is how a mark
  quietly stops being the brand's. `BrandIcon` draws one, `brandMark(name)` binds
  one for a table that also holds lucide icons, and `ProviderIcon` draws the
  provider half; nothing else touches the glyph data. There were three
  mechanisms before #156 — `react-icons` for connectors, a deep
  `@lobehub/icons` import for providers, this file's ancestor for MCP favicons —
  199 MB installed to draw 89 marks that are the same artwork either way.
  The generator refuses a source SVG it cannot draw with paths alone, or one
  carrying a literal fill: a mark that silently loses a layer still renders, and
  is still the wrong logo. It also emits `src/lib/auth-glyphs.generated.ts` —
  just the identity-provider marks — because `BrandIcon` reads the 89-mark table
  by dynamic key, which no bundler can tree-shake, so importing it put every mark
  on the critical path of the sign-in page; the auth pages import `AUTH_GLYPHS`
  and draw it through `GlyphIcon` instead (#955).
- Do not hand-edit `src/lib/mcp-logos.generated.ts` — run `bun run gen:mcp-logos`.
- **A dependency nothing imports fails `make lint`.** `bun run lint:deps` is knip
  narrowed to that one question, and it runs in `lint-frontend`. A false positive
  takes an entry in `knip.jsonc` *with the reason on the line above it* — the
  same bargain `i18n-exempt` and `[tool.vulture] ignore_names` take. An entry
  added to silence a finding is worse than the finding: `date-fns` was declared,
  imported by nothing, and sitting in that ignore list, so the report that would
  have found it had been told not to look.
- **How big a dialog is comes from `src/lib/dialog-sizes.ts`, and nothing else.**
  One width token (`DIALOG_CONFIRM` … `DIALOG_CANVAS`) and one shape token
  (`DIALOG_SCROLL`, `DIALOG_COLUMN`, `DIALOG_FILL`, `DIALOG_FRAMED`), or
  `DIALOG_WINDOW`, which carries both. Forty dialogs used to hold five heights and
  nine widths between them, decided one at a time - which is #940 in the width
  dimension and #1069 in the height one, and both were the same defect: nobody had
  decided, each had picked. A height is a floor as much as a cap, so a three-field
  form takes `DIALOG_COLUMN` and only a pane to work in takes `DIALOG_FILL`. Two
  shapes owe their body a class the token cannot give it - `min-h-0 flex-1
  overflow-y-auto` under `DIALOG_COLUMN`, `min-h-0 overflow-y-auto` under
  `DIALOG_FRAMED` - because a flex or grid child without `min-h-0` refuses to
  shrink, and the dialog then grows past its own ceiling or clips the footer that
  holds the button advancing the wizard.
- **Opening a file is `components/files`, and there is no second one.** `FileViewer` is
  the dialog every surface opens; `FileContent` is it without the dialog, for a surface
  with its own chrome; `FileTextView` is it without the fetching, for content already in
  hand. What kind of file it is comes from `resolveFileKind` in `src/lib/file-kinds.ts`
  and nowhere else — that one answer decides which request is made, which viewer
  renders, and which icon `FileIcon` draws. How a surface *reaches* the bytes is a
  `FileAccess` the caller builds (`workspaceFileAccess`, `kbDocumentAccess`,
  `attachmentAccess`), because the addresses authorise different callers and the viewer
  must never branch on which it was handed. There were four viewers, three notions of
  "what kind of file is this" and two icon sets before #136: a `.csv` an agent wrote was
  a spreadsheet to the icon, plain text to the workspace dialog and a table to the
  composer's card, on the same screen — and a PDF, an image or an HTML page opened from
  the chat panel was a byte count with a download link.
- **A tool the backend registers is one row in `src/lib/tool-catalog.ts`, and nowhere
  else.** Icon, what the step says while it runs, what it is called once finished, and
  which renderer opens under it — one table, keyed on the id a capability declares.
  That knowledge used to sit in `tool-steps.ts`, `agent-step-captions.ts` and
  `tool-call-card.tsx` independently, so the `web_search` / `create_chart` rename landed
  in one of the three and both tools rendered as pretty-printed JSON for five weeks,
  beside the renderers written for them, with a green suite — because the tests
  constructed calls under the old names too (#144).
  `backend/tests/test_capability_registry.py::TestFrontendToolCatalog` compares the two
  in both directions, so a missing row and a surplus one each fail there, naming the
  tool. A name from anywhere else — an MCP tool, one a binding renamed — has no row and
  needs none: it falls back to a humanized name and the generic renderer. What a row
  holds is `captionKey` / `displayNameKey` / `verbs`, all of them keys under
  `chat.tools`, because the table is a module constant with no translator to reach.

## A new surface owes the onboarding walkthrough a stop

`src/lib/onboarding/tour.ts` (the passive walk every page's "?" replays) and
`flows.ts` (the guided creation it offers at the end) are **registries**. A page,
tab, section or create control added anywhere else is simply missing from them —
nothing fails and nothing warns, so the feature ships invisible to everyone who
learns the product through the tour.

Add the stop in the same change: a `TourStep` plus a `data-tour` on the control it
names; a `CreationFlow` and its `flowForPage` entry where the page can create
something; a resolver in `components/onboarding/detail-targets.ts` for a detail
view with no route of its own; and `steps.<id>.title`/`.body` in `messages/en.json`,
because a missing key renders the key.

Three things decide whether the stop works, each got wrong here at least once:
gate it on the permission its control carries (an ungated step waits four seconds
for an element a refusal never mounts); mark it `optional: true` when the control
renders only where data exists (an empty catalog otherwise pins a caption to
nothing); and anchor it on something **bounded** — `data-tour` on a card whose body
is a whole catalog spotlights the entire viewport, which highlights nothing, so the
describing step takes the header and the card's own anchor is left to the guided
flow, which needs the list reachable.

The full picture, including what CLAUDE.md requires, is in `CLAUDE.md` under
"A new surface owes the walkthrough a stop".

## A feature with glanceable state owes the dashboard a widget

The arrangeable dashboard is a registry with the same failure mode as the tour: a
feature added anywhere else is simply absent from the catalog, nothing fails, and
the product reads as parallel features rather than one — #594 stitched exactly
these seams after W3 shipped four features on branches that could not see each
other. If a feature produces activity or state a person would want at a glance
(runs, schedules, sync health, spend), it ships its card in the same change. Five
edits, each demonstrated by every existing widget:

- the id in `WidgetId` and its def in `WIDGETS` (`src/lib/dashboard/registry.ts`) —
  gate on the permission the card's **primary** read demands, and fetch a more
  privileged half conditionally rather than raising the gate to it (the routines
  card gates `agents:view`, which `GET /triggers` asks, and reads the run outcomes
  only for a caller holding `runs:view` — a card that 403s on a permission its
  primary data never needed is a card its audience cannot add);
- the component under `components/dashboard/widgets/`, registered in
  `WIDGET_COMPONENTS` (`widgets/index.ts`) — built on `WidgetFrame` and the
  `widget-states` trio, reusing an existing hook rather than adding a card-only
  endpoint;
- a placement in `DEFAULT_SECTIONS` (`src/lib/dashboard/layouts.ts`) when the card
  belongs on the default arrangement, not merely in the add-a-widget catalog;
- the id mirrored in `WIDGET_IDS` in `backend/app/schemas/dashboard_layout.py` —
  `backend/tests/test_dashboard_registry.py` fails the build when the two drift,
  and `registry.test.ts`'s gate table plus its widget count both name the new id;
- `dashboard.widgets.<id>.*` copy (title, description, states) in en **and** pl,
  and the file itself in `vitest.config.ts`'s coverage include — the widget
  directory is gated file-by-file, so a new card is otherwise invisible to the
  100% gate however green its tests run.

## Permissions

`use-permissions.ts` gives the effective permission set for the active organization. A
control the caller may not use is **not rendered** — not rendered and then 403.

Prove it with an integration test (`*.integration.test.tsx`, Testing Library against a
mocked API), not with Playwright.

**Which roles a picker offers is arithmetic, not a list.** `assignableRoles` in
`lib/assignable-roles.ts` mirrors the server's `assignable_roles` over the catalog's
permission sets: a role is offered only when the caller's own strictly outranks it.
A list of "every role but owner" is what offered an Admin the Admin option and 403'd
after the email address was typed (#1028).

**And a page that names an organization in its URL *is* that organization.**
`apiClient` stamps `X-Organization-Id: activeOrgId` on every request, so a page acting
on the org in its path while reading permissions for the active one decides Acme's
members by the caller's role in Globex — which is what `/orgs/{id}/members` did, because
the organizations list opens it without switching (#1032). The adoption lives in
`ActiveOrgGuard`, once, beside the tenant cache reset it has to happen before; a page
does not do it for itself.

## An empty page is ambiguous

Every dashboard page fans out to several queries and renders its empty state when one
fails. "No skills yet" and "the request answered 502" are the same pixels — check the
network before the component, and never write a test that asserts only on chrome.

## Verify

From `frontend/` — at the repository root vitest finds no config and reports phantom
failures. While writing, run only what covers the change:

```bash
bunx vitest run src/components/chat/usage-strip.test.tsx
```

Once, before the push — from the repository root, because CI's `test-frontend` job
runs all four and `make lint-frontend` is the first three of them:

```bash
make lint-frontend && make test-frontend-cov && make build-frontend
```

**`test:coverage`, not `test:run`.** The job CI runs measures coverage and fails under
100% lines/statements/functions or 97.5% branches on `src/{app/api,lib,stores,hooks}`
and most of `src/components`, so a suite where every test passes can still be red. A
dead branch is easier to delete than to cover: a `?? ""` behind a check that already
proved the value, or an optional prop two callers always pass, is one the gate is
right to notice.

**A red spec that says "timed out" is usually the machine.** `testTimeout` is 15s and
`asyncUtilTimeout` 5s, both measured rather than guessed - `docs/testing.md#two-deadlines-both-sized-for-a-loaded-machine`
has the four runs behind them (#862). Neither is a reason to keep a spec that mounts
more than its assertions read.
