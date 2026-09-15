---
source_sha: "d68ab617b471"
---

# Das Komponenteninventar { #the-component-inventory }

Woraus ein Deployment von AgenticOS besteht: die Teile, die dieses Projekt
schreibt, die Drittanbieter-Pakete, von denen sie abhängen, die Images, in denen
sie laufen, die Assets, die sie mitliefern, und die Modelle und Dienste, die ein
Betreiber danach anschließt. Es ist die lesbare Hälfte des Release-SBOM und die
Antwort auf „was ist darin", wenn diese Frage aus einem Sicherheits-Review kommt
und nicht aus einem Build-System.

!!! abstract "Was diese Seite abdeckt und wo sie aufhört"

    Alles bis einschließlich *Mitgelieferte Assets* wird von diesem Projekt
    ausgeliefert und ist exakt aufgezählt — aus den Lockfiles und den
    Dockerfiles. Alles danach — die Modelle, die Provider, die MCP-Server, die
    Datenbanken, auf die ein Betreiber das Deployment zeigen lässt — wird pro
    Deployment gewählt, wird hier nicht ausgeliefert und kann nur von dem
    Deployment aufgelistet werden, das es gewählt hat. Der letzte Abschnitt sagt,
    wie man diese Hälfte aufschreibt; diese Seite kann es nicht für Sie tun.

