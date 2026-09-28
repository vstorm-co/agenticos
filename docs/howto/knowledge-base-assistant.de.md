---
source_sha: "daee0cd1b399"
title: "Fragen über eine Dokumentbibliothek mit Zitaten beantworten"
description: "Legen Sie vier kleine synthetische Richtliniendokumente in einer Sammlung ab und prüfen Sie, dass der Agent das richtige findet, zwei davon kombiniert und zugibt, was keines abdeckt."
---

# Fragen über eine Dokumentbibliothek mit Zitaten beantworten { #answer-questions-across-a-document-library-with-citations }

Bauen Sie einen Agent, der aus einer kleinen HR-Richtlinienbibliothek statt aus
einer einzelnen Datei antwortet. Die Testdaten bestehen aus vier kurzen
Dokumenten in einer Sammlung: Eine Frage wird durch ein einzelnes Dokument
beantwortet, eine braucht zwei davon kombiniert, und eine wird gar nicht
abgedeckt. Eine Antwort aus mehreren Dokumenten zu prüfen heißt, beide
Quellpassagen zu lesen, nicht nur die Antwort selbst. Dies ist eine Anleitung
zum Durchführen, mit einem festgehaltenen Run als Referenz.

Für ein einzelnes Dokument ohne zu verwaltende Sammlung beginnen Sie
stattdessen mit [Ihrem ersten Dokumenten-Agent](first-document-agent.md).
Diese Seite ist der Schritt danach: mehrere Dokumente und eine Antwort, die
das richtige zitieren muss.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil.
- Ein Embedding-Anbieter und ein Vault-Schlüssel dafür — der festgehaltene Run
  verwendete OpenRouters `text-embedding-3-small`.
  [Eine Knowledge-Base einrichten](set-up-knowledge-base.md) behandelt den
  Erstellen-Dialog vollständig.
- Keine Sandbox und keine weitere Capability.

## Die Eingabe vorbereiten { #prepare-the-input }

Vier kurze Markdown-Dateien, gespeichert als separate Uploads. Die Testdaten
sind erfunden, und zwei Richtlinien teilen sich absichtlich eine Zahl, sodass
eine Frage beide braucht.

`expense-policy.md`:

```text
Employees may claim reimbursement for client meals up to 40 EUR per person.
Travel booked more than 14 days in advance must use economy class for flights
under 6 hours. Mileage for a personal car used on company business is
reimbursed at 0.35 EUR per kilometre. Receipts are required for any claim over
15 EUR. Claims must be submitted within 30 days of the expense.
```

`remote-work-policy.md`:

```text
Employees may work remotely up to 3 days per week without prior approval.
A fully remote arrangement needs sign-off from the department head and HR.
Remote employees must be reachable during core hours, 10:00 to 16:00 in their
local time zone. Equipment for a home office is reimbursed once per employee,
up to 400 EUR, on the same 15 EUR receipt threshold as the expense policy.
```

`onboarding-checklist.md`:

```text
A new employee's manager requests a laptop and accounts in the first week.
IT provisions access within 2 business days of the request. The employee
completes the compliance training module within 30 days of their start date.
The 400 EUR home-office equipment allowance from the remote work policy is
requested through the same IT ticket as the laptop.
```

`travel-booking-guide.md`:

```text
Book flights and hotels through the corporate travel portal. Economy class is
the default for flights under 6 hours, matching the expense policy's advance-
booking rule. Hotel stays are capped at 180 EUR per night in tier-1 cities and
120 EUR elsewhere. A trip that combines client meetings and a conference needs
the sponsoring manager's approval before booking.
```

Die Referenzfakten: Ein Kundenessen ist auf 40 EUR begrenzt (allein aus der
expense policy). Die Home-Office-Pauschale beträgt 400 EUR und wird über das
IT-Ticket für den Laptop beantragt — eine Zahl aus der remote-work policy, ein
Schritt aus der onboarding checklist. Nirgends wird hier eine Kündigungsfrist
genannt.

## Den Agent bauen { #build-the-agent }

1. Benennen Sie unter **Knowledge → New** die Sammlung, erweitern Sie
   **Embeddings** und wählen Sie den Anbieter und das Modell, die zu Ihrem
   Schlüssel passen — der festgehaltene Run verwendete OpenRouter und
   `text-embedding-3-small`. Diese Wahl ist fixiert, sobald die Sammlung
   existiert.
2. Erstellen Sie die Sammlung und laden Sie dann die vier Dateien hoch.
   Warten Sie, bis jede den Status `done` erreicht, bevor Sie weitermachen.
3. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr
   Modellprofil.
4. Aktivieren Sie unter **Toolbox** **Knowledge search** und binden Sie die
   Sammlung, die Sie gerade gefüllt haben. Belassen Sie `default_top_k` auf
   seinem Standardwert; vier kurze Dokumente brauchen nicht mehr.
5. Setzen Sie die folgenden Instruktionen und klicken Sie dann auf
   **Publish**.

```text
Answer questions from the bound HR policy collection.
Cite the document you used for each fact.
If the answer draws on more than one document, name each one.
If the collection does not cover the question, say so rather than guessing.
```

