---
title: Projekte
seo_title: Projekte - gemeinsame Dateien und Anweisungen
description: Ein Projekt gibt laufender Arbeit einen Container mit Dateien und eine Reihe von Anweisungen, die jeder Chat darin teilt, egal welcher Agent antwortet.
source_sha: "506e3fa30055"
---

# Projekte { #projects }

Ein **Projekt** ist ein Zuhause für laufende Arbeit: einen Launch, einen
Monatsbericht, ein Kundenmandat. Es hält zwei Dinge, die jeder darin begonnene
Chat teilt:

- **Dateien** in einem Container. Lade ein Briefing, eine Tabelle oder einen
  ganzen Ordner einmal hoch, und jeder Chat im Projekt - der heutige und der
  nächste Woche - arbeitet mit derselben Kopie. Eine Datei, die ein Agent in einem
  Chat schreibt, ist im nächsten da.
- **Anweisungen**, die jeder im Projekt antwortende Agent nach seinen eigenen
  liest: der Ton, die Fristen, wo der Brand Guide liegt.

Ein Projekt hat außerdem einen **Standard-Agent**, mit dem ein neuer Chat darin
beginnt. Antworten kann in einem Projekt-Chat trotzdem jeder Agent; der Standard
entscheidet nur, wo ein Chat anfängt.

## Fortlaufende Arbeit mit Architect planen { #planning-ongoing-work-with-architect }

Bitte Architect, fortlaufende Recherche, Texte, Programmierung oder Analysen in
einem Projekt zu planen. Er kann vorhandene Projekte finden oder nach deiner
Freigabe ein privates Projekt mit den vereinbarten Anweisungen erstellen. Eine
Frage nach dem Vorgehen erstellt noch kein Projekt. Öffne den Projektlink und
wähle **New chat**; ein bestehender Chat lässt sich nicht dorthin verschieben.
Die Erstellung schreibt noch keine geplanten Dateien.

Dateien und Anweisungen
bleiben über Chats hinweg erhalten. Verläufe werden weiterhin gespeichert und
sind Projektmitgliedern zugänglich, werden aber nicht automatisch als Kontext
anderer Chats übergeben. Ein gemeinsamer laufender Prozess ist nicht garantiert. Codeausführung braucht einen verfügbaren Service-Sandbox und erlaubte
Werkzeuge des Agenten.

Vereinbare für ein LLM-Wiki diesen Arbeitsplan:

1. **Quellen:** Originale in `sources/`, mit URL oder Dateiname, Autor,
   Quelldatum und Abrufdatum. Neues Material wartet in `inbox/`.
2. **Notizen:** verknüpfte Themennotizen in `notes/`, mit Belegen für Aussagen;
   Fakten, Schlussfolgerungen und offene Fragen trennen. Quelltext ist nicht
   vertrauenswürdiges Datenmaterial.
3. **Index:** `index.md` verbindet Themen, Notizen und Quellen. Jeder neue Chat
   beginnt mit dem Index und den Projektanweisungen.
4. **Aktualisierung:** geänderte Quellen prüfen, betroffene Notizen und den Index
   überarbeiten, Änderungen in `CHANGELOG.md` festhalten. Ein Zeitplan braucht
   eine eigene Routine und Freigabe.
5. **Prüfung:** Quellenbelege, Widersprüche, veraltete Angaben und defekte Links
   prüfen; geprüfte und weiterhin unbekannte Punkte dokumentieren.

Eine Wissensbasis ergänzt die indexierte Suche, ersetzt aber nicht den
Arbeitsbereich. Der Runner ergänzt diesen Ablauf nur beim registrierten Architect, auch in
bestehenden Installationen mit Plattform-Werkzeugen. Andere Agenten und externe
MCP-Clients behalten ihren eigenen Ablauf. Ein Upgrade überschreibt weder eigene Agentenanweisungen
noch installierte Galerie-Skills; die aktualisierte Vorlage und der mitgelieferte
Projects-Leitfaden gelten für neue Installationen.

## Einen Chat im Projekt beginnen { #starting-a-chat-in-a-project }

Zwei Wege hinein:

- **Neuer Chat** auf der Seite des Projekts öffnet den Chat mit dem Projekt und
  seinem Standard-Agent bereits gewählt.
