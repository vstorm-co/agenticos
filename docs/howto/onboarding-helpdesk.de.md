---
source_sha: "921578018ea4"
title: "Fragen neuer Mitarbeiter mit Context-Dateien und Skills beantworten"
description: "Binden Sie eine kurze Context-Datei mit festen Fakten und einen Skill mit einer Prozedur an einen Agent und prüfen Sie, welches von beiden welche Art von Frage beantwortet."
---

# Fragen neuer Mitarbeiter mit Context-Dateien und Skills beantworten { #answer-new-hire-questions-with-context-files-and-skills }

Bauen Sie einen Helpdesk für neue Mitarbeiter, der ein paar kleine, feste Fakten immer kennt und nur dann zu einer schriftlichen Prozedur greift, wenn die Frage sie wirklich braucht. Dahinter stehen zwei Capabilities: [Context-Dateien](../context.md) und [Skills](../skills.md). Diese Seite gibt es, weil die falsche Wahl der übliche Grund ist, warum ein Agent entweder ignoriert, was man ihm gesagt hat, oder nie öffnet, was er gebraucht hätte. Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz.

## Was wozu passt { #which-one-fits }

| | Enthält | Das Modell sieht es |
| --- | --- | --- |
| **Context-Datei** | Feste Fakten, klein und stabil: Gehaltstermin, der IT-Kanal | Immer (`inject`) oder bei Bedarf (`link`) |
| **Skill** | Eine Prozedur für eine Art von Aufgabe: wie man Zugang beantragt | Nur wenn das Modell entscheidet, dass genau diese Aufgabe anliegt |
| **Wissenssammlung** | Einen Bestand, zu groß zum vollständigen Lesen: ein ganzes Handbuch, jedes Richtlinien-PDF | Nur die Abschnitte, die eine Suche liefert |

