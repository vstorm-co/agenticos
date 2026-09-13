# Licences and third-party notices

!!! abstract "The claim this page makes, and the one it does not"

    Every component the two published images contain is listed with its licence
    and the evidence for it, every obligation those licences impose is either met
    in a way this page names or recorded as an open finding with an issue behind
    it. It does not say "all licences are compliant": three findings are open at
    the time of writing, and they are listed below rather than averaged away.

AgenticOS itself is Apache-2.0 (`LICENSE`, `NOTICE`). What a deployment actually
runs is that code plus roughly five hundred third-party packages, two Debian-based
images, a handful of fonts and icons, and whatever services and models the
deployment connects. This page is the review of all of that: what is in scope,
how the inventory is produced, what each licence family asks for and how it is
answered, and what to do when a dependency or a model changes.

## What is in scope

| Layer | Where the inventory comes from | Distributed by this project? |
|---|---|---|
| Backend Python distributions | `backend/uv.lock`, resolved for Linux with `uv export --no-dev` | Yes, in `agenticos-backend` |
| Frontend npm packages | the production closure of `frontend/package.json`, from `frontend/bun.lock` | Yes, in `agenticos-frontend` |
| Base images and the Debian packages the backend image installs | `backend/Dockerfile`, `frontend/Dockerfile` | Yes, as layers of both images |
| Fonts, brand glyphs, bundled data files | `frontend/src/app/fonts/`, `NOTICE`, `backend/app/core/catalog/` | Yes |
| Service images a deployment runs beside the two above | the compose files | No: pulled by the operator |
| Model weights | chosen per deployment in a model profile | No: never shipped |
| Hosted providers and services | configured per deployment with a credential in the vault | No: a contract between the deployment and the provider |

Development and documentation tooling (`uv sync --dev`, the `docs` dependency group,
`devDependencies`) is not in the images and not in the notices. Build tools that run
in a builder stage and are absent from the final layer, such as `uv`, are recorded
in `licenses/components.toml` as not distributed.

## The inventory

Two files carry it, and a script keeps them honest.

