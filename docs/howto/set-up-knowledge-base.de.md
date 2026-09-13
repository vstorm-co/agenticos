---
source_sha: bdfb0e0fa929
---

# Eine Knowledge Base einrichten { #set-up-a-knowledge-base }

Wie ein Agent aus Ihren eigenen Dokumenten antwortet, von Anfang bis Ende. Etwa
zwanzig Minuten, kein Terminal, und unterwegs eine Entscheidung, die sich nicht
rückgängig machen lässt.

[Dateiverarbeitung](../file-processing.md) erklärt die Pipeline; dies hier ist
das Rezept.

## 1. Die Collection anlegen { #1-create-the-collection }

**Knowledge → New**. Geben Sie ihr einen Namen, den ein Mensch wiedererkennt — er
ist das, was später jemand aus einer Liste auswählt — und einen Geltungsbereich,
der entscheidet, ob sie Ihnen gehört oder der Organisation.

!!! danger "Das Embedding-Model ist bei der Erstellung eingefroren"

    Es ist die eine Wahl auf dieser Seite, die Sie danach nicht mehr ändern
    können. Die Vektorspalte wird in der Breite dieses Models angelegt, und zwei
    Models gleicher Breite schreiben trotzdem in *verschiedene* Räume — die Suche
    würde also weiterhin Vektoren vergleichen, die nicht dasselbe bedeuten.

    Es sich später anders zu überlegen heißt, eine neue Collection anzulegen und
    alles neu aufzunehmen. Belassen Sie es beim Standard des Deployments, sofern
    Sie keinen Grund haben, und wenn Sie einen haben, siehe
    [Ein Model wählen](../choosing-models.md#embeddings-are-a-separate-permanent-choice).

## 2. Entscheiden, wie Dokumente gelesen werden { #2-decide-how-documents-are-read }

Jede Collection trägt ihre eigenen Ingestion-Einstellungen, und jeder Upload kann
sie überschreiben. Die Standardwerte sind vernünftig; diese drei sind einen
Gedanken wert.

**Welcher Parser ein PDF liest.**

| | Was es ist | Wählen Sie es, wenn |
|---|---|---|
| `pymupdf` | Lokal, schnell, kostenlos — und der einzige, der eingebettete Bilder zur Beschreibung extrahiert | Dokumente, bei denen der Text im Vordergrund steht. Fangen Sie hier an |
| `liteparse` | Lokal, layoutbewusst, behält Tabellen als ASCII-Raster, statt sie einzuebnen | Dokumente, deren Bedeutung in ihren Tabellen steckt |
| `llamaparse` | Ein Cloud-Dienst, pro Seite abgerechnet, gibt Markdown zurück | Gescannte oder sperrige Dokumente, an denen die beiden lokalen scheitern — und Sie nehmen in Kauf, dass die Seiten das Haus verlassen |

**Ob OCR verwendet wird.** An bei Scans und Fotografien von Dokumenten, sonst
aus. Es ist langsamer, und auf sauberem Text erfindet es Zeichen.

**Wie Seiten in Chunks geschnitten werden.** `recursive` trennt an der Struktur
und ist der richtige Standard; `markdown` folgt den Überschriften, was besser
ist, wenn Ihre Dokumente tatsächlich welche haben; `fixed` ist ein grobes Zählen
von Zeichen, für den Fall, dass die anderen beiden Unsinn produzieren.

!!! tip "Ändern Sie immer nur eine Sache"

    Diese Einstellungen wirken aufeinander. Ist die Trefferqualität schlecht,
    ändern Sie den Parser *oder* das Chunking, nehmen Sie ein Dokument neu auf und
    stellen Sie dieselbe Frage noch einmal.

## 3. Dokumente hineingeben { #3-put-documents-in }

Zwei Wege, und Sie können beide in einer Collection nutzen.

**Laden Sie Dateien** direkt hoch — der gewählte Parser liest sie, zerteilt sie,
bettet sie ein, und das Dokument steht auf `processing`, bis das fertig ist.

**Synchronisieren Sie eine Source** — einen Google-Drive-Ordner oder einen
S3-Bucket, nach einem Zeitplan neu gelesen, sodass die Collection dem Ordner
folgt statt einer Kopie davon. Siehe
[Sync-Sources konfigurieren](configure-sync-sources.md).

!!! warning "Wenn die Ingestion bei einer frischen Installation scheitert, prüfen Sie das Datenbank-Image"

    Der Speicher setzt beim ersten Schreiben in eine Collection
    `CREATE EXTENSION IF NOT EXISTS vector` ab, und ein gewöhnliches Postgres
    antwortet *extension "vector" is not available* — ein 500, bevor eine einzige
    Zeile committet wird. Das Image muss `pgvector/pgvector:pg16` sein.

## 4. Sie einem Agent geben { #4-give-it-to-an-agent }

Im Builder, am Agent:

1. Schalten Sie die Capability **Knowledge search** ein.
2. Binden Sie die Collection — ein Agent durchsucht die Collections, die Sie
   benennen, und sonst nichts.
3. Setzen Sie `default_top_k`, die Anzahl der Chunks, die eine Suche
   zurückgibt.

**Fangen Sie bei drei an.** Acht Chunks, wo drei genügen, sind die häufigste
stille Mehrausgabe in diesem Produkt: abgerufener Text wird in dem Zug gelesen,
in dem er ankommt, und in jedem Zug, in dem er mitgetragen wird, und er ist
meistens das Größte im Prompt.

Sagen Sie es dann in den Instructions. Das Abrufen legt dem Model den Text vor;
die Instructions entscheiden, was es damit tut:

```
Answer from the knowledge collection and cite the document you used.
If the collection does not cover it, say so rather than guessing.
```

Dieser zweite Satz ist das, was aus einer selbstbewussten Erfindung ein "das habe
ich nicht" macht — und es lohnt sich, das absichtlich zu testen, indem Sie nach
etwas fragen, von dem Sie wissen, dass es nicht in den Dokumenten steht.

## 5. Sie testen { #5-test-it }

Veröffentlichen Sie, öffnen Sie den Tab **Test** des Agents und stellen Sie drei
Fragen:

| Frage | Was Sie prüfen |
|---|---|
| Etwas, das eindeutig in den Dokumenten steht | Dass das Abrufen überhaupt funktioniert und dass die Antwort eine Quellenangabe trägt |
| Etwas, das eindeutig *nicht* darin steht | Dass es ablehnt, statt zu erfinden |
| Etwas am Rand — ein Detail in einer Tabelle oder in einem Scan | Ob der Parser diesen Teil tatsächlich gelesen hat |

Die dritte ist die, die echte Probleme findet, und deshalb lohnt es sich, die
Parser-Wahl aus Schritt 2 noch einmal anzusehen, statt ihr zu vertrauen.

## Wenn es etwas nicht findet, das eindeutig da ist { #when-it-cannot-find-something-that-is-definitely-there }

Arbeiten Sie diese Liste ab; sie ist grob danach sortiert, wie oft der jeweilige
Punkt die Ursache ist.

1. **Steht das Dokument auf `processing` oder ist es fehlgeschlagen?** Der Fehler
   eines fehlgeschlagenen Dokuments steht am Dokument selbst und sagt, welche
   Stufe aufgegeben hat.
2. **Ist die Collection an *diesen* Agent gebunden?** Die Bindung gilt pro Agent,
   und eine veröffentlichte Version trägt die Bindungen, die sie beim
   Veröffentlichen hatte.
3. **Hat der Parser diesen Teil gelesen?** Öffnen Sie das Dokument und sehen Sie
   sich den extrahierten Text an. Eine in Prosa eingeebnete Tabelle oder ein Scan
   ohne OCR ist für die Suche unsichtbar, so deutlich Sie ihn auch sehen können.
4. **Ist `default_top_k` zu klein?** Drei ist richtig für ein enges Korpus und zu
   wenig für ein breites.
5. **Ist die Seite wirklich leer, oder ist die Anfrage fehlgeschlagen?** Beides
   ergibt dasselbe "hier ist nichts". Prüfen Sie den Netzwerk-Tab, bevor Sie
   irgendetwas schließen.

## Zusammenfassung { #recap }

- Das **Embedding-Model ist bei der Erstellung eingefroren**. Es ist die einzige
  unumkehrbare Wahl hier.
- **Zuerst `pymupdf`**, `liteparse` für tabellenlastige Dokumente, `llamaparse`,
  wenn die Seiten das Haus verlassen dürfen und die anderen nicht zurechtkommen.
- **Starten Sie `default_top_k` bei drei** und erhöhen Sie es nur, wenn Antworten
  tatsächlich Kontext fehlt.
- Die Instructions müssen **"say so rather than guessing"** sagen — das Abrufen
  allein stoppt das Erfinden nicht.
- Testen Sie mit etwas, das **nicht** in den Dokumenten steht, und mit etwas, das
  in einer Tabelle vergraben ist.

[Die Pipeline im Detail →](../file-processing.md) ·
[Einen Ordner synchronisieren →](configure-sync-sources.md)