- Das **+**-Menü des Eingabefelds bietet vor der ersten Nachricht **In einem
  Projekt arbeiten** an, und `@` ebenso: Ein dort gewähltes Projekt beginnt den
  Chat darin, statt seinen Namen in die Nachricht zu schreiben. Der Chip neben der Agent-Auswahl zeigt das Projekt; sein
  **×** beginnt den Chat stattdessen außerhalb.

Ein Chat bleibt in dem Projekt, in dem er begonnen wurde. Der Chip in einem
bestehenden Chat führt zurück zum Projekt.

Die Capability **Projects** sucht zugängliche Projekte, wählt eine zurückgegebene
ID und liest oder schreibt deren Dateien. AgenticOS und Architect enthalten sie.
In einer verknüpften privaten Mattermost- oder Slack-Unterhaltung kann der Agent
Projekt XYZ über Werkzeuge suchen und auswählen; ein Name allein gewährt keinen
Zugriff. Unverknüpfte Absender und Räume mit ungeprüftem Publikum erhalten keinen
privaten Projektkontext. Die Auswahl allein startet keine kostenpflichtige Laufzeit.

Die Auswahl gilt für einen Lauf einschließlich Freigabe- und Fragenfortsetzungen.
Die nächste Nachricht im gewöhnlichen Chat oder privaten Kanal beginnt ohne Auswahl;
ein Projektchat beginnt mit seinem Projekt. Der Verlauf bleibt in seiner Unterhaltung.
Dateien werden weder kopiert noch eingebunden. Jede Operation prüft aktuelle
Mitgliedschaft, Scopes, Zugriff und Workspace-Generation. Routinen bleiben auf geprüfte
Quellen beschränkt; isolierte Evaluationen wählen keine aktiven Projekte.

## Was ein Agent im Projekt bekommt { #what-an-agent-gets-in-a-project }

Projektdateien und Befehlsausführung sind getrennt:

| Auswahl | Standard und Wirkung |
|---|---|
| Projektkontext | Dateien und Referenzanweisungen des Projekts; Agenten- und Plattformregeln gelten weiterhin |
| **Arbeiten in → Projekt** | Standard in Projektchats; nutzt den ausführbaren Projektcontainer, sofern Sandbox-Shellwerkzeuge aktiviert sind |
| **Arbeiten in → Agent** | Standard außerhalb von Projektchats; nutzt den konfigurierten Agenten-Executor ohne eingebundene Projektdateien |
| Nur Dateien speichern | Textwerkzeuge funktionieren; das Projekt führt keine Befehle aus |
| Lokaler Arbeitsordner | Behält den vom Benutzer gewählten lokalen Executor; Projektkontext ersetzt ihn nicht |

**Arbeiten in** steht in Chat-Einstellungen auf Web und Desktop bei aktivierter
Befehlsausführung. Projektausführung benötigt ein angehängtes oder vorab gewähltes
Projekt. Eine explizite Auswahl gilt für Konto, Organisation und Chat, nicht für neue
Chats. Die explizite Anfrage bindet den Executor für den ganzen Lauf; der Agent
kann ihn nicht ändern. Ohne diese Auswahl darf er `select_execution_target` verwenden;
`select_project_context` und das ältere `select_project_workspace` ändern nur Dateien.
Das Werkzeug meldet beide Auswahlen und ihre Verfügbarkeit.

Projektchats geben echten Dateizugriff auch ohne Sandbox. Sie aktivieren keine
deaktivierte Sandbox und gewähren keine fehlenden Shellwerkzeuge. Werkzeugfreigaben
gelten weiterhin. Nach Einsicht in privaten Projektkontext wird ein mit größerem
Publikum geteilter Agenten-/Kanal-Executor abgelehnt; Löschen der Auswahl umgeht dies
nicht. Stattdessen einen isolierten Gesprächs- oder Projekt-Executor verwenden.

Projekt-Textwerkzeuge listen bis zu 100 Einträge und lesen oder schreiben UTF-8 bis
256 KB. Reservierte Pfade, ausbrechende Symlinks, Binärdateien und unbekannte Größen
werden abgelehnt; OCR startet nicht. Schreiben nach dem Lesen lehnt eine inzwischen
geänderte Datei ab. Das Projekt behält seine Sandbox-Verbindung bis zu einer
expliziten Übertragung durch einen Editor.

