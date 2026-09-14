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
source_sha: "4f2b9c1ad07e"
---

# Instalacja
```

That is the first twelve hex characters of the SHA-256 of `install.md` as it
stood when the page was translated, taken from the text with its line endings
normalized so that a Windows checkout answers the same as CI.
`scripts/docs_i18n.py` computes it, and two things read it back.

`python3 scripts/check_docs_i18n.py` runs in `make lint` and fails the build on a
page with no translation, a translation whose fingerprint no longer matches its
English source, and a translation whose English page has been renamed or deleted.

The site build reads the same fingerprint and puts a warning admonition, in the
reader's own language, at the top of any page that is either untranslated or
behind. Without it a locale looks finished when it is not: a page nobody has
translated still answers on `/de/...`, in English, inside a German navigation,
and nothing distinguishes it from a page somebody actually translated.

!!! warning "`--update` is the last step of translating, not a way to go quiet"

    `python3 scripts/check_docs_i18n.py --update docs/install.pl.md` stamps the
    current English fingerprint onto that file. **Name the files you actually
    retranslated**, and nothing else is touched - stamping a page nobody
    retranslated hides a stale translation from both the gate and the reader,
    which is the one failure this design exists to prevent.

    That is why it takes paths rather than updating everything it finds. Change
    two English pages, retranslate one, and a blanket update would mark both
    current: the untouched page keeps its old text, loses its notice, and is
    never mentioned again.

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

### A kept noun needs a gender, and it gets one here

An English noun dropped into a German, Polish or Spanish sentence has to take an
article and an ending, and left to each page it takes a different one. The first
German pass produced "der Sandbox" on one page and "ein Sandbox" on another; the
reader meets both. So the choice is made once, here:

| Noun | German | Polish | Spanish |
|---|---|---|---|
| agent | der Agent | ten agent, agenta | el agent |
| spec | der Spec | ten spec, speca | el spec |
| capability | die Capability | ta capability (nieodmienne) | la capability |
| skill | der Skill | ten skill, skilla | el skill |
| embed | das Embed | ten embed, embeda | el embed |
| budget | das Budget | ten budżet | el budget |
| run | der Run | ten run, runa | el run |
| prompt | der Prompt | ten prompt, promptu | el prompt |
| provider | der Provider | ten provider, providera | el provider |
| token | das Token | ten token, tokena | el token |
| vault | der Vault | ten vault, vaulcie | el vault |
| workspace | der Workspace | ten workspace, workspace'u | el workspace |
| sandbox | die Sandbox | ten sandbox, sandboksie | la sandbox |
| MCP server | der MCP-Server | ten serwer MCP | el servidor MCP |

German compounds them with a hyphen when the second half is German - Run-Kosten,
Vault-Eintrag, Sandbox-Session - and keeps the English word's own capital.

### A generic person is masculine, in all three languages

English says "the reader", "an operator", "whoever wrote the agent" without
choosing a gender, and every language here has to choose one. Left to each page
it comes out differently: the first German pass produced "der Betreiber" on one
page and "die Betreiberin" on the next, for the same person, and a reader met
both.

So the generic form of a role is masculine - der Leser, der Betreiber, der Autor,
der Entwickler, der Administrator, der Besitzer, der Kunde; czytelnik, operator,
autor; el lector, el operador, el autor. This is about a person nobody has named.
A named example keeps the gender the example gives it, and so does a sentence
about one particular person.

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

## The four files GitHub renders, not this site

`README.md`, `CONTRIBUTING.md`, `SECURITY.md` and `CODE_OF_CONDUCT.md` are
translated the same way and recorded the same way, and
`scripts/check_docs_i18n.py` asks about them too. Three things differ, all of
them because GitHub renders those files and MkDocs does not.

**The fingerprint goes in a comment, not front matter.** GitHub renders a `---`
block as a table, so a reader would meet `source_sha` before the project's name.
`--update` writes `<!-- source_sha: 4f2b9c1ad07e -->` on the first line instead,
and reads it back from there. In a page of the site the value is quoted, because
about one fingerprint in 281 is all decimal digits and YAML would read that as a
number.

**Headings cannot pin an anchor.** `{ #permissions }` is `attr_list`, which is a
Python-Markdown extension; GitHub has no equivalent and prints the braces.
A translated heading therefore answers to its own anchor, derived by GitHub's
rule rather than the `toc` extension's — close, but not the same one, because
GitHub keeps a letter the site folds to ASCII and turns each space into its own
hyphen. So **rewrite every link the file aims at itself**, and check the result:

```bash
python3 scripts/check_docs_i18n.py --anchors README.pl.md
```

The gate compares the shape of the sections instead of anchors — as many
headings, nested the same way — and fails on any in-page link that no heading
answers to. That second half is what catches a file left half-translated:
untranslated headings keep the shape of the ones they were copied from, so shape
alone cannot see it, but the links above them still point at headings that have
moved. Nothing else would notice, because GitHub serves a dead fragment as the
top of the page, silently.

**Every other link points at the reader's own language.** A Spanish README links
to `docs/install.es.md`, not `docs/install.md` — otherwise choosing a language
lasts exactly one click. The gate checks each one against the English page's
link in the same position, so a dropped, reordered or unlocalized link fails it.
A page with no translation, like `docs/ROADMAP.md`, stays English, and the
language bar is left alone: pointing at other languages is what it is for.

**Each file carries a language bar** to its three translations, and the
translations link back. Update all four when a language is added.

`CHANGELOG.md` is not translated, for the reason `release-notes.md` is not: it is
the commit history.

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
4. `python3 scripts/check_docs_i18n.py --update <page>.<locale>.md` - the file
   you just translated, and no others.
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
