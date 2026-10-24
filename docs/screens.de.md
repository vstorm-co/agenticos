---
source_sha: "4b8832761f4a"
---

# Jeder Bildschirm in der Konsole { #every-screen-in-the-console }

Jedes Modul der Konsole, beschrieben und mit einer Aufnahme. Die Bilder folgen dem Theme, in dem Sie die Seite lesen - wechseln Sie es in der Kopfzeile, wechseln sie mit. Sie zeigen eine Demo-Organisation, Northwind Labs, deren Firma, Dokumente und Zahlen erfunden sind; die Unterhaltungen und die veröffentlichte App sind echte Runs ihrer Agents.

## Produktdemo { #product-demo }

Die aktuelle bearbeitete Demo zeigt den OSS Launch Planner: eine Aufgabe mit einem Notion-Briefing und GitHub-Recherche, eine interaktive App und einen Freigabelink. Wartezeiten wurden entfernt; der Bericht enthält eine Momentaufnahme der Daten.

<video src="https://github.com/user-attachments/assets/529c8a90-501e-45c7-81d1-0f8de7829953" controls muted playsinline style="width:100%"></video>

## Wo Sie landen { #where-you-land }

### Dashboard { #dashboard }

Ihre eigene Ansicht, die anordenbare der Organisation, die einer Gruppe und - für einen Deployment-Admin - die des ganzen Deployments, oben gewählt. Runs, Ausgaben, Dienstzustand und Antwortqualität; jede Karte ist an der Permission gemessen, die ihre eigenen Daten verlangen, sodass eine Karte, deren primären Lesezugriff Sie nicht machen dürfen, Ihnen gar nicht angeboten wird.

