# Translate a page

This site publishes in English, Polish, German and Spanish from one `docs/`
tree. English is the source language: a page is written in English first, and
the other three are translations of it that can fall behind and are expected to
say so when they have.

## Where a translation lives

A translation sits beside the page it translates, with the locale in the file
name.

```text
docs/install.md      the English source
docs/install.pl.md   Polish
docs/install.de.md   German
docs/install.es.md   Spanish
```

[mkdocs-static-i18n](https://github.com/ultrabug/mkdocs-static-i18n) builds one
site per locale from that tree. English keeps the URLs it has always published -
`/install/` is still `/install/` - and each translation is added beside it at
`/pl/install/`, `/de/install/` and `/es/install/`. The language switcher in the
header moves between them without losing the reader's place.

Nothing else changes. There is no separate navigation file, no second `docs_dir`
and no per-locale copy of `mkdocs.yml`: the nav in `mkdocs.yml` is shared, and
its section headings are translated by the `nav_translations` table under each
locale there. A page's own title in the sidebar comes from the first heading of
the translated file, so translating the heading translates the nav entry.

## Every translation records what it was made from

The first thing in a translated file is its front matter, and the fingerprint in
it is the point of the whole arrangement:

```markdown
---
source_sha: 4f2b9c1ad07e
---

# Instalacja
```

That is the first twelve hex characters of the SHA-256 of `install.md` as it
stood when the page was translated. `scripts/docs_i18n.py` computes it, and two
things read it back.

`python3 scripts/check_docs_i18n.py` runs in `make lint` and fails the build on a
page with no translation, a translation whose fingerprint no longer matches its
English source, and a translation whose English page has been renamed or deleted.

The site build reads the same fingerprint and puts a warning admonition, in the
reader's own language, at the top of any page that is either untranslated or
behind. Without it a locale looks finished when it is not: a page nobody has
translated still answers on `/de/...`, in English, inside a German navigation,
and nothing distinguishes it from a page somebody actually translated.

!!! warning "`--update` is the last step of translating, not a way to go quiet"

    `python3 scripts/check_docs_i18n.py --update` stamps the current English
    fingerprint onto every translation that exists. Run it after you have
    retranslated a page. Run it over a page nobody retranslated and you have
    hidden a stale translation from both the gate and the reader, which is the
    one failure this design exists to prevent.

## Every heading pins its English anchor

A translated heading carries the English page's anchor explicitly, in the
`attr_list` form:

```markdown
## Berechtigungen { #permissions }
### Wer welche Rolle vergeben darf { #who-may-hand-out-which-role }
```

Without that, a heading translated into German gets a German anchor, and every
link written as `../permissions.md#who-may-hand-out-which-role` lands at the top
of the German page instead of at the section. There are over a hundred
cross-page links on this site and many carry a fragment, so this is not an edge
case - and `mkdocs build --strict` validates a link's path but **not** its
fragment, so nothing else notices.

Pinning also means one link works in all four languages without being rewritten
per locale, and a permalink somebody shared keeps working when they switch
language.

`scripts/check_docs_i18n.py` compares the two anchor lists in document order, so
a heading that is dropped, added, reordered or left unpinned fails `make lint`
and says which one. To read the list you have to pin before you start:

```bash
python3 scripts/check_docs_i18n.py --anchors docs/permissions.md
```

Do not derive the anchor by eye. The heading reading
`Layer 1: users.is_app_admin - the deployment superadmin` answers to
`layer-1-usersis_app_admin-the-deployment-superadmin`: the dot is dropped rather
than turned into a separator, and the underscores survive.

!!! note "Two heading anchors are not yours to pin"

    A repeated heading gets `_1` appended by the `toc` extension - `screens.md`
    has two called "MCP servers", the second of which answers to
    `mcp-servers_1`. Pin the same text on both and the suffix is applied to the
    translation the same way. The generated symbol headings on the
    `docs/reference/` pages come from the docstrings and have no heading in the
    Markdown to pin.

## What to translate, and what to leave alone

Translate the prose, the headings, the table headers and cell text that is
prose, the admonition titles, the image alt text and the link text.

Leave these exactly as they are in English:

| Never translated | Why |
|---|---|
| Code blocks, and everything in them | A reader types them verbatim |
| Command names, flags, environment variables | `make check`, `--strict`, `DATABASE_URL` |
| API paths, HTTP methods, status codes | `POST /api/v1/agents` |
| Field and configuration keys | `spec_version`, `budget.monthly_cap` |
| Permission names | `agents:edit` is a string the product compares |
| File and directory paths | `backend/app/core/vault.py` |
| Error and exception class names | `AuthorizationError` |
| Product names | Docker Compose, PostgreSQL, Slack, Prefect |
| Mermaid blocks | A label with a bracket or a quote in it breaks the graph, and the build cannot tell you - Mermaid renders in the browser |
| A console label the reader has to find on screen | The UI is English, so `Admin → Response Ratings` is a landmark, not a phrase |
| Image paths | One screenshot serves all four locales |

A comment inside a code block is prose a reader reads rather than types, so it
may be translated - but only where the block is an illustration. Never translate
a comment in a block somebody is meant to paste, because the paste will include
it.

## The product's own nouns stay English

The console does this already, and for the same reason: these words name things
a reader also meets in the API, in the YAML a spec exports into their own
repository, and in every English page of this site. Translating them here and
nowhere else gives one product two vocabularies, and a Polish reader who looks
up the translated word finds nothing.

**agent · spec · capability · skill · embed · budget · run · prompt · provider ·
token · vault · workspace · sandbox · MCP**

Inflect them rather than replacing them, and translate everything around them.

| English | Polish | German | Spanish |
|---|---|---|---|
| the agent's spec | spec agenta | der Spec des Agents | el spec del agent |
| publish a version | opublikuj wersję | eine Version veröffentlichen | publica una versión |
| grant a capability | przyznaj capability | eine Capability gewähren | concede una capability |
| the run failed | run zakończył się błędem | der Run ist fehlgeschlagen | el run ha fallado |
| a vault secret | sekret w vault | ein Secret im Vault | un secreto del vault |

Everything else is ordinary vocabulary and should read naturally: knowledge base,
organization, member, role, permission, approval, budget cap, notification,
channel, deployment.

## Terminology that has to be exact

Permission, governance and security pages describe refusals, and a refusal
described loosely is worse than one not described at all. Keep these
distinctions in every language:

| English | The distinction to preserve |
|---|---|
| permission / grant | A permission comes from a role; a grant is attached to one resource and widens it |
| role / membership | Authority lives on a membership row, not on a user |
| owner / admin / editor / viewer | Role names, matched against the catalog - keep the English name in parentheses on first use |
| budget cap / spend | The limit, and what has been spent against it |
| approval / refusal | A decision that is pending, and one that is final |
| organization / deployment | One tenant, and the whole installed instance |
| published / draft | A spec version that agents run, and one that nothing runs yet |

When a sentence states what the platform refuses, translate the refusal
literally. Do not soften "is refused" into "may not work", and do not turn a
statement about what cannot happen into advice about what you should not do.

## Two things a locale does not get

The reference pages under `docs/reference/` are generated from Python docstrings
by mkdocstrings. Translating one of those files translates its prose and its
headings; the generated symbol documentation stays English, because it is read
out of the source at build time. That is intended - say so in the page rather
than paraphrasing the docstrings into a second copy that drifts.

`release-notes.md` shows `CHANGELOG.md`, substituted at build time. A translated
release-notes page translates the page's own framing around the marker; the
changelog entries themselves stay English, because they are the commit history.

## Searching in Polish

lunr.js, which powers the site search, has no Polish stemmer, so `/pl/` search
matches whole words rather than word stems. German and Spanish stem normally.
There is nothing to configure - the build says so in its log - but it is worth
knowing before somebody reports it as a bug.

## The workflow

1. Copy the English page to `<page>.<locale>.md`.
2. Translate it, keeping the heading structure identical and pinning each
   heading's English anchor.
3. Check every relative link still resolves. A link to `../mcp.md` from a
   translated page resolves to the translated `mcp.md` automatically; a link
   written to `../mcp.pl.md` is wrong and fails the build.
4. `python3 scripts/check_docs_i18n.py --update`.
5. `make docs-build` - it runs `--strict`, so a dead link fails it.
6. `python3 scripts/check_docs_paragraphs.py` - the 115-word paragraph limit
   applies in every language, and a translation that merges two English
   paragraphs into one usually trips it.

Changing an English page is the same loop from the other end: change it, then
either retranslate the three translations in the same change, or leave them and
let the gate report them - what you cannot do is stamp `--update` over them.

## Recap

- A translation is `<page>.<locale>.md` beside the English page; English URLs do
  not move.
- Its front matter records the fingerprint of the English text it was made from,
  and every heading pins its English anchor.
- `scripts/check_docs_i18n.py` fails `make lint` on a missing, stale or orphaned
  translation and on headings that do not line up, and the site marks an
  untranslated or stale page for the reader.
- Code, commands, keys, paths and the product's own nouns stay English;
  everything around them is translated.
- Permission and governance wording is exact, not approximate.