Der Onboarding-Leitfaden unten ist kurz und immer relevant, also ist er eine Context-Datei. "Wie bekomme ich Zugang zu einem System" ist eine Prozedur mit Schritten und einer Ausnahme, also ein Skill. Wenn Ihr Onboarding-Material stattdessen ein fünfzigseitiges Handbuch ist, binden Sie es als [Wissenssammlung](set-up-knowledge-base.md) und nutzen Sie das Muster dieser Seite nur für die kurzen, festen Fakten. Dieselbe Unterscheidung von der Skill-Seite aus beschreibt [Skills oder Wissen?](../skills.md#skills-or-knowledge).

## Was Sie brauchen { #what-you-need }

Eine [laufende Installation](../install.md) mit einem Modellprofil. Keine Sandbox und kein Embedding-Modell: Beide Dateien hier sind klein genug, um sie einzuspeisen oder ganz zu laden.

## Die Eingabe vorbereiten { #prepare-the-input }

Eine Context-Datei mit festen Fakten:

```markdown
# Acme Robotics — new-hire quick facts

- Payroll runs on the last business day of the month.
- The standard laptop is a MacBook Pro; loaner laptops are requested from IT, not HR.
- The internal help channel for IT questions is #it-help.
- Health insurance enrollment is open during your first 30 days; after that, only
  during the November open-enrollment window.
```

Ein Skill für die eine Prozedur, nach der neue Mitarbeiter am häufigsten fragen:

```markdown
# Requesting access

Most access requests go through the #it-help channel, not a person directly.

1. Post in #it-help naming the system and the reason you need it.
2. IT grants standard tools (chat, email, laptop) within one business day.
3. Anything touching customer data (the CRM, production databases) needs your
   manager's written approval first - tag them in the same thread.
4. Access to the payroll system is never granted through chat; email
   payroll@acme-example.com instead.
```

Acme Robotics ist erfunden. Die Referenzfakten: Gehalt am letzten Werktag, standardmäßig ein MacBook Pro, und CRM-Zugang braucht zuerst die Zustimmung der Führungskraft.

## Den Agent bauen { #build-the-agent }

1. Legen Sie unter **Context → New** eine Datei namens `onboarding-guide` an, fügen Sie die Fakten oben ein, setzen Sie **Mode** auf `inject` und geben Sie eine Beschreibung an, die ein Mensch später wiedererkennt.
2. Legen Sie unter **Skills → New** `request-access` mit der Prozedur oben an und mit einer Beschreibung, die für das Modell geschrieben ist: *"When somebody asks how to get access to a tool, a repository, a system, or is not sure who grants it."* Ein verlinkter Skill wird allein nach seinem Namen und dieser Zeile gewählt.
3. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
4. Aktivieren Sie in der **Toolbox** **Context** und binden Sie `onboarding-guide`. Aktivieren Sie **Skills** und binden Sie `request-access`.
5. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You are Acme Robotics' new-hire helpdesk assistant.
Answer from the standing facts you were given, and use a bound skill's
procedure when a question is about how to do something.
If you are not sure, say so rather than guessing.
```

## Ausführen { #run-it }

Fragen Sie zuerst nach einer festen Tatsache, dann nach einer Prozedur:

```text
When does payroll run, and what laptop will I get?
```

```text
How do I get access to the CRM?
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| Frage zu Gehalt und Laptop | Direkt beantwortet, ohne Tool-Aufruf, weil die Context-Datei schon im Prompt steht |
| Frage zum CRM-Zugang | Ruft vor der Antwort `load_capability` für `request-access` auf |
| Die CRM-Antwort | Nennt als ersten Schritt die schriftliche Zustimmung der Führungskraft, nicht nur "post in #it-help" |
| Eine Frage, die die Context-Datei nicht abdeckt (z. B. "what's the dress code?") | Sagt, dass sie es nicht weiß, statt eine Regel zu erfinden |
| Die Context-Datei nachträglich bearbeiten | Der nächste Run spiegelt die Änderung wider, ohne dass der Agent neu veröffentlicht wird |

Die ersten beiden Zeilen sind die Prüfung, auf die es ankommt: Eine Antwort stammt aus Text, der in jedem Prompt steht, die andere aus einem Tool-Aufruf, für den sich das Modell entschieden hat. Passiert eines davon umgekehrt, wurde zur falschen Capability gegriffen.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter. Die Frage zu Gehalt und Laptop verbrauchte 914 Eingabe-Tokens **ohne Tool-Aufruf** und bekam die Antwort: *"Payroll runs on the last business day of the month... The standard laptop is a MacBook Pro"*. Kosten: 0,004 USD.

    Die CRM-Frage rief `load_capability` mit `{"id": "request-access"}` auf, bekam den vollständigen Inhalt des Skills zurück und antwortete: *"Since the CRM touches customer data, there's a specific process... Get your manager's written approval first... Post in #it-help. Tag your manager in the same thread"*. Kosten: 0,009 USD.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Eine feste Tatsache fehlt in einer Antwort.** Prüfen Sie den **Mode** der Context-Datei. Eine `link`-Datei steht gar nicht im Prompt, bis das Modell beschließt, sie zu lesen. Für Fakten, die nie fehlen dürfen, verwenden Sie `inject`.
- **Der Skill wird nie geladen.** Das Modell wählt ihn allein nach Name und Beschreibung. Eine Beschreibung, die wie ein Titel klingt ("Access requests"), sagt ihm weniger als eine, die als *wann man danach greift* formuliert ist.
- **Der Agent trägt den Skill bei jeder Frage vor.** Die Beschreibung des Skills ist zu breit, oder die Instruktionen unterscheiden "feste Tatsache" und "Prozedur" nicht deutlich genug, damit das Modell erkennt, was die Frage ist.
- **Eine bearbeitete Context-Datei ändert die Antwort nicht.** Stellen Sie sicher, dass Sie die Datei der Organisation bearbeitet haben und keine Kopie. Context-Dateien werden per ID gebunden, und es gibt keine eigene Version pro Agent.
- **Statt einer direkten Antwort erscheint ein Skill-Vorschlag.** Der Agent versucht vielleicht, den Skill mitten im Gespräch zu *verbessern*. Das ist ein Vorschlag, den eine Person mit `skills:edit` übernimmt oder verwirft, nichts, was ein Run selbst anwendet. Siehe [Skills](../skills.md#an-agent-can-propose-a-change-a-person-makes-it).

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie Inhalt und IDs beider Dateien, die Agent-Version, beide Fragen und Antworten und die Angabe auf, ob jede einen Tool-Aufruf nutzte. Ein Mensch schreibt und bearbeitet weiterhin die festen Fakten und die Prozedur. Dieses Muster entscheidet nur, wo jeder Text liegt, nicht, wer beim Gehaltstermin recht hat.

## Nächste Schritte { #next-steps }

Derselbe Agent kann statt an die Konsole an einen Slack-Bot für einen Team-Kanal gebunden werden. Siehe [Eine Handbuchfrage in Slack beantworten](slack-handbook-assistant.md), das Bindung, Kontoverknüpfung und die Prüfung beschreibt, welcher Run wem gehört. Wenn das Onboarding-Material über eine oder zwei Seiten hinauswächst, verschieben Sie es in eine [Wissenssammlung](set-up-knowledge-base.md), statt eine eingespeiste Context-Datei zu dehnen.
