---
source_sha: "e2efe341a181"
---

# Die ML-Dienste { #the-ml-services }

Vier Dienste dieser Plattform lassen sich für sich allein aufrufen, ohne eine
Unterhaltung zu beginnen und ohne einen Agent auszuführen: Dokumentanalyse, OCR,
Spracherkennung und Erkennung personenbezogener Daten. Es sind dieselben
Implementierungen, die die Agents benutzen, nur direkt erreicht — ein Satz
Parser, ein Satz Detektoren, ein Transkriptionsclient.

Es gibt sie, weil eine andere Komponente sie brauchen kann. Eine Warteschlange,
die einen eingescannten Antrag lesen muss, ein Batch-Job, der einen Export
schwärzt, ein Dienst, der ein Transkript will — keiner davon will ein
Chat-Fenster, und keiner sollte so tun müssen, als wäre er eines.

## Was geliefert ist und was nicht { #what-is-delivered-and-what-is-not }

Jede Dienstfamilie ist eine Zeile. **served** heißt, ein Endpunkt dieses
Deployments beantwortet sie mit der daneben genannten Engine. **dependency**
heißt, die Familie ist gefordert und etwas fehlt, und die Notiz sagt was.
**prepared** ist Architekturvorbereitung: keine Engine wird ausgeliefert, und die
Naht, durch die sie käme, ist benannt.

`GET /api/v1/ml/services` antwortet mit derselben Tabelle, sodass eine
Integration sie lesen kann, statt einer Seite zu vertrauen.

| Dienst | Anforderungen | Endpunkt | Stand | Engine |
|---|---|---|---|---|
| `document_analysis` | FA-069, FA-070 | `POST /api/v1/ml/documents/analyze` | served | LiteParse oder PyMuPDF, lokal |
| `ocr` | FA-069, FA-071 | `POST /api/v1/ml/documents/ocr` | served | LiteParse-OCR: mitgeliefertes Tesseract oder ein registrierter OCR-Server |
| `speech_to_text` | FA-069, FA-072 | `POST /api/v1/ml/audio/transcriptions` | served | Der eigene Transkriptionsendpunkt der Organisation |
| `pii_detection` | FA-069, FA-073 | `POST /api/v1/ml/privacy/pii` | served | Die Musterdetektoren, die auch die Guardrails benutzen |
| `pii_named_entities` | FA-073, DA-007 | — | dependency | Keine in diesem Deployment |
| `image_analysis` | FA-074 | — | prepared | Keine in diesem Deployment |

Zwei Zeilen sagen nein, und beide sagen warum. **Benannte Entitäten** — der Name
einer Person, eine Postanschrift — haben keine Musterform,
also findet sie kein regulärer Ausdruck: dafür braucht es ein
Named-Entity-Modell je Sprache im Umfang. Der Erkennungsendpunkt trägt die
zusätzlichen Kategorien an dem Tag, an dem eines bereitgestellt wird, und bis
dahin beansprucht er sie nicht. **Bildanalyse** ist in den Anforderungen selbst
als künftiger Umfang markiert.

## Einen aufrufen { #calling-one }

Authentifizierung, der Organisations-Header und der Fehlerumschlag gehören der
[HTTP-API](api.md). Es gibt keinen eigenen Schlüssel, keinen eigenen Host und
keinen zweiten Weg hinein, und das mit Absicht: eine Oberfläche mit eigener
Haustür ist eine Oberfläche mit eigenen Fehlern.

Eine Berechtigung sichert alle vier: **`ml:invoke`**. Bewusst nicht
`agents:run` — eine Integration, die Dokumente parst, sollte dadurch nicht auch
das Modellbudget der Organisation ausgeben können. Jede Rolle außer Viewer hält
sie.

```bash
curl -X POST "$BASE/api/v1/ml/documents/ocr" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -F "file=@scan.pdf" \
  -F "language=deu"
```

Die Antwort trägt die Seiten in Reihenfolge, die vorbereiteten Chunks sowie Größe
und Hash der Datei:

```json
{
  "filename": "scan.pdf",
  "filetype": "pdf",
  "byte_size": 184320,
  "content_hash": "9f2c…",
  "pages": [{"page_num": 1, "content": "Antrag auf …"}],
  "chunks": ["Antrag auf …"]
}
```

