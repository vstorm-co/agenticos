---
source_sha: 52c1284c9aae
---

# Jeder Bildschirm in der Konsole { #every-screen-in-the-console }

Eine Seite, jedes Modul, beschrieben. Die Screenshots folgen dem Theme, in dem
Sie die Website lesen - schalten Sie es mit dem Umschalter im Kopfbereich um, und
jedes Bild auf dieser Seite schaltet mit.

Aufgenommen am 01.09.2026 aus einem laufenden Deployment: 35 Bildschirme, 27
davon in beiden Themes unter `docs/assets/screens/`, in `light/` und `dark/`
gleich benannt. Die acht Builder-Bildschirme gibt es nur in dunkel, und sie sagen
das dort, wo sie erscheinen.

## Der Chat, in zwanzig Sekunden { #the-chat-in-twenty-seconds }

Eine CSV in die Unterhaltung gezogen, ein Satz Anweisung, und der Agent schreibt
Python, führt es in einer Sandbox aus und antwortet mit Diagrammen, die er aus
den Daten gezeichnet hat. Nichts davon wurde für genau diese Datei konfiguriert.

<video src="../assets/screens/chat-live-demo.mp4" poster="../assets/screens/chat-live-demo-poster.webp" controls muted loop playsinline style="width:100%"></video>

## Wo Sie landen { #where-you-land }

### Dashboard { #dashboard }

Anordenbare Widgets, zuerst das ganze Deployment und dann diese Organisation. Runs, Ausgaben, Dienstzustand und Antwortqualität; jede Karte ist an der Permission gemessen, die ihre eigenen Daten verlangen, sodass eine Karte, deren primären Lesezugriff Sie nicht machen dürfen, Ihnen gar nicht angeboten wird.