!!! info "Zwei Einstellungen, die Sie kennen sollten, bevor Sie das hier hochskalieren"

    `self_query_enabled` (standardmäßig aus) lässt das Modell Filter wie eine
    Quelle, einen Dokumenttyp oder einen Datumsbereich aus einer Frage wie
    „policies updated last quarter" ableiten — nützlich, sobald Dokumente
    solche Metadaten tragen, und für vier Dateien ohne solche nicht nötig.
    `parent_context` (standardmäßig aus) gibt den Text rund um einen
    getroffenen Chunk zurück statt nur den Chunk selbst, was hilft, wenn eine
    Antwort am Rand eines Chunks sitzt. Beide werden nur aus den eigenen
    expliziten Filtern des Modells gelesen, nie geschrieben, und keiner
    erweitert, welche Sammlungen oder welchen Tenant ein Agent erreichen
    kann. Siehe [die Capability-Referenz](../reference/capabilities.md#knowledge-search).

## Ausführen { #run-it }

Stellen Sie jede Frage in einer neuen Konversation, damit eine frühere
Antwort nicht in die nächste einfließen kann.

```text
How much can I claim for a client meal?
```

```text
I am fully remote. How much is the home-office equipment allowance, and how do I request it?
```

```text
What is the notice period if I want to resign?
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Antwort zum Kundenessen | 40 EUR, zitiert nach `expense-policy.md` |
| Antwort zum Home-Office | 400 EUR, zitiert nach `remote-work-policy.md`, mit dem Beantragungsschritt zitiert nach `onboarding-checklist.md` |
| Kündigungsfrage | Sagt, dass die Sammlung das nicht abdeckt, und erfindet keine Zahl |
| Abgerufene Passagen in Activity | Der Top-Treffer des Kundenessen-Runs ist `expense-policy.md`; die Treffer des Home-Office-Runs umfassen beide Quelldokumente |
| Eine Frage zu den Reisebuchungen der letzten Woche | Beantwortet aus `travel-booking-guide.md`, nicht mit den anderen drei vermischt |

Lesen Sie die abgerufenen Passagen in Activity, nicht nur die Antwort. Ein
Zitat, das die richtige Datei mit der falschen Zahl nennt, oder die richtige
Zahl aus der falschen Datei, sehen im Chat beide korrekt aus.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter, `default_top_k` bei 5. Die
    Frage zum Kundenessen rief `search_documents` einmal auf und antwortete
    „up to €40 per person," unter Zitat von `expense-policy.md`, für 0,0133
    USD. Die Frage zum Home-Office rief drei Dokumente ab und antwortete „up
    to €400," zitierte `remote-work-policy.md` für die Zahl und
    `onboarding-checklist.md` für „the same IT ticket used to request your
    laptop," für 0,0181 USD. Die Kündigungsfrage rief die drei am wenigsten
    relevanten Dokumente ab, fand darin nichts und antwortete „does not
    appear to contain a document covering resignation notice periods," für
    0,0135 USD.

    Der erste Versuch mit diesem Agent band keine Sammlung an den Spec — ein
    Fehler im Testaufbau, nicht am Produkt —, und das Modell antwortete aus
    seinem eigenen Training, statt zuzugeben, dass nichts gebunden war.
    `search_documents` wurde nie aufgerufen. Das Binden der Sammlung und
    erneutes Veröffentlichen behob es; der Unterschied zwischen „kein
    Tool-Aufruf fand statt" und „das Tool lief und fand nichts" ist das
    Erste, was Sie prüfen sollten, wenn eine Antwort selbstsicher wirkt, aber
    die Quelle fehlt.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Der Agent antwortet flüssig, ohne Zitat.** Prüfen Sie in Activity, ob
  `search_documents` überhaupt aufgerufen wurde. Eine Knowledge-Capability
  ohne gebundene Sammlung trägt stillschweigend nichts bei, statt ein Tool zu
  sein, das immer fehlschlägt.
- **Ein Dokument fehlt in einer Antwort, die es verwenden sollte.** Prüfen
  Sie den Status des Dokuments in der Sammlung. Ein Dokument mit Status
  `processing` oder fehlgeschlagen ist für die Suche unsichtbar, ganz gleich
  wie deutlich eine Person es lesen kann.
- **Die Kündigungsfrage bekommt eine selbstsichere, aber falsche Antwort.**
  Die letzte Zeile der Instruktionen — „say so rather than guessing" —
  verwandelt Schweigen in eine Ablehnung. Testen Sie das gezielt, so wie es
  die dritte Frage hier tut.
- **Zwei Dokumente, die sich kombinieren sollten, liefern die Antwort immer
  nur aus einem.** Erhöhen Sie `default_top_k`, oder prüfen Sie, ob die
  Formulierung der Frage das Vokabular des einen Dokuments gegenüber dem
  anderen bevorzugt.
- **Ein synchronisierter Ordner soll diese Sammlung statt manueller Uploads
  speisen.** Siehe [Sync-Quellen einrichten](configure-sync-sources.md) —
  dieselbe Sammlung kann Uploads und einen geplanten Sync mischen.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie die vier Dateien, die Fragen, die Agent-Version, das Modell- und
das Embedding-Profil sowie die abgerufenen Passagen aus Activity für jeden Run
auf — nicht nur die Antworten. Eine Person beurteilt weiterhin, ob ein Zitat
tatsächlich stützt, was der Agent gesagt hat, und ob „nicht abgedeckt" die
richtige Entscheidung war statt einer bequemen.

## Nächste Schritte { #next-steps }

Sobald das Retrieval über Dokumente hinweg zuverlässig funktioniert, stellen
Sie den Agent vor Menschen: [Slack](slack-handbook-assistant.md) ist dasselbe
Muster mit einem Kanal davor. Für einen Korpus, der zu groß zum manuellen
Hochladen ist, nutzen Sie stattdessen
[Sync-Quellen einrichten](configure-sync-sources.md).