### Dokumentanalyse { #document-analysis }

`POST /api/v1/ml/documents/analyze` liest, was ein Dokument bereits trägt. Das
Feld `parser` wählt zwischen `liteparse`, das das Layout erhält und
Office-Formate liest, wo LibreOffice installiert ist, und `pymupdf`, das PDFs
liest und schneller ist. `chunk_size`, `chunk_overlap` und `chunking_strategy`
formen die vorbereiteten Chunks; die Strategien sind `recursive`, `fixed` und
`markdown`, und eine vierte Schreibweise wird abgelehnt statt still als
`recursive` behandelt.

`chunk_overlap` muss **kleiner** als `chunk_size` sein. Gleich wird abgelehnt, und
nicht der Ordnung halber: der Splitter nimmt es an und rückt dann um etwa einen
Trenner je Chunk vor, während er eine fast vollständige Kopie des letzten behält -
ein zulässiger Upload antwortet also mit einem vielfach vervielfältigten Dokument.

Ein Dokument, in dem nichts lesbar ist, wird abgelehnt statt mit einer leeren
Seitenliste beantwortet, und die Ablehnung sagt, stattdessen OCR aufzurufen — was
ein Scan, der auf seine Textebene hin geparst wird, immer braucht.

### OCR { #ocr }

`POST /api/v1/ml/documents/ocr` erkennt den Text auf jeder Seite, ob die Seite
eine Textebene trägt oder nicht. Das ist der Unterschied zur Ingestion, die das
automatisch erkennt und die Erkennung überspringt, wo der Text schon da ist: wer
OCR verlangt hat, hat verlangt, dass die Seiten als Bilder gelesen werden.

`language` ist ein Tesseract-Code, also drei Buchstaben — `deu`, nicht `de`. Das
ausgelieferte Image installiert **`eng` und `pol`**, und genau diese zwei nimmt der
Endpunkt an: ein Code ohne Sprachpaket dahinter scheitert mitten im Parse, also
wird er schon an der Grenze abgelehnt. Ein Deployment, das weitere Pakete
installiert, erweitert die Liste in derselben Änderung.

`ocr_service_id` benennt einen OCR-Server, der unter den
[lokalen Diensten](configuration.md) registriert ist, sodass ein Deployment mit
eigenem Erkennungs-Sidecar die Seiten dorthin schickt; lässt man es weg, liest
sie die im Parser mitgelieferte Engine. So oder so bleiben die Seiten im eigenen
Netz des Deployments.

**Ein `.docx` wird hier abgelehnt**, obwohl der Parser eines liest. Die Ingestion
leitet Office-Dokumente an den nativen Leser, bevor sie den OCR-Parser befragt -
eines anzunehmen würde also vorhandene Absätze herausziehen, gescannte Seiten
überspringen und über den Unterschied schweigen. Konvertieren Sie es in PDF.

Ein Aufruf erkennt höchstens **200 Seiten** und hat **120 Sekunden**, beides enger
als bei der Ingestion, weil hier jemand wartet und auf eine Ingestion niemand.

### Spracherkennung { #speech-to-text }