![Dashboard](assets/screens/light/dashboard.webp#only-light)
![Dashboard](assets/screens/dark/dashboard.webp#only-dark)

### Chat { #chat }

Eine Tabelle hinein, eine veröffentlichte Seite heraus. Der Agent hat die CSV mit Python gelesen, die Zahlen berechnet, ein Umsatz-Dashboard als App veröffentlicht und gesagt, welche Werte er geprüft und welche er geschätzt hat. Jeder Schritt steht auf dem Bildschirm und lässt sich aufklappen - was ein Tool getan hat, steht in der Unterhaltung, nicht in einem Log, das jemand anderes liest.

![Chat](assets/screens/light/chat.webp#only-light)
![Chat](assets/screens/dark/chat.webp#only-dark)

### Ein Sprachanruf { #a-voice-call }

Das Eingabefeld ist zur Anrufleiste geworden: was der Anruf gerade tut, seine Zeit gemessen am Limit, eine Wellenform beider Stimmen, Stummschalten, Push-to-Talk und Beenden. Darüber läuft die Unterhaltung weiter - Untertitel in der Nachricht, die gerade gesprochen wird, Tool-Ausführungen und eine Freigabekarte mit den exakten Argumenten und dem, was von Ihnen verstanden wurde.

> **Screenshot ausstehend — Ein Sprachanruf.**

## Einen Agent bauen { #building-an-agent }

### Agents { #agents }

Der Katalog. Jeder Agent trägt die Version, die live ist, wer ihn erreichen darf und ob ein Entwurf wartet. Ein Agent ist Konfiguration, kein Code - deshalb ist diese Liste für alle bearbeitbar, die die Antwort kennen.

![Agents](assets/screens/light/agents.webp#only-light)
![Agents](assets/screens/dark/agents.webp#only-dark)

### Agent templates { #agent-templates }

Templates nach Branche, über dem Katalog. Eines zu installieren erzeugt einen Entwurf, den Sie fertigstellen und veröffentlichen; bis dahin läuft nichts.

![Agent templates](assets/screens/light/agent-templates.webp#only-light)
![Agent templates](assets/screens/dark/agent-templates.webp#only-dark)

### Skills { #skills }

Einmal aufgeschriebenes Know-how, das jeder daran gebundene Agent teilt - wie Rückerstattungen gehandhabt werden, was der Hausstil ist. Bearbeiten Sie es hier, und jeder gebundene Agent ist beim nächsten Run auf dem aktuellen Stand.

![Skills](assets/screens/light/skills.webp#only-light)
![Skills](assets/screens/dark/skills.webp#only-dark)

### Skill gallery { #skill-gallery }

Skills nach Branche. Beim Installieren wird einer in Ihre Organisation kopiert, wo Sie ihn bearbeiten können - eine Kopie, damit die Quelle nicht ändern kann, was Ihre Agents sagen.

![Skill gallery](assets/screens/light/skill-gallery.webp#only-light)
![Skill gallery](assets/screens/dark/skill-gallery.webp#only-dark)

### Ein Skill { #one-skill }

Zum Bearbeiten geöffnet, mit seiner Kategorie. Der Name, auf den sich das Modell bezieht, steht beim Anlegen fest und kann sich nicht ändern; alles andere hier schon.

![Ein Skill](assets/screens/light/skill-detail.webp#only-light)
![Ein Skill](assets/screens/dark/skill-detail.webp#only-dark)

### Context { #context }

Stehender Kontext, aus dem jeder Agent schöpfen kann - ein Glossar, eine Richtlinie, eine Markenstimme. In den Prompt eingespielt oder bei Bedarf gelesen, und aktuell in dem Moment, in dem Sie ihn bearbeiten.

![Context](assets/screens/light/context.webp#only-light)
![Context](assets/screens/dark/context.webp#only-dark)

## In einem Agent { #inside-one-agent }

Der Builder, Tab für Tab.

### Build { #build }

Instruktionen, Modell und Endpunkt. Das Verhalten wohnt hier statt im Code, in Markdown, das das Modell als Struktur liest - und der Kopfbereich trägt `published` neben `Draft differs from v40`, was der ganze Punkt ist: Bearbeiten geht nicht live.

![Build](assets/screens/light/agent-builder.webp#only-light)
![Build](assets/screens/dark/agent-builder.webp#only-dark)

### Toolbox { #toolbox }

Jede Capability als Schalter - Wissenssuche, ein Browser, Python in einer Sandbox, Diagramme, Delegation - und daneben jeweils das Approval-Gate pro Tool. Konfiguration erreicht nur, was Code registriert hat.

![Toolbox](assets/screens/light/agent-toolbox.webp#only-light)
![Toolbox](assets/screens/dark/agent-toolbox.webp#only-dark)

### MCP servers { #mcp-servers }

Welche Verbindungen dieser Agent erreichen darf und welche ihrer Tools. Die Liste der Organisation begrenzt ihn weiterhin; ein Agent kann darin enger werden und nicht darüber hinausreichen.

![MCP servers](assets/screens/light/agent-mcp.webp#only-light)
![MCP servers](assets/screens/dark/agent-mcp.webp#only-dark)

### Limits { #limits }

Eine Monatsobergrenze und eine Schrittgrenze. Die Obergrenze wird vor jeder Modellanfrage geprüft, und die Schrittgrenze fängt die andere Entgleisung ab - eine Tool-Schleife, die pro Aufruf billig ist und nie endet.

![Limits](assets/screens/light/agent-limits.webp#only-light)
![Limits](assets/screens/dark/agent-limits.webp#only-dark)

### Availability { #availability }

Wo dieser Agent antwortet: das Dashboard und die API immer, dazu jeder Chat-Bot, der hier gebunden ist. Ein Agent ist per `@handle` nur auf den Bots erwähnbar, an die er gebunden ist.

![Availability](assets/screens/light/agent-availability.webp#only-light)
![Availability](assets/screens/dark/agent-availability.webp#only-dark)

### Routines, am Agent { #routines-on-the-agent }

Was er tut, wenn niemand tippt, auf demselben Tab - ein Zeitplan, der sich pausieren lässt, oder ein Event-Trigger.

![Routines, am Agent](assets/screens/light/agent-routines.webp#only-light)
![Routines, am Agent](assets/screens/dark/agent-routines.webp#only-dark)

### History { #history }

Jede Version, die dieser Agent hatte. Die, die im März live war, ist immer noch lesbar, und das macht ein Zurückrollen zu einer Entscheidung statt zu einem Ausgrabungsprojekt.

![History](assets/screens/light/agent-history.webp#only-light)
![History](assets/screens/dark/agent-history.webp#only-dark)

### Visual map { #visual-map }

Derselbe Agent als Graph: was ihn erreicht und wonach er greift. Ein gestrichelter Kasten ist etwas, an dem nichts hängt - ein Budget ohne eigene Obergrenze liest sich als Lücke statt als Default.

![Visual map](assets/screens/light/agent-map.webp#only-light)
![Visual map](assets/screens/dark/agent-map.webp#only-dark)

## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Collections. Fassen Sie zusammengehörige Dokumente zu einer zusammen und wählen Sie dann im Chat, welche Collections ein Agent durchsuchen darf.

![Knowledge bases](assets/screens/light/knowledge-bases.webp#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp#only-dark)

### Eine Collection { #a-collection }

Ihre Dokumente, deren Chunk-Zahlen und alles, was bei der Ingestion mit Begründung gescheitert ist. Chunk-Grenzen sind das, wogegen eine Suche abgleicht, also wird ein nach einer Einstellungsänderung erneut hochgeladenes Dokument neu gechunkt.

![Eine Collection](assets/screens/light/knowledge-collection.webp#only-light)
![Eine Collection](assets/screens/dark/knowledge-collection.webp#only-dark)

### Parsing, pro Upload { #parsing-per-upload }

Die Wahl, die sonst niemand offenlegt: **PyMuPDF**, **LiteParse** oder **LlamaParse**, die Chunking-Strategie, Chunk-Größe und Überlappung, OCR und dessen Sprache. An der Collection gesetzt und bei der nächsten Datei überschreibbar - denn eine eingescannte Preisliste und ein Markdown-Runbook wollen nicht denselben Parser, und der falsche ist der Unterschied zwischen einer Antwort und einer Absage.

![Parsing, pro Upload](assets/screens/light/kb-parse-options.webp#only-light)
![Parsing, pro Upload](assets/screens/dark/kb-parse-options.webp#only-dark)

## Was passiert ist, und was wartet { #what-happened-and-what-is-waiting }

### Runs { #runs }

Jeder Run, den diese Organisation gemacht hat, mit Status, Oberfläche, Modell, Person und Kosten. Ein Run ist der Prozess: Er startet, er lässt sich stoppen, und er hinterlässt einen Eintrag.

![Runs](assets/screens/light/activity.webp#only-light)
![Runs](assets/screens/dark/activity.webp#only-dark)

### Ein Run, geöffnet { #one-run-opened }

Token hinein und hinaus, Kosten auf vier Nachkommastellen, wie lange es gedauert hat, und die Zeitleiste jedes Zuges und Tool-Aufrufs. Der Chat, in dem es passiert ist, ist einen Klick entfernt.

![Ein Run, geöffnet](assets/screens/light/run-detail.webp#only-light)
![Ein Run, geöffnet](assets/screens/dark/run-detail.webp#only-dark)

### Approvals { #approvals }

Alles, was auf einen Menschen wartet, mit dem, was der Agent vorhat. Eine Approval wird genau einmal entschieden - eine zweite Entscheidung über eine erledigte wird abgelehnt, und dieses Detail macht das Gate erst wertvoll.

![Approvals](assets/screens/light/approvals.webp#only-light)
![Approvals](assets/screens/dark/approvals.webp#only-dark)

### Spend { #spend }

Was tatsächlich ausgegeben wurde, nach Zeitraum. Ein Budget wird *vor* der Modellanfrage geprüft statt hinterher zusammengezählt, also stoppt ein Run, der eines reißt, mitten in der Antwort und verzeichnet seine Kosten trotzdem.

![Spend](assets/screens/light/spend.webp#only-light)
![Spend](assets/screens/dark/spend.webp#only-dark)

### Routines { #routines }

Was Agents tun, wenn niemand tippt - nach Zeitplan oder wenn ein Ereignis eintrifft. Diese Runs sind budgetiert, freigegeben und auditiert wie alle anderen.

![Routines](assets/screens/light/routines.webp#only-light)
![Routines](assets/screens/dark/routines.webp#only-dark)

### Ein neuer Event-Trigger { #a-new-event-trigger }

Das Ereignis benennen, das einen Run startet, über der Liste der Routines.

![Ein neuer Event-Trigger](assets/screens/light/routine-event-trigger.webp#only-light)
![Ein neuer Event-Trigger](assets/screens/dark/routine-event-trigger.webp#only-dark)

### Apps { #apps }

Seiten, die Agents veröffentlicht haben - Berichte, kleine Dashboards, Zusammenfassungen. Jede behält ihren Link, wenn der Agent sie erneut veröffentlicht, und ihre früheren Versionen bleiben lesbar.

![Apps](assets/screens/light/apps.webp#only-light)
![Apps](assets/screens/dark/apps.webp#only-dark)

### Eine App { #one-app }

Das Umsatz-Dashboard aus dem Chat oben, geöffnet. Es ist privat, bis jemand es teilt, und ein öffentlicher Link ist eine eigene Entscheidung, die sich zurücknehmen lässt.

![Eine App](assets/screens/light/app-detail.webp#only-light)
![Eine App](assets/screens/dark/app-detail.webp#only-dark)

## Die Organisation { #the-organization }

### Organizations { #organizations }

Zwischen ihnen wechseln, Mitglieder verwalten und neue anlegen. Autorität innerhalb einer Organisation ist eine Mitgliedschaftszeile plus der Permission-Katalog - es gibt keine Rollenspalte an einem Nutzer.

![Organizations](assets/screens/light/organizations.webp#only-light)
![Organizations](assets/screens/dark/organizations.webp#only-dark)

### Members { #members }

Die Menschen einer Organisation und ihre Rollen, mit dem Monatslimit, das sich alle ihre Agents teilen, und der Einstellung, ob eine Unterhaltung ihre Approvals überspringen darf.

![Members](assets/screens/light/members.webp#only-light)
![Members](assets/screens/dark/members.webp#only-dark)

### Roles { #roles }

Was jede Rolle darf, als die Matrix, die der Code definiert. Das Teilen einer einzelnen Ressource kann den Zugriff über die Rolle hinaus erweitern; es schränkt ihn nie ein.

![Roles](assets/screens/light/roles.webp#only-light)
![Roles](assets/screens/dark/roles.webp#only-dark)

### Groups { #groups }

Abteilungen und Teams. Teilen Sie einen Agent, eine Wissensdatenbank, einen Skill oder eine Kontextdatei mit einer Gruppe, und alle darin können ihn nutzen - Menschen außerhalb nicht.

![Groups](assets/screens/light/groups.webp#only-light)
![Groups](assets/screens/dark/groups.webp#only-dark)

### Vault { #vault }

Jeder Schlüssel, den diese Organisation gespeichert hat, pro Mandant versiegelt. Ersetzbar, nie wieder lesbar; und eine Rotation ist für einen veröffentlichten Agent unsichtbar, weil er das Secret referenziert und nicht dessen Wert.

![Vault](assets/screens/light/vault.webp#only-light)
![Vault](assets/screens/dark/vault.webp#only-dark)

### MCP servers { #mcp-servers_1 }

Verbinden Sie jeden MCP-Server per URL, und seine Tools werden zu Schaltern im Builder. Verbinden Sie ihn für die Organisation, und jeder Agent darf ihn nutzen; verbinden Sie ihn für sich selbst, und er bleibt in Ihrem eigenen Chat.

![MCP servers](assets/screens/light/mcp-servers.webp#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp#only-dark)

### Channels { #channels }

Die Chat-Plattformen, auf denen diese Organisation antwortet - Slack, Teams, Telegram, Mattermost. Ein Bot bedient jeden an ihn gebundenen Agent, und die Bindung wird auf dem Availability-Tab dieses Agents gemacht.

![Channels](assets/screens/light/channels.webp#only-light)
![Channels](assets/screens/dark/channels.webp#only-dark)

### Sandboxes { #sandboxes }

Wo die Agents dieser Organisation Shell-Befehle ausführen und Dateien behalten. Ein Agent benennt eine Verbindung per id, also ist der Umzug auf einen anderen Host eine Änderung hier statt einer Neuveröffentlichung jedes Agents.

![Sandboxes](assets/screens/light/sandboxes.webp#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp#only-dark)

### Documents { #documents }

Die Dateien, die Agents für Sie aufbewahren. Ein Workspace ist Ablagefläche - er wird mit der Unterhaltung gelöscht, zu der er gehört, und ist kein Ort für irgendetwas Dauerhaftes.

![Documents](assets/screens/light/documents.webp#only-light)
![Documents](assets/screens/dark/documents.webp#only-dark)

### Ihre Einstellungen { #your-settings }

Ihr Profil und Konto, Slash-Commands, Memory, die Anmeldungen, die der Browser-Agent für Sie aufbewahrt, Benachrichtigungen, API-Schlüssel, MCP-Clients und der Architect - jeweils ein Tab.

![Ihre Einstellungen](assets/screens/light/settings.webp#only-light)
![Ihre Einstellungen](assets/screens/dark/settings.webp#only-dark)

## Deployment-Verwaltung { #deployment-administration }

### Users { #users }

Alle, die sich an diesem Deployment anmelden können, und das App-Admin-Kennzeichen, das von jeder Organisationsrolle getrennt ist.

![Users](assets/screens/light/admin-users.webp#only-light)
![Users](assets/screens/dark/admin-users.webp#only-dark)

### All organizations { #all-organizations }

Jeder Mandant auf diesem Deployment, mit Owner, Mitgliedern und Agents.

![All organizations](assets/screens/light/admin-organizations.webp#only-light)
![All organizations](assets/screens/dark/admin-organizations.webp#only-dark)

### System { #system }

Datenbank, Redis, der Vektorspeicher, der Modellzugriff und geplante Jobs - dieselben Prüfungen, die `agenticos cmd doctor` ausführt, auf einer Seite.

![System](assets/screens/light/admin-system.webp#only-light)
![System](assets/screens/dark/admin-system.webp#only-dark)

### Deployment { #deployment }

Die eigene Identität und Richtlinie dieses Deployments: Registrierung, Einladungen, Hinweise und das, was ein Besucher beim ersten Mal antrifft.

![Deployment](assets/screens/light/admin-deployment.webp#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp#only-dark)

## Was hier noch fehlt { #what-is-not-here-yet }

Anmeldung, das Onboarding beim ersten Start und die Tour im Produkt sind noch nicht aufgenommen.

## Fazit { #recap }

Jeder Bildschirm ist in beiden Themes zu sehen, aus einer Demo-Organisation. `docs/assets/screens/capture.mjs` nimmt sie alle gegen jedes laufende Deployment neu auf, sodass ein geänderter Bildschirm ein neuer Lauf ist und kein handgemachtes Bild.