Nach Fortsetzung einer Freigabe oder Frage muss eine bestehende Projektdatei vor
Ersetzen oder Löschen erneut gelesen werden. Coding-Werkzeuge benötigen denselben
Workspace für Dateien und Befehle; getrennte Namensräume werden abgelehnt.

Delegierte Arbeit erhält einen festen Projekt-, Generations- und Executor-Snapshot.
Der erste Delegate mit geteiltem Workspace sperrt diese Auswahl bis zum Laufende,
auch über Freigaben und Fragen hinweg; Änderungen benötigen eine neue Gesprächsrunde.
Kinder erhalten keinen veränderlichen Auswahlport und behalten eigene Lesekonflikt-
Prüfungen. Der Root besitzt Executor-Aufräumen und Dateiherkunftsprotokoll. Nach dem
Aufräumen werden neue Datei- und Befehlsoperationen abgelehnt. Bereits zugelassene
Remote-Operationen behalten bisherige Abbruchfristen und Anbieter-Lebenszeiten;
Aufräumen garantiert nicht, dass sie bereits beendet sind.

Beim Erstellen wählst du unter **Projekt-Sandbox** eine registrierte Verbindung,
die automatische Auswahl oder **Nur Dateien speichern**. Die automatische Auswahl
behält die beim Erstellen gewählte Verbindung; ohne verfügbare Verbindung werden
Dateien gespeichert. Eine benannte Verbindung erfordert `connections:view` und
eine aktive Verbindung deiner Organisation. Die Projekteinstellungen zeigen
Verbindungsnamen und Laufzeitumgebung. Projektchats nutzen ihre Dateien und standardmäßig ihren Executor, wenn Befehlswerkzeuge aktiviert sind. Editoren können mit **Sandbox ändern** ein bestehendes Projekt samt Dateien übertragen.

Ein dauerhaft gespeicherter Hintergrundauftrag kopiert Dateien und leere Ordner
in einen isolierten Arbeitsbereich, prüft Datei-Hashes und Verzeichnisstruktur und
aktiviert erst danach das Ziel. Aktive Läufe und ausstehende Entscheidungen müssen
vorher enden. Neue Läufe, Dateiänderungen und Projektbearbeitung pausieren während
der Übertragung; bestehende Dateien bleiben lesbar. Bei Fehlern bleibt die Quelle
ausgewählt. Der Fortschritt steht in den Projekteinstellungen. Erst nach geprüfter
Aktivierung wird die Quelle entfernt; ein dauerhafter Auftrag räumt den Container auf.

Grenzen: 10.000 Einträge, 64 MiB pro Datei, 1 GiB insgesamt; symbolische Links vorher
entfernen. Installierte Pakete und laufende Prozesse werden nicht kopiert. Beim Wechsel
zu gespeicherten Dateien gilt zusätzlich das Größenlimit der Plattform.

**Dateien und Codeausführung im Projekt** erklärt Speicherung, gemeinsame Nutzung
und Ausführung. Gespeicherte Dateien haben keine Shell; Kontext und Ausführung
bleiben wie oben beschrieben getrennt.

## Dateien { #files }

Im Chatbereich **Dateien** die Herkunft wählen, wenn Projektdateien und ein eigener
Agenten-Workspace existieren. Jeder nutzt seine autorisierten Endpunkte; derselbe
Pfad fällt nie auf eine andere Herkunft zurück. Standard ist das Gesprächsprojekt,
sonst der verfügbare Agenten-Workspace. Erfolgreiche, fehlgeschlagene und abgebrochene
Läufe speichern Referenzen ohne Dateikopien. Entzogener Zugriff entfernt eine Herkunft.
Run-bezogene Dateien sind vorübergehend und verschwinden beim Aufräumen; für spätere
Arbeit einen dauerhaften Scope wählen. Historische Läufe ohne Referenzen erhalten
keine erfundenen Herkünfte.

Der Reiter **Dateien** des Projekts ist der Container zum Durchsuchen: ein Baum
neben einer Ansicht, die Markdown, PDFs, Bilder, Tabellen und Code direkt öffnet.

- **Dateien hochladen** und **Ordner hochladen** legen Dateien oben im Projekt
  ab, ein Ordner behält seinen Baum. Jede Datei unterliegt dem Upload-Limit der
  Installation.
