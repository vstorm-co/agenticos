---
source_sha: "b542fd3f7700"
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
einer Person, eine Postanschrift, eine Telefonnummer — haben keine Musterform,
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

`POST /api/v1/ml/audio/transcriptions` transkribiert eine Aufnahme auf den
eigenen Zugangsdaten der Organisation. `provider` und `model` benennen, was
benutzt wird; lässt man **beide** weg, wird das erste angebotene Paar des
Deployments genommen, und nennt man einen Anbieter ohne Modell, dessen erstes
Modell. Was nie passiert: auf den Standardanbieter zurückzufallen, obwohl ein
Anbieter genannt wurde — so landet eine Aufnahme, die für eine selbst gehostete
Engine gedacht war, bei einem Anbieter.

Eine Aufnahme unterliegt außerdem der eigenen 25-MB-Grenze des
Transkriptionsclients, auch wenn `ML_MAX_UPLOAD_SIZE_MB` höher steht - eine zu
große Aufnahme wird also als zu groß abgelehnt, statt die Engine zu erreichen und
als 503 über Zugangsdaten zurückzukommen.

Die Engine ist jener Endpunkt, den das model profile der Organisation für diesen
Anbieter benennt. Das ist die Antwort für ein Deployment, das kein Audio an einen
Anbieter senden darf: das Profil auf einen selbst gehosteten Server richten, der
dieselbe API spricht, und der Endpunkt hier bleibt unverändert. Eine Organisation
ohne brauchbare Zugangsdaten wird abgelehnt, und die Ablehnung sagt es — nichts
wird als vorhanden angenommen, was ein Betreiber nicht konfiguriert hat.

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
Die Kategorien sind `email`, `iban`, `credit_card` und `us_ssn`, und jede wird
nach Form getroffen und dann geprüft: Luhn für eine Karte, ISO 7064 für eine
IBAN, damit eine Ziffernfolge nicht als Konto gemeldet wird.

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
einem Parse, Zeichen bei einem Scan — und nicht in Geld. Die gelieferten Dienste
laufen entweder auf den eigenen Maschinen des Betreibers, wo es keinen
Anbieterpreis gibt, oder auf dem eigenen Anbieterkonto der Organisation, das ihr
direkt in Rechnung stellt. Eine Zahl, die niemand mit einer Rechnung abgleichen
kann, ist schlimmer als eine ehrliche Einheitenzählung.

## Grenzen { #limits }

Ein einzelner Aufruf nimmt bis zu `ML_MAX_UPLOAD_SIZE_MB` Megabyte an,
standardmäßig 25, und nur so viele Bytes werden aus dem Body gelesen - eine zu
große Einreichung wird abgelehnt, ohne vorher in den Speicher kopiert worden zu
sein. Ein Scan liest höchstens 200000 Zeichen. Ein Aufrufer darf
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