Das maschinenlesbare Inventar hängt an jedem Release als vier
[CycloneDX](https://cyclonedx.org/)-Dokumente — eines pro Image **pro
Architektur**, denn ein veröffentlichter Tag ist eine Manifest-Liste, und die
beiden Varianten enthalten nicht dieselben Pakete. Die
Lizenznachweise für jede Komponente stehen in
[`THIRD_PARTY_NOTICES.md`](https://github.com/vstorm-co/agenticos/blob/main/THIRD_PARTY_NOTICES.md),
und die Prüfung dessen, wozu diese Lizenzen verpflichten, in [Lizenzen und
Drittanbieter-Hinweise](../licenses.md).

## Das Release, das dieses Inventar beschreibt { #the-release-this-inventory-describes }

Ein Inventar ohne Version beschreibt nichts. Jedes Release trägt seine eigene:
die SBOM-Dokumente am GitHub-Release für den Tag `vX.Y.Z`, erzeugt aus den unter
diesem Tag veröffentlichten Images, und diese Seite so, wie sie im Baum dieses
Tags stand. Ein Deployment, das das Inventar für die von ihm ausgeführte Version
liest, sollte beides aus demselben Tag lesen und nicht aus `main`.

| Artefakt | Wo es liegt | Was seine Version benennt |
|---|---|---|
| `sbom-api-amd64.cdx.json`, `sbom-api-arm64.cdx.json` | die Assets des GitHub-Releases | der `v*`-Tag, an dem sie hängen |
| `sbom-frontend-amd64.cdx.json`, `sbom-frontend-arm64.cdx.json` | dieselben | dasselbe |
| `ghcr.io/vstorm-co/agenticos-backend` | GHCR | `<version>`, `latest`, `edge`, `sha-<short>` |
| `ghcr.io/vstorm-co/agenticos-frontend` | GHCR | dasselbe |
| `THIRD_PARTY_NOTICES.md` | das Repository, an diesem Tag | die Lockfiles in diesem Commit |

## Komponenten, die dieses Projekt schreibt { #components-this-project-writes }

Selbst entwickelt, Apache-2.0, in diesem Repository. Nichts hiervon ist eine
Drittanbieter-Komponente und nichts davon erscheint in den Hinweisen.

| Komponente | Wo | Was sie ist | Ausgeliefert in |
|---|---|---|---|
| API und Plattform | `backend/app` | Die FastAPI-Anwendung: Routes, Services, Repositories, der Runner für Agents, die Capability-Registry | `agenticos-backend` |
| Hintergrund-Worker | `backend/app/worker` | Der Prefect-Runner für Ingestion, Syncs, Sweeps und geplante Trigger | `agenticos-backend` |
| Migrationen | `backend/alembic` | Die Schema-Kette, angewandt vom Migrationsdienst bevor die API startet | `agenticos-backend` |
| Kommandozeile | `backend/app/commands` | `agenticos cmd …` — Bootstrap, Doctor, die RAG-Befehle | `agenticos-backend` |
| Konsole | `frontend/src` | Die Next.js-Anwendung, die ein Betreiber und ein Benutzer sehen | `agenticos-frontend` |
| Desktop-Shell | `desktop/` | Ein Tauri-Fenster um die Konsole eines Deployments, pro Plattform gebaut | kein Image; siehe [die Desktop-App](../desktop.md) |
| Dokumentationsseite | `docs/`, `mkdocs.yml` | Diese Seite | in keinem der beiden Images ausgeliefert |

## Drittanbieter-Abhängigkeiten { #third-party-dependencies }

Aus Lockfiles aufgelöst, nicht aus dem, was eine Maschine zufällig installiert
hat. Die Zahlen bewegen sich mit jeder Abhängigkeitsänderung, also ist die Zahl,
der zu trauen ist, die in der Hinweisdatei des Releases, das Sie lesen.

| Menge | Lockfile | Aufgelöst für | In den Hinweisen |
|---|---|---|---|
| Python-Distributionen des Backends | `backend/uv.lock` | Linux, beide Architekturen, `--no-dev` | Ja |
| npm-Pakete des Frontends | `frontend/bun.lock` | die Produktionshülle von `frontend/package.json` | Ja |
| Entwicklungs- und Dokumentationswerkzeuge des Backends | `backend/uv.lock`, die Gruppen `dev` und `docs` | die Maschine des Beitragenden | Nein: in keinem Image |
| `devDependencies` des Frontends | `frontend/bun.lock` | die Maschine des Beitragenden | Nein: nicht im Image |
| Rust-Crates der Desktop-Shell | `desktop/src-tauri/Cargo.lock` | die Plattform, für die die Shell gebaut wird | Nein: in keinem Image |

Zwei Audits lesen diese Lockfiles bei jedem Pull Request. `make audit` löst
`backend/uv.lock` auf und prüft es gegen die Advisory-Datenbank;
`make audit-frontend` führt `bun audit --audit-level=high` über
`frontend/bun.lock` aus. Beide stehen im Job `Security Scan` und in `make check`.

## Laufzeit-Images { #runtime-images }

| Image | Basis | Enthält | Gebaut von |
|---|---|---|---|
| `agenticos-backend` | ein Debian-basiertes Python-Image | die API, den Worker, die Migrationen, die CLI, die Abhängigkeitshülle des Backends, die Lizenztexte | `backend/Dockerfile` |
| `agenticos-frontend` | ein Debian-basiertes Node-Image | den Standalone-Build der Konsole, seine Produktionshülle, die Schriften, die Hinweise pro Paket | `frontend/Dockerfile` |

Beide werden für `amd64` und `arm64` gebaut, nach GHCR veröffentlicht und nach
der Veröffentlichung mit Trivy gescannt. Die Debian-Pakete, die jedes Image
installiert, stehen mit ihrer Lizenzlage in `licenses/components.toml` und
erscheinen in den CycloneDX-Dokumenten, weil der Generator das veröffentlichte
Image liest und nicht den Quellbaum.

Dienste, die ein Deployment neben diesen beiden betreibt — PostgreSQL mit
pgvector, Redis, ein Reverse Proxy, ein Prefect-Server — zieht der Betreiber von
deren eigenen Herausgebern. Sie sind in den Compose-Dateien benannt, werden hier
nicht gebaut und stehen nicht im SBOM dieses Projekts.

## Mitgelieferte Assets { #bundled-assets }

| Asset | Wo | Herkunft |
|---|---|---|
| Schriften der Oberfläche | `frontend/src/app/fonts/` | Inter, Bricolage Grotesque, Geist Mono, alle OFL-1.1 |
| Marken- und Provider-Glyphen | `frontend/src/components/brand/`, `backend/app/core/catalog/icons/` | Font Awesome, Simple Icons und selbst gezeichnete Zeichen; die Quellen benennt `NOTICE` |
| Der MCP-Server-Katalog | `backend/app/core/catalog/` | Eigene Daten dieses Projekts über Drittanbieter-Server, nicht die Server selbst |
| Voreinstellungen der Modellprofile | `backend/app/core/catalog/` | Eigene Daten dieses Projekts; die Modelle selbst werden nie ausgeliefert |

## Modelle, Provider und Dienste: die Hälfte des Deployments { #models-providers-and-services-the-deployments-half }

Nichts hiervon ist Teil eines Releases, und kein hier erzeugtes SBOM kann es
auflisten. Jeder Punkt ist eine Komponente des laufenden Systems und gehört in
das eigene Inventar des Deployments.

- **Modell-Provider.** Diejenigen von Anthropic, OpenAI, Google, Groq, xAI,
  Cohere, einem OpenAI-kompatiblen Endpunkt oder einer lokalen Laufzeit, die das
  Deployment konfiguriert, mit den Modellkennungen, die es festschreibt. Siehe
  [Modelle](../models.md).
- **Modellgewichte.** Eine lokale Laufzeit lädt sie herunter; ihre Lizenzen zu
  prüfen ist Sache des Betreibers, und [die Lizenzprüfung](../licenses.md) sagt
  warum.
- **MCP-Server.** Prozesse von Drittanbietern oder gehostete Endpunkte, pro
  Organisation angeschlossen. Der Katalog benennt Kandidaten; eine Installation
  ist eine Komponente.
- **Wissensquellen und Konnektoren.** Google Drive, S3 und der Rest, jeweils ein
  Drittanbieter-Dienst, der mit einem Secret im Vault erreicht wird.
- **Kanäle.** Slack-, Telegram- und Mattermost-Workspaces, bei denen das
  Deployment registriert ist.
- **Datenspeicher und Infrastruktur.** PostgreSQL, Redis, Objektspeicher, der
  Reverse Proxy, der Host und welcher Observability-Endpunkt auch immer Traces
  empfängt.

!!! warning "Ein Image-SBOM ist kein Systeminventar"

    Die beiden CycloneDX-Dokumente beschreiben zwei Images. Ein Deployment, das
    ein gehostetes Modell, drei MCP-Server und einen Objektspeicher anschließt,
    betreibt Komponenten, die kein Scan dieser Images sehen kann. Das
    Release-SBOM für das ganze Inventar zu halten ist die Lücke, die dieser
    Abschnitt benennen soll.

## Wie das Inventar entsteht und aktuell bleibt { #how-the-inventory-is-produced-and-kept-current }

| Artefakt | Erzeugt von | Wann |
|---|---|---|
| Die vier Release-SBOMs | dem Job `sbom` in `.github/workflows/images.yml`, eines pro Image pro Architektur, aus den veröffentlichten Manifesten | bei jeder Veröffentlichung; bei einem `v*`-Tag an das Release angehängt, sonst als Lauf-Artefakt |
| `THIRD_PARTY_NOTICES.md` | `make licenses` | wann immer sich ein Lockfile ändert; `make licenses-check` lässt den Build scheitern, wenn es veraltet ist |
| Diese Seite | von Hand | wann immer eine Komponente hinzukommt, entfällt oder zwischen den obigen Mengen wechselt |

`make sbom` schreibt etwas anderes, und die Namen sagen das:
`sbom-source-api.cdx.json` und `sbom-source-frontend.cdx.json` sind Inventare
dessen, was der **Quellbaum deklariert**, nicht dessen, was ein Image enthält.
Sie tragen die Entwicklungs- und Dokumentations-Abhängigkeitsgruppen, sofern
installiert, und keine der Schichten darunter — kein Basis-Image, keine
Debian-Pakete, keine gebauten Artefakte. Nützlich, um einen Abhängigkeitssatz zu
lesen, ohne zwei Images zu ziehen; nutzlos als Beleg dafür, was ein Release
ausliefert — dafür sind die vier Dokumente oben da. Es braucht ein installiertes
[syft](https://github.com/anchore/syft) und gehört bewusst nicht zu
`make check`.

Um das Inventar für ein Deployment zu erweitern, nehmen Sie das Release-SBOM für
die Version, die Sie betreiben, ergänzen die Komponenten aus dem obigen Abschnitt
mit Version und Anbieter und halten das neben der eigenen Konfiguration des
Deployments. Das [Sicherheits-Review](../rollout.md) ist der Ort, an dem der
Prüfer eines Kunden danach fragt, und [Datenschutz](../data-protection.md) der
Ort, an dem die Daten aufgeschrieben sind, die jede dieser Komponenten berührt.
