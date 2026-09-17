# The component inventory

What a deployment of AgenticOS is made of: the parts this project writes, the
third-party packages those parts depend on, the images they run in, the assets
they ship, and the models and services an operator connects afterwards. It is
the readable half of the release SBOM, and the answer to "what is in it" when
that question arrives from a security review rather than from a build system.

!!! abstract "What this page covers, and where it stops"

    Everything through *Bundled assets* below is shipped by this project and is
    enumerated exactly, from the lockfiles and the Dockerfiles. Everything after
    it — the models, the providers, the MCP servers, the databases an operator
    points the deployment at — is chosen per deployment, is not shipped here,
    and can only be listed by the deployment that chose it. The last section is
    how to write that half down; this page cannot write it for you.

The machine-readable inventory is attached to every release as four
[CycloneDX](https://cyclonedx.org/) documents — one per image **per
architecture**, because a published tag is a manifest list and the two variants
do not contain the same packages. Licence evidence for every
component is in
[`THIRD_PARTY_NOTICES.md`](https://github.com/vstorm-co/agenticos/blob/main/THIRD_PARTY_NOTICES.md),
and the review of what those licences oblige is [Licences and third-party
notices](../licenses.md).

## The release this inventory describes

An inventory with no version on it describes nothing. Each release carries its
own: the SBOM documents on the GitHub release for tag `vX.Y.Z`, generated from
the images published under that tag, and this page as it stood in that tag's
tree. A deployment reading the inventory for the version it runs should read
both from the same tag rather than from `main`.

| Artifact | Where it is | What names its version |
|---|---|---|
| `sbom-api-amd64.cdx.json`, `sbom-api-arm64.cdx.json` | the GitHub release assets | the `v*` tag they are attached to |
| `sbom-frontend-amd64.cdx.json`, `sbom-frontend-arm64.cdx.json` | the GitHub release assets | the same |
| `ghcr.io/vstorm-co/agenticos-backend` | GHCR | `<version>`, `latest`, `edge`, `sha-<short>` |
| `ghcr.io/vstorm-co/agenticos-frontend` | GHCR | the same |
| `THIRD_PARTY_NOTICES.md` | the repository, at that tag | the lockfiles at that commit |

## Components this project writes

Self-developed, Apache-2.0, in this repository. Nothing here is a third-party
component and none of it appears in the third-party notices.

| Component | Where | What it is | Shipped in |
|---|---|---|---|
| API and platform | `backend/app` | The FastAPI application: routes, services, repositories, the agent runner, the capability registry | `agenticos-backend` |
| Background worker | `backend/app/worker` | The Prefect runner for ingestion, syncs, sweeps and scheduled triggers | `agenticos-backend` |
| Migrations | `backend/alembic` | The schema chain, applied by the migration service before the API starts | `agenticos-backend` |
| Command line | `backend/app/commands` | `agenticos cmd …` — bootstrap, doctor, the RAG commands | `agenticos-backend` |
| Console | `frontend/src` | The Next.js application an operator and a user meet | `agenticos-frontend` |
| Desktop shell | `desktop/` | A Tauri window around a deployment's console, built per platform | not an image; see [the desktop app](../desktop.md) |
| Documentation site | `docs/`, `mkdocs.yml` | This site | not shipped in either image |

## Third-party dependencies

Resolved from lockfiles, not from what a machine happens to have installed. The
counts move with every dependency change, so the figure to trust is the one in
the notices file at the release you are reading.

| Set | Lockfile | Resolved for | In the notices |
|---|---|---|---|
| Backend Python distributions | `backend/uv.lock` | Linux, both architectures, `--no-dev` | Yes |
| Frontend npm packages | `frontend/bun.lock` | the production closure of `frontend/package.json` | Yes |
| Backend development and documentation tooling | `backend/uv.lock`, the `dev` and `docs` groups | the contributor's machine | No: not in either image |
| Frontend `devDependencies` | `frontend/bun.lock` | the contributor's machine | No: not in the image |
| Desktop Rust crates | `desktop/src-tauri/Cargo.lock` | the platform the shell is built for | No: not in either image |

Two audits read these lockfiles on every pull request. `make audit` resolves
`backend/uv.lock` and checks it against the advisory database;
`make audit-frontend` runs `bun audit --audit-level=high` over `frontend/bun.lock`.
Both are in the `Security Scan` job and in `make check`.

## Runtime images

| Image | Base | Contains | Built by |
|---|---|---|---|
| `agenticos-backend` | a Debian-based Python image | the API, the worker, the migrations, the CLI, the backend dependency closure, the licence texts | `backend/Dockerfile` |
| `agenticos-frontend` | a Debian-based Node image | the console's standalone build, its production dependency closure, the fonts, the per-package notices | `frontend/Dockerfile` |

Both are built for `amd64` and `arm64`, published to GHCR, and scanned with
Trivy after publication. The Debian packages each image installs are recorded in
`licenses/components.toml` with their licence position, and appear in the
CycloneDX documents because the generator reads the published image rather than
the source tree.

Services a deployment runs beside these two — PostgreSQL with pgvector, Redis, a
reverse proxy, a Prefect server — are pulled by the operator from their own
publishers. They are named in the compose files, they are not built here, and
they are not in this project's SBOM.

## Bundled assets

| Asset | Where | Provenance |
|---|---|---|
| Interface fonts | `frontend/src/app/fonts/` | Inter, Bricolage Grotesque, Geist Mono, all OFL-1.1 |
| Brand and provider glyphs | `frontend/src/components/brand/`, `backend/app/core/catalog/icons/` | Font Awesome, Simple Icons and hand-drawn marks; the sources are named in `NOTICE` |
| The MCP server catalog | `backend/app/core/catalog/` | This project's own data about third-party servers, not the servers |
| Model profile defaults | `backend/app/core/catalog/` | This project's own data; the models themselves are never shipped |

## Models, providers and services: the deployment's half

None of the following is part of a release, and no SBOM generated here can list
it. Each is a component of the running system and belongs in the deployment's own
inventory.

- **Model providers.** Whichever of Anthropic, OpenAI, Google, Groq, xAI, Cohere,
  an OpenAI-compatible endpoint or a local runtime the deployment configures, with
  the model identifiers it pins. See [models](../models.md).
- **Model weights.** A local runtime downloads them; their licences are the
  operator's to review, and [the licence review](../licenses.md) says why.
- **MCP servers.** Third-party processes or hosted endpoints, connected per
  organization. The catalog names candidates; an installation is a component.
- **Knowledge sources and connectors.** Google Drive, S3 and the rest, each a
  third-party service reached with a credential in the vault.
- **Channels.** Slack, Telegram and Mattermost workspaces the deployment is
  registered with.
- **Data stores and infrastructure.** PostgreSQL, Redis, object storage, the
  reverse proxy, the host, and whatever observability endpoint receives traces.

!!! warning "An image SBOM is not a system inventory"

    The two CycloneDX documents describe two images. A deployment that connects a
    hosted model, three MCP servers and an object store is running components no
    scan of those images can see. Treating the release SBOM as the whole
    inventory is the gap this section exists to name.

## How the inventory is produced and kept current

| Artifact | Produced by | When |
|---|---|---|
| The four release SBOMs | the `sbom` job in `.github/workflows/images.yml`, one per image per architecture, from the published manifests | every publish; attached to the release on a `v*` tag, kept as a run artifact otherwise |
| `THIRD_PARTY_NOTICES.md` | `make licenses` | whenever a lockfile changes; `make licenses-check` fails the build when it is stale |
| This page | by hand | whenever a component is added, removed or moved between the sets above |

`make sbom` writes something else, and the names say so:
`sbom-source-api.cdx.json` and `sbom-source-frontend.cdx.json` are inventories of
what the **source tree declares**, not of what an image contains. They carry the
development and documentation dependency groups if those are installed, and none
of the layers underneath — no base image, no Debian packages, no built
artifacts. Useful for reading a dependency set without pulling two images;
useless as evidence of what a release ships, which is what the four documents
above are for. It needs [syft](https://github.com/anchore/syft) installed and is
deliberately not part of `make check`.

To extend the inventory for a deployment, take the release SBOM for the version
you run, add the components from the section above with the version and the
provider of each, and keep it beside the deployment's own configuration. The
[security review](../rollout.md) is where a client's reviewer asks for it, and
[data protection](../data-protection.md) is where the data each of those
components touches is written down.