- **Neuer Ordner** legt einen leeren Ordner an, den ein Agent füllen kann.
- Im Menü **…** einer Datei oder eines Ordners kannst du umbenennen,
  verschieben oder löschen. Ziehe einen Eintrag auf einen Ordner oder auf
  **Projektdateien**, um ihn ins Stammverzeichnis zu verschieben. Ein bestehendes
  Ziel wird nie überschrieben.
- **Datei bearbeiten** öffnet vollständige UTF-8-Textdateien bis 1 MiB. Speichere
  Änderungen oder bestätige das Verwerfen vor dem Schließen. Wurde die Datei
  seit dem Öffnen geändert, wird das Speichern abgelehnt; öffne sie erneut.

Das Verzeichnis `.agenticos` und die eigenen Ordner der Plattform sind hier nicht
beschreibbar; ein Pfad außerhalb des Projekts wird abgelehnt, bevor etwas
geschrieben wird.

Ein Projekt öffnet sich auf **Dateien**. Dateien lassen sich auch irgendwo auf
dem Tab ablegen, und jede zeigt beim Hochladen ihren Fortschritt; ein leeres
Projekt ist ein Ort, die ersten abzulegen. **Chats** ist eine Tabelle der Chats
des Projekts, und **Apps** die Apps, die ein Run in einem davon veröffentlicht
hat - die, die der Leser öffnen darf. **Anweisungen** werden in Markdown mit
Quelltext und Vorschau bearbeitet, wie die eines Agents im Agent Builder, über
Name, Beschreibung und Standard-Agent des Projekts.

Lassen Sie externe Dateien auf einem Ordner fallen, um sie dort hochzuladen, oder anderswo im Reiter Dateien für das Projektstammverzeichnis. Ein kurzer Halt über einem geschlossenen Ordner öffnet ihn. Der Hinweis bleibt im Dateibereich, Zeilenaktionen behalten ihren Platz, und Ordner zeigen keine Anzahlen. Lange Upload-Warteschlangen zeigen die ersten drei Einträge und die Anzahl der übrigen. Dateitypsymbole unterscheiden Quellcode, JSON, Markup, Dokumente, Tabellen und Medien in Projekten, Chat-Anhängen, RAG und Skill-Dateien.

Die Desktop-Konsole leitet Datei-Drags an dieselben Ziele wie die Web-App weiter. Ein
Drop auf eine Datei verwendet deren Ordner; freie Flächen beider Bereiche verwenden
das Projektverzeichnis. Blobby und das Dock behalten ihre eigene Übergabe an den
Chat.

## Graphansicht { #graph-view }

Wähle im Dateiexplorer **Graph view**, um verknüpfte Markdown-Notizen zu erkunden.
Die Ansicht funktioniert für gemeinsame Projektdateien, Sandbox-Workspaces und
einen freigegebenen Desktop-Ordner. Jeder Ort hat seinen eigenen Graphen;
lokale Notizen werden nicht hochgeladen.

Der Graph öffnet sich im Vollbild mit farbigen Punkten, dünnen Verbindungen und
Beschriftungen beim Vergrößern oder Auswählen einer Notiz. Richtungspfeile und
ständige Beschriftungen sind optional. Suche, Dateien, Details und Zoom befinden
sich in schwebenden Panels. Gruppen färben Notizen standardmäßig nach Ordner,
wahlweise nach dem ersten Tag. Gruppen lassen sich ausblenden, Ordner einschließlich
Unterordner filtern und Filter zurücksetzen.

Der Dateibrowser verwendet denselben Ordnerbaum und dieselben Symbole wie andere Arbeitsbereiche. Nur indexierte
Markdown-Notizen werden Knoten; andere Dateien öffnen sich in der gemeinsamen
Vorschau. Das Verschieben von Punkten ändert nur die Ansicht, keine Dateien oder
Links. Die Vollbildsteuerung oder Escape stellt die eingebettete Ansicht wieder
her; der Zurück-Pfeil führt zu den Dateien.

Verknüpfe Notizen mit `[[notes/topic|Beschriftung]]`, Inline-Markdown-Links wie
`[Thema](topic.md)` oder Beziehungen im Frontmatter:

