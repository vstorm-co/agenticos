---
title: Projekte
seo_title: Projekte - gemeinsame Dateien und Anweisungen
description: Ein Projekt gibt laufender Arbeit einen Container mit Dateien und eine Reihe von Anweisungen, die jeder Chat darin teilt, egal welcher Agent antwortet.
source_sha: "07581e857110"
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

## Dateien { #files }

Der Reiter **Dateien** des Projekts ist der Container zum Durchsuchen: ein Baum
neben einer Ansicht, die Markdown, PDFs, Bilder, Tabellen und Code direkt öffnet.

- **Dateien hochladen** und **Ordner hochladen** legen Dateien oben im Projekt
  ab, ein Ordner behält seinen Baum. Jede Datei unterliegt dem Upload-Limit der
  Installation.
- **Neuer Ordner** legt einen leeren Ordner an, den ein Agent füllen kann.
- Der Papierkorb neben einer Datei oder einem Ordner entfernt sie - einen Ordner
  mit allem darin - für jeden Chat und Agent im Projekt.

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
| `use` | `projects:use` | Darin chatten, hochladen, Ordner anlegen, Dateien entfernen |
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
