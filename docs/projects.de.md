---
title: Projekte
seo_title: Projekte - gemeinsame Dateien und Anweisungen
description: Ein Projekt gibt laufender Arbeit einen Container mit Dateien und eine Reihe von Anweisungen, die jeder Chat darin teilt, egal welcher Agent antwortet.
source_sha: "1723f797c360"
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

## Was ein Agent im Projekt bekommt { #what-an-agent-gets-in-a-project }

Egal welcher Agent antwortet: Ein Run in einem Projekt-Chat arbeitet im
**Container des Projekts** statt in einem eigenen Workspace:

- Ein Agent ohne Sandbox bekommt eine, die des Projekts, sodass auch ein einfacher
  Chat-Agent die Dateien des Projekts lesen und schreiben kann.
- Ein Agent mit eigener Sandbox-Bindung wird in den Container des Projekts
  verlegt. Die Freigabe-Einstellungen der Bindung gehen mit, sodass ein Autor, der
  für die Shell **Immer fragen** gesetzt hat, diese Sperre behält.
- Name, Beschreibung und Anweisungen des Projekts werden nach den eigenen
  Anweisungen des Agent angefügt. Der Agent bleibt, was er ist, und arbeitet
  hieran.

Der Container ist eine [Sandbox](sandbox.md)-Session, wenn die Installation einen
Sandbox-Dienst betreibt, sodass die Dateien des Projekts auch ausgeführt und nicht
nur gelesen werden können. Ohne ihn hält das Projekt seine Dateien als
gespeicherten Workspace, der genauso liest und schreibt, aber keine Shell hat;
schreiben zwei Chats zugleich hinein, behält jeder, was er geschrieben hat, und wo
beide dieselbe Datei geändert haben, gilt der spätere Schreibvorgang.
Ein Projekt bleibt auf der Sandbox-Verbindung, auf der es angelegt wurde, darum
lässt sich diese Verbindung nicht löschen, solange ein Projekt dort Dateien hält.

Beim Erstellen wählst du unter **Projekt-Sandbox** eine registrierte Verbindung,
die automatische Auswahl oder **Nur Dateien speichern**. Die automatische Auswahl
behält die beim Erstellen gewählte Verbindung; ohne verfügbare Verbindung werden
Dateien gespeichert. Eine benannte Verbindung erfordert `connections:view` und
eine aktive Verbindung deiner Organisation. Die Projekteinstellungen zeigen
Verbindungsnamen und Laufzeitumgebung. Alle Projektchats nutzen diese Umgebung
anstelle der Agenten-Sandbox. Editoren können mit **Sandbox ändern** ein bestehendes Projekt samt Dateien übertragen.

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
und Ausführung neben der Auswahl. Das Projekt stellt Sandbox-Werkzeuge auch für
Agenten ohne eigene Sandbox bereit. Container erlauben Codeausführung; gespeicherte
Dateien haben keine Shell. Bestehende Werkzeugfreigaben gelten weiterhin.

## Dateien { #files }

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

## Teilen und Berechtigungen { #sharing-and-permissions }

Ein Projekt ist privat für seinen Ersteller, bis er es teilt - mit demselben
**Teilen**-Dialog, den ein Agent oder ein Skill nutzt: Personen,
[Abteilungen](departments.md) oder die ganze Organisation, jeweils auf einer
Stufe.

| Grant-Stufe | Berechtigung | Was sie erlaubt |
|---|---|---|
| `read` | `projects:view` | Das Projekt, seine Dateien und Anweisungen sehen |
| `use` | `projects:use` | Darin chatten; Dateien hinzufügen, bearbeiten, umbenennen, verschieben und löschen |
| `edit` | `projects:edit` | Anweisungen und Standard-Agent ändern, teilen, löschen |

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

- **Projekte** in der Seitenleiste listet die fünf zuletzt genutzten über dem
  Link zu allen.
- Die Chat-Liste führt jeden Chat in den Projekten, die du sehen kannst - deine
  und die deiner Kolleginnen und Kollegen - unter dem Namen des Projekts, über
  den Chats außerhalb von Projekten.
- Die Karte **Projekte** im Dashboard zeigt eine Reihe davon, mit den Chats in
  jedem.
- `GET /api/v1/projects` und seine Unterrouten gehören zur öffentlichen API, sodass
  ein Skript ein Projekt anlegen und mit Dateien füllen kann. Siehe [die
  API](api.md).
