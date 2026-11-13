---
source_sha: "12c6776e073b"
---

# Jeder Bildschirm der Konsole { #every-screen-in-the-console }

Aktuelle Aufnahmen der Demo-Organisation Northwind Labs vom 2. November 2026 mit AgenticOS 1.35.3. Unternehmensdaten, Umsätze, Lieferungen und Anlagen sind fiktiv. Vorbereitete Visuals sind gekennzeichnet; es besteht keine Verbindung zu CRM, ERP oder Maschinen. Die Aufnahmen zeigen das vollständige Anwendungsfenster.

## Wo Sie landen { #where-you-land }

### Dashboard { #dashboard }

Ihre eigene Ansicht, die anordenbare der Organisation, die einer Gruppe und - für einen Deployment-Admin - die des ganzen Deployments, oben gewählt. Runs, Ausgaben, Dienstzustand und Antwortqualität; jede Karte ist an der Permission gemessen, die ihre eigenen Daten verlangen, sodass eine Karte, deren primären Lesezugriff Sie nicht machen dürfen, Ihnen gar nicht angeboten wird.

![Dashboard](assets/screens/light/dashboard.webp?v=20261102-industrial#only-light)
![Dashboard](assets/screens/dark/dashboard.webp?v=20261102-industrial#only-dark)

### Chat { #chat }

Eine vorbereitete Vertriebsübersicht mit Revenue Pulse im Visuals-Renderer. Umsatz, Ziele und Teambeiträge ändern sich mit Region und Zeitraum. Gespräch und Daten sind vorbereitete Beispiele, kein Nachweis einer Dashboard-Erzeugung durch ein Modell.

![Chat](assets/screens/light/chat.webp?v=20261102-industrial#only-light)
![Chat](assets/screens/dark/chat.webp?v=20261102-industrial#only-dark)

## Einen Agent bauen { #building-an-agent }

### Agents { #agents }

Der Katalog. Jeder Agent trägt die Version, die live ist, wer ihn erreichen darf und ob ein Entwurf wartet. Ein Agent ist Konfiguration, kein Code - deshalb ist diese Liste für alle bearbeitbar, die die Antwort kennen.

![Agents](assets/screens/light/agents.webp?v=20261102-industrial#only-light)
![Agents](assets/screens/dark/agents.webp?v=20261102-industrial#only-dark)

### Agent templates { #agent-templates }

Templates nach Branche, über dem Katalog. Eines zu installieren erzeugt einen Entwurf, den Sie fertigstellen und veröffentlichen; bis dahin läuft nichts.

![Agent templates](assets/screens/light/agent-templates.webp?v=20261102-industrial#only-light)
![Agent templates](assets/screens/dark/agent-templates.webp?v=20261102-industrial#only-dark)

### Skills { #skills }

Einmal aufgeschriebenes Know-how, das jeder daran gebundene Agent teilt - wie Rückerstattungen gehandhabt werden, was der Hausstil ist. Bearbeiten Sie es hier, und jeder gebundene Agent ist beim nächsten Run auf dem aktuellen Stand.

![Skills](assets/screens/light/skills.webp?v=20261102-industrial#only-light)
![Skills](assets/screens/dark/skills.webp?v=20261102-industrial#only-dark)

### Skill gallery { #skill-gallery }

Skills nach Branche. Beim Installieren wird einer in Ihre Organisation kopiert, wo Sie ihn bearbeiten können - eine Kopie, damit die Quelle nicht ändern kann, was Ihre Agents sagen.

![Skill gallery](assets/screens/light/skill-gallery.webp?v=20261102-industrial#only-light)
![Skill gallery](assets/screens/dark/skill-gallery.webp?v=20261102-industrial#only-dark)

### Ein Skill { #one-skill }

Zum Bearbeiten geöffnet, mit seiner Kategorie. Der Name, auf den sich das Modell bezieht, steht beim Anlegen fest und kann sich nicht ändern; alles andere hier schon.

![Ein Skill](assets/screens/light/skill-detail.webp?v=20261102-industrial#only-light)
![Ein Skill](assets/screens/dark/skill-detail.webp?v=20261102-industrial#only-dark)

### Context { #context }

Stehender Kontext, aus dem jeder Agent schöpfen kann - ein Glossar, eine Richtlinie, eine Markenstimme. In den Prompt eingespielt oder bei Bedarf gelesen, und aktuell in dem Moment, in dem Sie ihn bearbeiten.

![Context](assets/screens/light/context.webp?v=20261102-industrial#only-light)
![Context](assets/screens/dark/context.webp?v=20261102-industrial#only-dark)

## In einem Agent { #inside-one-agent }

Der Builder, Tab für Tab.

### Build { #build }

Instruktionen, Modell und Endpunkt. Das Verhalten wohnt hier statt im Code, in Markdown, das das Modell als Struktur liest - und der Kopfbereich trägt `published` neben `Draft differs from agent v40`, was der ganze Punkt ist: Bearbeiten geht nicht live.

![Build](assets/screens/light/agent-builder.webp?v=20261102-industrial#only-light)
![Build](assets/screens/dark/agent-builder.webp?v=20261102-industrial#only-dark)

### Toolbox { #toolbox }

Jede Capability als Schalter - Wissenssuche, ein Browser, Python in einer Sandbox, Diagramme, Delegation - und daneben jeweils das Approval-Gate pro Tool. Konfiguration erreicht nur, was Code registriert hat.

![Toolbox](assets/screens/light/agent-toolbox.webp?v=20261102-industrial#only-light)
![Toolbox](assets/screens/dark/agent-toolbox.webp?v=20261102-industrial#only-dark)

### MCP servers { #mcp-servers }

Welche Verbindungen dieser Agent erreichen darf und welche ihrer Tools. Die Liste der Organisation begrenzt ihn weiterhin; ein Agent kann darin enger werden und nicht darüber hinausreichen.

![MCP servers](assets/screens/light/agent-mcp.webp?v=20261102-industrial#only-light)
![MCP servers](assets/screens/dark/agent-mcp.webp?v=20261102-industrial#only-dark)

### Limits { #limits }

Eine Monatsobergrenze und eine Schrittgrenze. Die Obergrenze wird vor jeder Modellanfrage geprüft, und die Schrittgrenze fängt die andere Entgleisung ab - eine Tool-Schleife, die pro Aufruf billig ist und nie endet.

![Limits](assets/screens/light/agent-limits.webp?v=20261102-industrial#only-light)
![Limits](assets/screens/dark/agent-limits.webp?v=20261102-industrial#only-dark)

### Availability { #availability }

Wo dieser Agent antwortet: das Dashboard und die API immer, dazu jeder Chat-Bot, der hier gebunden ist. Ein Agent ist per `@handle` nur auf den Bots erwähnbar, an die er gebunden ist.

![Availability](assets/screens/light/agent-availability.webp?v=20261102-industrial#only-light)
![Availability](assets/screens/dark/agent-availability.webp?v=20261102-industrial#only-dark)

### Routines, am Agent { #routines-on-the-agent }

Was er tut, wenn niemand tippt, auf demselben Tab - ein Zeitplan, der sich pausieren lässt, oder ein Event-Trigger.

![Routines, am Agent](assets/screens/light/agent-routines.webp?v=20261102-industrial#only-light)
![Routines, am Agent](assets/screens/dark/agent-routines.webp?v=20261102-industrial#only-dark)

### History { #history }

Jede Version, die dieser Agent hatte. Die, die im März live war, ist immer noch lesbar, und das macht ein Zurückrollen zu einer Entscheidung statt zu einem Ausgrabungsprojekt.

![History](assets/screens/light/agent-history.webp?v=20261102-industrial#only-light)
![History](assets/screens/dark/agent-history.webp?v=20261102-industrial#only-dark)

### Visual map { #visual-map }

Derselbe Agent als Graph: was ihn erreicht und wonach er greift. Ein gestrichelter Kasten ist etwas, an dem nichts hängt - ein Budget ohne eigene Obergrenze liest sich als Lücke statt als Default.

![Visual map](assets/screens/light/agent-map.webp?v=20261102-industrial#only-light)
![Visual map](assets/screens/dark/agent-map.webp?v=20261102-industrial#only-dark)

## Workflows und Tabellen { #workflows-and-tables }

### Workflows { #workflows }

Der Katalog der Automatisierungen, eine Karte pro Workflow: sein Status, wer ihn erreichen kann, ob eine Version live ist und wann er zuletzt bearbeitet wurde, mit seinen Runs, dem Editor und einer Kopie einen Klick entfernt.

![Workflows](assets/screens/light/workflows.webp?v=20261102-industrial#only-light)
![Workflows](assets/screens/dark/workflows.webp?v=20261102-industrial#only-dark)

### Der Workflow-Editor { #the-workflow-editor }

Die Zeichenfläche hat die ganze Breite: der Graph als Karten, die sagen, wofür jeder Schritt eingerichtet ist oder zu welcher Gruppe er gehört, die Einstellungen eines Schritts in einem Dialog darüber und jeder Schritt zum Hinzufügen einen Klick - oder einen Rechtsklick - entfernt. Eine Schleife zeigt, wie viele Schritte ihr Körper enthält.

![Workflow editor](assets/screens/light/workflow-editor.webp?v=20261102-industrial#only-light)
![Workflow editor](assets/screens/dark/workflow-editor.webp?v=20261102-industrial#only-dark)

### Der Körper einer Schleife { #a-loops-body }

Innerhalb der Schleife: das aktuelle Unternehmen, die Zuordnung für seinen Datensatz und der Schritt zum Sammeln des Ergebnisses. Das lokale Beispiel verarbeitet drei fiktive Unternehmensnamen ohne externe Zugangsdaten.

![Workflow loop body](assets/screens/light/workflow-loop-body.webp?v=20261102-industrial#only-light)
![Workflow loop body](assets/screens/dark/workflow-loop-body.webp?v=20261102-industrial#only-dark)

### Runs { #runs }

Jeder Run eines Workflows, die neuesten zuerst: ob er den Draft oder die veröffentlichte Version ausgeführt hat, was ihn gestartet hat, wann, wie lange und zu welchen Kosten. **Start a run** testet den Draft mit einem eigenen Input.

![Workflow runs](assets/screens/light/workflow-runs.webp?v=20261102-industrial#only-light)
![Workflow runs](assets/screens/dark/workflow-runs.webp?v=20261102-industrial#only-dark)

### Ein Run { #a-run }

Ein Run, wie er abgelaufen ist: der Graph, den er ausgeführt hat, jeder Schritt markiert mit dem, was er getan hat, die Ausgabe, mit der er geantwortet hat, und jeder Schritt, den er gemacht hat, Iteration für Iteration.

![Workflow run](assets/screens/light/workflow-run.webp?v=20261102-industrial#only-light)
![Workflow run](assets/screens/dark/workflow-run.webp?v=20261102-industrial#only-dark)

### Tabellen { #tables }

Die fiktive Vertriebspipeline als Kanban: eine Verkaufschance pro Karte, nach Phase gruppiert. Agenten und Workflows arbeiten mit denselben typisierten Datensätzen; das Board ist hier die Hauptansicht.

![Tables](assets/screens/light/table-kanban.webp?v=20261102-industrial#only-light)
![Tables](assets/screens/dark/table-kanban.webp?v=20261102-industrial#only-dark)

## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Collections. Fassen Sie zusammengehörige Dokumente zu einer zusammen und wählen Sie dann im Chat, welche Collections ein Agent durchsuchen darf.

![Knowledge bases](assets/screens/light/knowledge-bases.webp?v=20261102-industrial#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp?v=20261102-industrial#only-dark)

### Eine Collection { #a-collection }

Ihre Dokumente, deren Chunk-Zahlen und alles, was bei der Ingestion mit Begründung gescheitert ist. Chunk-Grenzen sind das, wogegen eine Suche abgleicht, also wird ein nach einer Einstellungsänderung erneut hochgeladenes Dokument neu gechunkt.

![Eine Collection](assets/screens/light/knowledge-collection.webp?v=20261102-industrial#only-light)
![Eine Collection](assets/screens/dark/knowledge-collection.webp?v=20261102-industrial#only-dark)

### Parsing, pro Upload { #parsing-per-upload }

Die Wahl, die sonst niemand offenlegt: **PyMuPDF**, **LiteParse** oder **LlamaParse**, die Chunking-Strategie, Chunk-Größe und Überlappung, OCR und dessen Sprache. An der Collection gesetzt und bei der nächsten Datei überschreibbar - denn eine eingescannte Preisliste und ein Markdown-Runbook wollen nicht denselben Parser, und der falsche ist der Unterschied zwischen einer Antwort und einer Absage.

![Parsing, pro Upload](assets/screens/light/kb-parse-options.webp?v=20261102-industrial#only-light)
![Parsing, pro Upload](assets/screens/dark/kb-parse-options.webp?v=20261102-industrial#only-dark)

## Einen Agent testen und verbessern { #testing-and-improving-an-agent }

Diese Ansichten stammen aus einer zweiten Demo-Organisation, Demo, und ihrem Agent Refund desk: Fragen eines Acme-Shops zu Erstattungen und Lieferung, bewertet von Checks und einem Judge. Die Fragen sind erfunden; die Antworten, Bewertungen und Verbesserungssitzungen sind echte Runs.

### Datasets { #datasets }

Die Testfragen, an denen Ihre Agents geprüft werden. Jede Änderung an den Fällen eines Datasets erzeugt eine neue Version, damit zwei Eval-Runs auf denselben Fragen verglichen werden oder gar nicht.

![Datasets](assets/screens/light/datasets.webp#only-light)
![Datasets](assets/screens/dark/datasets.webp#only-dark)

### Die Fälle eines Datasets { #a-datasets-cases }

Jede Frage mit ihrer Herkunft, der Zahl ihrer Checks und ob die Verbesserung sie zum Schreiben der Änderungen nutzt oder zurücklegt, um das Ergebnis zu prüfen.

![Die Fälle eines Datasets](assets/screens/light/dataset-cases.webp#only-light)
![Die Fälle eines Datasets](assets/screens/dark/dataset-cases.webp#only-dark)

### Bewertung { #grading }

Was eine Antwort bestehen lässt: die Checks, die jeder Fall bekommt, welcher Judge bewertet, nach welchen Kriterien und ab welcher Punktzahl. Checks kosten nichts; jede Bewertung durch den Judge ist ein Run auf einem Modell.

![Bewertung](assets/screens/light/dataset-grading.webp#only-light)
![Bewertung](assets/screens/dark/dataset-grading.webp#only-dark)

### Die Evals eines Datasets { #a-datasets-evals }

Jeder Run gegen dieses Dataset als Bestehensquote-Linie pro Agent; die Farbe eines Punkts zeigt, ob er Fälle repariert oder gebrochen hat, darunter die Liste der Runs.

![Die Evals eines Datasets](assets/screens/light/dataset-evals.webp#only-light)
![Die Evals eines Datasets](assets/screens/dark/dataset-evals.webp#only-dark)

### Ein Eval-Run { #one-eval-run }

Zuerst das Urteil in einem Satz, dann die Bestehensquote vorher und nachher, die Kosten gegenüber der Schätzung und die Fälle, die sich geändert haben. Eine Antwort, die bei erneutem Fragen anders ausfiel, zählt nicht als Änderung.

![Ein Eval-Run](assets/screens/light/eval-run.webp#only-light)
![Ein Eval-Run](assets/screens/dark/eval-run.webp#only-dark)

### Die Evals eines Agents { #an-agents-evals }

Derselbe Verlauf aus Sicht des Agents: jedes Dataset, gegen das er lief, eine Linie pro Dataset, daneben der Knopf zum Starten der Evals.

![Die Evals eines Agents](assets/screens/light/agent-evals.webp#only-light)
![Die Evals eines Agents](assets/screens/dark/agent-evals.webp#only-dark)

### Verbessern { #improve }

Wo eine Verbesserung beginnt: die negativ bewerteten Antworten, die fehlgeschlagenen Testantworten, wie sich die Testfragen auf das Schreiben der Änderungen und ihre Prüfung aufteilen, und was der erste Schritt kostet. Jeder weitere Schritt wird bepreist, bevor Sie ihn drücken.

![Verbessern](assets/screens/light/improve-start.webp#only-light)
![Verbessern](assets/screens/dark/improve-start.webp#only-dark)

### Verbessern · Verstehen { #improve-understand }

Was schiefging, sortiert danach, was der Agent beheben kann und was der Wissensbasis fehlt, eine Karte pro Frage mit den Bewertungen in Worten. Die Sitzung hält hier an, damit Sie es sich ansehen.

![Verbessern · Verstehen](assets/screens/light/improve-understand.webp#only-light)
![Verbessern · Verstehen](assets/screens/dark/improve-understand.webp#only-dark)

### Verbessern · Änderungen { #improve-changes }

Die Änderungen, die der Helfer geschrieben hat, als Diff des eigenen Texts des Agents, mit Begründung und dem, worauf sie beruhen. Sie können eine Änderung umformulieren, bevor sie geprüft wird; die Prüfung misst Ihre Formulierung.

![Verbessern · Änderungen](assets/screens/light/improve-changes.webp#only-light)
![Verbessern · Änderungen](assets/screens/dark/improve-changes.webp#only-dark)

### Verbessern · Ergebnis { #improve-result }

Wozu die Sitzung kam: jeder Versuch mit der Zahl der zurückgelegten Fragen, die er repariert und gebrochen hat, seinen Kosten und der Wahl, welcher Versuch bleibt. Nichts geht live, bevor ein Mensch es annimmt.

![Verbessern · Ergebnis](assets/screens/light/improve-result.webp#only-light)
![Verbessern · Ergebnis](assets/screens/dark/improve-result.webp#only-dark)

### Wissenslücken { #knowledge-gaps }

Fragen, für die ein Agent seine Wissensbasen durchsucht und nichts Passendes gefunden hat, nach Thema gruppiert. Nichts gelangt von selbst in eine Wissensbasis; ein Mensch entwirft das Dokument und fügt es hinzu.

![Wissenslücken](assets/screens/light/knowledge-gaps.webp#only-light)
![Wissenslücken](assets/screens/dark/knowledge-gaps.webp#only-dark)


## Was passiert ist, und was wartet { #what-happened-and-what-is-waiting }

### Runs { #runs }

Jeder Run, den diese Organisation gemacht hat, mit Status, Oberfläche, Modell, Person und Kosten. Ein Run ist der Prozess: Er startet, er lässt sich stoppen, und er hinterlässt einen Eintrag.

![Runs](assets/screens/light/activity.webp?v=20261102-industrial#only-light)
![Runs](assets/screens/dark/activity.webp?v=20261102-industrial#only-dark)

### Ein Run, geöffnet { #one-run-opened }

Token hinein und hinaus, Kosten auf vier Nachkommastellen, wie lange es gedauert hat, und die Zeitleiste jedes Zuges und Tool-Aufrufs. Der Chat, in dem es passiert ist, ist einen Klick entfernt.

![Ein Run, geöffnet](assets/screens/light/run-detail.webp?v=20261102-industrial#only-light)
![Ein Run, geöffnet](assets/screens/dark/run-detail.webp?v=20261102-industrial#only-dark)

### Approvals { #approvals }

Alles, was auf einen Menschen wartet, mit dem, was der Agent vorhat. Eine Approval wird genau einmal entschieden - eine zweite Entscheidung über eine erledigte wird abgelehnt, und dieses Detail macht das Gate erst wertvoll.

![Approvals](assets/screens/light/approvals.webp?v=20261102-industrial#only-light)
![Approvals](assets/screens/dark/approvals.webp?v=20261102-industrial#only-dark)

### Spend { #spend }

Was tatsächlich ausgegeben wurde, nach Zeitraum. Ein Budget wird _vor_ der Modellanfrage geprüft statt hinterher zusammengezählt, also stoppt ein Run, der eines reißt, mitten in der Antwort und verzeichnet seine Kosten trotzdem.

![Spend](assets/screens/light/spend.webp?v=20261102-industrial#only-light)
![Spend](assets/screens/dark/spend.webp?v=20261102-industrial#only-dark)

### Routines { #routines }

Was Agents tun, wenn niemand tippt - nach Zeitplan oder wenn ein Ereignis eintrifft. Diese Runs sind budgetiert, freigegeben und auditiert wie alle anderen.

![Routines](assets/screens/light/routines.webp?v=20261102-industrial#only-light)
![Routines](assets/screens/dark/routines.webp?v=20261102-industrial#only-dark)

### Ein neuer Event-Trigger { #a-new-event-trigger }

Das Ereignis benennen, das einen Run startet, über der Liste der Routines.

![Ein neuer Event-Trigger](assets/screens/light/routine-event-trigger.webp?v=20261102-industrial#only-light)
![Ein neuer Event-Trigger](assets/screens/dark/routine-event-trigger.webp?v=20261102-industrial#only-dark)

### Apps { #apps }

Seiten, die Agents veröffentlicht haben - Berichte, kleine Dashboards, Zusammenfassungen. Jede behält ihren Link, wenn der Agent sie erneut veröffentlicht, und ihre früheren Versionen bleiben lesbar.

![Apps](assets/screens/light/apps.webp?v=20261102-industrial#only-light)
![Apps](assets/screens/dark/apps.webp?v=20261102-industrial#only-dark)

### Eine App { #one-app }

Northline verbindet eine europäische Lieferantenkarte, Lieferausnahmen und Montagefenster. Verzögerungen simulieren, Lieferungen filtern und Abhängigkeiten prüfen: eine vorbereitete lokale Planungs-App ohne ERP- oder Speditionsanbindung.

![Northline](assets/screens/light/app-manufacturing.webp?v=20261102-industrial#only-light)
![Northline](assets/screens/dark/app-manufacturing.webp?v=20261102-industrial#only-dark)

### Motor Atlas { #motor }

Eine konzeptionelle Motor-Explosionsansicht mit auswählbaren Komponenten, Abstandsregler, fiktiver Stückliste und Beispieltelemetrie. Eine interaktive Erklärung, keine CAD-Zeichnung, Diagnose oder Wartungsanweisung.

![Motor Atlas](assets/screens/light/app-motor.webp?v=20261102-industrial#only-light)
![Motor Atlas](assets/screens/dark/app-motor.webp?v=20261102-industrial#only-dark)

### Revenue Pulse { #revenue }

Eine interaktive Vertriebsübersicht mit Umsatz und Ziel, Pipeline, Teambeiträgen und anstehenden Chancen. Summen werden aus fiktiven Demozeilen berechnet; Region und Zeitraum funktionieren lokal.

![Revenue Pulse](assets/screens/light/app-revenue.webp?v=20261102-industrial#only-light)
![Revenue Pulse](assets/screens/dark/app-revenue.webp?v=20261102-industrial#only-dark)

### Visuals { #visuals-in-the-conversation }

Das vorbereitete Revenue-Pulse-Visual im echten Chat-Renderer. Es lässt sich als App speichern; die Aufnahme zeigt keinen neuen Modelllauf und keinen Zugriff auf ein angebundenes CRM.

![Visuals](assets/screens/light/chat-hero.webp?v=20261102-industrial#only-light)
![Visuals](assets/screens/dark/chat-hero.webp?v=20261102-industrial#only-dark)

## Die Organisation { #the-organization }

### Organizations { #organizations }

Zwischen ihnen wechseln, Mitglieder verwalten und neue anlegen. Autorität innerhalb einer Organisation ist eine Mitgliedschaftszeile plus der Permission-Katalog - es gibt keine Rollenspalte an einem Nutzer.

![Organizations](assets/screens/light/organizations.webp?v=20261102-industrial#only-light)
![Organizations](assets/screens/dark/organizations.webp?v=20261102-industrial#only-dark)

### Members { #members }

Die Menschen einer Organisation und ihre Rollen, mit dem Monatslimit, das sich alle ihre Agents teilen, und der Einstellung, ob eine Unterhaltung ihre Approvals überspringen darf.

![Members](assets/screens/light/members.webp?v=20261102-industrial#only-light)
![Members](assets/screens/dark/members.webp?v=20261102-industrial#only-dark)

### Roles { #roles }

Was jede Rolle darf, als die Matrix, die der Code definiert. Das Teilen einer einzelnen Ressource kann den Zugriff über die Rolle hinaus erweitern; es schränkt ihn nie ein.

![Roles](assets/screens/light/roles.webp?v=20261102-industrial#only-light)
![Roles](assets/screens/dark/roles.webp?v=20261102-industrial#only-dark)

### Groups { #groups }

Abteilungen und Teams. Teilen Sie einen Agent, eine Wissensdatenbank, einen Skill oder eine Kontextdatei mit einer Gruppe, und alle darin können ihn nutzen - Menschen außerhalb nicht.

![Groups](assets/screens/light/groups.webp?v=20261102-industrial#only-light)
![Groups](assets/screens/dark/groups.webp?v=20261102-industrial#only-dark)

### Vault { #vault }

Jeder Schlüssel, den diese Organisation gespeichert hat, pro Mandant versiegelt. Ersetzbar, nie wieder lesbar; und eine Rotation ist für einen veröffentlichten Agent unsichtbar, weil er das Secret referenziert und nicht dessen Wert.

![Vault](assets/screens/light/vault.webp?v=20261102-industrial#only-light)
![Vault](assets/screens/dark/vault.webp?v=20261102-industrial#only-dark)

### MCP servers { #mcp-servers_1 }

Verbinden Sie jeden MCP-Server per URL, und seine Tools werden zu Schaltern im Builder. Verbinden Sie ihn für die Organisation, und jeder Agent darf ihn nutzen; verbinden Sie ihn für sich selbst, und er bleibt in Ihrem eigenen Chat.

![MCP servers](assets/screens/light/mcp-servers.webp?v=20261102-industrial#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp?v=20261102-industrial#only-dark)

### Channels { #channels }

Die Chat-Plattformen, auf denen diese Organisation antwortet - Slack, Teams, Telegram, Mattermost. Ein Bot bedient jeden an ihn gebundenen Agent, und die Bindung wird auf dem Availability-Tab dieses Agents gemacht.

![Channels](assets/screens/light/channels.webp?v=20261102-industrial#only-light)
![Channels](assets/screens/dark/channels.webp?v=20261102-industrial#only-dark)

### Sandboxes { #sandboxes }

Wo die Agents dieser Organisation Shell-Befehle ausführen und Dateien behalten. Ein Agent benennt eine Verbindung per id, also ist der Umzug auf einen anderen Host eine Änderung hier statt einer Neuveröffentlichung jedes Agents.

![Sandboxes](assets/screens/light/sandboxes.webp?v=20261102-industrial#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp?v=20261102-industrial#only-dark)

### Documents { #documents }

Die Dateien, die Agents für Sie aufbewahren. Ein Workspace ist Ablagefläche - er wird mit der Unterhaltung gelöscht, zu der er gehört, und ist kein Ort für irgendetwas Dauerhaftes.

![Documents](assets/screens/light/documents.webp?v=20261102-industrial#only-light)
![Documents](assets/screens/dark/documents.webp?v=20261102-industrial#only-dark)

### Ihre Einstellungen { #your-settings }

Ihr Profil und Konto, Slash-Commands, Memory, die Anmeldungen, die der Browser-Agent für Sie aufbewahrt, Benachrichtigungen, API-Schlüssel, MCP-Clients und der Architect - jeweils ein Tab.

![Ihre Einstellungen](assets/screens/light/settings.webp?v=20261102-industrial#only-light)
![Ihre Einstellungen](assets/screens/dark/settings.webp?v=20261102-industrial#only-dark)

## Deployment-Verwaltung { #deployment-administration }

### Users { #users }

Alle, die sich an diesem Deployment anmelden können, und das App-Admin-Kennzeichen, das von jeder Organisationsrolle getrennt ist.

![Users](assets/screens/light/admin-users.webp?v=20261102-industrial#only-light)
![Users](assets/screens/dark/admin-users.webp?v=20261102-industrial#only-dark)

### All organizations { #all-organizations }

Jeder Mandant auf diesem Deployment, mit Owner, Mitgliedern und Agents.

![All organizations](assets/screens/light/admin-organizations.webp?v=20261102-industrial#only-light)
![All organizations](assets/screens/dark/admin-organizations.webp?v=20261102-industrial#only-dark)

### System { #system }

Datenbank, Redis, der Vektorspeicher, der Modellzugriff und geplante Jobs - dieselben Prüfungen, die `agenticos cmd doctor` ausführt, auf einer Seite.

![System](assets/screens/light/admin-system.webp?v=20261102-industrial#only-light)
![System](assets/screens/dark/admin-system.webp?v=20261102-industrial#only-dark)

### Deployment { #deployment }

Die eigene Identität und Richtlinie dieses Deployments: Registrierung, Einladungen, Hinweise und das, was ein Besucher beim ersten Mal antrifft.

![Deployment](assets/screens/light/admin-deployment.webp?v=20261102-industrial#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp?v=20261102-industrial#only-dark)

## Was hier noch fehlt { #what-is-not-here-yet }

Anmeldung, das Onboarding beim ersten Start und die Tour im Produkt sind noch nicht aufgenommen.

## Fazit { #recap }

Jeder Bildschirm ist in beiden Themes zu sehen, aus einer Demo-Organisation. `docs/assets/screens/capture.mjs` nimmt sie alle gegen jedes laufende Deployment neu auf, sodass ein geänderter Bildschirm ein neuer Lauf ist und kein handgemachtes Bild.
