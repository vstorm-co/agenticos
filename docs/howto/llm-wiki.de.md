---
source_sha: "2db3d6fc670a"
title: "Ein LLM-Wiki bauen, das der Agent pflegt"
description: "Geben Sie einem Agent einen Workspace, der Konversationen überdauert, und eine Schema-Datei, und lassen Sie ihn rohe Notizen in ein kleines, verlinktes Markdown-Wiki verwandeln."
---

# Ein LLM-Wiki bauen, das der Agent pflegt { #build-an-llm-wiki-the-agent-maintains }

Andrej Karpathy beschrieb dieses Muster im April 2026: Rohquellen unverändert an einem Ort aufbewahren, einen Agent sie an einem anderen Ort zu einem kleinen, verlinkten Markdown-Wiki kompilieren lassen und das Schema aufschreiben, damit jede spätere Session sich daran prüfen kann, statt das Layout erneut zu raten. Diese Seite baut das auf einem Workspace, der eine einzelne Konversation überdauert, mit zwei synthetischen Quellen, die eine Session auseinander eingepflegt werden.

Dies ist eine Anleitung zum Ausführen, mit einem festgehaltenen Run als Referenz. Die beiden Konversationen zum Einpflegen unten liefen vollständig; die Frage und der Lint-Schritt wurden in diesem Run nicht erreicht und sind entsprechend markiert.

## Was Sie brauchen { #what-you-need }

- Eine [laufende Installation](../install.md) mit einem Modellprofil und einer registrierten [Sandbox-Verbindung](../sandbox.md), die die Runtime `workbench` anbietet.
- Keine weitere Capability. Das Wiki lebt vollständig im Workspace des Agents.

## Die Eingabe vorbereiten { #prepare-the-input }

Zwei kurze Notizen, die unzusammenhängend wirken, aber eine Tatsache teilen, sodass das Wiki einen Grund hat, sie zu verlinken.

Quelle eins, eingefügt in der ersten Konversation:

```text
Meeting notes, 3 March. The team adopts a weekly on-call rotation starting
Monday. Alice is on-call first, then Bob, then Carol, rotating every Monday
at 9am. Escalation rule: if the on-call person does not respond within 15
minutes, page the backup, who is always the previous week's on-call person.
```

Quelle zwei, eingefügt in einer zweiten, getrennten Konversation:

```text
Incident report, 11 March. A database outage occurred on Tuesday. Alice was
on-call and responded within 5 minutes; the backup escalation was not
needed. Root cause: a migration script left a lock unreleased. Fix: the
migration now acquires the lock with a timeout.
```

Die Referenztatsache, die eine Wiki-Seite über beide Notizen hinweg tragen muss: Alice hatte während des Ausfalls Bereitschaft, wegen der am 3. März festgelegten Rotation, und die Vertretungsregel aus derselben Rotation wurde nicht ausgelöst.

## Den Agent bauen { #build-the-agent }