`POST /api/v1/ml/audio/transcriptions` transkribiert eine Aufnahme mit einem
Schlüssel aus dem Vault der Organisation. `provider` und `model` benennen, was
benutzt wird; lässt man **beide** weg, wird die Spracherkennungs-Voreinstellung
der Organisation von der [Voice-Karte](console.md#the-voice-card) genommen, ohne
eine solche das erste angebotene Paar des Deployments, und nennt man einen
Anbieter ohne Modell, dessen erstes Modell. Was nie passiert: auf den
Standardanbieter zurückzufallen, obwohl ein Anbieter genannt wurde.

Eine Aufnahme unterliegt außerdem der eigenen 25-MB-Grenze des
Transkriptionsclients, auch wenn `ML_MAX_UPLOAD_SIZE_MB` höher steht - eine zu
große Aufnahme wird also als zu groß abgelehnt, statt die Engine zu erreichen und
als 503 über einen Schlüssel zurückzukommen.

**Der Schlüssel wird benannt, nie gesucht.** `secret_id` benennt den
Vault-Schlüssel, mit dem die Aufnahme gesendet wird: einen API-Schlüssel, dessen
Zweck der Anbieter ist und den der Aufrufer sehen kann. Fehlt er, wird der
Standardschlüssel der Organisation benutzt, aber nur für den Anbieter, für den er
gewählt wurde; jeder andere Anbieter ohne `secret_id` wird als `not_configured`
abgelehnt. Ein Schlüssel für einen anderen Anbieter, einer anderen Art oder einer,
den der Aufrufer nicht sieht, wird am Feld `secret_id` abgelehnt. Der
`OPENAI_API_KEY` des Deployments wird nie benutzt.

Jede Ebene, die Spracherkennung einrichtet, funktioniert gleich: Das Modell ist
eine Wahl aus dem Spracherkennungskatalog, und der Schlüssel ist ein daneben
benanntes Vault-Secret. Kein model profile wird gelesen - Profile sind das, was
ein Text-Run nutzt -, und nichts wählt einen Schlüssel, nur weil er zufällig der
einzige für einen Anbieter ist. Bei zwei OpenAI-Schlüsseln im Vault zahlt der
benannte.

!!! note "Noch kein selbst gehosteter Spracherkennungsserver"

    Jeder Anbieter im Katalog wird unter seiner eigenen Adresse erreicht, mit
    einem Schlüssel. Ein schlüsselloser Server im eigenen Netz - ein Whisper
    hinter einer OpenAI-kompatiblen API - ist heute nicht erreichbar. Das ist ein
    geplanter Folgeschritt: ein [lokaler Dienst](configuration.md) einer neuen
    Art, `speech`, benannt anstelle eines Schlüssels, so wie Collections schon
    einen Embedding- oder OCR-Server benennen.

Eine Ablehnung sagt in `details.reason`, warum, hier wie beim
[Diktieren](#dictation-in-chat). Der eigene Fehlertext des Anbieters wird
protokolliert und nie zurückgegeben, denn ein Anbieter-Client schreibt die
Anfrage-URL samt Schlüssel in seine Meldung.

| `reason` | Status | Was passiert ist |
|---|---|---|
| `not_configured` | 503 | Für den Anbieter ist kein brauchbarer Schlüssel benannt - keiner gewählt, gelöscht oder auf dieser Ebene nicht mehr zulässig; beim Diktieren auch: Server-Diktat nicht eingerichtet |
| `empty` | 400 | Die Engine hat keine Sprache gehört, oder die Aufnahme hat keine Bytes |
| `unsupported_type` | 400 | Nur beim Diktieren: die Aufnahme ist kein WAV mit 16 kHz, Mono und 16-Bit-PCM - oder, wo das Deployment komprimiertes Audio annimmt, kein WebM, Ogg oder MP4 -, oder auf einer gehosteten Seite oder in einem Widget lässt sich die Länge einer komprimierten Aufnahme nicht lesen. `details.accepted` listet die angenommenen Typen |
| `too_large` | 400 | Über 25 MB oder über der Diktatgrenze der Organisation in Bytes oder in gemessener Länge; `details.limit_seconds` nennt die Grenze |
| `provider_error` | 503 | Der Anbieter hat die Anfrage abgelehnt oder ist daran gescheitert |
| `timeout` | 503 | Der Anbieter hat nicht innerhalb von 60 Sekunden geantwortet |

#### Diktieren im Chat { #dictation-in-chat }

`POST /api/v1/agents/{agent_id}/dictation` ist das Mikrofon im
[Eingabefeld von `/chat`](console.md#dictation), wenn die Organisation auf dem
Server transkribiert. Es nimmt eine Aufnahme als `file` und antwortet mit
`{"text": "..."}`, das das Eingabefeld zum Bearbeiten einsetzt; gesendet wird
nichts, bis die Person auf Senden drückt. Der Aufrufer nennt weder Anbieter
noch Modell noch Sprache — die [lösen sich](#which-engine-a-recording-reaches)
aus dem Agent und der Organisation auf — und die Person darf jedem Agent
diktieren, den sie ausführen darf, ein Viewer mit einem
`use`-Grant darauf eingeschlossen. Ein Agent, den sie nicht ausführen darf,
antwortet mit 404, wie überall sonst.

Was es aus der Organisation liest, eingestellt auf der
[Karte Stimme (Voice)](console.md#the-voice-card) von jemandem mit `org:settings`:
`chat_dictation` (`off`, `browser` oder `server`; alles außer `server` wird als
`not_configured` abgelehnt), `speech_to_text_provider` und
`speech_to_text_model` (ein Paar aus dem Speech-to-Text-Katalog),
`speech_to_text_language` (ein ISO-639-1-Code, oder null, damit die Engine ihn
erkennt) und `dictation_max_seconds` (10 bis 600, standardmäßig 300). Die
Engine und das längste Diktat gehören immer der Organisation; der Agent kann nur
ändern, welcher Anbieter, welches Modell und welche Sprache.

`GET /api/v1/agents/{agent_id}/dictation` sagt mit demselben Zugriff, ob das
Mikrofon funktionieren wird, bevor jemand aufnimmt: `engine`, `max_seconds`,
`provider`, `format`, `ready`, `server_available` und `unavailable`.
`server_available` verlangt ein Paar, das sich für diesen Agent auflöst, einen
Katalog, der es noch anbietet, und einen brauchbaren Schlüssel, der neben dem
Paar benannt ist - auf sein Vorhandensein geprüft, nie geöffnet; `ready` ist
das, die Engine `server` und ein Agent, der nicht archiviert ist.

Ist es falsch,
sagt `unavailable`, was fehlt: `no_provider` (keine Ebene benennt ein Paar),
`not_offered` (der Katalog hat es zurückgezogen) oder `no_key` (kein brauchbarer
Schlüssel benannt - einen wählen).
Das Embed-Formular liest `server_available`, denn eine
[gehostete Seite oder ein Widget](channels.md#dictation-on-a-widget-or-a-hosted-page)
hängt nicht an der Engine von `/chat`.

`provider` ist der Anbieter, den eine Aufnahme erreichen würde, und `format`,
worin für ihn aufgenommen wird: `wav`, es sei denn, das Deployment
[nimmt komprimiertes Audio an](deployment.md#what-a-dictation-may-be-uploaded-as)
und der Speech-to-Text-Katalog sagt, dass der Anbieter nimmt, was
`MediaRecorder` erzeugt - dann `webm`. Das wird hier entschieden, sodass kein
Client eine eigene Liste führt. Ein Agent ohne veröffentlichte Version
antwortet aus den Einstellungen der Organisation.

**Standardmäßig ist ein Diktat rohes PCM**: `audio/wav` (oder `audio/x-wav`,
`audio/wave`) mit 16 kHz, Mono und 16-Bit-Integer-PCM, das jeder Browser über
Web Audio aufnimmt. Die Datei wird streng gelesen - ein `fmt `-Chunk, der genau
das sagt, ein `data`-Chunk aus ganzen Samples, Größen, die zur Datei passen -,
und jedes andere WAV, auch ein Stereo-, 48-kHz-, 24-Bit- oder Float-WAV, wird
als `unsupported_type` abgelehnt. Der Anbieter bekommt die gezählten Samples
hinter einem Header, den der Server baut, nie den Header des Aufrufers oder
einen anderen Chunk der Datei, als `recording.wav`.

Wo das Deployment komprimiertes Audio annimmt, werden auch `audio/webm`,
`audio/ogg` und `audio/mp4` angenommen, ein Codec-Suffix ist erlaubt, und
`audio/x-m4a` und `audio/m4a` werden als `audio/mp4` gelesen, `audio/opus`
sowie `audio/x-ogg` als `audio/ogg`. Sie erzeugt `MediaRecorder` in Browsern,
und der Anbieter erhält sie als `recording.webm`, `recording.ogg` oder
`recording.m4a`, nach derselben Tabelle, die eine Sprachnotiz aus einem Kanal
`voice.<ext>` nennt.

Die Route liest höchstens 25 MB des Bodys; die Byte-Grenze der Organisation -
die Bytes, die `dictation_max_seconds` plus drei Sekunden PCM belegen, 32.000
pro Sekunde, und 4 KB für den Container - gilt für das Gelesene. Ein Body, den die
Anfragegrenze des Deployments ablehnt, bevor die Route läuft, bekommt 413 ohne
`reason`, was das Eingabefeld als `too_large` liest.

Dann wird **die Länge gemessen**, bevor der Provider aufgerufen wird, und eine
Aufnahme, die länger als `dictation_max_seconds` ist, wird als `too_large`
abgelehnt, mit drei Sekunden Spielraum, weil das Eingabefeld im Sekundentakt
stoppt. Bei PCM ist die Länge die gezählten Samples, exakt. Die einer
komprimierten Aufnahme wird aus ihrem eigenen Header gelesen - der letzten
Ogg-Seite, den Zeitstempeln der WebM-Blöcke, den Movie- oder Fragment-Headern
von MP4 -, den eine von Hand gebaute Datei zu kurz angeben kann. Eine, deren
Länge sich nicht lesen lässt, wird hier innerhalb der Byte-Grenze angenommen;
[eine gehostete Seite oder ein Widget](channels.md#what-it-costs-and-what-bounds-it)
lehnt sie ab.

Jede Person darf `RATE_LIMIT_DICTATION_PER_MINUTE`-mal pro Minute diktieren,
standardmäßig 10, auf einem eigenen Zähler, sodass Diktieren nicht das
ML-Kontingent einer Integration verbraucht. Jedes Diktat hinterlässt einen
[Aufrufdatensatz](#what-is-recorded), unter `speech_to_text` und in Sekunden
Audio gezählt - bei PCM die gezählte Länge. Das Eingabefeld schickt die
aufgenommene Länge als Formularfeld `duration` neben `file`, das nur für eine
komprimierte Aufnahme verwendet wird, für die nichts anderes eine Länge angibt.

**Das Audio wird nie gespeichert**: Es wird verworfen, wenn der Aufruf
zurückkehrt, und der Text existiert nur in der Antwort. Abbrechen im Browser
bricht eine bereits gesendete Aufnahme nicht ab — der Anbieter transkribiert sie
trotzdem, stellt sie dem Konto der Organisation in Rechnung, und der Aufruf wird
aufgezeichnet.

!!! note "Bei Mistral nimmt der Browser immer WAV auf, und es werden weniger Sprachen transkribiert"

    Mistral dokumentiert für Voxtral WAV- und MP3-Eingaben, nicht WebM oder
    Opus, was Chrome und Firefox aufnehmen. Ist Mistral der Anbieter, auf den
    sich eine Aufnahme auflöst, nimmt das Eingabefeld deshalb in jedem Browser
    WAV mit 16 kHz, Mono und 16 Bit auf, auch wo das Deployment komprimiertes
    Audio annimmt. Ein PCM-Upload ist etwa doppelt so groß wie das WebM, das er
    ersetzt — 32.000 Bytes pro Sekunde —, und die Längengrenze ist dieselbe.

    Die Sprachliste ist die von Whisper, die OpenAI und Groq akzeptieren.
    Mistral nennt 13 Sprachen für Voxtral, sodass eine festgelegte Sprache, die
    er nicht nimmt, als `provider_error` zurückkommt. Bei Mistral die Sprache
    auf automatischer Erkennung lassen und eine Aufnahme ausprobieren, bevor man
    sich darauf verlässt.

#### Welche Engine eine Aufnahme erreicht { #which-engine-a-recording-reaches }

Drei Stellen können eine Speech-to-Text-Engine nennen: die
[Karte Stimme (Voice)](console.md#the-voice-card) der Organisation, die
[`speech_to_text`](reference/spec.md#speech-to-text)-Überschreibung eines Agents,
eingestellt auf seiner eigenen [Karte Stimme (Voice)](console.md#an-agents-own-engine)
und live, sobald er veröffentlicht ist, und ein
[Kanal-Bot](channels.md#what-every-channel-shares). Sie lösen sich in zwei
Hälften auf:

| Was | Kommt von der ersten Stelle, die es setzt |
|---|---|
| Anbieter, Modell und Schlüssel, zusammen | Der Bot, dann der Agent, dann die Organisation |
| Sprache | Der Agent, dann die Organisation, dann erkennt die Engine sie |

**Der Schlüssel reist mit seinem Paar.** Jede Ebene benennt einen Schlüssel neben
ihrem eigenen Anbieter und Modell, und die drei lösen sich als Einheit auf: Ein
Agent mit eigenem Paar sendet es mit seinem eigenen Schlüssel, nie mit dem der
Organisation. Ein Schlüssel erreicht also nie einen Anbieter, der ihn nicht
ausgestellt hat. Welche Schlüssel eine Ebene benennen darf:

| Ebene | Der Schlüssel muss sein |
|---|---|
| Die Voreinstellung der Organisation | Ein API-Schlüssel für den Anbieter, **für die ganze Organisation sichtbar** - die Plattform gibt ihn für alle aus. Geprüft beim Speichern der Voice-Karte und erneut bei jeder Aufnahme |
| Das eigene Paar eines Kanal-Bots | Ebenso: organisationsweit sichtbar, denn die Sprachnachrichten eines Bots werden für jeden bezahlt, der ihm schreibt |
| Die Überschreibung eines Agents | Ein API-Schlüssel für den Anbieter, den der Veröffentlichende sehen kann - die Regel, der jeder Schlüssel in einer Agent-Spec folgt. Geprüft beim Veröffentlichen |

Ein Schlüssel, der nach der Wahl auf Organisations- oder Bot-Ebene privat wird,
wird nicht mehr benutzt, statt weiter für die Aufnahmen anderer zu zahlen. Ein
gelöschter Schlüssel leert den Verweis auf diesen beiden Ebenen, und die Spec
eines Agents behält die ID, bis sie mit einem anderen neu veröffentlicht wird:
So oder so sagen die Voice-Karte und die Bereitschaftsprüfung „Schlüssel
wählen“, und Aufnahmen werden als `not_configured` abgelehnt, bis jemand das tut.

Ein polnischer Agent in einer auf Englisch eingerichteten Organisation legt also
`language: pl` fest und behält Anbieter und Schlüssel der Organisation. Ein Bot hat keine
eigene Sprache; die des Agents oder der Organisation gilt auch für sein eigenes
Paar. Löst sich nichts auf, wird nichts transkribiert: das Diktieren antwortet
`not_configured`, und ein Bot sagt, dass er nicht zuhören kann.

Das Diktieren liest die veröffentlichte Standardversion des Agents, die, die
`/chat` ausführt. Ein Bot liest den Agent, den seine Bindung bedient - nie einen
Agent, den jemand mit `@slug` erwähnt, denn eine Aufnahme wird transkribiert,
bevor Erwähnungen geroutet werden -, in der Version, die die Umgebung dieser
Bindung festlegt, der, die der Run benutzen wird. Ein Agent im Entwurf oder
archiviert hat keine Version, die jemand ausführt, und die Organisation
antwortet allein.

### Erkennung personenbezogener Daten { #personal-data-detection }

`POST /api/v1/ml/privacy/pii` nimmt JSON statt einer Datei:

```bash
curl -X POST "$BASE/api/v1/ml/privacy/pii" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-Organization-Id: $ORG_ID" \
  -H "Content-Type: application/json" \
  -d '{"text": "write to ada@example.com", "categories": ["email"]}'
```

```json
{
  "counts": [{"category": "email", "count": 1}],
  "total": 1,
  "redacted_text": "write to [redacted:email]"
}
```

Jede angeforderte Kategorie wird berichtet, auch die, die nichts getroffen haben
— "gesucht und nicht vorhanden" und "nicht gesucht" sind verschiedene Antworten.
Die Kategorien sind `email`, `iban`, `credit_card`, `us_ssn` und `phone`, und
jede wird nach Form getroffen und dann geprüft: Luhn für eine Karte, ISO 7064
für eine IBAN, der Nummerierungsplan des Landes und die Gruppierung der Ziffern
für eine Telefonnummer, damit eine Ziffernfolge nicht als Konto oder Nummer
gemeldet wird.

Eine mit `+` geschriebene Telefonnummer wird unabhängig vom Land gefunden; eine
nationale wie `415-555-0132` wird gegen die Standardländer der Guardrails
gelesen, `US, GB, DE, PL`. Das Feld `phone_regions`, das diese Liste ändert,
gehört zu den Guardrails eines Agenten, nicht zu diesem Endpunkt.

Zurück kommen Zählungen und der geschwärzte Text, nicht die Offsets der einzelnen
Treffer. Die Detektoren antworten mit umgeschriebenem Text, und die Positionen
zurückzugewinnen hieße, ihre Mustertabelle und ihre Prüfsummen zu kopieren — eine
Kopie, die still aufhört, mit dem Original übereinzustimmen, ist schlimmer als
ein engerer Vertrag.

## Was aufgezeichnet wird { #what-is-recorded }

Jeder Aufruf hinterlässt eine Zeile: welcher Dienst, welche Organisation, wer
gefragt hat, wie viele Bytes hineingingen, wie viel herauskam, wie lange es
dauerte und wie es endete. `GET /api/v1/ml/calls` liest sie zurück, neueste
zuerst, und `GET /api/v1/ml/calls/{id}` liest eine.

Ein abgelehnter Aufruf wird ebenfalls aufgezeichnet, und sein Datensatz wird
festgeschrieben, bevor die Ablehnung die Anfrage abwickelt - eine Zeile, die der
Transaktion nur hinzugefügt würde, nähme genau die Ablehnung zurück, die sie
beschreibt, und einem Betreiber mit der Frage, warum eine Integration scheitert,
würde gesagt, der Mandant habe gar keine Aufrufe gemacht.

**Kein Inhalt wird aufbewahrt.** Das Ergebnis geht in der Antwort zurück und wird
nicht gespeichert, sodass ein hier geparstes Dokument kein Dokument wird, das
dieses Deployment hält, und Text, der zur Prüfung auf personenbezogene Daten
geschickt wurde, nicht in einer Tabelle bleibt, an die niemand als
Dokumentenspeicher gedacht hat. Ein Aufrufdatensatz einer anderen Organisation
ist nicht auffindbar, genau wie jede andere Zeile auf dieser API.

Nutzung wird in der Einheit gezählt, in der der Dienst arbeitet — Seiten bei
einem Parse, Zeichen bei einem Scan, Sekunden Audio bei einer Transkription — und
nicht in Geld. Die gelieferten Dienste laufen entweder auf den eigenen Maschinen
des Betreibers, wo es keinen Anbieterpreis gibt, oder auf dem eigenen
Anbieterkonto der Organisation, das ihr direkt in Rechnung stellt. Eine Zahl, die
niemand mit einer Rechnung abgleichen kann, ist schlimmer als eine ehrliche
Einheitenzählung. Auf das [Budget](governance.md#budgets) eines Agents wird
Transkription ebenfalls nicht angerechnet.

### Transkriptionen { #transcriptions }

Sprache zu Text wird auf drei Wegen erreicht, und jeder hinterlässt dieselbe
Zeile: die API (`surface: api`), [Diktat](#dictation-in-chat) (`chat`) und die
[Sprachnachrichten eines Kanal-Bots](channels.md#what-every-channel-shares)
(`channel`). Die Zeile ergänzt `provider` und `model`, die `secret_id` des
Vault-Schlüssels, mit dem sie gesendet wurde - so wie ein Run seinen Schlüssel
festhält, damit „welcher Schlüssel kostet am meisten“ eine Antwort hat -, die
`agent_id`, für die sie war - der Agent, in den diktiert wurde, oder der Agent,
den der Bot bedient -, die `channel_bot_id` und `audio_ms`, die Länge der
Aufnahme.

Das Löschen des Schlüssels behält die Zeile und leert ihre
`secret_id`. Das `requested_by`
einer Sprachnachricht ist die Person, mit der der Absender verknüpft ist,
solange sie Mitglied der Organisation ist, oder niemand. Erfasst wird nur eine Aufnahme, die dem Provider übergeben wurde; ein
ausgeschalteter Bot oder einer ohne Engine zum Erben hat niemanden gefragt.

Die Länge ist die erste bekannte von diesen:

| Quelle | Wer sie liefert |
|---|---|
| Die Aufnahme selbst | Nur Diktat: die aus ihrem Container gelesene Länge, wie oben |
| Die Antwort des Providers | OpenAI `whisper-1` (`usage.seconds`), Groq (`duration`, angefordert mit `response_format=verbose_json`), Mistral (`usage.prompt_audio_seconds`) |
| Die Metadaten der Plattform | Eine Telegram-Sprachnachricht oder Audiodatei, ein Slack-Clip |
| Der Browser | Nur Diktat: die `duration`, die das Eingabefeld schickt, begrenzt auf das längste Diktat der Organisation, weil es das Wort des Clients ist |

OpenAIs `gpt-4o-transcribe` und `gpt-4o-mini-transcribe` melden Tokens, keine
Sekunden, und Mattermost gibt keine Länge an, sodass eine Sprachnachricht dort
mit diesen Modellen keine hat. Eine erfolgreiche Zeile zählt dann `0` Sekunden
mit leerem `audio_ms` - ungemessen, nicht still.

`GET /api/v1/ml/calls` filtert außer nach `ml_service` auch nach `agent_id`,
`channel_bot_id`, `surface`, `since` und `until`, immer innerhalb der
Organisation des Aufrufers: Die Agent-ID eines anderen Mandanten passt auf
nichts. Agent, Bot und Weg - als Filter und als Spalten - verlangen `runs:view`,
wie die Zusammenfassung unten. Mit `ml:invoke` allein wird ein Filter darauf mit
403 abgelehnt, und die drei kommen in jeder Zeile als null zurück.

`GET /api/v1/ml/calls/summary?days=30` summiert die erfolgreichen
Transkriptionen über ein Zeitfenster: `seconds` - die eigenen `units` jeder
Zeile, also die Aufnahme auf die Sekunde aufgerundet, addiert, damit die
Zusammenfassung zur Liste passt - und `count`, `count_unknown_length` für die Aufnahmen, die die Sekunden auslassen, und
dasselbe nach Agent, nach Kanal-Bot und nach Weg (`surface`). Es verlangt
`runs:view`, wie [`GET /spend`](governance.md#what-the-cost-screen-shows), statt
`ml:invoke`: Die Aufschlüsselung nennt Agents und Bots, die ein Member
möglicherweise nicht sehen darf. Die [Karte Stimme (Voice)](console.md#the-voice-card) der
Organisation zeigt es in einer Zeile.

## Grenzen { #limits }

Ein einzelner Aufruf nimmt bis zu `ML_MAX_UPLOAD_SIZE_MB` Megabyte an,
standardmäßig 25, und nur so viele Bytes werden aus dem Body gelesen - eine zu
große Einreichung wird abgelehnt, ohne vorher in den Speicher kopiert worden zu
sein. Ein Scan liest höchstens 200000 Zeichen, ein Scan mit `phone` höchstens 10.000
Ziffern: Die Telefonnummernsuche kostet Dutzende Mikrosekunden pro Ziffer, also
wird ein längerer Text abgelehnt statt gelesen. Ein Aufrufer darf
`RATE_LIMIT_ML_PER_MINUTE` Aufrufe pro Minute machen, standardmäßig 30, gezählt
pro Aufrufer statt pro Adresse.

Ein Ratenlimit zählt **Starts** und sieht nicht, was noch läuft, was für Arbeit im
Minutenbereich die falsche Form ist. Ein Worker parst deshalb höchstens
`ML_MAX_CONCURRENT_PARSES` Dokumente gleichzeitig, standardmäßig 4, und ein Aufruf,
der jeden Platz belegt vorfindet, wird mit einem `Retry-After` abgelehnt statt
eingereiht: wem gesagt wird, gleich wiederzukommen, der kann das, und wer hinter
vier Scans geparkt ist, hat längst irgendwo aufgegeben, wo es hier niemand sieht.

Die Ausführung ist synchron: die Antwort ist das Ergebnis, und es gibt keine
Warteschlange zum Abfragen. Das ist ehrlich gegenüber dem, was hier ist, statt
aspirativ — ein Warteschlangenmodus würde dem Aufrufdatensatz eigene Zustände
hinzufügen, und in dieser Form käme er an.

## Sie getrennt betreiben { #deploying-them-separately }

Die Dienste skalieren anders als die Konsole. Ein OCR-Durchlauf sind
CPU-gebundene Sekunden auf einem Thread; ein Dashboard auszuliefern ist keines
von beidem. Also führt `deploy/profiles/ml-services/` das API-Image ein zweites
Mal als Replik aus, die nur diese Pfade beantwortet, mit eigenen Ressourcen und
eigener Skalierung, und der Ingress davor leitet `/api/v1/ml/` dorthin.

Es ist dasselbe Image und dieselbe Datenbank, und genau das hält eine
Implementierung im Dienst sowohl der Agents als auch der direkten Aufrufer.
Getrennt sind der Prozess, die Grenzen und der Neustart — also das, worum
"unabhängig betrieben, aktualisiert und skaliert" bittet.

`deploy/profiles/ml-services/README.md` beschreibt das Overlay und was es
erwartet.
