---
source_sha: "097a2caa4c8d"
---

# Lizenzen und Drittanbieter-Hinweise { #licences-and-third-party-notices }

!!! abstract "Was diese Seite behauptet, und was sie nicht behauptet"

    Jede Komponente, die die beiden veröffentlichten Images enthalten, ist mit
    ihrer Lizenz und dem Nachweis dafür aufgeführt; jede Pflicht, die diese
    Lizenzen auferlegen, ist entweder auf eine Weise erfüllt, die diese Seite
    benennt, oder als offener Befund mit einem Issue dahinter festgehalten. Sie
    sagt nicht "alle Lizenzen sind konform": Zum Zeitpunkt des Schreibens ist ein
    Befund offen, und er steht unten, statt weggemittelt zu werden. Zwei weitere
    wurden geprüft und abgeschlossen - die AGPL-Komponente, die einen eigenen
    Abschnitt hat, und das Redis-Image, das ersetzt wurde.

AgenticOS selbst ist Apache-2.0 (`LICENSE`, `NOTICE`). Was ein Deployment
tatsächlich ausführt, ist dieser Code plus rund fünfhundert Drittanbieter-Pakete,
zwei Debian-basierte Images, eine Handvoll Fonts und Icons sowie alle Dienste und
Modelle, die das Deployment anbindet. Diese Seite ist die Prüfung all dessen: was
im Umfang liegt, wie das Inventar entsteht, was jede Lizenzfamilie verlangt und
wie das beantwortet wird, und was zu tun ist, wenn sich eine Abhängigkeit oder ein
Modell ändert.

## Was im Umfang liegt { #what-is-in-scope }

| Schicht | Woher das Inventar stammt | Von diesem Projekt ausgeliefert? |
|---|---|---|
| Python-Distributionen des Backends | `backend/uv.lock`, für Linux aufgelöst mit `uv export --no-dev` | Ja, in `agenticos-backend` |
| npm-Pakete des Frontends | die Produktionshülle von `frontend/package.json`, aus `frontend/bun.lock` | Ja, in `agenticos-frontend` |
| Base-Images und die Debian-Pakete, die das Backend-Image installiert | `backend/Dockerfile`, `frontend/Dockerfile` | Ja, als Layer beider Images |
| Fonts, Marken-Glyphen, mitgelieferte Datendateien | `frontend/src/app/fonts/`, `NOTICE`, `backend/app/core/catalog/` | Ja |
| Service-Images, die ein Deployment neben den beiden obigen betreibt | die Compose-Dateien | Nein: vom Betreiber gezogen |
| Modellgewichte | pro Deployment in einem Modellprofil gewählt | Nein: werden nie ausgeliefert |
| Gehostete Provider und Dienste | pro Deployment mit Zugangsdaten im Vault konfiguriert | Nein: ein Vertrag zwischen dem Deployment und dem Provider |

Werkzeuge für Entwicklung und Dokumentation (`uv sync --dev`, die
Dependency-Gruppe `docs`, `devDependencies`) stecken weder in den Images noch in
den Notices. Build-Werkzeuge, die in einer Builder-Stage laufen und in der
finalen Schicht fehlen, etwa `uv`, sind in `licenses/components.toml` als nicht
ausgeliefert festgehalten.

## Das Inventar { #the-inventory }

Zwei Dateien tragen es, und ein Skript hält sie ehrlich.