1. Erstellen Sie unter **Agents → New agent** einen Agent und wählen Sie Ihr Modellprofil.
2. Aktivieren Sie in der **Toolbox** **Files & shell**. Wählen Sie **Container**, Ihre Sandbox-Verbindung und die Runtime `workbench`.
3. Setzen Sie den **Session-Scope auf `user`**, nicht auf den Standard `conversation`. Ein Workspace mit Konversations-Scope beginnt im nächsten Chat leer, und genau diesen Fehler "das Wiki vergisst alles" prüft diese Seite. Einer mit Agent-Scope wird von allen in der Organisation geteilt, die mit diesem Agent sprechen, und das ist das falsche Freigabemodell für das Wiki einer Person. `user` behält einen Workspace für die Person über jede Konversation und jede Oberfläche, über die sie den Agent erreicht, und für niemanden sonst. Was jeder Scope teilt, steht unter [Files & shell](../reference/capabilities.md#files-shell).
4. Legen Sie Budget und Schrittlimit für den Versuch fest.
5. Setzen Sie die Instruktionen unten und klicken Sie dann auf **Publish**.

```text
You maintain a small personal LLM wiki in your workspace: raw sources
compiled into a cross-linked Markdown wiki, following this schema.

Layout:
raw/<slug>.md - one file per ingested source, saved verbatim, append-only.
Never edit a raw file once written.
wiki/index.md - one line per wiki page, each a Markdown link to it.
wiki/<topic>.md - one page per topic, written in your own words from the raw
sources. Link related pages with a relative Markdown link.
schema.md - this layout, written once on your first turn if it does not
exist, so any later session can check itself against it.

When asked to ingest a source: read schema.md first, writing it if it is
missing; list wiki/ so you know what exists; save the source verbatim to
raw/<slug>.md; update an existing wiki page if the source is about it, or
create a new one only for a genuinely new topic; cross-link pages that refer
to each other; update wiki/index.md; report which files you touched.

When asked a question, read the relevant wiki page(s) - not the raw sources,
unless a page is missing something the question needs - and answer citing
the page you used by name.

When asked to lint the wiki: list every file, read wiki/index.md and every
page it links to, then report broken links, orphan pages nothing links to,
and any two pages that state different facts about the same thing. Do not
fix anything unless asked; only report.
```

Das Schema steht hier in den Instruktionen, weil es kurz ist. Ein Schema, das über einen oder zwei Absätze hinauswächst, passt besser in eine [Context-Datei](../context.md) im Modus `link`, einmal gelesen und von jedem Agent geteilt, der auf diese Weise ein Wiki pflegt, statt sie in die Instruktionen jedes einzelnen einzufügen.

## Ausführen { #run-it }

In einer ersten, neuen Konversation:

```text
Ingest this source: [paste source one]
```

Beginnen Sie eine **zweite, neue Konversation** mit demselben Agent, keine Antwort in der ersten, und bitten Sie ihn, die zweite Quelle einzupflegen und dann die Frage zu beantworten:

```text
Ingest this source: [paste source two]
```

```text
Who was on-call during the outage, and what is the backup escalation rule?
```

Bitten Sie in einer dritten Runde oder einer dritten Konversation um die Prüfung, um die herum das Muster gebaut ist:

```text
Lint the wiki.
```

## Das Ergebnis prüfen { #check-the-result }

| Prüfung | Referenz |
| --- | --- |
| `schema.md` nach der ersten Konversation | Existiert und entspricht dem Layout aus den Instruktionen |
| Workspace zu Beginn der zweiten Konversation | Enthält bereits `schema.md`, `raw/` und `wiki/` aus der ersten; nichts wird neu angelegt |
| Wiki-Seiten nach beiden Quellen | Erwähnen Alice, die Reihenfolge der Rotation und den Ausfall; die beiden Themen verlinken aufeinander, statt als zwei unverbundene Seiten dazuliegen |
| Antwort auf die Frage | Nennt Alice, zitiert die Wiki-Seiten und stellt fest, dass die Vertretungsregel nicht ausgelöst wurde |
| Lint-Bericht | Nennt jeden defekten Link und jede verwaiste Seite wahrheitsgemäß, einschließlich "none found", statt eines allgemeinen "looks good" |
| Eine dritte Konversation mit einer Frage, ohne etwas Neues einzupflegen | Liest das vorhandene Wiki und antwortet trotzdem, weil der Workspace der Person gehört, nicht der Konversation |

Lesen Sie die tatsächlichen Dateien im Dateibereich der Konversation, nicht nur die Antwort. Ein Modell, das beschreibt, einen Querverweis zu aktualisieren, und eines, das ihn wirklich geschrieben hat, sehen in Prosa gleich aus.

!!! example "Festgehalten auf v0.0.504, 25. September 2026"

    Modell: Claude Sonnet 4.6 über OpenRouter, Runtime `workbench`, `session_scope: user`. Die erste Konversation fand weder `schema.md` noch `wiki/`, schrieb beides nach dem Layout der Instruktionen, speicherte die Bereitschaftsnotiz unter `raw/meeting-notes-2024-03-03.md` und legte `wiki/on-call-rotation.md` und `wiki/index.md` an. Es gab keinen `execute`-Aufruf, also war keine Genehmigung nötig. Kosten: 0,1022 USD.

    Eine zweite, getrennte Konversation mit demselben Agent begann mit dem Lesen von `schema.md` und dem Auflisten von `wiki/` und fand beides vor: Der Workspace war erhalten geblieben. Sie speicherte den Vorfallbericht unter `raw/incident-report-11-march.md`, legte `wiki/database-incidents.md` mit Alice, der 5-Minuten-Reaktion und der Ursache an, fügte dann per `edit_file` in `wiki/on-call-rotation.md` einen Abschnitt "Incidents" mit Link auf die neue Seite hinzu und aktualisierte `wiki/index.md`, sodass beide Seiten aufgeführt sind. Das ist ein echter Querverweis in beide Richtungen, keine zwei Seiten nebeneinander. Kosten: 0,1250 USD.

    Ein Infrastrukturausfall, der weder mit dem Agent noch mit der Sandbox zu tun hatte, stoppte den Versuch an dieser Stelle. Die Frage ("Who was on-call during the outage...") und der Lint-Schritt wurden nicht ausgeführt, die entsprechenden Zeilen der Tabelle oben sind also die erwartete Referenz, kein beobachtetes Ergebnis. Bestätigt ist der Teil, den diese Seite prüfen soll: Der Workspace hat eine völlig getrennte Konversation überdauert, und die beiden Themen haben sich verlinkt, statt Inhalt zu duplizieren.

## Wenn etwas schiefgeht { #when-it-goes-wrong }

- **Die zweite Konversation beginnt mit einem leeren Workspace.** Der Scope ist `conversation`, oder `agent` bindet an eine andere Standardverbindung als der erste Run, oder Verbindung oder Backend haben sich zwischen den beiden geändert. Jeder dieser Fälle startet einen frischen Workspace, statt den alten wieder anzubinden.
- **Zwei Seiten wiederholen sich, statt sich zu verlinken.** Das Modell hat `wiki/index.md` vor dem Schreiben nicht gelesen. Verschärfen Sie die Instruktionen, sodass jedes Mal zuerst das Wiki aufgelistet werden muss.
- **Der Lint-Bericht sagt immer, dass alles in Ordnung ist.** Lassen Sie ein Wiki prüfen, von dem Sie wissen, dass es ein Problem hat (benennen Sie vorher eine verlinkte Datei um), um zu prüfen, ob der Bericht die Dateien liest, statt etwas anzunehmen.
- **`schema.md` wird in jeder Konversation neu geschrieben.** Die Instruktionen sagen, es nur zu schreiben, wenn es fehlt. Wenn das Modell es trotzdem neu schreibt, sagen Sie ihm ausdrücklich, vor jedem Schreiben zu lesen.
- **Eine Kollegin sieht Notizen, die Sie für privat hielten.** Prüfen Sie den Session-Scope. `agent` teilt einen Workspace mit allen, die mit diesem Agent sprechen, und genau deshalb warnt der Builder an diesem Feld.

## Den Versuch festhalten { #record-the-trial }

Bewahren Sie beide Rohquellen, die genauen Prompts, die Agent-Version und die Dateiliste des Workspaces nach jeder Konversation auf, nicht nur die Antworten. Ein Mensch beurteilt weiterhin, ob ein Querverweis wirklich nützlich oder nur vorhanden ist und ob der Lint-Bericht etwas Echtes gefunden hat.

## Wiki oder Wissenssuche? { #wiki-or-knowledge-search }

Sie beantworten unterschiedliche Bedürfnisse. Die [Wissenssuche](../reference/capabilities.md#knowledge-search) holt Passagen aus Dokumenten, die niemand umschreibt, etwa einem unterzeichneten Vertrag oder einem Richtlinien-PDF, und zitiert den Quellabschnitt. Dieses Muster ist für Material, das unordentlich und klein beginnt und die Zeit eines Agents für das *Kompilieren* wert ist: Notizen, Transkripte, halbfertige Ausarbeitungen, die davon profitieren, in wenige gepflegte Seiten statt in einen wachsenden Stapel Quelldateien verwandelt zu werden. Sobald das kompilierte Wiki selbst zu groß wird, um es einzuspeisen oder ganz zu lesen, ist es der natürliche nächste Schritt, es wie jede andere Sammlung zu durchsuchen statt als Datei im Workspace.

## Nächste Schritte { #next-steps }

Pflegen Sie absichtlich eine Quelle ein, die einer früheren widerspricht, und prüfen Sie, ob der Lint-Schritt beide Seiten nennt, statt still eine Seite zu wählen. Für ein Wiki, das mehrere Personen lesen und erweitern sollen, wägen Sie den Session-Scope `agent` gegen die Möglichkeit ab, jeder beitragenden Person einen eigenen Agent zu geben, der an eine gemeinsame [Context-Datei](../context.md) gebunden ist.