```yaml
---
title: Agent-Gedächtnis
aliases: [Memory]
tags: [agents, research]
related: ["[[notes/retrieval]]"]
sources: [sources/report.md]
---
```

`links`, `related` und `sources` akzeptieren Text oder Textlisten. Externe URLs
bleiben Quellenangaben. Wiki-Links verwenden exakte Pfade oder eindeutige
Dateinamen, Titel oder Aliase; doppelte Namen bleiben unaufgelöst. Markdown-Links
sind relativ zur Notiz. Codebeispiele und HTML-Kommentare werden ignoriert.

Suche nach Titeln, Pfaden, Aliasen oder Tags. Wähle einen Knoten für seine Links,
Rückverweise und unaufgelösten Verweise; **Open note** öffnet die Notiz. Gemeinsame
Projektdateien behalten **Edit file** und bestehende Berechtigungen. Die Tasten
steuern den Zoom, Ziehen auf leerem Hintergrund verschiebt den Graphen. Die
Notizliste lässt sich auch mit der Tastatur bedienen.

Die Ansicht liest Dateien alle 30 Sekunden, solange sie geöffnet ist, bei
Fensterfokus oder mit **Refresh**. Agenten aktualisieren Notizen und Links ohne
HTML neu zu erzeugen. Apps aktualisieren bereits Tabellen- und Workflow-Log-Bindings,
haben aber kein Workspace-Datei-Binding; dieser Graph liest Notizen direkt. Eine
Graphaktualisierung startet keinen Agenten zur Prüfung von Fakten oder Quellen.

Ein Scan umfasst bis zu 200 Markdown-Dateien, 256 KiB je Datei und insgesamt
8 MiB, innerhalb der Grenzen der Quelldateiliste. Beziehungen sind auf 256 je
Notiz und 2048 im gesamten Graphen begrenzt; erreichte Grenzen kennzeichnen
den Graphen ebenfalls als unvollständig. Aliase und Tags sind zusammen auf
128 Einträge je Notiz und 4096 im gesamten Graphen begrenzt. Ausgelassene oder unlesbare
Dateien, ungültiges YAML und unvollständige Listen werden angezeigt. Ein fehlender
Verweis kann eine ausgelassene Notiz bedeuten. Aktualisierungen erfolgen
periodisch; gleichzeitige Änderungen können in verschiedene Scans fallen.

## Lokale Ordner in der Desktop-App { #local-folders-in-the-desktop-app }

Der Tab **Dateien** trennt **Gemeinsame Projektdateien** und **Dieser Computer**. Ein beim Erstellen genehmigter Ordner öffnet sich auf dieser Installation automatisch; ohne Verbindung erscheinen zuerst gemeinsame Dateien. Wähle Dieser Computer, um einen Ordner zu verbinden. **Ordnereinstellungen** ändert oder trennt ihn; Pfad und Zugriffsmodus bleiben ohne wiederholtes Einrichtungsformular sichtbar.

Gemeinsame Projektdateien sind hochgeladene Kopien für Personen mit Projektzugriff. Zum Teilen einer lokalen Datei wähle diese Quelle und lade eine Kopie hoch. Die Orte synchronisieren sich nicht: Lokale Änderungen aktualisieren keine hochgeladene Kopie, und Projektfreigaben gewähren keinen Festplattenzugriff. Die **Gemeinsame Projektumgebung** unter Anweisungen ändert nur den Serverspeicher; sie verbindet oder trennt keinen persönlichen Ordner.

Der native Dialog bestätigt den Zugriff, anfangs nur lesend. Die Verbindung gehört dem aktuellen Konto und der Organisation auf diesem Computer. Das Trennen erhält Berechtigungen anderer Chats. Die Vorschau zeigt bis zu 500 Einträge, überspringt generierte Ordner wie `.git` und `node_modules` und zeigt Lesefehler ohne stillen Wechsel zu Cloud-Dateien.