![Dashboard](assets/screens/light/dashboard.webp#only-light)
![Dashboard](assets/screens/dark/dashboard.webp#only-dark)

### Chat, mitten im Run { #chat-mid-run }

Der Agent beim Denken, dann die Shell-Befehle, die er in der Sandbox tatsächlich ausgeführt hat, jeder davon aufklappbar. Transparenz ist hier das Produkt: Was ein Tool getan hat, steht auf dem Bildschirm und nicht in einem Log, das jemand anderes lesen kann.

![Chat, mitten im Run](assets/screens/light/chat-sandbox-commands.webp#only-light)
![Chat, mitten im Run](assets/screens/dark/chat-sandbox-commands.webp#only-dark)

## Einen Agent bauen { #building-an-agent }

### Agents { #agents }

Der Katalog. Jeder Agent trägt die Version, die live ist, wer ihn erreichen darf und ob ein Entwurf wartet. Ein Agent ist Konfiguration, kein Code - deshalb ist diese Liste für alle bearbeitbar, die die Antwort kennen.

![Agents](assets/screens/light/agents.webp#only-light)
![Agents](assets/screens/dark/agents.webp#only-dark)

### Agent templates { #agent-templates }

Templates nach Branche, über dem Katalog. Eines zu installieren erzeugt einen Entwurf, den Sie fertigstellen und veröffentlichen; bis dahin läuft nichts.

![Agent templates](assets/screens/light/agents-templates-dialog.webp#only-light)
![Agent templates](assets/screens/dark/agents-templates-dialog.webp#only-dark)

### Skills { #skills }

Einmal aufgeschriebenes Know-how, das jeder daran gebundene Agent teilt - wie Rückerstattungen gehandhabt werden, was der Hausstil ist. Bearbeiten Sie es hier, und jeder gebundene Agent ist beim nächsten Run auf dem aktuellen Stand.

![Skills](assets/screens/light/skills.webp#only-light)
![Skills](assets/screens/dark/skills.webp#only-dark)

### Skill gallery { #skill-gallery }

Skills nach Branche. Beim Installieren wird einer in Ihre Organisation kopiert, wo Sie ihn bearbeiten können - eine Kopie, damit die Quelle nicht ändern kann, was Ihre Agents sagen.

![Skill gallery](assets/screens/light/skills-gallery-dialog.webp#only-light)
![Skill gallery](assets/screens/dark/skills-gallery-dialog.webp#only-dark)

### Ein Skill { #one-skill }

Zum Bearbeiten geöffnet, mit seiner Kategorie. Der Name, auf den sich das Modell bezieht, steht beim Anlegen fest und kann sich nicht ändern; alles andere hier schon.

![Ein Skill](assets/screens/light/skill-detail.webp#only-light)
![Ein Skill](assets/screens/dark/skill-detail.webp#only-dark)

### Context { #context }

Stehender Kontext, aus dem jeder Agent schöpfen kann - ein Glossar, eine Richtlinie, eine Markenstimme. In den Prompt eingespielt oder bei Bedarf gelesen, und aktuell in dem Moment, in dem Sie ihn bearbeiten.

![Context](assets/screens/light/context.webp#only-light)
![Context](assets/screens/dark/context.webp#only-dark)

## In einem Agent { #inside-one-agent }

Der Builder, Tab für Tab. Diese acht gibt es **nur in dunkel** - die helle
Hälfte wurde nicht aufgenommen, daher folgen sie anders als jeder andere
Bildschirm auf dieser Seite nicht Ihrer Palette.

### Build { #build }

Instruktionen, Modell und Endpunkt. Das Verhalten wohnt hier statt im Code, in Markdown, das das Modell als Struktur liest - und der Kopfbereich trägt `published` neben `Draft differs from v40`, was der ganze Punkt ist: Bearbeiten geht nicht live.

![Build](assets/screens/dark/builder-build.webp)

### Toolbox { #toolbox }

Jede Capability als Schalter - Wissenssuche, ein Browser, Python in einer Sandbox, Diagramme, Delegation - und daneben jeweils das Approval-Gate pro Tool. Konfiguration erreicht nur, was Code registriert hat.

![Toolbox](assets/screens/dark/builder-toolbox.webp)

### MCP servers { #mcp-servers }

Welche Verbindungen dieser Agent erreichen darf und welche ihrer Tools. Die Liste der Organisation begrenzt ihn weiterhin; ein Agent kann darin enger werden und nicht darüber hinausreichen.

![MCP servers](assets/screens/dark/builder-mcp-servers.webp)

### Limits { #limits }

Eine Monatsobergrenze und eine Schrittgrenze. Die Obergrenze wird vor jeder Modellanfrage geprüft, und die Schrittgrenze fängt die andere Entgleisung ab - eine Tool-Schleife, die pro Aufruf billig ist und nie endet.

![Limits](assets/screens/dark/builder-limits.webp)

### Availability { #availability }

Wo dieser Agent antwortet: das Dashboard und die API immer, dazu jeder Chat-Bot, der hier gebunden ist. Ein Agent ist per `@handle` nur auf den Bots erwähnbar, an die er gebunden ist.

![Availability](assets/screens/dark/builder-availability.webp)

### Routines, am Agent { #routines-on-the-agent }

Was er tut, wenn niemand tippt, auf demselben Tab - ein Zeitplan, der sich pausieren lässt, oder ein Event-Trigger.

![Routines, am Agent](assets/screens/dark/builder-routines.webp)

### History { #history }

Jede Version, die dieser Agent hatte. Die, die im März live war, ist immer noch lesbar, und das macht ein Zurückrollen zu einer Entscheidung statt zu einem Ausgrabungsprojekt.

![History](assets/screens/dark/builder-history.webp)

### Visual map { #visual-map }

Derselbe Agent als Graph: was ihn erreicht und wonach er greift. Ein gestrichelter Kasten ist etwas, an dem nichts hängt - ein Budget ohne eigene Obergrenze liest sich als Lücke statt als Default.

![Visual map](assets/screens/dark/builder-visual-map.webp)
## Knowledge { #knowledge }

### Knowledge bases { #knowledge-bases }

Collections. Fassen Sie zusammengehörige Dokumente zu einer zusammen und wählen Sie dann im Chat, welche Collections ein Agent durchsuchen darf.

![Knowledge bases](assets/screens/light/knowledge-bases.webp#only-light)
![Knowledge bases](assets/screens/dark/knowledge-bases.webp#only-dark)

### Eine Collection { #a-collection }

Ihre Dokumente, deren Chunk-Zahlen und alles, was bei der Ingestion mit Begründung gescheitert ist. Chunk-Grenzen sind das, wogegen eine Suche abgleicht, also wird ein nach einer Einstellungsänderung erneut hochgeladenes Dokument neu gechunkt.

![Eine Collection](assets/screens/light/knowledge-base-detail.webp#only-light)
![Eine Collection](assets/screens/dark/knowledge-base-detail.webp#only-dark)

### Parsing, pro Upload { #parsing-per-upload }

Die Wahl, die sonst niemand offenlegt: **PyMuPDF**, **LiteParse** oder **LlamaParse**, die Chunking-Strategie, Chunk-Größe und Überlappung, OCR und dessen Sprache. An der Collection gesetzt und bei der nächsten Datei überschreibbar - denn eine eingescannte Preisliste und ein Markdown-Runbook wollen nicht denselben Parser, und der falsche ist der Unterschied zwischen einer Antwort und einer Absage.

![Parsing, pro Upload](assets/screens/light/knowledge-base-upload-parsing-dialog.webp#only-light)
![Parsing, pro Upload](assets/screens/dark/knowledge-base-upload-parsing-dialog.webp#only-dark)

## Was passiert ist, und was wartet { #what-happened-and-what-is-waiting }

### Runs { #runs }

Jeder Run, den diese Organisation gemacht hat, mit Status, Oberfläche, Modell, Person und Kosten. Ein Run ist der Prozess: Er startet, er lässt sich stoppen, und er hinterlässt einen Eintrag.

![Runs](assets/screens/light/activity-runs.webp#only-light)
![Runs](assets/screens/dark/activity-runs.webp#only-dark)

### Ein Run, geöffnet { #one-run-opened }

Token hinein und hinaus, Kosten auf vier Nachkommastellen, wie lange es gedauert hat, und die Zeitleiste jedes Zuges und Tool-Aufrufs. Der Chat, in dem es passiert ist, ist einen Klick entfernt.

![Ein Run, geöffnet](assets/screens/light/activity-run-detail.webp#only-light)
![Ein Run, geöffnet](assets/screens/dark/activity-run-detail.webp#only-dark)

### Approvals { #approvals }

Alles, was auf einen Menschen wartet, mit dem, was der Agent vorhat. Eine Approval wird genau einmal entschieden - eine zweite Entscheidung über eine erledigte wird abgelehnt, und dieses Detail macht das Gate erst wertvoll.

![Approvals](assets/screens/light/activity-approvals.webp#only-light)
![Approvals](assets/screens/dark/activity-approvals.webp#only-dark)

### Spend { #spend }

Was tatsächlich ausgegeben wurde, nach Zeitraum. Ein Budget wird *vor* der Modellanfrage geprüft statt hinterher zusammengezählt, also stoppt ein Run, der eines reißt, mitten in der Antwort und verzeichnet seine Kosten trotzdem.

![Spend](assets/screens/light/activity-spend.webp#only-light)
![Spend](assets/screens/dark/activity-spend.webp#only-dark)

### Routines { #routines }

Was Agents tun, wenn niemand tippt - nach Zeitplan oder wenn ein Ereignis eintrifft. Diese Runs sind budgetiert, freigegeben und auditiert wie alle anderen.

![Routines](assets/screens/light/routines.webp#only-light)
![Routines](assets/screens/dark/routines.webp#only-dark)

### Ein neuer Event-Trigger { #a-new-event-trigger }

Das Ereignis benennen, das einen Run startet, über der Liste der Routines.

![Ein neuer Event-Trigger](assets/screens/light/routines-event-trigger-dialog.webp#only-light)
![Ein neuer Event-Trigger](assets/screens/dark/routines-event-trigger-dialog.webp#only-dark)

## Die Organisation { #the-organization }

### Organizations { #organizations }

Zwischen ihnen wechseln, Mitglieder verwalten und neue anlegen. Autorität innerhalb einer Organisation ist eine Mitgliedschaftszeile plus der Permission-Katalog - es gibt keine Rollenspalte an einem Nutzer.

![Organizations](assets/screens/light/organizations.webp#only-light)
![Organizations](assets/screens/dark/organizations.webp#only-dark)

### Vault { #vault }

Jeder Schlüssel, den diese Organisation gespeichert hat, pro Mandant versiegelt. Ersetzbar, nie wieder lesbar; und eine Rotation ist für einen veröffentlichten Agent unsichtbar, weil er das Secret referenziert und nicht dessen Wert.

![Vault](assets/screens/light/vault.webp#only-light)
![Vault](assets/screens/dark/vault.webp#only-dark)

### MCP servers { #mcp-servers_1 }

Verbinden Sie jeden MCP-Server per URL, und seine Tools werden zu Schaltern im Builder. Verbinden Sie ihn für die Organisation, und jeder Agent darf ihn nutzen; verbinden Sie ihn für sich selbst, und er bleibt in Ihrem eigenen Chat.

![MCP servers](assets/screens/light/mcp-servers.webp#only-light)
![MCP servers](assets/screens/dark/mcp-servers.webp#only-dark)

### Channels { #channels }

Die Chat-Plattformen, auf denen diese Organisation antwortet - Slack, Telegram, Mattermost. Ein Bot bedient jeden an ihn gebundenen Agent, und die Bindung wird auf dem Availability-Tab dieses Agents gemacht.

![Channels](assets/screens/light/channels.webp#only-light)
![Channels](assets/screens/dark/channels.webp#only-dark)

### Sandboxes { #sandboxes }

Wo die Agents dieser Organisation Shell-Befehle ausführen und Dateien behalten. Ein Agent benennt eine Verbindung per id, also ist der Umzug auf einen anderen Host eine Änderung hier statt einer Neuveröffentlichung jedes Agents.

![Sandboxes](assets/screens/light/sandboxes.webp#only-light)
![Sandboxes](assets/screens/dark/sandboxes.webp#only-dark)

### Workspaces { #workspaces }

Die Dateien, die Agents für Sie aufbewahren. Ein Workspace ist Ablagefläche - er wird mit der Unterhaltung gelöscht, zu der er gehört, und ist kein Ort für irgendetwas Dauerhaftes.

![Workspaces](assets/screens/light/workspaces.webp#only-light)
![Workspaces](assets/screens/dark/workspaces.webp#only-dark)

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

Datenbank, Redis, der Vektorspeicher und der Modellzugriff - dieselben Prüfungen, die `agenticos cmd doctor` ausführt, auf einer Seite.

![System](assets/screens/light/admin-system.webp#only-light)
![System](assets/screens/dark/admin-system.webp#only-dark)

### Deployment { #deployment }

Die eigene Identität und Richtlinie dieses Deployments: Registrierung, Einladungen, Hinweise und das, was eine Besucherin beim ersten Mal antrifft.

![Deployment](assets/screens/light/admin-deployment.webp#only-light)
![Deployment](assets/screens/dark/admin-deployment.webp#only-dark)

## Was hier noch fehlt { #what-is-not-here-yet }

- **Die helle Hälfte des Builders** - die acht Aufnahmen oben gibt es nur in
  dunkel.
- **Anmeldung und Onboarding**, also das, was eine Besucherin beim ersten Mal
  tatsächlich antrifft.

## Fazit { #recap }

- 27 Module liegen in beiden Themes in `docs/assets/screens/`, unter demselben
  Namen; die acht Builder-Bildschirme gibt es nur in dunkel.
- Auf dieser Website wird ein Bild zweimal geschrieben, mit `#only-light` und
  `#only-dark`; Material zeigt das, was zur Palette der Leserin passt.
- In der README steht dasselbe Paar in einem `<picture>` mit
  `media="(prefers-color-scheme: dark)"`, so wie GitHub es macht.
- Parsing ist die Einstellung, die zu kennen sich lohnt, bevor Sie irgendetwas
  hochladen: Der Parser und die Chunk-Größe entscheiden, ob eine Tabelle
  überhaupt beantwortet werden kann.