**[`THIRD_PARTY_NOTICES.md`](https://github.com/vstorm-co/agenticos/blob/main/THIRD_PARTY_NOTICES.md)**
wird generiert und eingecheckt. Für jede Distribution in einem der beiden Images
hält die Datei Namen, Version, SPDX-Lizenzausdruck, Quell-URL und den Nachweis
fest, aus dem die Lizenz gelesen wurde: einen `License-Expression`-Header, einen
Classifier, den Text der Lizenzdatei selbst, den Paketindex oder ein Override, das
jemand festgehalten hat. Sie listet außerdem die offenen Befunde zuerst, eine Zahl
der Komponenten pro Lizenz und die von Hand erfassten Komponenten.

**`licenses/policy.toml`** hält die Entscheidungen. Ein `override`-Eintrag ist die
Lizenz, die jemand für eine Komponente bestimmt hat, deren Metadaten dazu
schweigen, samt dem Nachweis, den er gelesen hat; er gilt nur, solange die
Metadaten schweigen. Ein `notices`-Eintrag ist der Rechteinhaber eines Pakets ohne
Lizenzdatei und ohne genannten Autor. Ein `review`-Eintrag ist die Entscheidung
für eine Komponente unter einer Copyleft-, Share-alike- oder nicht offenen Lizenz:
`accepted`, das sagt, wie die Pflicht erfüllt wird, oder `open`, das auf das Issue
verweist, dem sie gehört. **`licenses/components.toml`** hält fest, was kein
Lockfile weiß: die Images, die Debian-Pakete, die Fonts, die Glyphen, die
Datendateien und die Service-Images, jeweils mit Status und Pflicht.

`scripts/license_inventory.py` liest alle drei. `make licenses` generiert die
Notices neu; `make licenses-check`, das der `security`-Job und `make check`
ausführen, generiert sie im Speicher neu und schlägt fehl, wenn:

- die eingecheckten Notices von dem abweichen, worauf die Lockfiles jetzt
  auflösen, in irgendeiner Komponente, Version, Lizenz oder Quelle (die
  Nachweis-Zelle wird nicht verglichen: Zwei Wheels eines Releases können
  unterschiedliche Metadaten tragen, und sie hält fest, woher diese Maschine die
  Lizenz gelesen hat);
- die Metadaten einer Komponente keine Lizenz nennen und kein Override eine
  festhält, oder ein Override für eine Komponente festgehalten ist, deren
  Metadaten jetzt doch eine nennen;
- ein Paket keine Lizenzdatei ausliefert und entweder keinen Autor nennt (und
  kein `notices`-Eintrag den Rechteinhaber festhält) oder eine Lizenz angibt, zu
  der es unter `frontend/licenses/texts/` keinen Text gibt;
- eine Komponente unter einer Lizenz aus dem Review-Set steht und keine
  Entscheidung hat;
- eine Entscheidung über eine andere Lizenz getroffen wurde als die, die die
  Komponente jetzt trägt, weil ein Upgrade sie geändert hat;
- eine Entscheidung eine Komponente nennt, auf die die Lockfiles nicht mehr
  auflösen.

Ein offener Befund, der verfolgt wird, lässt die Prüfung nicht fehlschlagen. Die
Urteilszeile zählt ihn mit:
`LICENSES: REVIEWED - 518 components, 1 open finding(s)`.

!!! warning "Das Unbekannte eines Scanners ist eine Frage, keine Freigabe"

    Das Skript rät nie. Ein nacktes `BSD` in einem `License`-Feld wird nicht durch
    Annahme auf eine Klauselzahl aufgelöst; die Lizenzdatei entscheidet, und ist
    auch die unlesbar, schlägt die Prüfung fehl, bis jemand sie liest und die
    Antwort aufschreibt. Die Nachweis-Spalte in den Notices ist das, was einem
    Prüfer erlaubt, eine erklärte Lizenz von einer erschlossenen zu unterscheiden.

Das Inventar ist das, was ein Deployment installiert, nicht das, was die Maschine
hat, auf der das Skript läuft. Environment-Marker werden für Linux auf beiden
Architekturen ausgewertet, für die die Images gebaut werden, plattformspezifische
npm-Pakete werden nur behalten, wenn sie für Linux-glibc auf x64 oder arm64
bauen, und bei einem Paket, das der Maschine fehlt, werden die Metadaten von PyPI
oder aus der npm-Registry gelesen. Ein fehlgeschlagener Abruf ist ein Fehlschlag
des Laufs.

## Was die Lizenzen verlangen, und wie das beantwortet wird { #what-the-licences-ask-and-how-it-is-answered }

Die Zahlen unten stammen aus den Notices zum Zeitpunkt des Schreibens; die
Notices-Datei ist die aktuelle Zahl.

| Lizenzfamilie | Komponenten | Pflicht | Wie sie erfüllt wird |
|---|---|---|---|
| MIT, ISC, BSD-2-Clause, BSD-3-Clause, 0BSD, MIT-0, MIT-CMU, Unlicense | rund 400 | Copyright-Hinweis und Lizenztext bei Kopien mitführen | Die eigene Lizenzdatei jedes Pakets wird im Image neben dem Code ausgeliefert: das `*.dist-info/` jedes Wheels im Backend-Image, die Lizenzdatei jedes Pakets unter `/app/licenses/node_modules/<name>/` im Frontend-Image. Die Notices indexieren sie |
| Apache-2.0 | rund 90 | Der Lizenztext, ein Hinweis auf Änderungen, jede `NOTICE`-Datei, die das Paket mitführt | Wie oben; nichts wird verändert, es gibt also keine Änderungen, auf die hinzuweisen wäre |
| PSF-2.0, CNRI-Python, Zlib, CC0-1.0 | ein paar | Namensnennung oder nichts | Wie oben |
| MPL-2.0 (`certifi`, `pathspec`, `tqdm`, Teil von `orjson`) | 4 | Copyleft auf Dateiebene: Die erfassten Dateien bleiben unter der MPL, und ihr Quellcode ist verfügbar | Unverändert genutzt; der Lizenztext wird ausgeliefert; die Notices verlinken den Quellcode |
| LGPL-3.0-or-later (`psycopg2-binary`, `@img/sharp-libvips-linux-*`) | 3 | Lizenztext, Verfügbarkeit des Quellcodes und die Möglichkeit, die Bibliothek zu ersetzen | Beide sind separat installierte Binaries, dynamisch geladen, unverändert, durch Neuinstallation ersetzbar; die Quellen sind in den Notices verlinkt. Die libvips-Pakete veröffentlichen keine Lizenzdatei, deshalb legt das Image den LGPL-Text daneben |
| Artistic-1.0-Perl oder GPL-2.0-or-later (`text-unidecode`) | 1 | Dual; unter der Artistic License genommen: Hinweis und Text | Die Lizenzdatei des Wheels wird ausgeliefert |
| CC-BY-4.0 (`caniuse-lite`) | 1 | Namensnennung und ein Link auf die Quelle | In den Notices mit seiner Quelle genannt |
| AGPL-3.0-only (`pymupdf`) | 1 | Netzwerk-Copyleft: Das Image wird unter AGPL-3.0-Bedingungen weitergegeben, und ein verändertes Deployment schuldet seinen Nutzern den veränderten Quellcode (Abschnitt 13) | Bewusst behalten, Bedingungen benannt: [der Abschnitt unten](#the-agpl-component) und das `COPYING` des Wheels im Image |
| OFL-1.1 (Inter, Bricolage Grotesque, Geist Mono) | 3 Familien | Lizenztext und Copyright-Hinweise bei den Fonts; kein Verkauf der Fonts für sich allein; keine Wiederverwendung der reservierten Namen für veränderte Fonts | `frontend/src/app/fonts/OFL.txt` trägt alle drei Hinweise; die Fonts werden unverändert ausgeliefert |
| CC0-1.0, CC-BY-4.0, MIT (Marken-Glyphen) | 3 Quellen | Namensnennung für die Font-Awesome-Icons; die Marken bleiben Marken ihrer Inhaber | `NOTICE` nennt die Quellen und die markenrechtliche Position |

**Von einem Paket, das keine Lizenzdatei veröffentlicht**, lässt sich keine
kopieren. Mehrere npm-Pakete in der Hülle sind so, darunter
`@img/sharp-libvips-linux-x64` und sein arm64-Zwilling: eine LGPL-Bibliothek ohne
Kopie der LGPL im Tarball. Ebenso neun Wheels, darunter `tokenizers` und
`liteparse`. Für jedes npm-Paket schreibt
`frontend/scripts/collect-licenses.ts` ein `NOTICE`, das Paket, erklärte Lizenz,
Autor und Repository nennt, und kopiert den Text jeder Lizenz aus seinem Ausdruck
aus `frontend/licenses/texts/`. Das Backend-Image trägt dieselben Texte unter
`/app/licenses/texts/`, und das `METADATA` jedes Wheels nennt Lizenz und Autor
bereits. Eine Lizenz, zu der es dort keinen Text gibt, lässt den Build des
Frontend-Images fehlschlagen, und `make licenses-check` schlägt für beide Images
früher fehl, am Pull Request. Bei einem Paket, das auch keinen Autor nennt,
`client-only`, ist der Rechteinhaber in `licenses/policy.toml` unter `notices`
festgehalten, samt Nachweis, und die Notices-Datei trägt ihn.

Die Base-Images verdienen einen eigenen Satz. `python:3.12-slim` und `oven/bun:1`
sind Debian, was Hunderte Pakete unter GPL-, LGPL-, MIT- und BSD-Bedingungen
bedeutet. Debian legt die Lizenz jedes Pakets unter
`/usr/share/doc/<package>/copyright` im Image ab und veröffentlicht den
zugehörigen Quellcode zu jedem Binary, das es ausliefert - darauf ruht die
Quellcode-Pflicht von GPL und LGPL für ein weitergegebenes Image. Das
Backend-Image ergänzt LibreOffice (MPL-2.0) und Tesseract (Apache-2.0) als
Debian-Pakete, unverändert genutzt als separate Prozesse. Das in
[#1415](https://github.com/vstorm-co/agenticos/issues/1415) geplante SBOM pro
Release wird den genauen Paketsatz jedes Images festhalten; bis es kommt, sind
die Dockerfiles und die Digests der Base-Images das Inventar dieser Schicht.

## Die AGPL-Komponente { #the-agpl-component }

Eine Komponente im Backend-Image steht unter einem Netzwerk-Copyleft, und sie
trägt die einzige Lizenz im Satz, die etwas von einem Deployment verlangt statt
nur von uns.

`pymupdf` ist dual lizenziert, AGPL-3.0-only oder eine kommerzielle
Artifex-Lizenz. Er ist der voreingestellte PDF-Parser und der einzige der drei,
der eingebettete Bilder zur Beschreibung extrahiert. Die AGPL ist in eine
Richtung mit Apache-2.0 kompatibel: Unser Code darf mit ihr kombiniert werden,
und das entstehende Image wird dann unter AGPL-3.0-Bedingungen weitergegeben.

[#1602](https://github.com/vstorm-co/agenticos/issues/1602) hat abgewogen, ihn
zugunsten von LiteParse (Apache-2.0, ohnehin eine Abhängigkeit) fallen zu lassen,
ihn hinter ein Opt-in zu legen oder ihn mit benannten Bedingungen zu behalten.
**Er wird behalten, und die Bedingungen stehen hier.** Was das in der Praxis
bedeutet:

- **Ein unverändertes Release betreiben.** Es ist nichts geschuldet. AgenticOS ist
  öffentlich und Apache-2.0, der Quellcode, auf den ein Angebot nach Abschnitt 13
  zeigen würde, ist also bereits veröffentlicht.
- **Die Plattform verändern und über ein Netzwerk ausliefern** - der Fall, zu dem
  ein selbst gehostetes Produkt einlädt. AGPL-3.0 Abschnitt 13 verpflichtet dieses
  Deployment, seinen Nutzern den veränderten Quellcode des Ganzen anzubieten. Das
  ist die Pflicht, die man liest, bevor man privat forkt, und die, nach der eine
  Sicherheitsprüfung fragen wird.
- **Ein Deployment, das diese Bedingungen nicht tragen kann,** hat drei Auswege:
  die kommerzielle Artifex-Lizenz kaufen, den PDF-Parser der Collection auf
  `liteparse` setzen und die Abhängigkeit in einem privaten Build entfernen, oder
  seine Änderungen unveröffentlicht, aber für seine eigenen Nutzer verfügbar
  halten - was Abschnitt 13 tatsächlich verlangt.

Sonst trägt nichts in einem der beiden Images ein Copyleft, das über die eigenen
Dateien hinausreicht.

## Offene Befunde { #open-findings }

Zu jedem gibt es ein Issue; jeder bleibt in dieser Liste und zuoberst in den
Notices, bis das Issue schließt und der Policy-Eintrag auf `accepted` wechselt
oder die Komponente verschwunden ist.

Ein Befund wurde geschlossen, indem die Komponente ersetzt statt akzeptiert wurde.
`redis:7-alpine` löst auf Redis 7.4 auf, und ab 7.4.0 steht Redis unter RSALv2 oder
SSPL-1.0 statt unter BSD-3-Clause - keine von beiden ist OSI-anerkannt. Gebrochen
wurde dadurch nichts: Das Image wird vom Betreiber gezogen statt hier
weitergegeben, und RSALv2 erlaubt es, Redis innerhalb der eigenen Anwendung zu
betreiben - genau das tut dieser Stack. Der Befund war, dass das voreingestellte
`docker compose up` eine nicht offene Komponente startete, ohne das zu sagen.
[#1603](https://github.com/vstorm-co/agenticos/issues/1603) hat es gegen
`valkey/valkey:8-alpine` getauscht, den Linux-Foundation-Fork von Redis 7.2 unter
BSD-3-Clause. Valkey spricht dasselbe Protokoll, sodass der Dienstname, der Port,
das `redis://`-URL-Schema und jede `REDIS_*`-Einstellung unverändert bleiben.

**Die Sandbox-Runtime `workbench` wird beim Deployment gebaut**, aus
`sandbox_runtimes.json`: Python, Node, LibreOffice, `poppler-utils` (GPL) und eine
Liste von PyPI-Paketen, die zur Build-Zeit aufgelöst wird. Sie wird von diesem
Projekt nie veröffentlicht, es gibt also nichts weiterzugeben, und die
GPL-Werkzeuge laufen als separate Prozesse. Sie ist als `deployment-review`
festgehalten: Ein Deployment, das das gebaute Image dann doch veröffentlicht,
schuldet die Quellcode-Angebote dafür.

## Gehostete Dienste und Provider-Bedingungen { #hosted-services-and-provider-terms }

Die API eines Modell-Providers, Logfire, Tavily, Brave, Exa, LlamaParse, Mem0,
Daytona, Google Drive und S3 sind keine Software, die dieses Projekt ausliefert,
und haben keine Lizenz im obigen Sinne. Jedes ist eine Dienstvereinbarung zwischen
dem Deployment und dem Provider, geschlossen in dem Moment, in dem ein
Administrator die Zugangsdaten dieses Providers im [Vault](secrets.md) ablegt. Die
Bedingungen, auf die es für eine Prüfung ankommt, sind die des Providers: was mit
Prompts und Dokumenten geschieht, die dorthin gehen, ob darauf trainiert wird, wo
die Daten verarbeitet und wie lange sie aufbewahrt werden.

Das ist eine Frage des Datenschutzes und keine Lizenzfrage, und sie wird pro
Deployment beantwortet, nicht hier. Die SDKs, die mit diesen Diensten sprechen,
sind gewöhnliche Pakete in den Notices: Die Clients von Anthropic, OpenAI, Google,
Mistral, Cohere, Groq und xAI sind allesamt MIT oder Apache-2.0.

## Modellgewichte { #model-weights }

In keinem der beiden Images stecken Modellgewichte. Ein Deployment wählt Modelle
in [Modellprofilen](models.md); ein geschlossenes Modell wird über die API seines
Providers zu dessen Bedingungen erreicht, und ein Modell mit offenen Gewichten
lädt das Deployment unter der Lizenz herunter, die sein Herausgeber daran geheftet
hat. Diese Lizenzen unterscheiden sich stärker als Softwarelizenzen, und mehrere
sind nach der OSI-Definition kein Open Source, selbst wenn die Gewichte frei
herunterladbar sind.

| Familie | Lizenz, wie mit den Gewichten veröffentlicht | Was vor der Auswahl zu prüfen ist |
|---|---|---|
| Qwen 2.5 und 3 (die meisten Größen), Mistral 7B und Nemo, GPT-OSS, DeepSeek V3 und R1, Phi-4 | Apache-2.0 oder MIT | Nur Namensnennung. Einige größere Qwen-2.5-Größen tragen stattdessen die Qwen-Lizenz; lesen Sie die Model Card |
| Llama 3.x | Llama Community License | Kein Open Source: eine Acceptable-Use-Policy, eine Namensnennung "Built with Llama" und eine gesonderte Lizenz oberhalb einer Schwelle monatlich aktiver Nutzer |
| Gemma | Gemma Terms of Use | Kein Open Source: eine Policy verbotener Nutzungen, die auf abgeleitete Werke durchschlägt |
| Mistral Large und einige Codestral-Releases | Mistral Research License oder eine kommerzielle Lizenz | Nur Forschung und nicht-kommerzielle Nutzung, sofern nicht lizenziert |

Die Tabelle ist Orientierung, kein Nachweis: Modelllizenzen ändern sich zwischen
Releases, und die Model Card des Herausgebers ist das maßgebliche Dokument. Die
Seite [Ein Modell wählen](choosing-models.md#closed-models-or-open-weights) trägt
die technische Seite derselben Entscheidung.

!!! tip "Halten Sie die Entscheidung dort fest, wo das Modell konfiguriert wird"

    Die Beschreibung eines Modellprofils ist ein guter Ort, um die Lizenz zu
    nennen, unter der die Gewichte genommen wurden, und das Datum, an dem das
    geprüft wurde. Sie reist mit dem Profil in jedes Environment und zu jedem
    Agent, der es nutzt.

## Kundenspezifische Komponenten { #client-specific-components }

Der eigene Stack eines Deployments fügt Komponenten hinzu, die dieses Inventar
nicht sehen kann: das Modell, das es selbst hostet, die MCP-Server, die es
anbindet, eine verwaltete Datenbank oder ein Redis anstelle der Compose-Dienste,
einen Reverse Proxy, einen Identity Provider. Jede braucht dieselben drei Angaben
wie die Tabellen oben, Komponente, Lizenz, Pflicht, bevor die Prüfung des
Deployments vollständig ist. Die Voreinstellungen des Compose-Pfads sind in
`licenses/components.toml` unter `deployment-review` und `service image`
festgehalten, und dorthin gehören auch die eigenen Zeilen eines Deployments, in
seinem Fork oder seinem Deployment-Repository.

## Es wahr halten { #keeping-it-true }

Die Prüfung läuft an jedem Pull Request im `security`-Job und in `make check`, der
Wartungsablauf besteht also größtenteils darin, dass die Prüfung sich weigert
durchzugehen.

**Eine Abhängigkeit ändert sich.** Dependabot oder `make deps-upgrade` bewegt ein
Lockfile; der `security`-Job schlägt mit `THIRD_PARTY_NOTICES.md is stale` fehl.
Führen Sie `make licenses` aus, lesen Sie den Diff, committen Sie. Fügt der Diff
eine Komponente ohne Lizenz hinzu oder eine aus dem Review-Set, benennt die
Prüfung den Policy-Eintrag, der zu schreiben ist, und der Pull Request trägt die
Entscheidung neben dem Upgrade, das sie nötig gemacht hat.

**Eine Lizenz ändert sich.** Eine Komponente, die unter einer Lizenz geprüft
wurde, löst nach einem Upgrade auf eine andere auf; die Prüfung sagt
`reviewed as X but resolves to Y - review it again`. Die alte Entscheidung
überlebt das nicht von selbst.

**Ein Befund schließt.** Der Policy-Eintrag wechselt von `open` auf `accepted` mit
einem `fulfilled_by`, oder die Komponente wird entfernt und die Prüfung verlangt,
dass der Eintrag verschwindet. Generieren Sie die Notices neu; der Befund verlässt
den Kopf der Datei.

**Ein Modell oder ein Dienst ändert sich.** In den Lockfiles bewegt sich nichts,
also schlägt nichts fehl. Die Modelltabelle oben, die Beschreibung des
Modellprofils und die eigenen Komponentenzeilen des Deployments sind das, was zu
aktualisieren ist, und die Release-Checkliste ist das, was danach fragt.

**Ein Image ändert sich.** Ein neuer Base-Tag, ein zusätzliches Debian-Paket, ein
neuer Compose-Dienst: `licenses/components.toml` wird in derselben Änderung
bearbeitet, und `scripts/docs_drift.py` erinnert daran, wenn sich ein Dockerfile
bewegt und diese Seite nicht.

## Release-Checkliste { #release-checklist }

Bevor ein Release geschnitten wird, und als Nachweis, der daran hängt:

- [ ] `make licenses-check` ist auf dem Release-Commit durchgelaufen; die
  Urteilszeile steht in der Zusammenfassung des `security`-Jobs
- [ ] `THIRD_PARTY_NOTICES.md` bei diesem Commit sind die Notices für das Release;
  beide Images tragen ihre Lizenzdateien (`/app/THIRD_PARTY_NOTICES.md` sowie
  `.venv/**/*.dist-info/` und `/app/licenses/texts/` im Backend-Image;
  `/app/licenses/` im Frontend, mit `NOTICE`, `OFL.txt` und einem Verzeichnis pro
  Paket)
- [ ] Die offenen Befunde in den Notices sind die, die diese Seite auflistet,
  jeder mit einem Issue, das noch das richtige ist
- [ ] `licenses/components.toml` nennt die Image-Tags und Compose-Dienste, die das
  Release tatsächlich nutzt
- [ ] Wurde dem Katalog oder der Modelltabelle oben eine Modellfamilie
  hinzugefügt, wurde ihre Lizenz aus der aktuellen Model Card gelesen
- [ ] Sobald das SBOM pro Release aus #1415 existiert: Es hängt am Release, und
  sein Komponentensatz stimmt mit den Notices für die beiden Images überein

## Fazit { #recap }

- Die Images liefern rund fünfhundert Drittanbieter-Pakete aus, fast alle MIT,
  Apache-2.0 oder BSD; die Lizenzdatei jedes Pakets reist mit ihm, und
  `THIRD_PARTY_NOTICES.md` ist der generierte Index.
- Die Entscheidungen stehen in `licenses/policy.toml` und
  `licenses/components.toml`; die Prüfung schlägt bei allem fehl, das keine hat,
  und bei einer Entscheidung über eine Lizenz, die sich seither geändert hat.
- Ein Befund ist offen und wird verfolgt: die beim Deployment gebaute
  Sandbox-Runtime. Zwei weitere wurden erledigt, statt offen zu bleiben - die AGPL
  von PyMuPDF, geprüft und behalten, mit einem eigenen Abschnitt, und das
  Redis-Image, ersetzt durch Valkey.
- Modellgewichte und gehostete Provider werden pro Deployment zu den Bedingungen
  des Herausgebers oder des Providers gewählt; diese Seite sagt, was zu prüfen
  ist, das Deployment hält fest, was es gewählt hat.