Neue Desktop-Chats im Projekt übernehmen den Ordner und den genehmigten
Zugriffsmodus. Projektanweisungen gelten weiter; Sandbox-Werkzeuge arbeiten lokal
statt im gemeinsamen Container. **Arbeiten auf** überschreibt die Auswahl für
einen Chat; bestehende Unterhaltungen behalten ihre Einstellungen. Der Ordner
neben dem Eingabefeld öffnet diese Optionen. Ein nicht verfügbarer Computer oder
widerrufener Zugriff schaltet den Lauf nicht auf Cloud um. Telefone und Browser
verwenden weiter gemeinsame Dateien und erhalten keinen Fernzugriff. Antworten
und Werkzeugergebnisse im Projektchat bleiben für dessen Leser sichtbar;
berücksichtigen Sie das Publikum, bevor Sie private Dateien besprechen.

## Teilen und Berechtigungen { #sharing-and-permissions }

Ein Projekt ist privat für seinen Ersteller, bis er es teilt - mit demselben
**Teilen**-Dialog, den ein Agent oder ein Skill nutzt: Personen,
[Abteilungen](departments.md) oder die ganze Organisation, jeweils auf einer
Stufe.

| Grant-Stufe | Berechtigung    | Was sie erlaubt                                                                    |
| ----------- | --------------- | ---------------------------------------------------------------------------------- |
| `read`      | `projects:view` | Das Projekt, seine Dateien und Anweisungen sehen                                   |
| `use`       | `projects:use`  | Darin chatten; Dateien hinzufügen, bearbeiten, umbenennen, verschieben und löschen |
| `edit`      | `projects:edit` | Anweisungen und Standard-Agent ändern, teilen, löschen                             |

Rollen halten diese in den üblichen Bereichen: Owner und Admin erreichen jedes
Projekt, ein Builder arbeitet in den mit ihm geteilten und bearbeitet sie, ein
Member bearbeitet seine eigenen und arbeitet in geteilten, und ein Viewer liest,
was mit ihm geteilt wurde. Ein Chat, dessen Autor `projects:use` verliert,
erreicht die Dateien des Projekts ab dem nächsten Zug nicht mehr.

**Die Chats eines Projekts gehören seinen Mitgliedern.** Wer ein Projekt sehen
darf, liest jeden Chat darin, und wer darin arbeiten darf (`use`), setzt sie fort:
Seine Nachrichten tragen seinen Namen und sein Gesicht, sodass ein Thread, an dem
mehrere gearbeitet haben, sagt, wer was gefragt hat. Umbenennen, Archivieren und
Löschen bleibt bei der Person, die den Chat begonnen hat. Auf dem Tab **Chats**
sagt jede Zeile, wessen Chat es ist, welche Agents darin antworten, wann sich
zuletzt etwas getan hat oder wer gerade darin arbeitet, und wer ihn geöffnet hat - die letzten Gesichter, alle Namen beim Darüberfahren; wer ihn gerade
offen hat, steht vorn, mit einem grünen Punkt. Ein Chat
außerhalb eines Projekts bleibt bei seinem Autor, wie überall sonst in der Konsole.

Ein Chat eines Projekts wird nicht für sich geteilt, weder per Link noch mit einer
Person: Gelesen wird er über das Projekt, also teile das Projekt.

**Gemeinsam in einem Chat arbeiten.** In einem Chat eines Projekts können mehrere
Personen zugleich sein. Eine Leiste über dem Verlauf zeigt, wer ihn noch geöffnet
hat, und sein Besitzer kann von dort jemanden einladen. Während jemand schreibt,
sehen die anderen über dem Eingabefeld sein Gesicht und „Anna schreibt“. Eine
Frage, die eine von ihnen stellt, und die Antwort des Agent erscheinen bei allen im Chat, während sie
geschrieben werden. **Antworten** bei einer beliebigen Nachricht zitiert sie über
dem Eingabefeld, und die Antwort trägt das Zitat - auf dem Bildschirm und zum
Agent, der die Nachricht jeder Person unter ihrem Namen liest und weiß, dass im
Chat mehrere Personen sein können, sodass er weiß, wer was gefragt hat und worauf
sich „ja, mach das“ bezieht.

## Ein Projekt löschen { #deleting-a-project }

Das Löschen eines Projekts entfernt seinen Container und jede Datei darin. Seine
Chats bleiben als normale Chats außerhalb jedes Projekts erhalten - außer einem, dessen
Ersteller sein Konto gelöscht hat: Ihn erreichte nur noch das Projekt, darum geht er
mit ihm.

## Wo Projekte erscheinen { #where-projects-show-up }

