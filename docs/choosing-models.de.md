---
source_sha: 5d457ec305b9
---

# Ein Modell wählen { #choosing-a-model }

[Modelle](models.md) erklärt die Mechanik — was ein Profil ist, wie ein Fallback
auslöst, wie ein Run abgerechnet wird. Diese Seite beantwortet die Frage, die
tatsächlich zuerst gestellt wird: **Welches Modell soll dieser Agent nutzen?**

Die kurze Antwort lautet: Das ist nicht eine Entscheidung. Es ist eine
Entscheidung *pro Agent*, und Sie sollen später Ihre Meinung ändern — genau dafür
ist ein [Modellprofil](models.md#a-model-profile) da.

## Drei Fragen entscheiden { #three-questions-decide-it }

Stellen Sie sie in dieser Reihenfolge. Die erste, die eine harte Antwort liefert, gewinnt.

| | Frage | Wenn die Antwort lautet … |
|---|---|---|
| 1 | **Wohin dürfen diese Daten gehen?** | „Nirgendwohin“ — dann wählen Sie zwischen Modellen, die Sie selbst betreiben können. Hier ist Schluss; nichts weiter unten hebt das auf |
| 2 | **Wie schwer ist das Denken?** | Routinemäßiges Extrahieren und Umschreiben ist ein anderes Budget als mehrstufiges Schlussfolgern über einen unordentlichen Korpus |
| 3 | **Wie oft wird der Agent laufen?** | Hundert Unterhaltungen im Monat und hunderttausend sind verschiedene Produkte, selbst bei gleichen Instruktionen |

Die meisten Agents in einem Unternehmen sind Frage 3 mit einer leichten Antwort
auf Frage 2 — eine Support-Antwort, eine Dokumentzusammenfassung, ein aus einer
E-Mail ausgefülltes Formular. Dafür braucht es kein Frontier-Modell, und eines zu
bezahlen ist der häufigste Weg, auf dem ein Agent-Budget verschwindet.

## Was zu wählen ist, je nachdem was der Agent tut { #what-to-pick-by-what-the-agent-does }

| Der Agent … | Greifen Sie zu | Warum |
|---|---|---|
| Antwortet aus Ihren Dokumenten und zitiert sie | Einem **Mittelklasse**-Modell mit großem Kontextfenster | Die Retrieval-Seite erledigt den schweren Teil. Die Aufgabe des Modells ist, zu lesen, was es bekommen hat, und nichts auszuschmücken |
| Klassifiziert, extrahiert, routet, schreibt um | Dem **günstigsten** Modell, das Ihren eigenen Test besteht | Die Aufgabe hat eine richtige Antwort, also ist Qualität messbar und die Untergrenze liegt tiefer, als es sich anfühlt |
| Plant über viele Schritte und Tools hinweg | Einem **Frontier**-Modell | Zu entscheiden, *welches* Tool als Nächstes aufzurufen ist, ist die Stelle, an der günstige Modelle scheitern — und sie scheitern in Schleifen |
| Schreibt etwas, das ein Kunde liest | Einem **Frontier- oder starken Mittelklasse**-Modell | Tonfall und Ablehnungsverhalten sind die Stellen, an denen der Unterschied sichtbar wird, und beide sieht genau die Person, die Sie am wenigsten verärgern wollen |
| Verarbeitet Daten, die das Haus nicht verlassen dürfen | Einem **Open-Weights**-Modell, das Sie selbst hosten | Siehe unten — das ist Frage 1, und es ist kein Qualitätskompromiss, über den sich streiten ließe |

!!! tip "Eine Stufe höher anfangen, dann herunterkommen"

    Bauen Sie den Agent auf einem starken Modell, bis er sich so verhält, wie Sie
    es wollen, wechseln Sie dann im Profil auf ein günstigeres und sehen Sie, ob
    es jemandem auffällt. Andersherum debuggen Sie Ihre Instruktionen und das
    Modell gleichzeitig, und Sie werden dem Falschen die Schuld geben.

## Geschlossene Modelle oder offene Gewichte { #closed-models-or-open-weights }

Beide sind hier gleichrangig. Die 27 Provider umfassen die geschlossenen
Frontier-Labore, die Open-Weights-Hoster und zwei Einträge ohne Schlüssel —
[Ollama](models.md) und einen LiteLLM-Proxy — für Modelle, die auf Ihrer eigenen
Hardware laufen.

| | Geschlossene Modelle (API) | Offene Gewichte (gehostet) | Offene Gewichte (Ihre Hardware) |
|---|---|---|---|
| Beispiele in der Auswahl | Anthropic, OpenAI, Google, xAI | Groq, Together, Fireworks, Nebius, DeepSeek | Ollama, ein LiteLLM-Proxy |
| Beste verfügbare Qualität | Ja, an der Spitze | Nah dran, und holt auf | Begrenzt durch Ihre GPU |
| Daten verlassen Ihr Netz | Ja, zu diesem Anbieter | Ja, zu diesem Hoster | **Nein** |
| Kostenform | Pro Token, ohne Sockel | Pro Token, meist günstiger | Fix — Sie haben die Hardware gekauft |
| Wer eine Regression behebt | Der Anbieter, nach seinem Zeitplan | Der Hoster | Sie, und nur wenn Sie etwas geändert haben |
| Guter Grund dafür | Die Arbeit ist wirklich schwer | Hohes Volumen, gewöhnliche Arbeit | Datenresidenz, oder Volumen, das die Hardware weit übersteigt |

Die ehrliche Zusammenfassung: **Geschlossene Modelle liegen beim schwersten
Schlussfolgern weiterhin vorn, und der Abstand spielt für das meiste, was ein
Unternehmen automatisiert, keine Rolle.** Ein Agent, der ein Richtliniendokument
liest und eine Frage dazu beantwortet, ist keine Frontier-Aufgabe, und ihn auf
selbst gehosteten offenen Gewichten laufen zu lassen ist oft auch die bessere
technische Entscheidung, nicht nur die günstigere.

!!! warning "Ein Modell selbst zu hosten ist eine echte Verpflichtung"

    Eine GPU im Leerlauf wird trotzdem berechnet, jemand muss die Runtime gepatcht
    halten, und ein Modell, das Sie hosten, hat keinen Anbieter, an den Sie
    eskalieren können. Wählen Sie das, wenn Datenresidenz es verlangt oder Ihr
    Volumen die Hardware wirklich weit übersteigt — nicht, um bei vierzig
    Unterhaltungen am Tag Geld zu sparen.

## Ein Gateway davorsetzen { #putting-a-gateway-in-front }

Drei der 27 sind keine Modellanbieter, sondern Router: **OpenRouter**, **Vercel AI
Gateway** und ein **LiteLLM-Proxy**, den Sie selbst betreiben. Jeder gibt Ihnen
einen Schlüssel und einen Endpunkt vor vielen Modellen.

Das lohnt sich, wenn Sie zentrale Ausgabenkontrolle auch über Teams außerhalb von
AgenticOS wollen, oder wenn Sie noch unentschieden sind und mehrere Modelle
ausprobieren möchten, ohne pro Anbieter einen Beschaffungsvorgang zu durchlaufen.
Es kostet Sie einen zusätzlichen Hop, eine zweite Stelle, an der eine Anfrage
scheitern kann, und — bei einem gehosteten Router — ein zweites Unternehmen, das
den Verkehr sieht.

## Was die Rechnung wirklich treibt { #what-actually-drives-the-bill }

Nicht der Modellname. **Der Kontext.**

Die Kosten eines Runs werden davon bestimmt, wie viele Token *hineingehen*, und
hinein gehen Ihre Instruktionen, die abgerufenen Dokumente, die bisherige
Unterhaltung und jedes Tool-Ergebnis. Ein Agent mit einem System-Prompt von 4.000
Wörtern und acht abgerufenen Chunks pro Zug ist auf jedem Modell teuer.

Prüfen Sie also drei Dinge, bevor Sie das Modell wechseln:

- **`default_top_k` bei der Knowledge-Capability.** Acht Chunks, wo drei genügen
  würden, sind die häufigste stille Mehrausgabe.
- **Instruktionen, die sich wiederholen.** Sie werden bei jedem einzelnen Zug gelesen.
- **[Kontextverwaltung](reference/capabilities.md)**, die eine lange Unterhaltung
  im Fenster hält, statt sie vollständig erneut zu senden.

[Budgets](governance.md#budgets) sind das Auffangnetz, nicht der Plan: Ein Budget
stoppt einen Run vor der Modellanfrage, sodass ein falsch eingeschätztes Modell
als Agent auffällt, der aufgehört hat zu antworten, und nicht als Rechnung am
Monatsende.

## Später die Meinung ändern { #changing-your-mind-later }

Ein Modellprofil benennt das Modell; Agents zeigen auf das Profil. **Ändern Sie
das Profil, und jeder Agent, der es nutzt, zieht mit, ohne dass einer davon neu
veröffentlicht wird.**

Das ist der ganze Grund für diese Indirektion, und sie macht den Rat auf dieser
Seite gefahrlos befolgbar: Wählen Sie jetzt etwas Vernünftiges, messen Sie, was
Ihre eigene Arbeit tatsächlich braucht, und wechseln Sie.

Fallbacks liegen auf demselben Profil. Setzen Sie einen zweiten Provider hinter
den ersten, und aus einem Ausfall wird eine langsamere Antwort statt eines
Vorfalls — lohnend bei jedem Agent, den ein Kunde erreichen kann.

## Embeddings sind eine getrennte, dauerhafte Entscheidung { #embeddings-are-a-separate-permanent-choice }

Retrieval nutzt ein Embedding-Modell, und es ist **festgelegt, sobald eine
Collection angelegt wird**. Zwei Modelle gleicher Breite schreiben in
unterschiedliche Vektorräume, und die Suche würde sie weiterhin vergleichen, als
wären sie dasselbe — es zu ändern bedeutet also, die Collection neu zu embedden.

Wählen Sie es einmal, pro Collection, und lesen Sie vorher
[Dateiverarbeitung](file-processing.md).

## Zusammenfassung { #recap }

- Die Wahl gilt **pro Agent**, nicht pro Unternehmen, und ein Modellprofil
  existiert, damit Sie sie später ändern können, ohne irgendetwas neu zu
  veröffentlichen.
- **Wohin die Daten gehen dürfen** steht über jeder anderen Erwägung.
- Die meisten Agents in einem Unternehmen brauchen **kein** Frontier-Modell; bauen
  Sie auf einem, kommen Sie dann herunter und sehen Sie, ob es jemandem auffällt.
- **Der Kontext treibt die Rechnung**, nicht der Modellname — prüfen Sie
  `default_top_k` und Ihre Instruktionen, bevor Sie den Provider wechseln.
- Das **Embedding-Modell ist pro Collection dauerhaft**. Diese eine Wahl treffen
  Sie sorgfältig.

[Die Mechanik: Profile, Provider, Fallbacks und Kosten →](models.md)