**[`THIRD_PARTY_NOTICES.md`](https://github.com/vstorm-co/agenticos/blob/main/THIRD_PARTY_NOTICES.md)**
is generated and committed. For every distribution in either image it records the
name, version, SPDX licence expression, source URL and the evidence the licence was
read from: a `License-Expression` header, a classifier, the licence file's own text,
the package index, or an override a person recorded. It also lists the open findings
first, a count of components per licence, and the hand-recorded components.

**`licenses/policy.toml`** holds the decisions. An `override` entry is the licence a
person determined for a component whose metadata does not say, with the evidence
they read. A `review` entry is the decision for a component under a copyleft,
share-alike or non-open licence: `accepted`, saying how the obligation is met, or
`open`, pointing at the issue that owns it. **`licenses/components.toml`** records
what no lockfile knows: the images, the Debian packages, the fonts, the glyphs, the
data files and the service images, each with a status and its obligation.

`scripts/license_inventory.py` reads all three. `make licenses` regenerates the
notices; `make licenses-check`, which the `security` job and `make check` run,
regenerates them in memory and fails when:

- the committed notices differ from what the lockfiles now resolve to, in any
  component, version, licence or source (the evidence cell is not compared: two
  wheels of one release can carry different metadata, and it records where this
  machine read the licence from);
- a component's metadata names no licence and no override records one;
- a component is under a licence in the review set and has no decision;
- a decision was made about a different licence than the one the component now
  carries, because an upgrade changed it;
- a decision names a component the lockfiles no longer resolve.

An open finding that is tracked does not fail the check. The verdict line counts it:
`LICENSES: REVIEWED - 518 components, 3 open finding(s)`.

!!! warning "A scanner's unknown is a question, not an approval"

    The script never guesses. A bare `BSD` in a `License` field is not resolved to
    a clause count by assumption; the licence file decides, and if that too is
    unreadable the check fails until somebody reads it and writes the answer down.
    The evidence column in the notices is what lets a reviewer tell a declared
    licence from an inferred one.

The inventory is what a deployment installs, not what the machine running the
script has. Environment markers are evaluated for Linux on both architectures the
images are built for, platform-specific npm packages are kept only when they build
for Linux glibc on x64 or arm64, and a package the machine lacks has its metadata
read from PyPI or the npm registry. A lookup that fails is a failure of the run.

## What the licences ask, and how it is answered

The counts below are from the notices at the time of writing; the notices file is
the current figure.

| Licence family | Components | Obligation | How it is met |
|---|---|---|---|
| MIT, ISC, BSD-2-Clause, BSD-3-Clause, 0BSD, MIT-0, MIT-CMU, Unlicense | about 400 | Keep the copyright notice and the licence text with copies | Each package's own licence file ships in the image, next to the code: every wheel's `*.dist-info/` in the backend image, every package's `LICENSE` under `/app/licenses/` in the frontend image. The notices index them |
| Apache-2.0 | about 90 | The licence text, notice of changes, any `NOTICE` file the package carries | Same as above; nothing is modified, so there are no changes to notice |
| PSF-2.0, CNRI-Python, Zlib, CC0-1.0 | a few | Attribution or nothing | Same as above |
| MPL-2.0 (`certifi`, `pathspec`, `tqdm`, part of `orjson`) | 4 | File-level copyleft: the covered files stay under MPL and their source is available | Used unmodified; the licence text ships; the notices link the source |
| LGPL-3.0-or-later (`psycopg2-binary`, `@img/sharp-libvips-linux-*`) | 3 | Licence text, source availability, and the ability to replace the library | Both are separately installed binaries loaded dynamically, unmodified, replaceable by reinstalling; sources linked in the notices |
| Artistic-1.0-Perl or GPL-2.0-or-later (`text-unidecode`) | 1 | Dual; taken under the Artistic License: notice and text | The wheel's licence file ships |
| CC-BY-4.0 (`caniuse-lite`) | 1 | Attribution and a link to the source | Named with its source in the notices |
| AGPL-3.0-only (`pymupdf`) | 1 | Network copyleft, see the finding below | **Open** |
| OFL-1.1 (Inter, Bricolage Grotesque, Geist Mono) | 3 families | Licence text and copyright notices with the fonts; no selling the fonts alone; no reuse of the reserved names for modified fonts | `frontend/src/app/fonts/OFL.txt` carries all three notices; the fonts are served unmodified |
| CC0-1.0, CC-BY-4.0, MIT (brand glyphs) | 3 sources | Attribution for the Font Awesome icons; the marks stay their owners' trademarks | `NOTICE` names the sources and the trademark position |

The base images deserve a sentence of their own. `python:3.12-slim` and `oven/bun:1`
are Debian, which means hundreds of packages under GPL, LGPL, MIT and BSD terms.
Debian keeps each package's licence at `/usr/share/doc/<package>/copyright` inside
the image and publishes the corresponding source for every binary it ships, which
is what the GPL and LGPL source obligation for a redistributed image rests on. The
backend image adds LibreOffice (MPL-2.0) and Tesseract (Apache-2.0) as Debian
packages, used unmodified as separate processes. The per-release SBOM planned in
[#1415](https://github.com/vstorm-co/agenticos/issues/1415) will record the exact
package set of each image; until it ships, the Dockerfiles and the base image
digests are the inventory of that layer.

## Open findings

Each has an issue; each will stay in this list, and first in the notices, until the
issue closes and the policy entry moves to `accepted` or the component is gone.

**PyMuPDF is AGPL-3.0-only** -
[#1602](https://github.com/vstorm-co/agenticos/issues/1602). It is the default PDF
parser and the only one that extracts embedded images. Our Apache-2.0 code may be
combined with it, but the backend image as a whole is then conveyed under AGPL-3.0
terms, and a deployment that modifies the platform and serves it over a network owes
its users the modified source. For an unmodified public release the obligation is met
by the repository being public; the issue decides whether the dependency is dropped,
moved behind an opt-in, or kept with the terms stated.

**`redis:7-alpine` is Redis 7.4, under RSALv2 or SSPLv1** -
[#1603](https://github.com/vstorm-co/agenticos/issues/1603). Neither is an
OSI-approved licence. RSALv2 permits running Redis inside your own application,
which is what the stack does, and the image is pulled by the operator rather than
redistributed here. The finding is that the default compose path starts a non-open
component without saying so; Valkey (BSD-3-Clause) is the likely replacement.

**The sandbox `workbench` runtime is built at the deployment** from
`sandbox_runtimes.json`: Python, Node, LibreOffice, `poppler-utils` (GPL) and a list
of PyPI packages resolved at build time. It is never published by this project, so
there is nothing to redistribute and the GPL tools run as separate processes. It is
recorded as `deployment-review`: a deployment that goes on to publish the built image
owes the source offers for it.

## Hosted services and provider terms

A model provider's API, Logfire, Tavily, Brave, Exa, LlamaParse, Mem0, Daytona,
Google Drive and S3 are not software this project distributes and have no licence
in the sense above. Each is a service agreement between the deployment and the
provider, entered into when an administrator stores that provider's credential in
the [vault](secrets.md). The terms that matter for a review are the provider's: what
happens to prompts and documents sent to it, whether they train on them, where the
data is processed and for how long it is kept.

That is a data-protection question rather than a licence question, and it is
answered per deployment, not here. The SDKs that talk to those services are
ordinary packages in the notices: the Anthropic, OpenAI, Google, Mistral, Cohere,
Groq and xAI clients are all MIT or Apache-2.0.

## Model weights

No model weights ship in either image. A deployment chooses models in
[model profiles](models.md); a closed model is reached through its provider's API
under that provider's terms, and an open-weights model is downloaded by the
deployment under the licence its publisher attached to it. Those licences differ
more than software licences do, and several are not open source by the OSI
definition even when the weights are freely downloadable.

| Family | Licence, as published with the weights | What to check before selecting it |
|---|---|---|
| Qwen 2.5 and 3 (most sizes), Mistral 7B and Nemo, GPT-OSS, DeepSeek V3 and R1, Phi-4 | Apache-2.0 or MIT | Attribution only. Some larger Qwen 2.5 sizes carry the Qwen licence instead; read the model card |
| Llama 3.x | Llama Community License | Not open source: an acceptable-use policy, a "Built with Llama" attribution, and a separate licence above a monthly-active-user threshold |
| Gemma | Gemma Terms of Use | Not open source: a prohibited-use policy that flows down to derivatives |
| Mistral Large and some Codestral releases | Mistral Research License or a commercial licence | Research and non-commercial use only unless licensed |

The table is orientation, not evidence: model licences change between releases and
the publisher's model card is the document that governs. The
[choosing a model](choosing-models.md#closed-models-or-open-weights) page has the
engineering side of the same decision.

!!! tip "Record the decision where the model is configured"

    A model profile's description is a good place to name the licence the weights
    were taken under and the date it was checked. It travels with the profile into
    every environment and every agent that uses it.

## Client-specific components

A deployment's own stack will add components this inventory cannot see: the model
it self-hosts, the MCP servers it connects, a managed database or Redis in place of
the compose services, a reverse proxy, an identity provider. Each needs the same
three lines the tables above have, component, licence, obligation, before the
deployment's review is complete. The compose-path defaults are recorded in
`licenses/components.toml` under `deployment-review` and `service image`, which is
where a deployment's own rows belong too, in its fork or its deployment repository.

## Keeping it true

The check runs on every pull request in the `security` job and in `make check`, so
the maintenance workflow is mostly the check refusing to pass.

**A dependency changes.** Dependabot or `make deps-upgrade` moves a lockfile; the
`security` job fails with `THIRD_PARTY_NOTICES.md is stale`. Run `make licenses`,
read the diff, commit. If the diff adds a component with no licence, or one in the
review set, the check names the policy entry to write, and the pull request carries
the decision beside the upgrade that needed it.

**A licence changes.** A component reviewed under one licence resolves to another
after an upgrade; the check says `reviewed as X but resolves to Y - review it
again`. The old decision does not survive on its own.

**A finding closes.** The policy entry moves from `open` to `accepted` with a
`fulfilled_by`, or the component is removed and the check asks for the entry to go.
Regenerate the notices; the finding leaves the top of the file.

**A model or a service changes.** Nothing in the lockfiles moves, so nothing fails.
The model table above, the model profile's description, and the deployment's own
component rows are what to update, and the release checklist is what asks.

**An image changes.** A new base tag, an added Debian package, a new compose
service: `licenses/components.toml` is edited in the same change, and
`scripts/docs_drift.py` reminds when a Dockerfile moves and this page did not.

## Release checklist

Before a release is cut, and as evidence attached to it:

- [ ] `make licenses-check` passed on the release commit; the verdict line is in the
  `security` job's summary
- [ ] `THIRD_PARTY_NOTICES.md` at that commit is the notices for the release; both
  images carry their licence files (`/app/THIRD_PARTY_NOTICES.md` and
  `.venv/**/*.dist-info/` in the backend image, `/app/licenses/` in the frontend)
- [ ] The open findings in the notices are the ones this page lists, each with an
  issue that is still the right one
- [ ] `licenses/components.toml` names the image tags and compose services the
  release actually uses
- [ ] If a model family was added to the catalog or the model table above, its
  licence was read from the current model card
- [ ] When the per-release SBOM from #1415 exists: it is attached to the release
  and its component set agrees with the notices for the two images

## Recap

- The images ship about five hundred third-party packages, almost all MIT, Apache-2.0
  or BSD; each package's licence file travels with it and
  `THIRD_PARTY_NOTICES.md` is the generated index.
- Decisions live in `licenses/policy.toml` and `licenses/components.toml`; the check
  fails on anything without one, and on a decision made about a licence that has
  since changed.
- Three findings are open and tracked: PyMuPDF's AGPL, the Redis image's RSALv2/SSPL
  terms, and the sandbox runtime built at the deployment.
- Model weights and hosted providers are chosen per deployment under the
  publisher's or provider's terms; this page says what to check, the deployment
  records what it chose.