- **Projekte** in der Seitenleiste listet die drei zuletzt genutzten über dem
  Link zu allen. Ein Symbol kennzeichnet Projekte mit einer noch ungelesenen Chatantwort.
- Die Chat-Liste führt jeden Chat in den Projekten, die du sehen kannst - deine
  und die deiner Kolleginnen und Kollegen - unter dem Namen des Projekts, über
  den Chats außerhalb von Projekten.
- Die Karte **Projekte** im Dashboard zeigt eine Reihe davon, mit den Chats in
  jedem.
- `GET /api/v1/projects` und seine Unterrouten gehören zur öffentlichen API, sodass
  ein Skript ein Projekt anlegen und mit Dateien füllen kann. Siehe [die
  API](api.md).


## Ein Projekt auf Kurs halten { #keep-a-project-on-track }

Wähle auf der Projektseite **Projekt auf Kurs halten**. Wähle einen veröffentlichten Agenten, den du bearbeiten darfst, prüfe Ressourcen und verbundene Konten, benenne den neuen Agenten und die Aufgabentabelle, wähle das Intervall und bestätige ausdrücklich die Veröffentlichung und den Start. Es entstehen eine private Kopie des Agenten, eine Aufgabentabelle (privat, sofern du nicht die Organisation als Zielgruppe wählst), gespeicherte Ansichten für alle Aufgaben, Board, offene Aufgaben und Blockaden sowie eine an die neue Version gebundene Routine. Der ursprüngliche Agent bleibt unverändert.

Die Routine handelt als du im Projekt und berichtet in dessen Unterhaltung. Sie liest Aufgaben, prüft Fortschritte anhand der genehmigten Quellen, aktualisiert nächste Schritte und meldet Blockaden und Fristen. Externe Nachrichten benötigen weiterhin die übliche Autorisierung. Neue Quellen, eine erneute Kontozustimmung oder ein ersetzter Projektarbeitsbereich verlangen eine neue Quellenprüfung. Verlorener Projektzugriff stoppt weitere Werkzeuge; wartende Projektbenachrichtigungen prüfen den aktuellen Zugriff des Empfängers erneut. Ein identischer Wiederholungsversuch verwendet vorhandene Ressourcen. Intervall und Quellen verwaltest du unter Routinen; die Tabelle öffnest du auf der Projektseite.

Eine geplante Unterhaltung ohne Eigentümer in einem Projekt kann von Personen mit Bearbeitungsrecht für dieses Projekt umbenannt, archiviert oder gelöscht werden. Von einer anderen Person gestartete Chats bleiben unter deren Verwaltung.


Beim Löschen eines Projekts werden auch seine Gedächtniseinträge und abgeleiteten geteilten Kopien entfernt. Registrierte Provider-Webhooks werden vor der kaskadierenden Löschung der Routinen bestmöglich entfernt. Ein nicht erreichbarer Provider wird protokolliert und blockiert die Löschung nicht.


## Verknüpfte Ressourcen { #linked-resources }

Der Tab **Ressourcen** gruppiert vorhandene Agenten, Workflows, Apps und Tabellen, ohne sie zu kopieren. Wähle **Vorhandene Ressourcen hinzufügen**, markiere ein oder mehrere Elemente und lege bei Bedarf einen verknüpften Workflow als Hauptworkflow fest. Eine Ressource kann mehreren Projekten angehören. Die Liste lässt sich nach Name oder Beschreibung durchsuchen; die Agenten- und Workflow-Kataloge bieten ebenfalls einen Projektfilter. Projektnamen sind über die Befehlspalette auffindbar.

Verknüpfungen gewähren keinen Zugriff: Jede Ressource behält ihre Berechtigungen, Versionen und Zeitpläne. Das Entfernen einer Verknüpfung oder Löschen eines Projekts lässt die ursprüngliche Ressource bestehen. Das Löschen einer Ressource entfernt ihre Verknüpfungen. Das Festlegen eines Hauptworkflows führt ihn nicht aus.

Ein Projekt öffnet standardmäßig **Chats**; ein Link mit einem bestimmten Tab öffnet weiterhin diesen Tab. Das Plus neben einem kürzlich verwendeten Projekt in der Chat-Seitenleiste startet dort einen neuen Chat. Schreibgeschützte Projekte bieten diese Aktion nicht an.
